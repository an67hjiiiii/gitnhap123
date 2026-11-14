"""Offline incremental indexing, stable chunking, and scoped retrieval contracts."""
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.core.types import SourceChunk
from app.research.pipeline import ResearchPipeline
from app.retrieval import bm25_index, embeddings, hybrid
from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import LocalHashEmbedder, OllamaEmbedder
from app.retrieval.index_identity import IndexIncompatibleError, IndexManifest, IndexIdentity
from app.retrieval.text import chunk_text, contextual_text, make_chunks, normalize_text
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore, QdrantVectorStore, VectorRecord


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    for name in ("EMBEDDING_DIMENSION", "VECTOR_SIZE", "INDEX_STRICT"):
        monkeypatch.delenv(name, raising=False)


class CountingEmbedder:
    dimension = 32
    version = "counting-v1"

    def __init__(self):
        self.calls = []
        self.batches = []

    def embed(self, text):
        self.calls.append(text)
        return LocalHashEmbedder(dimension=self.dimension).embed(text)

    def embed_many(self, texts):
        self.batches.append(list(texts))
        return [self.embed(text) for text in texts]


@pytest.fixture(params=["memory", "qdrant"])
def vectors(request, tmp_path):
    if request.param == "memory":
        yield InMemoryVectorStore(vector_size=32)
    else:
        from qdrant_client import QdrantClient
        client = QdrantClient(":memory:")
        yield QdrantVectorStore(client=client, path=str(tmp_path / "qdrant"), vector_size=32)
        client.close()


def test_stable_markdown_ids_hashes_and_headers():
    text = "# First\n\nAlpha fact.\n\n# Second\n\nBeta fact.\n\n# Third\n\nGamma fact."
    before = make_chunks("policy.md", text)
    after = make_chunks("policy.md", text.replace("Beta", "Zeta"))
    assert len(before) == len(after) == 3
    assert [c.chunk_id for c in before] == [c.chunk_id for c in after]
    assert before[0].source_id != after[0].source_id
    assert [a.provenance["content_hash"] == b.provenance["content_hash"]
            for a, b in zip(before, after)] == [True, False, True]
    for chunk in before:
        assert chunk.provenance["content_hash"] == sha256(normalize_text(chunk.text).encode()).hexdigest()[:16]
    assert before[1].provenance["section_path"] == "Second"
    assert before[1].provenance["context_header"] == "Tài liệu: policy.md > Second"
    assert before[1].text == "# Second\nBeta fact."


def test_nested_sections_paragraph_order_and_sentence_boundary():
    chunks = make_chunks("rules.md", "# Rules\nIntro.\n## Giới hạn tốc độ\nMaximum 50.")
    assert chunks[1].provenance["section_path"] == "Rules > Giới hạn tốc độ"
    assert chunks[1].provenance["context_header"] == "Tài liệu: rules.md > Rules > Giới hạn tốc độ"
    assert chunk_text("First paragraph.\n\nSecond paragraph.") == ["First paragraph.", "Second paragraph."]
    paragraph = "a" * 82 + ". " + "b" * 40
    assert chunk_text(paragraph, max_chars=100) == ["a" * 82 + ".", "b" * 40]
    assert chunk_text("x" * 121, max_chars=60) == ["x" * 60, "x" * 60, "x"]
    before = make_chunks("plain.txt", "a" * 100 + "\n\nUnchanged.", max_chars=60)
    after = make_chunks("plain.txt", "a" * 160 + "\n\nUnchanged.", max_chars=60)
    assert before[-1].chunk_id == after[-1].chunk_id
    assert before[-1].provenance["content_hash"] == after[-1].provenance["content_hash"]


def test_incremental_reupload_delete_and_payload_refresh(vectors, tmp_path):
    sources = SourceStore(str(tmp_path / "sources"))
    embedder = CountingEmbedder()
    index = CandidateIndex(sources, vectors, owner_user_id="A", embedder=embedder)
    first = sources.import_text("policy.md", "# One\nAlpha.\n# Two\nBeta.\n# Three\nGamma.\n# Four\nDelta.")
    assert index.index_source(first["source_id"])["chunks_indexed"] == 4
    assert len(embedder.calls) == 4
    assert embedder.batches == [[contextual_text(c) for c in sources.chunks()]]
    # Recreating the request-scoped index must still use persisted payloads.
    index = CandidateIndex(sources, vectors, owner_user_id="A", embedder=embedder)
    result = index.index_source(first["source_id"])
    assert (result["chunks_indexed"], result["chunks_skipped"], result["chunks_deleted"]) == (0, 4, 0)
    assert len(embedder.calls) == 4
    second = sources.import_text("policy.md", "# One\nAlpha.\n# Two\nZeta.\n# Three\nGamma.\n# Four\nDelta.")
    result = index.index_source(second["source_id"])
    assert (result["chunks_indexed"], result["chunks_skipped"], result["chunks_deleted"]) == (1, 3, 0)
    assert len(embedder.calls) == 5
    assert len(index.candidates("Alpha", source_ids=[second["source_id"]])) == 4
    assert index.candidates("Alpha", source_ids=[first["source_id"]]) == []
    third = sources.import_text("policy.md", "# One\nAlpha.\n# Two\nZeta.\n# Three\nGamma.")
    result = index.index_source(third["source_id"])
    assert (result["chunks_indexed"], result["chunks_skipped"], result["chunks_deleted"]) == (0, 3, 1)
    assert len(embedder.calls) == 6  # One query embedding, no new document embeddings.
    assert vectors.count() == 3
    assert all(m.payload["content_hash"] for m in index.candidates("Alpha"))


def test_query_lru_and_single_embed_fallback(tmp_path):
    embedder = CountingEmbedder()
    embedder.embed_many = None
    sources = SourceStore(str(tmp_path / "sources"))
    source = sources.import_text("a.txt", "Alpha fact.")
    index = CandidateIndex(sources, InMemoryVectorStore(), owner_user_id="A", embedder=embedder)
    index.index_source(source["source_id"])
    embedder.calls.clear()
    index.candidates("same query")
    index.candidates("same query")
    assert embedder.calls == ["same query"]
    for i in range(256):
        index.candidates(f"query {i}")
    assert len(index._query_embeddings) == 256
    index.candidates("same query")
    assert len(embedder.calls) == 258


def test_owner_workspace_source_and_version_isolation(vectors, tmp_path):
    indexes = {}
    for owner, workspace in (("A", "1"), ("A", "2"), ("B", "1"), ("B", "2")):
        sources = SourceStore(str(tmp_path / f"sources-{owner}-{workspace}"))
        imported = sources.import_text("same.txt", "The same similar text.")
        index = CandidateIndex(sources, vectors, owner_user_id=owner,
                               embedder=LocalHashEmbedder(dimension=32), default_workspace_id=workspace)
        index.index_source(imported["source_id"])
        indexes[owner, workspace] = index
    found = indexes["A", "1"].candidates("similar text")
    assert len(found) == 1
    assert {(m.payload["owner_user_id"], m.payload["workspace_id"]) for m in found} == {("A", "1")}
    assert indexes["A", "1"].candidates("similar", source_ids=[]) == []
    vectors.upsert([VectorRecord("obsolete", LocalHashEmbedder(dimension=32).embed("similar text"),
                                {**found[0].payload, "embedding_version": "old", "chunk_id": "obsolete"})])
    assert [m.payload["chunk_id"] for m in indexes["A", "1"].candidates("similar text")] == [found[0].payload["chunk_id"]]
    assert len(indexes["A", "1"].candidates("similar text", workspace_id="2")) == 1


def test_ollama_batches_use_one_mockable_post_per_sixteen(monkeypatch):
    calls = []
    def post(url, *, json, timeout):
        calls.append((url, json, timeout))
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"embeddings": [[1, 0, 0] for _ in json["input"]]})
    monkeypatch.setattr(embeddings, "embedding_post", post)
    embedder = OllamaEmbedder(dimension=3)
    assert embedder.embed_many([str(i) for i in range(33)]) == [(1.0, 0.0, 0.0)] * 33
    assert [len(call[1]["input"]) for call in calls] == [16, 16, 1]
    assert calls[0][0] == "http://127.0.0.1:11434/api/embed"
    assert embedder.embed("single") == (1.0, 0.0, 0.0)


@pytest.mark.parametrize("vectors", [[], [[1, 0]], [[1, 0, 0], [1, 0, 0]]])
def test_ollama_rejects_invalid_batch_responses(monkeypatch, vectors):
    monkeypatch.setattr(embeddings, "embedding_post", lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"embeddings": vectors}))
    with pytest.raises(ValueError):
        OllamaEmbedder(dimension=3).embed_many(["one"])


def test_hydrates_only_matches_and_loads_fallback_lazily(tmp_path, monkeypatch):
    sources = SourceStore(str(tmp_path / "sources"))
    imported = sources.import_text("a.txt", "Alpha fact.\n\nBeta fact.")
    index = CandidateIndex(sources, InMemoryVectorStore(), owner_user_id="A")
    index.index_source(imported["source_id"])
    pipeline = ResearchPipeline(sources, None, candidate_index=index)
    ids = []
    hydrate = sources.chunks_by_ids
    def by_ids(requested, source_ids=None):
        ids.append(requested)
        return hydrate(requested, source_ids)
    monkeypatch.setattr(sources, "chunks_by_ids", by_ids)
    load = sources.chunks
    monkeypatch.setattr(sources, "chunks", lambda *a: pytest.fail("eager corpus load"))
    found = pipeline._retrieve_candidates("Alpha", None, top_k=1, min_score=0, source_ids=[imported["source_id"]])
    assert len(found) == 1
    assert ids == [[found[0].chunk_id]]
    assert sources.chunks_by_ids([found[0].chunk_id], source_ids=[]) == []
    monkeypatch.setattr(index, "candidates", lambda *a, **k: [])
    loads = []
    monkeypatch.setattr(sources, "chunks", lambda selected: (loads.append(selected), load(selected))[1])
    found = pipeline._retrieve_candidates("Alpha", None, top_k=1, min_score=0, source_ids=[imported["source_id"]])
    assert found[0].text == "Alpha fact."
    assert loads == [[imported["source_id"]]]


def test_bm25_corpus_cached_and_changed_text_rebuilds(monkeypatch):
    bm25_index._CACHE.clear()
    chunks = [SourceChunk("one", "s", "doc", "alpha beta", 0),
              SourceChunk("two", "s", "doc", "gamma delta", 1)]
    calls = []
    original = hybrid.tokens
    monkeypatch.setattr(hybrid, "tokens", lambda text: (calls.append(text), original(text))[1])
    first = hybrid.bm25_rank("alpha", chunks)
    second = hybrid.bm25_rank("alpha", list(reversed(chunks)))
    assert [(c.chunk_id, c.score) for c in first] == [(c.chunk_id, c.score) for c in second] == [("one", 0.693147)]
    assert calls.count("alpha beta") == calls.count("gamma delta") == 1
    hybrid.bm25_rank("alpha", [replace(chunks[0], text="alpha edited"), chunks[1]])
    assert calls.count("gamma delta") == 2


def test_bm25_searches_context_but_returns_raw_text():
    chunks = make_chunks("Speed limit", "Unrelated body.")
    found = hybrid.bm25_rank("Speed", chunks)
    assert len(found) == 1 and found[0].text == "Unrelated body."


def test_effective_dimension_and_validation(monkeypatch):
    assert embeddings.effective_dimension() == embeddings.make_embedder().dimension == 768
    monkeypatch.setenv("VECTOR_SIZE", "32")
    assert embeddings.effective_dimension() == embeddings.make_embedder().dimension == 32
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1024")
    embedder = embeddings.make_embedder(768)
    assert embeddings.effective_dimension(768) == embedder.dimension == 1024
    with pytest.raises(ValueError, match="1024.*768"):
        embeddings.validate_embedding_config(embedder, 768)
    embeddings.validate_embedding_config(embedder, 1024)


def test_header_identity_rejects_pre_header_manifest():
    embedder = LocalHashEmbedder()
    store = InMemoryVectorStore()
    current = IndexIdentity.from_embedder(embedder)
    assert current.embedding_version.endswith("+hdr1")
    store._index_manifest = IndexManifest(replace(current, embedding_version=current.embedding_version.removesuffix("+hdr1")))
    with pytest.raises(IndexIncompatibleError):
        CandidateIndex(None, store, owner_user_id="A", embedder=embedder).candidates("alpha")


def test_existing_qdrant_collection_dimension_is_validated(tmp_path):
    from qdrant_client import QdrantClient
    client = QdrantClient(":memory:")
    try:
        QdrantVectorStore(client=client, path=str(tmp_path / "qdrant"), vector_size=768)
        with pytest.raises(ValueError, match="1024.*768"):
            QdrantVectorStore(client=client, path=str(tmp_path / "qdrant"), vector_size=1024)
    finally:
        client.close()
