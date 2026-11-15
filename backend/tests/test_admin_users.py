"""Quản lý người dùng: kho tài khoản PostgresAuthStore chạy trên SQLite trong bộ nhớ (cùng mô hình SQLAlchemy) và API /api/admin/users."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.users import build_router
from app.storage.postgres.base import Base
from app.storage.postgres.runtime import PostgresAuthStore


@pytest.fixture()
def store():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    # ràng buộc CHECK của mô hình dùng hàm btrim của PostgreSQL
    event.listen(engine, "connect", lambda conn, _: conn.create_function("btrim", 1, lambda v: None if v is None else v.strip()))
    Base.metadata.create_all(engine)
    return PostgresAuthStore(sessionmaker(engine, expire_on_commit=False))


def _ids(store):
    admin = store.register(email="admin@x.vn", password="matkhau-admin-1", role="ADMIN", display_name="Admin")
    user = store.register(email="nv@x.vn", password="matkhau-nv-123", display_name="Nhân viên")
    return admin["user_id"], user["user_id"]


def test_list_has_counts_and_search(store):
    _ids(store)
    users = store.admin_users()
    assert {u["email"] for u in users} == {"admin@x.vn", "nv@x.vn"}
    assert all("password_hash" not in u and u["active_sessions"] == 0 and u["source_count"] == 0 for u in users)
    assert [u["email"] for u in store.admin_users(query="NHÂN")] == ["nv@x.vn"]


def test_disable_revokes_sessions_and_blocks_login(store):
    admin_id, user_id = _ids(store)
    _, token, _ = store.authenticate(identifier="nv@x.vn", password="matkhau-nv-123")
    assert store.session_for_token(token) is not None
    store.admin_update_user(user_id, actor_id=admin_id, status="DISABLED")
    assert store.session_for_token(token) is None
    with pytest.raises(Exception):
        store.authenticate(identifier="nv@x.vn", password="matkhau-nv-123")
    store.admin_update_user(user_id, actor_id=admin_id, status="ACTIVE")
    assert store.authenticate(identifier="nv@x.vn", password="matkhau-nv-123")[0]["status"] == "ACTIVE"


def test_guardrails_self_and_last_admin(store):
    admin_id, user_id = _ids(store)
    with pytest.raises(PermissionError):
        store.admin_update_user(admin_id, actor_id=admin_id, role="USER")
    with pytest.raises(PermissionError):
        store.admin_update_user(admin_id, actor_id=admin_id, status="DISABLED")
    # người khác hạ quyền admin cuối cùng cũng bị chặn
    with pytest.raises(PermissionError):
        store.admin_update_user(admin_id, actor_id=user_id, role="USER")
    store.admin_update_user(user_id, actor_id=admin_id, role="ADMIN")
    assert store.admin_update_user(admin_id, actor_id=user_id, role="USER")["role"] == "USER"
    with pytest.raises(ValueError):
        store.admin_update_user(user_id, actor_id=admin_id, role="ROOT")


def test_reset_password_gives_working_temporary_and_logs_out(store):
    admin_id, user_id = _ids(store)
    _, token, _ = store.authenticate(identifier="nv@x.vn", password="matkhau-nv-123")
    _, temporary = store.admin_reset_password(user_id)
    assert len(temporary) >= 12 and store.session_for_token(token) is None
    with pytest.raises(Exception):
        store.authenticate(identifier="nv@x.vn", password="matkhau-nv-123")
    assert store.authenticate(identifier="nv@x.vn", password=temporary)[0]["user_id"] == user_id


def _client(store, role="ADMIN", user_id="?"):
    app = FastAPI()
    app.state.auth_store = store
    app.include_router(build_router(current_user=lambda r: {"user_id": user_id, "role": role}))
    return TestClient(app)


def test_api_admin_only_and_flow(store):
    admin_id, user_id = _ids(store)
    assert _client(store, role="USER").get("/api/admin/users").status_code == 403
    c = _client(store, user_id=admin_id)
    body = c.get("/api/admin/users").json()
    assert body["total"] == 2 and body["admins_active"] == 1
    created = c.post("/api/admin/users", json={"email": "moi@x.vn", "display_name": "Mới"})
    assert created.status_code == 201 and len(created.json()["temporary_password"]) >= 12
    assert c.post("/api/admin/users", json={"email": "moi@x.vn"}).status_code == 409
    assert c.patch(f"/api/admin/users/{admin_id}", json={"role": "USER"}).status_code == 409
    assert c.patch(f"/api/admin/users/{user_id}", json={"status": "DISABLED"}).json()["user"]["status"] == "DISABLED"
    assert c.patch("/api/admin/users/khong-co", json={"status": "ACTIVE"}).status_code == 404
    assert c.post(f"/api/admin/users/{user_id}/revoke-sessions").json() == {"revoked": 0}
    assert "temporary_password" in c.post(f"/api/admin/users/{user_id}/reset-password").json()
