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
    pend = u["dung"].get("/api/org/spaces").json()[0]
    assert pend["member_count"] is None and pend["members_preview"] == [] and pend["doc_count"] is None  # chưa duyệt: không lộ gì
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
    assert u["an"].post(f"/api/org/spaces/{sp}/leave").status_code == 409  # Chủ cuối cùng: chặn kèm lý do rõ
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


def test_preset_only_renames_never_changes_access(env):
    """Đợt A đa lĩnh vực: mẫu tổ chức và tên tự đặt chỉ là nhãn; quyền xem phải y hệt doanh nghiệp."""
    factory, u = env
    sp, kd, _ = _setup_company(factory, u)
    detail = u["an"].get(f"/api/org/spaces/{sp}").json()
    assert detail["preset"] == "business" and detail["labels"] is None  # không gian cũ giữ nguyên chữ

    src = _upload(factory, "chi", "baocao.txt")
    assert u["chi"].post(f"/api/org/spaces/{sp}/sources/{src}/publish",
                         json={"classification": "DEPARTMENT", "department_id": kd}).status_code == 200

    def seen():
        return {p: src in {s["source_id"] for s in u[p].get(f"/api/org/spaces/{sp}/sources").json()}
                for p in ("an", "binh", "chi")}

    before = seen()
    r = u["an"].patch(f"/api/org/spaces/{sp}", json={"preset": "school", "labels": {"unit": "  Bộ môn ", "STAFF": ""}})
    assert r.status_code == 200 and r.json()["preset"] == "school" and r.json()["labels"] == {"unit": "Bộ môn"}
    assert seen() == before
    listed = {s["space_id"]: s for s in u["binh"].get("/api/org/spaces").json()}[sp]
    assert listed["preset"] == "school" and listed["labels"] == {"unit": "Bộ môn"}

    # chỉ Ban giám đốc đổi được mẫu; mẫu lạ và nhãn quá dài bị từ chối
    assert u["binh"].patch(f"/api/org/spaces/{sp}", json={"preset": "team"}).status_code == 403
    assert u["an"].patch(f"/api/org/spaces/{sp}", json={"preset": "army"}).status_code == 422
    assert u["an"].patch(f"/api/org/spaces/{sp}", json={"labels": {"unit": "x" * 41}}).status_code == 422
    assert u["an"].patch(f"/api/org/spaces/{sp}", json={"labels": {"role": "x"}}).status_code == 422
    assert u["an"].patch(f"/api/org/spaces/{sp}", json={"labels": None}).json()["labels"] is None


def test_create_space_with_preset_and_invite_shows_it(env):
    factory, u = env
    sp = u["an"].post("/api/org/spaces", json={"name": "Trường X", "departments": ["CNTT"], "preset": "custom",
                                               "labels": {"org": "viện", "EXECUTIVE": "Hội đồng viện"}}).json()["space_id"]
    dep = u["an"].get(f"/api/org/spaces/{sp}").json()["departments"][0]["department_id"]
    u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "USER", "email": "em@x.vn", "level": "STAFF", "department_id": dep})
    inv = u["em"].get("/api/org/invites").json()[0]
    assert inv["preset"] == "custom" and inv["labels"] == {"org": "viện", "EXECUTIVE": "Hội đồng viện"}


def test_single_unit_team_defaults_to_the_only_unit(env):
    """Đợt B: nhóm chỉ có một đơn vị; Trưởng nhóm (không thuộc đơn vị) đặt mức Nội bộ vẫn gắn đúng đơn vị đó."""
    factory, u = env
    sp = u["an"].post("/api/org/spaces", json={"name": "CLB", "departments": ["Chung"], "preset": "team"}).json()["space_id"]
    assert {s["space_id"]: s for s in u["an"].get("/api/org/spaces").json()}[sp]["unit_count"] == 1
    assert {s["space_id"]: s for s in u["an"].get("/api/org/spaces").json()}[sp]["member_count"] == 1
    dep = u["an"].get(f"/api/org/spaces/{sp}").json()["departments"][0]["department_id"]
    inv = u["an"].post(f"/api/org/spaces/{sp}/invites",
                       json={"kind": "USER", "email": "em@x.vn", "level": "STAFF", "department_id": dep}).json()["invite_id"]
    assert u["em"].post(f"/api/org/invites/{inv}/accept").status_code == 200
    src = _upload(factory, "an", "noiquy.txt")
    assert u["an"].post(f"/api/org/spaces/{sp}/sources/{src}/publish", json={"classification": "DEPARTMENT"}).status_code == 200
    row = {s["source_id"]: s for s in u["em"].get(f"/api/org/spaces/{sp}/sources").json()}[src]
    assert row["department_id"] == dep

    # có từ hai đơn vị trở lên thì không đoán: Trưởng nhóm phải chọn đơn vị
    u["an"].post(f"/api/org/spaces/{sp}/departments", json={"name": "Kỹ thuật"})
    src2 = _upload(factory, "an", "khac.txt")
    assert u["an"].post(f"/api/org/spaces/{sp}/sources/{src2}/publish", json={"classification": "DEPARTMENT"}).status_code != 200


# ---------------- Đợt A + B: kiểm tra nghiệp vụ theo luồng, nhiều vai trò ----------------

def _seen(u, sp, who):
    return {s["source_name"] for s in u[who].get(f"/api/org/spaces/{sp}/sources").json()}


def _invite(u, sp, by, who, level, dep):
    inv = u[by].post(f"/api/org/spaces/{sp}/invites",
                     json={"kind": "USER", "email": f"{who}@x.vn", "level": level, "department_id": dep})
    assert inv.status_code == 200, inv.text
    assert u[who].post(f"/api/org/invites/{inv.json()['invite_id']}/accept").status_code == 200


def _publish(factory, u, sp, who, name, level, **extra):
    src = _upload(factory, who, name)
    r = u[who].post(f"/api/org/spaces/{sp}/sources/{src}/publish", json={"classification": level, **extra})
    assert r.status_code == 200, (name, r.text)
    return src


@pytest.mark.parametrize("preset", ["business", "school", "hospital", "government", "team", "custom"])
def test_every_preset_has_the_same_access_matrix(env, preset):
    """Đổi lĩnh vực chỉ đổi cách gọi: bảng ai-xem-được-gì phải y hệt với mọi lĩnh vực."""
    factory, u = env
    sp = u["an"].post("/api/org/spaces", json={"name": "X", "departments": ["A", "B"], "preset": preset,
                                               "labels": {"unit": "nhóm"} if preset == "custom" else None}).json()["space_id"]
    deps = {d["name"]: d["department_id"] for d in u["an"].get(f"/api/org/spaces/{sp}").json()["departments"]}
    _invite(u, sp, "an", "binh", "MANAGER", deps["A"])
    _invite(u, sp, "binh", "chi", "STAFF", deps["A"])
    _invite(u, sp, "an", "dung", "STAFF", deps["B"])
    _publish(factory, u, sp, "an", "toan.txt", "COMPANY")
    _publish(factory, u, sp, "chi", "noibo.txt", "DEPARTMENT")
    _publish(factory, u, sp, "binh", "hanche.txt", "RESTRICTED")
    _publish(factory, u, sp, "an", "mat.txt", "SECRET")
    _publish(factory, u, sp, "chi", "nhap.txt", "PRIVATE")
    assert _seen(u, sp, "an") == {"toan.txt", "noibo.txt", "hanche.txt", "mat.txt"}
    assert _seen(u, sp, "binh") == {"toan.txt", "noibo.txt", "hanche.txt"}
    assert _seen(u, sp, "chi") == {"toan.txt", "noibo.txt", "nhap.txt"}
    assert _seen(u, sp, "dung") == {"toan.txt"}


def test_team_single_unit_whole_lifecycle(env):
    """Nhóm nhỏ một tổ: mời, vào bằng mã, tải lên không chọn tổ, đổi mức, rồi chia thêm tổ mà không ai mất quyền."""
    factory, u = env
    sp = u["an"].post("/api/org/spaces", json={"name": "CLB", "departments": ["Tổ chung"], "preset": "team"}).json()["space_id"]
    only = u["an"].get(f"/api/org/spaces/{sp}").json()["departments"][0]["department_id"]
    _invite(u, sp, "an", "binh", "MANAGER", only)
    _invite(u, sp, "binh", "chi", "STAFF", only)  # Tổ trưởng mời được Thành viên vào tổ mình
    code = u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "CODE"}).json()["token"]
    u["dung"].post("/api/org/join", json={"token": code})
    assert u["binh"].post(f"/api/org/spaces/{sp}/members/dung/approve", json={"level": "STAFF", "department_id": only}).status_code == 200

    # không ai phải chọn tổ: hệ thống gắn vào tổ duy nhất, kể cả Trưởng nhóm (không thuộc tổ nào)
    _publish(factory, u, sp, "chi", "lich_hop.txt", "DEPARTMENT")
    _publish(factory, u, sp, "an", "noi_quy.txt", "DEPARTMENT")
    _publish(factory, u, sp, "binh", "luong.txt", "RESTRICTED")
    toan = _publish(factory, u, sp, "an", "thong_bao.txt", "COMPANY")
    for who in ("an", "binh", "chi", "dung"):
        assert {"lich_hop.txt", "noi_quy.txt", "thong_bao.txt"} <= _seen(u, sp, who)
    assert "luong.txt" in _seen(u, sp, "an") and "luong.txt" in _seen(u, sp, "binh")
    assert "luong.txt" not in _seen(u, sp, "chi") | _seen(u, sp, "dung")

    # Trưởng nhóm hạ "Toàn nhóm" xuống "Hạn chế": tài liệu chưa có tổ thì gắn tổ duy nhất thay vì báo lỗi khó hiểu
    r = u["an"].patch(f"/api/org/spaces/{sp}/sources/{toan}", json={"classification": "RESTRICTED"})
    assert r.status_code == 200 and r.json()["department_id"] == only
    assert "thong_bao.txt" not in _seen(u, sp, "chi")

    # chia thêm tổ: tài liệu "Toàn nhóm" (mức Nội bộ) vẫn cho mọi người, kể cả người của tổ mới
    assert u["an"].post(f"/api/org/spaces/{sp}/departments", json={"name": "Kỹ thuật"}).status_code == 200
    kt = {d["name"]: d["department_id"] for d in u["an"].get(f"/api/org/spaces/{sp}").json()["departments"]}["Kỹ thuật"]
    _invite(u, sp, "an", "em", "STAFF", kt)
    for who in ("an", "binh", "chi", "dung", "em"):
        assert {"lich_hop.txt", "noi_quy.txt"} <= _seen(u, sp, who), who
    assert "luong.txt" not in _seen(u, sp, "em")  # Hạn chế vẫn chỉ Tổ trưởng của tổ cũ và Trưởng nhóm
    # tài liệu Nội bộ đặt SAU khi đã chia tổ thì đúng nghĩa hẹp
    _publish(factory, u, sp, "chi", "rieng_to_chung.txt", "DEPARTMENT")
    assert "rieng_to_chung.txt" in _seen(u, sp, "dung") and "rieng_to_chung.txt" not in _seen(u, sp, "em")

    # còn người thì không xóa được tổ; thông báo không dùng chữ của doanh nghiệp
    r = u["an"].delete(f"/api/org/spaces/{sp}/departments/{kt}")
    assert r.status_code == 409 and "phòng" not in r.json()["detail"]
    r = u["chi"].post(f"/api/org/spaces/{sp}/departments", json={"name": "Y"})
    assert r.status_code == 403 and "Ban giám đốc" not in r.json()["detail"]


def test_unit_level_on_document_without_unit_in_multi_unit_space(env):
    """Nhiều đơn vị, lãnh đạo không thuộc đơn vị nào: không đoán đơn vị, báo rõ; chọn đơn vị kèm theo thì được."""
    factory, u = env
    sp, kd, _ = _setup_company(factory, u)
    src = _publish(factory, u, sp, "an", "ke_hoach.txt", "COMPANY")
    r = u["an"].patch(f"/api/org/spaces/{sp}/sources/{src}", json={"classification": "DEPARTMENT"})
    assert r.status_code == 409 and "chọn đơn vị" in r.json()["detail"]
    r = u["an"].patch(f"/api/org/spaces/{sp}/sources/{src}", json={"classification": "DEPARTMENT", "department_id": kd})
    assert r.status_code == 200 and r.json()["department_id"] == kd
    assert "ke_hoach.txt" in _seen(u, sp, "chi")
    # Trưởng phòng hạ tài liệu Toàn công ty của mình: gắn phòng của chính mình
    src2 = _publish(factory, u, sp, "binh", "chi_tieu.txt", "COMPANY")
    r = u["binh"].patch(f"/api/org/spaces/{sp}/sources/{src2}", json={"classification": "RESTRICTED"})
    assert r.status_code == 200 and r.json()["department_id"] == kd


def test_audience_counts_match_who_really_sees_the_document(env):
    """Số người hiện trên thẻ chọn phạm vi phải bằng số người thật sự xem được sau khi tải lên."""
    factory, u = env
    sp, kd, kt = _setup_company(factory, u)  # an: Ban giám đốc; binh: Trưởng phòng KD; chi: Nhân viên KD
    _invite(u, sp, "an", "dung", "STAFF", kt)
    people = ("an", "binh", "chi", "dung")
    a = u["chi"].get(f"/api/org/spaces/{sp}/audience").json()
    assert a["total"] == 4 and a["unit_name"] == "Kinh doanh" and set(a["counts"]) == {"PRIVATE", "DEPARTMENT", "RESTRICTED"}
    for level, n in a["counts"].items():
        name = f"{level}.txt"
        _publish(factory, u, sp, "chi", name, level)
        assert sum(name in _seen(u, sp, p) for p in people) == n, level
    # Ban giám đốc không thuộc phòng, công ty nhiều phòng: mức cần phòng thì không đoán
    e = u["an"].get(f"/api/org/spaces/{sp}/audience").json()["counts"]
    assert e["DEPARTMENT"] is None and e["RESTRICTED"] is None and e["COMPANY"] == 4 and e["SECRET"] == 1
    assert u["em"].get(f"/api/org/spaces/{sp}/audience").status_code == 403


def test_sole_owner_cannot_leave_but_gets_a_clear_reason(env):
    factory, u = env
    sp, _, _ = _setup_company(factory, u)
    r = u["an"].post(f"/api/org/spaces/{sp}/leave")
    assert r.status_code == 409 and "chủ duy nhất" in r.json()["detail"]
    assert u["an"].get(f"/api/org/spaces/{sp}").status_code == 200  # vẫn còn trong tổ chức


def test_owner_deletes_space_removes_access_and_documents_keeps_record(env):
    factory, u = env
    sp, kd, _ = _setup_company(factory, u)
    _publish(factory, u, sp, "chi", "bao_cao.txt", "DEPARTMENT")
    code = u["an"].post(f"/api/org/spaces/{sp}/invites", json={"kind": "CODE"}).json()["token"]
    deleted_vectors = []

    class Store:
        def delete(self, ids): deleted_vectors.extend(ids)

    app = FastAPI()
    app.include_router(build_router(current_user=lambda request: {"user_id": request.headers["x-user"]},
                                    session_factory=lambda: factory, vector_store=lambda: Store()))
    c = TestClient(app)
    call = lambda who, body: c.request("DELETE", f"/api/org/spaces/{sp}", headers={"x-user": who}, json=body)

    assert call("binh", {"confirm_name": "Công ty ABC"}).status_code == 403  # không phải chủ
    assert call("an", {"confirm_name": "Công ty XYZ"}).status_code == 422  # gõ sai tên
    r = call("an", {"confirm_name": " Công ty ABC "})
    assert r.status_code == 200 and r.json()["sources_removed"] == 1 and r.json()["members_removed"] == 3
    assert deleted_vectors and all(v.startswith("chi:") for v in deleted_vectors)
    for who in ("an", "binh", "chi"):
        assert u[who].get("/api/org/spaces").json() == []
        assert u[who].get(f"/api/org/spaces/{sp}").status_code == 403
    assert u["dung"].post("/api/org/join", json={"token": code}).status_code == 404
    assert any(n["kind"] == "space_deleted" for n in u["chi"].get("/api/org/notifications").json()["items"])
    with factory() as s:
        from app.storage.postgres.models import KnowledgeSourceRecord, OrgSpaceRecord
        assert s.get(OrgSpaceRecord, sp).deleted_at is not None  # bản ghi giữ cho lượt chạy cũ
        assert s.query(KnowledgeSourceRecord).filter_by(space_id=sp).count() == 0


def test_space_list_preview_shows_members_and_my_visible_doc_count(env):
    factory, u = env
    sp, kd, _ = _setup_company(factory, u)
    _publish(factory, u, sp, "an", "mat.txt", "SECRET")
    _publish(factory, u, sp, "chi", "noibo.txt", "DEPARTMENT")
    an = {s["space_id"]: s for s in u["an"].get("/api/org/spaces").json()}[sp]
    chi = {s["space_id"]: s for s in u["chi"].get("/api/org/spaces").json()}[sp]
    assert an["members_preview"][0]["user_id"] == "an" and len(an["members_preview"]) == 3
    assert an["doc_count"] == 2 and chi["doc_count"] == 1  # số tài liệu theo đúng quyền xem của từng người
