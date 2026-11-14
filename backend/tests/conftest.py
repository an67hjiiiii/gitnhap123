from __future__ import annotations

import pytest

from app.research.pipeline import ResearchPipeline
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore


@pytest.fixture(autouse=True)
def _disable_review_rate_limiter_for_existing_tests(monkeypatch):
    monkeypatch.setenv("REVIEW_RATE_RUNS_PER_MIN", "0")
    monkeypatch.setenv("REVIEW_RATE_READS_PER_MIN", "0")


@pytest.fixture
def sf1_data_dir(tmp_path):
    """A per-test root for file-backed source and run stores."""
    root = tmp_path / "sf1-data"
    root.mkdir()
    return root


@pytest.fixture
def sf1_fake_provider_env(monkeypatch):
    """Select the local fake provider and a profile that permits all conditions."""
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "dev")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    return monkeypatch


@pytest.fixture
def sf1_vector_store():
    return InMemoryVectorStore()


@pytest.fixture
def sf1_pipeline_factory(sf1_data_dir):
    def make(*, candidate_index=None, retrieval_backend="lexical", run_store=None):
        return ResearchPipeline(
            SourceStore(str(sf1_data_dir / "sources")),
            run_store or RunStore(str(sf1_data_dir / "runs")),
            candidate_index=candidate_index,
            retrieval_backend=retrieval_backend,
        )

    return make
