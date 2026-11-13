from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrEnum(str, Enum):
    pass


class CaseStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMING = "CONFIRMING"
    READY = "READY"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class Verdict(StrEnum):
    SATISFIED = "SATISFIED"
    PARTIAL = "PARTIAL"
    NOT_FOUND = "NOT_FOUND"
    DEVIATES = "DEVIATES"
    UNDETERMINED = "UNDETERMINED"
    SKIPPED_BUDGET = "SKIPPED_BUDGET"


class Decision(StrEnum):
    NONE = "NONE"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    EDIT = "EDIT"


class Confidence(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class RequirementOrigin(StrEnum):
    AI_PROPOSED = "AI_PROPOSED"
    USER = "USER"


class JobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DomainModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True)


class ReviewCase(DomainModel):
    id: str
    owner_user_id: str
    title: str
    status: CaseStatus = CaseStatus.DRAFT
    source_ids: list[str] = Field(default_factory=list)
    request_text: str
    created_at: datetime
    updated_at: datetime


class Requirement(DomainModel):
    id: str
    case_id: str
    text: str
    origin: RequirementOrigin
    confirmed: bool = False
    order: int


class Evidence(DomainModel):
    evidence_id: str
    source_id: str
    locator: str
    excerpt: str


class Finding(DomainModel):
    id: str
    case_id: str
    requirement_id: str
    verdict: Verdict
    evidence: list[Evidence] = Field(default_factory=list)
    review: Decision = Decision.NONE
    edited_text: str | None = None
    confidence: Confidence


class RunJob(DomainModel):
    id: str
    case_id: str
    state: JobState
    seq: int
    budget: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
