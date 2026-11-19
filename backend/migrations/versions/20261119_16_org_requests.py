"""Đơn từ và duyệt theo cấp (đợt 10): bảng org_requests. Chỉ thêm bảng.

Revision ID: 20261119_16
Revises: 20261119_15
Create Date: 2026-11-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261119_16"
down_revision = "20261119_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_requests",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("space_id", sa.String(64), sa.ForeignKey("org_spaces.space_id", ondelete="CASCADE"), nullable=False),
        sa.Column("requester_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("days", sa.Float(), nullable=True),
        sa.Column("approver_level", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("check_result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("history", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("approver_level IN ('MANAGER', 'EXECUTIVE')", name="ck_org_requests_level"),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN')", name="ck_org_requests_status"),
        sa.CheckConstraint("approver_level = 'EXECUTIVE' OR department_id IS NOT NULL", name="ck_org_requests_department"),
    )
    op.create_index("ix_org_requests_space_status", "org_requests", ["space_id", "status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_org_requests_space_status", table_name="org_requests")
    op.drop_table("org_requests")
