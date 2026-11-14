"""Portable review persistence, independent of the product identity tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.postgres.base import Base


REVIEW_JSON = JSON().with_variant(JSONB(), "postgresql")


class ReviewCaseRecord(Base):
    __tablename__ = "review_cases"
    __table_args__ = (
        UniqueConstraint("id", "owner_user_id", name="uq_review_cases_id_owner"),
        Index("ix_review_cases_owner", "owner_user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    request_text: Mapped[str] = mapped_column(Text)
    source_ids: Mapped[list[str]] = mapped_column(REVIEW_JSON, default=list)
    kind: Mapped[str] = mapped_column(String(32), default="requirement_review", server_default="requirement_review")
    meta: Mapped[dict[str, Any] | None] = mapped_column(REVIEW_JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewRequirementRecord(Base):
    __tablename__ = "review_requirements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "owner_user_id"], ["review_cases.id", "review_cases.owner_user_id"],
            ondelete="CASCADE", name="fk_review_requirements_case_owner",
        ),
        UniqueConstraint("case_id", "ord", name="uq_review_requirements_case_ord"),
        Index("ix_review_requirements_owner_case", "owner_user_id", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64))
    owner_user_id: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(32))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ord: Mapped[int] = mapped_column(Integer)


class ReviewFindingRecord(Base):
    __tablename__ = "review_findings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "owner_user_id"], ["review_cases.id", "review_cases.owner_user_id"],
            ondelete="CASCADE", name="fk_review_findings_case_owner",
        ),
        Index("ix_review_findings_owner_case", "owner_user_id", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64))
    requirement_id: Mapped[str] = mapped_column(String(64))
    owner_user_id: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(REVIEW_JSON, default=list)
    review: Mapped[str] = mapped_column(String(32))
    edited_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewRunJobRecord(Base):
    __tablename__ = "review_run_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "owner_user_id"], ["review_cases.id", "review_cases.owner_user_id"],
            ondelete="CASCADE", name="fk_review_run_jobs_case_owner",
        ),
        Index("ix_review_run_jobs_owner_case", "owner_user_id", "case_id"),
        Index("ix_review_run_jobs_state_lease", "state", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64))
    owner_user_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32))
    seq: Mapped[int] = mapped_column(Integer)
    budget: Mapped[dict[str, Any] | None] = mapped_column(REVIEW_JSON)
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewRunEventRecord(Base):
    __tablename__ = "review_run_events"

    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("review_run_jobs.id", ondelete="CASCADE"), primary_key=True,
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type: Mapped[str] = mapped_column(String(128))
    data: Mapped[dict[str, Any]] = mapped_column(REVIEW_JSON)
