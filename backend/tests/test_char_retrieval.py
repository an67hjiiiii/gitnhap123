from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.types import SourceChunk
from app.research.pipeline import ResearchPipeline
from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import LocalHashEmbedder
from app.storage.vector_store import InMemoryVectorStore, VectorRecord


GOLDEN_PATH = Path(__file__).parent / "fixtures" / "sf1" / "retrieve_candidates.golden.json"


def _chunk(identifier, source_id, text):
    return SourceChunk(
        chunk_id=identifier,
        source_id=source_id,
        source_name=f"{source_id}.txt",
        text=text,
        index=0,
    )


@pytest.mark.parametrize("case", json.loads(GOLDEN_PATH.read_text(encoding="utf-8")), ids=lambda case: case["name"])
def test_vector_retrieval_matches_golden(case, sf1_vector_store):
    embedder = LocalHashEmbedder()
    chunks = [_chunk(item["id"], item["source_id"], item["text"]) for item in case["chunks"]]
    sf1_vector_store.upsert(
        VectorRecord(
            id=f"owner:{chunk.chunk_id}",
            vector=embedder.embed(chunk.text),
            payload={"owner_user_id": "owner", "source_id": chunk.source_id, "chunk_id": chunk.chunk_id},
        )
        for chunk in chunks
    )
    index = CandidateIndex(None, sf1_vector_store, owner_user_id="owner", embedder=embedder)
    pipeline = ResearchPipeline(None, None, candidate_index=index, retrieval_backend="vector")

    found = pipeline._retrieve_candidates(
        case["query"], chunks, top_k=4, min_score=0.0, source_ids=None
    )
    assert [chunk.chunk_id for chunk in found] == case["expected_ids"]
    assert [round(chunk.score, 6) for chunk in found] == case["expected_scores"]


def test_empty_vector_search_uses_lexical_fallback(sf1_vector_store):
    embedder = LocalHashEmbedder()
    index = CandidateIndex(None, sf1_vector_store, owner_user_id="owner", embedder=embedder)
    pipeline = ResearchPipeline(None, None, candidate_index=index, retrieval_backend="vector")
    chunks = [_chunk("lexical-1", "source-1", "The API returns a stable error response.")]
    trace = {}

    found = pipeline._retrieve_candidates(
        "What API error response is stable?",
        chunks,
        top_k=3,
        min_score=0.0,
        source_ids=None,
        fallback_trace=trace,
    )

    assert [chunk.chunk_id for chunk in found] == ["lexical-1"]
    assert trace == {
        "backend": "lexical",
        "reason": "no_vector_candidate_met_min_score",
        "candidate_count": 1,
    }


def test_source_store_none_selection_loads_chunks_from_all_sources(sf1_data_dir):
    from app.storage.source_store import SourceStore

    source_store = SourceStore(str(sf1_data_dir / "all-sources"))
    first = source_store.import_text("first.txt", "First source has a unique apple fact.")
    second = source_store.import_text("second.txt", "Second source has a unique orange fact.")

    selected = source_store.chunks(None)

    assert {chunk.source_id for chunk in selected} == {first["source_id"], second["source_id"]}


@pytest.mark.xfail(strict=False, reason="SUSPECTED DEFECT: vector candidate filtering does not constrain embedding_version")
def test_qdrant_owner_filter_includes_embedding_version():
    class MatchValue:
        def __init__(self, value):
            self.value = value

    class FieldCondition:
        def __init__(self, key, match):
            self.key = key
            self.match = match

    class Filter:
        def __init__(self, must):
            self.must = must

    class Models:
        FieldCondition = FieldCondition
        MatchValue = MatchValue
        Filter = Filter

    from app.storage.vector_store import QdrantVectorStore

    store = QdrantVectorStore(client=object(), models=Models)
    query_filter = store._owner_filter("owner", None)
    conditions = {condition.key: condition.match.value for condition in query_filter.must}

    assert conditions["embedding_version"] == "local-hash-embedding-v1"
