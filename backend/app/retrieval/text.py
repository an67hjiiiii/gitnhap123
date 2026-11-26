from __future__ import annotations
import hashlib
import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from app.core.types import SourceChunk

STOP = {"the","a","an","and","or","to","of","in","on","for","with","is","are","be","this","that","và","là","của","cho","trong","với","một","các","những","được","hãy","theo"}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", str(text or ""))
    return text.replace("\ufeff", "", 1).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def estimate_tokens(text: str) -> int:
    """Tokenizer-independent conservative proxy used only for pre-call budgeting.

    Actual provider-reported token counts remain authoritative in run metrics.
    """
    clean = normalize_text(text)
    if not clean:
        return 0
    # Mixed Vietnamese/English text generally lands near 3-4 chars/token.
    return max(1, (len(clean) + 2) // 3)


def _stem_token(token: str) -> str:
    # Tiny deterministic English normalization; intentionally not a learned stemmer.
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token

def terms(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-zÀ-ỹ0-9_'-]{2,}", normalize_text(text).lower())
    expanded = {piece for token in raw for piece in (token, *re.split(r"[_'-]", token)) if len(piece) >= 2}
    normalized = {_stem_token(t) for t in expanded if t not in STOP}
    return normalized


_TRAILING_HEADING = re.compile(
    r"^(?:#+\s*|(?:Chương|CHƯƠNG|Điều|ĐIỀU|Mục|MỤC|Chapter|Article|Section)\s+(?:[IVXLCDM]+|\d+)\b)"
)


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for part in parts:
        if len(buf) + len(part) + 2 <= max_chars:
            buf = (buf + "\n\n" + part).strip()
        else:
            carry = ""
            if buf and "\n\n" in buf:
                head_prefix, tail = buf.rsplit("\n\n", 1)
                if len(tail) <= 120 and _TRAILING_HEADING.match(tail) and len(tail) + len(part) + 2 <= max_chars:
                    buf = head_prefix
                    carry = tail
            if buf:
                chunks.append(buf)
            merged_part = f"{carry}\n\n{part}" if carry else part
            if len(merged_part) <= max_chars:
                buf = merged_part
            else:
                for i in range(0, len(merged_part), max_chars):
                    chunks.append(merged_part[i:i+max_chars])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def make_chunks(
    source_name: str,
    text: str,
    max_chars: int = 1200,
    *,
    provenance: Mapping[str, Any] | None = None,
) -> list[SourceChunk]:
    clean = normalize_text(text)
    source_id = "src_" + hashlib.sha256((source_name + "\0" + clean).encode()).hexdigest()[:16]
    base_provenance = dict(provenance or {})
    result: list[SourceChunk] = []
    for i, chunk in enumerate(chunk_text(clean, max_chars=max_chars)):
        result.append(SourceChunk(
            chunk_id=f"{source_id}_c{i:04d}",
            source_id=source_id,
            source_name=source_name,
            text=chunk,
            index=i,
            provenance={**base_provenance, "chunk_index": i},
        ))
    return result


def lexical_score(query: str, chunk: SourceChunk) -> float:
    q = terms(query)
    c = terms(chunk.text)
    if not q or not c:
        return 0.0
    overlap = len(q & c)
    coverage = overlap / max(1, len(q))
    density = overlap / max(1, len(c))
    return round(0.8 * coverage + 0.2 * density, 8)


def retrieve(query: str, chunks: list[SourceChunk], top_k: int = 6, min_score: float = 0.0) -> list[SourceChunk]:
    scored: list[SourceChunk] = []
    for chunk in chunks:
        score = lexical_score(query, chunk)
        if score >= min_score and score > 0:
            scored.append(SourceChunk(**{**chunk.__dict__, "score": score}))
    scored.sort(key=lambda x: (-x.score, x.chunk_id))
    return scored[:top_k]


def _source_aware_relevance(query: str, chunk: SourceChunk) -> tuple[float, float]:
    """Đo mức khớp truy vấn trên cả tên nguồn (năm, mã luật) lẫn nội dung đoạn."""
    q = terms(query)
    if not q:
        return (0.0, 0.0)
    combined = terms(f"{chunk.source_name} {chunk.text}")
    coverage = round(len(q & combined) / len(q), 4)
    return (coverage, round(lexical_score(query, chunk), 4))


def select_budgeted_chunks(
    chunks: list[SourceChunk],
    *,
    cost_fn,
    budget: int,
    query: str | None = None,
    truncate_first: bool = False,
    budget_reason: str = "token_budget_proxy",
) -> tuple[list[SourceChunk], list[dict]]:
    """Bộ chọn đoạn dùng chung cho char-proxy và token-budget: bảo toàn đa nguồn + đoạn nối tiếp theo đúng truy vấn."""
    if not chunks:
        return [], []
    if not query or len({c.source_id for c in chunks}) < 2:
        selected: list[SourceChunk] = []
        dropped: list[dict] = []
        seen_exact: set[str] = set()
        used = 0
        for chunk in chunks:
            digest = hashlib.sha256(chunk.text.strip().encode()).hexdigest()
            if digest in seen_exact:
                dropped.append({"chunk_id": chunk.chunk_id, "reason": "exact_duplicate"})
                continue
            cost = cost_fn(chunk.text)
            if (selected or not truncate_first) and used + cost > budget:
                dropped.append({"chunk_id": chunk.chunk_id, "reason": budget_reason})
                continue
            if not selected and truncate_first and cost > budget:
                char_cap = max(128, budget * 3)
                excerpt = chunk.text[:char_cap]
                selected.append(SourceChunk(**{**chunk.__dict__, "text": excerpt}))
                used += cost_fn(excerpt)
                dropped.append({"chunk_id": chunk.chunk_id, "reason": "truncated_to_hard_context_token_cap"})
                continue
            seen_exact.add(digest)
            selected.append(chunk)
            used += cost
        return selected, dropped

    picked: list[SourceChunk] = []
    picked_ids: set[str] = set()
    seen_exact: set[str] = set()
    dropped: list[dict] = []
    used = 0

    def _try_take(chunk: SourceChunk) -> bool:
        nonlocal used
        if chunk.chunk_id in picked_ids:
            return False
        digest = hashlib.sha256(chunk.text.strip().encode()).hexdigest()
        if digest in seen_exact:
            return False
        cost = cost_fn(chunk.text)
        if (picked or not truncate_first) and used + cost > budget:
            return False
        if not picked and truncate_first and cost > budget:
            char_cap = max(128, budget * 3)
            excerpt = chunk.text[:char_cap]
            picked.append(SourceChunk(**{**chunk.__dict__, "text": excerpt}))
            picked_ids.add(chunk.chunk_id)
            seen_exact.add(digest)
            used += cost_fn(excerpt)
            return True
        seen_exact.add(digest)
        picked_ids.add(chunk.chunk_id)
        picked.append(chunk)
        used += cost
        return True

    by_src: dict[str, list[SourceChunk]] = {}
    for c in chunks:
        by_src.setdefault(c.source_id, []).append(c)

    ranked_sources: list[tuple[tuple[float, float, float], SourceChunk, list[SourceChunk]]] = []
    for src_chunks in by_src.values():
        best = max(src_chunks, key=lambda c: (*_source_aware_relevance(query, c), float(c.score or 0.0), -c.index))
        cov, lex = _source_aware_relevance(query, best)
        ranked_sources.append(((cov, lex, float(best.score or 0.0)), best, src_chunks))
    ranked_sources.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[1].chunk_id))

    seeded: list[tuple[SourceChunk, list[SourceChunk]]] = []
    for _, best, src_chunks in ranked_sources:
        if _try_take(best):
            seeded.append((best, src_chunks))

    for best, src_chunks in seeded:
        nxt = next((c for c in src_chunks if c.index == best.index + 1), None)
        if nxt is None:
            nxt = next((c for c in src_chunks if c.index == best.index - 1), None)
        if nxt is not None:
            _try_take(nxt)

    for chunk in chunks:
        if chunk.chunk_id in picked_ids:
            continue
        digest = hashlib.sha256(chunk.text.strip().encode()).hexdigest()
        if digest in seen_exact:
            dropped.append({"chunk_id": chunk.chunk_id, "reason": "exact_duplicate"})
            continue
        if not _try_take(chunk):
            dropped.append({"chunk_id": chunk.chunk_id, "reason": budget_reason})
    return picked, dropped


def apply_token_budget(chunks: list[SourceChunk], max_tokens: int, *, query: str | None = None) -> tuple[list[SourceChunk], list[dict]]:
    return select_budgeted_chunks(
        chunks,
        cost_fn=estimate_tokens,
        budget=max_tokens,
        query=query,
        truncate_first=True,
        budget_reason="hard_context_token_cap",
    )
