from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.storage.postgres.base import Base

# Mức mật tài liệu. Thang từ thấp đến cao: COMPANY < DEPARTMENT < RESTRICTED < SECRET; PRIVATE nằm ngoài thang.
CLASSIFICATIONS = ("PRIVATE", "COMPANY", "DEPARTMENT", "RESTRICTED", "SECRET")
# Cấp bậc trong một không gian tổ chức (khác vai trò hệ thống USER/ADMIN).
MEMBER_LEVELS = ("STAFF", "MANAGER", "EXECUTIVE")
# mẫu tổ chức chỉ đổi tên gọi trên giao diện (Trưởng khoa thay Trưởng phòng...); luật quyền không đọc cột này
ORG_PRESETS = ("business", "school", "hospital", "government", "team", "custom")


class UserRecord(Base):
    """Persisted identity fields for the PostgreSQL foundation."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR username IS NOT NULL",
            name="ck_users_login_identity",
        ),
        CheckConstraint("role IN ('USER', 'ADMIN')", name="ck_users_role"),
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
    )

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="USER")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ảnh đại diện: "preset:<mã>" (ảnh mẫu vẽ sẵn ở giao diện) hoặc data URL ảnh 256px; NULL = chữ cái đầu
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)

    knowledge_sources: Mapped[list[KnowledgeSourceRecord]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    conversations: Mapped[list[ConversationRecord]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs: Mapped[list[RunRecord]] = relationship(
        back_populates="owner",
        foreign_keys="RunRecord.owner_user_id",
    )
    sessions: Mapped[list[SessionRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class SessionRecord(Base):
    """Hashed, expiring authentication sessions persisted by PostgreSQL."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_expiry", "user_id", "expires_at"),
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[UserRecord] = relationship(back_populates="sessions")


class KnowledgeSourceRecord(Base):
    """Private source metadata; ownership is enforced by the user foreign key."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PROCESSING', 'READY', 'FAILED')",
            name="ck_knowledge_sources_lifecycle",
        ),
        Index("ix_knowledge_sources_owner_status", "owner_user_id", "status"),
        CheckConstraint(
            f"classification IN {CLASSIFICATIONS!r}",
            name="ck_knowledge_sources_classification",
        ),
        # tài liệu cá nhân (không thuộc không gian tổ chức) luôn là Riêng tư và không có phòng ban
        CheckConstraint(
            "space_id IS NOT NULL OR (classification = 'PRIVATE' AND department_id IS NULL)",
            name="ck_knowledge_sources_personal_private",
        ),
        CheckConstraint(
            "classification NOT IN ('DEPARTMENT', 'RESTRICTED') OR department_id IS NOT NULL",
            name="ck_knowledge_sources_department_required",
        ),
        ForeignKeyConstraint(
            ["space_id", "department_id"],
            ["org_departments.space_id", "org_departments.department_id"],
            name="fk_knowledge_sources_department_same_space",
            ondelete="RESTRICT",
        ),
        Index("ix_knowledge_sources_space_classification", "space_id", "classification"),
    )

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_name: Mapped[str] = mapped_column(String(512), nullable=False)
    # NULL = tài liệu cá nhân, hành vi như trước khi có không gian tổ chức
    space_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("org_spaces.space_id", ondelete="RESTRICT"), nullable=True
    )
    department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PRIVATE", server_default="PRIVATE"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PROCESSING", server_default="PROCESSING"
    )
    file_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped[UserRecord] = relationship(back_populates="knowledge_sources")
    chunks: Mapped[list[KnowledgeChunkRecord]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="KnowledgeChunkRecord.chunk_index",
    )


class KnowledgeChunkRecord(Base):
    """Authoritative chunk text and provenance used to rebuild retrieval data."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_index"),
        CheckConstraint(
            "content IS NOT NULL OR content_ref IS NOT NULL",
            name="ck_knowledge_chunks_content_reference",
        ),
        UniqueConstraint(
            "source_id", "chunk_index", name="uq_knowledge_chunks_source_index"
        ),
    )

    chunk_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    indexing_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped[KnowledgeSourceRecord] = relationship(back_populates="chunks")


class ConversationRecord(Base):
    """Owner-scoped conversation header; messages remain ordered child rows."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(title)) > 0", name="ck_conversations_title_nonempty"
        ),
        UniqueConstraint(
            "conversation_id",
            "owner_user_id",
            name="uq_conversations_id_owner",
        ),
        ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.user_id"],
            name="fk_conversations_owner_user",
            ondelete="CASCADE",
        ),
        Index("ix_conversations_owner_updated", "owner_user_id", "updated_at"),
        Index("ix_conversations_space", "space_id"),
    )

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL = hội thoại cá nhân; khác NULL = thuộc không gian tổ chức (ở lại khi thành viên rời đi)
    space_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("org_spaces.space_id", ondelete="RESTRICT"), nullable=True
    )
    schema_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="conversation-v1",
        server_default="conversation-v1",
    )
    title: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="New conversation",
        server_default="New conversation",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ghim lên đầu danh sách; xóa = ẩn (tin nhắn, lượt chạy vẫn giữ để phân tích nghiên cứu)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[UserRecord] = relationship(back_populates="conversations")
    messages: Mapped[list[ConversationMessageRecord]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ConversationMessageRecord.sequence_number",
    )
    runs: Mapped[list[RunRecord]] = relationship(
        back_populates="conversation",
        foreign_keys="RunRecord.conversation_id",
    )


class RunRecord(Base):
    """Structured persistence shape for one processing/research run."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "conversation_id IS NULL OR owner_user_id IS NOT NULL",
            name="ck_runs_conversation_requires_owner",
        ),
        UniqueConstraint(
            "conversation_id", "run_id", name="uq_runs_conversation_id"
        ),
        ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.user_id"],
            name="fk_runs_owner_user",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "owner_user_id"],
            ["conversations.conversation_id", "conversations.owner_user_id"],
            name="fk_runs_conversation_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_runs_owner_created_at", "owner_user_id", "created_at"),
        Index("ix_runs_space", "space_id"),
    )

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # phạm vi lúc chạy: NULL = cá nhân; khác NULL = không gian tổ chức (câu trả lời có thể chứa nội dung tổ chức)
    space_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("org_spaces.space_id", ondelete="RESTRICT"), nullable=True
    )
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    condition: Mapped[str | None] = mapped_column(String(16), nullable=True)
    implementation_profile: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_context: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_snapshot_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    task_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    effective_config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    scoring_versions: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    planning_retrieval_scoring_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    retrieval_scoring_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    domain_ranking_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    retrieval: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    owner: Mapped[UserRecord | None] = relationship(
        back_populates="runs", foreign_keys=[owner_user_id]
    )
    conversation: Mapped[ConversationRecord | None] = relationship(
        back_populates="runs", foreign_keys=[conversation_id]
    )


class ConversationMessageRecord(Base):
    """Ordered user/assistant turn with an optional same-thread run link."""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "sequence_number >= 0", name="ck_conversation_messages_sequence"
        ),
        CheckConstraint(
            "role IN ('USER', 'ASSISTANT')", name="ck_conversation_messages_role"
        ),
        CheckConstraint(
            "length(btrim(content)) > 0", name="ck_conversation_messages_content"
        ),
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_conversation_messages_order",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.conversation_id"],
            name="fk_conversation_messages_conversation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "run_id"],
            ["runs.conversation_id", "runs.run_id"],
            name="fk_conversation_messages_run_same_conversation",
            ondelete="RESTRICT",
        ),
    )

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    conversation: Mapped[ConversationRecord] = relationship(back_populates="messages")


class OrgSpaceRecord(Base):
    """Không gian tổ chức (công ty, bộ phận); tài liệu và hội thoại trong đó thuộc về tổ chức."""

    __tablename__ = "org_spaces"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_org_spaces_name_nonempty"),
        CheckConstraint(f"preset IN {ORG_PRESETS!r}", name="ck_org_spaces_preset"),
    )

    space_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    preset: Mapped[str] = mapped_column(String(16), nullable=False, default="business", server_default="business")
    # lĩnh vực cho trợ lý AI (bộ tác tử ở app/research/registry.py); kiểm giá trị ở tầng API
    domain_pack: Mapped[str] = mapped_column(String(32), nullable=False, default="general", server_default="general")
    # xóa mềm: giữ bản ghi để lượt chạy AI và hội thoại cũ (dữ liệu nghiên cứu) vẫn trỏ được tới tổ chức
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # tên gọi tự đặt đè lên mẫu: org, unit, STAFF, MANAGER, EXECUTIVE (NULL = dùng nguyên mẫu)
    labels: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgDepartmentRecord(Base):
    """Phòng ban trong một không gian tổ chức."""

    __tablename__ = "org_departments"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_org_departments_name_nonempty"),
        UniqueConstraint("space_id", "name", name="uq_org_departments_space_name"),
        # đích của khóa ngoại kép (space_id, department_id): phòng ban phải cùng không gian
        UniqueConstraint("space_id", "department_id", name="uq_org_departments_space_id"),
    )

    department_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgMemberRecord(Base):
    """Thành viên của không gian: phòng ban, cấp bậc, cờ chủ không gian, trạng thái."""

    __tablename__ = "org_members"
    __table_args__ = (
        CheckConstraint(f"level IN {MEMBER_LEVELS!r}", name="ck_org_members_level"),
        CheckConstraint("status IN ('PENDING', 'ACTIVE')", name="ck_org_members_status"),
        # Nhân viên và Trưởng phòng đang hoạt động phải thuộc một phòng; Ban giám đốc thì không bắt buộc
        CheckConstraint(
            "status = 'PENDING' OR level = 'EXECUTIVE' OR department_id IS NOT NULL",
            name="ck_org_members_department_required",
        ),
        ForeignKeyConstraint(
            ["space_id", "department_id"],
            ["org_departments.space_id", "org_departments.department_id"],
            name="fk_org_members_department_same_space",
            ondelete="RESTRICT",
        ),
        Index("ix_org_members_user", "user_id"),
    )

    space_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("org_spaces.space_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="STAFF", server_default="STAFF")
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgInviteRecord(Base):
    """Lời mời: theo tài khoản (gán sẵn cấp bậc) hoặc link/mã (người vào ở trạng thái chờ duyệt)."""

    __tablename__ = "org_invites"
    __table_args__ = (
        CheckConstraint("kind IN ('USER', 'LINK', 'CODE')", name="ck_org_invites_kind"),
        CheckConstraint(f"level IN {MEMBER_LEVELS!r}", name="ck_org_invites_level"),
        CheckConstraint(
            "(kind = 'USER' AND invitee_user_id IS NOT NULL AND token_hash IS NULL)"
            " OR (kind IN ('LINK', 'CODE') AND token_hash IS NOT NULL AND invitee_user_id IS NULL)",
            name="ck_org_invites_target",
        ),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_org_invites_max_uses"),
        CheckConstraint("use_count >= 0", name="ck_org_invites_use_count"),
        UniqueConstraint("token_hash", name="uq_org_invites_token_hash"),
        ForeignKeyConstraint(
            ["space_id", "department_id"],
            ["org_departments.space_id", "org_departments.department_id"],
            name="fk_org_invites_department_same_space",
            ondelete="CASCADE",
        ),
        Index("ix_org_invites_space", "space_id"),
        Index("ix_org_invites_invitee", "invitee_user_id"),
    )

    invite_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    invitee_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True
    )
    # chỉ lưu SHA-256 của link/mã, không lưu nguyên văn
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="STAFF", server_default="STAFF")
    created_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgSourceShareRecord(Base):
    """Chia sẻ trực tiếp một tài liệu cho một người hoặc một phòng ban."""

    __tablename__ = "org_source_shares"
    __table_args__ = (
        CheckConstraint(
            "(target_user_id IS NULL) <> (target_department_id IS NULL)",
            name="ck_org_source_shares_one_target",
        ),
        Index(
            "uq_org_source_shares_user", "source_id", "target_user_id", unique=True,
            postgresql_where=text("target_user_id IS NOT NULL"),
            sqlite_where=text("target_user_id IS NOT NULL"),
        ),
        Index(
            "uq_org_source_shares_department", "source_id", "target_department_id", unique=True,
            postgresql_where=text("target_department_id IS NOT NULL"),
            sqlite_where=text("target_department_id IS NOT NULL"),
        ),
        Index("ix_org_source_shares_target_user", "target_user_id"),
        Index("ix_org_source_shares_target_department", "target_department_id"),
    )

    share_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"), nullable=False
    )
    target_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True
    )
    target_department_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("org_departments.department_id", ondelete="CASCADE"), nullable=True
    )
    shared_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NotificationRecord(Base):
    """Thông báo trong ứng dụng (chuông): lời mời, yêu cầu tham gia, được chia sẻ tài liệu, đổi cấp bậc."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "read_at", "created_at"),
    )

    notification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    space_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgSecretAccessRecord(Base):
    """Nhật ký truy cập tài liệu mức Mật (đợt 9): ai mở hoặc hỏi AI dùng tới tài liệu nào, lúc nào. Không ghi nội dung."""

    __tablename__ = "org_secret_access"
    __table_args__ = (
        CheckConstraint("action IN ('VIEW', 'ASK')", name="ck_org_secret_access_action"),
        Index("ix_org_secret_access_space_time", "space_id", "created_at"),
    )

    access_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    space_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgRequestRecord(Base):
    """Đơn từ và duyệt theo cấp (đợt 10): đơn của một thành viên, chuyển tới Trưởng phòng hoặc Ban giám đốc duyệt."""

    __tablename__ = "org_requests"
    __table_args__ = (
        CheckConstraint("approver_level IN ('MANAGER', 'EXECUTIVE')", name="ck_org_requests_level"),
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN')", name="ck_org_requests_status"),
        CheckConstraint("approver_level = 'EXECUTIVE' OR department_id IS NOT NULL", name="ck_org_requests_department"),
        Index("ix_org_requests_space_status", "space_id", "status", "created_at"),
    )

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=False)
    requester_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    days: Mapped[float | None] = mapped_column(nullable=True)
    approver_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    check_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    history: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoutingExampleRecord(Base):
    """Học từ người dùng (Đợt 8, P1-5): câu hỏi và tác tử người dùng đã chọn (bấm nút hỏi lại, chọn lại tác tử).
    Theo từng người và từng không gian; chỉ ô chat sản phẩm dùng làm ví dụ cho bộ chọn tác tử."""

    __tablename__ = "routing_examples"
    __table_args__ = (Index("ix_routing_examples_owner_space", "owner_user_id", "space_id", "created_at"),)

    example_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    space_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="clarify")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
