"""Pure, conservative query normalization; no model calls or environment reads."""
from __future__ import annotations

import re
import unicodedata

_RESTORE = {
    "mat khau": "mật khẩu", "dang nhap": "đăng nhập", "nhat ky": "nhật ký",
    "thong tu": "thông tư", "hieu luc": "hiệu lực", "tuyen sinh": "tuyển sinh",
    "nghi dinh": "nghị định", "quyet dinh": "quyết định", "het han": "hết hạn",
    "het hieu luc": "hết hiệu lực", "giao vien": "giáo viên", "sinh vien": "sinh viên",
    "dai hoc": "đại học", "sau dai hoc": "sau đại học", "tai khoan": "tài khoản",
    "bao mat": "bảo mật", "nua gio": "nửa giờ",
}
_ABBREVIATIONS = {
    "tt": "thông tư", "nđ": "nghị định", "qđ": "quyết định",
    "bgdđt": "bộ giáo dục và đào tạo", "gv": "giáo viên", "sv": "sinh viên",
    "đh": "đại học", "sđh": "sau đại học", "mk": "mật khẩu",
}
# Minimal alias table copied from review_adapters/slot_check.py::_UNITS.
# Importing that adapter is forbidden by the Core pipeline layers contract.
# Canonical Vietnamese spellings keep query text useful for Vietnamese retrieval.
_UNIT_GROUPS = (
    ("second seconds sec secs giay giây", "giây"),
    ("minute minutes min mins phut phút", "phút"),
    ("hour hours hr hrs gio giờ", "giờ"),
    ("day days ngay ngày", "ngày"), ("week weeks tuan tuần", "tuần"),
    ("month months thang tháng", "tháng"), ("year years nam năm", "năm"),
    ("percent percentage %", "%"), ("byte bytes", "bytes"),
    ("kb kilobyte kilobytes", "kb"), ("mb megabyte megabytes", "mb"),
    ("gb gigabyte gigabytes", "gb"), ("character characters", "ký tự"),
    ("attempt attempts time times lan lần", "lần"),
)
_UNITS = {alias: canonical for aliases, canonical in _UNIT_GROUPS for alias in aliases.split()}
_UNITS.update({"ky tu": "ký tự", "ký tự": "ký tự"})
_ONES = "không một hai ba bốn năm sáu bảy tám chín".split()
_NUMBERS = {word: str(i) for i, word in enumerate(_ONES)}
_NUMBERS["mười"] = "10"
for _i in range(11, 100):
    _prefix = "mười" if _i < 20 else _ONES[_i // 10] + " mươi"
    _tail = "lăm" if _i % 10 == 5 else "mốt" if _i > 20 and _i % 10 == 1 else _ONES[_i % 10]
    _NUMBERS[_prefix + (" " + _tail if _i % 10 else "")] = str(_i)
_NUMBERS["một trăm"] = "100"
_DOCUMENT = re.compile(r"(?<!\w)\d+/\d{4}/[^\W_]+(?:[-/][^\W_]+)*(?!\w)")


def _pattern(mapping):
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r")(?!\w)")


def _sub(text, mapping):
    return _pattern(mapping).sub(lambda m: mapping[m[0]], text)


def normalize_query(text: str) -> tuple[str, list[str]]:
    """Return canonical text and ordered names of transformations that changed it.

    Restore only whole phrases from a closed vocabulary when >=60% of word
    tokens are ASCII (a conservative proxy for missing Vietnamese diacritics).
    Number words are recognized before units or as a complete query, avoiding
    ambiguous prose such as 'năm học' and 'không đăng nhập'. Synonyms are added
    once, preserving both expiry phrases rather than equating legal meanings.
    """
    changes: list[str] = []
    def changed(before, after, label):
        if before != after:
            changes.append(label)
        return after

    text = changed(text, unicodedata.normalize("NFC", text), "unicode_nfc")
    text = changed(text, " ".join(text.split()), "whitespace")
    # Normalize ordinary text around document references; preserve their spelling.
    parts = re.split("(" + _DOCUMENT.pattern + ")", text)
    lowered = "".join(part if _DOCUMENT.fullmatch(part) else part.lower() for part in parts)
    text = changed(text, lowered, "case")
    documents = []
    def protect(m):
        documents.append(m[0])
        return f"\ue000{len(documents)-1}\ue001"
    text = _DOCUMENT.sub(protect, text)
    words = re.findall(r"[^\W\d_]+", text)
    if words and sum(w.isascii() for w in words) / len(words) >= .6:
        text = changed(text, _sub(text, _RESTORE), "diacritics")
    text = changed(text, _sub(text, _ABBREVIATIONS), "abbreviations")
    text = changed(text, re.sub(r"(?<!\w)nửa(?= giờ(?!\w))", "0,5", text), "half_hour")
    unit_pattern = _pattern(_UNITS).pattern
    number_pattern = re.compile(_pattern(_NUMBERS).pattern + r"(?=\s*(?:" + unit_pattern + r"))")
    numbered = _NUMBERS[text] if text in _NUMBERS else number_pattern.sub(lambda m: _NUMBERS[m[0]], text)
    text = changed(text, numbered, "number_words")
    units = re.compile(r"(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>" + unit_pattern + ")")
    text = changed(text, units.sub(lambda m: m['number'] + " " + _UNITS[m['unit']], text), "units")
    # Expiry of credentials and legal loss of effect remain separate concepts.
    for phrase, addition in (("hết hạn", "quá hạn"), ("hết hiệu lực", "không còn hiệu lực")):
        if re.search(r"(?<!\w)" + phrase + r"(?!\w)", text) and addition not in text:
            text += " (" + addition + ")"
            if "synonyms" not in changes:
                changes.append("synonyms")
    for i, document in enumerate(documents):
        text = text.replace(f"\ue000{i}\ue001", document)
    return text, changes
