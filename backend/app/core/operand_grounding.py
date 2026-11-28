"""Operand Grounding & Dimensional Unit Verification (B139.1 Phase C).

Ensures every operand used in calculation or rule reasoning has verified provenance
(USER_INPUT, authorized DOCUMENT_EVIDENCE / OFFICIAL_RULE, or traced DERIVED_VALUE),
and blocks unit mismatches, example leakage, cross-entity contamination, and ACL violations.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.core.structured_evidence import (
    EvidenceRole,
    StructuredEvidence,
    ValidationStatus,
)


@dataclass
class OperandGroundingResult:
    status: str
    operand_value: Any = None
    unit: str = ""
    currency: str = ""
    evidence_id: str = ""
    source_id: str = ""
    chunk_id: str = ""
    evidence_role: str = EvidenceRole.UNKNOWN
    reason: str = ""
    derivation: dict[str, Any] | None = None


_UNIT_COMPAT_GROUPS = {
    "VND": {"VND"},
    "VND/hour": {"VND/hour"},
    "VND/day": {"VND/day"},
    "VND/month": {"VND/month"},
    "VND/year": {"VND/year"},
    "USD": {"USD"},
    "USD/month": {"USD/month"},
    "hour": {"hour", "hour/day"},
    "hour/day": {"hour/day", "hour"},
    "day": {"day", "working_day"},
    "working_day": {"working_day", "day"},
    "percent": {"percent"},
}


def are_units_compatible(source_unit: str, target_unit: str) -> bool:
    """Strictly verify unit compatibility so e.g. VND/day is never accepted as VND/hour."""
    su = (source_unit or "").strip()
    tu = (target_unit or "").strip()
    if not tu:
        return True
    if su == tu:
        return True
    return su in _UNIT_COMPAT_GROUPS.get(tu, {tu})


def _matches_entity(item: StructuredEvidence, entity: str) -> bool:
    if not entity:
        return True
    ent_cf = entity.casefold()
    item_ent = (item.entity or "").casefold()
    span_cf = (item.source_span or "").casefold()
    if item_ent:
        return ent_cf in item_ent or item_ent in ent_cf
    # Global rule without an entity header can still apply only when conditions match,
    # EXCEPT if we have entity-bound candidates — prefer exact entity rows over generic lines.
    return ent_cf in span_cf or item.evidence_role == EvidenceRole.OFFICIAL_RULE


_SPECIAL_SCOPE_CONDITIONS = frozenset({"minor_worker", "hazardous_work", "multi_year_3yr", "weekly_schedule"})


def _matches_conditions(item: StructuredEvidence, active_conditions: list[str] | None) -> bool:
    avail = {c.casefold() for c in item.applicable_conditions}
    req = {c.casefold() for c in (active_conditions or ())}
    # Restrictive rules (e.g. minor/hazardous/weekly schedule) apply ONLY when explicitly activated.
    if (avail & _SPECIAL_SCOPE_CONDITIONS) and not ((avail & _SPECIAL_SCOPE_CONDITIONS) <= req):
        return False
    # If weekly_schedule is requested for hours_per_day, prefer weekly items over daily-only defaults
    if "weekly_schedule" in req and "daily_schedule" in avail and "weekly_schedule" not in avail:
        return False
    if not req or not avail:
        return True
    if req <= {"weekly_schedule"} and "weekly_schedule" in avail:
        return True
    return bool(req & avail) or ("daily_schedule" in avail and not (req - {"daily_schedule"}))


def _date_applicable(item: StructuredEvidence, effective_date: str) -> bool:
    if not effective_date or not item.effective_date:
        return True
    return item.effective_date <= effective_date


def ground_operand(
    pool: list[StructuredEvidence],
    *,
    attribute: str = "",
    entity: str = "",
    target_unit: str = "",
    target_currency: str = "",
    active_conditions: list[str] | None = None,
    effective_date: str = "",
    allowed_source_ids: set[str] | None = None,
    expected_value: float | int | None = None,
    allow_examples: bool = False,
) -> OperandGroundingResult:
    """Ground a single operand against structured evidence with strict provenance, ACL, entity, condition, and unit checks."""
    authorized = [
        item for item in pool
        if item.validation_status == ValidationStatus.VALIDATED
        and item.data_type != "identifier"
        and (
            allowed_source_ids is None
            or item.source_id in {"user_input", "derived"}
            or item.source_id in allowed_source_ids
        )
    ]
    if not allow_examples:
        authorized = [
            item for item in authorized
            if item.evidence_role not in {EvidenceRole.DOCUMENT_EXAMPLE, EvidenceRole.UNKNOWN}
        ]

    candidates = []
    for item in authorized:
        if attribute and item.attribute != attribute:
            continue
        if target_currency and item.currency and item.currency != target_currency:
            continue
        if target_unit and not are_units_compatible(item.unit, target_unit):
            continue
        if not _matches_conditions(item, active_conditions):
            continue
        if not _date_applicable(item, effective_date):
            continue
        if entity:
            # If entity is explicitly tagged on another item, reject mismatched explicit entity items!
            if item.entity and entity.casefold() not in item.entity.casefold() and item.entity.casefold() not in entity.casefold():
                continue
            if not _matches_entity(item, entity):
                continue
        if expected_value is not None:
            if isinstance(item.value, (int, float)) and abs(float(item.value) - float(expected_value)) > 1e-6:
                continue
        candidates.append(item)

    if not candidates:
        return OperandGroundingResult(
            status=ValidationStatus.UNSUPPORTED if expected_value is not None else ValidationStatus.UNKNOWN,
            reason="no authorized matching evidence satisfying entity/condition/unit constraints",
        )

    # Prefer explicit entity matches over global rules when both exist
    if entity:
        exact_ent = [c for c in candidates if c.entity and entity.casefold() in c.entity.casefold()]
        if exact_ent:
            candidates = exact_ent

    # For working hours, prefer actual contractual/company schedule over statutory maximum caps
    if attribute == "hours_per_day":
        actual_cands = [c for c in candidates if "actual_schedule" in c.applicable_conditions]
        if actual_cands:
            candidates = actual_cands
        else:
            non_stat = [c for c in candidates if "statutory_max" not in c.applicable_conditions]
            if non_stat:
                candidates = non_stat

    # Resolve superseded effective dates cleanly when newer official rule exists
    if len({c.value for c in candidates if isinstance(c.value, (int, float, str))}) > 1:
        dated = [c for c in candidates if c.effective_date]
        if dated:
            latest_date = max(c.effective_date for c in dated)
            latest_candidates = [c for c in dated if c.effective_date == latest_date]
            if len({c.value for c in latest_candidates}) == 1:
                candidates = latest_candidates

    distinct_vals = {str(c.value) for c in candidates}
    if len(distinct_vals) > 1:
        return OperandGroundingResult(
            status=ValidationStatus.CONFLICT,
            reason=f"conflicting evidence values for attribute={attribute}: {sorted(distinct_vals)}",
        )

    chosen = candidates[0]
    return OperandGroundingResult(
        status=ValidationStatus.VALIDATED,
        operand_value=chosen.value,
        unit=chosen.unit,
        currency=chosen.currency,
        evidence_id=chosen.evidence_id,
        source_id=chosen.source_id,
        chunk_id=chosen.chunk_id,
        evidence_role=chosen.evidence_role,
        reason="grounded",
        derivation=chosen.derivation,
    )


def derive_hourly_rate(
    pool: list[StructuredEvidence],
    *,
    entity: str = "",
    hours_per_day: float | None = None,
    workdays_per_month: float | None = None,
    allowed_source_ids: set[str] | None = None,
) -> tuple[StructuredEvidence | None, OperandGroundingResult]:
    """Convert monthly/daily salary to VND/hour ONLY with explicit workdays_per_month and hours_per_day evidence (no silent defaults)."""
    sal_daily = ground_operand(
        pool,
        attribute="salary_daily",
        entity=entity,
        target_unit="VND/day",
        allowed_source_ids=allowed_source_ids,
    )
    sal = ground_operand(
        pool,
        attribute="salary_monthly",
        entity=entity,
        target_unit="VND/month",
        allowed_source_ids=allowed_source_ids,
    )
    if sal.status != ValidationStatus.VALIDATED and sal_daily.status == ValidationStatus.VALIDATED:
        hpd_val = hours_per_day
        hpd_id = "explicit_arg"
        if hpd_val is None:
            hpd = ground_operand(pool, attribute="hours_per_day", target_unit="hour/day", allowed_source_ids=allowed_source_ids)
            if hpd.status != ValidationStatus.VALIDATED:
                return None, OperandGroundingResult(status=ValidationStatus.UNKNOWN, reason="missing hours_per_day evidence (refusing silent /8 assumption)")
            hpd_val, hpd_id = float(hpd.operand_value), hpd.evidence_id
        if hpd_val <= 0:
            return None, OperandGroundingResult(status=ValidationStatus.UNSUPPORTED, reason="non-positive divisor in hourly derivation")
        hourly_d = float(sal_daily.operand_value) / hpd_val
        derived_d = StructuredEvidence(
            evidence_id=f"ev_derived_hourly_{sal_daily.evidence_id}",
            source_id="derived",
            chunk_id=sal_daily.chunk_id,
            source_span=f"{sal_daily.operand_value} / {hpd_val}",
            entity=entity,
            attribute="hourly_rate",
            value=hourly_d,
            data_type="currency",
            unit="VND/hour",
            currency="VND",
            evidence_role=EvidenceRole.DERIVED_VALUE,
            derivation={"formula": "salary_daily / hours_per_day", "input_evidence_ids": [sal_daily.evidence_id, hpd_id]},
            validation_status=ValidationStatus.VALIDATED,
        )
        return derived_d, OperandGroundingResult(
            status=ValidationStatus.VALIDATED,
            operand_value=hourly_d,
            unit="VND/hour",
            currency="VND",
            evidence_id=derived_d.evidence_id,
            source_id=derived_d.source_id,
            chunk_id=derived_d.chunk_id,
            evidence_role=EvidenceRole.DERIVED_VALUE,
            reason="derived hourly rate from daily salary with explicit hours_per_day trace",
            derivation=derived_d.derivation,
        )

    if sal.status != ValidationStatus.VALIDATED:
        return None, OperandGroundingResult(status=sal.status, reason=f"missing monthly salary: {sal.reason}")

    wd_val = workdays_per_month
    wd_id = "explicit_arg"
    if wd_val is None:
        wd = ground_operand(pool, attribute="workdays_per_month", entity=entity, target_unit="working_day", allowed_source_ids=allowed_source_ids)
        if wd.status != ValidationStatus.VALIDATED:
            return None, OperandGroundingResult(status=ValidationStatus.UNKNOWN, reason="missing workdays_per_month evidence")
        wd_val, wd_id = float(wd.operand_value), wd.evidence_id

    hpd_val = hours_per_day
    hpd_id = "explicit_arg"
    if hpd_val is None:
        hpd = ground_operand(pool, attribute="hours_per_day", target_unit="hour/day", allowed_source_ids=allowed_source_ids)
        if hpd.status != ValidationStatus.VALIDATED:
            return None, OperandGroundingResult(status=ValidationStatus.UNKNOWN, reason="missing hours_per_day evidence (refusing silent /8 assumption)")
        hpd_val, hpd_id = float(hpd.operand_value), hpd.evidence_id

    if wd_val <= 0 or hpd_val <= 0:
        return None, OperandGroundingResult(status=ValidationStatus.UNSUPPORTED, reason="non-positive divisor in hourly derivation")

    hourly = float(sal.operand_value) / wd_val / hpd_val
    derived = StructuredEvidence(
        evidence_id=f"ev_derived_hourly_{sal.evidence_id}",
        source_id="derived",
        chunk_id=sal.chunk_id,
        source_span=f"{sal.operand_value} / {wd_val} / {hpd_val}",
        entity=entity,
        attribute="hourly_rate",
        value=hourly,
        data_type="currency",
        unit="VND/hour",
        currency="VND",
        evidence_role=EvidenceRole.DERIVED_VALUE,
        derivation={
            "formula": "salary_monthly / workdays_per_month / hours_per_day",
            "input_evidence_ids": [sal.evidence_id, wd_id, hpd_id],
        },
        validation_status=ValidationStatus.VALIDATED,
    )
    return derived, OperandGroundingResult(
        status=ValidationStatus.VALIDATED,
        operand_value=hourly,
        unit="VND/hour",
        currency="VND",
        evidence_id=derived.evidence_id,
        source_id=derived.source_id,
        chunk_id=derived.chunk_id,
        evidence_role=EvidenceRole.DERIVED_VALUE,
        reason="derived hourly rate with explicit denominator trace",
        derivation=derived.derivation,
    )


def verify_expression_grounding(
    expr: str,
    *,
    expected_target_unit: str,
    bindings: dict[str, StructuredEvidence],
    allowed_source_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Validate provenance, role, ACL, and unit dimensional consistency across bound operands in an expression."""
    if not bindings:
        return {"valid": False, "status": ValidationStatus.UNKNOWN, "reason": "no bound operands", "issues": ["missing_bindings"]}

    issues: list[str] = []
    units: list[str] = []
    for name, ev in bindings.items():
        if ev.validation_status != ValidationStatus.VALIDATED:
            issues.append(f"unvalidated_operand:{name}:{ev.validation_status}")
        if ev.evidence_role in {EvidenceRole.DOCUMENT_EXAMPLE, EvidenceRole.UNKNOWN}:
            issues.append(f"disallowed_role:{name}:{ev.evidence_role}")
        if ev.data_type == "identifier":
            issues.append(f"identifier_used_as_operand:{name}")
        if allowed_source_ids is not None and ev.source_id not in {"user_input", "derived"} and ev.source_id not in allowed_source_ids:
            issues.append(f"unauthorized_source:{name}:{ev.source_id}")
        units.append(ev.unit)

    # Check multiplicative unit compatibility: e.g., (VND/day) * hour cannot produce VND!
    has_daily_rate = any(u in {"VND/day", "USD/day"} for u in units)
    has_monthly_rate = any(u in {"VND/month", "USD/month"} for u in units)
    has_hours = any(u in {"hour", "hour/day"} for u in units)
    if expected_target_unit in {"VND", "USD"} and has_hours and (has_daily_rate or has_monthly_rate):
        issues.append("unit_mismatch:multiplying_non_hourly_rate_by_hours")

    if issues:
        return {
            "valid": False,
            "status": ValidationStatus.UNSUPPORTED,
            "reason": "; ".join(issues),
            "issues": issues,
            "expr": expr,
        }
    return {
        "valid": True,
        "status": ValidationStatus.VALIDATED,
        "reason": "all operands grounded with compatible units",
        "issues": [],
        "expr": expr,
    }


_DOC_ID_NUM = re.compile(
    r"\b(?:Nghị\s*định|Thông\s*tư|Quyết\s*định|Luật|Công\s*văn|Điều|Khoản|Mục|tháng|năm)\s+(?:số\s*:?\s*)?(\d{1,4})(?:[/-](\d{2,4}))?\b",
    re.I,
)


def identifier_numbers_in_text(text: str) -> set[str]:
    """Return numeric tokens belonging to document/article/month identifiers so they are never treated as calc operands."""
    out: set[str] = set()
    for m in _DOC_ID_NUM.finditer(text or ""):
        out.add(str(int(m.group(1))) if m.group(1).isdigit() else m.group(1))
        if m.group(2) and m.group(2).isdigit():
            out.add(str(int(m.group(2))))
    return out
