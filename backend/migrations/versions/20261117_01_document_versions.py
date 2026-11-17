"""Add unconfirmed document version proposals, independent of source lifecycle."""
from alembic import op
import sqlalchemy as sa

revision = "20261117_01"
down_revision = "20261115_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(128), sa.ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("owner_user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_key", sa.String(256)),
        sa.Column("doc_number", sa.String(256)),
        sa.Column("version_label", sa.String(128)),
        sa.Column("issued_on", sa.Date()),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("applies_from", sa.Date()),
        sa.Column("applies_note", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="unverified"),
        sa.Column("relations", sa.JSON(), nullable=False),
        sa.Column("transition_note", sa.Text()),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("confirmed_by", sa.String(64), sa.ForeignKey("users.user_id", ondelete="SET NULL")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft', 'issued', 'superseded', 'unverified')", name="ck_document_versions_status"),
    )
    op.create_index("ix_document_versions_owner_user_id", "document_versions", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_document_versions_owner_user_id", table_name="document_versions")
    op.drop_table("document_versions")
