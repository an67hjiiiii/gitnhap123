"""Persist adjacent document version changes."""
from alembic import op
import sqlalchemy as sa

revision = "20261117_03"
down_revision = "20261117_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "version_diffs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("family_key", sa.String(256), nullable=False),
        sa.Column("old_source_id", sa.String(128), sa.ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("new_source_id", sa.String(128), sa.ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_article", sa.String(128)),
        sa.Column("new_article", sa.String(128)),
        sa.Column("old_clause", sa.String(32)),
        sa.Column("new_clause", sa.String(32)),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("atoms_before", sa.JSON(), nullable=False),
        sa.Column("atoms_after", sa.JSON(), nullable=False),
        sa.Column("text_before", sa.Text(), nullable=False),
        sa.Column("text_after", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('DOI', 'THEM', 'BO')", name="ck_version_diffs_kind"),
    )
    op.create_index("ix_version_diffs_pair", "version_diffs", ["old_source_id", "new_source_id"])
    op.create_index("ix_version_diffs_family", "version_diffs", ["family_key"])


def downgrade():
    op.drop_table("version_diffs")
