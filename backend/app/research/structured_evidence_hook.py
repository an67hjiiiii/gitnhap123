"""Experimental OFF-by-Default Structured Evidence Hook (B139.1 Phase E).

Gate: `PRODUCT_STRUCTURED_EVIDENCE=on` (default `off`).
Zero LLM calls, zero arbitrary eval, zero impact on Research Mode (`product_mode=False`) or default Product runs.
"""
from __future__ import annotations

import os
from typing import Any

from app.core.operand_grounding import identifier_numbers_in_text
from app.core.structured_evidence import (
    SCHEMA_VERSION,
    EvidenceRole,
    ValidationStatus,
    extract_structured_evidence,
)
from app.core.types import SourceChunk


def structured_evidence_enabled() -> bool:
    """Return True only when explicitly opted in via PRODUCT_STRUCTURED_EVIDENCE=on|1|true|yes."""
    return os.getenv("PRODUCT_STRUCTURED_EVIDENCE", "off").strip().lower() in {"1", "on", "true", "yes"}


def advanced_reasoning_enabled() -> bool:
    """Return True only when explicitly opted in via PRODUCT_ADVANCED_REASONING=on|1|true|yes."""
    return os.getenv("PRODUCT_ADVANCED_REASONING", "off").strip().lower() in {"1", "on", "true", "yes"}


def build_grounding_snapshot(
    query: str,
    chunks: list[SourceChunk],
    *,
    answer: str = "",
    allowed_source_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build a read-only structured evidence & identifier snapshot ready for B139.2 calculator/rule consumers."""
    items = extract_structured_evidence(chunks, query=query, allowed_source_ids=allowed_source_ids)
    role_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for item in items:
        role_counts[item.evidence_role] = role_counts.get(item.evidence_role, 0) + 1
        status_counts[item.validation_status] = status_counts.get(item.validation_status, 0) + 1

    id_nums = sorted(identifier_numbers_in_text(f"{query}\n" + "\n".join(c.text for c in chunks)))
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_count": len(items),
        "role_counts": role_counts,
        "status_counts": status_counts,
        "identifier_numbers": id_nums,
        "example_count": role_counts.get(EvidenceRole.DOCUMENT_EXAMPLE, 0),
        "unknown_count": status_counts.get(ValidationStatus.UNKNOWN, 0) + status_counts.get(ValidationStatus.AMBIGUOUS, 0),
        "answer_checked_len": len(answer or ""),
    }
