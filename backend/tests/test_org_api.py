"""Đợt 5 phân quyền: kịch bản Công ty ABC đi trọn qua API /api/org (SQLite cùng mô hình).

An tạo công ty, mời Bình làm Trưởng phòng Kinh doanh; Bình mời Chi; Dũng vào bằng mã và chờ duyệt;
Chi nộp tài liệu với mức mật; chia sẻ; Chi nghỉ việc và bản nháp được bàn giao; An chuyển quyền Chủ.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.org import JOIN_FAILURE_LIMIT, build_router
from app.storage.postgres.base import Base
from app.storage.postgres.models import OrgInviteRecord, UserRecord
from app.storage.postgres.runtime import PostgresSourceStore

PEOPLE = ["an", "binh", "chi", "dung", "em"]


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    def _connect(conn, _):
        conn.create_function("btrim", 1, lambda v: None if v is None else v.strip())
        conn.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", _connect)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as s:
        s.add_all([UserRecord(user_id=p, email=f"{p}@x.vn", display_name=p.title(), password_hash="x") for p in PEOPLE])
        s.execute(text("CREATE TABLE studio_workspace_items (workspace_id TEXT, item_type TEXT, item_id TEXT)"))
        s.execute(text("CREATE TABLE studio_activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id TEXT, "
                       "action TEXT, target TEXT, status INTEGER, created_at TEXT)"))
    app = FastAPI()
    app.include_router(build_router(current_user=lambda request: {"user_id": request.headers["x-user"]},
                                    session_factory=lambda: factory))
    raw = TestClient(app)

    class As:
        def __init__(self, user): self.user = user
        def __getattr__(self, method):
            return lambda url, **kw: getattr(raw, method)(url, headers={"x-user": self.user}, **kw)

    return factory, {p: As(p) for p in PEOPLE}


def _setup_company(factory, u):
    sp = u["an"].post("/api/org/spaces", json={"name": "Công ty ABC", "departments": ["Kinh doanh", "Kế toán"]}).json()["space_id"]
    deps = {d["name"]: d["department_id"] for d in u["an"].get(f"/api/org/spaces/{sp}").json()["departments"]}
    kd, kt = deps["Kinh doanh"], deps["Kế toán"]
    inv = u["an"].post(f"/api/org/spaces/{sp}/invites",
                       json={"kind": "USER", "email": "BINH@x.vn", "level": "MANAGER", "department_id": kd}).json()["invite_id"]
    assert u["binh"].post(f"/api/org/invites/{inv}/accept").status_code == 200
    inv = u["binh"].post(f"/api/org/spaces/{sp}/invites",
                         json={"kind": "USER", "email": "chi@x.vn", "level": "STAFF", "department_id": kd}).json()["invite_id"]
    assert u["chi"].post(f"/api/org/invites/{inv}/accept").status_code == 200
    return sp, kd, kt


def _upload(factory, user, name):
    return PostgresSourceStore(factory, user).import_text(name, f"Nội dung {name}.")["source_id"]


def test_create_and_invite_by_account(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    me = {s["space_id"]: s for s in u["binh"].get("/api/org/spaces").json()}[sp]
    assert (me["level"], me["department_id"], me["status"]) == ("MANAGER", kd, "ACTIVE")
    owner = u["an"].get("/api/org/spaces").json()[0]
    assert owner["is_owner"] and owner["level"] == "EXECUTIVE"
    # Trưởng phòng chỉ mời Nhân viên vào phòng mình; Nhân viên không mời được
    bad = [
        u["binh"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "USER", "email": "dung@x.vn", "level": "MANAGER", "department_id": kd}),
        u["binh"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "USER", "email": "dung@x.vn", "level": "STAFF", "department_id": kt}),
        u["chi"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "USER", "email": "dung@x.vn", "level": "STAFF", "department_id": kd}),
        u["chi"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "CODE"}),
    ]
    assert [r.status_code for r in bad] == [403, 403, 403, 403]
    assert u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "USER", "email": "khong@x.vn", "department_id": kd}).status_code == 404
    assert u["an"].post(f"/api/org/spaces/{sp}/invites",
                        json={"kind": "USER", "email": "chi@x.vn", "department_id": kd}).status_code == 409
    # lời mời chỉ dùng một lần, chỉ đúng người được mời
    inv = u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "USER", "email": "em@x.vn", "department_id": kt}).json()["invite_id"]
    assert u["dung"].post(f"/api/org/invites/{inv}/accept").status_code == 404
    assert [i["invite_id"] for i in u["em"].get("/api/org/invites").json()] == [inv]
    assert u["em"].post(f"/api/org/invites/{inv}/decline").status_code == 200
    assert u["em"].post(f"/api/org/invites/{inv}/accept").status_code == 404
    kinds = [n["kind"] for n in u["an"].get("/api/org/notifications").json()["items"]]
    assert "invite_accepted" in kinds and "invite_declined" in kinds


def test_join_by_code_waits_for_approval(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    created = u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "CODE", "max_uses": 2}).json()
    code = created["token"]
    with factory() as s:  # chỉ lưu mã băm
        assert code.replace("-", "") not in str(s.get(OrgInviteRecord, created["invite_id"]).token_hash)
    joined = u["dung"].post("/api/org/join", json={"token": code.lower().replace("-", " ")})
    assert joined.status_code == 200 and joined.json()["status"] == "PENDING"
    assert u["dung"].get(f"/api/org/spaces/{sp}").status_code == 403  # chờ duyệt thì chưa vào được
    assert u["dung"].post("/api/org/join", json={"token": code}).status_code == 409
    assert any(n["kind"] == "join_request" for n in u["an"].get("/api/org/notifications").json()["items"])
    # Trưởng phòng Kinh doanh không duyệt người vào Kế toán, cũng không gán cấp Trưởng phòng
    assert u["binh"].post(f"/api/org/spaces/{sp}/members/dung/approve", json={"level": "MANAGER", "department_id": kt}).status_code == 403
    assert u["binh"].post(f"/api/org/spaces/{sp}/members/dung/approve", json={"level": "STAFF", "department_id": kt}).status_code == 403
    # Nhân viên không thấy yêu cầu chờ duyệt
    assert all(m["status"] == "ACTIVE" for m in u["chi"].get(f"/api/org/spaces/{sp}").json()["members"])
    ok = u["an"].post(f"/api/org/spaces/{sp}/members/dung/approve", json={"level": "MANAGER", "department_id": kt})
    assert ok.status_code == 200 and u["dung"].get(f"/api/org/spaces/{sp}").json()["me"]["level"] == "MANAGER"
    assert any(n["kind"] == "join_approved" for n in u["dung"].get("/api/org/notifications").json()["items"])


def test_link_revoke_and_limits(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    link = u["binh"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "LINK", "max_uses": 1}).json()
    assert u["dung"].post("/api/org/join", json={"token": link["token"]}).status_code == 200
    assert u["em"].post("/api/org/join", json={"token": link["token"]}).status_code == 404  # hết lượt
    # Bình tạo link nên yêu cầu gắn phòng Kinh doanh: Bình duyệt được
    assert u["binh"].post(f"/api/org/spaces/{sp}/members/dung/approve", json={"level": "STAFF", "department_id": kd}).status_code == 200
    other = u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "LINK"}).json()
    assert u["an"].delete(f"/api/org/spaces/{sp}/invites/{other['invite_id']}").status_code == 200
    assert u["em"].post("/api/org/join", json={"token": other["token"]}).status_code == 404  # đã thu hồi


def test_join_guessing_is_rate_limited(env):
    factory, u = env
    for _ in range(JOIN_FAILURE_LIMIT):
        assert u["em"].post("/api/org/join", json={"token": "SAI0-SAI0"}).status_code == 404
    assert u["em"].post("/api/org/join", json={"token": "SAI0-SAI0"}).status_code == 429


def test_documents_publish_change_share(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    code = u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "CODE"}).json()["token"]
    u["dung"].post("/api/org/join", json={"token": code})
    u["an"].post(f"/api/org/spaces/{sp}/members/dung/approve", json={"level": "MANAGER", "department_id": kt})

    report = _upload(factory, "chi", "bao_cao.txt")
    price = _upload(factory, "chi", "bang_gia.txt")
    assert u["chi"].post(f"/api/org/spaces/{sp}/sources/{report}/publish", json={"classification": "COMPANY"}).status_code == 403
    assert u["binh"].post(f"/api/org/spaces/{sp}/sources/{report}/publish", json={"classification": "RESTRICTED"}).status_code == 404  # không phải của Bình
    r = u["chi"].post(f"/api/org/spaces/{sp}/sources/{report}/publish", json={"classification": "RESTRICTED"})
    assert r.status_code == 200 and r.json()["department_id"] == kd  # tự gắn phòng của người nộp
    u["chi"].post(f"/api/org/spaces/{sp}/sources/{price}/publish", json={"classification": "DEPARTMENT"})
    assert PostgresSourceStore(factory, "chi").list_sources() == []  # đã rời phạm vi cá nhân

    names = lambda who: {s["source_id"] for s in u[who].get(f"/api/org/spaces/{sp}/sources").json()}
    assert names("binh") == {report, price} and names("dung") == set() and names("an") == {report, price}
    # người tải lên không tự hạ mức; Trưởng phòng hạ được; Trưởng phòng khác không thấy nên 404
    assert u["chi"].patch(f"/api/org/spaces/{sp}/sources/{report}", json={"classification": "DEPARTMENT"}).status_code == 403
    assert u["dung"].patch(f"/api/org/spaces/{sp}/sources/{report}", json={"classification": "DEPARTMENT"}).status_code == 404
    assert u["binh"].patch(f"/api/org/spaces/{sp}/sources/{report}", json={"classification": "DEPARTMENT"}).status_code == 200
    assert u["binh"].patch(f"/api/org/spaces/{sp}/sources/{report}", json={"department_id": kt}).status_code == 403
    # chia sẻ
    assert u["chi"].post(f"/api/org/spaces/{sp}/sources/{price}/shares", json={"department_id": kt}).status_code == 403
    assert u["binh"].post(f"/api/org/spaces/{sp}/sources/{price}/shares", json={"department_id": kt}).status_code == 200
    assert u["binh"].post(f"/api/org/spaces/{sp}/sources/{price}/shares", json={"department_id": kt}).status_code == 409
    assert names("dung") == {price}
    note = u["dung"].get("/api/org/notifications").json()["items"][0]
    assert note["kind"] == "source_shared" and note["payload"]["source_name"] == "bang_gia.txt"
    share_id = u["binh"].get(f"/api/org/spaces/{sp}/sources/{price}/shares").json()[0]["share_id"]
    assert u["chi"].delete(f"/api/org/spaces/{sp}/shares/{share_id}").status_code == 403
    assert u["binh"].delete(f"/api/org/spaces/{sp}/shares/{share_id}").status_code == 200
    assert names("dung") == set()


def test_removal_hands_over_drafts(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    draft = _upload(factory, "chi", "nhap.txt")
    u["chi"].post(f"/api/org/spaces/{sp}/sources/{draft}/publish", json={"classification": "PRIVATE"})
    assert draft not in {s["source_id"] for s in u["binh"].get(f"/api/org/spaces/{sp}/sources").json()}
    assert u["binh"].delete(f"/api/org/spaces/{sp}/members/chi", params={"handover_to": "chi"}).status_code == 422
    r = u["binh"].delete(f"/api/org/spaces/{sp}/members/chi")
    assert r.status_code == 200 and r.json() == {"removed": "chi", "handed_over_to": "binh", "drafts": 1}
    assert draft in {s["source_id"] for s in u["binh"].get(f"/api/org/spaces/{sp}/sources").json()}
    assert u["chi"].get("/api/org/spaces").json() == []
    assert u["chi"].get(f"/api/org/spaces/{sp}/sources").status_code == 403
    assert any(n["kind"] == "member_removed" for n in u["chi"].get("/api/org/notifications").json()["items"])
    assert u["binh"].delete(f"/api/org/spaces/{sp}/members/an").status_code == 403


def test_owner_guards_and_transfer(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    assert u["an"].post(f"/api/org/spaces/{sp}/leave").status_code == 403  # Chủ cuối cùng
    assert u["an"].patch(f"/api/org/spaces/{sp}/members/binh", json={"level": "MANAGER", "department_id": kd, "is_owner": True}).status_code == 403
    assert u["binh"].patch(f"/api/org/spaces/{sp}/members/chi", json={"level": "MANAGER", "department_id": kd}).status_code == 403
    assert u["an"].patch(f"/api/org/spaces/{sp}/members/binh", json={"level": "EXECUTIVE", "is_owner": True}).status_code == 200
    assert u["an"].post(f"/api/org/spaces/{sp}/leave").status_code == 200
    assert u["binh"].get(f"/api/org/spaces/{sp}").json()["me"] == {"level": "EXECUTIVE", "department_id": None, "is_owner": True}


def test_departments_and_notifications(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    assert u["binh"].post(f"/api/org/spaces/{sp}/departments", json={"name": "Nhân sự"}).status_code == 403
    assert u["an"].post(f"/api/org/spaces/{sp}/departments", json={"name": "Kế toán"}).status_code == 409
    assert u["an"].delete(f"/api/org/spaces/{sp}/departments/{kd}").status_code == 409  # còn người
    assert u["an"].delete(f"/api/org/spaces/{sp}/departments/{kt}").status_code == 200
    feed = u["chi"].get("/api/org/notifications").json()
    assert feed["unread"] >= 1
    assert u["chi"].post("/api/org/notifications/read", json={"all": True}).json()["marked"] == feed["unread"]
    assert u["chi"].get("/api/org/notifications").json()["unread"] == 0
    assert u["em"].get(f"/api/org/spaces/{sp}").status_code == 403  # người ngoài


def test_publish_masks_file_name_in_admin_audit_log(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    secret = _upload(factory, "an", "ke_hoach_sap_nhap.txt")
    personal = _upload(factory, "an", "ghi_chu_rieng.txt")
    with factory.begin() as s:  # nhật ký ghi lúc tải lên (middleware trong app.main)
        for name in ("ke_hoach_sap_nhap.txt", "ghi_chu_rieng.txt"):
            s.execute(text("INSERT INTO studio_activity (owner_user_id, action, target, status) VALUES ('an', 'Nạp tài liệu', :t, 200)"), {"t": name})
    assert u["an"].post(f"/api/org/spaces/{sp}/sources/{secret}/publish", json={"classification": "SECRET"}).status_code == 200
    with factory() as s:
        targets = {r[0] for r in s.execute(text("SELECT target FROM studio_activity"))}
    assert targets == {"(tài liệu tổ chức)", "ghi_chu_rieng.txt"}  # tài liệu cá nhân giữ nguyên tên
    assert personal


def test_new_document_notifies_only_people_who_can_now_see_it(env):
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)
    code = u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "CODE"}).json()["token"]
    u["dung"].post("/api/org/join", json={"token": code})
    u["an"].post(f"/api/org/spaces/{sp}/members/dung/approve", json={"level": "MANAGER", "department_id": kt})

    def seen(who, kind):
        items = u[who].get("/api/org/notifications").json()["items"]
        return [n["payload"]["source_name"] for n in items if n["kind"] == kind]

    price = _upload(factory, "chi", "bang_gia.txt")
    u["chi"].post(f"/api/org/spaces/{sp}/sources/{price}/publish", json={"classification": "DEPARTMENT"})
    report = _upload(factory, "chi", "bao_cao.txt")
    u["chi"].post(f"/api/org/spaces/{sp}/sources/{report}/publish", json={"classification": "RESTRICTED"})
    secret = _upload(factory, "an", "sap_nhap.txt")
    u["an"].post(f"/api/org/spaces/{sp}/sources/{secret}/publish", json={"classification": "SECRET"})

    # Nội bộ phòng: phòng Kinh doanh và Ban giám đốc; Hạn chế: Trưởng phòng Kinh doanh và Ban giám đốc; Mật: không ai khác
    assert seen("binh", "source_published") == ["bao_cao.txt", "bang_gia.txt"]
    assert seen("an", "source_published") == ["bao_cao.txt", "bang_gia.txt"]
    assert seen("dung", "source_published") == [] and seen("chi", "source_published") == []
    note = next(n for n in u["binh"].get("/api/org/notifications").json()["items"] if n["kind"] == "source_published")
    assert note["payload"]["by"] == "Chi" and note["payload"]["classification"] == "RESTRICTED" and note["payload"]["department"] == "Kinh doanh"

    # đổi mức mật: chỉ người VỪA được quyền xem mới nhận thông báo
    u["binh"].patch(f"/api/org/spaces/{sp}/sources/{report}", json={"classification": "DEPARTMENT"})
    assert all(seen(p, "source_access_granted") == [] for p in ("an", "binh", "chi", "dung"))
    u["an"].patch(f"/api/org/spaces/{sp}/sources/{secret}", json={"classification": "COMPANY"})
    assert [p for p in ("an", "binh", "chi", "dung") if seen(p, "source_access_granted") == ["sap_nhap.txt"]] == ["binh", "chi", "dung"]
