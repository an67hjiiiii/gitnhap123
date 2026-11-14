"""Conservative lexical verdict rules; no provider or storage dependencies.

Durations use minutes (365 days/year, 30 days/month); sizes use decimal MB.
These are explicit fixed conversions, not calendar arithmetic. Subjects are
lexical hints, not parsed entities; synonyms and implicit obligations are unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata
from typing import Any, Iterable


SATISFIES = "SATISFIES"
CONFLICTS = "CONFLICTS"
UNRELATED = "UNRELATED"


@dataclass(frozen=True)
class Claim:
    kind: str
    subject_hint: str
    op: str
    value: Decimal | None
    unit: str
    span: str


@dataclass(frozen=True)
class Assessment:
    verdict_hint: str
    supporting: list[Any]
    conflicting: list[Any]
    notes: list[str]


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                   if unicodedata.category(c) != "Mn").replace("đ", "d")


_UNITS = {
    "characters": ("characters", 1), "character": ("characters", 1), "ky tu": ("characters", 1),
    "minutes": ("minutes", 1), "minute": ("minutes", 1), "phut": ("minutes", 1),
    "hours": ("minutes", 60), "hour": ("minutes", 60), "gio": ("minutes", 60),
    "days": ("minutes", 1440), "day": ("minutes", 1440), "ngay": ("minutes", 1440),
    "months": ("minutes", 43200), "month": ("minutes", 43200), "thang": ("minutes", 43200),
    "years": ("minutes", 525600), "year": ("minutes", 525600), "nam": ("minutes", 525600),
    "%": ("percent", 1), "percent": ("percent", 1),
    "mb": ("MB", 1), "gb": ("MB", 1000),
    "times": ("times", 1), "time": ("times", 1), "lan": ("times", 1),
    "attempts": ("times", 1), "attempt": ("times", 1),
}
_COMPARATORS = {
    "at least": ">=", "minimum": ">=", "it nhat": ">=", "toi thieu": ">=",
    "at most": "<=", "maximum": "<=", "khong qua": "<=", "toi da": "<=",
    "exactly": "==", "dung": "==", "within": "<=", "trong vong": "<=",
}
_NUMBER_UNIT = re.compile(
    r"(?<![\w.,-])(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>"
    + "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
    + r")(?!\w)"
)
_COMPARATOR = re.compile(r"\b(" + "|".join(_COMPARATORS) + r")\s*$")
_NEGATIVE = re.compile(r"\b(?:must not|never|khong duoc)\b")
_POSITIVE = re.compile(r"\b(?:must|always|phai)\b")
_STOPWORDS = set("""
    a an the is are was were be been being to of for in on at by with from as
    and or but if then than this that it its their our your can could should
    shall may will have has had do does after before during per only least most
    minimum maximum exactly within not no must never always
    la co cac nhung mot cua cho trong voi va hoac thi duoc phai khong it nhat
    toi thieu da qua dung vong
    retain retained retaining require requires required keep kept allow allowed
    use used provide provides support supports
""".split())
_UNIT_WORDS = set(" ".join(_UNITS).split())


def _subject(text: str) -> str:
    # Remove quantities and grammatical/comparator words, retaining stable lexical
    # hints. Singularize English plurals only; do not stem Vietnamese syllables.
    words = re.findall(r"[a-z]+", _NUMBER_UNIT.sub(" ", text))
    words = [w[:-1] if w.endswith("s") and len(w) > 3 else w
             for w in words if w not in _STOPWORDS and w not in _UNIT_WORDS]
    return " ".join(sorted(set(words)))


def extract_claims(text: str) -> list[Claim]:
    """Extract digit/unit claims and explicit modal polarity, clause by clause.

    span preserves the original clause, including its accents. Bare numeric
    claims use their unit noun as a subject hint (e.g. "12 characters").
    """
    claims = []
    # A decimal point is not a sentence boundary. Conjunctions isolate subjects.
    for clause in re.split(r"[;!?\n]+|\.(?!\d)|\b(?:and|but|va|nhung)\b", text, flags=re.I):
        clause = clause.strip()
        if not clause:
            continue
        folded = _fold(clause)
        subject = _subject(folded)
        negative = bool(_NEGATIVE.search(folded))
        positive = bool(_POSITIVE.search(_NEGATIVE.sub(" ", folded)))
        if negative != positive:
            claims.append(Claim("polarity", subject, "forbid" if negative else "oblige",
                                None, "", clause))
        # Negated quantities need semantic interpretation; leave them unknown.
        if negative or re.search(r"\b(?:not|no)\b", folded):
            continue
        for match in _NUMBER_UNIT.finditer(folded):
            prefix = folded[:match.start()]
            comparator = _COMPARATOR.search(prefix)
            op = _COMPARATORS[comparator[1]] if comparator else "=="
            unit, factor = _UNITS[match["unit"]]
            claims.append(Claim("quantitative", subject or unit.casefold(), op,
                                Decimal(match["number"]) * factor, unit, clause))
    return claims


def compare(requirement_claim: Claim, evidence_claim: Claim) -> str:
    """Compare explicit assertions; weaker same-direction limits conflict.

    Crossing, overlapping bounds are unknown. A matching unit alone is insufficient
    when either assertion names a subject. Polarity requires two shared hints.
    """
    req, ev = requirement_claim, evidence_claim
    if req.kind != ev.kind:
        return UNRELATED
    shared = set(req.subject_hint.split()) & set(ev.subject_hint.split())
    if req.kind == "polarity":
        if len(shared) < 2:
            return UNRELATED
        return SATISFIES if req.op == ev.op else CONFLICTS
    if req.unit != ev.unit or (not shared and (req.subject_hint or ev.subject_hint)):
        return UNRELATED
    if req.op == ev.op:
        satisfies = {"==": ev.value == req.value,
                     ">=": ev.value >= req.value, "<=": ev.value <= req.value}[req.op]
        return SATISFIES if satisfies else CONFLICTS
    if ev.op == "==":
        satisfies = ev.value >= req.value if req.op == ">=" else ev.value <= req.value
        return SATISFIES if satisfies else CONFLICTS
    if req.op == "==":
        excluded = ev.value > req.value if ev.op == ">=" else ev.value < req.value
    else:
        excluded = ev.value < req.value if req.op == ">=" else ev.value > req.value
    return CONFLICTS if excluded else UNRELATED


def assess(requirement_text: str, evidence_items: Iterable[Any]) -> Assessment:
    """Classify excerpts, preserving input order and original item identity.

    Items may be excerpt strings, mappings, or objects exposing .excerpt. An item
    can both support and conflict; conflicting takes precedence in verdict_hint.
    """
    requirements = extract_claims(requirement_text)
    supporting, conflicting, notes = [], [], []
    for item in evidence_items:
        excerpt = item if isinstance(item, str) else (
            item.get("excerpt", "") if isinstance(item, dict) else getattr(item, "excerpt", "")
        )
        outcomes = set()
        evidence_claims = extract_claims(excerpt or "")
        for req in requirements:
            for ev in evidence_claims:
                outcome = compare(req, ev)
                outcomes.add(outcome)
                if outcome == CONFLICTS:
                    notes.append(f"Conflicting claim: requirement [{req.span}] ({req.op} "
                                 f"{req.value} {req.unit}); evidence [{ev.span}] "
                                 f"({ev.op} {ev.value} {ev.unit}).")
        if CONFLICTS in outcomes:
            conflicting.append(item)
        if SATISFIES in outcomes:
            supporting.append(item)
    hint = "DEVIATES" if conflicting else SATISFIES if supporting else UNRELATED
    return Assessment(hint, supporting, conflicting, notes)
