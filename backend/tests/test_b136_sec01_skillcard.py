"""Prepared Regression & Security Suite for B135-SEC-01 (SEC-T01 .. SEC-T15).

STATUS: PREPARED ONLY — NOT EXECUTED IN B136 DUE TO GATE 0 RESOURCE_HOLD
(Host FreePhysicalMemory = 0.992..1.506 GB < ~2.0 GB recommended target).

Copy/run inside backend/ once >= 2 GB free RAM is available:
  python -m pytest -q <path_to_this_file>
Uses isolated in-memory SQLite + StaticPool (0 Postgres/Qdrant/Ollama touches).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.org import build_router as build_org_router
from app.core.access import REDACTED_ANSWER
from app.storage.postgres.base import Base
from app.storage.postgres.models import (
    ConversationMessageRecord,
    ConversationRecord,
    OrgSourceShareRecord,
    UserRecord,
)
from app.storage.postgres.runtime import (
    PostgresConversationStore,
    PostgresSourceStore,
)


def _make_isolated_factory():
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
            UserRecord(user_id="exec_a", email="exec_a@x.vn", display_name="ExecA", role="USER", password_hash="x"),
            UserRecord(user_id="staff_a", email="staff_a@x.vn", display_name="StaffA", role="USER", password_hash="x"),
            UserRecord(user_id="outsider", email="outsider@x.vn", display_name="Outsider", role="USER", password_hash="x"),
            UserRecord(user_id="exec_b", email="exec_b@x.vn", display_name="ExecB", role="USER", password_hash="x"),
        ])
        s.execute(text("CREATE TABLE studio_workspaces (workspace_id TEXT PRIMARY KEY, owner_user_id TEXT, name TEXT, description TEXT, domain_pack TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.execute(text("CREATE TABLE studio_workspace_items (workspace_id TEXT, item_type TEXT, item_id TEXT, UNIQUE(item_type, item_id))"))
        s.execute(text("CREATE TABLE studio_activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id TEXT, action TEXT, target TEXT, status INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.execute(text("CREATE TABLE studio_reports (report_id TEXT PRIMARY KEY, owner_user_id TEXT, workspace_id TEXT, kind TEXT, title TEXT, payload TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.execute(text("CREATE TABLE studio_feedback (owner_user_id TEXT, run_id TEXT, rating INTEGER, note TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(owner_user_id, run_id))"))
        s.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        s.execute(text("INSERT INTO alembic_version (version_num) VALUES ('head_test')"))
    return factory


@pytest.fixture()
def env(monkeypatch, tmp_path):
    factory = _make_isolated_factory()
    users = {
        "tok_exec_a": {"user_id": "exec_a", "role": "USER"},
        "tok_staff_a": {"user_id": "staff_a", "role": "USER"},
        "tok_outsider": {"user_id": "outsider", "role": "USER"},
        "tok_exec_b": {"user_id": "exec_b", "role": "USER"},
    }

    org_api = FastAPI()
    org_api.include_router(
        build_org_router(
            current_user=lambda r: users[r.headers["x-tok"]],
            session_factory=lambda: factory,
        )
    )
    oc = TestClient(org_api)

    sp_a = oc.post("/api/org/spaces", headers={"x-tok": "tok_exec_a"}, json={"name": "OrgA", "departments": ["D1"]}).json()["space_id"]
    dep_a = oc.get(f"/api/org/spaces/{sp_a}", headers={"x-tok": "tok_exec_a"}).json()["departments"][0]["department_id"]
    inv = oc.post(f"/api/org/spaces/{sp_a}/invites", headers={"x-tok": "tok_exec_a"}, json={"kind": "USER", "email": "staff_a@x.vn", "level": "STAFF", "department_id": dep_a}).json()["invite_id"]
    assert oc.post(f"/api/org/invites/{inv}/accept", headers={"x-tok": "tok_staff_a"}).status_code == 200

    sp_b = oc.post("/api/org/spaces", headers={"x-tok": "tok_exec_b"}, json={"name": "OrgB", "departments": ["D2"]}).json()["space_id"]

    # Seed sources in OrgA (COMPANY + SECRET), OrgB, and Personal (staff_a)
    src_company_a = PostgresSourceStore(factory, "exec_a").import_text("co_a.txt", "Chính sách chung OrgA.")["source_id"]
    oc.post(f"/api/org/spaces/{sp_a}/sources/{src_company_a}/publish", headers={"x-tok": "tok_exec_a"}, json={"classification": "COMPANY"})

    src_secret_a = PostgresSourceStore(factory, "exec_a").import_text("sec_a.txt", "Bí mật sáp nhập OrgA 900 tỷ.")["source_id"]
    oc.post(f"/api/org/spaces/{sp_a}/sources/{src_secret_a}/publish", headers={"x-tok": "tok_exec_a"}, json={"classification": "SECRET"})

    src_secret_shared = PostgresSourceStore(factory, "exec_a").import_text("sec_sh.txt", "Bí mật chia sẻ cho StaffA.")["source_id"]
    oc.post(f"/api/org/spaces/{sp_a}/sources/{src_secret_shared}/publish", headers={"x-tok": "tok_exec_a"}, json={"classification": "SECRET"})
    with factory.begin() as db:
        db.add(OrgSourceShareRecord(share_id="sh_staff", source_id=src_secret_shared, target_user_id="staff_a"))

    src_company_b = PostgresSourceStore(factory, "exec_b").import_text("co_b.txt", "Tài liệu riêng OrgB.")["source_id"]
    oc.post(f"/api/org/spaces/{sp_b}/sources/{src_company_b}/publish", headers={"x-tok": "tok_exec_b"}, json={"classification": "COMPANY"})

    src_personal_staff = PostgresSourceStore(factory, "staff_a").import_text("personal_staff.txt", "Ghi chú cá nhân của StaffA.")["source_id"]

    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("PROVIDER", "fake")
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(main_mod.app.state, "storage_backend", "postgres")
    monkeypatch.setattr(main_mod.app.state, "session_factory", factory)

    class _Auth:
        def resolve(self, tok):
            if tok not in users:
                raise main_mod.InvalidSessionError("invalid")
            return users[tok]

    monkeypatch.setattr(main_mod.app.state, "auth_store", _Auth())
    client = TestClient(main_mod.app)
    return SimpleNamespace(
        factory=factory, client=client, oc=oc,
        sp_a=sp_a, sp_b=sp_b,
        src_company_a=src_company_a, src_secret_a=src_secret_a,
        src_secret_shared=src_secret_shared, src_company_b=src_company_b,
        src_personal_staff=src_personal_staff,
    )


def _msg_count(factory):
    with factory() as db:
        return len(db.scalars(select(ConversationMessageRecord)).all())


def test_sec_t01_org_source_ref_without_space_id_rejected(env):
    before = _msg_count(env.factory)
    r = env.client.post(
        "/api/conversations/skill-card",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={
            "question": "Q", "summary": "S",
            "card": {"skill": "validity", "data": {"chunk_id": f"{env.src_company_a}_c0000"}},
        },
    )
    assert r.status_code in (403, 404)
    assert _msg_count(env.factory) == before


def test_sec_t02_mismatched_space_id_rejected(env):
    before = _msg_count(env.factory)
    # exec_b belongs to OrgB, tries saving OrgA src_ using ?space_id=sp_b
    r = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_b}",
        headers={"Authorization": "Bearer tok_exec_b"},
        json={
            "question": "Q", "summary": "S",
            "card": {"skill": "validity", "data": {"source_id": env.src_company_a}},
        },
    )
    assert r.status_code in (403, 404)
    assert _msg_count(env.factory) == before


def test_sec_t03_outsider_cannot_access_org_skillcard(env):
    before = _msg_count(env.factory)
    r1 = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_a}",
        headers={"Authorization": "Bearer tok_outsider"},
        json={"question": "Q", "summary": "S", "card": {"skill": "validity", "data": {"source_id": env.src_company_a}}},
    )
    r2 = env.client.post(
        "/api/conversations/skill-card",
        headers={"Authorization": "Bearer tok_outsider"},
        json={"question": "Q", "summary": "S", "card": {"skill": "validity", "data": {"source_id": env.src_company_a}}},
    )
    assert r1.status_code == 403
    assert r2.status_code in (403, 404)
    assert _msg_count(env.factory) == before


def test_sec_t04_authorized_org_member_succeeds(env):
    r = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_a}",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={
            "question": "Chính sách chung?", "summary": "Đã kiểm tra.",
            "card": {"skill": "validity", "data": {"chunk_id": f"{env.src_company_a}_c0000"}},
        },
    )
    assert r.status_code == 200
    assert r.json().get("conversation_id", "").startswith("conv_")


def test_sec_t05_revoked_user_blocked_and_existing_card_redacted(env):
    r_ok = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_a}",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"question": "Q", "summary": "Bí mật chia sẻ.", "card": {"skill": "validity", "data": {"source_id": env.src_secret_shared}}},
    )
    assert r_ok.status_code == 200
    cid = r_ok.json()["conversation_id"]
    with env.factory.begin() as db:
        db.delete(db.get(OrgSourceShareRecord, "sh_staff"))

    before = _msg_count(env.factory)
    r_after = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_a}",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"question": "Q2", "summary": "S2", "card": {"skill": "validity", "data": {"source_id": env.src_secret_shared}}},
    )
    assert r_after.status_code in (403, 404)
    assert _msg_count(env.factory) == before
    conv = env.client.get(f"/api/conversations/{cid}?space_id={env.sp_a}", headers={"Authorization": "Bearer tok_staff_a"}).json()
    assert conv["messages"][1]["content"] == REDACTED_ANSWER


def test_sec_t06_unshared_secret_blocked_with_and_without_space_id(env):
    before = _msg_count(env.factory)
    r1 = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_a}",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"question": "Q", "summary": "S", "card": {"skill": "validity", "data": {"source_id": env.src_secret_a}}},
    )
    r2 = env.client.post(
        "/api/conversations/skill-card",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"question": "Q", "summary": "S", "card": {"skill": "validity", "data": {"source_id": env.src_secret_a}}},
    )
    assert r1.status_code == 404
    assert r2.status_code in (403, 404)
    assert _msg_count(env.factory) == before


def test_sec_t07_shared_secret_with_space_id_succeeds(env):
    r = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_a}",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"question": "Q", "summary": "Được chia sẻ.", "card": {"skill": "validity", "data": {"source_id": env.src_secret_shared}}},
    )
    assert r.status_code == 200


def test_sec_t08_nonexistent_source_id_rejected(env):
    before = _msg_count(env.factory)
    r = env.client.post(
        "/api/conversations/skill-card",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"question": "Q", "summary": "S", "card": {"skill": "validity", "data": {"source_id": "src_0000111122223333"}}},
    )
    assert r.status_code == 404
    assert _msg_count(env.factory) == before


def test_sec_t09_mixed_valid_and_unauthorized_sources_rejected(env):
    before = _msg_count(env.factory)
    r = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_a}",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={
            "question": "Q", "summary": f"Chứa {env.src_secret_a}",
            "card": {"skill": "compare", "data": {"old": env.src_company_a}},
            "source_ids": [env.src_company_a],
        },
    )
    assert r.status_code == 404
    assert _msg_count(env.factory) == before


def test_sec_t10_spoofed_top_level_run_id_rejected_422(env):
    before = _msg_count(env.factory)
    r = env.client.post(
        "/api/conversations/skill-card",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={
            "question": "Q", "summary": "S",
            "card": {"skill": "validity", "data": {}},
            "run_id": "run_victim_other_user",
        },
    )
    assert r.status_code == 422
    assert _msg_count(env.factory) == before


def test_sec_t11_personal_workspace_valid_flow_preserved(env):
    r = env.client.post(
        "/api/conversations/skill-card",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={
            "question": "Ghi chú riêng?", "summary": "Tóm tắt riêng.",
            "card": {"skill": "validity", "data": {"source_id": env.src_personal_staff}},
            "source_ids": [env.src_personal_staff],
        },
    )
    assert r.status_code == 200
    cid = r.json()["conversation_id"]
    got = env.client.get(f"/api/conversations/{cid}", headers={"Authorization": "Bearer tok_staff_a"})
    assert got.status_code == 200 and "Tóm tắt riêng." in got.json()["messages"][1]["content"]


def test_sec_t12_other_users_conversation_id_rejected_404(env):
    cid_exec = PostgresConversationStore(env.factory, "exec_a", None).create("ExecPrivate")["conversation_id"]
    before = _msg_count(env.factory)
    r = env.client.post(
        "/api/conversations/skill-card",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"conversation_id": cid_exec, "question": "Q", "summary": "S", "card": {"skill": "validity", "data": {}}},
    )
    assert r.status_code == 404
    assert _msg_count(env.factory) == before


def test_sec_t13_unauthenticated_request_rejected_401(env):
    r = env.client.post(
        "/api/conversations/skill-card",
        json={"question": "Q", "summary": "S", "card": {"skill": "validity", "data": {}}},
    )
    assert r.status_code == 401


def test_sec_t14_rejected_request_creates_zero_conversation_or_message_rows(env):
    with env.factory() as db:
        convs_before = len(db.scalars(select(ConversationRecord)).all())
        msgs_before = len(db.scalars(select(ConversationMessageRecord)).all())
    r = env.client.post(
        "/api/conversations/skill-card",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"question": "Q", "summary": "S", "card": {"skill": "validity", "data": {"source_id": env.src_secret_a}}},
    )
    assert r.status_code in (403, 404)
    with env.factory() as db:
        assert len(db.scalars(select(ConversationRecord)).all()) == convs_before
        assert len(db.scalars(select(ConversationMessageRecord)).all()) == msgs_before


def test_sec_t15_error_response_discloses_no_secret_content(env):
    r = env.client.post(
        f"/api/conversations/skill-card?space_id={env.sp_a}",
        headers={"Authorization": "Bearer tok_staff_a"},
        json={"question": "Q", "summary": "S", "card": {"skill": "validity", "data": {"source_id": env.src_secret_a}}},
    )
    assert r.status_code == 404
    body_text = r.text
    assert "900 tỷ" not in body_text
    assert "sec_a.txt" not in body_text
    assert env.src_secret_a not in body_text
