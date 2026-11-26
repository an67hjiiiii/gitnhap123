from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.auth.store import AuthStore


def _make_client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.state.auth_store = AuthStore(root=tmp_path)
    app.include_router(auth_router)
    return TestClient(app)


def test_profile_update_change_password_and_session_management(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    reg = client.post(
        "/api/auth/register",
        json={"username": "tester01", "email": "tester01@example.com", "display_name": "Ban Đầu", "password": "Password@123"},
    )
    assert reg.status_code == 201

    login1 = client.post("/api/auth/login", json={"username": "tester01", "password": "Password@123"})
    assert login1.status_code == 200
    tok1 = login1.json()["access_token"]

    login2 = client.post("/api/auth/login", json={"username": "tester01", "password": "Password@123"})
    assert login2.status_code == 200
    tok2 = login2.json()["access_token"]

    # Cập nhật họ tên
    prof = client.put("/api/auth/profile", json={"display_name": "Nguyễn Minh An"}, headers={"Authorization": f"Bearer {tok1}"})
    assert prof.status_code == 200
    assert prof.json()["user"]["display_name"] == "Nguyễn Minh An"

    # Liệt kê 2 phiên hoạt động
    sess = client.get("/api/auth/sessions", headers={"Authorization": f"Bearer {tok1}"})
    assert sess.status_code == 200
    items = sess.json()["sessions"]
    assert len(items) == 2
    assert sum(1 for s in items if s["is_current"]) == 1

    # Sai mật khẩu hiện tại bị từ chối
    bad_pw = client.post(
        "/api/auth/change-password",
        json={"current_password": "WrongPassword", "new_password": "NewPassword@456"},
        headers={"Authorization": f"Bearer {tok1}"},
    )
    assert bad_pw.status_code == 400

    # Đổi mật khẩu thành công: giữ phiên tok1, thu hồi tok2
    ok_pw = client.post(
        "/api/auth/change-password",
        json={"current_password": "Password@123", "new_password": "NewPassword@456"},
        headers={"Authorization": f"Bearer {tok1}"},
    )
    assert ok_pw.status_code == 200
    assert ok_pw.json()["revoked_sessions"] == 1

    # tok1 còn sống, tok2 đã bị thu hồi
    assert client.get("/api/auth/session", headers={"Authorization": f"Bearer {tok1}"}).status_code == 200
    assert client.get("/api/auth/session", headers={"Authorization": f"Bearer {tok2}"}).status_code == 401

    # Đăng nhập bằng mật khẩu mới thành công, mật khẩu cũ thất bại
    assert client.post("/api/auth/login", json={"username": "tester01", "password": "Password@123"}).status_code == 401
    login3 = client.post("/api/auth/login", json={"username": "tester01", "password": "NewPassword@456"})
    assert login3.status_code == 200
    tok3 = login3.json()["access_token"]

    # Đăng xuất tất cả phiên khác từ tok3 -> tok1 bị thu hồi, tok3 còn sống
    rev = client.post("/api/auth/sessions/revoke-others", headers={"Authorization": f"Bearer {tok3}"})
    assert rev.status_code == 200
    assert rev.json()["revoked_sessions"] == 1
    assert client.get("/api/auth/session", headers={"Authorization": f"Bearer {tok1}"}).status_code == 401
    assert client.get("/api/auth/session", headers={"Authorization": f"Bearer {tok3}"}).status_code == 200
