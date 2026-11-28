"""Batch 133.1 Independent Safety Verification & Targeted Regression Tests.

Covers:
- SEC-02: SkillCard provenance, card-ref forging/omission bypasses, demotion, revocation, personal vs org.
- SEC-01: Synthetic audit semantics (read vs hit, omitted source_ids, exception pre-response, fail-open, non-SECRET).
- AI-GUARD-01: Strict pre-flight hard provider-call limit across extractor/planner/worker/retry/parallel/synth/review.
- Research Mode A/B/C preservation (`product_mode=False`) & `/compare`, `/eval/run` FairQueue latency isolation.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.analysis import build_router as build_analysis_router
from app.api.org import build_router as build_org_router
from app.api.studio import build_router as build_studio_router
from app.core.access import REDACTED_ANSWER
from app.core.secret_audit import log_secret_access
from app.core.types import ProviderResult, Usage
from app.providers.fake import FakeProvider
from app.research.conversation_context import build_conversation_context
from app.research.pipeline import ResearchPipeline
from app.research.registry import OFFICE_PACK
from app.research.run_queue import FairQueue, product_runs
from app.storage.postgres.base import Base
from app.storage.postgres.models import (
    OrgSecretAccessRecord,
    OrgSourceShareRecord,
    UserRecord,
)
from app.storage.postgres.runtime import (
    PostgresConversationStore,
    PostgresRunStore,
    PostgresSourceStore,
)
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


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
        return SimpleNamespace(
            text=json.dumps({
                "status": "COVERED",
                "reason": "ok",
                "citations": [],
                "flags": [],
                "verdict": "CONTRADICTION",
                "summary": "Tóm tắt",
                "design": "Chi tiết",
                "gaps": [],
                "title": "Báo cáo",
                "sections": [{"heading": "A", "body": "B"}],
                "recommendations": [],
            }),
            input_tokens=5,
            output_tokens=5,
            latency_ms=1,
        )


def _setup_org_env(monkeypatch, *, provider_factory=None):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("ALLOWED_CONDITIONS", "A,B,C,C-P,C-N,C-O")
    factory = _make_sqlite_factory()
    users = {
        "an": {"user_id": "an", "role": "ADMIN"},
        "binh": {"user_id": "binh", "role": "USER"},
        "chi": {"user_id": "chi", "role": "USER"},
        "em": {"user_id": "em", "role": "USER"},
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
    api.include_router(build_analysis_router(current_user=principal, owner_pipeline=pipe, session_factory=lambda: factory, provider_factory=provider_factory or (lambda: _StubProvider())))
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

    s_company = PostgresSourceStore(factory, "an").import_text(
        "company_policy.txt",
        "Quy định chung công ty: Nhân viên thử việc tối đa 60 ngày và nghỉ phép 12 ngày.",
    )["source_id"]
    assert c.post(f"/api/org/spaces/{sp}/sources/{s_company}/publish", headers={"x-user": "an"}, json={"classification": "COMPANY"}).status_code == 200

    s_secret = PostgresSourceStore(factory, "an").import_text(
        "secret_merger.txt",
        "Kế hoạch sáp nhập tuyệt mật trị giá 500 tỷ với đối tác Minh Phát.",
    )["source_id"]
    assert c.post(f"/api/org/spaces/{sp}/sources/{s_secret}/publish", headers={"x-user": "an"}, json={"classification": "SECRET"}).status_code == 200

    s_restr = PostgresSourceStore(factory, "chi").import_text(
        "kd_budget.txt",
        "Điều 1: Ngân sách phòng KD là 100 triệu đồng.",
    )["source_id"]
    assert c.post(f"/api/org/spaces/{sp}/sources/{s_restr}/publish", headers={"x-user": "chi"}, json={"classification": "RESTRICTED", "department_id": kd}).status_code == 200

    return factory, c, sp, kd, kt, s_company, s_secret, s_restr


def _bind_main_app(monkeypatch, tmp_path, factory):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("PROVIDER", "fake")
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(main_mod.app.state, "storage_backend", "postgres")
    monkeypatch.setattr(main_mod.app.state, "session_factory", factory)
    tokens = {
        "tok_an": {"user_id": "an", "role": "ADMIN"},
        "tok_binh": {"user_id": "binh", "role": "USER"},
        "tok_em": {"user_id": "em", "role": "USER"},
    }

    class _Auth:
        def resolve(self, tok):
            if tok not in tokens:
                raise main_mod.InvalidSessionError("invalid")
            return tokens[tok]

    monkeypatch.setattr(main_mod.app.state, "auth_store", _Auth())
    return TestClient(main_mod.app)


def _secret_rows(factory, source_id: str):
    with factory() as db:
        return list(db.scalars(
            select(OrgSecretAccessRecord)
            .where(OrgSecretAccessRecord.source_id == source_id)
            .order_by(OrgSecretAccessRecord.access_id)
        ).all())


# ==============================================================================
# TEST 1: SEC-02 (SkillCard provenance & redaction - 7 scenarios)
# ==============================================================================

def test_sec02_case1_to_6_matrix_and_zero_provenance_policy_gap(monkeypatch, tmp_path):
    factory, org_client, sp, kd, _, s_company, s_secret, s_restr = _setup_org_env(monkeypatch)
    client = _bind_main_app(monkeypatch, tmp_path, factory)

    # Share s_secret with em temporarily (Case 1 & Case 5)
    with factory.begin() as db:
        db.add(OrgSourceShareRecord(share_id="sh1", source_id=s_secret, target_user_id="em"))

    # Case 1: valid source_ids saved -> redacted on revoke
    r1 = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "question": "Thương vụ sáp nhập?",
            "summary": "Trị giá 500 tỷ.",
            "card": {"skill": "approver", "data": {"approver": "BGĐ"}},
            "source_ids": [s_secret],
        },
    )
    assert r1.status_code == 200
    cid_em = r1.json()["conversation_id"]

    # Case 3: No source_ids AND no src_... refs in card (like current FE /api/conversations/skill-card callers)
    r3 = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "conversation_id": cid_em,
            "question": "Legacy quiz card?",
            "summary": "Kết quả từ dữ liệu mật nhưng không có ref.",
            "card": {"skill": "quiz", "data": {"questions": [{"q": "Trị giá?", "a": "500 tỷ"}]}},
        },
    )
    assert r3.status_code == 200

    # Revoke Em's share
    with factory.begin() as db:
        db.delete(db.get(OrgSourceShareRecord, "sh1"))

    msgs_after_revoke = client.get(f"/api/conversations/{cid_em}?space_id={sp}", headers={"Authorization": "Bearer tok_em"}).json()["messages"]
    assert msgs_after_revoke[1]["content"] == REDACTED_ANSWER  # Case 1 & 5 redacted
    # Case 3 (legacy zero-provenance without refs/source_ids): remains visible under current metadata-less schema -> OWNER_POLICY_DECISION_REQUIRED
    assert "500 tỷ" in msgs_after_revoke[3]["content"]

    # Case 2 & Case 4: Binh (MANAGER -> STAFF demotion) redacts run_id=None legacy content refs + strips context
    conv_b = PostgresConversationStore(factory, "binh", sp)
    cid_b = conv_b.create("KD")["conversation_id"]
    conv_b.add_message(cid_b, "USER", "Kiểm tra ngân sách KD")
    conv_b.add_message(cid_b, "ASSISTANT", f"Ngân sách 100 triệu.\n\n<!--skill-card:{{\"chunk_id\":\"{s_restr}_c0000\"}}-->", run_id=None)
    assert org_client.patch(f"/api/org/spaces/{sp}/members/binh", headers={"x-user": "an"}, json={"level": "STAFF", "department_id": kd, "is_owner": False}).status_code == 200
    b_got = conv_b.get(cid_b)
    assert b_got["messages"][1]["content"] == REDACTED_ANSWER
    assert "100 triệu" not in build_conversation_context(b_got).text

    # Case 6: Personal non-org conversation never redacted
    conv_p = PostgresConversationStore(factory, "em", None)
    cid_p = conv_p.create("Personal")["conversation_id"]
    personal_msg = f"Cá nhân.\n\n<!--skill-card:{{\"source_id\":\"{s_secret}\"}}-->"
    conv_p.add_message(cid_p, "ASSISTANT", personal_msg, run_id=None)
    assert conv_p.get(cid_p)["messages"][0]["content"] == personal_msg


def test_sec02_case7_incomplete_or_forged_client_source_ids_blocked(monkeypatch, tmp_path):
    factory, _, sp, _, _, s_company, s_secret, _ = _setup_org_env(monkeypatch)
    client = _bind_main_app(monkeypatch, tmp_path, factory)

    # 7a: Em only has access to s_company, tries to spoof source_ids=[s_company] while embedding unauthorized s_secret in card
    r_incomplete_unauth = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "question": "Giả mạo source_ids?",
            "summary": "Thương vụ 500 tỷ.",
            "card": {"skill": "conditions", "data": {"chunk_id": f"{s_secret}_c0000"}},
            "source_ids": [s_company],
        },
    )
    assert r_incomplete_unauth.status_code == 404

    # 7b: Em omits source_ids while embedding unauthorized s_secret in card
    r_omit_unauth = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "question": "Bỏ qua source_ids?",
            "summary": "Thương vụ 500 tỷ.",
            "card": {"skill": "conditions", "data": {"source_id": s_secret}},
        },
    )
    assert r_omit_unauth.status_code == 404

    # 7c: Forged nonexistent/foreign src_0000... ID in card or source_ids rejected
    r_forged = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "question": "ID giả?",
            "summary": "Tóm tắt.",
            "card": {"skill": "conditions", "data": {"source_id": "src_deadbeefdeadbeef"}},
            "source_ids": [s_company],
        },
    )
    assert r_forged.status_code == 404

    # 7d: Authorized incomplete source_ids=[s_company] + s_secret ref inside card -> after s_secret revoked, MUST redact
    with factory.begin() as db:
        db.add(OrgSourceShareRecord(share_id="sh7d", source_id=s_secret, target_user_id="em"))
    r_partial_auth = client.post(
        f"/api/conversations/skill-card?space_id={sp}",
        headers={"Authorization": "Bearer tok_em"},
        json={
            "question": "Gộp thông tin?",
            "summary": "Thử việc 60 ngày và sáp nhập 500 tỷ.",
            "card": {"skill": "conditions", "data": {"chunk_id": f"{s_secret}_c0000"}},
            "source_ids": [s_company],
        },
    )
    assert r_partial_auth.status_code == 200
    cid7d = r_partial_auth.json()["conversation_id"]
    with factory.begin() as db:
        db.delete(db.get(OrgSourceShareRecord, "sh7d"))
    msgs7d = client.get(f"/api/conversations/{cid7d}?space_id={sp}", headers={"Authorization": "Bearer tok_em"}).json()["messages"]
    assert msgs7d[1]["content"] == REDACTED_ANSWER


# ==============================================================================
# TEST 2: SEC-01 (SECRET access audit - 7 synthetic cases)
# ==============================================================================

def test_sec01_all_7_synthetic_audit_cases(monkeypatch):
    factory, c, sp, _, _, s_company, s_secret, _ = _setup_org_env(monkeypatch)

    # Case 7: COMPANY-only doc never writes to org_secret_access
    assert c.post(f"/api/studio/retrieval-test?space_id={sp}", headers={"x-user": "an"}, json={"query": "thử việc 60 ngày", "source_ids": [s_company]}).status_code == 200
    assert _secret_rows(factory, s_company) == []
    assert _secret_rows(factory, s_secret) == []

    # Case 2a: Authorized retrieval-test with source_ids=None and 0 hits -> 0 SECRET audit rows
    r_zero_unscoped = c.post(f"/api/studio/retrieval-test?space_id={sp}", headers={"x-user": "an"}, json={"query": "khong_co_tu_khoa_nao_xyz123"})
    assert r_zero_unscoped.status_code == 200 and r_zero_unscoped.json()["results"] == []
    assert _secret_rows(factory, s_secret) == []

    # Case 2b: Authorized retrieval-test with explicit source_ids=[s_secret] and 0 hits -> logs scoped read (1 ASK row via studio.py:136)
    r_zero_scoped = c.post(f"/api/studio/retrieval-test?space_id={sp}", headers={"x-user": "an"}, json={"query": "khong_co_tu_khoa_nao_xyz123", "source_ids": [s_secret]})
    assert r_zero_scoped.status_code == 200 and r_zero_scoped.json()["results"] == []
    assert len(_secret_rows(factory, s_secret)) == 1

    # Case 3: Omitted source_ids=None -> matches s_company only => 0 extra SECRET rows; matches s_secret => +1 SECRET row
    r_omit_co = c.post(f"/api/studio/retrieval-test?space_id={sp}", headers={"x-user": "an"}, json={"query": "thử việc 60 ngày", "top_k": 1})
    assert r_omit_co.status_code == 200
    assert len(_secret_rows(factory, s_secret)) == 1

    r_omit_sec = c.post(f"/api/studio/retrieval-test?space_id={sp}", headers={"x-user": "an"}, json={"query": "sáp nhập Minh Phát 500 tỷ", "top_k": 3})
    assert r_omit_sec.status_code == 200 and len(r_omit_sec.json()["results"]) >= 1
    assert len(_secret_rows(factory, s_secret)) == 2

    # Case 1: Explicit authorized read of SECRET increments audit
    assert c.post(f"/api/studio/req-quality?space_id={sp}", headers={"x-user": "an"}, json={"source_id": s_secret}).status_code == 200
    assert len(_secret_rows(factory, s_secret)) == 3

    # Case 6: Unauthorized user blocked (0 hits / 404), 0 audit rows added
    assert c.post(f"/api/studio/retrieval-test?space_id={sp}", headers={"x-user": "em"}, json={"query": "sáp nhập 500 tỷ", "source_ids": [s_secret]}).json()["results"] == []
    assert c.post(f"/api/studio/req-quality?space_id={sp}", headers={"x-user": "em"}, json={"source_id": s_secret}).status_code == 404
    assert len(_secret_rows(factory, s_secret)) == 3

    # Case 5: Simulated DB error during audit write -> fail-open returns 0 (Owner decision gate)
    class _BrokenSession:
        def __call__(self): raise RuntimeError("audit db down")
    assert log_secret_access(_BrokenSession(), "an", [s_secret], "ASK") == 0


def test_sec01_case4_exception_before_response_semantics(monkeypatch):
    class _ExplodingProvider:
        async def generate(self, system: str, user: str, **kwargs):
            raise RuntimeError("boom_before_response")

    factory, c, sp, _, _, _, s_secret, _ = _setup_org_env(
        monkeypatch, provider_factory=lambda: _ExplodingProvider()
    )
    api = c.app
    no_raise_c = TestClient(api, raise_server_exceptions=False)
    # 1) analysis.py /consistency/judge audits at read/model-evidence dispatch stage (BEFORE _llm),
    # so even when provider raises HTTP 500, model-evidence access IS recorded.
    resp = no_raise_c.post(
        f"/api/studio/consistency/judge?space_id={sp}",
        headers={"x-user": "an"},
        json={
            "a": {"source_name": "secret.txt", "text": "500 tỷ", "source_id": s_secret},
            "b": {"source_name": "secret2.txt", "text": "700 tỷ", "source_id": s_secret},
        },
    )
    assert resp.status_code == 500
    assert len(_secret_rows(factory, s_secret)) == 1

    # 2) Post-run routes (/eval/run) audit at response assembly stage AFTER pipeline.run returns;
    # unhandled exception inside pipeline before log_secret_access leaves audit count unchanged.
    with patch("app.research.pipeline.ResearchPipeline.run", side_effect=RuntimeError("unhandled_eval_crash")):
        resp_eval = no_raise_c.post(
            f"/api/studio/eval/run?space_id={sp}",
            headers={"x-user": "an"},
            json={"question": "Kế hoạch sáp nhập?", "condition": "A", "source_ids": [s_secret]},
        )
    assert resp_eval.status_code == 500
    assert len(_secret_rows(factory, s_secret)) == 1


# ==============================================================================
# TEST 3: AI-GUARD-01 (Hard provider-call limit - 8 cases with independent counter)
# ==============================================================================

def _make_pipe(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("CONTEXT_POLICY", "char_proxy")
    monkeypatch.setenv("MAX_RUN_TOKENS", "50000")
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    src = SourceStore(str(tmp_path / "src"))
    src.import_text("spec.md", "API dùng REST JWT. Database dùng PostgreSQL. Authentication bắt buộc MFA.")
    return ResearchPipeline(src, RunStore(str(tmp_path / "runs")))


class _CountingFake(FakeProvider):
    def __init__(self, *, fail_system_prefix: str | None = None, delay_system_prefix: str | None = None, delay_s: float = 0.0, usage_tokens: int = 10):
        self.calls: list[str] = []
        self.fail_system_prefix = fail_system_prefix
        self.delay_system_prefix = delay_system_prefix
        self.delay_s = delay_s
        self.usage_tokens = usage_tokens

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        self.calls.append(system.splitlines()[0][:60])
        if self.delay_system_prefix and system.startswith(self.delay_system_prefix):
            await asyncio.sleep(self.delay_s)
        if self.fail_system_prefix and system.startswith(self.fail_system_prefix):
            raise TimeoutError("simulated upstream failure")
        res = await super().generate(system=system, user=user)
        res.usage = Usage(self.usage_tokens, self.usage_tokens)
        return res


def test_ai_guard01_case1_limit_1_blocks_after_first_call(tmp_path, monkeypatch):
    pipe = _make_pipe(tmp_path, monkeypatch, MAX_RUN_LLM_CALLS="1")
    prov = _CountingFake()
    with patch("app.research.pipeline.get_provider", return_value=prov):
        run = asyncio.run(pipe.run("Review API architecture, database schema, and authentication security", "C", provider_name="fake"))
    assert len(prov.calls) == 1
    assert run["status"] == "FAILED"
    assert any(e["stage"] == "run_budget_exceeded" and e.get("reason") == "max_llm_calls" for e in run["events"])


def test_ai_guard01_case2_planner_consumes_budget_zero_workers(tmp_path, monkeypatch):
    pipe = _make_pipe(tmp_path, monkeypatch, MAX_RUN_LLM_CALLS="2")
    prov = _CountingFake()
    with patch("app.research.pipeline.get_provider", return_value=prov):
        run = asyncio.run(pipe.run("Review API architecture, database schema, and authentication security", "C", provider_name="fake"))
    assert len(prov.calls) <= 2
    assert not any(c.startswith("WORKER.") for c in prov.calls)
    assert run["status"] == "FAILED"
    assert any(e["stage"] == "run_budget_exceeded" and e.get("reason") == "max_llm_calls" for e in run["events"])


def test_ai_guard01_case3_worker_post_budget_stops_and_skips_synthesis(tmp_path, monkeypatch):
    # 1 extraction + 1 planner + 1 worker = 3 calls; 2nd worker + synthesis MUST NOT fire
    pipe = _make_pipe(tmp_path, monkeypatch, MAX_RUN_LLM_CALLS="3")
    prov = _CountingFake()
    with patch("app.research.pipeline.get_provider", return_value=prov):
        run = asyncio.run(pipe.run("Review API architecture, database schema, and authentication security", "C", provider_name="fake"))
    assert len(prov.calls) == 3
    assert not any(c.startswith("SYNTHESIZER.") for c in prov.calls)
    assert run["status"] == "PARTIAL"
    assert len(run["task_results"]) == 1
    assert any(e["stage"] == "run_budget_exceeded" and e.get("reason") == "max_llm_calls" for e in run["events"])


def test_ai_guard01_case4_failed_retries_count_against_hard_limit(tmp_path, monkeypatch):
    # Even when worker calls raise TimeoutError (so metrics.add_usage isn't called),
    # attempted provider calls MUST count against MAX_RUN_LLM_CALLS=3 (1 extract + 1 plan + 1 failed attempt = 3).
    pipe = _make_pipe(tmp_path, monkeypatch, MAX_RUN_LLM_CALLS="3", RETRY_LIMIT="2")
    prov = _CountingFake(fail_system_prefix="WORKER.")
    with patch("app.research.pipeline.get_provider", return_value=prov):
        run = asyncio.run(pipe.run("Review API architecture and database schema", "C", provider_name="fake"))
    assert len(prov.calls) == 3
    assert run["status"] == "FAILED"
    assert any(e["stage"] == "run_budget_exceeded" and e.get("reason") == "max_llm_calls" for e in run["events"])


def test_ai_guard01_case5_synthesis_blocked_at_exact_budget(tmp_path, monkeypatch):
    # 1 extract + 1 plan + 2 workers = 4 calls; synthesis would be 5th call -> MUST be blocked
    pipe = _make_pipe(tmp_path, monkeypatch, MAX_RUN_LLM_CALLS="4")
    prov = _CountingFake()
    with patch("app.research.pipeline.get_provider", return_value=prov):
        run = asyncio.run(pipe.run("Review API architecture and database schema", "C", provider_name="fake"))
    assert len(prov.calls) == 4
    assert not any(c.startswith("SYNTHESIZER.") for c in prov.calls)
    assert run["status"] == "PARTIAL"
    assert len(run["task_results"]) >= 1
    assert any(e["stage"] == "run_budget_exceeded" and e.get("reason") == "max_llm_calls" for e in run["events"])

    # Also verify simple product path with PRODUCT_REVIEWER=on + MAX_RUN_LLM_CALLS=1 blocks reviewer call pre-flight
    monkeypatch.setenv("PRODUCT_REVIEWER", "on")
    monkeypatch.setenv("MAX_RUN_LLM_CALLS", "1")
    prov_simple = _CountingFake()
    # Provide generate_structured so review_answer is eligible if unguarded
    async def _gen_struct(*, system, user, response_schema, **kw):
        prov_simple.calls.append(system.splitlines()[0][:60])
        return ProviderResult(text='{"claims":[{"claim":"PostgreSQL","supported":false}]}', usage=Usage(5, 5))
    prov_simple.generate_structured = _gen_struct
    with patch("app.research.pipeline.get_provider", return_value=prov_simple):
        run_simple = asyncio.run(pipe.run("Database dùng hệ quản trị gì?", "C", provider_name="fake", product_mode=True, domain_pack="software"))
    assert len(prov_simple.calls) == 1
    assert run_simple["status"] == "PARTIAL"
    assert any(e["stage"] == "run_budget_exceeded" and e.get("reason") == "max_llm_calls" for e in run_simple["events"])


def test_ai_guard01_case6_parallel_wave_cannot_burst_past_limit(tmp_path, monkeypatch):
    # With PRODUCT_TASK_PARALLEL=4 and 3 independent tasks in wave 1,
    # MAX_RUN_LLM_CALLS=3 allows 1 extract + 1 plan + at most 1 worker = 3 real provider calls total!
    pipe = _make_pipe(tmp_path, monkeypatch, MAX_RUN_LLM_CALLS="3", PRODUCT_TASK_PARALLEL="4")
    prov = _CountingFake(delay_system_prefix="WORKER.", delay_s=0.02)
    with patch("app.research.pipeline.get_provider", return_value=prov):
        run = asyncio.run(pipe.run("Phân tích kiến trúc API, kiểm tra cơ sở dữ liệu PostgreSQL và bảo mật JWT.", "C", provider_name="fake", product_mode=True, domain_pack="software"))
    assert len(prov.calls) <= 3
    assert run["status"] == "PARTIAL"
    assert any(e["stage"] == "run_budget_exceeded" and e.get("reason") == "max_llm_calls" for e in run["events"])


def test_ai_guard01_case7_wall_timeout_across_early_phases_preserves_safety(tmp_path, monkeypatch):
    pipe = _make_pipe(tmp_path, monkeypatch, MAX_DAG_WALL_SECONDS="0.04")
    prov = _CountingFake(delay_system_prefix="PLANNER.", delay_s=0.2)
    with patch("app.research.pipeline.get_provider", return_value=prov):
        run = asyncio.run(pipe.run("Review API architecture and database schema", "C", provider_name="fake"))
    assert run["status"] == "FAILED"
    assert any(e["stage"] in ("run_budget_exceeded", "run_failed") for e in run["events"])
    assert "Traceback" not in run["answer"]


def test_ai_guard01_case8_cancellation_releases_fair_queue_across_loops():
    # Also checks cross-event-loop reuse of shared FairQueue
    q = FairQueue(1)

    async def cancelled_run():
        entered = asyncio.Event()

        async def work():
            async with q.slot():
                entered.set()
                await asyncio.sleep(10)

        t = asyncio.create_task(work())
        await entered.wait()
        assert q.active == 1
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        assert q.active == 0 and q.waiting == 0

    asyncio.run(cancelled_run())

    async def second_loop_acquire():
        async with q.slot():
            assert q.active == 1
        assert q.active == 0

    asyncio.run(second_loop_acquire())


# ==============================================================================
# TEST 4: Research Mode A/B/C Preservation & /compare + /eval/run FairQueue
# ==============================================================================

def test_research_mode_abc_preservation_and_eval_compare_queue_latency(tmp_path, monkeypatch):
    monkeypatch.delenv("MAX_RUN_LLM_CALLS", raising=False)
    monkeypatch.delenv("MAX_DAG_WALL_SECONDS", raising=False)
    pipe = _make_pipe(
        tmp_path,
        monkeypatch,
        PRODUCT_MAX_CONTEXT_TOKENS="8000",
        PRODUCT_TASK_PARALLEL="4",
    )

    worker_prompts: list[str] = []

    class _ResearchSpyFake(FakeProvider):
        async def generate(self, *, system: str, user: str) -> ProviderResult:
            if system.startswith("WORKER."):
                worker_prompts.append(user)
            return await super().generate(system=system, user=user)

    with patch("app.research.pipeline.get_provider", return_value=_ResearchSpyFake()):
        run_a = asyncio.run(pipe.run("Review API architecture and database schema", "A", provider_name="fake"))
        run_b = asyncio.run(pipe.run("Review API architecture and database schema", "B", provider_name="fake"))
        run_c = asyncio.run(pipe.run("Review API architecture and database schema", "C", provider_name="fake"))

    for r in (run_a, run_b, run_c):
        assert r["status"] == "COMPLETE"
        assert r["effective_config"]["max_context_tokens"] == 3000
        assert "task_parallel" not in r["effective_config"]  # parallel stayed 1 for product_mode=False
        assert r["provenance"]["model"]["provider"] == "fake"
    assert len(run_a["tasks"]) == 1
    assert len(run_b["tasks"]) >= 2
    assert len(run_c["tasks"]) >= 2
    assert worker_prompts and all(p.startswith("[DOMAIN]") and "[TASK]" in p for p in worker_prompts)

    # Verify FairQueue wait BEFORE pipeline.run does NOT inflate pipeline latency_ms in /eval/run & /compare
    async def check_eval_latency_isolation():
        monkeypatch.setenv("PRODUCT_MAX_CONCURRENT_RUNS", "1")
        tok = await product_runs.acquire()

        class _FastPipe:
            retrieval_backend = "lexical"
            source_store = pipe.source_store

            async def run(self, message, condition, source_ids=None, **kwargs):
                t0 = time.perf_counter()
                await asyncio.sleep(0.01)
                return {
                    "run_id": "r_eval",
                    "condition": condition,
                    "status": "COMPLETE",
                    "answer": "PostgreSQL + JWT",
                    "task_results": [],
                    "tasks": [{"domain": "api"}],
                    "events": [],
                    "metrics": {"latency_ms": max(1, int((time.perf_counter() - t0) * 1000))},
                    "effective_config": {},
                    "model": "fake",
                    "config_hash": "h",
                }

        api = FastAPI()
        u = lambda r: {"user_id": "u1", "role": "ADMIN"}
        api.include_router(build_analysis_router(current_user=u, owner_pipeline=lambda _u, *a: _FastPipe(), session_factory=lambda: None))
        client = TestClient(api)
        req_task = asyncio.create_task(asyncio.to_thread(
            client.post,
            "/api/studio/eval/run",
            json={"question": "Check API", "condition": "C", "key_points": ["JWT"]},
        ))
        await asyncio.sleep(0.12)  # Hold slot for >=120ms
        product_runs.release(tok)
        t_http0 = time.perf_counter()
        resp = await asyncio.wait_for(req_task, timeout=3.0)
        assert resp.status_code == 200
        body = resp.json()
        # Pipeline run() metric latency excludes FairQueue pre-slot wait (>=120ms)!
        assert body["metrics"]["latency_ms"] < 90, f"Queue wait leaked into latency_ms: {body['metrics']}"
        assert t_http0 > 0

    asyncio.run(check_eval_latency_isolation())
