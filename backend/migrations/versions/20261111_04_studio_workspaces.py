"""Studio workspaces: group a user's sources and conversations into named workspaces.

Chỉ thêm bảng mới; không đổi bảng gốc của CAP1. Tài liệu và cuộc trò chuyện chưa gán
được gán vào không gian đầu tiên của người dùng khi họ mở Studio lần đầu.

Revision ID: 20261111_04
Revises: 20261010_03
Create Date: 2026-11-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261111_04"
down_revision = "20261010_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_workspaces",
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_index("ix_studio_workspaces_owner", "studio_workspaces", ["owner_user_id"])
    op.create_table(
        "studio_workspace_items",
        sa.Column("workspace_id", sa.String(length=64), sa.ForeignKey("studio_workspaces.workspace_id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),  # source | conversation
        sa.Column("item_id", sa.String(length=160), nullable=False),
        sa.PrimaryKeyConstraint("item_type", "item_id"),  # mỗi tài liệu/cuộc trò chuyện thuộc đúng một không gian
    )
    op.create_index("ix_studio_workspace_items_ws", "studio_workspace_items", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_studio_workspace_items_ws", table_name="studio_workspace_items")
    op.drop_table("studio_workspace_items")
    op.drop_index("ix_studio_workspaces_owner", table_name="studio_workspaces")
    op.drop_table("studio_workspaces")
