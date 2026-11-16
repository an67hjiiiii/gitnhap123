"""Phạm vi của lượt chạy (Đợt 4 phân quyền): runs.space_id.

NULL = lượt chạy cá nhân (mọi lượt cũ). Khác NULL = lượt chạy trong không gian tổ chức; chỉ hiện trong đúng không gian đó
và trang quản trị không thấy câu hỏi của lượt này. Không đổi điều kiện A/B/C hay số liệu đã lưu.

Revision ID: 20261116_09
Revises: 20261115_08
Create Date: 2026-11-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261116_09"
down_revision = "20261115_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column(
        "space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="RESTRICT"), nullable=True))
    op.create_index("ix_runs_space", "runs", ["space_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_space", table_name="runs")
    op.drop_column("runs", "space_id")
