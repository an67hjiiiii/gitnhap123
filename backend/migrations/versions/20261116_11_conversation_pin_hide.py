"""Ghim và xóa (ẩn) cuộc trò chuyện: conversations.pinned_at, conversations.hidden_at.

Xóa chỉ đặt hidden_at: cuộc trò chuyện biến khỏi danh sách nhưng tin nhắn và lượt chạy vẫn giữ nguyên
(dữ liệu nghiên cứu không bị mất, hoàn tác được). NULL = chưa ghim / đang hiện, như mọi bản ghi cũ.

Revision ID: 20261116_11
Revises: 20261116_10
Create Date: 2026-11-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261116_11"
down_revision = "20261116_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "hidden_at")
    op.drop_column("conversations", "pinned_at")
