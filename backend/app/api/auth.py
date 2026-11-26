from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth.store import (
    AuthStore,
    DuplicateUserError,
    InvalidCredentialsError,
    InvalidSessionError,
)

LOGIN_FAILURE_LIMIT = int(os.getenv("LOGIN_FAILURE_LIMIT", "10"))
LOGIN_FAILURE_WINDOW_S = int(os.getenv("LOGIN_FAILURE_WINDOW_S", str(15 * 60)))
_login_failures: dict[tuple[str, str], list[float]] = {}
_login_lock = threading.Lock()


def reset_login_rate_limit() -> None:
    """Dùng cho kiểm thử tự động để xóa bộ đếm đăng nhập sai giữa các ca."""
    with _login_lock:
        _login_failures.clear()


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client and request.client.host else "unknown").strip()


def _check_login_rate_limit(key: tuple[str, str]) -> None:
    now = time.monotonic()
    with _login_lock:
        recent = [t for t in _login_failures.get(key, []) if now - t < LOGIN_FAILURE_WINDOW_S]
        if recent:
            _login_failures[key] = recent
        else:
            _login_failures.pop(key, None)
        if len(recent) >= LOGIN_FAILURE_LIMIT:
            retry_after = max(1, int(LOGIN_FAILURE_WINDOW_S - (now - recent[0])))
            raise HTTPException(
                status_code=429,
                detail="Bạn đã nhập sai mật khẩu quá nhiều lần. Vui lòng thử lại sau 15 phút.",
                headers={"Retry-After": str(retry_after)},
            )


def _record_login_failure(key: tuple[str, str]) -> None:
    now = time.monotonic()
    with _login_lock:
        recent = [t for t in _login_failures.get(key, []) if now - t < LOGIN_FAILURE_WINDOW_S]
        recent.append(now)
        _login_failures[key] = recent


def _clear_login_failures(key: tuple[str, str]) -> None:
    with _login_lock:
        _login_failures.pop(key, None)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    username: str | None = None
    display_name: str | None = Field(default=None, max_length=128)
    password: str = Field(min_length=8, max_length=1024)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str | None = None
    email: str | None = None
    username: str | None = None
    password: str = Field(min_length=1, max_length=1024)


class AvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avatar: str | None = Field(default=None, max_length=200_000)


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store


def get_session_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    header_token = request.headers.get("x-session-token", "").strip()
    if header_token:
        return header_token
    for cookie_name in ("session_token", "local_session"):
        token = request.cookies.get(cookie_name, "").strip()
        if token:
            return token
    return None


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request) -> dict[str, object]:
    store = get_auth_store(request)
    try:
        user = store.register(
            email=body.email,
            username=body.username,
            display_name=body.display_name,
            password=body.password,
        )
    except DuplicateUserError as exc:
        raise HTTPException(status_code=409, detail="Account already exists") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user}


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
) -> dict[str, object]:
    identifier = next(
        (
            value.strip()
            for value in (body.identifier, body.email, body.username)
            if isinstance(value, str) and value.strip()
        ),
        None,
    )
    if identifier is None:
        raise HTTPException(status_code=400, detail="Login identifier is required")

    rate_key = (_client_ip(request), identifier.casefold())
    _check_login_rate_limit(rate_key)
    try:
        user, token, session = get_auth_store(request).authenticate(
            identifier=identifier,
            password=body.password,
        )
    except InvalidCredentialsError as exc:
        _record_login_failure(rate_key)
        raise HTTPException(
            status_code=401,
            detail="Invalid email, username, or password",
        ) from exc
    _clear_login_failures(rate_key)
    response.set_cookie(
        "session_token",
        token,
        httponly=True,
        # bật COOKIE_SECURE=true khi chạy sau HTTPS (máy chủ công ty); để false khi chạy http://127.0.0.1 trên máy cá nhân
        secure=os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"},
        samesite="lax",
        path="/",
    )
    payload: dict[str, object] = {
        "authenticated": True,
        "user": user,
        "session": session,
    }
    # Ở môi trường sản xuất chỉ phát phiên qua cookie HttpOnly để tránh rò token qua phản hồi JSON;
    # giữ nguyên ở development/test để không làm gãy công cụ và kịch bản kiểm thử hiện có.
    if os.getenv("APP_ENV", "development").strip().lower() != "production":
        payload.update({
            "token_type": "bearer",
            "access_token": token,
            "token": token,
        })
    return payload


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    get_auth_store(request).revoke(get_session_token(request))
    response.delete_cookie("session_token", path="/")
    response.delete_cookie("local_session", path="/")
    return {"ok": True, "authenticated": False}


@router.get("/session")
def current_session(request: Request) -> dict[str, object]:
    try:
        user = get_auth_store(request).resolve(get_session_token(request))
    except InvalidSessionError as exc:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required",
        ) from exc
    return {"authenticated": True, "user": user}


@router.put("/avatar")
def update_avatar(body: AvatarRequest, request: Request) -> dict[str, object]:
    """Tự đổi ảnh đại diện của chính mình (không có tham số user_id nên không sửa được ảnh người khác)."""
    store = get_auth_store(request)
    try:
        user = store.resolve(get_session_token(request))
    except InvalidSessionError as exc:
        raise HTTPException(status_code=401, detail="Authentication is required") from exc
    if not hasattr(store, "set_avatar"):
        raise HTTPException(status_code=501, detail="Kho tài khoản này không hỗ trợ ảnh đại diện")
    try:
        return {"user": store.set_avatar(str(user["user_id"]), body.avatar)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/profile")
def update_profile(body: ProfileUpdateRequest, request: Request) -> dict[str, object]:
    """Tự cập nhật tên hiển thị của chính mình."""
    store = get_auth_store(request)
    try:
        user = store.resolve(get_session_token(request))
    except InvalidSessionError as exc:
        raise HTTPException(status_code=401, detail="Authentication is required") from exc
    if not hasattr(store, "update_profile"):
        raise HTTPException(status_code=501, detail="Kho tài khoản này chưa hỗ trợ cập nhật hồ sơ")
    try:
        return {"user": store.update_profile(str(user["user_id"]), display_name=body.display_name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, request: Request) -> dict[str, object]:
    """Tự đổi mật khẩu (yêu cầu xác nhận mật khẩu hiện tại) và thu hồi các phiên đăng nhập khác."""
    store = get_auth_store(request)
    token = get_session_token(request)
    try:
        user = store.resolve(token)
    except InvalidSessionError as exc:
        raise HTTPException(status_code=401, detail="Authentication is required") from exc
    if not hasattr(store, "change_password"):
        raise HTTPException(status_code=501, detail="Kho tài khoản này chưa hỗ trợ đổi mật khẩu")
    try:
        revoked = store.change_password(
            str(user["user_id"]),
            current_password=body.current_password,
            new_password=body.new_password,
            keep_session_token=token,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "revoked_sessions": revoked}


@router.get("/sessions")
def list_sessions(request: Request) -> dict[str, object]:
    """Xem các phiên đăng nhập đang hoạt động của chính tài khoản này."""
    store = get_auth_store(request)
    token = get_session_token(request)
    try:
        user = store.resolve(token)
    except InvalidSessionError as exc:
        raise HTTPException(status_code=401, detail="Authentication is required") from exc
    if not hasattr(store, "list_sessions"):
        return {"sessions": []}
    return {"sessions": store.list_sessions(str(user["user_id"]), current_session_token=token)}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(request: Request) -> dict[str, object]:
    """Đăng xuất tất cả thiết bị/phiên khác, giữ nguyên phiên đang dùng."""
    store = get_auth_store(request)
    token = get_session_token(request)
    try:
        user = store.resolve(token)
    except InvalidSessionError as exc:
        raise HTTPException(status_code=401, detail="Authentication is required") from exc
    if not hasattr(store, "revoke_other_sessions"):
        return {"ok": True, "revoked_sessions": 0}
    revoked = store.revoke_other_sessions(str(user["user_id"]), keep_session_token=token)
    return {"ok": True, "revoked_sessions": revoked}
