from __future__ import annotations

import importlib.util
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.types import SourceChunk
from app.research.pipeline import ResearchPipeline
from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import LocalHashEmbedder, OllamaEmbedder
from app.retrieval.index_identity import (
    IndexIdentity,
    IndexIncompatibleError,
    IndexLegacyUnverifiedError,
    IndexManifest,
    IndexState,
    compute_state,
    manifest_path,
    read_manifest,
    write_manifest,
)
from app.storage.vector_store import InMemoryVectorStore, VectorRecord


GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "sf1" / "retrieve_candidates.golden.json").read_text(encoding="utf-8")
)
EMBEDDER = LocalHashEmbedder()
IDENTITY = IndexIdentity.from_embedder(EMBEDDER)


@pytest.fixture(autouse=True)
def fake_environment(sf1_fake_provider_env):
    sf1_fake_provider_env.delenv("INDEX_STRICT", raising=False)


def _seed(store, chunks=None):
    chunks = chunks or [SourceChunk("chunk", "source", "source.txt", "stable API error", 0)]
    store.upsert(
        VectorRecord(
            f"owner:{chunk.chunk_id}",
            EMBEDDER.embed(chunk.text),
            {"owner_user_id": "owner", "source_id": chunk.source_id, "chunk_id": chunk.chunk_id},
        )
        for chunk in chunks
    )
    return chunks


def _index(store, **kwargs):
    return CandidateIndex(None, store, owner_user_id="owner", embedder=EMBEDDER, **kwargs)


@pytest.mark.parametrize("case", GOLDEN, ids=lambda case: case["name"])
def test_legacy_results_match_sf1_golden(case, sf1_vector_store, caplog):
    chunks = _seed(
        sf1_vector_store,
        [SourceChunk(c["id"], c["source_id"], f'{c["source_id"]}.txt', c["text"], 0) for c in case["chunks"]],
    )
    index = _index(sf1_vector_store)
    pipeline = ResearchPipeline(None, None, candidate_index=index, retrieval_backend="vector")
    with caplog.at_level(logging.WARNING):
        found = pipeline._retrieve_candidates(case["query"], chunks, top_k=4, min_score=0.0, source_ids=None)
        # A new per-request CandidateIndex must not produce another warning for this store.
        _index(sf1_vector_store).candidates(case["query"])
    assert [chunk.chunk_id for chunk in found] == case["expected_ids"]
    assert [round(chunk.score, 6) for chunk in found] == case["expected_scores"]
    assert sum("LEGACY_UNVERIFIED" in record.message for record in caplog.records) == 1
    assert index.last_search_info == {
        "index_state": "LEGACY_UNVERIFIED",
        "index_embedding_version": None,
        "retrieval_backend_used": "memory",
        "fallback_reason": None,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"backend": "other"}, {"model_name": "other"}, {"digest": "sha256:other"},
        {"dimension": 16}, {"embedding_version": "other"}, {"normalization_version": "other"},
    ],
)
def test_each_identity_mismatch_raises_before_query(change, sf1_vector_store, monkeypatch):
    _seed(sf1_vector_store)
    sf1_vector_store._index_manifest = IndexManifest(replace(IDENTITY, **change))
    index = _index(sf1_vector_store)
    monkeypatch.setattr(sf1_vector_store, "search", lambda *a, **k: pytest.fail("must refuse before vector search"))
    monkeypatch.setattr(index.embedder.__class__, "embed", lambda *a: pytest.fail("must refuse before embedding"))
    with pytest.raises(IndexIncompatibleError) as exc:
        index.candidates("API")
    assert exc.value.code == "INDEX_INCOMPATIBLE"
    assert index.last_search_info["index_state"] == "INCOMPATIBLE"
    assert index.last_search_info["retrieval_backend_used"] is None


def test_strict_legacy_is_refused(sf1_vector_store, monkeypatch):
    _seed(sf1_vector_store)
    index = _index(sf1_vector_store)
    monkeypatch.setenv("INDEX_STRICT", "1")
    with pytest.raises(IndexLegacyUnverifiedError) as exc:
        index.candidates("API")
    assert exc.value.code == "INDEX_LEGACY_UNVERIFIED"
    assert index.last_search_info["index_state"] == "LEGACY_UNVERIFIED"


def test_compatible_preserves_owner_source_filters_and_versionless_payloads(sf1_vector_store):
    _seed(sf1_vector_store)
    sf1_vector_store.upsert([
        VectorRecord("other:chunk", EMBEDDER.embed("API"), {"owner_user_id": "other", "source_id": "source"}),
        VectorRecord("owner:excluded", EMBEDDER.embed("API"), {"owner_user_id": "owner", "source_id": "excluded"}),
    ])
    expected = sf1_vector_store.search(EMBEDDER.embed("API"), limit=2, owner_user_id="owner", source_ids=["source"])
    sf1_vector_store._index_manifest = IndexManifest(IDENTITY)
    index = _index(sf1_vector_store)
    assert index.candidates("API", limit=2, source_ids=iter(["source"])) == expected
    assert expected and "embedding_version" not in expected[0].payload
    assert index.last_search_info["index_state"] == "COMPATIBLE"
    assert index.last_search_info["index_embedding_version"] == EMBEDDER.version


def test_all_states_preserve_results_or_raise_typed_error(monkeypatch):
    manifests = {
        IndexState.COMPATIBLE: IndexManifest(IDENTITY),
        IndexState.EMPTY: IndexManifest(IDENTITY, empty=True),
        IndexState.LEGACY_UNVERIFIED: None,
        IndexState.INCOMPATIBLE: IndexManifest(replace(IDENTITY, embedding_version="old")),
    }
    for strict in ("0", "1"):
        monkeypatch.setenv("INDEX_STRICT", strict)
        for state, manifest in manifests.items():
            for query in ("API", "error", "unrelated"):
                store = InMemoryVectorStore()
                _seed(store)
                store._index_manifest = manifest
                expected = store.search(EMBEDDER.embed(query), owner_user_id="owner")
                index = _index(store)
                assert compute_state(manifest, IDENTITY) == state
                # Search must use metadata only, including when it says EMPTY.
                monkeypatch.setattr(store, "count", lambda: pytest.fail("count on search path"))
                error = (
                    IndexIncompatibleError if state == IndexState.INCOMPATIBLE else
                    IndexLegacyUnverifiedError if strict == "1" and state == IndexState.LEGACY_UNVERIFIED else None
                )
                if error:
                    with pytest.raises(error):
                        index.candidates(query)
                else:
                    assert index.candidates(query) == expected
                    assert expected  # A stale EMPTY flag must not suppress actual vector results.


def _source_store(chunks):
    return SimpleNamespace(source=lambda sid: {"status": "READY"}, chunks=lambda ids: chunks)


def test_write_creates_manifest_only_for_empty_collection_and_refuses_mismatch(sf1_vector_store, monkeypatch):
    chunk = SourceChunk("chunk", "source", "source.txt", "stable API error", 0)
    index = CandidateIndex(_source_store([chunk]), sf1_vector_store, owner_user_id="owner", embedder=EMBEDDER)
    monkeypatch.setenv("INDEX_STRICT", "1")
    assert index.index_source("source")["chunks_indexed"] == 1
    assert sf1_vector_store._index_manifest == IndexManifest(IDENTITY)
    assert sf1_vector_store._index_manifest.payload_complete is False
    before = dict(sf1_vector_store._records)
    sf1_vector_store._index_manifest = IndexManifest(replace(IDENTITY, model_name="different"))
    with pytest.raises(IndexIncompatibleError):
        index.index_source("source")
    assert sf1_vector_store._records == before
    assert sf1_vector_store._index_manifest.identity.model_name == "different"


def test_legacy_write_does_not_certify_preexisting_vectors(sf1_vector_store, monkeypatch):
    chunks = _seed(sf1_vector_store)
    index = CandidateIndex(_source_store(chunks), sf1_vector_store, owner_user_id="owner", embedder=EMBEDDER)
    index.index_source("source")
    assert not hasattr(sf1_vector_store, "_index_manifest")
    monkeypatch.setenv("INDEX_STRICT", "1")
    with pytest.raises(IndexLegacyUnverifiedError):
        index.index_source("source")


def test_manifest_round_trip_and_empty_write(tmp_path, sf1_vector_store):
    path = manifest_path(tmp_path / "qdrant", "collection")
    assert path == tmp_path / "collection.manifest.json"
    assert read_manifest(path) is None
    # Exercise production sidecar discovery with a memory adapter, never real Qdrant.
    sf1_vector_store.path = tmp_path / "qdrant"
    sf1_vector_store.collection = "collection"
    index = CandidateIndex(_source_store([]), sf1_vector_store, owner_user_id="owner")
    assert index.manifest_path == path
    index.index_source("source")
    assert read_manifest(path) == IndexManifest(IDENTITY, empty=True)
    assert index.candidates("API") == []
    assert index.last_search_info["index_state"] == "EMPTY"
    index.source_store = _source_store([SourceChunk("chunk", "source", "source.txt", "API", 0)])
    index.index_source("source")
    assert read_manifest(path) == IndexManifest(IDENTITY)
    assert _index(sf1_vector_store, manifest_path=path).candidates("API")
    assert not (tmp_path / "qdrant").exists()


def test_disk_manifest_rechecked_on_search_and_write(tmp_path, sf1_vector_store):
    chunks = _seed(sf1_vector_store)
    path = manifest_path(tmp_path / "qdrant", "collection")
    write_manifest(path, IndexManifest(IDENTITY))
    index = CandidateIndex(_source_store(chunks), sf1_vector_store, owner_user_id="owner", manifest_path=path)
    assert index.candidates("API")
    mismatch = IndexManifest(replace(IDENTITY, digest="different"))
    write_manifest(path, mismatch)
    with pytest.raises(IndexIncompatibleError):
        index.candidates("API")
    with pytest.raises(IndexIncompatibleError):
        index.index_source("source")
    assert read_manifest(path) == mismatch


@pytest.mark.parametrize("raw", ["{", "null", "[]", '{}', '{"schema_version":1,"identity":{}}'])
def test_malformed_manifest_fails_closed(raw, tmp_path, sf1_vector_store):
    path = tmp_path / "collection.manifest.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(IndexIncompatibleError):
        _index(sf1_vector_store, manifest_path=path).candidates("API")


def test_embedder_identity_requires_no_embedding_or_network():
    assert IDENTITY.backend == "hash"
    assert IDENTITY.digest is None
    semantic = IndexIdentity.from_embedder(OllamaEmbedder(model="example", dimension=32))
    assert semantic.backend == "ollama" and semantic.model_name == "example"
    assert semantic.dimension == 32
    assert semantic != IDENTITY


@pytest.fixture
def http_main(monkeypatch):
    import dotenv
    import app.auth.store as auth_module
    import app.storage.source_store as source_module
    import app.storage.run_store as run_module

    # Import the actual routes without creating files or reading dotenv.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    sources = SimpleNamespace(
        snapshot_id=lambda: "test-snapshot",
        chunks=lambda ids=None: [SourceChunk("chunk", "source", "source.txt", "stable API error", 0)],
    )
    monkeypatch.setattr(auth_module, "AuthStore", lambda *a: object())
    monkeypatch.setattr(source_module, "SourceStore", lambda *a: sources)
    monkeypatch.setattr(run_module, "RunStore", lambda *a: SimpleNamespace(save=lambda run: None))
    for key, value in {
        "APP_STORAGE_BACKEND": "file", "APP_ENV": "test", "VECTOR_BACKEND": "memory",
    }.items():
        monkeypatch.setenv(key, value)
    name = "app._index_identity_http_test"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app" / "main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "current_user", lambda request: {"user_id": "owner"})
    conversations = SimpleNamespace(
        create=lambda title: {"conversation_id": "conversation"},
        get=lambda cid: {"messages": []},
        add_message=lambda *a, **k: None,
    )
    monkeypatch.setattr(module, "owner_conversation_store", lambda user: conversations)
    return module


@pytest.mark.parametrize("error", [IndexIncompatibleError, IndexLegacyUnverifiedError])
def test_http_maps_typed_errors_to_503(http_main, monkeypatch, error):
    async def run(*args, **kwargs):
        raise error("injected index refusal")

    monkeypatch.setattr(http_main, "owner_pipeline", lambda *a: SimpleNamespace(run=run))
    response = TestClient(http_main.app).post("/api/chat", json={"message": "API", "provider": "fake"})
    assert response.status_code == 503
    assert response.json()["code"] == error.code


@pytest.mark.parametrize("strict", [False, True])
def test_real_pipeline_propagates_index_refusal(http_main, monkeypatch, strict):
    store = InMemoryVectorStore()
    _seed(store)
    if strict:
        monkeypatch.setenv("INDEX_STRICT", "1")
    else:
        store._index_manifest = IndexManifest(replace(IDENTITY, model_name="different"))
    monkeypatch.setattr(http_main, "_configured_vector_store", lambda: store)
    response = TestClient(http_main.app).post("/api/chat", json={"message": "API", "provider": "fake"})
    assert response.status_code == 503
    assert response.json()["code"] == ("INDEX_LEGACY_UNVERIFIED" if strict else "INDEX_INCOMPATIBLE")
