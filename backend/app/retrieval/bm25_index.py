"""Bounded corpus cache for deterministic, owner-scoped BM25 statistics."""
from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass

from app.retrieval.text import content_hash, contextual_text


@dataclass(frozen=True)
class Bm25Index:
    postings: dict[str, dict[str, int]]
    lengths: dict[str, int]
    df: Counter
    avg_length: float
    size: int
    headers: tuple


_CACHE: OrderedDict = OrderedDict()


def get_index(chunks) -> Bm25Index:
    # Recompute hashes: callers can supply mutable or legacy provenance.
    key = tuple(sorted((c.chunk_id, content_hash(c.text)) for c in chunks))
    headers = tuple(sorted((c.chunk_id, c.provenance.get("context_header", "")) for c in chunks))
    cached = _CACHE.get(key)
    if cached is not None and cached.headers == headers:
        _CACHE.move_to_end(key)
        return cached
    from app.retrieval.hybrid import tokens

    postings: dict[str, dict[str, int]] = {}
    lengths: dict[str, int] = {}
    df: Counter = Counter()
    for chunk in chunks:
        corpus_tokens = tokens(contextual_text(chunk))
        lengths[chunk.chunk_id] = len(corpus_tokens)
        counts = Counter(corpus_tokens)
        df.update(counts.keys())
        for term, count in counts.items():
            postings.setdefault(term, {})[chunk.chunk_id] = count
    size = len(chunks)
    index = Bm25Index(postings, lengths, df,
                      (sum(lengths.values()) / size or 1.0) if size else 1.0,
                      size, headers)
    _CACHE[key] = index
    _CACHE.move_to_end(key)
    if len(_CACHE) > 32:
        _CACHE.popitem(last=False)
    return index
