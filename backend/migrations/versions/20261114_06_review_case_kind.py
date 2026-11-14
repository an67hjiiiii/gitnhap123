"""Add review case kind and source-pair metadata.

Revision ID: 20261114_06
Revises: 20261114_05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20261114_06"
down_revision = "20261114_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_cases", sa.Column(
        "kind", sa.String(32), nullable=False, server_default="requirement_review",
    ))
    op.add_column("review_cases", sa.Column(
        "meta", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("review_cases", "meta")
    op.drop_column("review_cases", "kind")
