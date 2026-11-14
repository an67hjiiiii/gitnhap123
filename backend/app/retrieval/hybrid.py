"""Hybrid retrieval helpers: BM25, Reciprocal Rank Fusion, and a rule-based "weak retrieval" test.

All pure functions, no model calls. Used by the product chat path (I1/I2/I3).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

from app.core.types import SourceChunk
from app.retrieval.text import STOP, _stem_token, normalize_text

_TOKEN = re.compile(r"[A-Za-zÀ-ỹ0-9_'-]{2,}")
RRF_K = 60

_QUANTITY_ASK = re.compile(
    r"(bao nhiêu|bao lâu|mấy|how (?:many|much|long|often)|maximum|minimum|tối đa|tối thiểu|"
    r"\bkhi nào\b|lúc mấy|giờ nào|\bwhen\b)", re.IGNORECASE)
_DIGIT = re.compile(r"\d")


def tokens(text: str) -> list[str]:
    return [_stem_token(t) for t in _TOKEN.findall(normalize_text(text).lower()) if t not in STOP]


def bm25_rank(query: str, chunks: Sequence[SourceChunk], top_k: int = 10,
              *, k1: float = 1.5, b: float = 0.75, rel_min: float = 0.4) -> list[SourceChunk]:
    """BM25 over the supplied (already owner-scoped) chunks. Chunks with score 0 are dropped."""
    docs = [(chunk, tokens(chunk.text)) for chunk in chunks]
    if not docs:
        return []
    n = len(docs)
    avg = sum(len(t) for _, t in docs) / n or 1.0
    df: Counter[str] = Counter()
    for _, toks in docs:
        df.update(set(toks))
    q_terms = set(tokens(query))
    scored: list[SourceChunk] = []
    for chunk, toks in docs:
        tf = Counter(toks)
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * len(toks) / avg))
        if score > 0:
            scored.append(SourceChunk(**{**chunk.__dict__, "score": round(score, 6)}))
    scored.sort(key=lambda c: (-(c.score or 0.0), c.chunk_id))
    if scored:  # relative cut: weak partial matches must not enter the fused context as noise
        floor = rel_min * (scored[0].score or 0.0)
        scored = [c for c in scored if (c.score or 0.0) >= floor]
    return scored[:top_k]


def rrf_merge(rankings: Iterable[Sequence[SourceChunk]], top_k: int = 10, *, k: int = RRF_K) -> list[SourceChunk]:
    """Reciprocal Rank Fusion; dedupes by chunk_id. The merged score is the RRF sum, scaled to 0..1 by the best."""
    fused: dict[str, float] = {}
    keep: dict[str, SourceChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            fused[chunk.chunk_id] = fused.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            keep.setdefault(chunk.chunk_id, chunk)
    if not fused:
        return []
    best = max(fused.values())
    order = sorted(fused, key=lambda cid: (-fused[cid], cid))[:top_k]
    return [SourceChunk(**{**keep[cid].__dict__, "score": round(fused[cid] / best, 6)}) for cid in order]


def asks_quantity(query: str) -> bool:
    return bool(_QUANTITY_ASK.search(query))


def weakness(query: str, candidates: Sequence[SourceChunk], *, min_score: float,
             strong_score: float | None = None) -> list[str]:
    """Rule-based reasons why retrieval looks weak (empty list = fine).

    - NO_CANDIDATES: nothing passed the score gate;
    - FEW_STRONG: fewer than 2 chunks pass the gate and even the best one scores below 0.5;
    - MISSING_QUANTITY: the question asks for a number/time/size but no candidate contains a digit.
    """
    reasons: list[str] = []
    if not candidates:
        return ["NO_CANDIDATES"]
    strong = strong_score if strong_score is not None else 0.5
    passing = [c for c in candidates if (c.score or 0.0) >= min_score]
    if len(passing) < 2 and max((c.score or 0.0) for c in candidates) < strong:
        reasons.append("FEW_STRONG")
    if asks_quantity(query) and not any(_DIGIT.search(c.text) for c in candidates):
        reasons.append("MISSING_QUANTITY")
    return reasons
