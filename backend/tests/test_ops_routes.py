import json
import logging
from pathlib import Path
from threading import RLock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

import os
os.environ.setdefault("APP_STORAGE_BACKEND", "file")
os.environ.setdefault("PROVIDER", "fake")
from app.main import app
import app.main as main_module
from app.storage.postgres.config import engine_options
from app.core.observability import TTLCache
from app.auth.store import AuthStore, AUTH_SCHEMA_VERSION, DEFAULT_SESSION_TTL_SECONDS


class MemoryAuthStore(AuthStore):
    def __init__(self):
        self.root = Path(".")
        self.path = Path("unused-auth-store.json")
        self.session_ttl_seconds = DEFAULT_SESSION_TTL_SECONDS
        self._lock = RLock()
        self._data = {"schema_version": AUTH_SCHEMA_VERSION, "users": [], "sessions": []}

    def _save(self):
        return None


@pytest.fixture(autouse=True)
def file_backend(monkeypatch):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("PROVIDER", "fake")
    main_module._ready_cache = TTLCache(5)
    main_module._local_health_cache = TTLCache(30)
    app.state.auth_store = MemoryAuthStore()


def test_request_id_health_and_security_headers():
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "request_123"})
        assert response.headers["X-Request-ID"] == "request_123"
        assert response.json() == {"ok": True, "app": "local-multi-agent-rag", "version": "0.2.0-m0"}
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Permissions-Policy"]
        invalid = client.get("/api/health", headers={"X-Request-ID": "bad id"})
        assert len(invalid.headers["X-Request-ID"]) == 32
        missing = client.get("/not-found")
        assert missing.status_code == 404
        assert "X-Frame-Options" in missing.headers


def test_unhandled_500_keeps_request_and_security_headers():
    from fastapi import FastAPI
    from app.core.observability import RequestIdMiddleware, SecurityHeadersMiddleware
    failing = FastAPI()
    failing.add_middleware(RequestIdMiddleware)
    failing.add_middleware(SecurityHeadersMiddleware)

    @failing.get("/failure")
    def failure():
        raise RuntimeError("private exception detail")

    with TestClient(failing, raise_server_exceptions=False) as client:
        response = client.get("/failure", headers={"X-Request-ID": "request_123"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "request_123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "private exception detail" not in response.text


def test_health_is_minimal_and_config_is_safe():
    client = TestClient(app)
    assert set(client.get("/api/health").json()) == {"ok", "app", "version"}
    config = client.get("/api/config").json()
    assert "config_hash" not in config
    assert not any(any(secret in key.lower() for secret in ("path", "url", "dsn", "host", "endpoint")) for key in config)


def test_ready_ok_skipped_and_fail_are_cached_and_stable(monkeypatch):
    now = [0.0]
    main_module._ready_cache = TTLCache(5, clock=lambda: now[0])
    monkeypatch.setattr(main_module, "check_postgres", lambda factory: "ok")
    monkeypatch.setattr(main_module, "check_vector", lambda store: "skipped")
    async def ollama_ok(): return "ok"
    monkeypatch.setattr(main_module, "check_ollama", ollama_ok)
    client = TestClient(app)
    ok = client.get("/api/ready")
    assert ok.status_code == 200 and ok.json()["ready"] is True
    assert ok.json()["checks"]["qdrant"]["status"] == "skipped"
    calls = []
    monkeypatch.setattr(main_module, "check_postgres", lambda factory: calls.append(1) or "fail")
    now[0] = 4
    assert client.get("/api/ready").status_code == 200
    assert calls == []
    now[0] = 6
    failed = client.get("/api/ready")
    assert failed.status_code == 503
    assert "exception" not in failed.text.lower()
    assert "dsn" not in failed.text.lower()


def test_local_model_health_requires_login_and_caches(monkeypatch):
    assert TestClient(app).get("/api/local-model/health").status_code == 401
    now = [0.0]
    main_module._local_health_cache = TTLCache(30, clock=lambda: now[0])
    calls = []
    async def health(self):
        calls.append(1)
        return {"ok": True}
    monkeypatch.setattr(main_module.OllamaProvider, "health", health)
    with TestClient(app) as client:
        client.post("/api/auth/register", json={"username": "opsuser", "password": "Sup3r-Secret-pass"})
        login = client.post("/api/auth/login", json={"username": "opsuser", "password": "Sup3r-Secret-pass"})
        assert login.status_code == 200
        assert client.get("/api/local-model/health").json() == {"ok": True}
        assert client.get("/api/local-model/health").json() == {"ok": True}
    assert len(calls) == 1


def test_cookie_secure_flag_uses_environment(monkeypatch):
    with TestClient(app) as client:
        client.post("/api/auth/register", json={"username": "cookieuser", "password": "Sup3r-Secret-pass"})
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
        response = client.post("/api/auth/login", json={"username": "cookieuser", "password": "Sup3r-Secret-pass"})
        assert "; Secure" in response.headers["set-cookie"]


def test_json_access_log_has_request_id_and_no_secrets(caplog, capsys):
    caplog.set_level(logging.INFO)
    with TestClient(app) as client:
        client.post("/api/auth/register", json={"username": "loguser", "password": "Sup3r-Secret-pass"})
        client.post("/api/auth/login", json={"username": "loguser", "password": "Sup3r-Secret-pass"},
                    headers={"Authorization": "Bearer auth-secret-token"}, cookies={"session_token": "cookie-secret"})
    output = "\n".join(record.getMessage() for record in caplog.records)
    # The installed JSON formatter serializes access records; verify the formatter directly.
    records = [record for record in caplog.records if record.name == "cap1.access"]
    assert records and records[-1].request_id
    formatter = next(handler.formatter for handler in logging.getLogger().handlers
                     if handler.formatter and handler.formatter.__class__.__name__ == "JsonFormatter")
    line = formatter.format(records[-1])
    parsed = json.loads(line)
    assert parsed["request_id"] and parsed["method"] == "POST"
    assert all(secret not in output + line for secret in ("Sup3r-Secret-pass", "cookie-secret", "auth-secret-token"))


def test_cors_default_absent_and_configured_present(monkeypatch):
    with TestClient(app) as client:
        response = client.options("/api/health", headers={"Origin": "https://example.test", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in response.headers
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://example.test")
    from fastapi import FastAPI
    configured = FastAPI()
    origins = main_module.cors_origins_from_env()
    configured.add_middleware(main_module.CORSMiddleware, allow_origins=origins, allow_credentials=True,
                              allow_methods=["*"], allow_headers=["*"])
    configured.get("/api/health")(lambda: {"ok": True})
    with TestClient(configured) as client:
        response = client.options("/api/health", headers={"Origin": "https://example.test", "Access-Control-Request-Method": "GET"})
        assert response.headers["access-control-allow-origin"] == "https://example.test"
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    assert main_module.cors_origins_from_env() == []


def test_engine_options_for_postgres_and_sqlite():
    pg = engine_options(make_url("postgresql+psycopg://user:pass@localhost/db"), {})
    assert pg["pool_timeout"] == 10.0
    assert pg["connect_args"] == {"connect_timeout": 5}
    sqlite = engine_options(make_url("sqlite+pysqlite:///:memory:"), {})
    assert "connect_args" not in sqlite
