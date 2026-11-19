"""Lĩnh vực của không gian (đa ngành): studio_workspaces.domain_pack, org_spaces.domain_pack.

Dòng cũ nhận "software" nên trả lời giữ nguyên như trước; không gian tạo sau mặc định "general".
Giá trị hợp lệ kiểm ở tầng API theo app/research/registry.py (PACKS), không đặt CHECK để thêm ngành không cần migration.

Revision ID: 20261118_14
Revises: 20261118_13
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261118_14"
down_revision = "20261118_13"
branch_labels = None
depends_on = None

TABLES = ("studio_workspaces", "org_spaces")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("domain_pack", sa.String(32), nullable=False, server_default="software"))
        op.alter_column(table, "domain_pack", server_default="general")


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "domain_pack")
