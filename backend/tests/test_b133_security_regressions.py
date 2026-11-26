"""Batch 133 security regression tests for SEC-01 (FIX-A1) and SEC-02 (FIX-A2)."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.analysis import build_router as build_analysis_router
from app.api.org import build_router as build_org_router
from app.api.studio import build_router as build_studio_router
from app.core.access import REDACTED_ANSWER
from app.research.conversation_context import build_conversation_context
from app.research.pipeline import ResearchPipeline
from app.storage.postgres.base import Base
from app.storage.postgres.models import (
    KnowledgeSourceRecord,
    OrgMemberRecord,
    OrgSecretAccessRecord,
    OrgSourceShareRecord,
    UserRecord,
)
from app.storage.postgres.runtime import (
    PostgresConversationStore,
    PostgresRunStore,
    PostgresSourceStore,
)


def _make_sqlite_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    def _connect(conn, _):
        conn.create_function("btrim", 1, lambda v: None if v is None else v.strip())
        conn.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", _connect)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as s:
        s.add_all([
            UserRecord(user_id="an", email="an@x.vn", display_name="An", role="ADMIN", password_hash="x"),
            UserRecord(user_id="binh", email="binh@x.vn", display_name="Binh", role="USER", password_hash="x"),
            UserRecord(user_id="chi", email="chi@x.vn", display_name="Chi", role="USER", password_hash="x"),
            UserRecord(user_id="em", email="em@x.vn", display_name="Em", role="USER", password_hash="x"),
            UserRecord(user_id="giang", email="giang@x.vn", display_name="Giang", role="USER", password_hash="x"),
        ])
        s.execute(text("CREATE TABLE studio_workspaces (workspace_id TEXT PRIMARY KEY, owner_user_id TEXT, name TEXT, description TEXT, domain_pack TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.execute(text("CREATE TABLE studio_workspace_items (workspace_id TEXT, item_type TEXT, item_id TEXT, UNIQUE(item_type, item_id))"))
        s.execute(text("CREATE TABLE studio_activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id TEXT, action TEXT, target TEXT, status INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.execute(text("CREATE TABLE studio_reports (report_id TEXT PRIMARY KEY, owner_user_id TEXT, workspace_id TEXT, kind TEXT, title TEXT, payload TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.execute(text("CREATE TABLE studio_feedback (owner_user_id TEXT, run_id TEXT, rating INTEGER, note TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(owner_user_id, run_id))"))
        s.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        s.execute(text("INSERT INTO alembic_version (version_num) VALUES ('head_test')"))
    return factory


class _StubProvider:
    async def generate(self, system: str, user: str, **kwargs):
        if "REPORT" in system or "answer_report" in system:
            content = json.dumps({"title": "Báo cáo", "summary": "Tóm tắt", "sections": [{"heading": "Mục 1", "body": "Nội dung"}], "recommendations": []})
        elif "CONSISTENCY" in system or "CONTRADICTION" in system or "verdict" in user:
            content = json.dumps({"verdict": "CONTRADICTION", "reason": "Khác số tiền", "confidence": "high"})
        elif "MINDMAP" in system or "children" in user:
            content = json.dumps({
                "root": {
                    "label": "Kế hoạch",
                    "children": [
                        {"label": "Nhánh 1", "children": []},
                        {"label": "Nhánh 2", "children": []},
                    ],
                }
            })
        elif "SUMMARY" in system or "TÓM TẮT" in system.upper() or "summary" in user:
            content = json.dumps({"summary": "Tóm tắt nội dung.", "bullets": ["Ý 1"], "questions": ["Câu hỏi 1?"]})
        elif "GLOSSARY" in system or "terms" in user:
            content = json.dumps({"terms": [{"term": "sáp nhập", "definition": "gộp công ty"}]})
        elif "DESIGN" in system or "sections" in user or "points" in user:
            content = json.dumps({"summary": "Thiết kế", "design": "Chi tiết", "citations": [], "gaps": []})
        elif "TRACEABILITY" in system or "REQUIREMENT" in system or "status" in user:
            content = json.dumps({"status": "COVERED", "reason": "Có trong tài liệu", "citations": [], "flags": []})
        else:
            content = json.dumps({"ok": True, "summary": "Tóm tắt", "questions": ["Hỏi gì?"], "title": "Báo cáo", "sections": [{"heading": "A", "body": "B"}]})
        return SimpleNamespace(text=content, input_tokens=10, output_tokens=10, latency_ms=1)


def _setup_org_env(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("ALLOWED_CONDITIONS", "A,B,C")
    factory = _make_sqlite_factory()
    users = {
        "an": {"user_id": "an", "role": "ADMIN"},
        "binh": {"user_id": "binh", "role": "USER"},
        "chi": {"user_id": "chi", "role": "USER"},
        "em": {"user_id": "em", "role": "USER"},
        "giang": {"user_id": "giang", "role": "USER"},
    }

    def principal(request):
        uid = request.headers["x-user"]
        sp = request.query_params.get("space_id") or None
        return {**users[uid], "space_id": sp}

    def src_store(u):
        return PostgresSourceStore(factory, u["user_id"], u.get("space_id"))

    def pipe(u, cid=None):
        return ResearchPipeline(src_store(u), PostgresRunStore(factory, u["user_id"], cid, u.get("space_id")))

    api = FastAPI()
    api.include_router(build_org_router(current_user=lambda r: users[r.headers["x-user"]], session_factory=lambda: factory))
    api.include_router(build_studio_router(current_user=principal, owner_pipeline=pipe, session_factory=lambda: factory, owner_source_store=src_store))
    api.include_router(build_analysis_router(current_user=principal, owner_pipeline=pipe, session_factory=lambda: factory, provider_factory=lambda: _StubProvider()))
    c = TestClient(api)

    sp = c.post("/api/org/spaces", headers={"x-user": "an"}, json={"name": "OrgSec", "departments": ["KD", "KT"]}).json()["space_id"]
    deps = {d["name"]: d["department_id"] for d in c.get(f"/api/org/spaces/{sp}", headers={"x-user": "an"}).json()["departments"]}
    kd, kt = deps["KD"], deps["KT"]
    for uid, email, lvl, dep in [
        ("binh", "binh@x.vn", "MANAGER", kd),
        ("chi", "chi@x.vn", "STAFF", kd),
        ("em", "em@x.vn", "STAFF", kt),
    ]:
        inv = c.post(f"/api/org/spaces/{sp}/invites", headers={"x-user": "an"}, json={"kind": "USER", "email": email, "level": lvl, "department_id": dep}).json()["invite_id"]
        assert c.post(f"/api/org/invites/{inv}/accept", headers={"x-user": uid}).status_code == 200

    s_secret = PostgresSourceStore(factory, "an").import_text(
        "secret_plan.txt",
        "# Kế hoạch sáp nhập\nFR-01: Hệ thống phải bảo vệ kế hoạch sáp nhập tuyệt mật trị giá 500 tỷ.\n"
        "Quyết định số 01/2025/QĐ-CT có hiệu lực từ ngày 01/01/2025. Sáp nhập công ty Minh Phát.",
    )["source_id"]
    assert c.post(f"/api/org/spaces/{sp}/sources/{s_secret}/publish", headers={"x-user": "an"}, json={"classification": "SECRET"}).status_code == 200

    s_secret_2 = PostgresSourceStore(factory, "an").import_text(
        "secret_plan_v2.txt",
        "# Kế hoạch sáp nhập sửa đổi\nQuyết định số 02/2025/QĐ-CT thay thế Quyết định số 01/2025/QĐ-CT.\n"
        "Hệ thống phải bảo vệ kế hoạch sáp nhập tuyệt mật trị giá 700 tỷ. Sáp nhập công ty Minh Phát.",
    )["source_id"]
    assert c.post(f"/api/org/spaces/{sp}/sources/{s_secret_2}/publish", headers={"x-user": "an"}, json={"classification": "SECRET"}).status_code == 200

    s_restr = PostgresSourceStore(factory, "chi").import_text(
        "kd_restricted.txt",
        "Điều 1: Ngân sách phòng KD là 100 triệu đồng.",
    )["source_id"]
    assert c.post(f"/api/org/spaces/{sp}/sources/{s_restr}/publish", headers={"x-user": "chi"}, json={"classification": "RESTRICTED", "department_id": kd}).status_code == 200

    return factory, c, sp, kd, kt, s_secret, s_secret_2, s_restr


def _secret_audit_rows(factory, source_id: str) -> list[OrgSecretAccessRecord]:
    with factory() as db:
        return list(db.scalars(
            select(OrgSecretAccessRecord)
            .where(OrgSecretAccessRecord.source_id == source_id)
            .order_by(OrgSecretAccessRecord.access_id)
        ).all())


# ---------------- SEC-01: Audit logging & ACL across studio.py + analysis.py ----------------

def test_sec01_all_secret_reading_endpoints_record_audit_and_enforce_acl(monkeypatch):
    factory, c, sp, _, _, s_secret, s_secret_2, _ = _setup_org_env(monkeypatch)

    # Save a run referencing s_secret for /grounding and /answer-report
    run_store_an = PostgresRunStore(factory, "an", space_id=sp)
    run_store_an.save({
        "run_id": "run_secret_1",
        "created_at": "2026-11-25T00:00:00Z",
        "condition": "A",
        "query": "Kế hoạch sáp nhập trị giá bao nhiêu?",
        "status": "COMPLETED",
        "answer": f"Trị giá 500 tỷ [{s_secret}_c0000].",
        "task_results": [{"citations": [f"{s_secret}_c0000"], "evidence_ids": [f"{s_secret}_c0000"]}],
    })

    # Unauthorized user (em, STAFF in KT) must NEVER read SECRET content or write audit rows
    em_ret = c.post(f"/api/studio/retrieval-test?space_id={sp}", headers={"x-user": "em"}, json={"query": "sáp nhập", "source_ids": [s_secret]})
    assert em_ret.status_code == 200 and em_ret.json()["results"] == []
    assert c.post(f"/api/studio/req-quality?space_id={sp}", headers={"x-user": "em"}, json={"source_id": s_secret}).status_code == 404
    assert c.post(f"/api/studio/traceability/extract?space_id={sp}", headers={"x-user": "em"}, json={"source_id": s_secret}).status_code == 404
    assert c.post(f"/api/studio/profile/local?space_id={sp}", headers={"x-user": "em"}, json={"source_id": s_secret}).status_code == 404
    assert c.post(f"/api/studio/mindmap?space_id={sp}", headers={"x-user": "em"}, json={"source_id": s_secret, "mode": "outline"}).status_code == 404
    assert c.post(f"/api/studio/related?space_id={sp}", headers={"x-user": "em"}, json={"source_id": s_secret}).status_code == 404
    assert c.post(f"/api/studio/compare?space_id={sp}", headers={"x-user": "em"}, json={"message": "sáp nhập", "conditions": ["A"], "source_ids": [s_secret]}).status_code == 404
    assert _secret_audit_rows(factory, s_secret) == []

    # Authorized user (an, EXECUTIVE): EVERY route reading SECRET content must increment ASK audit log
    checks = [
        ("retrieval-test", lambda: c.post(f"/api/studio/retrieval-test?space_id={sp}", headers={"x-user": "an"}, json={"query": "sáp nhập", "source_ids": [s_secret]})),
        ("compare", lambda: c.post(f"/api/studio/compare?space_id={sp}", headers={"x-user": "an"}, json={"message": "Kế hoạch sáp nhập?", "conditions": ["A"], "source_ids": [s_secret]})),
        ("req-quality", lambda: c.post(f"/api/studio/req-quality?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret})),
        ("traceability/extract", lambda: c.post(f"/api/studio/traceability/extract?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret, "mode": "coded"})),
        ("traceability/check", lambda: c.post(f"/api/studio/traceability/check?space_id={sp}", headers={"x-user": "an"}, json={"requirement": {"req_id": "FR-01", "title": "Bảo vệ kế hoạch sáp nhập"}, "source_ids": [s_secret]})),
        ("design/section", lambda: c.post(f"/api/studio/design/section?space_id={sp}", headers={"x-user": "an"}, json={"request": "Thiết kế bảo vệ dữ liệu sáp nhập", "domain": "security", "points": [{"id": "P1", "text": "Bảo vệ kế hoạch", "domain": "security"}], "source_ids": [s_secret]})),
        ("consistency/candidates", lambda: c.post(f"/api/studio/consistency/candidates?space_id={sp}", headers={"x-user": "an"}, json={"source_ids": [s_secret, s_secret_2]})),
        ("consistency/judge", lambda: c.post(f"/api/studio/consistency/judge?space_id={sp}", headers={"x-user": "an"}, json={"a": {"source_name": "secret_plan.txt", "text": "Trị giá 500 tỷ.", "source_id": s_secret}, "b": {"source_name": "secret_plan_v2.txt", "text": "Trị giá 700 tỷ.", "source_id": s_secret_2}})),
        ("eval/run", lambda: c.post(f"/api/studio/eval/run?space_id={sp}", headers={"x-user": "an"}, json={"question": "Kế hoạch sáp nhập trị giá bao nhiêu?", "condition": "A", "source_ids": [s_secret]})),
        ("grounding", lambda: c.post(f"/api/studio/grounding?space_id={sp}", headers={"x-user": "an"}, json={"run_id": "run_secret_1"})),
        ("profile/local", lambda: c.post(f"/api/studio/profile/local?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret})),
        ("profile/masked", lambda: c.post(f"/api/studio/profile/masked?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret})),
        ("profile/summary", lambda: c.post(f"/api/studio/profile/summary?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret})),
        ("profile/questions", lambda: c.post(f"/api/studio/profile/questions?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret})),
        ("profile/glossary", lambda: c.post(f"/api/studio/profile/glossary?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret})),
        ("compare-docs", lambda: c.post(f"/api/studio/compare-docs?space_id={sp}", headers={"x-user": "an"}, json={"old_source_id": s_secret, "new_source_id": s_secret_2, "summarize": False})),
        ("mindmap", lambda: c.post(f"/api/studio/mindmap?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret, "mode": "outline"})),
        ("related", lambda: c.post(f"/api/studio/related?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret})),
        ("answer-report", lambda: c.post(f"/api/studio/answer-report?space_id={sp}", headers={"x-user": "an"}, json={"run_id": "run_secret_1"})),
        ("library-quality", lambda: c.get(f"/api/studio/library-quality?space_id={sp}", headers={"x-user": "an"})),
    ]

    missing_audit: list[str] = []
    for name, call in checks:
        before = len(_secret_audit_rows(factory, s_secret))
        resp = call()
        assert resp.status_code == 200, f"{name} failed with {resp.status_code}: {resp.text}"
        rows = _secret_audit_rows(factory, s_secret)
        if len(rows) <= before:
            missing_audit.append(name)
        else:
            assert rows[-1].action == "ASK" and rows[-1].user_id == "an"
            assert rows[-1].space_id == sp

    assert not missing_audit, f"Routes missing SECRET audit log: {missing_audit}"


def test_sec01_file_mode_session_factory_none_does_not_crash():
    from app.core.types import SourceChunk

    chunk1 = SourceChunk("s1_c0000", "s1", "doc1.txt", "Nội dung FR-01: phải mã hóa dữ liệu.", 0)
    chunk2 = SourceChunk("s2_c0000", "s2", "doc2.txt", "Nội dung FR-02: thay thế bản cũ.", 0)

    class _Store:
        def chunks(self, ids=None):
            if ids is None:
                return [chunk1, chunk2]
            return [c for c in (chunk1, chunk2) if c.source_id in ids]

        def list_sources(self):
            return [{"source_id": "s1", "source_name": "doc1.txt"}, {"source_id": "s2", "source_name": "doc2.txt"}]

    class _Pipe:
        retrieval_backend = "lexical"
        source_store = _Store()

        def _retrieve_candidates(self, query, chunks, *, top_k, min_score, source_ids, fallback_trace=None):
            return chunks[:top_k]

        async def run(self, message, condition, source_ids=None, **kwargs):
            return {"run_id": "r1", "condition": condition, "status": "COMPLETE", "answer": "ok", "task_results": []}

    app = FastAPI()
    app.include_router(build_studio_router(current_user=lambda r: {"user_id": "u1", "role": "USER"}, owner_pipeline=lambda u, *a: _Pipe(), session_factory=lambda: None))
    app.include_router(build_analysis_router(current_user=lambda r: {"user_id": "u1", "role": "USER"}, owner_pipeline=lambda u, *a: _Pipe(), session_factory=lambda: None, provider_factory=lambda: _StubProvider()))
    c = TestClient(app)

    assert c.post("/api/studio/retrieval-test", json={"query": "mã hóa", "source_ids": ["s1"]}).status_code == 200
    assert c.post("/api/studio/compare", json={"message": "mã hóa", "conditions": ["A"], "source_ids": ["s1"]}).status_code == 200
    assert c.post("/api/studio/req-quality", json={"source_id": "s1"}).status_code == 200
    assert c.post("/api/studio/traceability/extract", json={"source_id": "s1"}).status_code == 200
    assert c.post("/api/studio/profile/local", json={"source_id": "s1"}).status_code == 200
    assert c.post("/api/studio/mindmap", json={"source_id": "s1", "mode": "outline"}).status_code == 200
    assert c.post("/api/studio/related", json={"source_id": "s1"}).status_code == 200
    assert c.get("/api/studio/library-quality").status_code == 200
    assert c.post("/api/studio/consistency/candidates", json={"source_ids": ["s1", "s2"]}).status_code == 200


# ---------------- SEC-02: SkillCard & run_id=None redaction ----------------

def test_sec02_skill_card_and_historical_messages_redacted_on_demotion(monkeypatch):
    factory, c, sp, kd, _, _, _, s_restr = _setup_org_env(monkeypatch)

    # Binh (MANAGER in KD) sees s_restr initially
    conv_store_b = PostgresConversationStore(factory, "binh", sp)
    cid_b = conv_store_b.create("Ngân sách KD")["conversation_id"]
    PostgresRunStore(factory, "binh", cid_b, sp).save({
        "run_id": "run_normal_1",
        "created_at": "2026-11-25T00:00:00Z",
        "condition": "C",
        "query": "Ngân sách KD là bao nhiêu?",
        "status": "COMPLETED",
        "answer": "Ngân sách phòng KD là 100 triệu đồng.",
        "task_results": [{"citations": [f"{s_restr}_c0000"], "evidence_ids": [f"{s_restr}_c0000"]}],
    })
    conv_store_b.add_message(cid_b, "USER", "Ngân sách KD là bao nhiêu?")
    conv_store_b.add_message(cid_b, "ASSISTANT", "Ngân sách phòng KD là 100 triệu đồng.", run_id="run_normal_1")

    # Historical SkillCard saved with run_id=None referencing s_restr via source_id and chunk_id
    conv_store_b.add_message(cid_b, "USER", "Kiểm tra điều kiện ngân sách")
    conv_store_b.add_message(
        cid_b,
        "ASSISTANT",
        f"Ngân sách phòng KD là 100 triệu đồng.\n\n<!--skill-card:{{\"skill\":\"conditions\",\"source_id\":\"{s_restr}\",\"chunk_id\":\"{s_restr}_c0000\"}}-->",
        run_id=None,
    )

    before = conv_store_b.get(cid_b)["messages"]
    assert before[1]["content"] == "Ngân sách phòng KD là 100 triệu đồng."
    assert "100 triệu đồng" in before[3]["content"]

    # Demote Binh MANAGER -> STAFF -> loses access to s_restr (RESTRICTED owned by chi)
    assert c.patch(
        f"/api/org/spaces/{sp}/members/binh",
        headers={"x-user": "an"},
        json={"level": "STAFF", "department_id": kd, "is_owner": False},
    ).status_code == 200

    after = conv_store_b.get(cid_b)["messages"]
    assert after[0]["content"] == "Ngân sách KD là bao nhiêu?"  # USER question preserved
    assert after[1]["content"] == REDACTED_ANSWER  # normal message redacted
    assert after[2]["content"] == "Kiểm tra điều kiện ngân sách"  # USER question preserved
    assert after[3]["content"] == REDACTED_ANSWER  # SkillCard with run_id=None MUST be redacted!
    assert "100 triệu" not in build_conversation_context(conv_store_b.get(cid_b)).text


def test_sec02_skill_card_redacted_on_share_revocation_and_via_main_endpoint(monkeypatch, tmp_path):
    # Test through main.py's save_skill_card & get_conversation endpoints + share revocation
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("PROVIDER", "fake")
    factory, _, sp, _, _, s_secret, _, _ = _setup_org_env(monkeypatch)

    import app.main as main_mod

    # Rebind main_mod stores to our isolated SQLite factory for this test without touching production DB
    monkeypatch.setattr(main_mod, "STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(main_mod.app.state, "storage_backend", "postgres")
    monkeypatch.setattr(main_mod.app.state, "session_factory", factory)

    tokens = {
        "tok_em": {"user_id": "em", "role": "USER"},
        "tok_an": {"user_id": "an", "role": "ADMIN"},
    }

    class _TestAuthStore:
        def resolve(self, token):
            if token not in tokens:
                raise main_mod.InvalidSessionError("invalid")
            return tokens[token]

    monkeypatch.setattr(main_mod.app.state, "auth_store", _TestAuthStore())
    client = TestClient(main_mod.app)

    # Share s_secret directly with em
    with factory.begin() as db:
        share = OrgSourceShareRecord(share_id="sh_em_secret", source_id=s_secret, target_user_id="em")
        db.add(share)

    # Em saves a SkillCard referencing s_secret via source_ids (even when card body has no src_...)
    resp = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "question": "Tóm tắt sáp nhập?",
            "summary": "Thương vụ trị giá 500 tỷ.",
            "card": {"skill": "approver", "data": {"approver": "Ban giám đốc"}},
            "source_ids": [s_secret],
        },
    )
    assert resp.status_code == 200
    cid = resp.json()["conversation_id"]

    # Also save a SkillCard whose card payload embeds chunk_id (no top-level source_ids)
    resp2 = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "conversation_id": cid,
            "question": "Điều kiện sáp nhập?",
            "summary": "Cần Ban giám đốc duyệt 500 tỷ.",
            "card": {"skill": "conditions", "data": {"evidence": [{"chunk_id": f"{s_secret}_c0000"}]}},
        },
    )
    assert resp2.status_code == 200

    # Before revocation, Em can see both SkillCards
    before = client.get(f"/api/conversations/{cid}?space_id={sp}", headers={"Authorization": "Bearer tok_em"}).json()["messages"]
    assert "500 tỷ" in before[1]["content"]
    assert "500 tỷ" in before[3]["content"]

    # Revoke Em's share
    with factory.begin() as db:
        db.delete(db.get(OrgSourceShareRecord, "sh_em_secret"))

    # After revocation, BOTH SkillCards are redacted, USER questions remain visible
    after = client.get(f"/api/conversations/{cid}?space_id={sp}", headers={"Authorization": "Bearer tok_em"}).json()["messages"]
    assert after[0]["content"] == "Tóm tắt sáp nhập?"
    assert after[1]["content"] == REDACTED_ANSWER
    assert after[2]["content"] == "Điều kiện sáp nhập?"
    assert after[3]["content"] == REDACTED_ANSWER

    # Also after revocation, saving a SkillCard with unauthorized source_ids is rejected (404)
    denied = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "question": "Hỏi lại?",
            "summary": "Tóm tắt",
            "card": {"skill": "approver", "data": {}},
            "source_ids": [s_secret],
        },
    )
    assert denied.status_code == 404


def test_sec02_personal_conversations_are_not_redacted(monkeypatch):
    factory, _, _, _, _, s_secret, _, _ = _setup_org_env(monkeypatch)
    # Personal conversation (space_id=None) containing a SkillCard referencing an org/deleted src_... ID
    personal_conv = PostgresConversationStore(factory, "em", space_id=None)
    cid = personal_conv.create("Personal notes")["conversation_id"]
    personal_conv.add_message(cid, "USER", "Kiểm tra ghi chú cá nhân")
    skill_content = f"Kết quả cá nhân.\n\n<!--skill-card:{{\"source_id\":\"{s_secret}\",\"note\":\"kept\"}}-->"
    personal_conv.add_message(cid, "ASSISTANT", skill_content, run_id=None)

    got = personal_conv.get(cid)
    assert got["messages"][1]["content"] == skill_content
    assert got["messages"][1]["content"] != REDACTED_ANSWER
