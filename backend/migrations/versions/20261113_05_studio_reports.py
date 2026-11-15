"""Studio reports: lưu kết quả các chức năng phân tích (truy vết yêu cầu, gói thiết kế, rà soát...).

Chỉ thêm bảng mới; không đổi bảng gốc của CAP1 hay lượt chạy nghiên cứu.

Revision ID: 20261113_05
Revises: 20261111_04
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261113_05"
down_revision = "20261111_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_reports",
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), sa.ForeignKey("studio_workspaces.workspace_id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("report_id"),
    )
    op.create_index("ix_studio_reports_owner_kind", "studio_reports", ["owner_user_id", "kind", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_studio_reports_owner_kind", table_name="studio_reports")
    op.drop_table("studio_reports")
