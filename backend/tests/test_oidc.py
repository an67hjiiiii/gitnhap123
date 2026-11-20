"""Đợt 10: đăng nhập tổ chức OIDC thử với nhà cung cấp GIẢ LẬP (khóa RSA thử tạo riêng cho kiểm thử, không dùng ở đâu khác).
Chưa thử với Google/Microsoft thật."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.oidc import build_router, check_claims, providers_from_env, verify_rs256

# khóa RSA 2048 bit chỉ dùng trong kiểm thử (sinh bằng openssl 20/11)
N = 25056611280749741519991883682763566453372783772059301012564415692691116786913405610560055870043365702105782584879058854036470056051998059884219400993757121335453207001370062186053504561578932028064966805299595671903932225821121998822230481538705399800009522941985981092604726804442294873361693164780748805002010799179254328186740520140970179722703059745204301498683548937616453354162664201672466236798003281745180801536429677749804012098725928615858293085077568300874259476291090954360639847996821814968001861459515062963703233749281053098402095869046036847657924882405971592749364697277797630762398613013870926150777
D = 1928142374394633130021805515349453380819504158360270761399887733761438838252215645029873024834933454333732281601373885144497376611881861376109665417169173480856815210375962463157689535501108544886140222473718320531763444621921791157061080358880445886925167347456535498728775166129106206094906880777526888349446961656529581142070958043704037773435991352803339245182789158940209382492562215202993244751996756371190250788935737809962916783101863296627492953448684686016845577609346038961330038809669435577593594469237819609645600355771944749337139741026458942334922515808118440214123370120000352988332896471892683417385
E = 65537
ISS = "https://idp.thu.local"
ENV = {"OIDC_PROVIDERS": "google", "OIDC_GOOGLE_CLIENT_ID": "cid-thu", "OIDC_GOOGLE_CLIENT_SECRET": "bi-mat-thu",
       "OIDC_GOOGLE_ISSUER": ISS, "OIDC_REDIRECT_BASE": "http://testserver"}


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign(claims: dict, alg: str = "RS256", d: int = D) -> str:
    head = b64(json.dumps({"alg": alg, "kid": "k1"}).encode())
    body = b64(json.dumps(claims).encode())
    size = (N.bit_length() + 7) // 8
    digest = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(f"{head}.{body}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    return f"{head}.{body}.{b64(pow(int.from_bytes(em, 'big'), d, N).to_bytes(size, 'big'))}"


JWKS = {"keys": [{"kty": "RSA", "kid": "k1", "n": b64(N.to_bytes(256, "big")), "e": b64(E.to_bytes(3, "big"))}]}


def claims(nonce: str, **kw):
    return {"iss": ISS, "aud": "cid-thu", "exp": time.time() + 300, "nonce": nonce, "email": "nv@congty.vn", "email_verified": True, "name": "Nhân viên A", **kw}


def test_rs256_signature_and_claims():
    tok = sign(claims("n1"))
    assert verify_rs256(tok, JWKS)["email"] == "nv@congty.vn"
    with pytest.raises(ValueError):
        verify_rs256(tok[:-4] + "AAAA", JWKS)                       # chữ ký bị sửa
    with pytest.raises(ValueError):
        verify_rs256(sign(claims("n1"), alg="HS256"), JWKS)          # thuật toán khác
    c = claims("n1")
    assert check_claims(c, issuer=ISS, client_id="cid-thu", nonce="n1") == "nv@congty.vn"
    for bad in ({"aud": "khac"}, {"iss": "https://gia.local"}, {"exp": time.time() - 3600}, {"nonce": "x"}, {"email_verified": False}):
        with pytest.raises(ValueError):
            check_claims({**c, **bad}, issuer=ISS, client_id="cid-thu", nonce="n1")
    with pytest.raises(ValueError):
        check_claims(c, issuer=ISS, client_id="cid-thu", nonce="n1", allowed_domains=["truong.edu.vn"])


def test_off_by_default():
    assert providers_from_env({}) == {}
    assert providers_from_env({"OIDC_PROVIDERS": "google"}) == {}  # thiếu client id/secret: coi như chưa bật
    app = FastAPI()
    app.include_router(build_router(env={}))
    c = TestClient(app)
    assert c.get("/api/auth/oidc/providers").json() == {"providers": []}
    assert c.get("/api/auth/oidc/google/start", follow_redirects=False).status_code == 404


class Store:
    def __init__(self):
        self.users, self.sessions = {}, []

    def find_or_create_sso_user(self, *, email, display_name=None):
        return self.users.setdefault(email, {"user_id": f"u{len(self.users)}", "email": email})

    def create_session(self, user_id):
        self.sessions.append(user_id)
        return f"tok-{user_id}", {}


def make_app(id_claims_fn):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"authorization_endpoint": f"{ISS}/auth", "token_endpoint": f"{ISS}/token", "jwks_uri": f"{ISS}/jwks"})
        if req.url.path == "/jwks":
            return httpx.Response(200, json=JWKS)
        if req.url.path == "/token":
            form = parse_qs(req.content.decode())
            verifier = form["code_verifier"][0]
            ok = b64(hashlib.sha256(verifier.encode()).digest()) == seen["challenge"] and form["code"][0] == "ma-hop-le"
            return httpx.Response(200, json={"id_token": sign(id_claims_fn(seen["nonce"]))}) if ok else httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(404)

    app = FastAPI()
    app.state.auth_store = Store()
    app.include_router(build_router(secret=b"k" * 32, env=ENV, http=lambda: httpx.Client(transport=httpx.MockTransport(handler))))
    return app, seen


def start(c, seen):
    r = c.get("/api/auth/oidc/google/start", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    seen.update(nonce=q["nonce"][0], challenge=q["code_challenge"][0])
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"] == ["http://testserver/api/auth/oidc/google/callback"]
    return q["state"][0]


def test_full_login_flow_with_mock_provider():
    app, seen = make_app(lambda nonce: claims(nonce))
    c = TestClient(app)
    assert c.get("/api/auth/oidc/providers").json()["providers"] == [{"id": "google", "label": "Google"}]
    state = start(c, seen)
    r = c.get(f"/api/auth/oidc/google/callback?code=ma-hop-le&state={state}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/studio" and "session_token=tok-u0" in r.headers["set-cookie"]
    assert app.state.auth_store.users["nv@congty.vn"]["user_id"] == "u0"


def test_wrong_state_bad_code_and_forged_token_are_refused():
    app, seen = make_app(lambda nonce: claims(nonce))
    c = TestClient(app)
    state = start(c, seen)
    assert c.get("/api/auth/oidc/google/callback?code=ma-hop-le&state=gia", follow_redirects=False).status_code == 400
    assert c.get(f"/api/auth/oidc/google/callback?code=sai&state={state}", follow_redirects=False).status_code == 401
    fresh = TestClient(app)  # không có cookie trạng thái
    assert fresh.get(f"/api/auth/oidc/google/callback?code=ma-hop-le&state={state}", follow_redirects=False).status_code == 400
    app2, seen2 = make_app(lambda nonce: {**claims(nonce), "aud": "ung-dung-khac"})
    c2 = TestClient(app2)
    st2 = start(c2, seen2)
    r = c2.get(f"/api/auth/oidc/google/callback?code=ma-hop-le&state={st2}", follow_redirects=False)
    assert r.status_code == 401 and app2.state.auth_store.sessions == []
