"""Minimal read access and confirmed-version policy for retrieval."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from dataclasses import dataclass
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.storage.postgres.models import KnowledgeSourceRecord, OrgMemberRecord, OrgSourceShareRecord

LADDER = {"COMPANY": 1, "DEPARTMENT": 2, "RESTRICTED": 3, "SECRET": 4}
# Configuration labels only; university titles are not authorization rules.
ROLE_LABELS = {"hiệu trưởng": "EXECUTIVE", "phó hiệu trưởng": "EXECUTIVE",
               "trưởng khoa": "MANAGER", "trưởng phòng": "MANAGER", "giảng viên": "STAFF"}

@dataclass(frozen=True)
class Member:
    user_id: str
    space_id: str
    department_id: str | None
    level: str
    is_owner: bool = False
    status: str = "ACTIVE"

    @property
    def active(self) -> bool:
        return self.status == "ACTIVE"

    @property
    def executive(self) -> bool:
        return self.active and self.level == "EXECUTIVE"

    def manages(self, department_id: str | None) -> bool:
        return (
            self.active and self.level == "MANAGER"
            and department_id is not None and self.department_id == department_id
        )


@dataclass(frozen=True)
class Source:
    source_id: str
    owner_user_id: str
    space_id: str | None
    department_id: str | None
    classification: str


def _in_space(member: Member | None, space_id: str | None) -> bool:
    return member is not None and member.active and space_id is not None and member.space_id == space_id


# ---- Xem tài liệu ----

def can_view(user_id: str, member: Member | None, source: Source, shared_to_me: bool = False) -> bool:
    if source.space_id is None:  # tài liệu cá nhân: chỉ chủ, như trước khi có tổ chức
        return source.owner_user_id == user_id
    if not _in_space(member, source.space_id) or member.user_id != user_id:
        return False
    if source.owner_user_id == user_id or shared_to_me:
        return True
    level = source.classification
    if level == "PRIVATE":
        return False
    if member.executive:
        return True
    if level == "COMPANY":
        return True
    if level == "DEPARTMENT":
        return source.department_id is not None and member.department_id == source.department_id
    if level == "RESTRICTED":
        return member.manages(source.department_id)
    return False  # SECRET hoặc mức lạ


def _member_from_row(row: OrgMemberRecord) -> Member:
    return Member(row.user_id, row.space_id, row.department_id, row.level, bool(row.is_owner), row.status)


def load_member(db: Session, user_id: str, space_id: str) -> Member | None:
    row = db.get(OrgMemberRecord, (space_id, user_id))
    return None if row is None else _member_from_row(row)


def _shared_source_ids(db: Session, member: Member, space_id: str) -> set[str]:
    # dựng điều kiện tường minh: so sánh với None sẽ thành IS NULL và khớp nhầm mọi lượt chia sẻ cho người khác
    targets = [OrgSourceShareRecord.target_user_id == member.user_id]
    if member.department_id is not None:
        targets.append(OrgSourceShareRecord.target_department_id == member.department_id)
    rows = db.scalars(
        select(OrgSourceShareRecord.source_id)
        .join(KnowledgeSourceRecord, KnowledgeSourceRecord.source_id == OrgSourceShareRecord.source_id)
        .where(KnowledgeSourceRecord.space_id == space_id, or_(*targets))
    )
    return set(rows)


def visible_source_ids(db: Session, user_id: str, space_id: str | None = None) -> set[str]:
    """Tập tài liệu người dùng được xem trong một phạm vi (None = không gian cá nhân).

    Tập rỗng nghĩa là không được xem gì; nơi gọi phải coi rỗng là "không tìm", không phải "tìm tất cả".
    """
    if space_id is None:
        return set(db.scalars(select(KnowledgeSourceRecord.source_id).where(
            KnowledgeSourceRecord.owner_user_id == user_id, KnowledgeSourceRecord.space_id.is_(None))))
    member = load_member(db, user_id, space_id)
    if member is None or not member.active:
        return set()
    shared = _shared_source_ids(db, member, space_id)
    # shortcut: nạp mọi tài liệu của không gian rồi lọc bằng can_view để luật chỉ nằm một chỗ;
    # đủ cho vài nghìn tài liệu, lớn hơn thì đẩy điều kiện xuống SQL kèm test đối chiếu với can_view.
    rows = db.execute(select(
        KnowledgeSourceRecord.source_id, KnowledgeSourceRecord.owner_user_id, KnowledgeSourceRecord.space_id,
        KnowledgeSourceRecord.department_id, KnowledgeSourceRecord.classification,
    ).where(KnowledgeSourceRecord.space_id == space_id)).all()
    return {row[0] for row in rows if can_view(user_id, member, Source(*row), row[0] in shared)}



def asks_other_versions(query: str) -> bool:
    """Pure intent detection; version/comparison questions keep all visible versions."""
    text = unicodedata.normalize("NFC", query).casefold()
    return bool(re.search(
        r"bản cũ|(?:bản|phiên bản)\s+(?:[a-z]+[- ]*)?\d+(?:\.\d+)*|dự thảo|trước đây|"
        r"thay đổi|khác nhau|so với|so sánh|điểm mới|bị bỏ|thêm|"
        r"\b(?:old|previous|draft|compare|comparison|changes|added|removed)\b|\bversion\s+\d+", text))


def filter_version_ids(visible_ids: set[str], versions, query: str, *, today: date) -> set[str]:
    """Current confirmed issued versions are computed BEFORE intersecting selection."""
    allowed = set(visible_ids)
    if asks_other_versions(query):
        return allowed
    confirmed = [v for v in versions if v["source_id"] in visible_ids
                 and v.get("confirmed_at") is not None and v.get("family_key")]
    latest = {}
    for v in confirmed:
        effective = v.get("effective_from")
        if v.get("status") == "issued" and effective is not None and effective <= today:
            family = v["family_key"]
            latest[family] = max(latest.get(family, date.min), effective)
    for v in confirmed:
        if v.get("status") == "draft":
            allowed.discard(v["source_id"])
        elif (v.get("status") == "issued" and v.get("effective_from") is not None
              and v["family_key"] in latest and v["effective_from"] < latest[v["family_key"]]):
            allowed.discard(v["source_id"])
    return allowed
