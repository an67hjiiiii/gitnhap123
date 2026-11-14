"""Product chat retrieval: multi-idea retrieval (I2), weak-retrieval retry (I1), optional BM25+RRF fusion (I3).

No new subsystem: it composes PipelineRetriever._retrieve_candidates, hybrid.py helpers and at most one extra
model call (query rewrite) per question.
"""
from __future__ import annotations

import asyncio
import os
import re

from app.core.types import RunMetrics, SourceChunk
from app.retrieval.hybrid import bm25_rank, rrf_merge, weakness
from app.retrieval.text import retrieve

_DEPENDENT = re.compile(
    r"(sau đó|rồi (?:thì )?(?:cho|nêu|tính|so sánh)|tiếp theo|dựa (?:trên|vào) (?:đó|kết quả)|nếu .+ thì|"
    r"\bthen\b|after that|based on (?:that|the result))", re.IGNORECASE)
_SPLITTER = re.compile(  # same clause markers as the review auto-route (kept local: core must not import review code)
    r"\s*(?:;|\bvà\b|\bđồng\s+thời\b|\bcũng\s+như\b|\band\b|\bas\s+well\s+as\b)\s*", re.IGNORECASE)
_COMMA_BEFORE_VERB = re.compile(r",\s*(?=(?:phải|cần|được|must|shall|should)\b)", re.IGNORECASE)
_MAX_IDEAS = 4
_MIN_CLAUSE_WORDS = 3


def split_ideas(query: str) -> tuple[list[str], bool]:
    """Return (idea clauses, dependent). Fewer than 2 usable clauses -> ([], False)."""
    text = _COMMA_BEFORE_VERB.sub("; ", query)
    parts = [re.sub(r"^[\s,.;:]+|[\s?!.;,]+$", "", p) for p in _SPLITTER.split(text)]
    # Split only when BOTH sides look like clauses (>= 3 words). This keeps "Research and Development department",
    # "PDF, DOCX và PNG" and similar lists/proper names in one piece.
    if any(len(p.split()) < _MIN_CLAUSE_WORDS for p in parts if p):
        return [], False
    for left, right in zip(parts, parts[1:]):  # "A, B và C": a list, not two clauses
        first = right.split()[0] if right.split() else ""
        if re.search(r",\s*\S{1,15}$", left) and (first.isupper() or first[:1].isdigit()):
            return [], False
    ideas = [p for p in parts if p][:_MAX_IDEAS]
    if len(ideas) < 2:
        return [], False
    return ideas, bool(_DEPENDENT.search(query))


def fusion_mode() -> str:
    return os.getenv("RETRIEVAL_FUSION", "off").strip().lower()


async def rewrite_query(provider, query: str, metrics: RunMetrics) -> str:
    """One call: a keyword-style rewrite with likely synonyms, same language. Falls back to the original."""
    try:
        result = await provider.generate(
            system=("You rewrite a question into a short keyword search query for finding it in internal documents. "
                    "Same language as the question. Add 2-4 likely synonyms or related terms. "
                    "Output ONLY the query on one line."),
            user=query,
        )
        metrics.add_usage(result.usage)
    except Exception:
        metrics.failed_llm_attempts += 1
        return query
    text = " ".join(str(getattr(result, "text", "") or "").split()).strip(" \"'“”")
    return text if text and len(text) <= 3 * len(query) + 160 else query


def run_budget_exceeded(metrics: RunMetrics, cfg, event, step: str) -> bool:
    total = metrics.input_tokens + metrics.output_tokens
    if total >= getattr(cfg, "max_run_tokens", float("inf")):
        event("run_budget_exceeded", total_tokens=total, skipped_step=step)
        return True
    return False


def _base(pipeline, q: str, chunks, cfg, source_ids, top_k: int, trace: dict | None = None) -> list[SourceChunk]:
    return pipeline._retrieve_candidates(
        q, chunks, top_k=top_k, min_score=cfg.retrieval_min_score, source_ids=source_ids, fallback_trace=trace)


def _lists_for(pipeline, q: str, chunks, cfg, source_ids, top_k: int, fusion: str, trace=None) -> list[list[SourceChunk]]:
    lists = [_base(pipeline, q, chunks, cfg, source_ids, top_k, trace)]
    if fusion in {"bm25", "hybrid"}:
        ranked = bm25_rank(q, chunks, top_k=top_k)
        lists += [ranked, ranked]  # BM25 counted twice: measured best of the non-vector rankings (see FE/BE notes)
        if pipeline.candidate_index is not None:
            lists.append(retrieve(q, chunks, top_k=top_k, min_score=cfg.retrieval_min_score))
    return lists


async def product_retrieve(pipeline, provider, metrics: RunMetrics, *, query: str, retrieval_query: str,
                           chunks: list[SourceChunk], cfg, source_ids, trace: dict, event,
                           multi: bool = False, retry: bool = True) -> list[SourceChunk]:
    fusion = fusion_mode()
    top_k = cfg.task_top_k
    ideas, dependent = split_ideas(query) if multi else ([], False)
    if ideas:
        queries = [retrieval_query, *ideas]
        per_idea_k = max(2, cfg.task_top_k // 2)
        event("retrieval.multi", ideas=ideas, dependent=dependent, queries=len(queries))
        per_query = await asyncio.gather(*[
            asyncio.to_thread(_lists_for, pipeline, q, chunks, cfg, source_ids,
                              cfg.task_top_k if i == 0 else per_idea_k, fusion, trace if i == 0 else None)
            for i, q in enumerate(queries)
        ])
        base_list = [c for group in per_query for c in group[0]]  # raw scores of every idea, for the weakness test
        merged = rrf_merge([lst for group in per_query for lst in group], top_k)
    else:
        lists = await asyncio.to_thread(
            _lists_for, pipeline, retrieval_query, chunks, cfg, source_ids, top_k, fusion, trace)
        base_list = lists[0]
        merged = rrf_merge(lists, top_k) if len(lists) > 1 else base_list

    reasons = weakness(query, base_list, min_score=cfg.retrieval_min_score)
    if retry and reasons and os.getenv("RETRIEVAL_RETRY", "0").strip() == "1":
        event("retrieval.retry", phase="start", reasons=reasons)
        rewritten = query if run_budget_exceeded(metrics, cfg, event, "query_rewrite") else await rewrite_query(provider, query, metrics)
        wide = top_k * 2
        extra = await asyncio.to_thread(
            _lists_for, pipeline, rewritten, chunks, cfg, source_ids, wide, "bm25")
        before = {c.chunk_id for c in merged}
        retried = rrf_merge([merged, *extra], wide)
        gained = [c.chunk_id for c in retried if c.chunk_id not in before]
        event("retrieval.retry", phase="end", reasons=reasons, rewritten_query=rewritten, top_k=wide,
              before=len(merged), after=len(retried), gained=gained)
        merged = retried
    return merged
