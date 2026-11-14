"""Deterministic citation checks, with no storage or provider side effects."""

from types import SimpleNamespace
import unicodedata

import pytest

from app.review_adapters.citation_check import (
    citations_in_retrieved, excerpt_in_chunk, numbers_in_answer_supported,
)
from app.review_adapters.pipeline_engine import PipelineReviewEngine


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")


@pytest.mark.parametrize("excerpt,chunk,expected", [
    ("giữ 30 ngày", "Logs: giữ\n 30\tngày.", True),
    (unicodedata.normalize("NFD", "giữ"), "giữ 30 ngày", True),
    ("30 days", "130 days", True),  # The contract is substring containment.
    ("30 days", "30 hours", False),
    ("Days", "days", False),
    ("", "anything", True),
    ("anything", "", False),
])
def test_excerpt_normalization(excerpt, chunk, expected):
    assert excerpt_in_chunk(excerpt, chunk) is expected


@pytest.mark.parametrize("answer,evidence,missing", [
    ("Retain 30 days and 2 GB", ["Retain thirty days", "Limit 2048 MB"], []),
    ("Retain 12 months", ["Retain 1 year"], []),
    ("Limit 1000 characters", ["Limit 1.000 ký tự"], []),
    ("Retain 30 days and 2 GB", ["Retain 30 hours", "Limit 1 GB"],
     ["number:30 days", "number:2 GB"]),
    ("Retain 30 days and 30 days", [], ["number:30 days"]),
    ("Retain 30 days", ["Retain 30", "days"], ["number:30 days"]),
    ("No quantities", [], []),
])
def test_unsupported_answer_quantities(answer, evidence, missing):
    assert list(map(str, numbers_in_answer_supported(answer, iter(evidence)))) == missing


def test_citations_outside_retrieval_are_stable_and_distinct():
    assert citations_in_retrieved(["c2", "c1", "c2", "c3"], iter(["c1"])) == ["c2", "c3"]


def test_engine_filters_unretrieved_unknown_and_out_of_scope_citations(monkeypatch):
    def chunk(cid, source):
        return SimpleNamespace(chunk_id=cid, source_id=source, text="30 days", provenance={})

    pipeline = SimpleNamespace(source_store=SimpleNamespace(
        chunks=lambda ids: [chunk("valid", "selected"), chunk("unretrieved", "selected"),
                            chunk("outside", "other")]))
    result = {"task_results": [{"citations": ["valid", "unretrieved", "unknown", "outside"],
                                "evidence_ids": ["valid", "unknown", "outside"]}]}
    evidence = PipelineReviewEngine._evidence(pipeline, result, ["selected"])
    assert [item.evidence_id for item in evidence] == ["valid"]
    assert evidence[0].excerpt == "30 days"
    # Exercise the defensive branch even though current excerpts equal chunk.text.
    monkeypatch.setattr("app.review_adapters.citation_check.excerpt_in_chunk", lambda *args: False)
    assert PipelineReviewEngine._evidence(pipeline, result, ["selected"]) == []
