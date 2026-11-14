"""Conservative lexical verdict rules; no provider or storage dependencies.

Durations use minutes (365 days/year, 30 days/month); sizes use decimal MB.
These are explicit fixed conversions, not calendar arithmetic. Subjects are
lexical hints, not parsed entities; synonyms and implicit obligations are unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    conflicts_data: list[dict] = field(default_factory=list)


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
    supporting, conflicting, notes, conflicts_data = [], [], [], []
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
                    conflicts_data.append({
                        "requirement": {"span": req.span, "op": req.op,
                                         "value": str(req.value), "unit": req.unit},
                        "evidence": {"span": ev.span, "op": ev.op,
                                     "value": str(ev.value), "unit": ev.unit},
                    })
                    notes.append(f"Conflicting claim: requirement [{req.span}] ({req.op} "
                                 f"{req.value} {req.unit}); evidence [{ev.span}] "
                                 f"({ev.op} {ev.value} {ev.unit}).")
        if CONFLICTS in outcomes:
            conflicting.append(item)
        if SATISFIES in outcomes:
            supporting.append(item)
    hint = "DEVIATES" if conflicting else SATISFIES if supporting else UNRELATED
    return Assessment(hint, supporting, conflicting, notes, conflicts_data)


@dataclass(frozen=True)
class AnswerCheck:
    status: str
    notes: list[str]
    unsupported: list[dict] = field(default_factory=list)


# Separate from the evidence lexer: malformed numeric tokens must stay whole,
# rather than letting e.g. the trailing "00 minutes" in "3:00 minutes" match.
_ANSWER_UNITS = {**_UNITS, "seconds": ("seconds", 1), "second": ("seconds", 1),
                 "giay": ("seconds", 1)}
_ANSWER_QUANTITY = re.compile(
    r"(?<![\w.,:+-])(?P<number>[+-]?\d+(?:[.,:]\d+)*)(?:\s*)"
    r"(?P<unit>" + "|".join(re.escape(u) for u in sorted(_ANSWER_UNITS, key=len, reverse=True))
    + r")(?!\w)"
)
_CHANNELS = {"email", "e-mail", "sms", "mms", "push", "slack", "teams", "webhook",
             "whatsapp", "telegram", "zalo"}
_ANSWER_ALTERNATIVE = re.compile(
    r"(?=\b(?P<base>[\w-]+)\s+(?i:and(?:/or)?|và|va)\s+(?P<extra>[\w-]+)"
    r"(?=\s*(?:[,;.!?\n]|$|\b(?i:and|or|và|va|hoặc)\b)))"
)


def _answer_clauses(text: str) -> list[str]:
    # Quoted mentions, examples, conditionals and negations are not clear claims.
    unquoted = _QUOTED.sub(" ", text)
    clauses = re.split(r"[;!?\n]+|\.(?!\d)", unquoted)
    return [clause for clause in clauses if clause.strip() and not (
        _CONTEXT.search(_fold(clause))
        or re.search(r"\b(?:not|no|never|khong)\b", _fold(clause))
    )]


def _answer_subject(text: str) -> set[str]:
    return set(_subject(_ANSWER_QUANTITY.sub(" ", _fold(text))).split())


def _answer_quantities(text: str) -> list[tuple[str, Decimal | str, str]]:
    quantities = []
    for match in _ANSWER_QUANTITY.finditer(_fold(text)):
        number = match["number"]
        unit, factor = _ANSWER_UNITS[match["unit"]]
        # A comma decimal is common in Vietnamese; conventional comma grouping
        # is unambiguous here. Other malformed formats remain distinct literals.
        if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", number):
            number = number.replace(",", "")
        elif re.fullmatch(r"[+-]?\d+,\d+", number):
            number = number.replace(",", ".")
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", number):
            value = Decimal(number) * factor
            if unit == "minutes":
                value *= 60
                unit = "seconds"
        else:
            value = "literal:" + number
        quantities.append((unit, value, match[0]))
    return quantities


def check_answer(
    requirement_text: str | None, answer_text: str | None,
    evidence_items: Iterable[Any] | None,
) -> AnswerCheck:
    """Check explicit answer quantities and narrow channel-list additions.

    Only lexically aligned subjects are checked. Quantity support may come from
    the requirement or any excerpt; channel additions need an excerpt. UNKNOWN
    means this small lexer cannot establish a comparable assertion, not failure.
    This check never changes the evidence assessment or infers semantic conflict.
    """
    if not isinstance(requirement_text, str) or not isinstance(answer_text, str):
        return AnswerCheck("UNKNOWN", [])
    requirements = _answer_clauses(requirement_text)
    answers = _answer_clauses(answer_text)
    excerpts = []
    for item in evidence_items if evidence_items is not None else ():
        excerpt = item if isinstance(item, str) else (
            item.get("excerpt", "") if isinstance(item, dict) else getattr(item, "excerpt", "")
        )
        if isinstance(excerpt, str) and excerpt.strip():
            excerpts.append(excerpt)
    if not requirements or not answers or not excerpts:
        return AnswerCheck("UNKNOWN", [])
    supported = {(unit, value) for text in [requirement_text, *excerpts]
                 for unit, value, _ in _answer_quantities(text)}
    evidence_tokens = set(re.findall(r"[\w-]+", _fold(" ".join(excerpts))))
    subjects = [_answer_subject(text) for text in requirements]
    notes, unsupported = [], []
    checked = False
    for clause in answers:
        subject = _answer_subject(clause)
        if not any(subject & req and (subject <= req or req <= subject) for req in subjects):
            continue
        for part in re.split(r"\b(?:and(?!\s+\d)|but|va(?!\s+\d)|nhung)\b", _fold(clause)):
            part_subject = _answer_subject(part)
            if not any(part_subject & req and (part_subject <= req or req <= part_subject)
                       for req in subjects):
                continue
            for unit, value, span in _answer_quantities(part):
                checked = True
                if (unit, value) not in supported:
                    unsupported.append({"kind": "quantity", "span": span,
                                        "unit": unit, "value": str(value)})
                    notes.append(f"Unsupported answer quantity [{span}] for requirement "
                                 f"[{requirement_text}]; absent from requirement and evidence excerpts.")
        for match in _ANSWER_ALTERNATIVE.finditer(clause):
            extra = match["extra"]
            if _fold(match["base"]) not in _CHANNELS:
                continue
            if _fold(extra) not in _CHANNELS and not extra[0].isupper():
                continue
            checked = True
            if _fold(extra) not in evidence_tokens:
                unsupported.append({"kind": "alternative", "value": extra})
                notes.append(f"Unsupported answer alternative [{extra}]; "
                             "absent from evidence excerpts.")
        if subject and subject <= set(_subject(_fold(" ".join(excerpts))).split()):
            checked = True
        if _CHANNELS & evidence_tokens & set(re.findall(r"[\w-]+", _fold(clause))):
            checked = True
    return AnswerCheck("UNSUPPORTED_CLAIM" if notes else "CONSISTENT" if checked else "UNKNOWN",
                       notes, unsupported)
