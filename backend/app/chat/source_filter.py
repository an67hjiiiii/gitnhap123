"""Keep only the sources the delivered answer actually uses (no extra model call).

A source is used when at least one answer sentence matches its chunk: every number of the sentence appears in the
chunk and they share enough keywords (3+ characters). Sources the body already cites with [n] are always kept.
If the filter would leave nothing for an answer that has sources, the original list is kept.
"""
from __future__ import annotations

import re
import unicodedata

from app.chat.answer_guard import split_sentences

_STOP = frozenset("theo tai lieu duoc cac nhung trong khong mot cua nay khi sau and the for with from".split())
_MARK = re.compile(r"\[(\d+)\]")


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                   if unicodedata.category(c) != "Mn").replace("đ", "d")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", _fold(text)) if w not in _STOP and not w.isdigit()}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def sentence_matches(sentence: str, chunk_text: str) -> bool:
    numbers = _numbers(sentence)
    if numbers and not numbers <= _numbers(chunk_text):
        return False
    shared = len(_words(sentence) & _words(chunk_text))
    return shared >= (1 if numbers else 2)


def filter_sources(answer: str, sources: list[dict], chunk_text) -> tuple[str, list[dict], list[dict]]:
    """Return (answer with renumbered [n], kept sources, dropped [{n, doc_name, reason}]).

    `chunk_text(chunk_id)` returns the full chunk text (or "")."""
    if len(sources) < 1 or not answer:
        return answer, sources, []
    sentences = [_MARK.sub("", s) for s in split_sentences(answer)]
    cited = {int(m) for m in _MARK.findall(answer)}
    keep, dropped = [], []
    for source in sources:
        text = chunk_text(source["chunk_id"]) or source.get("snippet", "")
        if source["n"] in cited or any(sentence_matches(s, text) for s in sentences):
            keep.append(source)
        else:
            dropped.append({"n": source["n"], "doc_name": source["doc_name"], "reason": "no answer sentence matches the chunk"})
    if not keep:  # never leave a grounded answer without a source
        return answer, sources, []
    if len(keep) == len(sources):
        return answer, sources, []
    mapping = {s["n"]: i for i, s in enumerate(keep, 1)}
    body = _MARK.sub(lambda m: f"[{mapping[int(m.group(1))]}]" if int(m.group(1)) in mapping else "", answer)
    return body, [{**s, "n": mapping[s["n"]]} for s in keep], dropped
