"""Deterministic value coverage over cited excerpts, not semantic entailment.

Units use fixed conversions plus calendar-year and binary-byte aliases.
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

# Closed vocabulary, scoped to phrases immediately preceding a known unit.
_WORDS = {}
_EN_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_EN_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_VI_ONES = "khong mot hai ba bon nam sau bay tam chin".split()
for _n in range(101):
    if _n < 20:
        _WORDS[_EN_ONES[_n]] = str(_n)
    elif _n < 100:
        _tens = _EN_TENS[_n // 10 - 2]
        _WORDS[_tens + (" " + _EN_ONES[_n % 10] if _n % 10 else "")] = str(_n)
    else:
        _WORDS["one hundred"] = "100"
    if _n < 10:
        _WORDS[_VI_ONES[_n]] = str(_n)
    elif _n < 100:
        _prefix = "muoi" if _n < 20 else _VI_ONES[_n // 10] + " muoi"
        _tail = _VI_ONES[_n % 10]
        _WORDS[_prefix + (" " + _tail if _n % 10 else "")] = str(_n)
        if _n % 10 == 5:
            _WORDS[_prefix + " lam"] = str(_n)
        if _n > 20 and _n % 10 == 4:
            _WORDS[_prefix + " tu"] = str(_n)
    else:
        _WORDS["mot tram"] = "100"
_WORD_NUMBER = re.compile(
    r"(?<![\w-])(?:" + "|".join(
        re.escape(word).replace(r"\ ", r"[\s-]+")
        for word in sorted(_WORDS, key=len, reverse=True)
    ) + r")(?=\s*(?:" + "|".join(
        re.escape(unit) for unit in sorted(_UNITS, key=len, reverse=True)
    ) + r")(?!\w))"
)


def _replace_number_words(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    # Casefold may expand a character (e.g. sharp S); preserve original offsets.
    folded = "".join(_fold(char) for char in text)
    offsets = [index for index, char in enumerate(text) for _ in _fold(char)]
    for match in reversed(list(_WORD_NUMBER.finditer(folded))):
        word = re.sub(r"[\s-]+", " ", match[0])
        start, end = offsets[match.start()], offsets[match.end() - 1] + 1
        text = text[:start] + _WORDS[word] + text[end:]
    return text

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
    alternatives: tuple[str, ...] = ()

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
    for match in _NUMBER.finditer(_fold(_replace_number_words(text))):
        value = match["value"]
        # Multiple decimal separators are not a number understood by this lexer.
        if value.count(".") > 1 or ("," in value and "." not in value
                                    and value.count(",") > 1
                                    and not re.fullmatch(r"\d{1,3}(?:,\d{3})+", value)):
            continue
        if "," in value and "." in value and not re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d+", value):
            continue
        slots.append(Slot("number", format(_decimal(value).normalize(), "f"),
                          _UNITS[match["unit"]][0],
                          (value.replace(".", ""),) if re.fullmatch(r"\d+\.\d{3}", value) else ()))
    return slots


def _quantity_key(slot: Slot) -> tuple[str, Decimal]:
    _, dimension, factor = _UNITS[slot.unit.casefold()]
    return dimension, Decimal(slot.value) * factor


def _quantity_keys(slot: Slot) -> set[tuple[str, Decimal]]:
    """Independent accepted readings; never chain ambiguous conversions."""
    keys = {_quantity_key(slot)}
    for value in (slot.value, *slot.alternatives):
        quantity = Decimal(value)
        _, dimension, factor = _UNITS[slot.unit.casefold()]
        keys.add((dimension, quantity * factor))
        if slot.unit in {"months", "years"}:
            keys.add(("calendar_months", quantity * (12 if slot.unit == "years" else 1)))
        if slot.unit in {"KB", "MB", "GB"}:
            keys.add(("bytes", quantity * 1024 ** {"KB": 1, "MB": 2, "GB": 3}[slot.unit]))
    return keys


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
    unquoted = _replace_number_words("".join(masked))
    masked = list(unquoted)
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
    quantities = {key for text in excerpts for slot in _numbers(text) for key in _quantity_keys(slot)}
    missing = []
    for slot in slots:
        if slot.kind == "number":
            covered = bool(_quantity_keys(slot) & quantities)
        else:
            # Word boundaries prevent ERR_40 matching ERR_401 or /v1 matching /v10.
            pattern = r"(?<![\w/.-])" + re.escape(slot.value) + r"(?![\w/-]|\.[\w])"
            covered = any(re.search(pattern, _text(text)) for text in excerpts)
        if not covered:
            missing.append(str(slot))
    return SlotCoverage(slots, tuple(missing))
