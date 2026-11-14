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


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def contextual_text(chunk: SourceChunk) -> str:
    header = chunk.provenance.get("context_header")
    return f"{header}\n{chunk.text}" if header else chunk.text


def _document_parts(text: str) -> list[tuple[str, str]]:
    """Keep paragraph boundaries independent of neighbouring paragraph lengths."""
    result: list[tuple[str, str]] = []
    headings: list[tuple[int, str]] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            result.append(("\n".join(pending).strip(), " > ".join(h for _, h in headings)))
            pending.clear()

    for line in normalize_text(text).splitlines():
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            flush()
            level = len(heading[1])
            headings = [(n, h) for n, h in headings if n < level]
            headings.append((level, heading[2]))
            pending.append(line)
        elif not line.strip():
            # Attach a heading to its first paragraph, even with a blank line.
            if pending and not all(re.match(r"^\s*#", p) for p in pending):
                flush()
        else:
            pending.append(line)
    flush()
    return result


def _split_paragraph(text: str, max_chars: int) -> list[str]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    result: list[str] = []
    while len(text) > max_chars:
        boundaries = list(re.finditer(r"[.!?。！？](?:[\"'”’)]*)\s+", text[:max_chars + 1]))
        boundaries = [m for m in boundaries if m.end() >= max_chars * 0.8 and m.end() <= max_chars]
        end = boundaries[-1].end() if boundaries else max_chars
        result.append(text[:end].strip())
        text = text[end:].strip()
    if text:
        result.append(text)
    return result


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    return [piece for part, _ in _document_parts(text)
            for piece in _split_paragraph(part, max_chars)]


def make_chunks(
    source_name: str,
    text: str,
    max_chars: int = 1200,
    *,
    provenance: Mapping[str, Any] | None = None,
) -> list[SourceChunk]:
    clean = normalize_text(text)
    source_id = "src_" + hashlib.sha256((source_name + "\0" + clean).encode()).hexdigest()[:16]
    # Source versions remain content-addressed; document identity survives re-upload.
    doc_id = "src_" + hashlib.sha256(source_name.encode()).hexdigest()[:16]
    result: list[SourceChunk] = []
    for order, (part, section_path) in enumerate(_document_parts(clean)):
        for piece_order, chunk in enumerate(_split_paragraph(part, max_chars)):
            chunk_id = f"{doc_id}_c{order:04d}"
            if piece_order:
                chunk_id += f"_p{piece_order:04d}"
            result.append(SourceChunk(
                chunk_id=chunk_id, source_id=source_id, source_name=source_name,
                text=chunk, index=len(result),
                provenance={**dict(provenance or {}), "doc_id": doc_id,
                            "chunk_index": len(result), "content_hash": content_hash(chunk),
                            "section_path": section_path,
                            "context_header": f"Tài liệu: {source_name} > {section_path}"},
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


def apply_token_budget(chunks: list[SourceChunk], max_tokens: int) -> tuple[list[SourceChunk], list[dict]]:
    selected: list[SourceChunk] = []
    dropped: list[dict] = []
    used = 0
    for chunk in chunks:
        cost = estimate_tokens(chunk.text)
        if selected and used + cost > max_tokens:
            dropped.append({"chunk_id": chunk.chunk_id, "reason": "hard_context_token_cap", "estimated_tokens": cost})
            continue
        if not selected and cost > max_tokens:
            # Preserve a bounded excerpt instead of silently exceeding the cap.
            char_cap = max(128, max_tokens * 3)
            excerpt = chunk.text[:char_cap]
            selected.append(SourceChunk(**{**chunk.__dict__, "text": excerpt}))
            used += estimate_tokens(excerpt)
            dropped.append({"chunk_id": chunk.chunk_id, "reason": "truncated_to_hard_context_token_cap", "estimated_tokens": cost})
            continue
        selected.append(chunk)
        used += cost
    return selected, dropped
