"""Mẫu tổ chức (Đợt A đa lĩnh vực): org_spaces.preset, org_spaces.labels.

Chỉ đổi tên gọi hiển thị (Trưởng khoa, Ban giám hiệu...). Luật quyền ở app/core/access.py không đọc hai cột này.
Không gian cũ nhận mẫu "business" nên giao diện giữ nguyên chữ Nhân viên / Trưởng phòng / Ban giám đốc.

Revision ID: 20261117_12
Revises: 20261116_11
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261117_12"
down_revision = "20261116_11"
branch_labels = None
depends_on = None

PRESETS = ("business", "school", "hospital", "government", "team", "custom")


def upgrade() -> None:
    op.add_column("org_spaces", sa.Column("preset", sa.String(16), nullable=False, server_default="business"))
    op.add_column("org_spaces", sa.Column("labels", sa.JSON(), nullable=True))
    op.create_check_constraint("ck_org_spaces_preset", "org_spaces", f"preset IN {PRESETS!r}")


def downgrade() -> None:
    op.drop_constraint("ck_org_spaces_preset", "org_spaces", type_="check")
    op.drop_column("org_spaces", "labels")
    op.drop_column("org_spaces", "preset")
