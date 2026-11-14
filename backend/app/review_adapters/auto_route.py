"""Deterministic selection between grounded and planned review pipelines."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.review_adapters.slot_check import extract_slots


_SPLITTER = re.compile(
    r"\s*(?:;|\bvà\b|\bđồng\s+thời\b|\bcũng\s+như\b|\band\b|\bas\s+well\s+as\b)\s*",
    re.IGNORECASE,
)
_COMMA_BEFORE_VERB = re.compile(
    r",\s*(?=(?:phải|cần|được|must|shall|should)\b)", re.IGNORECASE,
)


@dataclass(frozen=True)
class RouteChoice:
    path: str
    reason: str
    params: dict


def choose_path(text: str, *, c_available: bool = True) -> RouteChoice:
    clauses = [part for part in _SPLITTER.split(text) if part.strip()]
    ideas = max(1, len(clauses)) if text.strip() else 0
    ideas += len(_COMMA_BEFORE_VERB.findall(text))
    slots = len(extract_slots(text))
    words = len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))
    params = {"ideas": ideas, "words": words, "slots": slots}
    if not c_available:
        return RouteChoice("B", "C_NOT_AVAILABLE", params)
    if ideas >= 2 and words >= 12:
        return RouteChoice("C", "MULTI_IDEA", params)
    if ideas >= 2 and slots >= 2:
        return RouteChoice("C", "MULTI_QUANTITY", params)
    if ideas >= 2:
        return RouteChoice("B", "SHORT_REQUEST", params)
    if words < 12:
        return RouteChoice("B", "SHORT_REQUEST", params)
    return RouteChoice("B", "SINGLE_IDEA", params)
