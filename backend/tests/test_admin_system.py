"""Bảng điều khiển quản trị: /api/admin/system trả số đo thật hoặc None (không điền số giả), /api/admin/audit gộp nhật ký mọi tài khoản."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import admin_system
from app.storage.postgres.base import Base


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.create_function("btrim", 1, lambda v: None if v is None else v.strip()))
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE studio_activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id TEXT, action TEXT, target TEXT, status INTEGER, created_at TEXT)"))
        c.execute(text("INSERT INTO users (user_id, email, display_name, role, status, password_hash, created_at, updated_at) VALUES ('u1','a@x.vn','An','ADMIN','ACTIVE','x','2026-11-15','2026-11-15'), ('u2','b@x.vn','Bình','USER','ACTIVE','x','2026-11-15','2026-11-15')"))
        c.execute(text("INSERT INTO studio_activity (owner_user_id, action, target, status, created_at) VALUES ('u1','Nạp tài liệu','a.md',200,'2026-11-15T01:00:00'), ('u2','Đặt câu hỏi','',500,'2026-11-15T02:00:00'), ('u2','Xóa tài liệu','b.md',200,'2026-11-15T03:00:00')"))
    return sessionmaker(engine, expire_on_commit=False)


def _client(factory, role, tmp_path):
    app = FastAPI()
    app.include_router(admin_system.build_router(current_user=lambda r: {"user_id": "u1", "role": role}, session_factory=lambda: factory, vector_path=str(tmp_path)))
    return TestClient(app)


def test_non_admin_forbidden(factory, tmp_path):
    c = _client(factory, "USER", tmp_path)
    assert c.get("/api/admin/system").status_code == 403
    assert c.get("/api/admin/audit").status_code == 403


def test_audit_all_users_search_and_errors(factory, tmp_path):
    c = _client(factory, "ADMIN", tmp_path)
    r = c.get("/api/admin/audit").json()
    assert r["total"] == 3 and [x["action"] for x in r["rows"]] == ["Xóa tài liệu", "Đặt câu hỏi", "Nạp tài liệu"]
    assert r["rows"][0]["email"] == "b@x.vn"
    assert c.get("/api/admin/audit", params={"q": "a@x.vn"}).json()["total"] == 1
    assert [x["status"] for x in c.get("/api/admin/audit", params={"errors": True}).json()["rows"]] == [500]


def test_system_reports_real_values_or_none(factory, tmp_path, monkeypatch):
    (tmp_path / "collection" / "chunks").mkdir(parents=True)
    (tmp_path / "collection" / "chunks" / "f.bin").write_bytes(b"x" * 1234)
    async def fake_ollama(*a, **k):
        return {"reachable": False, "models": [], "loaded": [], "chat_model_ready": None, "embed_model_ready": None}
    monkeypatch.setattr(admin_system, "ollama_metrics", fake_ollama)
    r = _client(factory, "ADMIN", tmp_path).get("/api/admin/system").json()
    assert r["qdrant"]["size_bytes"] == 1234 and r["qdrant"]["collections"] == ["chunks"]
    assert r["postgres"]["reachable"] and r["postgres"]["counts"]["users"] == 2
    assert r["postgres"]["size_bytes"] is None  # SQLite: không đo được dung lượng kiểu PostgreSQL, không điền số giả
    assert r["host"]["available"] and 0 <= r["host"]["cpu_percent"] <= 100 and r["host"]["ram_total_bytes"] > 0


def test_ollama_unreachable_is_none_not_zero():
    out = asyncio.run(admin_system.ollama_metrics("http://127.0.0.1:9", "qwen3:4b", "nomic-embed-text"))
    assert out["reachable"] is False and out["chat_model_ready"] is None and out["models"] == []


def test_dir_size_missing_is_none(tmp_path):
    assert admin_system.dir_size(tmp_path / "khong-co") is None
