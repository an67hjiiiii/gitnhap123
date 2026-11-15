"""Nhật ký hoạt động: middleware chỉ ghi nhãn thao tác, đích (tên/ID) và mã trạng thái, không bao giờ ghi nội dung
câu hỏi hay nội dung tài liệu. Quyền ADMIN của các router mới được kiểm riêng ở test_admin_users/test_admin_system;
ở đây thêm kiểm trên app thật rằng route quản trị từ chối người dùng thường và ẩn khi chưa đăng nhập."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import dotenv
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.storage.postgres.base import Base

SECRET_QUESTION = "CAU-HOI-BI-MAT-ZXQ-12345 mức phạt hợp đồng là bao nhiêu?"
SECRET_BODY = "NOI-DUNG-TAI-LIEU-BI-MAT-QWV-98765 điều khoản bảo mật nội bộ."


@pytest.fixture()
def audited(monkeypatch, tmp_path, sf1_fake_provider_env, sf1_vector_store):
    import app.auth.store as auth_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(auth_module, "AuthStore", lambda *args: SimpleNamespace(
        resolve=lambda token: {"user_id": token, "role": "USER"}))
    for key, value in {"APP_STORAGE_BACKEND": "file", "APP_ENV": "test", "APP_DATA_DIR": str(tmp_path / "documents"),
                       "RUNS_DIR": str(tmp_path / "outputs"), "VECTOR_BACKEND": "memory"}.items():
        monkeypatch.setenv(key, value)
    name = "app._integration_audit_main"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app" / "main.py")
    main_module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, main_module)
    spec.loader.exec_module(main_module)
    monkeypatch.setattr(main_module, "_configured_vector_store", lambda: sf1_vector_store)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.create_function("btrim", 1, lambda v: None if v is None else v.strip()))
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE studio_activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id TEXT, "
            "action TEXT, target TEXT, status INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main_module.app.state, "session_factory", factory, raising=False)
    holder = {"role": "USER"}
    monkeypatch.setattr(main_module, "current_user",
                        lambda request: {"user_id": "u-audit", "role": holder["role"], "email": "a@x.vn"})
    client = TestClient(main_module.app, raise_server_exceptions=False)
    client.main = main_module
    return client, engine, holder


def _dump(engine) -> str:
    with engine.begin() as c:
        rows = c.execute(text("SELECT owner_user_id, action, target, status FROM studio_activity")).fetchall()
    return "\n".join("|".join(str(v) for v in r) for r in rows)


def test_audit_never_stores_question_or_document_text(audited):
    client, engine, _ = audited
    client.post("/api/chat", json={"message": SECRET_QUESTION, "product_mode": True})
    client.post("/api/sources/text", json={"source_name": "hop_dong.md", "text": SECRET_BODY})
    dump = _dump(engine)
    assert "Đặt câu hỏi" in dump and "Nạp tài liệu" in dump  # đã ghi thao tác
    assert "hop_dong.md" in dump                              # đích = tên tệp
    assert "ZXQ-12345" not in dump and "QWV-98765" not in dump
    assert SECRET_QUESTION not in dump and SECRET_BODY not in dump


def test_audit_target_is_truncated_and_columns_are_fixed(audited):
    client, engine, _ = audited
    client.post("/api/sources/text", json={"source_name": "x" * 500 + ".md", "text": SECRET_BODY})
    with engine.begin() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(studio_activity)")).fetchall()]
        target = c.execute(text("SELECT target FROM studio_activity")).scalar()
    assert cols == ["activity_id", "owner_user_id", "action", "target", "status", "created_at"]  # không có cột nội dung
    assert target is not None and len(target) <= 200


def test_unauthenticated_request_is_not_audited(audited, monkeypatch):
    client, engine, _ = audited

    def deny(request):
        raise client.main.HTTPException(401, "AUTHENTICATION_REQUIRED")

    monkeypatch.setattr(client.main, "current_user", deny)
    client.post("/api/chat", json={"message": SECRET_QUESTION})
    assert _dump(engine) == ""


def test_admin_routes_forbidden_for_normal_user_on_real_app(audited):
    client, _, holder = audited
    holder["role"] = "USER"
    for path in ("/api/admin/users", "/api/admin/system", "/api/admin/audit"):
        assert client.get(path).status_code == 403, path
    assert client.post("/api/admin/users", json={"email": "moi@x.vn"}).status_code == 403
