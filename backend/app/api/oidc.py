"""Đăng nhập bằng tài khoản tổ chức qua OpenID Connect (Google, Microsoft) — Đợt 10, TẮT MẶC ĐỊNH.

Bật bằng biến môi trường (không có thì mọi đường /api/auth/oidc/* trả 404 và trang đăng nhập không hiện nút):
  OIDC_PROVIDERS=google,microsoft
  OIDC_GOOGLE_CLIENT_ID, OIDC_GOOGLE_CLIENT_SECRET            (issuer mặc định https://accounts.google.com)
  OIDC_MICROSOFT_CLIENT_ID, OIDC_MICROSOFT_CLIENT_SECRET, OIDC_MICROSOFT_TENANT (mặc định "organizations")
  OIDC_<TÊN>_ISSUER                                            (ghi đè issuer, ví dụ nhà cung cấp riêng)
  OIDC_REDIRECT_BASE=https://studio.congty.vn                  (địa chỉ công khai của máy chủ, để tạo redirect_uri)
  OIDC_ALLOWED_DOMAINS=congty.vn,truong.edu.vn                 (tùy chọn: chỉ nhận email thuộc các miền này)

Luồng: Authorization Code + PKCE (S256), state và nonce giữ trong cookie ký HMAC, sống 10 phút. Mã đổi lấy id_token
qua kênh sau (HTTPS tới token_endpoint); id_token được kiểm chữ ký RS256 bằng khóa JWKS của nhà cung cấp, iss, aud,
exp, nonce, email_verified. Không thêm thư viện: RSA PKCS#1 v1.5 + SHA-256 tính bằng pow() của Python.
Chưa thử với tài khoản Google/Microsoft thật (cần tổ chức đăng ký ứng dụng); đã thử với nhà cung cấp giả lập trong
tests/test_oidc.py.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

DEFAULT_ISSUERS = {"google": "https://accounts.google.com", "microsoft": "https://login.microsoftonline.com/{tenant}/v2.0"}
LABELS = {"google": "Google", "microsoft": "Microsoft"}
STATE_COOKIE = "oidc_state"
STATE_TTL = 600
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")  # DigestInfo của SHA-256 (RFC 8017)


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def providers_from_env(env: dict[str, str] | None = None) -> dict[str, dict[str, str]]:
    env = dict(os.environ if env is None else env)
    out = {}
    for name in [p.strip().lower() for p in env.get("OIDC_PROVIDERS", "").split(",") if p.strip()]:
        key = name.upper()
        cid, secret = env.get(f"OIDC_{key}_CLIENT_ID", ""), env.get(f"OIDC_{key}_CLIENT_SECRET", "")
        issuer = env.get(f"OIDC_{key}_ISSUER") or DEFAULT_ISSUERS.get(name, "").format(tenant=env.get(f"OIDC_{key}_TENANT", "organizations"))
        if cid and secret and issuer:  # thiếu cấu hình thì coi như chưa bật, không lộ lỗi ra người dùng
            out[name] = {"client_id": cid, "client_secret": secret, "issuer": issuer.rstrip("/"), "label": LABELS.get(name, name.capitalize())}
    return out


def verify_rs256(token: str, jwks: dict) -> dict:
    """Kiểm chữ ký RS256 của JWT bằng khóa trong JWKS; trả phần payload. Thuật toán khác RS256 bị từ chối."""
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        header = json.loads(_b64d(head_b64))
    except Exception as exc:
        raise ValueError("id_token không đúng định dạng") from exc
    if header.get("alg") != "RS256":
        raise ValueError("chỉ nhận chữ ký RS256")
    keys = [k for k in jwks.get("keys", []) if k.get("kty") == "RSA" and (not header.get("kid") or k.get("kid") == header.get("kid"))]
    if not keys:
        raise ValueError("không có khóa phù hợp trong JWKS")
    signed = f"{head_b64}.{body_b64}".encode()
    sig = int.from_bytes(_b64d(sig_b64), "big")
    for k in keys:
        n, e = int.from_bytes(_b64d(k["n"]), "big"), int.from_bytes(_b64d(k["e"]), "big")
        size = (n.bit_length() + 7) // 8
        if sig >= n:
            continue
        em = pow(sig, e, n).to_bytes(size, "big")
        digest = _SHA256_PREFIX + hashlib.sha256(signed).digest()
        expected = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
        if hmac.compare_digest(em, expected):
            return json.loads(_b64d(body_b64))
    raise ValueError("chữ ký id_token không hợp lệ")


def check_claims(claims: dict, *, issuer: str, client_id: str, nonce: str, now: float | None = None, allowed_domains: list[str] | None = None) -> str:
    now = time.time() if now is None else now
    aud = claims.get("aud")
    if claims.get("iss", "").rstrip("/") != issuer and not (issuer.endswith("/organizations/v2.0") and "login.microsoftonline.com" in claims.get("iss", "")):
        raise ValueError("iss không khớp")
    if client_id not in (aud if isinstance(aud, list) else [aud]):
        raise ValueError("aud không khớp")
    if float(claims.get("exp", 0)) < now - 60:
        raise ValueError("id_token đã hết hạn")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("nonce không khớp")
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if "@" not in email:
        raise ValueError("nhà cung cấp không trả email")
    if claims.get("email_verified") is False:
        raise ValueError("email chưa được nhà cung cấp xác minh")
    if allowed_domains and email.split("@")[-1] not in allowed_domains:
        raise ValueError("email không thuộc miền được phép")
    return email


def build_router(*, secret: bytes | None = None, http: Callable[[], httpx.Client] | None = None,
                 env: dict[str, str] | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/auth/oidc", tags=["auth"])
    key = secret or secrets.token_bytes(32)  # ký cookie trạng thái; mỗi tiến trình một khóa (state sống 10 phút)
    client = http or (lambda: httpx.Client(timeout=15))

    def conf() -> dict[str, dict[str, str]]:
        return providers_from_env(env)

    def provider(name: str) -> dict[str, str]:
        p = conf().get(name)
        if p is None:
            raise HTTPException(404, "Đăng nhập bằng tài khoản tổ chức chưa được bật cho nhà cung cấp này.")
        return p

    def discovery(p: dict[str, str]) -> dict[str, Any]:
        with client() as c:
            r = c.get(f"{p['issuer']}/.well-known/openid-configuration")
            r.raise_for_status()
            return r.json()

    def redirect_uri(request: Request, name: str) -> str:
        base = (env or os.environ).get("OIDC_REDIRECT_BASE") or str(request.base_url).rstrip("/")
        return f"{base.rstrip('/')}/api/auth/oidc/{name}/callback"

    def sign(data: dict) -> str:
        body = _b64e(json.dumps(data, separators=(",", ":")).encode())
        return f"{body}.{_b64e(hmac.new(key, body.encode(), hashlib.sha256).digest())}"

    def unsign(value: str | None) -> dict:
        try:
            body, mac = (value or "").split(".")
            if not hmac.compare_digest(mac, _b64e(hmac.new(key, body.encode(), hashlib.sha256).digest())):
                raise ValueError
            data = json.loads(_b64d(body))
        except Exception as exc:
            raise HTTPException(400, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Thử lại từ trang đăng nhập.") from exc
        if data.get("exp", 0) < time.time():
            raise HTTPException(400, "Phiên đăng nhập đã hết hạn. Thử lại từ trang đăng nhập.")
        return data

    @router.get("/providers")
    def list_providers() -> dict:
        return {"providers": [{"id": k, "label": v["label"]} for k, v in conf().items()]}

    @router.get("/{name}/start")
    def start(name: str, request: Request) -> RedirectResponse:
        p = provider(name)
        meta = discovery(p)
        state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        challenge = _b64e(hashlib.sha256(verifier.encode()).digest())
        url = meta["authorization_endpoint"] + "?" + urlencode({
            "response_type": "code", "client_id": p["client_id"], "redirect_uri": redirect_uri(request, name),
            "scope": "openid email profile", "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        resp = RedirectResponse(url, status_code=302)
        resp.set_cookie(STATE_COOKIE, sign({"p": name, "state": state, "nonce": nonce, "v": verifier, "exp": time.time() + STATE_TTL}),
                        max_age=STATE_TTL, httponly=True, samesite="lax", path="/api/auth/oidc",
                        secure=(env or os.environ).get("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"})
        return resp

    @router.get("/{name}/callback")
    def callback(name: str, request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
        p = provider(name)
        if error:
            return RedirectResponse(f"/login?sso_error={error[:60]}", status_code=302)
        saved = unsign(request.cookies.get(STATE_COOKIE))
        if saved.get("p") != name or not hmac.compare_digest(saved.get("state", ""), state) or not code:
            raise HTTPException(400, "Mã trạng thái không khớp. Thử lại từ trang đăng nhập.")
        meta = discovery(p)
        with client() as c:
            tok = c.post(meta["token_endpoint"], data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(request, name),
                "client_id": p["client_id"], "client_secret": p["client_secret"], "code_verifier": saved["v"],
            })
            if tok.status_code != 200 or "id_token" not in tok.json():
                raise HTTPException(401, "Nhà cung cấp từ chối đăng nhập.")
            jwks = c.get(meta["jwks_uri"]).json()
        domains = [d.strip().lower() for d in (env or os.environ).get("OIDC_ALLOWED_DOMAINS", "").split(",") if d.strip()]
        try:
            claims = verify_rs256(tok.json()["id_token"], jwks)
            email = check_claims(claims, issuer=p["issuer"], client_id=p["client_id"], nonce=saved["nonce"], allowed_domains=domains)
        except ValueError as exc:
            raise HTTPException(401, f"Không xác thực được tài khoản tổ chức: {exc}.") from exc
        store = request.app.state.auth_store
        user = store.find_or_create_sso_user(email=email, display_name=str(claims.get("name") or "")[:128] or None)
        token, _ = store.create_session(user["user_id"])
        resp = RedirectResponse("/studio", status_code=302)
        resp.delete_cookie(STATE_COOKIE, path="/api/auth/oidc")
        resp.set_cookie("session_token", token, httponly=True, samesite="lax", path="/",
                        secure=(env or os.environ).get("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"})
        return resp

    return router
