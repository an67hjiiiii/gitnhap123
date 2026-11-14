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
    upper_value: Decimal | None = None


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
    "up to": "<=",
    "exactly": "==", "dung": "==", "within": "<=", "trong vong": "<=",
}
_NUMBER_UNIT = re.compile(
    r"(?<![\w.,-])(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>"
    + "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
    + r")(?!\w)"
)
_COMPARATOR = re.compile(r"\b(" + "|".join(_COMPARATORS) + r")\s*$")
_UNIT_PATTERN = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
_RANGE = re.compile(
    r"(?<![\w.,-])(?:between\s+|tu\s+)?(?P<lower>\d+(?:\.\d+)?)\s*"
    r"(?P<lower_unit>" + _UNIT_PATTERN + r")?(?!\w)\s*"
    r"(?:and|den|[-–])\s*(?P<upper>\d+(?:\.\d+)?)\s*"
    r"(?P<upper_unit>" + _UNIT_PATTERN + r")(?!\w)"
)
_CONTEXT = re.compile(
    r"\b(?:unless|except|if|provided|example|examples|e\.g|vi du|tru khi|ngoai tru|neu)\b"
)
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\x27[^\x27\n]*\x27')
_NEGATIVE = re.compile(r"\b(?:must not|never|khong duoc)\b")
_POSITIVE = re.compile(r"\b(?:must|always|phai)\b")
_STOPWORDS = set("""
    a an the is are was were be been being to of for in on at by with from as
    and or but if then than this that it its their our your can could should
    shall may will have has had do does after before during per only least most
    minimum maximum exactly within not no must never always up
    between den tu
    la co cac nhung mot cua cho trong voi va hoac thi duoc phai khong it nhat
    toi thieu da qua dung vong
    retain retained retaining require requires required keep kept allow allowed
    use used provide provides support supports
""".split())
_SUBJECT_COMPARATOR = re.compile(r"\b(?:" + "|".join(_COMPARATORS) + r")\b")
# These syllables also occur in Vietnamese subjects (notably "nhat ky").
_STOPWORDS -= {"nhat", "toi", "thieu", "da", "qua", "dung", "tu", "den"}


def _subject(text: str) -> str:
    # Remove quantities and grammatical/comparator words, retaining stable lexical
    # hints. Singularize English plurals only; do not stem Vietnamese syllables.
    words = re.findall(r"[a-z]+", _SUBJECT_COMPARATOR.sub(
        " ", _NUMBER_UNIT.sub(" ", _RANGE.sub(" ", text))
    ))
    words = [w[:-1] if w.endswith("s") and len(w) > 3 else w
             for w in words if w not in _STOPWORDS]
    return " ".join(sorted(set(words)))


def extract_claims(text: str | None) -> list[Claim]:
    """Extract digit/unit claims and explicit modal polarity, clause by clause.

    span preserves the original clause, including its accents. Bare numeric
    claims use their unit noun as a subject hint (e.g. "12 characters").
    """
    if not isinstance(text, str):
        return []
    claims = []
    # Quoted assertions are mentions, not commitments. Keep offsets and original
    # spans intact while hiding their content from the lexical rules.
    unquoted = _QUOTED.sub(lambda match: " " * len(match[0]), text)
    # A decimal point is not a sentence boundary. Conjunctions isolate subjects.
    start = 0
    for boundary in re.finditer(
        r"[;!?\n]+|\.(?!\d)|\b(?:and(?!\s+\d)|but|va|nhung)\b|$",
        unquoted, flags=re.I,
    ):
        clause = text[start:boundary.start()].strip()
        folded = _fold(unquoted[start:boundary.start()].strip())
        start = boundary.end()
        if not clause:
            continue
        # Conditional scope and examples require semantics this lexer cannot
        # establish. Abstain for the clause on either side of the comparison.
        if _CONTEXT.search(folded):
            continue
        subject = _subject(folded)
        negative = bool(_NEGATIVE.search(folded))
        positive = bool(_POSITIVE.search(_NEGATIVE.sub(" ", folded)))
        if negative != positive:
            claims.append(Claim("polarity", subject, "forbid" if negative else "oblige",
                                None, "", clause))
        # Negated quantities need semantic interpretation; leave them unknown.
        if negative or re.search(r"\b(?:not|no)\b", folded):
            continue
        ranges = list(_RANGE.finditer(folded))
        for match in ranges:
            unit, factor = _UNITS[match["upper_unit"]]
            lower_unit, lower_factor = _UNITS[match["lower_unit"] or match["upper_unit"]]
            lower = Decimal(match["lower"]) * lower_factor
            upper = Decimal(match["upper"]) * factor
            if lower_unit == unit and lower <= upper:
                claims.append(Claim("quantitative", subject or unit.casefold(), "range",
                                    lower, unit, clause, upper))
        for match in _NUMBER_UNIT.finditer(folded):
            if any(r.start() <= match.start() < r.end() for r in ranges):
                continue
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
    when either assertion names a subject. Subject hints must contain one another;
    polarity additionally requires two shared hints.
    """
    req, ev = requirement_claim, evidence_claim
    if req.kind != ev.kind:
        return UNRELATED
    req_subject, ev_subject = set(req.subject_hint.split()), set(ev.subject_hint.split())
    shared = req_subject & ev_subject
    # An added qualifier ("audit logs") can refine a subject ("logs").
    # Shared generic words alone cannot align different subjects or actions.
    aligned = bool(shared) and (req_subject <= ev_subject or ev_subject <= req_subject)
    if req.kind == "polarity":
        if len(shared) < 2 or not aligned:
            return UNRELATED
        return SATISFIES if req.op == ev.op else CONFLICTS
    if req.unit != ev.unit or not aligned:
        return UNRELATED
    if req.op == "range" or ev.op == "range":
        def interval(claim):
            if claim.op == "range":
                return claim.value, claim.upper_value
            if claim.op == ">=":
                return claim.value, Decimal("Infinity")
            if claim.op == "<=":
                return Decimal("-Infinity"), claim.value
            return claim.value, claim.value

        req_lower, req_upper = interval(req)
        ev_lower, ev_upper = interval(ev)
        if ev_upper < req_lower or ev_lower > req_upper:
            return CONFLICTS
        if req_lower <= ev_lower and ev_upper <= req_upper:
            return SATISFIES
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


def assess(requirement_text: str | None, evidence_items: Iterable[Any] | None) -> Assessment:
    """Classify excerpts, preserving input order and original item identity.

    Items may be excerpt strings, mappings, or objects exposing .excerpt. An item
    can both support and conflict; conflicting takes precedence in verdict_hint.
    """
    requirements = extract_claims(requirement_text)
    supporting, conflicting, notes = [], [], []
    for item in evidence_items if evidence_items is not None else ():
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
