"""Phản hồi về câu trả lời (thích/không thích) và nhật ký hoạt động của người dùng.

Chỉ thêm bảng mới; không đổi bảng gốc của CAP1 hay lượt chạy nghiên cứu.

Revision ID: 20261113_06
Revises: 20261113_05
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261113_06"
down_revision = "20261113_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_feedback",
        sa.Column("owner_user_id", sa.String(length=64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(length=80), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),  # 1 = hữu ích, -1 = chưa đúng
        sa.Column("note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("owner_user_id", "run_id"),
        sa.CheckConstraint("rating IN (-1, 1)", name="ck_studio_feedback_rating"),
    )
    op.create_table(
        "studio_activity",
        sa.Column("activity_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("activity_id"),
    )
    op.create_index("ix_studio_activity_owner_time", "studio_activity", ["owner_user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_studio_activity_owner_time", table_name="studio_activity")
    op.drop_table("studio_activity")
    op.drop_table("studio_feedback")
