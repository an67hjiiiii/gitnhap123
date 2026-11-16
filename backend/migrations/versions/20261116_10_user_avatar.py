"""Ảnh đại diện người dùng: users.avatar.

NULL = hiện chữ cái đầu như cũ. Giá trị "preset:<mã>" (ảnh mẫu vẽ sẵn ở giao diện) hoặc data URL ảnh đã thu nhỏ 256px.

Revision ID: 20261116_10
Revises: 20261116_09
Create Date: 2026-11-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261116_10"
down_revision = "20261116_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar")
