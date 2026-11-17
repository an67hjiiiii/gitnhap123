"""Pure, deterministic article/clause comparison and quick-question intent."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
import unicodedata


def canonical(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).casefold()).strip()


def diff_intent(query: str) -> str | None:
    text = canonical(query)
    if not re.search(r"so sánh|so với|thay đổi|khác nhau|điểm mới|\bthêm\b|\bbỏ\b|\bmới\b", text):
        return None
    if re.search(r"\b(?:bị )?bỏ\b", text) and not re.search(r"so sánh|so với|thay đổi|khác nhau|thêm|mới", text):
        return "BO"
    if re.search(r"điểm mới|\bthêm\b", text) and not re.search(r"so sánh|so với|thay đổi|khác nhau|\bbỏ\b", text):
        return "THEM"
    if "mới" in text and not re.search(r"so sánh|so với|thay đổi|khác nhau|\bbỏ\b", text):
        return "NEW"
    return "ALL"


_QUANTITY = re.compile(
    r"(?<!\w)(\d+(?:[.,]\d+)?|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười)\s*"
    r"(yêu cầu\s*(?:mỗi\s+|/\s*)phút|ký tự|mật khẩu|phút|giờ|tháng|năm|ngày|%|lần)(?!\w)")
_WORDS = dict(zip("một hai ba bốn năm sáu bảy tám chín mười".split(), range(1, 11)))


def atoms(text: str) -> list[str]:
    text = canonical(text)
    result = set()
    def calendar(match):
        try:
            result.add(date(int(match[3]), int(match[2]), int(match[1])).isoformat())
        except ValueError:
            result.add(match[0])
        return " "
    text = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", calendar, text)
    def quantity(match):
        raw, unit = match.groups()
        number = Decimal(_WORDS[raw]) if raw in _WORDS else Decimal(raw.replace(",", "."))
        if unit == "giờ":
            number, unit = number * 60, "phút"
        elif unit == "năm":
            number, unit = number * 12, "tháng"
        elif unit.startswith("yêu cầu"):
            unit = "yêu cầu/phút"
        value = format(number.normalize(), "f")
        result.add(f"{value} {unit}")
        return " "
    text = _QUANTITY.sub(quantity, text)
    # Keep standalone statutory values (HTTP codes, counts without a listed unit).
    result.update(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", text))
    result.update(re.findall(r"không được|bắt buộc|khuyến khích|có thể|phải|được", text))
    return sorted(result)


@dataclass(frozen=True)
class Article:
    label: str
    title: str
    clauses: tuple[tuple[str, str], ...]


def articles(text: str) -> list[Article]:
    text = unicodedata.normalize("NFC", text)
    headings = list(re.finditer(r"^[ \t]*Điều\s+(\d+[a-zđ]?)\s*[.:]\s*([^\n]*)", text, re.M | re.I))
    result = []
    for i, heading in enumerate(headings):
        body = text[heading.end():headings[i + 1].start() if i + 1 < len(headings) else len(text)].strip()
        markers = list(re.finditer(r"^\s*(\d+)\s*[.)]\s+", body, re.M))
        clauses = []
        if markers:
            prefix = body[:markers[0].start()].strip()
            if prefix:
                clauses.append(("0", prefix))
            for j, marker in enumerate(markers):
                value = body[marker.end():markers[j + 1].start() if j + 1 < len(markers) else len(body)].strip()
                clauses.append((marker[1], value))
        else:
            clauses = [("1", body)]
        result.append(Article("Điều " + heading[1], heading[2].strip(), tuple(clauses)))
    return result


def compare_units(old: str, new: str, pair: str = "") -> list[dict]:
    """Include unchanged units internally so equivalence answers have both texts."""
    before, after = articles(old), articles(new)
    matched = {}
    used = set()
    # Title first: a renumbered article must not be paired with its old number.
    for i, a in enumerate(before):
        candidates = [j for j, b in enumerate(after) if j not in used and canonical(a.title).rstrip(".:") == canonical(b.title).rstrip(".:")]
        if candidates:
            j = min(candidates, key=lambda j: after[j].label != a.label)
            matched[i] = j
            used.add(j)
    result = []
    def emit(a, b, x, y, kind):
        result.append(dict(pair=pair, old_article=a.label if a else None,
                           new_article=b.label if b else None, kind=kind,
                           atoms_before=atoms(x[1]) if x else [], atoms_after=atoms(y[1]) if y else [],
                           text_before=(a.title + "\n" + x[1]) if a and x else "",
                           text_after=(b.title + "\n" + y[1]) if b and y else "",
                           old_clause=x[0] if x else None, new_clause=y[0] if y else None))
    for i, a in enumerate(before):
        if i not in matched:
            for x in a.clauses:
                emit(a, None, x, None, "BO")
            continue
        b = after[matched[i]]
        remaining = list(b.clauses)
        pairs = []
        # Exact text first allows clause renumbering and insertion.
        for x in a.clauses:
            y = next((y for y in remaining if canonical(x[1]) == canonical(y[1])), None)
            if y:
                remaining.remove(y)
            pairs.append([x, y])
        for entry in pairs:
            x, y = entry
            if y is None:
                y = next((y for y in remaining if x[0] == y[0]), None)
                if y:
                    remaining.remove(y)
            kind = "BO" if y is None else ("DOI" if atoms(x[1]) != atoms(y[1]) else None)
            emit(a, b if y else None, x, y, kind)
        for y in remaining:
            emit(None, b, None, y, "THEM")
    for j, b in enumerate(after):
        if j not in used:
            for y in b.clauses:
                emit(None, b, None, y, "THEM")
    return result


OUTPUT_FIELDS = ("pair", "old_article", "new_article", "kind", "atoms_before", "atoms_after")


def diff_versions(old: str, new: str, pair: str = "", *, include_text: bool = False) -> list[dict]:
    return [row if include_text else {key: row[key] for key in OUTPUT_FIELDS}
            for row in compare_units(old, new, pair) if row["kind"]]


_STOP = set("chính sách có gì nào không đổi nội dung về so sánh thay khác nhau điểm mới thêm bị bỏ giữa các bản và với trước sau trong của mục một những đã còn hay như thế nào tài liệu quy định được phải là không thể cho biết ở v1 v2".split())


def topic_units(query: str, units: list[dict], *, family_label: str = "") -> list[dict]:
    """Select the most specific item mentioned; no topic means all items."""
    query = canonical(query)
    query = query.replace("thời gian", " ")
    ref = re.search(r"điều\s+(\d+[a-zđ]?)(?:[.\s]+(?:khoản\s*)?(\d+))?", query)
    if ref:
        selected = [r for r in units if f"Điều {ref[1]}" in (r["old_article"], r["new_article"])
                    and (not ref[2] or ref[2] in (r.get("old_clause"), r.get("new_clause")))]
        return selected
    # Family terms identify the policy, not a particular clause within it.
    label = canonical(family_label).split(" và ")[0]
    if "chính sách" in query:
        # Remove only the named policy phrase, preserving a separately named item.
        query = query.replace(label, " ")
        if "api" in label:
            query = re.sub(r"chính sách\s+(?:sử dụng\s+)?api", " ", query)
    tokens = set(re.findall(r"\w+", query)) - _STOP
    family_tokens = set(re.findall(r"\w+", label)) - _STOP
    if tokens <= family_tokens:
        tokens = set()
    if not tokens:
        return units
    scored = [(len(tokens & set(re.findall(r"\w+", canonical(r["text_before"] + " " + r["text_after"])))), r) for r in units]
    best = max((score for score, _ in scored), default=0)
    return [row for score, row in scored if score == best] if best else []
