"""Học từ người dùng (Đợt 8, P1-5): bảng routing_examples. Chỉ thêm bảng, không đổi bảng cũ.

Revision ID: 20261120_17
Revises: 20261119_16
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261120_17"
down_revision = "20261119_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routing_examples",
        sa.Column("example_id", sa.String(64), primary_key=True),
        sa.Column("owner_user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(64), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("agent", sa.String(32), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="clarify"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_routing_examples_owner_space", "routing_examples", ["owner_user_id", "space_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_routing_examples_owner_space", table_name="routing_examples")
    op.drop_table("routing_examples")
