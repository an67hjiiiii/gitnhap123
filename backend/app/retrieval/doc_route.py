"""Deterministic document cards and opt-in, S4-scoped document routing."""
from __future__ import annotations

import math
import os
import re
from dataclasses import replace

from app.core.types import SourceChunk
from app.retrieval.embeddings import make_embedder
from app.retrieval.hybrid import bm25_rank, rrf_merge
from app.retrieval.text import normalize_text


def enabled() -> bool:
    return os.getenv("DOC_ROUTE", "off").strip().lower() == "on"


_NUMBER = re.compile(r"(?<!\d)(\d{1,4})\s*/\s*((?:19|20)\d{2})(?:\s*/\s*([\wĐđ-]+))?", re.I)
_SHORT = re.compile(r"\b(thông\s+tư|tt|nghị\s+định|nđ|quyết\s+định|qđ|luật)\s*(?:số\s*:?\s*)?(\d{1,4})(?!\d)", re.I)


def number_keys(text: str) -> set[str]:
    keys = {f"{int(m[1])}/{m[2]}" for m in _NUMBER.finditer(text)}
    for match in _NUMBER.finditer(text):
        kind = (match[3] or "").split("-")[0].casefold()
        if kind in {"tt", "nđ", "qđ"}:
            keys.add(f"{kind}:{int(match[1])}")
    kinds = {"thông tư": "tt", "nghị định": "nđ", "quyết định": "qđ"}
    for m in _SHORT.finditer(text):
        kind = " ".join(m[1].casefold().split())
        keys.add(f"{kinds.get(kind, kind)}:{int(m[2])}")
    return keys


def build_doc_card(source_name: str, text: str) -> dict:
    """Extract metadata without generation; retain every article heading."""
    lines = [line.strip().lstrip("# ") for line in normalize_text(text).splitlines() if line.strip()]
    headings = [line for line in lines if re.match(r"^Điều\s+\d+[a-zđ]?[\s.:)]", line, re.I)]
    header = "\n".join(lines[:40])
    numbers = [m[0] for m in _NUMBER.finditer(source_name + "\n" + header)]
    dates = re.findall(r"\b(?:ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})\b", header, re.I)
    title = next((line for line in lines[:40] if re.match(
        r"^(?:quy định|ban hành|hướng dẫn|về việc|về\s|luật\s+\S|bộ luật\s)", line, re.I)), "")
    if not title:
        title = next((line for line in lines[:40] if line not in headings
                      and not re.match(r"^(?:cộng hòa|độc lập|số\s*:|ngày\s|căn cứ)", line, re.I)), source_name)
    card = {"version": 1, "source_name": source_name, "numbers": numbers,
            "dates": dates, "title": title, "article_headings": headings, "opening_lines": lines[:5]}
    card["text"] = "\n".join([source_name, *numbers, *dates, title, *headings, *lines[:5]])
    card["number_keys"] = sorted(number_keys(source_name + "\n" + header))
    return card


def route_source_ids(pipeline, query: str, source_ids=None):
    """None means disabled; [] is authoritative and must never widen scope."""
    if not enabled():
        return source_ids
    store = pipeline.source_store
    scope = getattr(store, "effective_source_ids", None)
    if callable(scope):
        source_ids = sorted(scope(query, source_ids))
    if source_ids == []:
        return []
    reader = getattr(store, "doc_cards", None)
    if not callable(reader):
        return []
    cards = reader(source_ids)
    cards = [c for c in cards if source_ids is None or c.source_id in source_ids]
    if not cards:
        return []
    embedder = getattr(getattr(pipeline, "candidate_index", None), "embedder", None) or make_embedder()
    query_vector = embedder.embed(query)
    batch = getattr(embedder, "embed_many", None)
    vectors = batch([c.text for c in cards]) if callable(batch) else [embedder.embed(c.text) for c in cards]
    def cosine(vector):
        norm = math.sqrt(sum(v * v for v in vector) * sum(v * v for v in query_vector))
        return sum(a * b for a, b in zip(query_vector, vector)) / norm if norm else 0.0
    vector_rank = sorted((replace(c, score=cosine(v)) for c, v in zip(cards, vectors)),
                         key=lambda c: (-c.score, c.source_id))
    fused = rrf_merge([vector_rank, bm25_rank(query, cards, len(cards), rel_min=0)], len(cards))
    wanted = number_keys(query)
    # A full year-qualified reference must not match a different year through its short alias.
    full = {k for k in wanted if "/" in k}
    wanted = full or wanted
    fused.sort(key=lambda c: not bool(wanted & set(c.provenance.get("number_keys", []))))
    return [c.source_id for c in fused[:3]]


def card_chunk(source_id: str, card: dict) -> SourceChunk:
    return SourceChunk("doc_card:" + source_id, source_id, card["source_name"], card["text"], -1,
                       provenance={"number_keys": card.get("number_keys", []), "chunk_kind": "doc_card"})


def rebuild_doc_cards(session_factory, *, source_ids=None) -> int:
    """Explicit maintenance operation across all READY sources; no model calls."""
    from sqlalchemy import select
    from app.storage.postgres.models import KnowledgeSourceRecord, KnowledgeChunkRecord

    count = 0
    with session_factory.begin() as db:
        statement = select(KnowledgeSourceRecord.source_id).where(KnowledgeSourceRecord.status == "READY")
        if source_ids is not None:
            statement = statement.where(KnowledgeSourceRecord.source_id.in_(source_ids))
        ids = db.scalars(statement).all()
        for sid in ids:
            source = db.get(KnowledgeSourceRecord, sid)
            chunks = db.scalars(select(KnowledgeChunkRecord).where(
                KnowledgeChunkRecord.source_id == sid).order_by(KnowledgeChunkRecord.chunk_index)).all()
            text = (source.display_metadata or {}).get("_version_diff_text") or "\n".join(
                row.content for row in chunks if (row.provenance or {}).get("chunk_kind") != "doc_card")
            source.display_metadata = {**(source.display_metadata or {}), "doc_card": build_doc_card(source.source_name, text)}
            count += 1
    return count
