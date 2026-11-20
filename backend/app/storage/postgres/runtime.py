from __future__ import annotations
import threading

import hashlib
import re
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import cast, delete, false, func, literal, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.store import (
    AUTH_SCHEMA_VERSION,
    DEFAULT_SESSION_TTL_SECONDS,
    PASSWORD_MIN_LENGTH,
    USER_ROLES,
    DuplicateUserError,
    InvalidCredentialsError,
    InvalidSessionError,
    _iso,
    _normalized_email,
    _normalized_username,
    _password_hash,
    _password_matches,
    _parse_iso,
    _token_hash,
)
from app.core.access import REDACTED_ANSWER, redact_run, referenced_source_ids, visible_source_ids
from app.core.types import SourceChunk
from app.ingestion.doc_type import DOC_TYPES, classify_document, DOC_TYPE_VERSION
from app.retrieval.text import make_chunks, normalize_text
from app.storage.postgres.models import (
    ConversationMessageRecord,
    ConversationRecord,
    KnowledgeChunkRecord,
    KnowledgeSourceRecord,
    RunRecord,
    SessionRecord,
    UserRecord,
)


_LAST_NOW: datetime | None = None
_NOW_LOCK = threading.Lock()


def _now() -> datetime:
    """Giờ UTC tăng nghiêm ngặt trong tiến trình: đồng hồ Windows có thể trả cùng giá trị cho hai lần gọi liền nhau,
    làm hai bản ghi tạo liền nhau (cuộc trò chuyện, tin nhắn) có thứ tự không xác định (kiểm thử chập chờn 20/11)."""
    global _LAST_NOW
    with _NOW_LOCK:
        now = datetime.now(timezone.utc)
        if _LAST_NOW is not None and now <= _LAST_NOW:
            now = _LAST_NOW + timedelta(microseconds=1)
        _LAST_NOW = now
        return now


def _public_user(user: UserRecord) -> dict[str, Any]:
    return {
        "id": user.user_id,
        "user_id": user.user_id,
        "email": user.email,
        "username": user.username,
        "name": user.display_name,
        "display_name": user.display_name,
        "role": user.role.upper(),
        "created_at": _iso(user.created_at),
        "updated_at": _iso(user.updated_at),
        "last_login_at": None if user.last_login_at is None else _iso(user.last_login_at),
        "status": user.status.upper(),
        "avatar": user.avatar,
    }


# ảnh mẫu do giao diện vẽ (preset:<mã>) hoặc ảnh tải lên đã thu nhỏ; chỉ nhận PNG/JPEG/WebP, không nhận SVG
_AVATAR_RE = re.compile(r"^(preset:[a-z0-9-]{1,32}|data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2})$")
AVATAR_MAX_CHARS = 200_000


def _public_session(session: SessionRecord) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "created_at": _iso(session.created_at),
        "expires_at": _iso(session.expires_at),
    }


class PostgresAuthStore:
    """PostgreSQL implementation of the existing user/session contract."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> None:
        self.session_factory = session_factory
        self.session_ttl_seconds = max(60, int(session_ttl_seconds))
        self._bootstrap_admin_from_environment()

    def _bootstrap_admin_from_environment(self) -> None:
        email = _normalized_email(os.getenv("LOCAL_AUTH_ADMIN_EMAIL"))
        password = os.getenv("LOCAL_AUTH_ADMIN_PASSWORD", "")
        if not email or len(password) < PASSWORD_MIN_LENGTH:
            return
        with self.session_factory.begin() as db:
            if db.scalar(select(func.count()).select_from(UserRecord)):
                return
            now = _now()
            db.add(UserRecord(
                user_id=f"usr_{secrets.token_urlsafe(12)}",
                email=email,
                display_name=email.split("@", 1)[0],
                password_hash=_password_hash(password),
                role="ADMIN",
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            ))

    def register(
        self,
        *,
        password: str,
        email: str | None = None,
        username: str | None = None,
        display_name: str | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        email_value = _normalized_email(email)
        username_value = _normalized_username(username)
        if not email_value and not username_value:
            raise ValueError("email or username is required")
        if email_value and ("@" not in email_value or len(email_value) > 254):
            raise ValueError("email is invalid")
        if username_value and not re.fullmatch(
            r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,63}$", username_value
        ):
            raise ValueError("username is invalid")
        if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"password must be at least {PASSWORD_MIN_LENGTH} characters")
        requested_role = str(role or "USER").strip().upper()
        if requested_role not in USER_ROLES:
            raise ValueError("role must be USER or ADMIN")

        now = _now()
        try:
            with self.session_factory.begin() as db:
                existing = db.scalar(select(UserRecord.user_id).where(or_(
                    UserRecord.email == email_value if email_value else False,
                    UserRecord.username == username_value if username_value else False,
                )))
                if existing:
                    raise DuplicateUserError("email or username is already registered")
                assigned_role = requested_role if not db.scalar(
                    select(func.count()).select_from(UserRecord)
                ) else "USER"
                name = (display_name or username_value or email_value.split("@", 1)[0]).strip()
                record = UserRecord(
                    user_id=f"usr_{secrets.token_urlsafe(12)}",
                    email=email_value or None,
                    username=username_value or None,
                    display_name=name,
                    role=assigned_role,
                    status="ACTIVE",
                    password_hash=_password_hash(password),
                    created_at=now,
                    updated_at=now,
                )
                db.add(record)
                db.flush()
                result = _public_user(record)
        except IntegrityError as exc:
            raise DuplicateUserError("email or username is already registered") from exc
        return result

    def authenticate(self, *, identifier: str, password: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
        normalized = str(identifier or "").strip().lower()
        if not normalized or not isinstance(password, str):
            raise InvalidCredentialsError("invalid credentials")
        now = _now()
        with self.session_factory.begin() as db:
            user = db.scalar(select(UserRecord).where(or_(
                UserRecord.email == normalized, UserRecord.username == normalized
            )))
            if (
                user is None
                or user.status.upper() != "ACTIVE"
                or not _password_matches(password, user.password_hash)
            ):
                raise InvalidCredentialsError("invalid credentials")
            user.last_login_at = now
            user.updated_at = now
            token = secrets.token_urlsafe(32)
            record = SessionRecord(
                session_id=f"ses_{secrets.token_urlsafe(12)}",
                user_id=user.user_id,
                token_hash=_token_hash(token),
                created_at=now,
                expires_at=now + timedelta(seconds=self.session_ttl_seconds),
            )
            db.add(record)
            db.flush()
            return _public_user(user), token, _public_session(record)

    def create_session(self, user_id: str) -> tuple[str, dict[str, Any]]:
        now = _now()
        token = secrets.token_urlsafe(32)
        with self.session_factory.begin() as db:
            user = db.get(UserRecord, user_id)
            if user is None or user.status.upper() != "ACTIVE":
                raise InvalidCredentialsError("user not found")
            record = SessionRecord(
                session_id=f"ses_{secrets.token_urlsafe(12)}",
                user_id=user_id,
                token_hash=_token_hash(token),
                created_at=now,
                expires_at=now + timedelta(seconds=self.session_ttl_seconds),
            )
            db.add(record)
            db.flush()
            return token, _public_session(record)

    def resolve(self, token: str | None) -> dict[str, Any]:
        if not isinstance(token, str) or not token.strip():
            raise InvalidSessionError("authentication is required")
        digest = _token_hash(token.strip())
        now = _now()
        with self.session_factory() as db:
            row = db.execute(
                select(SessionRecord, UserRecord)
                .join(UserRecord, UserRecord.user_id == SessionRecord.user_id)
                .where(
                    SessionRecord.token_hash == digest,
                    SessionRecord.revoked_at.is_(None),
                    SessionRecord.expires_at > now,
                    UserRecord.status == "ACTIVE",
                )
            ).first()
            if row is None:
                raise InvalidSessionError("session is invalid or expired")
            return _public_user(row[1])

    def revoke(self, token: str | None) -> bool:
        if not isinstance(token, str) or not token.strip():
            return False
        with self.session_factory.begin() as db:
            record = db.scalar(select(SessionRecord).where(
                SessionRecord.token_hash == _token_hash(token.strip()),
                SessionRecord.revoked_at.is_(None),
            ))
            if record is None:
                return False
            record.revoked_at = _now()
            return True

    def session_for_token(self, token: str | None) -> dict[str, Any] | None:
        if not isinstance(token, str) or not token.strip():
            return None
        now = _now()
        with self.session_factory() as db:
            record = db.scalar(select(SessionRecord).where(
                SessionRecord.token_hash == _token_hash(token.strip()),
                SessionRecord.revoked_at.is_(None),
                SessionRecord.expires_at > now,
            ))
            return None if record is None else _public_session(record)

    def list_users(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self.session_factory() as db:
            rows = db.scalars(select(UserRecord).order_by(
                UserRecord.created_at.desc(), UserRecord.user_id.desc()
            ).offset(offset).limit(limit)).all()
            return [_public_user(row) for row in rows]

    def user_count(self) -> int:
        with self.session_factory() as db:
            return int(db.scalar(select(func.count()).select_from(UserRecord)) or 0)

    def status(self) -> dict[str, Any]:
        now = _now()
        with self.session_factory() as db:
            return {
                "schema_version": AUTH_SCHEMA_VERSION,
                "local_only": True,
                "user_count": int(db.scalar(select(func.count()).select_from(UserRecord)) or 0),
                "admin_count": int(db.scalar(select(func.count()).select_from(UserRecord).where(UserRecord.role == "ADMIN")) or 0),
                "active_session_count": int(db.scalar(select(func.count()).select_from(SessionRecord).where(
                    SessionRecord.revoked_at.is_(None), SessionRecord.expires_at > now
                )) or 0),
                "session_ttl_seconds": self.session_ttl_seconds,
            }

    # ---- Quản trị tài khoản (trang Quản lý người dùng, chỉ ADMIN gọi) ----

    def admin_users(self, *, query: str = "") -> list[dict[str, Any]]:
        """Mọi tài khoản kèm số phiên đang mở, số tài liệu và số lượt hỏi (không trả mật khẩu băm)."""
        now = _now()
        sessions = (select(SessionRecord.user_id, func.count().label("n"))
                    .where(SessionRecord.revoked_at.is_(None), SessionRecord.expires_at > now)
                    .group_by(SessionRecord.user_id).subquery())
        sources = (select(KnowledgeSourceRecord.owner_user_id.label("uid"), func.count().label("n"))
                   .group_by(KnowledgeSourceRecord.owner_user_id).subquery())
        runs = (select(RunRecord.owner_user_id.label("uid"), func.count().label("n"))
                .group_by(RunRecord.owner_user_id).subquery())
        stmt = (select(UserRecord, sessions.c.n, sources.c.n, runs.c.n)
                .outerjoin(sessions, sessions.c.user_id == UserRecord.user_id)
                .outerjoin(sources, sources.c.uid == UserRecord.user_id)
                .outerjoin(runs, runs.c.uid == UserRecord.user_id)
                .order_by(UserRecord.created_at.desc(), UserRecord.user_id.desc()))
        q = str(query or "").strip().lower()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(func.lower(UserRecord.email).like(like), func.lower(UserRecord.username).like(like),
                                  func.lower(UserRecord.display_name).like(like)))
        with self.session_factory() as db:
            return [{**_public_user(u), "active_sessions": int(s or 0), "source_count": int(c or 0), "run_count": int(r or 0)}
                    for u, s, c, r in db.execute(stmt.limit(1000)).all()]

    @staticmethod
    def _other_active_admins(db: Session, user_id: str) -> int:
        return int(db.scalar(select(func.count()).select_from(UserRecord).where(
            UserRecord.role == "ADMIN", UserRecord.status == "ACTIVE", UserRecord.user_id != user_id)) or 0)

    @staticmethod
    def _revoke_all(db: Session, user_id: str) -> int:
        open_sessions = db.scalars(select(SessionRecord).where(
            SessionRecord.user_id == user_id, SessionRecord.revoked_at.is_(None))).all()
        now = _now()
        for record in open_sessions:
            record.revoked_at = now
        return len(open_sessions)

    def admin_update_user(self, user_id: str, *, actor_id: str, role: str | None = None,
                          status: str | None = None, display_name: str | None = None) -> dict[str, Any]:
        """Đổi vai trò / trạng thái / tên hiển thị. Khóa tài khoản thì thu hồi mọi phiên của tài khoản đó ngay.

        Rào chắn: không tự đổi vai trò hay tự khóa chính mình; không hạ quyền hay khóa ADMIN đang hoạt động cuối cùng.
        """
        with self.session_factory.begin() as db:
            user = db.get(UserRecord, user_id)
            if user is None:
                raise KeyError(user_id)
            new_role = None if role is None else str(role).strip().upper()
            new_status = None if status is None else str(status).strip().upper()
            if new_role is not None and new_role not in USER_ROLES:
                raise ValueError("role must be USER or ADMIN")
            if new_status is not None and new_status not in ("ACTIVE", "DISABLED"):
                raise ValueError("status must be ACTIVE or DISABLED")
            if user_id == actor_id and ((new_role and new_role != user.role) or (new_status and new_status != user.status)):
                raise PermissionError("Không thể tự đổi vai trò hoặc tự khóa tài khoản của chính mình.")
            loses_admin = user.role == "ADMIN" and user.status == "ACTIVE" and (new_role == "USER" or new_status == "DISABLED")
            if loses_admin and self._other_active_admins(db, user_id) == 0:
                raise PermissionError("Phải còn ít nhất một quản trị viên đang hoạt động.")
            if display_name is not None:
                name = str(display_name).strip()
                if not name or len(name) > 128:
                    raise ValueError("display_name must be 1-128 characters")
                user.display_name = name
            if new_role:
                user.role = new_role
            if new_status:
                user.status = new_status
                if new_status == "DISABLED":
                    self._revoke_all(db, user_id)
            user.updated_at = _now()
            db.flush()
            return _public_user(user)

    def set_avatar(self, user_id: str, avatar: str | None) -> dict[str, Any]:
        """Người dùng tự đổi ảnh đại diện của mình; None hoặc chuỗi rỗng = bỏ ảnh."""
        value = (avatar or "").strip() or None
        if value is not None and (len(value) > AVATAR_MAX_CHARS or not _AVATAR_RE.match(value)):
            raise ValueError("Ảnh đại diện không hợp lệ (chỉ PNG, JPEG, WebP dưới 150 KB hoặc ảnh mẫu).")
        with self.session_factory.begin() as db:
            user = db.get(UserRecord, user_id)
            if user is None:
                raise KeyError(user_id)
            user.avatar = value
            user.updated_at = _now()
            db.flush()
            return _public_user(user)

    def admin_reset_password(self, user_id: str) -> tuple[dict[str, Any], str]:
        """Đặt mật khẩu tạm ngẫu nhiên (trả về đúng một lần để admin đưa cho người dùng) và đăng xuất mọi phiên cũ."""
        temporary = secrets.token_urlsafe(12)
        with self.session_factory.begin() as db:
            user = db.get(UserRecord, user_id)
            if user is None:
                raise KeyError(user_id)
            user.password_hash = _password_hash(temporary)
            user.updated_at = _now()
            self._revoke_all(db, user_id)
            db.flush()
            return _public_user(user), temporary

    def admin_revoke_sessions(self, user_id: str) -> int:
        with self.session_factory.begin() as db:
            if db.get(UserRecord, user_id) is None:
                raise KeyError(user_id)
            return self._revoke_all(db, user_id)


class PostgresSourceStore:
    """A source/chunk store bound to one authenticated user and one scope.

    space_id None = không gian cá nhân (chỉ tài liệu của chính người dùng, không thuộc tổ chức nào).
    space_id khác None = không gian tổ chức: chỉ đọc tài liệu mà app.core.access cho phép.
    Ghi (import, mark_failed, clear) vẫn theo chủ tài liệu.
    """

    def __init__(self, session_factory: sessionmaker[Session], owner_user_id: str,
                 space_id: str | None = None) -> None:
        self.session_factory = session_factory
        self.owner_user_id = owner_user_id
        self.space_id = space_id

    def scope_source_ids(self) -> set[str]:
        """Tài liệu được đọc trong phạm vi này; tính lại mỗi lần để quyền mới có hiệu lực ngay."""
        with self.session_factory() as db:
            return visible_source_ids(db, self.owner_user_id, self.space_id)

    def _read_filters(self) -> list[Any]:
        if self.space_id is None:
            # tài liệu tổ chức do mình tải lên không lọt sang phạm vi cá nhân (kể cả sau khi bị gỡ khỏi tổ chức)
            return [KnowledgeSourceRecord.owner_user_id == self.owner_user_id,
                    KnowledgeSourceRecord.space_id.is_(None)]
        allowed = self.scope_source_ids()
        return [KnowledgeSourceRecord.source_id.in_(sorted(allowed))] if allowed else [false()]

    def import_text(
        self,
        source_name: str,
        text: str,
        *,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_text = normalize_text(text)
        if not str(source_name or "").strip():
            raise ValueError("source_name must not be empty")
        if not clean_text:
            raise ValueError("text must not be empty")
        original_source_id = "src_" + hashlib.sha256(
            (str(source_name).strip() + "\0" + clean_text).encode("utf-8")
        ).hexdigest()[:16]
        source_id = "src_" + hashlib.sha256(
            f"{self.owner_user_id}\0{original_source_id}".encode("utf-8")
        ).hexdigest()[:16]
        metadata = {
            "storage": "postgresql",
            "indexing_version": "s2-lifecycle-v1",
            **(dict(provenance) if isinstance(provenance, dict) else {}),
        }
        source_provenance = {
            **metadata,
            "source_id": source_id,
            "source_name": str(source_name).strip(),
            "source_hash": hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
            "source_version": source_id,
        }
        metadata = {**source_provenance, "doc_type": classify_document(str(source_name), clean_text), "doc_type_by": "auto", "doc_type_v": DOC_TYPE_VERSION}
        now = _now()
        with self.session_factory.begin() as db:
            source = db.get(KnowledgeSourceRecord, source_id)
            old_meta = dict(source.display_metadata or {}) if source is not None else {}
            if old_meta.get("doc_type_by") == "user":  # nhãn người dùng đã sửa thì giữ khi nạp lại
                metadata = {**metadata, "doc_type": old_meta.get("doc_type"), "doc_type_by": "user"}
            if source is None:
                db.add(
                    KnowledgeSourceRecord(
                        source_id=source_id,
                        owner_user_id=self.owner_user_id,
                        source_name=str(source_name).strip(),
                        status="PROCESSING",
                        display_metadata=metadata,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif source.owner_user_id != self.owner_user_id:
                raise PermissionError("source belongs to another owner")
            else:
                source.status = "PROCESSING"
                source.display_metadata = metadata
                source.updated_at = now

        try:
            chunks = make_chunks(
                str(source_name).strip(), clean_text, provenance=source_provenance
            )
            if not chunks:
                raise ValueError("text must not be empty")
            owned_chunks = [
                SourceChunk(
                    chunk_id=f"{source_id}_c{chunk.index:04d}",
                    source_id=source_id,
                    source_name=chunk.source_name,
                    text=chunk.text,
                    index=chunk.index,
                    provenance={
                        **chunk.provenance,
                        "chunk_id": f"{source_id}_c{chunk.index:04d}",
                    },
                )
                for chunk in chunks
            ]
        except Exception as exc:
            self.mark_failed(source_id, exc)
            raise

        try:
            with self.session_factory.begin() as db:
                source = db.get(KnowledgeSourceRecord, source_id)
                if source is None or source.owner_user_id != self.owner_user_id:
                    raise PermissionError("source belongs to another owner")
                existing = set(db.scalars(select(KnowledgeChunkRecord.chunk_id).where(
                    KnowledgeChunkRecord.source_id == source_id
                )).all())
                added = [chunk for chunk in owned_chunks if chunk.chunk_id not in existing]
                db.add_all([
                    KnowledgeChunkRecord(
                        chunk_id=chunk.chunk_id,
                        source_id=source_id,
                        chunk_index=chunk.index,
                        content=chunk.text,
                        provenance=dict(chunk.provenance),
                        indexing_version="s2-lifecycle-v1",
                    )
                    for chunk in added
                ])
                source.status = "READY"
                source.display_metadata = {**metadata, "status": "READY"}
                source.updated_at = _now()
        except Exception as exc:
            self.mark_failed(source_id, exc)
            raise
        return {
            "source_id": source_id,
            "source_name": source_name,
            "chunks_added": len(added),
            "total_chunks_for_source": len(owned_chunks),
            "source_hash": source_provenance["source_hash"],
            "source_version": source_id,
            "provenance": dict(source_provenance),
            "snapshot_id": self.snapshot_id(),
        }

    def mark_failed(self, source_id: str, error: Exception | str) -> None:
        """Persist a terminal FAILED state without exposing source contents."""

        with self.session_factory.begin() as db:
            source = db.scalar(
                select(KnowledgeSourceRecord).where(
                    KnowledgeSourceRecord.source_id == source_id,
                    KnowledgeSourceRecord.owner_user_id == self.owner_user_id,
                )
            )
            if source is None:
                return
            source.status = "FAILED"
            source.display_metadata = {
                **(source.display_metadata or {}),
                "status": "FAILED",
                "error_type": type(error).__name__ if isinstance(error, Exception) else "IngestionError",
                "error": str(error),
            }
            source.updated_at = _now()

    def source_status(self, source_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            source = db.scalar(
                select(KnowledgeSourceRecord).where(
                    KnowledgeSourceRecord.source_id == source_id,
                    *self._read_filters(),
                )
            )
            if source is None:
                return None
            return {
                "source_id": source.source_id,
                "source_name": source.source_name,
                "status": source.status,
                "metadata": dict(source.display_metadata or {}),
            }

    def chunks(self, source_ids: list[str] | None = None) -> list[SourceChunk]:
        with self.session_factory() as db:
            filters = [
                *self._read_filters(),
                KnowledgeSourceRecord.status == "READY",
            ]
            if source_ids is not None:
                filters.append(KnowledgeChunkRecord.source_id.in_(source_ids))
            rows = db.scalars(
                select(KnowledgeChunkRecord)
                .join(KnowledgeSourceRecord)
                .where(*filters)
                .order_by(KnowledgeChunkRecord.source_id, KnowledgeChunkRecord.chunk_index)
            ).all()
            return [self._chunk(row) for row in rows]

    def validate_source_selection(self, source_ids: list[str]) -> None:
        """Reject missing, non-ready, or foreign source IDs before retrieval."""

        requested = {str(source_id) for source_id in source_ids if str(source_id)}
        if not requested:
            return
        with self.session_factory() as db:
            available = set(
                db.scalars(
                    select(KnowledgeSourceRecord.source_id).where(
                        *self._read_filters(),
                        KnowledgeSourceRecord.status == "READY",
                        KnowledgeSourceRecord.source_id.in_(requested),
                    )
                ).all()
            )
        if available != requested:
            raise LookupError("source not found")

    def list_sources(self) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.execute(
                select(KnowledgeSourceRecord, func.count(KnowledgeChunkRecord.chunk_id))
                .outerjoin(KnowledgeChunkRecord)
                .where(*self._read_filters())
                .group_by(KnowledgeSourceRecord.source_id)
                .order_by(KnowledgeSourceRecord.source_name, KnowledgeSourceRecord.source_id)
            ).all()
            metas = {source.source_id: (source.display_metadata or {}) for source, _ in rows}
            labels = {sid: m.get("doc_type") for sid, m in metas.items()}
        # chưa có nhãn, hoặc nhãn máy gán theo luật cũ (P2-2): phân loại lại; nhãn người dùng đã sửa thì giữ
        missing = [sid for sid, m in metas.items()
                   if not m.get("doc_type") or (m.get("doc_type_by") != "user" and m.get("doc_type_v") != DOC_TYPE_VERSION)]
        if missing:
            labels.update(self._label_unlabelled(missing))
        return [{"source_id": source.source_id, "source_name": source.source_name,
                 "chunk_count": int(count), "status": source.status,
                 "doc_type": labels.get(source.source_id)} for source, count in rows]

    def _label_unlabelled(self, source_ids: list[str]) -> dict[str, str]:
        """Tài liệu nạp trước đợt 3 chưa có nhãn: phân loại từ 3 đoạn đầu rồi lưu (một lần)."""
        out: dict[str, str] = {}
        with self.session_factory.begin() as db:
            for source in db.scalars(select(KnowledgeSourceRecord).where(KnowledgeSourceRecord.source_id.in_(source_ids))):
                text = "\n".join(db.scalars(select(KnowledgeChunkRecord.content).where(
                    KnowledgeChunkRecord.source_id == source.source_id
                ).order_by(KnowledgeChunkRecord.chunk_index).limit(3)).all())
                if not text:
                    continue
                out[source.source_id] = classify_document(source.source_name, text)
                source.display_metadata = {**(source.display_metadata or {}), "doc_type": out[source.source_id], "doc_type_by": "auto", "doc_type_v": DOC_TYPE_VERSION}
        return out

    def set_doc_type(self, source_id: str, doc_type: str) -> dict[str, Any]:
        """Người dùng sửa nhãn loại tài liệu. Chỉ người tải lên được sửa."""
        if doc_type not in DOC_TYPES:
            raise ValueError("doc_type is invalid")
        with self.session_factory.begin() as db:
            source = db.get(KnowledgeSourceRecord, source_id)
            if source is None or source.owner_user_id != self.owner_user_id:
                raise LookupError(source_id)
            source.display_metadata = {**(source.display_metadata or {}), "doc_type": doc_type, "doc_type_by": "user"}
        return {"source_id": source_id, "doc_type": doc_type, "doc_type_by": "user"}

    def source(self, source_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            source = db.scalar(select(KnowledgeSourceRecord).where(
                KnowledgeSourceRecord.source_id == source_id,
                *self._read_filters(),
            ))
            if source is None:
                return None
            chunks = db.scalars(select(KnowledgeChunkRecord).where(
                KnowledgeChunkRecord.source_id == source_id
            ).order_by(KnowledgeChunkRecord.chunk_index)).all()
            return {"source_id": source_id, "source_name": source.source_name,
                    "status": source.status,
                    "provenance": dict(source.display_metadata or {}),
                    "metadata": dict(source.display_metadata or {}),
                    "chunks": [self._chunk(row).__dict__ for row in chunks]}

    def chunk(self, chunk_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.scalar(
                select(KnowledgeChunkRecord)
                .join(KnowledgeSourceRecord)
                .where(
                    KnowledgeChunkRecord.chunk_id == chunk_id,
                    *self._read_filters(),
                )
            )
            return None if row is None else self._chunk(row).__dict__.copy()

    def snapshot_id(self) -> str:
        chunks = self.chunks()
        payload = "\n".join(
            f"{c.chunk_id}\0{c.source_id}\0{c.source_name}\0{c.index}\0{c.text}"
            for c in sorted(chunks, key=lambda item: item.chunk_id)
        )
        return "corpus_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def clear(self) -> None:
        with self.session_factory.begin() as db:
            # chỉ xóa tài liệu cá nhân; tài liệu đã nộp vào tổ chức thuộc về tổ chức
            source_ids = select(KnowledgeSourceRecord.source_id).where(
                KnowledgeSourceRecord.owner_user_id == self.owner_user_id,
                KnowledgeSourceRecord.space_id.is_(None),
            )
            db.execute(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.source_id.in_(source_ids)))

    @staticmethod
    def _chunk(row: KnowledgeChunkRecord) -> SourceChunk:
        return SourceChunk(
            chunk_id=row.chunk_id,
            source_id=row.source_id,
            source_name=row.source.source_name,
            text=row.content or "",
            index=row.chunk_index,
            provenance=dict(row.provenance or {}),
        )


class PostgresRunStore:
    """Run persistence that cannot read or overwrite another owner's runs."""

    _FIELDS = (
        "run_id", "created_at", "condition", "implementation_profile", "provider", "model",
        "query", "conversation_context", "status", "answer", "source_snapshot_id", "config_hash",
        "tasks", "task_results", "metrics", "events", "effective_config", "scoring_versions",
        "planning_retrieval_scoring_version", "retrieval_scoring_version", "domain_ranking_version", "retrieval",
    )

    def __init__(self, session_factory: sessionmaker[Session], owner_user_id: str,
                 conversation_id: str | None = None, space_id: str | None = None) -> None:
        self.session_factory = session_factory
        self.owner_user_id = owner_user_id
        self.conversation_id = conversation_id
        self.space_id = space_id

    def _scope(self) -> list[Any]:
        """Lượt chạy của chính người dùng, đúng phạm vi (cá nhân hoặc một không gian tổ chức)."""
        space = RunRecord.space_id.is_(None) if self.space_id is None else RunRecord.space_id == self.space_id
        return [RunRecord.owner_user_id == self.owner_user_id, space]

    def save(self, run: dict[str, Any]) -> None:
        created_at = _parse_iso(run.get("created_at"))
        with self.session_factory.begin() as db:
            record = db.get(RunRecord, run["run_id"])
            if record is not None and (record.owner_user_id != self.owner_user_id or record.space_id != self.space_id):
                raise PermissionError("run belongs to another owner or scope")
            values: dict[str, Any] = {
                field: run[field] for field in self._FIELDS if field in run
            }
            values.update(
                owner_user_id=self.owner_user_id,
                conversation_id=self.conversation_id,
                space_id=self.space_id,
                created_at=created_at,
                extra_data={
                    **run,
                    **({"conversation_id": self.conversation_id} if self.conversation_id else {}),
                },
            )
            if record is None:
                for field, default in {
                    "tasks": [], "task_results": [], "metrics": {}, "events": [],
                    "effective_config": {}, "scoring_versions": {}, "retrieval": {},
                }.items():
                    values.setdefault(field, default)
                record = RunRecord(**values)
                db.add(record)
            else:
                for field, value in values.items():
                    setattr(record, field, value)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.scalar(select(RunRecord).where(RunRecord.run_id == run_id, *self._scope()))
            if row is None:
                return None
            data = dict(row.extra_data)
            if self.space_id is not None and not (
                referenced_source_ids(data) <= visible_source_ids(db, self.owner_user_id, self.space_id)
            ):
                return redact_run(data)  # mất quyền với tài liệu gốc thì câu trả lời cũ bị ẩn
            return data

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.scalars(select(RunRecord).where(*self._scope())
                              .order_by(RunRecord.created_at.desc(), RunRecord.run_id.desc()).limit(limit)).all()
            return [{key: row.extra_data.get(key) for key in
                     ("run_id", "created_at", "condition", "query", "status", "lifecycle_status", "metrics")} for row in rows]

    # ---- Bản gọn cho trang Tổng quan: cùng kết quả với list()/get() nhưng không tải các cột JSON lớn của từng lượt.
    def list_light(self, limit: int = 30) -> list[dict[str, Any]]:
        """Như list(), nhưng đọc các cột đã lưu sẵn khi ghi (save() ghi cùng giá trị vào cột và extra_data); chỉ created_at
        (chuỗi gốc) và lifecycle_status (không có cột riêng) lấy từ extra_data. Nhanh hơn ~3-4 lần với vài trăm lượt."""
        with self.session_factory() as db:
            rows = db.execute(select(
                RunRecord.run_id, RunRecord.extra_data["created_at"], RunRecord.condition, RunRecord.query,
                RunRecord.status, RunRecord.extra_data["lifecycle_status"], RunRecord.metrics,
            ).where(*self._scope())
             .order_by(RunRecord.created_at.desc(), RunRecord.run_id.desc()).limit(limit)).all()
            keys = ("run_id", "created_at", "condition", "query", "status", "lifecycle_status", "metrics")
            return [dict(zip(keys, row)) for row in rows]

    def recent_citations(self, limit: int = 120) -> list[str]:
        """Mọi mã đoạn được trích dẫn trong `limit` lượt gần nhất, gom bằng MỘT truy vấn
        (thay cho gọi get() từng lượt rồi đọc task_results[*].citations[*])."""
        path = func.jsonb_path_query_array(cast(RunRecord.extra_data, JSONB), cast(literal("$.task_results[*].citations[*]"), JSONPATH))
        with self.session_factory() as db:
            arrays = db.execute(select(path).where(*self._scope())
                                .order_by(RunRecord.created_at.desc(), RunRecord.run_id.desc()).limit(limit)).scalars().all()
        return [str(c) for arr in arrays for c in (arr or [])]


class PostgresConversationStore:
    """Owner-scoped conversation and ordered message persistence."""

    def __init__(self, session_factory: sessionmaker[Session], owner_user_id: str,
                 space_id: str | None = None) -> None:
        self.session_factory = session_factory
        self.owner_user_id = owner_user_id
        self.space_id = space_id

    def _scope(self) -> list[Any]:
        space = (ConversationRecord.space_id.is_(None) if self.space_id is None
                 else ConversationRecord.space_id == self.space_id)
        return [ConversationRecord.owner_user_id == self.owner_user_id, space]

    def create(self, title: str = "New conversation") -> dict[str, Any]:
        title = str(title or "New conversation").strip()[:120] or "New conversation"
        now = _now()
        record = ConversationRecord(
            conversation_id=f"conv_{uuid4().hex[:16]}", owner_user_id=self.owner_user_id,
            space_id=self.space_id, title=title, created_at=now, updated_at=now,
        )
        with self.session_factory.begin() as db:
            db.add(record)
            db.flush()
        return self.get(record.conversation_id) or {}

    def add_message(self, conversation_id: str, role: str, content: str,
                    run_id: str | None = None) -> dict[str, Any]:
        role = str(role).upper()
        content = str(content or "").strip()
        if role not in {"USER", "ASSISTANT"} or not content:
            raise ValueError("message role or content is invalid")
        now = _now()
        with self.session_factory.begin() as db:
            conversation = db.scalar(select(ConversationRecord).where(
                ConversationRecord.conversation_id == conversation_id, *self._scope(),
            ).with_for_update())
            if conversation is None:
                raise LookupError("conversation not found")
            current_sequence = db.scalar(select(func.max(
                ConversationMessageRecord.sequence_number
            )).where(ConversationMessageRecord.conversation_id == conversation_id))
            next_sequence = int(current_sequence if current_sequence is not None else -1) + 1
            message = ConversationMessageRecord(
                message_id=f"msg_{uuid4().hex[:16]}", conversation_id=conversation_id,
                sequence_number=next_sequence, role=role, content=content, run_id=run_id,
                created_at=now,
            )
            conversation.updated_at = now
            db.add(message)
            db.flush()
            message_id = message.message_id
        return {"message_id": message_id, "conversation_id": conversation_id,
                "sequence_number": next_sequence, "role": role, "content": content,
                "created_at": _iso(now), "run_id": run_id}

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            conversation = db.scalar(select(ConversationRecord).where(
                ConversationRecord.conversation_id == conversation_id, *self._scope(),
                ConversationRecord.hidden_at.is_(None),
            ))
            if conversation is None:
                return None
            messages = db.scalars(select(ConversationMessageRecord).where(
                ConversationMessageRecord.conversation_id == conversation_id
            ).order_by(ConversationMessageRecord.sequence_number)).all()
            hidden = self._hidden_runs(db, [row.run_id for row in messages if row.run_id])
            return {
                "conversation_id": conversation.conversation_id,
                "title": conversation.title,
                "pinned": conversation.pinned_at is not None,
                "created_at": _iso(conversation.created_at),
                "updated_at": _iso(conversation.updated_at),
                "messages": [{
                    "message_id": row.message_id,
                    "conversation_id": row.conversation_id,
                    "sequence_number": row.sequence_number,
                    "role": row.role,
                    "content": REDACTED_ANSWER if row.run_id in hidden else row.content,
                    "created_at": _iso(row.created_at),
                    "run_id": row.run_id,
                } for row in messages],
            }

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.scalars(select(ConversationRecord).where(*self._scope(), ConversationRecord.hidden_at.is_(None)).order_by(
                ConversationRecord.pinned_at.is_(None), ConversationRecord.pinned_at.desc(), ConversationRecord.updated_at.desc(),
            ).limit(max(1, min(limit, 200)))).all()
            return [{"conversation_id": row.conversation_id, "title": row.title, "pinned": row.pinned_at is not None,
                     "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at)} for row in rows]

    def update(self, conversation_id: str, *, title: str | None = None, pinned: bool | None = None,
               hidden: bool | None = None) -> dict[str, Any]:
        """Đổi tên, ghim/bỏ ghim, xóa (ẩn) hoặc khôi phục. Không đổi updated_at để thứ tự theo hoạt động giữ nguyên."""
        values: dict[str, Any] = {}
        if title is not None:
            name = str(title).strip()
            if not name or len(name) > 120:
                raise ValueError("Tên cuộc trò chuyện cần 1–120 ký tự.")
            values["title"] = name
        now = _now()
        if pinned is not None:
            values["pinned_at"] = now if pinned else None
        if hidden is not None:
            values["hidden_at"] = now if hidden else None
        with self.session_factory.begin() as db:
            row = db.scalar(select(ConversationRecord).where(
                ConversationRecord.conversation_id == conversation_id, *self._scope()))
            if row is None:
                raise LookupError("conversation not found")
            if values:
                # gán updated_at = chính nó để ORM không tự cập nhật thời điểm (onupdate)
                db.execute(sa_update(ConversationRecord).where(ConversationRecord.conversation_id == conversation_id)
                           .values(**values, updated_at=ConversationRecord.updated_at))
            db.refresh(row)
            return {"conversation_id": row.conversation_id, "title": row.title, "pinned": row.pinned_at is not None,
                    "hidden": row.hidden_at is not None, "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at)}

    def _hidden_runs(self, db: Session, run_ids: list[str]) -> set[str]:
        """Câu trả lời trong hội thoại tổ chức bị ẩn khi người xem không còn quyền với mọi tài liệu nó dùng."""
        if self.space_id is None or not run_ids:
            return set()
        visible = visible_source_ids(db, self.owner_user_id, self.space_id)
        rows = db.execute(select(RunRecord.run_id, RunRecord.extra_data).where(RunRecord.run_id.in_(run_ids))).all()
        return {run_id for run_id, data in rows if not referenced_source_ids(data or {}) <= visible}
