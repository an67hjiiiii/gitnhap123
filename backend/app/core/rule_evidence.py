"""Rule Evidence Foundation Schema & Missing-Rule vs Interpretation Classifier (B139.1 Phase D).

Reuses `app.analysis.casework.VERDICTS` and `overall_verdict()` conventions (`MET`, `NOT_MET`, `UNKNOWN`),
without silently upgrading missing/unretrieved rules into `MET` or `ELIGIBLE`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.analysis.casework import VERDICTS
from app.core.types import SourceChunk

RULE_SCHEMA_VERSION = "rule-evidence-v1"
VALID_CONDITION_KINDS = frozenset({"mandatory", "optional", "exception", "approval", "applicability"})


@dataclass
class RuleConditionEvidence:
    condition_id: str
    description: str
    kind: str = "mandatory"
    applicability_conditions: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    approval_roles: list[str] = field(default_factory=list)
    verdict: str = "UNKNOWN"
    case_fact: str = ""
    source_id: str = ""
    chunk_id: str = ""
    source_span: str = ""
    missing_evidence_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleAssessmentResult:
    overall: str
    failure_classification: str
    conditions: list[RuleConditionEvidence] = field(default_factory=list)
    missing_rule_topics: list[str] = field(default_factory=list)
    missing_statutes: list[str] = field(default_factory=list)
    approval_requirements: list[str] = field(default_factory=list)
    schema_version: str = RULE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "conditions": [c.to_dict() for c in self.conditions],
        }


def _statute_loaded(statute: str, chunks: list[SourceChunk]) -> bool:
    st_cf = statute.casefold()
    for ch in chunks:
        prov = ch.provenance or {}
        if str(prov.get("doc_type") or "").lower() == "contract":
            continue
        if st_cf in (ch.source_name or "").casefold():
            return True
        if str(prov.get("doc_type") or "").lower() == "legal_doc" and st_cf in (ch.text or "").casefold():
            return True
    return False


def assess_rule_conditions(
    conditions: list[RuleConditionEvidence],
    *,
    required_rule_topics: list[str] | None = None,
    evidence_chunks: list[SourceChunk] | None = None,
    requested_statutes: list[str] | None = None,
    allowed_source_ids: set[str] | None = None,
) -> RuleAssessmentResult:
    """Evaluate structured rule conditions and separate missing retrieval evidence from rule evaluation gaps."""
    authorized_chunks = [
        ch for ch in (evidence_chunks or [])
        if allowed_source_ids is None or ch.source_id in allowed_source_ids
    ]
    joined = "\n".join((ch.text or "").casefold() for ch in authorized_chunks)

    missing_topics: list[str] = []
    for topic in (required_rule_topics or []):
        t_cf = (topic or "").strip().casefold()
        if t_cf and t_cf not in joined:
            missing_topics.append(topic)

    missing_statutes: list[str] = []
    for st in (requested_statutes or []):
        if st and not _statute_loaded(st, authorized_chunks):
            missing_statutes.append(st)

    normalized_conds: list[RuleConditionEvidence] = []
    approvals: list[str] = []
    for c in conditions:
        v = c.verdict.upper() if c.verdict and c.verdict.upper() in VERDICTS else "UNKNOWN"
        # Unauthorized or uncited conditions cannot verify MET
        if allowed_source_ids is not None and c.source_id and c.source_id not in allowed_source_ids:
            v = "UNKNOWN"
            c = RuleConditionEvidence(
                **{**asdict(c), "verdict": "UNKNOWN", "missing_evidence_reason": "unauthorized_source_scope"}
            )
        else:
            c = RuleConditionEvidence(**{**asdict(c), "verdict": v})
        normalized_conds.append(c)
        for role in c.approval_roles:
            if role not in approvals:
                approvals.append(role)

    mandatory_verdicts = {c.verdict for c in normalized_conds if c.kind in {"mandatory", "approval", "applicability"}}

    if not normalized_conds:
        if missing_topics or missing_statutes:
            return RuleAssessmentResult(
                overall="NO_EVIDENCE_FOR_RULE",
                failure_classification="RETRIEVAL_MISSING_EVIDENCE",
                conditions=[],
                missing_rule_topics=missing_topics,
                missing_statutes=missing_statutes,
                approval_requirements=approvals,
            )
        return RuleAssessmentResult(
            overall="UNRESOLVED",
            failure_classification="EXTRACTION_FAILURE",
            conditions=[],
            missing_rule_topics=[],
            missing_statutes=missing_statutes,
            approval_requirements=approvals,
        )

    if "NOT_MET" in mandatory_verdicts:
        overall = "NOT_ELIGIBLE"
        failure_cls = "RETRIEVAL_MISSING_EVIDENCE" if (missing_topics or missing_statutes) else "NONE"
    elif "UNKNOWN" in mandatory_verdicts or missing_topics or missing_statutes:
        overall = "INSUFFICIENT_INFO"
        failure_cls = "RETRIEVAL_MISSING_EVIDENCE" if (missing_topics or missing_statutes) else "RULE_INTERPRETATION_FAILURE"
    else:
        overall = "ELIGIBLE"
        failure_cls = "NONE"

    return RuleAssessmentResult(
        overall=overall,
        failure_classification=failure_cls,
        conditions=normalized_conds,
        missing_rule_topics=missing_topics,
        missing_statutes=missing_statutes,
        approval_requirements=approvals,
    )
