"""Cookie phiên: chỉ gắn cờ Secure khi bật COOKIE_SECURE (chạy sau HTTPS); mặc định tắt để http://127.0.0.1 vẫn đăng nhập được."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router


class FakeAuthStore:
    def authenticate(self, *, identifier, password):
        return {"user_id": "u1"}, "tok123", {"session_id": "s1"}


def _login_cookie_header(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("COOKIE_SECURE", raising=False)
    else:
        monkeypatch.setenv("COOKIE_SECURE", value)
    app = FastAPI()
    app.state.auth_store = FakeAuthStore()
    app.include_router(router)
    r = TestClient(app).post("/api/auth/login", json={"identifier": "a@b.c", "password": "x"})
    assert r.status_code == 200
    return r.headers["set-cookie"].lower()


def test_cookie_not_secure_by_default(monkeypatch):
    header = _login_cookie_header(monkeypatch, None)
    assert "session_token=tok123" in header and "httponly" in header and "secure" not in header


def test_cookie_secure_when_enabled(monkeypatch):
    assert "secure" in _login_cookie_header(monkeypatch, "true")
