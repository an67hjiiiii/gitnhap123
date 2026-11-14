"""Deterministic value coverage over cited excerpts, not semantic entailment.

Units use fixed conversions (30 days/month, 365 days/year, decimal byte sizes).
Single title-case words at sentence starts are ambiguous and are ignored; internal
capitalized words, multiword names, acronyms and identifiers are lexical entities.
Quoted values are literals. Matching is case-insensitive, preserves accents for
names/literals, and never joins excerpts to manufacture a match. Subjects,
negation, paraphrases and implicit facts are deliberately outside this check.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata
from collections.abc import Iterable


def _text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                   if unicodedata.category(c) != "Mn").replace("đ", "d")


# Alias -> display unit, comparison dimension, multiplier.
_UNITS = {}
for _aliases, _unit, _dimension, _factor in (
    ("second seconds sec secs giay", "seconds", "seconds", 1),
    ("minute minutes min mins phut", "minutes", "seconds", 60),
    ("hour hours hr hrs gio", "hours", "seconds", 3600),
    ("day days ngay", "days", "seconds", 86400),
    ("week weeks tuan", "weeks", "seconds", 604800),
    ("month months thang", "months", "seconds", 2592000),
    ("year years nam", "years", "seconds", 31536000),
    ("% percent percentage", "%", "%", 1),
    ("byte bytes", "bytes", "bytes", 1),
    ("kb kilobyte kilobytes", "KB", "bytes", 1000),
    ("mb megabyte megabytes", "MB", "bytes", 1000000),
    ("gb gigabyte gigabytes", "GB", "bytes", 1000000000),
    ("character characters ky tu", "characters", "characters", 1),
    ("attempt attempts time times lan", "times", "times", 1),
):
    # The Vietnamese unit "ky tu" contains a space.
    for _alias in (_aliases.split() if _unit != "characters"
                   else ["character", "characters", "ky tu"]):
        _UNITS[_alias] = (_unit, _dimension, _factor)

_NUMBER = re.compile(
    r"(?<![\w.,:+-])(?P<value>\d+(?:[.,]\d+)*)\s*(?P<unit>"
    + "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
    + r")(?!\w)", re.I,
)
_QUOTED = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|`([^`\n]+)`|(?<!\w)\x27([^\x27\n]+)\x27')
_PATH = re.compile(r"(?<![\w/])/(?:[\w{}.-]+/)*[\w{}.-]+/?")
_TOKEN = re.compile(r"[^\W_][\w]*(?:[-.:][\w]+)*", re.UNICODE)
_GRAMMAR = set("a an the all each every this that these those how which what where "
               "when why must should shall use require requires ensure support "
               "supporting please".split())


@dataclass(frozen=True)
class Slot:
    kind: str
    value: str
    unit: str = ""

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}{' ' + self.unit if self.unit else ''}"


def _decimal(value: str) -> Decimal:
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", value):
        value = value.replace(",", "")
    else:
        value = value.replace(",", ".")
    return Decimal(value)


def _numbers(text: str) -> list[Slot]:
    slots = []
    for match in _NUMBER.finditer(_fold(text)):
        value = match["value"]
        # Multiple decimal separators are not a number understood by this lexer.
        if value.count(".") > 1 or ("," in value and "." not in value
                                    and value.count(",") > 1
                                    and not re.fullmatch(r"\d{1,3}(?:,\d{3})+", value)):
            continue
        if "," in value and "." in value and not re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d+", value):
            continue
        slots.append(Slot("number", format(_decimal(value).normalize(), "f"),
                          _UNITS[match["unit"]][0]))
    return slots


def _quantity_key(slot: Slot) -> tuple[str, Decimal]:
    _, dimension, factor = _UNITS[slot.unit.casefold()]
    return dimension, Decimal(slot.value) * factor


def extract_slots(text: str) -> tuple[Slot, ...]:
    """Return deduplicated, stable slot strings in literal/number/entity order."""
    text = unicodedata.normalize("NFC", text)
    slots = []
    masked = list(text)
    for match in _QUOTED.finditer(text):
        value = next(group for group in match.groups() if group is not None)
        if value.strip():
            slots.append(Slot("literal", _text(value)))
        masked[match.start():match.end()] = " " * len(match[0])
    unquoted = "".join(masked)
    slots.extend(_numbers(unquoted))
    # Unit words such as MB and Days are quantities, not additional entities.
    unit_words = {word for alias in _UNITS for word in alias.split()}
    for match in _PATH.finditer(unquoted):
        value = match[0].rstrip(".")
        slots.append(Slot("entity", _text(value)))
        masked[match.start():match.end()] = " " * len(match[0])
    tokens = list(_TOKEN.finditer("".join(masked)))
    names: list[str] = []

    def flush() -> None:
        if names:
            slots.append(Slot("entity", _text(" ".join(names))))
            names.clear()

    for index, match in enumerate(tokens):
        word = match[0]
        if index and unquoted[tokens[index - 1].end():match.start()].strip():
            flush()
        folded = _fold(word)
        identifier = (any(c.isalpha() for c in word) and (
            any(c.isdigit() for c in word) or "_" in word
            or any(c.isupper() for c in word[1:])
        ))
        capitalized = word[0].isupper() and (folded not in _GRAMMAR or bool(names))
        if folded in unit_words or not (identifier or capitalized):
            flush()
            continue
        sentence_start = bool(re.search(r"(?:^|[.!?\n])\s*$", unquoted[:match.start()]))
        next_word = tokens[index + 1][0] if index + 1 < len(tokens) else ""
        next_is_name = (bool(next_word) and next_word[0].isupper()
                        and _fold(next_word) not in unit_words | _GRAMMAR
                        and not unquoted[match.end():tokens[index + 1].start()].strip())
        if capitalized and sentence_start and not identifier and not next_is_name:
            flush()
            continue
        names.append(word)
    flush()
    return tuple(dict.fromkeys(slots))


@dataclass(frozen=True)
class SlotCoverage:
    slots: tuple[Slot, ...]
    missing_slots: tuple[str, ...]

    @property
    def any_covered(self) -> bool:
        return len(self.missing_slots) < len(self.slots)


def check_slots(requirement: str, evidence_texts: Iterable[str]) -> SlotCoverage:
    """Check each value against individual cited chunks, allowing union coverage."""
    slots = extract_slots(requirement)
    excerpts = tuple(evidence_texts)
    quantities = {_quantity_key(slot) for text in excerpts for slot in _numbers(text)}
    missing = []
    for slot in slots:
        if slot.kind == "number":
            covered = _quantity_key(slot) in quantities
        else:
            # Word boundaries prevent ERR_40 matching ERR_401 or /v1 matching /v10.
            pattern = r"(?<![\w/.-])" + re.escape(slot.value) + r"(?![\w/-]|\.[\w])"
            covered = any(re.search(pattern, _text(text)) for text in excerpts)
        if not covered:
            missing.append(str(slot))
    return SlotCoverage(slots, tuple(missing))
