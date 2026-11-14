"""Rule-based post-checks for chat answers (no model calls).

G1: drop trailing "no information" filler when the answer already carries real content.
G2: drop sentences whose number+unit does not appear in the evidence used (reuses slot_check).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.review_adapters.citation_check import numbers_in_answer_supported
from app.review_adapters.slot_check import _numbers

_NEGATIVE = re.compile(
    r"(không có thông tin|chưa có thông tin|không tìm thấy|không đề cập|không nêu|không được nêu|"
    r"không có dữ liệu|không rõ|no information|not mentioned|does not mention|doesn't mention|not specified)",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
_BARE_NUMBER = re.compile(r"(?<![\w.])\d{2,}(?:[.,]\d+)?(?![\w])")
_FOOTER = re.compile(r"\n*\s*Nguồn:.*\Z", re.DOTALL)


@dataclass
class GuardResult:
    answer: str
    notes: list[str] = field(default_factory=list)


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text) if part and part.strip()]


_FILLER_START = re.compile(
    r"^(tuy nhiên|ngoài ra|lưu ý|however|note)?[,:]?\s*(không|chưa|no |there is no|not )", re.IGNORECASE)


def drop_trailing_negatives(answer: str) -> tuple[str, int]:
    """Drop 'no information' filler sentences (trailing, or sentences that start with the negation).

    Always keeps at least one sentence; a negation inside a sentence that also carries content is kept.
    """
    sentences = split_sentences(answer)
    kept = list(sentences)
    for index in range(len(sentences) - 1, -1, -1):
        sentence = sentences[index]
        filler = _NEGATIVE.search(sentence) and (index == len(sentences) - 1 or _FILLER_START.match(sentence))
        if filler and len(kept) > 1:
            kept.remove(sentence)
    removed = len(sentences) - len(kept)
    return (" ".join(kept) if removed else answer), removed


def drop_unsupported_numbers(answer: str, evidence_texts: Iterable[str]) -> tuple[list[str], list[str]]:
    """Return (kept sentences, unsupported quantity labels of dropped sentences)."""
    texts = list(evidence_texts)
    kept: list[str] = []
    dropped: list[str] = []
    for sentence in split_sentences(answer):
        bad = [str(slot) for slot in numbers_in_answer_supported(sentence, texts)]
        if not bad and not _numbers(sentence):
            # numbers with units unknown to slot_check (e.g. "500 yêu cầu"): the digits must appear in the evidence
            evidence_digits = {m.group(0).replace(",", ".") for t in texts for m in _BARE_NUMBER.finditer(t)}
            bad = [m.group(0) for m in _BARE_NUMBER.finditer(sentence)
                   if m.group(0).replace(",", ".") not in evidence_digits]
        if bad:
            dropped.extend(bad)
        else:
            kept.append(sentence)
    return kept, dropped


def guard_answer(answer: str, *, status: str, evidence_texts: Iterable[str],
                 source_label: str = "") -> GuardResult:
    """Apply G2 then G1 to an answer WITHOUT its 'Nguồn:' footer."""
    texts = [t for t in evidence_texts if t]
    notes: list[str] = []
    body = _FOOTER.sub("", answer).strip()
    if not body or not texts:
        return GuardResult(answer, notes)
    kept, dropped = drop_unsupported_numbers(body, texts)
    if dropped:
        notes.append("UNSUPPORTED_NUMBER_DROPPED:" + ",".join(dict.fromkeys(dropped)))
        if kept:
            body = " ".join(kept)
        else:
            excerpt = " ".join(texts[0].split())[:220].rstrip()
            where = f" {source_label}" if source_label else ""
            body = f"Mình chưa kiểm chứng được số liệu trong câu trả lời. Đoạn liên quan trong tài liệu{where}: {excerpt}"
            notes.append("ANSWER_REPLACED_BY_EXCERPT")
    if status == "COMPLETE":
        body, removed = drop_trailing_negatives(body)
        if removed:
            notes.append(f"TRAILING_NEGATIVE_DROPPED:{removed}")
    return GuardResult(body, notes)
