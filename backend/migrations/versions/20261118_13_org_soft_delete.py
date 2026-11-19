"""Xóa tổ chức (xóa mềm): org_spaces.deleted_at.

Xóa tổ chức gỡ mọi thành viên, lời mời, đơn vị và tài liệu tổ chức; bản ghi tổ chức được giữ (deleted_at) để
lượt chạy AI và hội thoại cũ vẫn hợp lệ, không ai còn truy cập được. NULL = đang hoạt động (mọi tổ chức cũ).

Revision ID: 20261118_13
Revises: 20261117_12
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261118_13"
down_revision = "20261117_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("org_spaces", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("org_spaces", "deleted_at")
