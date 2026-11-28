"""Batch 133 Backend API & Integration regression tests (Phase 2B):
NEW-06, VAL-05/B105-COMPARE-500, GAP-B122-01, OBS-W3-P82-02,
VAL-06, VAL-01, VAL-03, INF-04, RET-04.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.admin_system import qdrant_metrics
from app.api.analysis import build_router as build_analysis_router
from app.api.org import build_router as build_org_router
from app.api.studio import build_router as build_studio_router
from app.core.types import SourceChunk
from app.research.run_queue import product_runs
from app.storage.postgres.base import Base
from app.storage.postgres.models import NotificationRecord, UserRecord
from app.storage.postgres.runtime import PostgresSourceStore


class _Pipe:
    retrieval_backend = "lexical"

    def __init__(self, chunks=None):
        self._chunks = chunks or [SourceChunk("s1_c0000", "s1", "doc.md", "Điều 1. Nghỉ phép năm 12 ngày.", 0)]
        self.source_store = SimpleNamespace(
            chunks=lambda ids=None: [c for c in self._chunks if ids is None or c.source_id in ids],
            list_sources=lambda: [{"source_id": "s1", "source_name": "doc.md", "doc_type": "internal_rules", "chunk_count": 1}],
        )

    async def run(self, message, condition, source_ids=None, **kwargs):
        if condition not in {"A", "B", "C", "C-P", "C-N", "C-O"}:
            raise ValueError(f"Unknown condition {condition}")
        if source_ids is not None and any(sid not in {"s1"} for sid in source_ids):
            raise LookupError("source not found")
        return {
            "run_id": "r1",
            "condition": condition,
            "status": "COMPLETE",
            "answer": "Nghỉ phép 12 ngày.",
            "citations": ["s1_c0000"],
            "task_results": [{"citations": ["s1_c0000"], "evidence_ids": ["s1_c0000"]}],
            "metrics": {},
            "tasks": [],
            "events": [],
            "effective_config": {"request_route": "SIMPLE_PROJECT_QUESTION", "domain_pack": kwargs.get("domain_pack")},
        }


class _StubProvider:
    async def generate(self, system: str, user: str, **kwargs):
        return SimpleNamespace(text='{"status":"COVERED","reason":"ok","citations":[],"flags":[]}', input_tokens=1, output_tokens=1, latency_ms=1)


def _api(pipe=None):
    p = pipe or _Pipe()
    app = FastAPI()
    user = lambda r: {"user_id": "u1", "role": "ADMIN"}
    app.include_router(build_studio_router(current_user=user, owner_pipeline=lambda u, *a: p, session_factory=lambda: None))
    app.include_router(build_analysis_router(current_user=user, owner_pipeline=lambda u, *a: p, session_factory=lambda: None, provider_factory=lambda: _StubProvider()))
    return TestClient(app)


# ---------------- NEW-06: FairQueue product_runs integration ----------------

def test_new06_eval_auto_and_compare_acquire_product_runs_when_busy(monkeypatch):
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PRODUCT_MAX_CONCURRENT_RUNS", "1")
    entered = []

    class _SlowPipe(_Pipe):
        async def run(self, message, condition, source_ids=None, **kwargs):
            entered.append(("start", condition))
            await asyncio.sleep(0.03)
            entered.append(("end", condition))
            return await super().run(message, condition, source_ids=source_ids, **kwargs)

    async def go():
        tok = await product_runs.acquire()
        try:
            c = _api(_SlowPipe())
            task = asyncio.create_task(asyncio.to_thread(
                c.post, "/api/studio/eval/run",
                json={"question": "Nghỉ phép năm là bao nhiêu ngày?", "condition": "AUTO"},
            ))
            await asyncio.sleep(0.04)
            # While FairQueue slot is held, eval/run AUTO MUST wait and not enter pipeline yet!
            assert entered == []
            product_runs.release(tok)
            tok = None
            resp = await asyncio.wait_for(task, timeout=3.0)
            assert resp.status_code == 200
            assert entered == [("start", "C"), ("end", "C")]
        finally:
            if tok is not None:
                product_runs.release(tok)

        # And /compare runs cleanly without nested deadlock inside product_runs
        resp2 = await asyncio.wait_for(asyncio.to_thread(
            c.post, "/api/studio/compare",
            json={"message": "Nghỉ phép?", "conditions": ["A", "C"], "source_ids": ["s1"]},
        ), timeout=3.0)
        assert resp2.status_code == 200 and len(resp2.json()["runs"]) == 2

    asyncio.run(go())


# ---------------- VAL-05 & GAP-B122-01 ----------------

def test_val05_compare_rejects_invalid_condition_and_foreign_source(monkeypatch):
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    c = _api()
    r_bad_cond = c.post("/api/studio/compare", json={"message": "Hỏi", "conditions": ["INVALID_COND"]})
    assert r_bad_cond.status_code in (400, 422)

    r_missing_src = c.post("/api/studio/compare", json={"message": "Hỏi", "conditions": ["A"], "source_ids": ["foreign_src"]})
    assert r_missing_src.status_code == 404


def test_gap_b122_01_studio_route_accepts_and_validates_domain_pack():
    c = _api()
    r_bad = c.post("/api/studio/route", json={"message": "Ai duyệt?", "domain_pack": "NON_EXISTENT_PACK"})
    assert r_bad.status_code == 422
    r_ok = c.post("/api/studio/route", json={"message": "Ai duyệt nghỉ phép?", "domain_pack": "office"})
    assert r_ok.status_code == 200


# ---------------- OBS-W3-P82-02 & VAL-06 (main.py) ----------------

def test_obs_w3_p82_02_stream_auth_401_and_val06_whitespace_source_name(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    import app.main as main_mod

    c = TestClient(main_mod.app)
    r_unauth = c.post("/api/chat/stream", json={"message": "hello", "product_mode": True})
    assert r_unauth.status_code == 401

    # Authenticated blank source_name returns 422 instead of 500
    tok = main_mod.app.state.auth_store.create_user("u@x.vn", "pass1234", "U") if hasattr(main_mod.app.state.auth_store, "create_user") else None
    monkeypatch.setattr(main_mod.app.state, "auth_store", SimpleNamespace(resolve=lambda t: {"user_id": "u1", "role": "USER"}))
    r_ws = c.post("/api/sources/text", headers={"Authorization": "Bearer any"}, json={"source_name": "   ", "text": "Nội dung hợp lệ."})
    assert r_ws.status_code in (400, 422)
    assert tok is None or isinstance(tok, dict)


# ---------------- INF-04 ----------------

def test_inf04_vector_backend_env_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("VECTOR_INDEX_BACKEND", raising=False)
    monkeypatch.setenv("VECTOR_BACKEND", "qdrant")
    assert qdrant_metrics(str(tmp_path))["backend"] == "qdrant"

    r_audit = _api().get("/api/studio/admin/overview")
    # Also verify studio security_audit checks VECTOR_BACKEND fallback via direct source/client
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    app = FastAPI()
    app.include_router(build_studio_router(current_user=lambda r: {"user_id": "a", "role": "ADMIN"}, owner_pipeline=lambda u, *a: _Pipe(), session_factory=lambda: object()))
    sec = TestClient(app).get("/api/studio/admin/security-audit").json()
    assert sec["checks"]["vector_index"] == "memory"
    assert r_audit.status_code in (200, 503)


# ---------------- VAL-01, VAL-03, RET-04 (org.py + studio.py) ----------------

def _org_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    def _connect(conn, _):
        conn.create_function("btrim", 1, lambda v: None if v is None else v.strip())
        conn.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", _connect)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as s:
        s.add(UserRecord(user_id="an", email="an@x.vn", display_name="An", role="ADMIN", password_hash="x"))
        s.execute(text("CREATE TABLE studio_workspace_items (workspace_id TEXT, item_type TEXT, item_id TEXT)"))
        s.execute(text("CREATE TABLE studio_activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id TEXT, action TEXT, target TEXT, status INTEGER)"))
    app = FastAPI()
    app.include_router(build_org_router(current_user=lambda r: {"user_id": "an", "role": "ADMIN"}, session_factory=lambda: factory))
    c = TestClient(app)
    sp = c.post("/api/org/spaces", headers={"x-user": "an"}, json={"name": "OrgTest"}).json()["space_id"]
    return factory, c, sp


def test_val01_val03_whitespace_rejected_and_ret04_publish_runs_doc_watch(monkeypatch):
    factory, c, sp = _org_client(monkeypatch)
    # VAL-01: blank department name & blank space update name must return 422 instead of 409/200
    assert c.post(f"/api/org/spaces/{sp}/departments", headers={"x-user": "an"}, json={"name": "   "}).status_code == 422
    assert c.patch(f"/api/org/spaces/{sp}", headers={"x-user": "an"}, json={"name": "   "}).status_code == 422
    # VAL-03: blank request title must return 422 instead of 200
    assert c.post(f"/api/org/spaces/{sp}/requests", headers={"x-user": "an"}, json={"kind": "leave", "title": "   ", "approver_level": "EXECUTIVE"}).status_code == 422

    # RET-04: publishing a newer replacement document into org space triggers doc_watch notification
    s_old = PostgresSourceStore(factory, "an").import_text(
        "quyet_dinh_cu.txt",
        "Quyết định số 01/2024/QĐ-CT có hiệu lực từ ngày 01/01/2024.",
    )["source_id"]
    assert c.post(f"/api/org/spaces/{sp}/sources/{s_old}/publish", headers={"x-user": "an"}, json={"classification": "COMPANY"}).status_code == 200

    s_new = PostgresSourceStore(factory, "an").import_text(
        "quyet_dinh_moi.txt",
        "Quyết định số 02/2025/QĐ-CT thay thế Quyết định số 01/2024/QĐ-CT và có hiệu lực từ ngày 01/01/2025.",
    )["source_id"]
    pub = c.post(f"/api/org/spaces/{sp}/sources/{s_new}/publish", headers={"x-user": "an"}, json={"classification": "COMPANY"})
    assert pub.status_code == 200
    with factory() as db:
        notes = list(db.scalars(__import__("sqlalchemy").select(NotificationRecord)).all())
    assert any(n.kind == "doc_watch" for n in notes)
