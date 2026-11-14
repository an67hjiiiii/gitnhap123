from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from app.retrieval.embeddings import LocalHashEmbedder, TextEmbedder
from app.retrieval.index_identity import (
    IndexIdentity,
    IndexIncompatibleError,
    IndexLegacyUnverifiedError,
    IndexManifest,
    IndexState,
    IndexingError,
    compute_state,
    manifest_path as collection_manifest_path,
    read_manifest,
    write_manifest,
)
from app.retrieval.text import content_hash, contextual_text
from app.storage.vector_store import VectorMatch, VectorRecord, VectorStore


logger = logging.getLogger(__name__)


class CandidateIndex:
    """Build/search a derived vector index from an owner-scoped source store."""

    def __init__(
        self,
        source_store: Any,
        vector_store: VectorStore,
        *,
        owner_user_id: str,
        embedder: TextEmbedder | None = None,
        manifest_path: str | Path | None = None,
        default_workspace_id: str | None = None,
    ) -> None:
        if not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("owner_user_id must be non-empty")
        self.source_store = source_store
        self.vector_store = vector_store
        self.owner_user_id = owner_user_id
        self.embedder = embedder or LocalHashEmbedder()
        if manifest_path is None and hasattr(vector_store, "path") and hasattr(vector_store, "collection"):
            manifest_path = collection_manifest_path(vector_store.path, vector_store.collection)
        self.manifest_path = None if manifest_path is None else Path(manifest_path)
        self.last_search_info: dict[str, Any] = {}
        self.default_workspace_id = default_workspace_id
        self._query_embeddings = OrderedDict()

    @property
    def identity(self) -> IndexIdentity:
        return IndexIdentity.from_embedder(self.embedder)

    def _read_manifest(self) -> IndexManifest | None:
        if self.manifest_path is not None:
            return read_manifest(self.manifest_path)
        # Memory stores retain metadata for their own lifetime, just like their vectors.
        return getattr(self.vector_store, "_index_manifest", None)

    def _write_manifest(self, manifest: IndexManifest) -> None:
        if self.manifest_path is not None:
            write_manifest(self.manifest_path, manifest)
        else:
            self.vector_store._index_manifest = manifest

    def _check_identity(self, manifest: IndexManifest | None) -> IndexState:
        state = compute_state(manifest, self.identity)
        if state == IndexState.INCOMPATIBLE:
            raise IndexIncompatibleError("Index identity differs from the current embedder; rebuild the index")
        if state == IndexState.LEGACY_UNVERIFIED:
            if os.getenv("INDEX_STRICT", "").strip() == "1":
                raise IndexLegacyUnverifiedError("Index has no identity manifest; rebuild or verify the index")
            if not getattr(self.vector_store, "_index_legacy_warned", False):
                logger.warning("LEGACY_UNVERIFIED vector index: preserving legacy retrieval without identity verification")
                self.vector_store._index_legacy_warned = True
        return state

    def index_source(self, source_id: str, *, workspace_id: str | None = None) -> dict[str, Any]:
        source = self.source_store.source(source_id)
        if source is None:
            raise LookupError("source not found")
        if source.get("status") not in {None, "READY"}:
            raise IndexingError("only READY sources may be indexed")
        manifest = self._read_manifest()
        if manifest is None:
            # Counting is confined to writes. Searches never inspect collection contents.
            count = getattr(self.vector_store, "count", None)
            if callable(count) and count() == 0:
                manifest = IndexManifest(self.identity, empty=True)
        self._check_identity(manifest)
        try:
            chunks = self.source_store.chunks([source_id])
            workspace_id = workspace_id if workspace_id is not None else self.default_workspace_id
            doc_id = chunks[0].provenance.get("doc_id") if chunks else None
            lookup = getattr(self.vector_store, "records_for_source", None)
            previous = lookup(self.owner_user_id, source_id, workspace_id=workspace_id, doc_id=doc_id) if callable(lookup) else []
            previous_by_id = {record.payload.get("chunk_id"): record for record in previous}
            current_ids = {chunk.chunk_id for chunk in chunks}
            deleted = [record.id for record in previous if record.payload.get("chunk_id") not in current_ids]
            changed = []
            unchanged = []
            for chunk in chunks:
                old = previous_by_id.get(chunk.chunk_id)
                if (old is not None and old.payload.get("content_hash") == content_hash(chunk.text)
                        and old.payload.get("context_header") == chunk.provenance.get("context_header")
                        and old.payload.get("embedding_version") == self.identity.embedding_version):
                    unchanged.append((chunk, old))
                else:
                    changed.append(chunk)
            texts = [contextual_text(chunk) for chunk in changed]
            batch = getattr(self.embedder, "embed_many", None)
            vectors = batch(texts) if callable(batch) and texts else [self.embedder.embed(text) for text in texts]
            if len(vectors) != len(changed):
                raise ValueError("embed_many returned an unexpected embedding count")

            def record_id(chunk):
                prefix = f"{self.owner_user_id}:" if workspace_id is None else f"{self.owner_user_id}:{workspace_id}:"
                return prefix + chunk.chunk_id

            def payload(chunk):
                return {**dict(chunk.provenance), "owner_user_id": self.owner_user_id,
                        "source_id": chunk.source_id, "chunk_id": chunk.chunk_id,
                        "source_name": chunk.source_name, "content_hash": content_hash(chunk.text),
                        "embedding_version": self.identity.embedding_version, "workspace_id": workspace_id}

            records = [VectorRecord(record_id(chunk), vector, payload(chunk))
                       for chunk, vector in zip(changed, vectors)]
            # A new source version can reuse vectors but must update source filters.
            for chunk, old in unchanged:
                if old.payload.get("source_id") != chunk.source_id:
                    if old.vector:
                        records.append(VectorRecord(old.id, old.vector, payload(chunk)))
                    else:
                        self.vector_store.update_payload(old.id, payload(chunk))
            if manifest is not None:
                # Persist the identity before writing any vectors, including on partial failure.
                manifest = replace(manifest, empty=manifest.empty and not chunks,
                                   payload_complete=manifest.payload_complete or manifest.empty and bool(chunks) and all(
                                       "context_header" in c.provenance for c in chunks))
                self._write_manifest(manifest)
            self.vector_store.upsert(records)
            self.vector_store.delete(deleted)
        except Exception as exc:
            marker = getattr(self.source_store, "mark_failed", None)
            if callable(marker):
                marker(source_id, exc)
            raise IndexingError("derived index write failed") from exc
        return {
            "source_id": source_id,
            "chunks_indexed": len(changed),
            "chunks_skipped": len(unchanged),
            "chunks_deleted": len(deleted),
            "embedding_version": self.identity.embedding_version,
        }

    def candidates(
        self,
        query: str,
        *,
        limit: int = 10,
        source_ids: Iterable[str] | None = None,
        workspace_id: str | None = None,
    ) -> list[VectorMatch]:
        self.last_search_info = {
            "index_state": IndexState.INCOMPATIBLE.value,
            "index_embedding_version": None,
            "retrieval_backend_used": None,
            "fallback_reason": None,
        }
        manifest = self._read_manifest()
        state = compute_state(manifest, self.identity)
        self.last_search_info.update(
            index_state=state.value,
            index_embedding_version=None if manifest is None else manifest.identity.embedding_version,
        )
        self._check_identity(manifest)
        selected = None if source_ids is None else [str(source_id) for source_id in source_ids]
        self.last_search_info["retrieval_backend_used"] = (
            "qdrant" if hasattr(self.vector_store, "collection") else "memory"
        )
        key = (self.identity.embedding_version, hashlib.sha256(query.encode("utf-8")).hexdigest())
        if key not in self._query_embeddings:
            self._query_embeddings[key] = self.embedder.embed(query)
            if len(self._query_embeddings) > 256:
                self._query_embeddings.popitem(last=False)
        self._query_embeddings.move_to_end(key)
        filters = {}
        workspace_id = workspace_id if workspace_id is not None else self.default_workspace_id
        if workspace_id is not None:
            filters["workspace_id"] = workspace_id
        if manifest is not None and manifest.payload_complete:
            filters["embedding_version"] = self.identity.embedding_version
        return self.vector_store.search(
            self._query_embeddings[key],
            limit=limit,
            owner_user_id=self.owner_user_id,
            source_ids=selected,
            **filters,
        )


__all__ = ["CandidateIndex", "IndexingError"]
