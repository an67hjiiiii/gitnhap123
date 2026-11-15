"""Chấm mù nhiều người: đợt chấm (mục chấm giữ điều kiện ở phía máy chủ) và điểm của từng người chấm.

Chỉ thêm bảng mới; không đổi bảng gốc của CAP1 hay lượt chạy nghiên cứu.

Revision ID: 20261114_07
Revises: 20261113_06
Create Date: 2026-11-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261114_07"
down_revision = "20261113_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_rating_studies",
        sa.Column("study_id", sa.String(length=40), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=12), nullable=False, unique=True),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("failed", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_studio_rating_studies_owner", "studio_rating_studies", ["owner_user_id"])
    op.create_table(
        "studio_ratings",
        sa.Column("study_id", sa.String(length=40), sa.ForeignKey("studio_rating_studies.study_id", ondelete="CASCADE"), nullable=False),
        sa.Column("rater_user_id", sa.String(length=64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.String(length=40), nullable=False),
        sa.Column("scores", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("study_id", "rater_user_id", "item_id"),
    )


def downgrade() -> None:
    op.drop_table("studio_ratings")
    op.drop_index("ix_studio_rating_studies_owner", table_name="studio_rating_studies")
    op.drop_table("studio_rating_studies")
