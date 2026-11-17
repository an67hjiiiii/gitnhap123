"""Minimal organization read access."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261117_02"
down_revision = "20261117_01"
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

def downgrade() -> None:
    for name in ("ix_org_source_shares_target_department", "ix_org_source_shares_target_user",
                 "uq_org_source_shares_department", "uq_org_source_shares_user"):
        op.drop_index(name, table_name="org_source_shares")
    op.drop_table("org_source_shares")


    op.drop_index("ix_knowledge_sources_space_classification", table_name="knowledge_sources")
    op.drop_constraint("fk_knowledge_sources_department_same_space", "knowledge_sources", type_="foreignkey")
    for name in ("ck_knowledge_sources_department_required", "ck_knowledge_sources_personal_private",
                 "ck_knowledge_sources_classification"):
        op.drop_constraint(name, "knowledge_sources", type_="check")
    op.drop_column("knowledge_sources", "classification")
    op.drop_column("knowledge_sources", "department_id")
    op.drop_column("knowledge_sources", "space_id")

    op.drop_index("ix_org_members_user", table_name="org_members")
    op.drop_table("org_members")
    op.drop_table("org_departments")
    op.drop_table("org_spaces")
