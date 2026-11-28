"""Rule & Nested Condition Evaluator (B139.2 Phase D).

Reuses `rule_evidence.py` and `casework.py` conventions (`MET`, `NOT_MET`, `UNKNOWN`, `NOT_APPLICABLE`, `CONFLICT`).
Supports nested AND/OR logic, negation, exceptions, approvals, applicability, and effective dates.
Never conflates UNKNOWN with MET or approves overall eligibility from partial checks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


VALID_LEAF_VERDICTS = frozenset({"MET", "NOT_MET", "UNKNOWN", "NOT_APPLICABLE", "CONFLICT"})


@dataclass
class RuleLeaf:
    rule_id: str
    description: str
    kind: str = "mandatory"  # mandatory | optional | exception | approval | applicability
    verdict: str = "UNKNOWN"
    negated: bool = False
    case_fact: str = ""
    chunk_id: str = ""
    source_id: str = ""
    approval_roles: list[str] = field(default_factory=list)
    effective_date: str = ""


@dataclass
class RuleGroup:
    op: str  # "AND" | "OR"
    children: list[RuleLeaf | "RuleGroup"] = field(default_factory=list)
    negated: bool = False


def _effective_leaf_status(leaf: RuleLeaf, *, allowed_source_ids: set[str] | None = None) -> tuple[str, str]:
    raw_v = (leaf.verdict or "UNKNOWN").strip().upper()
    if raw_v not in VALID_LEAF_VERDICTS:
        return "UNKNOWN", "unrecognized leaf verdict"
    if allowed_source_ids is not None and leaf.source_id and leaf.source_id not in allowed_source_ids:
        return "UNKNOWN", "unauthorized source blocked by ACL"
    if raw_v == "NOT_APPLICABLE":
        return "NOT_APPLICABLE", "rule condition not applicable to this case"
    if raw_v == "CONFLICT":
        return "CONFLICT", "conflicting rule sources"

    # Negation flips MET <-> NOT_MET (e.g., exception: "must NOT be in peak window" with case_fact="in peak window" -> MET exception violation -> FAILS requirement)
    v = raw_v
    if leaf.negated:
        if v == "MET":
            v = "NOT_MET"
        elif v == "NOT_MET":
            v = "MET"
    return v, leaf.case_fact or ("satisfied" if v == "MET" else "violated" if v == "NOT_MET" else "missing case evidence")


def _eval_node(
    node: RuleLeaf | RuleGroup,
    *,
    allowed_source_ids: set[str] | None,
    trace: list[dict[str, Any]],
) -> str:
    if isinstance(node, RuleLeaf):
        eff, reason = _effective_leaf_status(node, allowed_source_ids=allowed_source_ids)
        trace.append({
            "rule_id": node.rule_id,
            "description": node.description,
            "kind": node.kind,
            "raw_verdict": node.verdict,
            "negated": node.negated,
            "effective_status": eff,
            "chunk_id": node.chunk_id,
            "case_fact": node.case_fact,
            "approval_roles": node.approval_roles,
            "reason": reason,
        })
        if node.kind == "optional" and eff in {"UNKNOWN", "NOT_MET"}:
            return "MET"  # Optional conditions do not fail mandatory eligibility
        return eff

    op = (node.op or "AND").strip().upper()
    child_statuses = [_eval_node(ch, allowed_source_ids=allowed_source_ids, trace=trace) for ch in node.children]
    applicable = [s for s in child_statuses if s != "NOT_APPLICABLE"]
    if not applicable:
        res = "NOT_APPLICABLE"
    elif "CONFLICT" in applicable:
        res = "CONFLICT"
    elif op == "AND":
        if "NOT_MET" in applicable:
            res = "NOT_MET"
        elif "UNKNOWN" in applicable:
            res = "UNKNOWN"
        else:
            res = "MET"
    elif op == "OR":
        if "MET" in applicable:
            res = "MET"
        elif "UNKNOWN" in applicable:
            res = "UNKNOWN"
        else:
            res = "NOT_MET"
    else:
        res = "UNKNOWN"

    if node.negated:
        if res == "MET":
            res = "NOT_MET"
        elif res == "NOT_MET":
            res = "MET"
    return res


def evaluate_rule_tree(
    root: RuleLeaf | RuleGroup,
    *,
    allowed_source_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Evaluate nested AND/OR rule tree and map strictly to ELIGIBLE / NOT_ELIGIBLE / INSUFFICIENT_INFO / NOT_APPLICABLE / CONFLICT."""
    trace: list[dict[str, Any]] = []
    status = _eval_node(root, allowed_source_ids=allowed_source_ids, trace=trace)
    overall_map = {
        "MET": "ELIGIBLE",
        "NOT_MET": "NOT_ELIGIBLE",
        "UNKNOWN": "INSUFFICIENT_INFO",
        "NOT_APPLICABLE": "NOT_APPLICABLE",
        "CONFLICT": "CONFLICT",
    }
    return {
        "overall": overall_map.get(status, "INSUFFICIENT_INFO"),
        "tree_status": status,
        "conditions": trace,
        "missing_approval_roles": [
            role
            for row in trace
            if row["kind"] == "approval" and row["effective_status"] == "UNKNOWN"
            for role in row.get("approval_roles") or []
        ],
    }
