"""API không gian tổ chức (/api/org): không gian, phòng ban, thành viên, lời mời, tài liệu tổ chức, thông báo.

Mọi quyết định "được hay không" gọi app.core.access; file này chỉ đọc/ghi CSDL và trả lời HTTP.
Link và mã mời chỉ lưu dạng SHA-256 và chỉ trả nguyên văn đúng một lần khi tạo.
Người vào bằng link/mã luôn ở trạng thái chờ duyệt; cấp bậc được gán khi duyệt, không bao giờ lấy từ link.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import bindparam, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.access import (
    SETTABLE,
    can_decide_request,
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
    load_member,
    require_active_member,
    visible_source_ids,
)
from app.research.registry import PACKS
from app.storage.postgres.models import (
    ORG_PRESETS,
    ConversationRecord,
    KnowledgeChunkRecord,
    KnowledgeSourceRecord,
    NotificationRecord,
    OrgDepartmentRecord,
    OrgInviteRecord,
    OrgMemberRecord,
    OrgRequestRecord,
    OrgSecretAccessRecord,
    OrgSourceShareRecord,
    OrgSpaceRecord,
    UserRecord,
)

Level = Literal["STAFF", "MANAGER", "EXECUTIVE"]
Classification = Literal["PRIVATE", "COMPANY", "DEPARTMENT", "RESTRICTED", "SECRET"]
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bỏ ký tự dễ nhầm (0/O, 1/I)
JOIN_FAILURE_LIMIT = 10
JOIN_FAILURE_WINDOW_S = 15 * 60
ORG_AUDIT_MASK = "(tài liệu tổ chức)"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


PresetName = Literal[ORG_PRESETS]  # type: ignore[valid-type]
PackName = Literal[tuple(PACKS)]  # type: ignore[valid-type]
# lĩnh vực gợi ý khi tạo tổ chức mà chưa chọn (Y tế chưa có bộ riêng nên dùng Tổng quát)
PRESET_PACK = {"school": "education", "government": "legal_admin", "business": "business_hr"}


class OrgLabels(_Body):
    """Tên gọi tự đặt, chỉ để hiển thị; trống thì giao diện dùng tên của mẫu."""

    org: str | None = Field(default=None, max_length=40)
    unit: str | None = Field(default=None, max_length=40)
    STAFF: str | None = Field(default=None, max_length=40)
    MANAGER: str | None = Field(default=None, max_length=40)
    EXECUTIVE: str | None = Field(default=None, max_length=40)


def _clean_labels(labels: OrgLabels | None) -> dict[str, str] | None:
    kept = {k: v.strip() for k, v in (labels.model_dump() if labels else {}).items() if v and v.strip()}
    return kept or None


class SpaceBody(_Body):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    departments: list[str] = Field(default_factory=list, max_length=50)
    preset: PresetName = "business"
    labels: OrgLabels | None = None
    domain_pack: PackName | None = None  # bỏ trống = gợi ý theo mẫu tổ chức

    @field_validator("name")
    @classmethod
    def _non_blank_space_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Tên không gian tổ chức không được để trống.")
        return s


class DeleteSpaceBody(_Body):
    confirm_name: str = Field(min_length=1, max_length=120)

    @field_validator("confirm_name")
    @classmethod
    def _non_empty_confirm(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Tên xác nhận không được để trống.")
        return s


class SpaceUpdate(_Body):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    preset: PresetName | None = None
    labels: OrgLabels | None = None  # gửi null để bỏ tên tự đặt
    domain_pack: PackName | None = None

    @field_validator("name")
    @classmethod
    def _non_blank_space_name_opt(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("Tên không gian tổ chức không được để trống.")
        return s


class DepartmentBody(_Body):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _non_blank_dept_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Tên đơn vị không được để trống.")
        return s


class MemberUpdate(_Body):
    level: Level
    department_id: str | None = None
    is_owner: bool = False


class ApproveBody(_Body):
    level: Level = "STAFF"
    department_id: str | None = None


class InviteBody(_Body):
    kind: Literal["USER", "LINK", "CODE"]
    email: str | None = Field(default=None, max_length=254)
    level: Level = "STAFF"
    department_id: str | None = None
    expires_days: int = Field(default=7, ge=1, le=30)
    max_uses: int = Field(default=20, ge=1, le=500)


class JoinBody(_Body):
    token: str = Field(min_length=4, max_length=200)


class PublishBody(_Body):
    classification: Classification = "DEPARTMENT"
    department_id: str | None = None


class SourceUpdate(_Body):
    classification: Classification | None = None
    department_id: str | None = None


class ShareBody(_Body):
    user_id: str | None = None
    department_id: str | None = None


class ReadBody(_Body):
    ids: list[str] = Field(default_factory=list, max_length=200)
    all: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _aware(value: datetime | None) -> datetime | None:
    # SQLite trả datetime không múi giờ; PostgreSQL trả có múi giờ
    return None if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


class RequestBody(BaseModel):
    """Đơn từ (đợt 10). check_result: kết quả kỹ năng Kiểm tra điều kiện / Ai duyệt người gửi đã chạy (lưu kèm để người duyệt xem)."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["leave", "purchase", "other"] = "leave"
    title: str = Field(min_length=3, max_length=200)
    details: str = Field(default="", max_length=4000)
    days: float | None = Field(default=None, ge=0, le=366, allow_inf_nan=False)
    approver_level: Literal["MANAGER", "EXECUTIVE"]
    check_result: dict = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def _non_empty_title(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 3:
            raise ValueError("Tiêu đề đơn cần tối thiểu 3 ký tự.")
        return s


class DecideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVED", "REJECTED"]
    note: str = Field(default="", max_length=1000)


def build_router(*, current_user: Callable[[Request], dict], session_factory: Callable[[], Any],
                 vector_store: Callable[[], Any] | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/org", tags=["org"])
    join_failures: dict[str, list[float]] = {}  # shortcut: đếm sai trong bộ nhớ một tiến trình; nhiều tiến trình thì chuyển vào CSDL

    def _db():
        factory = session_factory()
        if factory is None:
            raise HTTPException(503, "Không gian tổ chức cần APP_STORAGE_BACKEND=postgres.")
        return factory()

    def _uid(request: Request) -> str:
        return str(current_user(request)["user_id"])

    def _actor(db, user_id: str, space_id: str) -> Member:
        try:
            return require_active_member(db, user_id, space_id)
        except PermissionError as exc:
            raise HTTPException(403, "Bạn không thuộc không gian tổ chức này.") from exc

    def _member_or_404(db, user_id: str, space_id: str) -> Member:
        member = load_member(db, user_id, space_id)
        if member is None:
            raise HTTPException(404, "Không tìm thấy thành viên.")
        return member

    def _department(db, space_id: str, department_id: str | None) -> None:
        if department_id is None:
            return
        row = db.get(OrgDepartmentRecord, department_id)
        if row is None or row.space_id != space_id:
            raise HTTPException(404, "Không tìm thấy đơn vị.")

    def _owner_count(db, space_id: str) -> int:
        return int(db.scalar(select(func.count()).select_from(OrgMemberRecord).where(
            OrgMemberRecord.space_id == space_id, OrgMemberRecord.is_owner.is_(True),
            OrgMemberRecord.status == "ACTIVE")) or 0)

    def _notify(db, user_ids, space_id: str | None, kind: str, payload: dict) -> None:
        for user_id in dict.fromkeys(user_ids):  # bỏ trùng, giữ thứ tự
            db.add(NotificationRecord(notification_id=_new_id("ntf"), user_id=user_id, space_id=space_id,
                                      kind=kind, payload=payload, created_at=_now()))  # đủ chính xác để sắp thứ tự

    def _approvers(db, space_id: str, department_id: str | None) -> list[str]:
        """Người duyệt được yêu cầu tham gia: Ban giám đốc, chủ tổ chức, và Trưởng phòng của phòng được gợi ý."""
        conds = [OrgMemberRecord.level == "EXECUTIVE", OrgMemberRecord.is_owner.is_(True)]
        if department_id is not None:
            conds.append((OrgMemberRecord.level == "MANAGER") & (OrgMemberRecord.department_id == department_id))
        return list(db.scalars(select(OrgMemberRecord.user_id).where(
            OrgMemberRecord.space_id == space_id, OrgMemberRecord.status == "ACTIVE", or_(*conds))))

    def _only_department(db, space_id: str) -> str | None:
        """Tổ chức chỉ có một đơn vị (chế độ nhóm nhỏ): người không thuộc đơn vị nào mặc định gắn vào đơn vị đó."""
        ids = db.scalars(select(OrgDepartmentRecord.department_id).where(
            OrgDepartmentRecord.space_id == space_id).limit(2)).all()
        return ids[0] if len(ids) == 1 else None

    def _space_name(db, space_id: str) -> str:
        row = db.get(OrgSpaceRecord, space_id)
        return "" if row is None else row.name

    def _user_label(db, user_id: str | None) -> str:
        row = db.get(UserRecord, user_id) if user_id else None
        return "" if row is None else (row.display_name or row.email or row.username or "")

    def _source(row: KnowledgeSourceRecord) -> Source:
        return Source(row.source_id, row.owner_user_id, row.space_id, row.department_id, row.classification)

    def _viewers(db, row: KnowledgeSourceRecord) -> set[str]:
        """Thành viên đang xem được tài liệu này (cùng luật can_view, tính cả chia sẻ trực tiếp)."""
        if row.space_id is None:
            return set()
        shares = db.scalars(select(OrgSourceShareRecord).where(OrgSourceShareRecord.source_id == row.source_id)).all()
        to_users = {s.target_user_id for s in shares if s.target_user_id}
        to_deps = {s.target_department_id for s in shares if s.target_department_id}
        members = db.scalars(select(OrgMemberRecord).where(
            OrgMemberRecord.space_id == row.space_id, OrgMemberRecord.status == "ACTIVE")).all()
        out = set()
        for m in members:
            member = Member(m.user_id, m.space_id, m.department_id, m.level, bool(m.is_owner), m.status)
            if can_view(m.user_id, member, _source(row), m.user_id in to_users or (m.department_id in to_deps)):
                out.add(m.user_id)
        return out

    def _notify_new_viewers(db, row: KnowledgeSourceRecord, before: set[str], actor_uid: str, kind: str) -> None:
        """Báo cho người VỪA được quyền xem (nộp mới, đổi mức mật); người đã xem từ trước không bị báo lại."""
        db.flush()
        fresh = _viewers(db, row) - before - {actor_uid}
        if not fresh:
            return
        dep = db.get(OrgDepartmentRecord, row.department_id) if row.department_id else None
        _notify(db, sorted(fresh), row.space_id, kind, {
            "space_name": _space_name(db, row.space_id), "source_name": row.source_name, "by": _user_label(db, actor_uid),
            "classification": row.classification, "department": dep.name if dep else None})

    def _space_source(db, space_id: str, source_id: str, user_id: str) -> KnowledgeSourceRecord:
        """Tài liệu của không gian mà người hỏi được xem; không xem được thì như không tồn tại (404)."""
        row = db.get(KnowledgeSourceRecord, source_id)
        if row is None or row.space_id != space_id or source_id not in visible_source_ids(db, user_id, space_id):
            raise HTTPException(404, "Không tìm thấy tài liệu.")
        return row

    def _commit(db, conflict: str = "Dữ liệu bị trùng hoặc đang được dùng.") -> None:
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, conflict) from exc

    # ---------------- Không gian
    @router.post("/spaces")
    def create_space(body: SpaceBody, request: Request) -> dict:
        uid = _uid(request)
        names = list(dict.fromkeys(n.strip() for n in body.departments if n.strip()))
        if not body.name.strip():
            raise HTTPException(422, "Tên không gian không được để trống.")
        space_id = _new_id("sp")
        with _db() as db:
            db.add(OrgSpaceRecord(space_id=space_id, name=body.name.strip(), description=body.description.strip(),
                                  preset=body.preset, labels=_clean_labels(body.labels), created_by=uid,
                                  domain_pack=body.domain_pack or PRESET_PACK.get(body.preset, "general")))
            db.flush()
            for name in names:
                db.add(OrgDepartmentRecord(department_id=_new_id("dep"), space_id=space_id, name=name))
            # người tạo là Chủ + Ban giám đốc
            db.add(OrgMemberRecord(space_id=space_id, user_id=uid, level="EXECUTIVE", is_owner=True, status="ACTIVE"))
            _commit(db)
        request.state.audit_target = space_id
        return {"space_id": space_id, "name": body.name.strip()}

    @router.get("/spaces")
    def my_spaces(request: Request) -> list[dict]:
        uid = _uid(request)
        with _db() as db:
            rows = db.execute(select(OrgSpaceRecord, OrgMemberRecord).join(
                OrgMemberRecord, OrgMemberRecord.space_id == OrgSpaceRecord.space_id).where(
                OrgMemberRecord.user_id == uid).order_by(OrgSpaceRecord.name)).all()
            counts = dict(db.execute(select(OrgDepartmentRecord.space_id, func.count()).group_by(
                OrgDepartmentRecord.space_id)).all())
            people = dict(db.execute(select(OrgMemberRecord.space_id, func.count()).where(
                OrgMemberRecord.status == "ACTIVE").group_by(OrgMemberRecord.space_id)).all())
            # vài thành viên và số tài liệu bạn xem được, chỉ cho tổ chức bạn đã được duyệt
            mine = [s.space_id for s, m in rows if m.status == "ACTIVE"]
            preview: dict[str, list[dict]] = {k: [] for k in mine}
            for mem, usr in db.execute(select(OrgMemberRecord, UserRecord).join(
                    UserRecord, UserRecord.user_id == OrgMemberRecord.user_id).where(
                    OrgMemberRecord.space_id.in_(mine), OrgMemberRecord.status == "ACTIVE")
                    .order_by(OrgMemberRecord.is_owner.desc(), OrgMemberRecord.joined_at)).all():
                if len(preview[mem.space_id]) < 5:
                    preview[mem.space_id].append({"user_id": usr.user_id, "display_name": usr.display_name, "avatar": usr.avatar})
            docs = {k: len(visible_source_ids(db, uid, k)) for k in mine}
            return [{"space_id": s.space_id, "name": s.name, "description": s.description, "preset": s.preset,
                     "domain_pack": s.domain_pack,
                     "labels": s.labels, "unit_count": counts.get(s.space_id, 0),
                     # người chưa được duyệt không xem được quy mô tổ chức
                     "member_count": people.get(s.space_id, 0) if m.status == "ACTIVE" else None,
                     "members_preview": preview.get(s.space_id, []), "doc_count": docs.get(s.space_id),
                     "level": m.level,
                     "department_id": m.department_id, "is_owner": bool(m.is_owner), "status": m.status}
                    for s, m in rows]

    @router.get("/spaces/{space_id}")
    def space_detail(space_id: str, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            me = _actor(db, uid, space_id)
            space = db.get(OrgSpaceRecord, space_id)
            departments = db.scalars(select(OrgDepartmentRecord).where(
                OrgDepartmentRecord.space_id == space_id).order_by(OrgDepartmentRecord.name)).all()
            rows = db.execute(select(OrgMemberRecord, UserRecord).join(
                UserRecord, UserRecord.user_id == OrgMemberRecord.user_id).where(
                OrgMemberRecord.space_id == space_id).order_by(UserRecord.display_name)).all()
            members = [{"user_id": m.user_id, "display_name": u.display_name, "email": u.email,
                        "avatar": u.avatar, "department_id": m.department_id, "level": m.level, "is_owner": bool(m.is_owner),
                        "status": m.status, "joined_at": _iso(m.joined_at)} for m, u in rows]
            if not (me.executive or me.level == "MANAGER"):
                members = [m for m in members if m["status"] == "ACTIVE"]  # yêu cầu chờ duyệt chỉ người duyệt thấy
            return {"space_id": space_id, "name": space.name, "description": space.description,
                    "preset": space.preset, "labels": space.labels, "domain_pack": space.domain_pack,
                    "me": {"level": me.level, "department_id": me.department_id, "is_owner": me.is_owner},
                    "departments": [{"department_id": d.department_id, "name": d.name} for d in departments],
                    "members": members}

    @router.delete("/spaces/{space_id}")
    def delete_space(space_id: str, body: DeleteSpaceBody, request: Request) -> dict:
        """Chủ xóa tổ chức: gỡ mọi quyền truy cập và tài liệu tổ chức; lượt chạy AI, hội thoại được giữ nhưng ẩn."""
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            space = db.get(OrgSpaceRecord, space_id)
            if not actor.is_owner:
                raise HTTPException(403, "Chỉ chủ tổ chức được xóa tổ chức.")
            if body.confirm_name.strip() != space.name.strip():
                raise HTTPException(422, "Tên nhập lại không khớp với tên tổ chức.")
            sources = db.execute(select(KnowledgeSourceRecord.source_id, KnowledgeSourceRecord.owner_user_id).where(
                KnowledgeSourceRecord.space_id == space_id)).all()
            chunks = db.execute(select(KnowledgeChunkRecord.chunk_id, KnowledgeSourceRecord.owner_user_id).join(
                KnowledgeSourceRecord, KnowledgeSourceRecord.source_id == KnowledgeChunkRecord.source_id).where(
                KnowledgeSourceRecord.space_id == space_id)).all()
            others = [m for m in db.scalars(select(OrgMemberRecord.user_id).where(
                OrgMemberRecord.space_id == space_id, OrgMemberRecord.status == "ACTIVE")) if m != uid]
        # vector dẫn xuất xóa trước, như xóa từng tài liệu; mở chỉ mục lỗi thì vẫn xóa bản có thẩm quyền trong CSDL
        try:
            store = vector_store() if vector_store else None
        except Exception:
            store = None
        if store is not None and chunks:
            store.delete([f"{owner}:{cid}" for cid, owner in chunks])
        with _db() as db:
            ids = [s for s, _ in sources]
            if ids:
                db.execute(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.source_id.in_(ids)))
                # bảng thư mục Studio chỉ có trên PostgreSQL thật (và trong test)
                db.execute(text("DELETE FROM studio_workspace_items WHERE item_type = 'source' AND item_id IN :ids")
                           .bindparams(bindparam("ids", expanding=True)), {"ids": ids})
            for model in (OrgInviteRecord, OrgMemberRecord, OrgDepartmentRecord):
                db.execute(delete(model).where(model.space_id == space_id))
            db.execute(update(ConversationRecord).where(ConversationRecord.space_id == space_id,
                                                        ConversationRecord.hidden_at.is_(None)).values(hidden_at=_now()))
            db.get(OrgSpaceRecord, space_id).deleted_at = _now()
            _notify(db, others, None, "space_deleted", {"space_name": space.name, "by": _user_label(db, uid)})
            _commit(db)
        request.state.audit_target = space_id
        return {"deleted": space_id, "sources_removed": len(sources), "members_removed": len(others) + 1}

    @router.patch("/spaces/{space_id}")
    def update_space(space_id: str, body: SpaceUpdate, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            if not _actor(db, uid, space_id).executive:
                raise HTTPException(403, "Bạn không có quyền sửa thông tin tổ chức.")
            space = db.get(OrgSpaceRecord, space_id)
            if body.name is not None:
                space.name = body.name.strip() or space.name
            if body.description is not None:
                space.description = body.description.strip()
            if body.preset is not None:
                space.preset = body.preset
            if "labels" in body.model_fields_set:
                space.labels = _clean_labels(body.labels)
            if body.domain_pack is not None:
                space.domain_pack = body.domain_pack
            _commit(db)
            return {"space_id": space_id, "name": space.name, "description": space.description,
                    "preset": space.preset, "labels": space.labels, "domain_pack": space.domain_pack}

    # ---------------- Phòng ban
    @router.post("/spaces/{space_id}/departments")
    def create_department(space_id: str, body: DepartmentBody, request: Request) -> dict:
        uid = _uid(request)
        department_id = _new_id("dep")
        with _db() as db:
            if not _actor(db, uid, space_id).executive:
                raise HTTPException(403, "Bạn không có quyền thêm đơn vị.")
            only = _only_department(db, space_id)
            if only is not None:
                # Khi chỉ có một đơn vị, giao diện gọi mức Nội bộ là "Toàn tổ chức" vì nó đúng là cho mọi người.
                # Chia thêm đơn vị thì Nội bộ sẽ hẹp lại; đổi các tài liệu đó sang COMPANY để ai đang xem vẫn xem được
                # và người của đơn vị mới cũng thấy, đúng như nhãn người tải lên đã chọn.
                db.execute(update(KnowledgeSourceRecord).where(
                    KnowledgeSourceRecord.space_id == space_id, KnowledgeSourceRecord.department_id == only,
                    KnowledgeSourceRecord.classification == "DEPARTMENT").values(classification="COMPANY"))
            db.add(OrgDepartmentRecord(department_id=department_id, space_id=space_id, name=body.name.strip()))
            _commit(db, "Tên đơn vị này đã có.")
        return {"department_id": department_id, "name": body.name.strip()}

    @router.patch("/spaces/{space_id}/departments/{department_id}")
    def rename_department(space_id: str, department_id: str, body: DepartmentBody, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            if not _actor(db, uid, space_id).executive:
                raise HTTPException(403, "Bạn không có quyền đổi tên đơn vị.")
            _department(db, space_id, department_id)
            db.get(OrgDepartmentRecord, department_id).name = body.name.strip()
            _commit(db, "Tên đơn vị này đã có.")
        return {"department_id": department_id, "name": body.name.strip()}

    @router.delete("/spaces/{space_id}/departments/{department_id}")
    def delete_department(space_id: str, department_id: str, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            if not _actor(db, uid, space_id).executive:
                raise HTTPException(403, "Bạn không có quyền xóa đơn vị.")
            _department(db, space_id, department_id)
            db.delete(db.get(OrgDepartmentRecord, department_id))
            _commit(db, "Đơn vị còn thành viên hoặc tài liệu: chuyển sang đơn vị khác trước.")
        return {"deleted": department_id}

    # ---------------- Thành viên
    @router.patch("/spaces/{space_id}/members/{user_id}")
    def update_member(space_id: str, user_id: str, body: MemberUpdate, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            target = _member_or_404(db, user_id, space_id)
            if target.status != "ACTIVE":
                raise HTTPException(409, "Thành viên đang chờ duyệt: dùng chức năng duyệt.")
            department_id = None if body.level == "EXECUTIVE" and body.department_id is None else body.department_id
            _department(db, space_id, department_id)
            if not can_update_member(actor, target, level=body.level, department_id=department_id,
                                     is_owner=body.is_owner, owner_count=_owner_count(db, space_id)):
                raise HTTPException(403, "Bạn không có quyền thay đổi thành viên này theo cách đó.")
            row = db.get(OrgMemberRecord, (space_id, user_id))
            row.level, row.department_id, row.is_owner = body.level, department_id, body.is_owner
            if user_id != uid:
                _notify(db, [user_id], space_id, "member_updated",
                        {"space_name": _space_name(db, space_id), "level": body.level, "department_id": department_id,
                         "is_owner": body.is_owner})
            _commit(db)
        return {"user_id": user_id, "level": body.level, "department_id": department_id, "is_owner": body.is_owner}

    def _remove(db, actor: Member, target: Member, handover_to: str | None) -> dict:
        space_id = target.space_id
        owners = _owner_count(db, space_id)
        if actor.user_id == target.user_id and target.is_owner and owners <= 1:
            raise HTTPException(409, "Bạn là chủ duy nhất của tổ chức này. Hãy trao quyền chủ cho một thành viên khác "
                                     "trước khi rời, hoặc xóa tổ chức.")
        if not can_remove_member(actor, target, owners):
            raise HTTPException(403, "Bạn không có quyền gỡ thành viên này.")
        drafts = list(db.scalars(select(KnowledgeSourceRecord.source_id).where(
            KnowledgeSourceRecord.space_id == space_id, KnowledgeSourceRecord.owner_user_id == target.user_id,
            KnowledgeSourceRecord.classification == "PRIVATE")))
        recipient = None
        if drafts:
            # bàn giao bản nháp cho người có quyền quản lý: Trưởng phòng của họ, hoặc Ban giám đốc
            if handover_to is None:
                manager = db.scalar(select(OrgMemberRecord.user_id).where(
                    OrgMemberRecord.space_id == space_id, OrgMemberRecord.status == "ACTIVE",
                    OrgMemberRecord.level == "MANAGER", OrgMemberRecord.department_id == target.department_id,
                    OrgMemberRecord.department_id.is_not(None), OrgMemberRecord.user_id != target.user_id))
                owner = db.scalar(select(OrgMemberRecord.user_id).where(
                    OrgMemberRecord.space_id == space_id, OrgMemberRecord.status == "ACTIVE",
                    OrgMemberRecord.is_owner.is_(True), OrgMemberRecord.user_id != target.user_id))
                handover_to = manager or (actor.user_id if actor.user_id != target.user_id else owner)
            recipient = load_member(db, handover_to, space_id) if handover_to else None
            if (recipient is None or not recipient.active or recipient.user_id == target.user_id
                    or not (recipient.executive or recipient.manages(target.department_id))):
                raise HTTPException(422, "Người nhận bàn giao phải là trưởng đơn vị của người này hoặc thuộc cấp lãnh đạo.")
            existing = set(db.scalars(select(OrgSourceShareRecord.source_id).where(
                OrgSourceShareRecord.target_user_id == recipient.user_id,
                OrgSourceShareRecord.source_id.in_(drafts))))
            for source_id in drafts:
                if source_id not in existing:  # bàn giao = chia sẻ trực tiếp, mã vector vẫn mang tên người tải lên
                    db.add(OrgSourceShareRecord(share_id=_new_id("shr"), source_id=source_id,
                                                target_user_id=recipient.user_id, shared_by=actor.user_id))
        db.execute(delete(OrgMemberRecord).where(OrgMemberRecord.space_id == space_id,
                                                 OrgMemberRecord.user_id == target.user_id))
        name = _space_name(db, space_id)
        if target.user_id != actor.user_id:
            _notify(db, [target.user_id], None, "member_removed", {"space_name": name})
        if recipient is not None:
            _notify(db, [recipient.user_id], space_id, "drafts_handed_over",
                    {"space_name": name, "from": _user_label(db, target.user_id), "count": len(drafts)})
        _commit(db)
        return {"removed": target.user_id, "handed_over_to": None if recipient is None else recipient.user_id,
                "drafts": len(drafts)}

    @router.delete("/spaces/{space_id}/members/{user_id}")
    def remove_member(space_id: str, user_id: str, request: Request, handover_to: str | None = None) -> dict:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            target = _member_or_404(db, user_id, space_id)
            if target.status == "PENDING":  # từ chối yêu cầu tham gia
                if not (actor.executive or actor.manages(target.department_id)):
                    raise HTTPException(403, "Bạn không có quyền xử lý yêu cầu này.")
                db.delete(db.get(OrgMemberRecord, (space_id, user_id)))
                _notify(db, [user_id], None, "join_rejected", {"space_name": _space_name(db, space_id)})
                _commit(db)
                return {"removed": user_id, "handed_over_to": None, "drafts": 0}
            return _remove(db, actor, target, handover_to)

    @router.post("/spaces/{space_id}/leave")
    def leave(space_id: str, request: Request, handover_to: str | None = None) -> dict:
        uid = _uid(request)
        with _db() as db:
            member = _member_or_404(db, uid, space_id)
            if member.status == "PENDING":
                db.delete(db.get(OrgMemberRecord, (space_id, uid)))
                _commit(db)
                return {"removed": uid, "handed_over_to": None, "drafts": 0}
            return _remove(db, member, member, handover_to)

    @router.post("/spaces/{space_id}/members/{user_id}/approve")
    def approve(space_id: str, user_id: str, body: ApproveBody, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            target = _member_or_404(db, user_id, space_id)
            department_id = None if body.level == "EXECUTIVE" and body.department_id is None else body.department_id
            _department(db, space_id, department_id)
            if not can_approve(actor, target, body.level, department_id):
                raise HTTPException(403, "Bạn không có quyền duyệt với cấp bậc và đơn vị này.")
            row = db.get(OrgMemberRecord, (space_id, user_id))
            row.status, row.level, row.department_id = "ACTIVE", body.level, department_id
            _notify(db, [user_id], space_id, "join_approved",
                    {"space_name": _space_name(db, space_id), "level": body.level, "department_id": department_id})
            _commit(db)
        return {"user_id": user_id, "status": "ACTIVE", "level": body.level, "department_id": department_id}

    # ---------------- Lời mời
    @router.post("/spaces/{space_id}/invites")
    def create_invite(space_id: str, body: InviteBody, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            _department(db, space_id, body.department_id)
            invite_id = _new_id("inv")
            if body.kind == "USER":
                department_id = None if body.level == "EXECUTIVE" and body.department_id is None else body.department_id
                if not can_invite(actor, body.level, department_id):
                    raise HTTPException(403, "Bạn không có quyền mời với cấp bậc và đơn vị này.")
                email = (body.email or "").strip().lower()
                invitee = db.scalar(select(UserRecord).where(func.lower(UserRecord.email) == email)) if email else None
                if invitee is None or invitee.status != "ACTIVE":
                    raise HTTPException(404, "Không tìm thấy tài khoản với email này. Người được mời cần đăng ký trước.")
                if db.get(OrgMemberRecord, (space_id, invitee.user_id)) is not None:
                    raise HTTPException(409, "Người này đã là thành viên hoặc đang chờ duyệt.")
                db.add(OrgInviteRecord(invite_id=invite_id, space_id=space_id, kind="USER", invitee_user_id=invitee.user_id,
                                       department_id=department_id, level=body.level, created_by=uid,
                                       expires_at=_now() + timedelta(days=body.expires_days)))
                _notify(db, [invitee.user_id], space_id, "invite",
                        {"invite_id": invite_id, "space_name": _space_name(db, space_id),
                         "inviter": _user_label(db, uid), "level": body.level, "department_id": department_id})
                _commit(db)
                return {"invite_id": invite_id, "kind": "USER"}
            # link/mã: chỉ người duyệt được yêu cầu tham gia mới được tạo
            if not (actor.executive or (actor.level == "MANAGER" and body.department_id in (None, actor.department_id))):
                raise HTTPException(403, "Bạn không có quyền tạo link hoặc mã mời.")
            hint = body.department_id if body.department_id is not None else (None if actor.executive else actor.department_id)
            if body.kind == "LINK":
                token = secrets.token_urlsafe(24)
                token_hash, shown = _sha(token), token
            else:
                raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
                token_hash, shown = _sha(raw), f"{raw[:4]}-{raw[4:]}"
            db.add(OrgInviteRecord(invite_id=invite_id, space_id=space_id, kind=body.kind, token_hash=token_hash,
                                   department_id=hint, level="STAFF", created_by=uid,
                                   expires_at=_now() + timedelta(days=body.expires_days), max_uses=body.max_uses))
            _commit(db)
            return {"invite_id": invite_id, "kind": body.kind, "token": shown,
                    "note": "Chỉ hiện một lần. Người vào bằng link/mã phải chờ duyệt."}

    @router.get("/spaces/{space_id}/invites")
    def list_invites(space_id: str, request: Request) -> list[dict]:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            if not (actor.executive or actor.level == "MANAGER"):
                raise HTTPException(403, "Bạn không có quyền xem danh sách lời mời.")
            query = select(OrgInviteRecord).where(OrgInviteRecord.space_id == space_id)
            if not actor.executive:
                query = query.where(OrgInviteRecord.created_by == uid)
            rows = db.scalars(query.order_by(OrgInviteRecord.created_at.desc())).all()
            return [{"invite_id": r.invite_id, "kind": r.kind, "invitee": _user_label(db, r.invitee_user_id) or None,
                     "level": r.level, "department_id": r.department_id, "expires_at": _iso(r.expires_at),
                     "max_uses": r.max_uses, "use_count": r.use_count, "revoked": r.revoked_at is not None} for r in rows]

    @router.delete("/spaces/{space_id}/invites/{invite_id}")
    def revoke_invite(space_id: str, invite_id: str, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            row = db.get(OrgInviteRecord, invite_id)
            if row is None or row.space_id != space_id:
                raise HTTPException(404, "Không tìm thấy lời mời.")
            if not (actor.executive or row.created_by == uid):
                raise HTTPException(403, "Bạn không có quyền thu hồi lời mời này.")
            row.revoked_at = row.revoked_at or _now()
            _commit(db)
        return {"invite_id": invite_id, "revoked": True}

    def _usable(row: OrgInviteRecord) -> bool:
        expires = _aware(row.expires_at)
        return (row.revoked_at is None and (expires is None or expires > _now())
                and (row.max_uses is None or row.use_count < row.max_uses))

    @router.get("/invites")
    def my_invites(request: Request) -> list[dict]:
        uid = _uid(request)
        with _db() as db:
            rows = db.scalars(select(OrgInviteRecord).where(OrgInviteRecord.invitee_user_id == uid)
                              .order_by(OrgInviteRecord.created_at.desc())).all()
            out = []
            for r in rows:
                if not _usable(r):
                    continue
                space = db.get(OrgSpaceRecord, r.space_id)
                out.append({"invite_id": r.invite_id, "space_id": r.space_id, "space_name": space.name if space else "",
                            "preset": space.preset if space else "business", "labels": space.labels if space else None,
                            "inviter": _user_label(db, r.created_by), "level": r.level, "department_id": r.department_id,
                            "expires_at": _iso(r.expires_at)})
            return out

    @router.post("/invites/{invite_id}/{decision}")
    def answer_invite(invite_id: str, decision: Literal["accept", "decline"], request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            row = db.get(OrgInviteRecord, invite_id)
            if row is None or row.invitee_user_id != uid or not _usable(row):
                raise HTTPException(404, "Lời mời không còn hiệu lực.")
            space_id = row.space_id
            row.use_count, row.revoked_at = row.use_count + 1, _now()  # mời theo tài khoản chỉ dùng một lần
            if decision == "accept":
                if db.get(OrgMemberRecord, (space_id, uid)) is not None:
                    raise HTTPException(409, "Bạn đã là thành viên hoặc đang chờ duyệt.")
                db.add(OrgMemberRecord(space_id=space_id, user_id=uid, level=row.level,
                                       department_id=row.department_id, status="ACTIVE"))
            if row.created_by:
                _notify(db, [row.created_by], space_id, {"accept": "invite_accepted", "decline": "invite_declined"}[decision],
                        {"space_name": _space_name(db, space_id), "user": _user_label(db, uid)})
            _commit(db)
        return {"invite_id": invite_id, "decision": decision, "space_id": space_id}

    @router.post("/join")
    def join(body: JoinBody, request: Request) -> dict:
        uid = _uid(request)
        now = time.monotonic()
        recent = [t for t in join_failures.get(uid, []) if now - t < JOIN_FAILURE_WINDOW_S]
        if len(recent) >= JOIN_FAILURE_LIMIT:
            raise HTTPException(429, "Nhập sai quá nhiều lần. Thử lại sau 15 phút.")
        raw = body.token.strip()
        candidates = {_sha(raw), _sha(_normalize_code(raw))}
        with _db() as db:
            row = db.scalar(select(OrgInviteRecord).where(
                OrgInviteRecord.kind.in_(("LINK", "CODE")), OrgInviteRecord.token_hash.in_(candidates)))
            if row is None or not _usable(row):
                join_failures[uid] = recent + [now]
                raise HTTPException(404, "Link hoặc mã không đúng, đã hết hạn hoặc đã hết lượt.")
            space_id = row.space_id
            if db.get(OrgMemberRecord, (space_id, uid)) is not None:
                raise HTTPException(409, "Bạn đã là thành viên hoặc đang chờ duyệt.")
            row.use_count += 1
            db.add(OrgMemberRecord(space_id=space_id, user_id=uid, level="STAFF",
                                   department_id=row.department_id, status="PENDING"))
            _notify(db, _approvers(db, space_id, row.department_id), space_id, "join_request",
                    {"space_name": _space_name(db, space_id), "user_id": uid, "user": _user_label(db, uid),
                     "department_id": row.department_id})
            _commit(db)
            join_failures.pop(uid, None)
            return {"space_id": space_id, "space_name": _space_name(db, space_id), "status": "PENDING"}

    # ---------------- Tài liệu tổ chức
    @router.get("/spaces/{space_id}/audience")
    def audience(space_id: str, request: Request) -> dict:
        """Nếu tôi tải tài liệu lên với từng mức mật, bao nhiêu người xem được (cùng luật can_view, như lúc công bố)."""
        uid = _uid(request)
        with _db() as db:
            me = _actor(db, uid, space_id)
            unit = me.department_id or _only_department(db, space_id)
            rows = db.scalars(select(OrgMemberRecord).where(
                OrgMemberRecord.space_id == space_id, OrgMemberRecord.status == "ACTIVE")).all()
            members = [Member(m.user_id, m.space_id, m.department_id, m.level, bool(m.is_owner), m.status) for m in rows]
            counts: dict[str, int | None] = {}
            for level in sorted(SETTABLE.get(me.level, ())):
                bound = level in ("DEPARTMENT", "RESTRICTED")
                if bound and unit is None:
                    counts[level] = None  # cần chọn đơn vị: không đoán
                    continue
                src = Source("_", uid, space_id, unit if bound else None, level)
                counts[level] = sum(can_view(m.user_id, m, src) for m in members)
            dep = db.get(OrgDepartmentRecord, unit) if unit else None
            return {"counts": counts, "total": len(members), "unit_name": dep.name if dep else None}

    # ---------------- Đơn từ và duyệt theo cấp (đợt 10)
    def _request_out(db, r: OrgRequestRecord, uid: str, me) -> dict:
        return {"request_id": r.request_id, "kind": r.kind, "title": r.title, "details": r.details, "days": r.days,
                "approver_level": r.approver_level, "department_id": r.department_id, "status": r.status,
                "requester": _user_label(db, r.requester_id), "mine": r.requester_id == uid,
                "can_decide": r.status == "PENDING" and can_decide_request(me, r.approver_level, r.department_id, r.requester_id),
                "check_result": r.check_result or {}, "history": r.history or [],
                "created_at": _iso(r.created_at), "decided_at": _iso(r.decided_at)}

    @router.post("/spaces/{space_id}/requests")
    def create_request(space_id: str, body: RequestBody, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db, db.begin():
            me = _actor(db, uid, space_id)
            department = me.department_id or _only_department(db, space_id)
            if body.approver_level == "MANAGER" and department is None:
                raise HTTPException(400, "Bạn chưa thuộc phòng ban nào nên đơn phải gửi Ban giám đốc duyệt.")
            approvers = [a for a in _approvers(db, space_id, department if body.approver_level == "MANAGER" else None) if a != uid]
            if not approvers:
                # P1-4: người duy nhất có quyền duyệt tự gửi đơn thì không ai duyệt được: báo rõ thay vì để đơn treo mãi
                raise HTTPException(409, "Không có ai khác duyệt được đơn này (bạn là người duy nhất ở cấp duyệt). "
                                         "Nhờ chủ tổ chức thêm người vào Ban giám đốc ở trang Tổ chức rồi gửi lại.")
            row = OrgRequestRecord(request_id=_new_id("req"), space_id=space_id, requester_id=uid, department_id=department,
                                   kind=body.kind, title=body.title.strip(), details=body.details.strip(), days=body.days,
                                   approver_level=body.approver_level, status="PENDING", check_result=body.check_result,
                                   history=[{"at": _iso(_now()), "by": _user_label(db, uid), "action": "SUBMITTED"}], created_at=_now())
            db.add(row)
            _notify(db, approvers, space_id, "request_submitted",
                    {"space_name": _space_name(db, space_id), "user": _user_label(db, uid), "title": row.title, "request_id": row.request_id})
            db.flush()
            return _request_out(db, row, uid, me)

    @router.get("/spaces/{space_id}/requests/approvers")
    def request_approvers(space_id: str, request: Request, level: Literal["MANAGER", "EXECUTIVE"] = "MANAGER") -> dict:
        """Trước khi gửi: có bao nhiêu người khác duyệt được đơn ở cấp này (P1-4). Chỉ trả số và tên gọi, không lộ danh sách."""
        uid = _uid(request)
        with _db() as db:
            me = _actor(db, uid, space_id)
            department = me.department_id or _only_department(db, space_id)
            count = len([a for a in _approvers(db, space_id, department if level == "MANAGER" else None) if a != uid])
            return {"level": level, "count": count, "needs_department": level == "MANAGER" and department is None}

    @router.get("/spaces/{space_id}/requests")
    def list_requests(space_id: str, request: Request) -> dict:
        """Đơn tôi đã gửi và đơn chờ tôi duyệt (chỉ người gửi và người có quyền duyệt thấy đơn)."""
        uid = _uid(request)
        with _db() as db:
            me = _actor(db, uid, space_id)
            rows = db.scalars(select(OrgRequestRecord).where(OrgRequestRecord.space_id == space_id)
                              .order_by(OrgRequestRecord.created_at.desc()).limit(500)).all()
            mine = [_request_out(db, r, uid, me) for r in rows if r.requester_id == uid]
            to_me = [_request_out(db, r, uid, me) for r in rows
                     if r.requester_id != uid and can_decide_request(me, r.approver_level, r.department_id, r.requester_id)]
            return {"mine": mine, "to_me": to_me}

    @router.post("/spaces/{space_id}/requests/{request_id}/decide")
    def decide_request(space_id: str, request_id: str, body: DecideBody, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db, db.begin():
            me = _actor(db, uid, space_id)
            row = db.get(OrgRequestRecord, request_id, with_for_update=True)
            if row is None or row.space_id != space_id:
                raise HTTPException(404, "Không tìm thấy đơn.")
            if not can_decide_request(me, row.approver_level, row.department_id, row.requester_id):
                raise HTTPException(403, "Bạn không có quyền duyệt đơn này.")
            if row.status != "PENDING":
                raise HTTPException(409, "Đơn đã được xử lý.")
            row.status, row.decided_at = body.decision, _now()
            row.history = [*(row.history or []), {"at": _iso(row.decided_at), "by": _user_label(db, uid), "action": body.decision, "note": body.note.strip()}]
            _notify(db, [row.requester_id], space_id, "request_decided",
                    {"space_name": _space_name(db, space_id), "by": _user_label(db, uid), "title": row.title, "decision": body.decision})
            db.flush()
            return _request_out(db, row, uid, me)

    @router.post("/spaces/{space_id}/requests/{request_id}/withdraw")
    def withdraw_request(space_id: str, request_id: str, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db, db.begin():
            me = _actor(db, uid, space_id)
            row = db.get(OrgRequestRecord, request_id, with_for_update=True)
            if row is None or row.space_id != space_id or row.requester_id != uid:
                raise HTTPException(404, "Không tìm thấy đơn.")
            if row.status != "PENDING":
                raise HTTPException(409, "Đơn đã được xử lý, không rút lại được.")
            row.status = "WITHDRAWN"
            row.history = [*(row.history or []), {"at": _iso(_now()), "by": _user_label(db, uid), "action": "WITHDRAWN"}]
            db.flush()
            return _request_out(db, row, uid, me)

    @router.get("/spaces/{space_id}/secret-access")
    def secret_access(space_id: str, request: Request, limit: int = 200) -> list[dict]:
        """Nhật ký truy cập tài liệu mức Mật (đợt 9). Chỉ Ban giám đốc và chủ tổ chức xem được."""
        uid = _uid(request)
        with _db() as db:
            me = _actor(db, uid, space_id)
            if not (me.executive or me.is_owner):
                raise HTTPException(403, "Chỉ Ban giám đốc xem được nhật ký truy cập tài liệu Mật.")
            rows = db.execute(
                select(OrgSecretAccessRecord, KnowledgeSourceRecord.source_name)
                .join(KnowledgeSourceRecord, KnowledgeSourceRecord.source_id == OrgSecretAccessRecord.source_id)
                .where(OrgSecretAccessRecord.space_id == space_id)
                .order_by(OrgSecretAccessRecord.created_at.desc(), OrgSecretAccessRecord.access_id.desc())
                .limit(max(1, min(int(limit), 1000)))
            ).all()
            return [{"source_id": r.source_id, "source_name": name, "user": _user_label(db, r.user_id),
                     "action": r.action, "at": _iso(r.created_at)} for r, name in rows]

    @router.get("/spaces/{space_id}/sources")
    def list_sources(space_id: str, request: Request) -> list[dict]:
        uid = _uid(request)
        with _db() as db:
            me = _actor(db, uid, space_id)
            visible = visible_source_ids(db, uid, space_id)
            if not visible:
                return []
            rows = db.scalars(select(KnowledgeSourceRecord).where(
                KnowledgeSourceRecord.source_id.in_(sorted(visible))).order_by(KnowledgeSourceRecord.source_name)).all()
            counts = dict(db.execute(select(KnowledgeChunkRecord.source_id, func.count()).where(
                KnowledgeChunkRecord.source_id.in_(sorted(visible))).group_by(KnowledgeChunkRecord.source_id)).all())
            return [{"source_id": r.source_id, "source_name": r.source_name, "status": r.status,
                     "chunk_count": int(counts.get(r.source_id, 0)),
                     "classification": r.classification, "department_id": r.department_id,
                     "owner": _user_label(db, r.owner_user_id), "mine": r.owner_user_id == uid,
                     "can_delete": can_delete(uid, me, _source(r)), "created_at": _iso(r.created_at),
                     "doc_type": (r.display_metadata or {}).get("doc_type")} for r in rows]

    @router.post("/spaces/{space_id}/sources/{source_id}/publish")
    def publish(space_id: str, source_id: str, body: PublishBody, request: Request) -> dict:
        """Nộp một tài liệu cá nhân (đã tải lên như hiện nay) vào không gian, kèm phòng ban và mức mật."""
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            row = db.get(KnowledgeSourceRecord, source_id)
            if row is None or row.owner_user_id != uid or row.space_id is not None:
                raise HTTPException(404, "Không tìm thấy tài liệu cá nhân này.")
            department_id = body.department_id
            if department_id is None and body.classification in ("DEPARTMENT", "RESTRICTED"):
                department_id = actor.department_id or _only_department(db, space_id)
            _department(db, space_id, department_id)
            if not can_upload(actor, body.classification, department_id):
                raise HTTPException(403, "Bạn không được đặt mức mật hoặc đơn vị này.")
            row.space_id, row.department_id, row.classification = space_id, department_id, body.classification
            # rời thư mục cá nhân (Studio); bảng chỉ có trên PostgreSQL thật
            db.execute(text("DELETE FROM studio_workspace_items WHERE item_type = 'source' AND item_id = :s"),
                       {"s": source_id})
            # nhật ký hoạt động (ADMIN xem được) đã ghi tên tệp lúc tải lên: che đi, tên tài liệu tổ chức là nội dung tổ chức
            db.execute(text("UPDATE studio_activity SET target = :mask WHERE owner_user_id = :o "
                            "AND action = 'Nạp tài liệu' AND target = :name"),
                       {"mask": ORG_AUDIT_MASK, "o": uid, "name": row.source_name[:200]})
            _notify_new_viewers(db, row, set(), uid, "source_published")
            _commit(db)
            source_name = row.source_name
        # RET-04: kiểm tra văn bản thay thế/mâu thuẫn trong không gian sau khi công bố (lỗi phụ không làm hỏng publish)
        try:
            import logging
            from app.analysis.watch import notify_findings, watch_findings
            from app.storage.postgres.runtime import PostgresSourceStore
            factory = session_factory()
            findings = watch_findings(source_id, PostgresSourceStore(factory, uid, space_id).chunks())
            if findings:
                notify_findings(factory, uid, source_name, findings)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("org doc watch failed")
        return {"source_id": source_id, "space_id": space_id, "classification": body.classification,
                "department_id": department_id}

    @router.patch("/spaces/{space_id}/sources/{source_id}")
    def update_source(space_id: str, source_id: str, body: SourceUpdate, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            row = _space_source(db, space_id, source_id, uid)
            before = _viewers(db, row)
            if body.department_id is not None and body.department_id != row.department_id:
                if not actor.executive:
                    raise HTTPException(403, "Bạn không có quyền chuyển tài liệu sang đơn vị khác.")
                _department(db, space_id, body.department_id)
                row.department_id = body.department_id
            if body.classification is not None and body.classification != row.classification:
                if body.classification in ("DEPARTMENT", "RESTRICTED") and row.department_id is None:
                    row.department_id = actor.department_id or _only_department(db, space_id)
                    if row.department_id is None:
                        raise HTTPException(409, "Mức này chỉ đặt được khi tài liệu thuộc một đơn vị: chọn đơn vị cho tài liệu trước.")
                if not can_change_classification(actor, _source(row), body.classification):
                    raise HTTPException(403, "Bạn không được đổi sang mức mật này.")
                row.classification = body.classification
            try:
                _notify_new_viewers(db, row, before, uid, "source_access_granted")
            except IntegrityError as exc:  # mức mật cần phòng ban mà tài liệu chưa có: báo lỗi rõ thay vì 500
                db.rollback()
                raise HTTPException(409, "Mức này chỉ đặt được khi tài liệu thuộc một đơn vị: chọn đơn vị cho tài liệu trước.") from exc
            _commit(db, "Mức này chỉ đặt được khi tài liệu thuộc một đơn vị: chọn đơn vị cho tài liệu trước.")
            return {"source_id": source_id, "classification": row.classification, "department_id": row.department_id}

    @router.post("/spaces/{space_id}/sources/{source_id}/shares")
    def share(space_id: str, source_id: str, body: ShareBody, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            row = _space_source(db, space_id, source_id, uid)
            if (body.user_id is None) == (body.department_id is None):
                raise HTTPException(422, "Chọn đúng một người hoặc một đơn vị để chia sẻ.")
            target_member = load_member(db, body.user_id, space_id) if body.user_id else None
            if body.user_id and target_member is None:
                raise HTTPException(404, "Không tìm thấy thành viên.")
            target_department = None
            if body.department_id:
                _department(db, space_id, body.department_id)
                target_department = Department(space_id, body.department_id)
            if not can_share(actor, _source(row), target_member=target_member, target_department=target_department):
                raise HTTPException(403, "Bạn không có quyền chia sẻ tài liệu này cho đích đó.")
            share_id = _new_id("shr")
            db.add(OrgSourceShareRecord(share_id=share_id, source_id=source_id, target_user_id=body.user_id,
                                        target_department_id=body.department_id, shared_by=uid))
            try:
                db.flush()  # phát hiện chia sẻ trùng trước khi truy vấn tiếp (autoflush sẽ ném lỗi ngoài _commit)
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(409, "Tài liệu đã được chia sẻ cho đích này.") from exc
            recipients = [body.user_id] if body.user_id else list(db.scalars(select(OrgMemberRecord.user_id).where(
                OrgMemberRecord.space_id == space_id, OrgMemberRecord.department_id == body.department_id,
                OrgMemberRecord.status == "ACTIVE")))
            _notify(db, [r for r in recipients if r != uid], space_id, "source_shared",
                    {"space_name": _space_name(db, space_id), "source_name": row.source_name, "by": _user_label(db, uid)})
            _commit(db, "Tài liệu đã được chia sẻ cho đích này.")
        return {"share_id": share_id}

    @router.get("/spaces/{space_id}/sources/{source_id}/shares")
    def list_shares(space_id: str, source_id: str, request: Request) -> list[dict]:
        uid = _uid(request)
        with _db() as db:
            _actor(db, uid, space_id)
            _space_source(db, space_id, source_id, uid)
            rows = db.scalars(select(OrgSourceShareRecord).where(OrgSourceShareRecord.source_id == source_id)).all()
            return [{"share_id": r.share_id, "user_id": r.target_user_id, "user": _user_label(db, r.target_user_id) or None,
                     "department_id": r.target_department_id, "shared_by": _user_label(db, r.shared_by)} for r in rows]

    @router.delete("/spaces/{space_id}/shares/{share_id}")
    def unshare(space_id: str, share_id: str, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            actor = _actor(db, uid, space_id)
            row = db.get(OrgSourceShareRecord, share_id)
            source = None if row is None else db.get(KnowledgeSourceRecord, row.source_id)
            if row is None or source is None or source.space_id != space_id:
                raise HTTPException(404, "Không tìm thấy lượt chia sẻ.")
            if not (actor.executive or row.shared_by == uid or actor.manages(source.department_id)):
                raise HTTPException(403, "Bạn không có quyền gỡ lượt chia sẻ này.")
            db.delete(row)
            _commit(db)
        return {"deleted": share_id}

    # ---------------- Thông báo (chuông)
    @router.get("/notifications")
    def notifications(request: Request, limit: int = 50) -> dict:
        uid = _uid(request)
        with _db() as db:
            rows = db.scalars(select(NotificationRecord).where(NotificationRecord.user_id == uid).order_by(
                NotificationRecord.created_at.desc()).limit(max(1, min(limit, 200)))).all()
            unread = int(db.scalar(select(func.count()).select_from(NotificationRecord).where(
                NotificationRecord.user_id == uid, NotificationRecord.read_at.is_(None))) or 0)
            return {"unread": unread, "items": [
                {"notification_id": r.notification_id, "kind": r.kind, "space_id": r.space_id, "payload": r.payload,
                 "read": r.read_at is not None, "created_at": _iso(r.created_at)} for r in rows]}

    @router.post("/notifications/read")
    def mark_read(body: ReadBody, request: Request) -> dict:
        uid = _uid(request)
        with _db() as db:
            query = select(NotificationRecord).where(NotificationRecord.user_id == uid, NotificationRecord.read_at.is_(None))
            if not body.all:
                query = query.where(NotificationRecord.notification_id.in_(body.ids or ["-"]))
            rows = db.scalars(query).all()
            for row in rows:
                row.read_at = _now()
            _commit(db)
        return {"marked": len(rows)}

    return router
