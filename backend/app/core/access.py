"""Phân quyền trong không gian tổ chức: nơi DUY NHẤT quyết định ai xem được và làm được gì.

Luật chốt với chủ dự án ngày 2026-11-15. API và luồng AI phải gọi các hàm ở đây, không tự viết luật riêng.
Nguyên tắc chung: đóng khi nghi ngờ. Thiếu dữ liệu, mức mật lạ, thành viên chưa duyệt đều coi là không có quyền.

Thang mức mật (thấp đến cao): COMPANY < DEPARTMENT < RESTRICTED < SECRET. PRIVATE (bản nháp) nằm ngoài thang.
Cấp bậc: STAFF (Nhân viên) < MANAGER (Trưởng phòng) < EXECUTIVE (Ban giám đốc); cờ is_owner = Chủ không gian.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.storage.postgres.models import (
    MEMBER_LEVELS,
    KnowledgeSourceRecord,
    OrgMemberRecord,
    OrgSourceShareRecord,
)

LADDER = {"COMPANY": 1, "DEPARTMENT": 2, "RESTRICTED": 3, "SECRET": 4}
# mức mật mỗi cấp bậc được phép đặt cho tài liệu
SETTABLE = {
    "STAFF": frozenset({"PRIVATE", "DEPARTMENT", "RESTRICTED"}),
    "MANAGER": frozenset({"PRIVATE", "COMPANY", "DEPARTMENT", "RESTRICTED"}),
    "EXECUTIVE": frozenset({"PRIVATE", "COMPANY", "DEPARTMENT", "RESTRICTED", "SECRET"}),
}
DEPARTMENT_BOUND = frozenset({"DEPARTMENT", "RESTRICTED"})


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


@dataclass(frozen=True)
class Department:
    space_id: str
    department_id: str


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


def can_view_all(source_ids: Iterable[str], visible_ids: set[str]) -> bool:
    """Câu trả lời cũ hay bản phân tích gộp nhiều tài liệu chỉ hiện khi người xem còn quyền với MỌI tài liệu gốc."""
    return set(source_ids) <= visible_ids


_SOURCE_ID = re.compile(r"src_[0-9a-f]{16}")
REDACTED_ANSWER = "Nội dung đã ẩn do thay đổi quyền truy cập."


def referenced_source_ids(value: Any) -> set[str]:
    """Mọi mã tài liệu xuất hiện ở bất kỳ đâu trong một lượt chạy (trích dẫn, đoạn đã đưa cho mô hình, sự kiện).

    Quét rộng có chủ ý: thừa thì chỉ ẩn nhầm, thiếu thì lộ.
    """
    return set(_SOURCE_ID.findall(json.dumps(value, ensure_ascii=False, default=str)))


def redact_run(run: dict[str, Any]) -> dict[str, Any]:
    """Giữ khung lượt chạy (mã, thời điểm, câu hỏi của chính người dùng, trạng thái), bỏ mọi nội dung lấy từ tài liệu."""
    keep = ("run_id", "created_at", "condition", "query", "status", "lifecycle_status", "conversation_id")
    return {**{k: run[k] for k in keep if k in run}, "answer": REDACTED_ANSWER, "task_results": [], "events": [],
            "tasks": [], "retrieval": {}, "metrics": {}, "access_redacted": True}


def derived_classification(classifications: Iterable[str]) -> str:
    """Sản phẩm sinh từ nhiều tài liệu kế thừa mức cao nhất; có bản nháp trong đầu vào thì là bản nháp."""
    levels = list(classifications)
    if not levels:
        raise ValueError("derived artifact needs at least one source")
    if "PRIVATE" in levels:
        return "PRIVATE"
    return max(levels, key=lambda level: LADDER[level])  # mức lạ -> KeyError, không đoán


# ---- Tải lên, đổi mức mật, xóa, chia sẻ ----

def can_upload(member: Member | None, classification: str, department_id: str | None) -> bool:
    if member is None or not member.active or classification not in SETTABLE.get(member.level, ()):
        return False
    if classification in DEPARTMENT_BOUND and department_id is None:
        return False
    # chỉ Ban giám đốc được gắn tài liệu vào phòng khác phòng mình
    return member.executive or department_id in (None, member.department_id)


def can_change_classification(member: Member | None, source: Source, new: str) -> bool:
    if not _in_space(member, source.space_id) or new not in SETTABLE.get(member.level, ()):
        return False
    if new in DEPARTMENT_BOUND and source.department_id is None:
        return False
    old = source.classification
    if member.executive:
        return True
    if "SECRET" in (old, new):
        return False
    if new == "PRIVATE":  # rút tài liệu đã công bố về bản nháp = giấu khỏi tổ chức; muốn bỏ thì xóa
        return old == "PRIVATE" and source.owner_user_id == member.user_id
    if member.manages(source.department_id):
        return True
    if source.owner_user_id == member.user_id:
        # người tải lên chỉ được công bố bản nháp hoặc TĂNG mức; hạ mức là việc của Trưởng phòng/Ban giám đốc
        return old == "PRIVATE" or LADDER[new] > LADDER[old]
    return False


def can_delete(user_id: str, member: Member | None, source: Source) -> bool:
    if source.space_id is None:
        return source.owner_user_id == user_id
    if not _in_space(member, source.space_id) or member.user_id != user_id:
        return False
    if member.executive:
        return True
    if source.classification == "SECRET":
        return False
    return source.owner_user_id == user_id or member.manages(source.department_id)


def can_share(
    member: Member | None,
    source: Source,
    *,
    target_member: Member | None = None,
    target_department: Department | None = None,
) -> bool:
    """Chia sẻ trực tiếp cho đúng một đích (một thành viên hoặc một phòng) trong cùng không gian."""
    if (target_member is None) == (target_department is None):
        return False
    if not _in_space(member, source.space_id) or source.classification == "PRIVATE":
        return False  # bản nháp phải công bố trước
    if target_member is not None:
        if not _in_space(target_member, source.space_id):
            return False
        target_dept = target_member.department_id
    else:
        if target_department.space_id != source.space_id:
            return False
        target_dept = target_department.department_id
    if member.executive:
        return True
    if source.classification == "SECRET":
        return False
    if member.manages(source.department_id):
        return True
    # Nhân viên: chỉ tài liệu do mình tải lên, chỉ trong phòng mình
    return (
        source.owner_user_id == member.user_id
        and target_dept is not None and target_dept == member.department_id
    )


# ---- Quản lý thành viên ----

def can_invite(actor: Member | None, level: str, department_id: str | None) -> bool:
    """Áp cho mời theo tài khoản và cho việc duyệt người vào bằng link/mã (gán cấp bậc khi duyệt)."""
    if actor is None or not actor.active or level not in MEMBER_LEVELS:
        return False
    if level != "EXECUTIVE" and department_id is None:
        return False
    if actor.executive:
        return True
    return level == "STAFF" and actor.manages(department_id)


def can_approve(actor: Member | None, pending: Member, level: str, department_id: str | None) -> bool:
    return (
        pending.status == "PENDING" and actor is not None and actor.space_id == pending.space_id
        and can_invite(actor, level, department_id)
    )


def can_remove_member(actor: Member | None, target: Member, owner_count: int) -> bool:
    if actor is None or not actor.active or actor.space_id != target.space_id:
        return False
    if target.is_owner and (not actor.is_owner or owner_count <= 1):
        return False  # chỉ Chủ gỡ được Chủ, và luôn còn ít nhất một Chủ
    if actor.user_id == target.user_id:
        return True  # tự rời không gian
    if actor.executive:
        return True
    return target.level == "STAFF" and actor.manages(target.department_id)


def can_update_member(
    actor: Member | None,
    target: Member,
    *,
    level: str,
    department_id: str | None,
    is_owner: bool,
    owner_count: int,
) -> bool:
    if actor is None or not actor.executive or actor.space_id != target.space_id:
        return False
    if level not in MEMBER_LEVELS or (level != "EXECUTIVE" and department_id is None):
        return False
    if is_owner != target.is_owner and not actor.is_owner:
        return False  # chỉ Chủ trao hoặc thu quyền Chủ
    if target.is_owner and not is_owner and owner_count <= 1:
        return False
    return not is_owner or level == "EXECUTIVE"  # Chủ luôn là Ban giám đốc


# ---- Đọc từ CSDL ----

def _member_from_row(row: OrgMemberRecord) -> Member:
    return Member(row.user_id, row.space_id, row.department_id, row.level, bool(row.is_owner), row.status)


def load_member(db: Session, user_id: str, space_id: str) -> Member | None:
    row = db.get(OrgMemberRecord, (space_id, user_id))
    return None if row is None else _member_from_row(row)


def require_active_member(db: Session, user_id: str, space_id: str) -> Member:
    """Cửa vào mọi yêu cầu có phạm vi tổ chức: chưa duyệt, đã bị gỡ hay không thuộc không gian đều bị từ chối."""
    member = load_member(db, user_id, space_id)
    if member is None or not member.active:
        raise PermissionError("not an active member of this space")
    return member


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


def can_view_source_id(db: Session, user_id: str, source_id: str) -> bool:
    row = db.get(KnowledgeSourceRecord, source_id)
    if row is None:
        return False
    return source_id in visible_source_ids(db, user_id, row.space_id)


# ---------------- Đơn từ và duyệt theo cấp (đợt 10)
def can_decide_request(actor: Member | None, approver_level: str, department_id: str | None, requester_id: str) -> bool:
    """Ban giám đốc duyệt mọi đơn; Trưởng phòng duyệt đơn cấp phòng của chính phòng mình. Không tự duyệt đơn của mình."""
    if actor is None or not actor.active or actor.user_id == requester_id:
        return False
    if actor.executive:
        return True
    return approver_level == "MANAGER" and actor.manages(department_id)
