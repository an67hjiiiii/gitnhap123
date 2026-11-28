"""Targeted Evidence Completeness Recovery (B139.2 Phase E).

Zero Ollama / zero embedding calls: recovers unretrieved mandatory rule or continuation
chunks (such as mid-chunk rules buried below non-matching headings) strictly within
authorized `allowed_source_ids` and token budget, preserving already-selected chunks.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.core.types import SourceChunk
from app.retrieval.hybrid import _needs_next_continuation, bm25_scores, fold
from app.retrieval.text import estimate_tokens

_RULE_FACET_PAT = re.compile(
    r"\b(?:noi quy|quy dinh|hop le|du dieu kien|nghi phep|ban giao|phe duyet|tham quyen|cao diem|hieu luc|chiet khau|uu dai|giam gia|lam them|tang ca|luong|bao truoc|bang gia|tong tien|tong chi phi|chi phi|trien khai|bao hiem|khoi tao)\b",
    re.I,
)
_MID_HEADING_TAIL = re.compile(r"#+\s*(?:Điều|Mục|Chương|Article|Section)\s+\d+", re.I)


def _query_facet_terms(query: str) -> str:
    """Extract focused rule & operand search cues without proper-noun bloat starving mandatory clauses."""
    q_fold = fold(query or "")
    hits = _RULE_FACET_PAT.findall(q_fold)
    # Include explicitly cited article/clause numbers (e.g. Điều 9.1, 9.2) for contract review queries
    art_refs = re.findall(r"\bdieu\s+\d+(?:\.\d+)?\b", q_fold)
    if art_refs:
        hits.extend(art_refs)
    if "nghi phep" in q_fold or "don xin nghi" in q_fold:
        # Focus BM25 strongly on statutory/handbook leave rules & approvals without case proper nouns
        hits.extend(["nghi phep", "nghi hang nam", "ngay lam viec", "ban giao", "phe duyet", "giam doc nhan su", "truong phong", "cao diem", "truc thay", "lien tiep"])
        return " ".join(dict.fromkeys(hits))
    if "lam them" in q_fold or "tang ca" in q_fold:
        hits.extend(["lam them", "gio lam viec", "trong 01 ngay", "moi ngay", "gio/ngay", "luong gio", "150%", "200%", "300%"])
        return " ".join(dict.fromkeys([query, *hits]))
    if any(k in q_fold for k in ("chiet khau", "bang gia", "tong tien", "tong chi phi", "chi phi", "goi", "uu dai", "trien khai")):
        hits.extend(["chiet khau", "giam", "uu dai", "bang gia", "phe duyet", "tham quyen", "phi trien khai", "niem yet", "khong chiet khau", "dieu kien"])
        # Return concise domain-neutral pricing/policy cues alongside query so English goal text never starves VN discount chunks
        return " ".join(dict.fromkeys([*hits, query]))
    if any(k in q_fold for k in ("dieu khoan", "hop dong", "vi pham", "boi thuong", "phat", "rui ro")):
        hits.extend(["phat vi pham", "boi thuong", "gioi han", "trach nhiem", "hop dong", "thiet hai"])
        return " ".join(dict.fromkeys([*hits, query]))
    return " ".join(dict.fromkeys([query, *hits]))


def complete_missing_evidence(
    *,
    query: str,
    selected: list[SourceChunk],
    all_chunks: list[SourceChunk],
    allowed_source_ids: set[str] | None = None,
    max_tokens: int = 4000,
    max_added: int = 4,
) -> tuple[list[SourceChunk], dict[str, Any]]:
    """Recover missing continuation, neighbor, and lexical/BM25 rule chunks without evicting selected anchors."""
    authorized_pool = [
        c for c in all_chunks
        if allowed_source_ids is None or c.source_id in allowed_source_ids
    ]
    by_pos = {(c.source_id, c.index): c for c in authorized_pool}
    selected_ids = {c.chunk_id for c in selected}
    seen_hashes = {hashlib.sha256(c.text.strip().encode()).hexdigest() for c in selected}
    used_tokens = sum(estimate_tokens(c.text) for c in selected)

    out = list(selected)
    added_ids: list[str] = []
    reasons: dict[str, str] = {}

    def _try_add(ch: SourceChunk, reason: str) -> bool:
        nonlocal used_tokens
        if len(added_ids) >= max_added or ch.chunk_id in selected_ids:
            return False
        if allowed_source_ids is not None and ch.source_id not in allowed_source_ids:
            return False
        digest = hashlib.sha256(ch.text.strip().encode()).hexdigest()
        if digest in seen_hashes:
            return False
        cost = estimate_tokens(ch.text)
        if used_tokens + cost > max_tokens:
            return False
        seen_hashes.add(digest)
        selected_ids.add(ch.chunk_id)
        out.append(ch)
        added_ids.append(ch.chunk_id)
        reasons[ch.chunk_id] = reason
        used_tokens += cost
        return True

    # Pass 1: Article/heading continuation from already-selected chunks (e.g., # Điều 5 at chunk tail -> index + 1)
    for c in list(selected):
        nxt = by_pos.get((c.source_id, c.index + 1))
        if nxt is None:
            continue
        tail = (c.text or "")[-220:]
        if _needs_next_continuation(c.text, nxt.text) or _MID_HEADING_TAIL.search(tail):
            _try_add(nxt, "article_continuation")

    # Pass 2: Focused BM25 across authorized pool within active sources, prioritized by top relevance score per source
    active_sources = sorted({c.source_id for c in selected} or ({c.source_id for c in authorized_pool} if allowed_source_ids else set()))
    if len(added_ids) < max_added and active_sources:
        faceted_q = _query_facet_terms(query)
        # Score globally against candidate pool so IDF reflects cross-source discriminative policy terms
        unselected_pool = [c for c in authorized_pool if c.source_id in set(active_sources) and c.chunk_id not in selected_ids]
        global_scores = bm25_scores(faceted_q, unselected_pool) if unselected_pool else {}
        ranked_by_src: list[list[tuple[float, SourceChunk]]] = []
        for sid in active_sources:
            src_pool = [c for c in unselected_pool if c.source_id == sid]
            if not src_pool:
                continue
            ordered_src = sorted(
                ((float(global_scores.get(c.chunk_id, 0.0)), c) for c in src_pool),
                key=lambda x: (-x[0], x[1].chunk_id),
            )
            positives = [(s, ch) for s, ch in ordered_src if s > 0.0]
            if positives:
                ranked_by_src.append(positives)
        # Prioritize sources whose top unretrieved chunk has highest relevance so policy sections beat alphabetical noise
        ranked_by_src.sort(key=lambda lst: (-lst[0][0], lst[0][1].source_id))

        # Round-robin across active sources so one handbook never starves companion company policy chunks
        depth = 0
        while len(added_ids) < max_added and any(depth < len(lst) for lst in ranked_by_src):
            for lst in ranked_by_src:
                if len(added_ids) >= max_added:
                    break
                if depth >= len(lst):
                    continue
                _, ch = lst[depth]
                if _try_add(ch, "bm25_section_rescue"):
                    nxt = by_pos.get((ch.source_id, ch.index + 1))
                    if nxt and _needs_next_continuation(ch.text, nxt.text):
                        _try_add(nxt, "bm25_rescue_continuation")
            depth += 1

    return out, {
        "added_count": len(added_ids),
        "added_chunk_ids": added_ids,
        "reasons": reasons,
        "used_tokens": used_tokens,
        "max_tokens": max_tokens,
    }
