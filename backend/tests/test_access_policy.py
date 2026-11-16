"""Đợt 2 phân quyền: kịch bản Công ty ABC chạy trên CSDL thật (SQLite cùng mô hình) và các luật thao tác.

Nhân vật: An (Ban giám đốc, Chủ), Bình (Trưởng phòng Kinh doanh), Chi (Nhân viên Kinh doanh),
Dũng (Trưởng phòng Kế toán), Em (Nhân viên Kế toán), Hà (chờ duyệt), Giang (không phải thành viên).
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.access import (
    Department,
    Member,
    Source,
    can_approve,
    can_change_classification,
    can_delete,
    can_invite,
    can_remove_member,
    can_share,
    can_update_member,
    can_upload,
    can_view,
    can_view_all,
    can_view_source_id,
    derived_classification,
    load_member,
    visible_source_ids,
)
from app.storage.postgres.base import Base
from app.storage.postgres.models import (
    KnowledgeSourceRecord,
    OrgDepartmentRecord,
    OrgMemberRecord,
    OrgSourceShareRecord,
    OrgSpaceRecord,
    UserRecord,
)

SP = "sp_abc"
PEOPLE = ["an", "binh", "chi", "dung", "em", "ha", "giang"]
DOCS = {
    # mã: (người tải lên, phòng, mức mật)
    "bang_gia": ("chi", "d_kd", "DEPARTMENT"),
    "bao_cao_chi": ("chi", "d_kd", "RESTRICTED"),
    "danh_gia_ns": ("binh", "d_kd", "RESTRICTED"),
    "sap_nhap": ("an", None, "SECRET"),
    "noi_quy": ("an", None, "COMPANY"),
    "nhap_chi": ("chi", "d_kd", "PRIVATE"),
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    def _connect(conn, _):
        conn.create_function("btrim", 1, lambda v: None if v is None else v.strip())
        conn.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", _connect)
    Base.metadata.create_all(engine)
    s = sessionmaker(engine)()
    s.add_all([UserRecord(user_id=p, email=f"{p}@x.vn", display_name=p, password_hash="x") for p in PEOPLE])
    s.flush()
    s.add_all([OrgSpaceRecord(space_id=SP, name="Công ty ABC"), OrgSpaceRecord(space_id="sp_khac", name="Công ty khác")])
    s.flush()
    s.add_all([
        OrgDepartmentRecord(department_id="d_kd", space_id=SP, name="Kinh doanh"),
        OrgDepartmentRecord(department_id="d_kt", space_id=SP, name="Kế toán"),
    ])
    s.flush()
    s.add_all([
        OrgMemberRecord(space_id=SP, user_id="an", level="EXECUTIVE", is_owner=True, status="ACTIVE"),
        OrgMemberRecord(space_id=SP, user_id="binh", department_id="d_kd", level="MANAGER", status="ACTIVE"),
        OrgMemberRecord(space_id=SP, user_id="chi", department_id="d_kd", level="STAFF", status="ACTIVE"),
        OrgMemberRecord(space_id=SP, user_id="dung", department_id="d_kt", level="MANAGER", status="ACTIVE"),
        OrgMemberRecord(space_id=SP, user_id="em", department_id="d_kt", level="STAFF", status="ACTIVE"),
        OrgMemberRecord(space_id=SP, user_id="ha", level="STAFF", status="PENDING"),
    ])
    for sid, (owner, dept, level) in DOCS.items():
        s.add(KnowledgeSourceRecord(source_id=sid, owner_user_id=owner, source_name=sid, space_id=SP,
                                    department_id=dept, classification=level, display_metadata={}))
    s.add(KnowledgeSourceRecord(source_id="ca_nhan_chi", owner_user_id="chi", source_name="x", display_metadata={}))
    s.add(KnowledgeSourceRecord(source_id="cty_khac", owner_user_id="giang", source_name="x", space_id="sp_khac",
                                classification="COMPANY", display_metadata={}))
    s.commit()
    yield s
    s.close()


# Bảng "ai thấy gì" đã chốt trong kế hoạch, mở rộng thêm Kế toán, người chờ duyệt và người ngoài.
EXPECTED = {
    "an": {"bang_gia", "bao_cao_chi", "danh_gia_ns", "sap_nhap", "noi_quy"},
    "binh": {"bang_gia", "bao_cao_chi", "danh_gia_ns", "noi_quy"},
    "chi": {"bang_gia", "bao_cao_chi", "noi_quy", "nhap_chi"},
    "dung": {"noi_quy"},
    "em": {"noi_quy"},
    "ha": set(),
    "giang": set(),
}


@pytest.mark.parametrize("person", PEOPLE)
def test_matrix(db, person):
    assert visible_source_ids(db, person, SP) == EXPECTED[person]


def test_personal_scope_unchanged(db):
    assert visible_source_ids(db, "chi") == {"ca_nhan_chi"}
    assert visible_source_ids(db, "an") == set()  # Ban giám đốc không thấy tài liệu cá nhân của nhân viên
    assert not can_view_source_id(db, "an", "ca_nhan_chi")
    assert can_view_source_id(db, "chi", "ca_nhan_chi")


def test_other_space_isolated(db):
    assert "cty_khac" not in visible_source_ids(db, "an", SP)
    assert visible_source_ids(db, "an", "sp_khac") == set()
    assert not can_view_source_id(db, "an", "cty_khac")
    assert not can_view_source_id(db, "an", "khong_ton_tai")


def test_share_to_department_and_person(db):
    db.add_all([
        OrgSourceShareRecord(share_id="s1", source_id="bang_gia", target_department_id="d_kt", shared_by="binh"),
        OrgSourceShareRecord(share_id="s2", source_id="sap_nhap", target_user_id="dung", shared_by="an"),
    ])
    db.commit()
    assert visible_source_ids(db, "dung", SP) == {"noi_quy", "bang_gia", "sap_nhap"}
    assert visible_source_ids(db, "em", SP) == {"noi_quy", "bang_gia"}


def test_user_share_does_not_leak_to_member_without_department(db):
    # lỗi kinh điển: target_department_id == None thành IS NULL và khớp mọi lượt chia sẻ cho người khác
    db.add(OrgSourceShareRecord(share_id="s1", source_id="nhap_chi", target_user_id="em"))
    db.commit()
    assert "nhap_chi" not in visible_source_ids(db, "an", SP)
    assert "nhap_chi" in visible_source_ids(db, "em", SP)


def test_removed_member_loses_everything_even_own_upload(db):
    db.delete(db.get(OrgMemberRecord, (SP, "binh")))
    db.commit()
    assert visible_source_ids(db, "binh", SP) == set()
    assert not can_view_source_id(db, "binh", "danh_gia_ns")


def test_demoted_manager_and_old_answers_hidden(db):
    before = visible_source_ids(db, "binh", SP)
    db.get(OrgMemberRecord, (SP, "binh")).level = "STAFF"
    db.commit()
    after = visible_source_ids(db, "binh", SP)
    assert "bao_cao_chi" not in after and "danh_gia_ns" in after  # vẫn thấy tài liệu do mình tải lên
    cited = ["bang_gia", "bao_cao_chi"]
    assert can_view_all(cited, before) and not can_view_all(cited, after)


def test_moved_department(db):
    db.get(OrgMemberRecord, (SP, "em")).department_id = "d_kd"
    db.get(OrgMemberRecord, (SP, "chi")).department_id = "d_kt"
    db.commit()
    assert visible_source_ids(db, "em", SP) == {"bang_gia", "noi_quy"}  # vào phòng mới thì thấy tài liệu phòng mới
    # người chuyển đi vẫn thấy tài liệu do chính mình tải lên (khi nghỉ hẳn thì bàn giao ở Đợt 5)
    assert visible_source_ids(db, "chi", SP) == {"bang_gia", "bao_cao_chi", "noi_quy", "nhap_chi"}


def test_pending_member_and_share_to_pending(db):
    db.add(OrgSourceShareRecord(share_id="s1", source_id="noi_quy", target_user_id="ha"))
    db.commit()
    assert visible_source_ids(db, "ha", SP) == set()
    assert load_member(db, "ha", SP).status == "PENDING"


# ---- Luật thao tác (hàm thuần, không cần CSDL) ----

AN = Member("an", SP, None, "EXECUTIVE", is_owner=True)
BINH = Member("binh", SP, "d_kd", "MANAGER")
CHI = Member("chi", SP, "d_kd", "STAFF")
DUNG = Member("dung", SP, "d_kt", "MANAGER")
EM = Member("em", SP, "d_kt", "STAFF")
HA = Member("ha", SP, None, "STAFF", status="PENDING")
SRC = {sid: Source(sid, owner, SP, dept, level) for sid, (owner, dept, level) in DOCS.items()}


def test_unknown_level_closed():
    weird = Source("x", "an", SP, "d_kd", "TOP_SECRET")
    assert not can_view("binh", BINH, weird)
    assert can_view("an", AN, weird) is True  # Ban giám đốc thấy mọi mức đã công bố; mức lạ bị CSDL chặn từ trước
    assert not can_view("chi", BINH, SRC["bang_gia"])  # đối tượng thành viên phải đúng người hỏi


def test_upload_rules():
    assert can_upload(CHI, "DEPARTMENT", "d_kd")
    assert can_upload(CHI, "RESTRICTED", "d_kd")  # nộp báo cáo lên sếp
    assert not can_upload(CHI, "COMPANY", None)
    assert not can_upload(CHI, "SECRET", None)
    assert not can_upload(CHI, "DEPARTMENT", "d_kt")  # không gắn vào phòng khác
    assert not can_upload(CHI, "DEPARTMENT", None)
    assert can_upload(BINH, "COMPANY", None) and not can_upload(BINH, "SECRET", None)
    assert can_upload(AN, "SECRET", None) and can_upload(AN, "DEPARTMENT", "d_kt")
    assert not can_upload(HA, "PRIVATE", None) and not can_upload(None, "PRIVATE", None)


def test_change_classification_rules():
    bao_cao = SRC["bao_cao_chi"]  # RESTRICTED, Chi tải lên
    bang_gia = SRC["bang_gia"]  # DEPARTMENT, Chi tải lên
    nhap = SRC["nhap_chi"]
    assert can_change_classification(CHI, nhap, "DEPARTMENT")  # công bố bản nháp
    assert can_change_classification(CHI, bang_gia, "RESTRICTED")  # tăng mức
    assert not can_change_classification(CHI, bao_cao, "DEPARTMENT")  # người tải lên không tự hạ
    assert not can_change_classification(CHI, bang_gia, "PRIVATE")  # không rút về nháp
    assert can_change_classification(BINH, bao_cao, "DEPARTMENT")  # Trưởng phòng hạ được trong phòng mình
    assert not can_change_classification(DUNG, bao_cao, "DEPARTMENT")  # Trưởng phòng khác thì không
    assert not can_change_classification(BINH, bang_gia, "SECRET")
    assert not can_change_classification(BINH, SRC["sap_nhap"], "COMPANY")
    assert can_change_classification(AN, SRC["sap_nhap"], "COMPANY")
    assert not can_change_classification(BINH, SRC["noi_quy"], "DEPARTMENT")  # tài liệu không có phòng


def test_delete_rules():
    assert can_delete("chi", CHI, SRC["bang_gia"])
    assert can_delete("binh", BINH, SRC["bang_gia"])
    assert not can_delete("em", EM, SRC["noi_quy"])
    assert not can_delete("dung", DUNG, SRC["bang_gia"])
    assert not can_delete("binh", BINH, SRC["sap_nhap"])
    assert can_delete("an", AN, SRC["sap_nhap"])
    personal = Source("p", "chi", None, None, "PRIVATE")
    assert can_delete("chi", None, personal) and not can_delete("an", AN, personal)


def test_share_rules():
    kt = Department(SP, "d_kt")
    assert can_share(BINH, SRC["bang_gia"], target_department=kt)  # Trưởng phòng chia ra phòng khác
    assert not can_share(CHI, SRC["bang_gia"], target_department=kt)  # Nhân viên không chia ra ngoài phòng
    assert can_share(CHI, SRC["bao_cao_chi"], target_member=BINH)  # tài liệu của mình, trong phòng mình
    assert not can_share(CHI, SRC["danh_gia_ns"], target_member=CHI)  # không phải tài liệu của mình
    assert not can_share(CHI, SRC["nhap_chi"], target_member=BINH)  # bản nháp phải công bố trước
    assert not can_share(BINH, SRC["sap_nhap"], target_member=DUNG)
    assert can_share(AN, SRC["sap_nhap"], target_member=DUNG)
    assert not can_share(AN, SRC["sap_nhap"], target_member=HA)  # đích chưa được duyệt
    assert not can_share(AN, SRC["noi_quy"], target_department=Department("sp_khac", "d_x"))
    assert not can_share(AN, SRC["noi_quy"], target_member=DUNG, target_department=kt)  # đúng một đích
    assert not can_share(AN, SRC["noi_quy"])


def test_invite_and_approve_rules():
    assert can_invite(AN, "EXECUTIVE", None)
    assert can_invite(BINH, "STAFF", "d_kd")
    assert not can_invite(BINH, "STAFF", "d_kt")
    assert not can_invite(BINH, "MANAGER", "d_kd")
    assert not can_invite(CHI, "STAFF", "d_kd")
    assert not can_invite(AN, "STAFF", None)  # Nhân viên phải có phòng
    assert not can_invite(AN, "OWNER", None)
    assert can_approve(BINH, HA, "STAFF", "d_kd")
    assert not can_approve(BINH, CHI, "STAFF", "d_kd")  # người đã hoạt động, không phải duyệt


def test_remove_member_rules():
    assert can_remove_member(BINH, CHI, owner_count=1)
    assert not can_remove_member(BINH, EM, owner_count=1)
    assert not can_remove_member(BINH, DUNG, owner_count=1)
    assert not can_remove_member(CHI, EM, owner_count=1)
    assert can_remove_member(CHI, CHI, owner_count=1)  # tự rời
    assert not can_remove_member(AN, AN, owner_count=1)  # Chủ cuối cùng không rời được
    second_owner = Member("binh", SP, None, "EXECUTIVE", is_owner=True)
    assert can_remove_member(AN, second_owner, owner_count=2)
    exec_not_owner = Member("dung", SP, None, "EXECUTIVE")
    assert not can_remove_member(exec_not_owner, AN, owner_count=2)  # chỉ Chủ gỡ được Chủ


def test_update_member_rules():
    kw = dict(owner_count=1)
    assert can_update_member(AN, CHI, level="MANAGER", department_id="d_kd", is_owner=False, **kw)
    assert not can_update_member(BINH, CHI, level="STAFF", department_id="d_kt", is_owner=False, **kw)
    assert not can_update_member(AN, CHI, level="STAFF", department_id=None, is_owner=False, **kw)
    assert not can_update_member(AN, AN, level="EXECUTIVE", department_id=None, is_owner=False, **kw)  # Chủ cuối
    assert not can_update_member(AN, CHI, level="STAFF", department_id="d_kd", is_owner=True, **kw)  # Chủ phải là BGĐ
    assert can_update_member(AN, CHI, level="EXECUTIVE", department_id=None, is_owner=True, **kw)
    exec_not_owner = Member("dung", SP, None, "EXECUTIVE")
    assert not can_update_member(exec_not_owner, CHI, level="EXECUTIVE", department_id=None, is_owner=True, **kw)


def test_derived_classification():
    assert derived_classification(["COMPANY", "SECRET", "DEPARTMENT"]) == "SECRET"
    assert derived_classification(["COMPANY", "PRIVATE"]) == "PRIVATE"
    with pytest.raises(ValueError):
        derived_classification([])
    with pytest.raises(KeyError):
        derived_classification(["COMPANY", "TOP_SECRET"])
