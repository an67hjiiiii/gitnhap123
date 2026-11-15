"""API Quản lý người dùng (/api/admin/users), chỉ ADMIN dùng được.

Liệt kê tài khoản, tạo tài khoản (mật khẩu tạm nếu admin không đặt), đổi vai trò, khóa/mở khóa (khóa thì thu hồi mọi phiên),
đặt lại mật khẩu tạm, đăng xuất mọi phiên. Mật khẩu tạm chỉ trả về đúng một lần trong phản hồi, không lưu dạng rõ ở đâu.
Mọi thao tác ghi được nhật ký hoạt động ghi lại (xem _AUDITED trong app/main.py).
"""
from __future__ import annotations

import secrets
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.store import DuplicateUserError


class CreateUserBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str | None = None
    username: str | None = None
    display_name: str | None = Field(default=None, max_length=128)
    role: str = "USER"
    password: str | None = Field(default=None, min_length=8, max_length=1024)


class UpdateUserBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str | None = None
    status: str | None = None
    display_name: str | None = Field(default=None, max_length=128)


def build_router(*, current_user: Callable[[Request], dict]) -> APIRouter:
    router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])

    def admin(request: Request):
        user = current_user(request)
        if str(user.get("role", "")).upper() != "ADMIN":
            raise HTTPException(403, "Chỉ quản trị viên được dùng chức năng này.")
        store = request.app.state.auth_store
        if not hasattr(store, "admin_users"):
            raise HTTPException(501, "Quản lý người dùng cần chế độ lưu trữ PostgreSQL.")
        return user, store

    def label(u: dict) -> str:
        return str(u.get("email") or u.get("username") or u.get("user_id") or "")

    def target(request: Request, store, user_id: str) -> None:
        # ghi tên tài khoản bị tác động vào nhật ký (thay cho mã nội bộ khó đọc)
        found = next((u for u in store.admin_users() if u["user_id"] == user_id), None)
        if found is None:
            raise HTTPException(404, "Không tìm thấy tài khoản.")
        request.state.audit_target = label(found)

    @router.get("")
    def list_users(request: Request, q: str = ""):
        _, store = admin(request)
        users = store.admin_users(query=q)
        return {"users": users, "total": len(users),
                "admins_active": sum(1 for u in users if u["role"] == "ADMIN" and u["status"] == "ACTIVE")}

    @router.post("", status_code=201)
    def create_user(body: CreateUserBody, request: Request):
        _, store = admin(request)
        temporary = None if body.password else secrets.token_urlsafe(12)
        try:
            user = store.register(email=body.email, username=body.username, display_name=body.display_name,
                                  password=body.password or temporary, role=body.role)
        except DuplicateUserError as exc:
            raise HTTPException(409, "Email hoặc tên đăng nhập đã có tài khoản.") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        request.state.audit_target = label(user)
        return {"user": user, "temporary_password": temporary}

    @router.patch("/{user_id}")
    def update_user(user_id: str, body: UpdateUserBody, request: Request):
        actor, store = admin(request)
        target(request, store, user_id)
        try:
            user = store.admin_update_user(user_id, actor_id=str(actor["user_id"]), role=body.role,
                                           status=body.status, display_name=body.display_name)
        except KeyError as exc:
            raise HTTPException(404, "Không tìm thấy tài khoản.") from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"user": user}

    @router.post("/{user_id}/reset-password")
    def reset_password(user_id: str, request: Request):
        _, store = admin(request)
        target(request, store, user_id)
        user, temporary = store.admin_reset_password(user_id)
        return {"user": user, "temporary_password": temporary}

    @router.post("/{user_id}/revoke-sessions")
    def revoke_sessions(user_id: str, request: Request):
        _, store = admin(request)
        target(request, store, user_id)
        return {"revoked": store.admin_revoke_sessions(user_id)}

    return router
