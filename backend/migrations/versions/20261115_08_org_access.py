"""Không gian tổ chức và phân quyền theo cấp bậc (Đợt 1: chỉ nền dữ liệu).

Thêm bảng mới (không gian, phòng ban, thành viên, lời mời, chia sẻ tài liệu, thông báo) và cột mới
cho knowledge_sources (space_id, department_id, classification) và conversations (space_id).
Dữ liệu cũ giữ nguyên hành vi: space_id NULL = cá nhân, classification mặc định PRIVATE.
Không đổi lượt chạy nghiên cứu hay điều kiện A/B/C.

Revision ID: 20261115_08
Revises: 20261114_07
Create Date: 2026-11-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261115_08"
down_revision = "20261114_07"
branch_labels = None
depends_on = None

LEVELS = "('STAFF', 'MANAGER', 'EXECUTIVE')"
CLASSIFICATIONS = "('PRIVATE', 'COMPANY', 'DEPARTMENT', 'RESTRICTED', 'SECRET')"


def _ts(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "org_spaces",
        sa.Column("space_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(64), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        _ts(),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_org_spaces_name_nonempty"),
    )
    op.create_table(
        "org_departments",
        sa.Column("department_id", sa.String(64), primary_key=True),
        sa.Column("space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        _ts(),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_org_departments_name_nonempty"),
        sa.UniqueConstraint("space_id", "name", name="uq_org_departments_space_name"),
        sa.UniqueConstraint("space_id", "department_id", name="uq_org_departments_space_id"),
    )
    op.create_table(
        "org_members",
        sa.Column("space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("department_id", sa.String(64), nullable=True),
        sa.Column("level", sa.String(16), nullable=False, server_default="STAFF"),
        sa.Column("is_owner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        _ts("joined_at"),
        sa.CheckConstraint(f"level IN {LEVELS}", name="ck_org_members_level"),
        sa.CheckConstraint("status IN ('PENDING', 'ACTIVE')", name="ck_org_members_status"),
        sa.CheckConstraint(
            "status = 'PENDING' OR level = 'EXECUTIVE' OR department_id IS NOT NULL",
            name="ck_org_members_department_required",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "department_id"], ["org_departments.space_id", "org_departments.department_id"],
            name="fk_org_members_department_same_space", ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_org_members_user", "org_members", ["user_id"])
    op.create_table(
        "org_invites",
        sa.Column("invite_id", sa.String(64), primary_key=True),
        sa.Column("space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("invitee_user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("department_id", sa.String(64), nullable=True),
        sa.Column("level", sa.String(16), nullable=False, server_default="STAFF"),
        sa.Column("created_by", sa.String(64), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _ts(),
        sa.CheckConstraint("kind IN ('USER', 'LINK', 'CODE')", name="ck_org_invites_kind"),
        sa.CheckConstraint(f"level IN {LEVELS}", name="ck_org_invites_level"),
        sa.CheckConstraint(
            "(kind = 'USER' AND invitee_user_id IS NOT NULL AND token_hash IS NULL)"
            " OR (kind IN ('LINK', 'CODE') AND token_hash IS NOT NULL AND invitee_user_id IS NULL)",
            name="ck_org_invites_target",
        ),
        sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_org_invites_max_uses"),
        sa.CheckConstraint("use_count >= 0", name="ck_org_invites_use_count"),
        sa.UniqueConstraint("token_hash", name="uq_org_invites_token_hash"),
        sa.ForeignKeyConstraint(
            ["space_id", "department_id"], ["org_departments.space_id", "org_departments.department_id"],
            name="fk_org_invites_department_same_space", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_org_invites_space", "org_invites", ["space_id"])
    op.create_index("ix_org_invites_invitee", "org_invites", ["invitee_user_id"])

    # cột mới cho tài liệu: mặc định PRIVATE nên mọi tài liệu cũ vẫn chỉ chủ xem được
    op.add_column("knowledge_sources", sa.Column(
        "space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="RESTRICT"), nullable=True))
    op.add_column("knowledge_sources", sa.Column("department_id", sa.String(64), nullable=True))
    op.add_column("knowledge_sources", sa.Column(
        "classification", sa.String(16), nullable=False, server_default="PRIVATE"))
    op.create_check_constraint(
        "ck_knowledge_sources_classification", "knowledge_sources", f"classification IN {CLASSIFICATIONS}")
    op.create_check_constraint(
        "ck_knowledge_sources_personal_private", "knowledge_sources",
        "space_id IS NOT NULL OR (classification = 'PRIVATE' AND department_id IS NULL)")
    op.create_check_constraint(
        "ck_knowledge_sources_department_required", "knowledge_sources",
        "classification NOT IN ('DEPARTMENT', 'RESTRICTED') OR department_id IS NOT NULL")
    op.create_foreign_key(
        "fk_knowledge_sources_department_same_space", "knowledge_sources", "org_departments",
        ["space_id", "department_id"], ["space_id", "department_id"], ondelete="RESTRICT")
    op.create_index("ix_knowledge_sources_space_classification", "knowledge_sources", ["space_id", "classification"])

    op.add_column("conversations", sa.Column(
        "space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="RESTRICT"), nullable=True))
    op.create_index("ix_conversations_space", "conversations", ["space_id"])

    op.create_table(
        "org_source_shares",
        sa.Column("share_id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(128), sa.ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True),
        sa.Column("target_department_id", sa.String(64), sa.ForeignKey("org_departments.department_id", ondelete="CASCADE"), nullable=True),
        sa.Column("shared_by", sa.String(64), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        _ts(),
        sa.CheckConstraint("(target_user_id IS NULL) <> (target_department_id IS NULL)", name="ck_org_source_shares_one_target"),
    )
    op.create_index("uq_org_source_shares_user", "org_source_shares", ["source_id", "target_user_id"],
                    unique=True, postgresql_where=sa.text("target_user_id IS NOT NULL"))
    op.create_index("uq_org_source_shares_department", "org_source_shares", ["source_id", "target_department_id"],
                    unique=True, postgresql_where=sa.text("target_department_id IS NOT NULL"))
    op.create_index("ix_org_source_shares_target_user", "org_source_shares", ["target_user_id"])
    op.create_index("ix_org_source_shares_target_department", "org_source_shares", ["target_department_id"])

    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        _ts(),
    )
    op.create_index("ix_notifications_user_unread", "notifications", ["user_id", "read_at", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_table("notifications")
    for name in ("ix_org_source_shares_target_department", "ix_org_source_shares_target_user",
                 "uq_org_source_shares_department", "uq_org_source_shares_user"):
        op.drop_index(name, table_name="org_source_shares")
    op.drop_table("org_source_shares")

    op.drop_index("ix_conversations_space", table_name="conversations")
    op.drop_column("conversations", "space_id")

    op.drop_index("ix_knowledge_sources_space_classification", table_name="knowledge_sources")
    op.drop_constraint("fk_knowledge_sources_department_same_space", "knowledge_sources", type_="foreignkey")
    for name in ("ck_knowledge_sources_department_required", "ck_knowledge_sources_personal_private",
                 "ck_knowledge_sources_classification"):
        op.drop_constraint(name, "knowledge_sources", type_="check")
    op.drop_column("knowledge_sources", "classification")
    op.drop_column("knowledge_sources", "department_id")
    op.drop_column("knowledge_sources", "space_id")

    op.drop_index("ix_org_invites_invitee", table_name="org_invites")
    op.drop_index("ix_org_invites_space", table_name="org_invites")
    op.drop_table("org_invites")
    op.drop_index("ix_org_members_user", table_name="org_members")
    op.drop_table("org_members")
    op.drop_table("org_departments")
    op.drop_table("org_spaces")
