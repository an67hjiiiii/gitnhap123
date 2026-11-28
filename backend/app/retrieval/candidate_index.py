from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterable

from app.retrieval.embeddings import LocalHashEmbedder, TextEmbedder, are_embedding_versions_compatible
from app.storage.vector_store import VectorMatch, VectorRecord, VectorStore

_RUN_EMBED_CACHE: ContextVar[dict[tuple[str, str, str, str], tuple[float, ...]] | None] = ContextVar(
    "candidate_index_run_embed_cache", default=None
)


@contextmanager
def scoped_embed_cache():
    """Enable an isolated per-run query embedding memo, discarded immediately on exit."""
    tok = _RUN_EMBED_CACHE.set({})
    try:
        yield
    finally:
        _RUN_EMBED_CACHE.reset(tok)


def embed_with_run_cache(embedder: TextEmbedder, text: str) -> tuple[float, ...]:
    cache = _RUN_EMBED_CACHE.get()
    if cache is None:
        return embedder.embed(text)
    key = (
        str(getattr(embedder, "version", "") or ""),
        str(getattr(embedder, "model", "") or ""),
        str(getattr(embedder, "base_url", "") or ""),
        text,
    )
    hit = cache.get(key)
    if hit is not None:
        return hit
    vec = embedder.embed(text)
    cache[key] = vec
    return vec


class IndexingError(RuntimeError):
    """A derived-index write failed; the authoritative source remains separate."""


class CandidateIndex:
    """Build/search a derived vector index from an owner-scoped source store."""

    def __init__(
        self,
        source_store: Any,
        vector_store: VectorStore,
        *,
        owner_user_id: str,
        embedder: TextEmbedder | None = None,
    ) -> None:
        if not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("owner_user_id must be non-empty")
        self.source_store = source_store
        self.vector_store = vector_store
        self.owner_user_id = owner_user_id
        self.embedder = embedder or LocalHashEmbedder()
        self.last_search_stats: dict[str, Any] = {}

    def index_source(self, source_id: str) -> dict[str, Any]:
        source = self.source_store.source(source_id)
        if source is None:
            raise LookupError("source not found")
        if source.get("status") not in {None, "READY"}:
            raise IndexingError("only READY sources may be indexed")
        try:
            chunks = self.source_store.chunks([source_id])
            records = [
                VectorRecord(
                    id=f"{self.owner_user_id}:{chunk.chunk_id}",
                    vector=self.embedder.embed(chunk.text),
                    payload={
                        "owner_user_id": self.owner_user_id,
                        "source_id": chunk.source_id,
                        "chunk_id": chunk.chunk_id,
                        "source_name": chunk.source_name,
                        "embedding_version": self.embedder.version,
                        **dict(chunk.provenance),
                    },
                )
                for chunk in chunks
            ]
            self.vector_store.upsert(records)
        except Exception as exc:
            marker = getattr(self.source_store, "mark_failed", None)
            if callable(marker):
                marker(source_id, exc)
            raise IndexingError("derived index write failed") from exc
        return {
            "source_id": source_id,
            "chunks_indexed": len(records),
            "embedding_version": self.embedder.version,
        }

    def candidates(
        self,
        query: str,
        *,
        limit: int = 10,
        source_ids: Iterable[str] | None = None,
    ) -> list[VectorMatch]:
        selected = None if source_ids is None else [str(source_id) for source_id in source_ids]
        scope_reader = getattr(self.source_store, "scope_source_ids", None)
        if not callable(scope_reader):  # kho tệp cũ (không có không gian tổ chức): giữ nguyên hành vi
            matches = self.vector_store.search(
                embed_with_run_cache(self.embedder, query), limit=limit, owner_user_id=self.owner_user_id, source_ids=selected,
            )
        else:
            allowed = scope_reader()
            if selected is not None:
                allowed &= set(selected)
            if not allowed:
                return []  # đóng khi rỗng: không bao giờ tìm toàn kho
            # không gian tổ chức đọc cả tài liệu người khác tải lên nên chỉ lọc theo danh sách được phép
            personal = getattr(self.source_store, "space_id", None) is None
            matches = self.vector_store.search(
                embed_with_run_cache(self.embedder, query),
                limit=limit,
                owner_user_id=self.owner_user_id if personal else None,
                source_ids=sorted(allowed),
            )
        expected = self.embedder.version
        filtered: list[VectorMatch] = []
        skipped_mismatch = 0
        alias_matched = 0
        for m in matches:
            ver = (m.payload or {}).get("embedding_version")
            compat, reason = are_embedding_versions_compatible(ver, expected)
            if not compat:
                skipped_mismatch += 1
                continue
            if reason == "ollama_default_latest_alias":
                alias_matched += 1
            filtered.append(m)
        self.last_search_stats = {
            "expected_version": expected,
            "raw_matches": len(matches),
            "accepted_matches": len(filtered),
            "alias_matched": alias_matched,
            "skipped_mismatch": skipped_mismatch,
        }
        if skipped_mismatch:
            logging.getLogger(__name__).warning(
                "RET-03 skipped %d vector matches with mismatched embedding_version (expected %s)",
                skipped_mismatch,
                expected,
            )
        return filtered


__all__ = ["CandidateIndex", "IndexingError"]
