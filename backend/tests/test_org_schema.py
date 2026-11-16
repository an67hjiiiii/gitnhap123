"""Đợt 1 phân quyền tổ chức: ràng buộc CSDL bảo vệ dữ liệu ngay cả khi code ứng dụng sai.

Chạy trên SQLite trong bộ nhớ (cùng mô hình SQLAlchemy); migration PostgreSQL được kiểm riêng bằng alembic upgrade.
"""
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.storage.postgres.base import Base
from app.storage.postgres.models import (
    KnowledgeSourceRecord,
    OrgDepartmentRecord,
    OrgInviteRecord,
    OrgMemberRecord,
    OrgSourceShareRecord,
    OrgSpaceRecord,
    UserRecord,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    def _connect(conn, _):
        conn.create_function("btrim", 1, lambda v: None if v is None else v.strip())
        conn.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", _connect)
    Base.metadata.create_all(engine)
    session = sessionmaker(engine)()
    session.add_all([
        UserRecord(user_id="u_an", email="an@x.vn", display_name="An", password_hash="x"),
        UserRecord(user_id="u_chi", email="chi@x.vn", display_name="Chi", password_hash="x"),
    ])
    session.flush()  # các bảng tổ chức không khai báo relationship nên phải flush theo thứ tự khóa ngoại
    session.add_all([
        OrgSpaceRecord(space_id="sp_abc", name="Công ty ABC", created_by="u_an"),
        OrgSpaceRecord(space_id="sp_xyz", name="Công ty XYZ", created_by="u_an"),
    ])
    session.flush()
    session.add_all([
        OrgDepartmentRecord(department_id="d_kd", space_id="sp_abc", name="Kinh doanh"),
        OrgDepartmentRecord(department_id="d_xyz", space_id="sp_xyz", name="Kế toán"),
    ])
    session.commit()
    yield session
    session.close()


def _source(sid="s1", **kw):
    return KnowledgeSourceRecord(source_id=sid, owner_user_id="u_chi", source_name="a.pdf", display_metadata={}, **kw)


def _rejects(db, *rows):
    db.add_all(rows)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_old_source_defaults_to_private_personal(db):
    db.add(_source())
    db.commit()
    row = db.get(KnowledgeSourceRecord, "s1")
    assert (row.space_id, row.department_id, row.classification) == (None, None, "PRIVATE")


def test_raw_insert_without_new_columns_still_private(db):
    # code cũ chèn tài liệu không biết tới cột mới: vẫn phải ra Riêng tư
    db.execute(text("INSERT INTO knowledge_sources (source_id, owner_user_id, source_name, status, display_metadata) "
                    "VALUES ('s_raw', 'u_chi', 'b.pdf', 'READY', '{}')"))
    db.commit()
    assert db.get(KnowledgeSourceRecord, "s_raw").classification == "PRIVATE"


def test_personal_source_cannot_be_shared_level(db):
    _rejects(db, _source(classification="COMPANY"))
    _rejects(db, _source(department_id="d_kd"))


def test_unknown_classification_rejected(db):
    _rejects(db, _source(space_id="sp_abc", classification="TOP_SECRET"))


def test_department_levels_need_department(db):
    _rejects(db, _source(space_id="sp_abc", classification="DEPARTMENT"))
    _rejects(db, _source(space_id="sp_abc", classification="RESTRICTED"))
    db.add(_source(space_id="sp_abc", department_id="d_kd", classification="RESTRICTED"))
    db.add(_source("s2", space_id="sp_abc", classification="SECRET"))
    db.commit()


def test_source_department_must_be_in_same_space(db):
    _rejects(db, _source(space_id="sp_abc", department_id="d_xyz", classification="DEPARTMENT"))


def test_member_rules(db):
    # Nhân viên đang hoạt động phải có phòng; Ban giám đốc thì không cần; người chờ duyệt chưa cần phòng
    _rejects(db, OrgMemberRecord(space_id="sp_abc", user_id="u_chi", level="STAFF", status="ACTIVE"))
    _rejects(db, OrgMemberRecord(space_id="sp_abc", user_id="u_chi", level="BOSS", status="PENDING"))
    _rejects(db, OrgMemberRecord(space_id="sp_abc", user_id="u_chi", department_id="d_xyz", status="ACTIVE"))
    db.add_all([
        OrgMemberRecord(space_id="sp_abc", user_id="u_an", level="EXECUTIVE", is_owner=True, status="ACTIVE"),
        OrgMemberRecord(space_id="sp_abc", user_id="u_chi"),
    ])
    db.commit()
    chi = db.get(OrgMemberRecord, ("sp_abc", "u_chi"))
    assert (chi.level, chi.status, chi.is_owner) == ("STAFF", "PENDING", False)


def test_department_with_members_cannot_be_deleted(db):
    db.add(OrgMemberRecord(space_id="sp_abc", user_id="u_chi", department_id="d_kd", status="ACTIVE"))
    db.commit()
    db.delete(db.get(OrgDepartmentRecord, "d_kd"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_space_with_documents_cannot_be_deleted(db):
    db.add(_source(space_id="sp_abc", classification="SECRET"))
    db.commit()
    db.delete(db.get(OrgSpaceRecord, "sp_abc"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invite_target_rules(db):
    _rejects(db, OrgInviteRecord(invite_id="i1", space_id="sp_abc", kind="USER"))
    _rejects(db, OrgInviteRecord(invite_id="i1", space_id="sp_abc", kind="LINK"))
    _rejects(db, OrgInviteRecord(invite_id="i1", space_id="sp_abc", kind="LINK", token_hash="h", invitee_user_id="u_chi"))
    _rejects(db, OrgInviteRecord(invite_id="i1", space_id="sp_abc", kind="CODE", token_hash="h", max_uses=0))
    db.add_all([
        OrgInviteRecord(invite_id="i1", space_id="sp_abc", kind="USER", invitee_user_id="u_chi",
                        department_id="d_kd", level="STAFF"),
        OrgInviteRecord(invite_id="i2", space_id="sp_abc", kind="CODE", token_hash="h" * 64, max_uses=5),
    ])
    db.commit()
    _rejects(db, OrgInviteRecord(invite_id="i3", space_id="sp_abc", kind="LINK", token_hash="h" * 64))


def test_share_has_exactly_one_target_and_no_duplicates(db):
    db.add(_source(space_id="sp_abc", department_id="d_kd", classification="DEPARTMENT"))
    db.commit()
    _rejects(db, OrgSourceShareRecord(share_id="sh1", source_id="s1"))
    _rejects(db, OrgSourceShareRecord(share_id="sh1", source_id="s1", target_user_id="u_an", target_department_id="d_kd"))
    db.add(OrgSourceShareRecord(share_id="sh1", source_id="s1", target_user_id="u_an"))
    db.commit()
    _rejects(db, OrgSourceShareRecord(share_id="sh2", source_id="s1", target_user_id="u_an"))
    # xóa tài liệu thì xóa luôn các lượt chia sẻ
    db.delete(db.get(KnowledgeSourceRecord, "s1"))
    db.commit()
    assert db.get(OrgSourceShareRecord, "sh1") is None
