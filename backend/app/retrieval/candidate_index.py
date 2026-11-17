from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
from collections import Counter, OrderedDict
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


def no_full_load_enabled() -> bool:
    from app.retrieval.bm25_index import enabled
    return os.getenv("RETRIEVAL_NO_FULL_LOAD", "0").strip() == "1" or enabled()


_CORPORA: OrderedDict = OrderedDict()
_CORPUS_LOCK = threading.RLock()


class _LexicalCorpus:
    """Derived terms only; canonical text/provenance are hydrated after ranking."""

    def __init__(self, chunks):
        from app.retrieval.hybrid import tokens
        from app.retrieval.text import terms

        self.sources = {}
        self.lengths = {}
        self.lexical = {}
        self.postings = {}
        for chunk in chunks:
            cid = chunk.chunk_id
            self.sources[cid] = chunk.source_id
            counts = Counter(tokens(contextual_text(chunk)))
            self.lengths[cid] = sum(counts.values())
            self.lexical[cid] = terms(chunk.text)
            for term, freq in counts.items():
                self.postings.setdefault(term, {})[cid] = freq

    def rank(self, query, source_ids, top_k, min_score, bm25):
        from app.retrieval.hybrid import tokens
        from app.retrieval.text import terms

        selected = None if source_ids is None else set(source_ids)
        ids = {cid for cid, sid in self.sources.items() if selected is None or sid in selected}
        if not ids:
            return []
        scores = {}
        if bm25:
            n = len(ids)
            avg = sum(self.lengths[cid] for cid in ids) / n or 1.0
            for term in set(tokens(query)):
                posting = self.postings.get(term, {})
                matching = ids.intersection(posting)
                df = len(matching)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                for cid in matching:
                    freq = posting[cid]
                    scores[cid] = scores.get(cid, 0.0) + idf * freq * 2.5 / (
                        freq + 1.5 * (0.25 + 0.75 * self.lengths[cid] / avg))
            scores = {cid: round(score, 6) for cid, score in scores.items() if score > 0}
        else:
            q = terms(query)
            for cid in ids:
                c = self.lexical[cid]
                overlap = len(q & c)
                score = round(0.8 * (overlap / max(1, len(q))) + 0.2 * (overlap / max(1, len(c))), 8)
                if score > 0 and score >= min_score:
                    scores[cid] = score
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if bm25 and ranked:
            ranked = [item for item in ranked if item[1] >= 0.4 * ranked[0][1]]
        return ranked[:top_k]


def cached_rank(store, query, source_ids, top_k, min_score=0.0, *, bm25=False):
    """None selects legacy behavior; [] is an authoritative empty ranking.

    Cache by database/owner/space and cheap corpus signature. Effective S4 and
    version filters are applied to statistics as well as final canonical reads.
    """
    from app.retrieval.bm25_index import enabled, persistent_rank
    if enabled():
        return persistent_rank(store, query, source_ids, top_k, min_score, bm25=bm25)
    signature_reader = getattr(store, "retrieval_signature", None)
    if not no_full_load_enabled() or not callable(signature_reader):
        return None
    if source_ids == []:
        return []
    signature = signature_reader()
    factory = getattr(store, "session_factory", None)
    database = factory.kw.get("bind") if factory is not None else store
    key = (database, getattr(store, "owner_user_id", None), getattr(store, "space_id", None),
           os.getenv("CHUNK_MODE", ""))
    with _CORPUS_LOCK:
        cached = _CORPORA.get(key)
        if cached is None or cached[0] != signature:
            corpus = _LexicalCorpus(store.chunks())
            _CORPORA[key] = (signature, corpus)
        else:
            corpus = cached[1]
        _CORPORA.move_to_end(key)
        while len(_CORPORA) > 16:
            _CORPORA.popitem(last=False)
    ranked = corpus.rank(query, source_ids, top_k, min_score, bm25)
    chunks = {c.chunk_id: c for c in store.chunks_by_ids([cid for cid, _ in ranked], source_ids=source_ids)}
    return [replace(chunks[cid], score=score) for cid, score in ranked if cid in chunks]


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

    def begin_rebuild(self) -> None:
        """Adopt the current identity for the whole collection before re-embedding source by source.

        Nothing is deleted: vectors are overwritten in place (same record ids) by `index_source`. Until a source
        is re-embedded its old vectors are invisible to search (payload_complete -> embedding_version filter).
        """
        self._write_manifest(IndexManifest(self.identity, empty=False, payload_complete=True))

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
        version_query: str | None = None,
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
        scope_reader = getattr(self.source_store, "effective_source_ids", None)
        scoped = callable(scope_reader)
        if scoped:
            selected = sorted(scope_reader(query if version_query is None else version_query, selected))
        if selected == []:
            return []
        personal = getattr(self.source_store, "space_id", None) is None
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
            owner_user_id=self.owner_user_id if personal or not scoped else None,
            source_ids=selected,
            **filters,
        )


__all__ = ["CandidateIndex", "IndexingError"]
