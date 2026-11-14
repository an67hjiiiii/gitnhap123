"""Review cases, requirements, findings, and durable run jobs/events.

Revision ID: 20261114_05
Revises: 20261111_04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20261114_05"
down_revision = "20261111_04"
branch_labels = None
depends_on = None


def _json():
    return sa.JSON().with_variant(JSONB(), "postgresql")


def _case_owner_fk(table):
    return sa.ForeignKeyConstraint(
        ["case_id", "owner_user_id"], ["review_cases.id", "review_cases.owner_user_id"],
        ondelete="CASCADE", name=f"fk_{table}_case_owner",
    )


def upgrade() -> None:
    op.create_table(
        "review_cases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_user_id", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("source_ids", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("id", "owner_user_id", name="uq_review_cases_id_owner"),
    )
    op.create_index("ix_review_cases_owner", "review_cases", ["owner_user_id"])
    op.create_table(
        "review_requirements",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ord", sa.Integer(), nullable=False),
        _case_owner_fk("review_requirements"),
        sa.UniqueConstraint("case_id", "ord", name="uq_review_requirements_case_ord"),
    )
    op.create_index("ix_review_requirements_owner_case", "review_requirements", ["owner_user_id", "case_id"])
    op.create_table(
        "review_findings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("requirement_id", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("evidence", _json(), nullable=False),
        sa.Column("review", sa.String(32), nullable=False),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _case_owner_fk("review_findings"),
    )
    op.create_index("ix_review_findings_owner_case", "review_findings", ["owner_user_id", "case_id"])
    op.create_table(
        "review_run_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("budget", _json(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _case_owner_fk("review_run_jobs"),
    )
    op.create_index("ix_review_run_jobs_owner_case", "review_run_jobs", ["owner_user_id", "case_id"])
    op.create_index("ix_review_run_jobs_state_lease", "review_run_jobs", ["state", "lease_expires_at"])
    op.create_table(
        "review_run_events",
        sa.Column("job_id", sa.String(64), sa.ForeignKey("review_run_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(128), nullable=False),
        sa.Column("data", _json(), nullable=False),
    )


def downgrade() -> None:
    for table in ("review_run_events", "review_run_jobs", "review_findings", "review_requirements", "review_cases"):
        op.drop_table(table)
