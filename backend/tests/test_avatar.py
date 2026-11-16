"""Ảnh đại diện: PUT /api/auth/avatar chỉ đổi ảnh của chính người gọi, kiểm tra định dạng, ảnh hiện trong phiên."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import router
from app.storage.postgres.base import Base
from app.storage.postgres.runtime import PostgresAuthStore

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.create_function("btrim", 1, lambda v: None if v is None else v.strip()))
    Base.metadata.create_all(engine)
    store = PostgresAuthStore(sessionmaker(engine, expire_on_commit=False))
    store.register(email="a@x.vn", password="matkhau-a-123", display_name="A")
    store.register(email="b@x.vn", password="matkhau-b-123", display_name="B")
    app = FastAPI()
    app.state.auth_store = store
    app.include_router(router)
    return TestClient(app), store


def _auth(store, email, pw):
    return {"Authorization": f"Bearer {store.authenticate(identifier=email, password=pw)[1]}"}


def test_set_preset_upload_and_clear(client):
    c, store = client
    h = _auth(store, "a@x.vn", "matkhau-a-123")
    assert c.get("/api/auth/session", headers=h).json()["user"]["avatar"] is None
    assert c.put("/api/auth/avatar", json={"avatar": "preset:robot-c27"}, headers=h).json()["user"]["avatar"] == "preset:robot-c27"
    assert c.put("/api/auth/avatar", json={"avatar": PNG}, headers=h).status_code == 200
    assert c.get("/api/auth/session", headers=h).json()["user"]["avatar"] == PNG
    # người khác không bị ảnh hưởng
    hb = _auth(store, "b@x.vn", "matkhau-b-123")
    assert c.get("/api/auth/session", headers=hb).json()["user"]["avatar"] is None
    assert c.put("/api/auth/avatar", json={"avatar": None}, headers=h).json()["user"]["avatar"] is None


@pytest.mark.parametrize("bad", [
    "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",  # SVG có thể chứa script
    "https://example.com/a.png",
    "preset:Robot C27",
    "javascript:alert(1)",
    pytest.param("data:image/png;base64," + "A" * 200_000, id="qua-lon"),
])
def test_rejects_invalid(client, bad):
    c, store = client
    h = _auth(store, "a@x.vn", "matkhau-a-123")
    assert c.put("/api/auth/avatar", json={"avatar": bad}, headers=h).status_code in (400, 422)


def test_requires_login_and_cannot_target_others(client):
    c, _ = client
    assert c.put("/api/auth/avatar", json={"avatar": "preset:meo"}).status_code == 401
    # không nhận trường user_id: không có cách sửa ảnh của người khác
    assert c.put("/api/auth/avatar", json={"avatar": "preset:meo", "user_id": "x"}).status_code in (401, 422)
