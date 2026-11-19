"""Nhật ký truy cập tài liệu mức Mật (đợt 9): bảng org_secret_access. Chỉ thêm bảng, không đổi dữ liệu cũ.

Revision ID: 20261119_15
Revises: 20261118_14
Create Date: 2026-11-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261119_15"
down_revision = "20261118_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_secret_access",
        sa.Column("access_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(128), sa.ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("action IN ('VIEW', 'ASK')", name="ck_org_secret_access_action"),
    )
    op.create_index("ix_org_secret_access_space_time", "org_secret_access", ["space_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_org_secret_access_space_time", table_name="org_secret_access")
    op.drop_table("org_secret_access")
