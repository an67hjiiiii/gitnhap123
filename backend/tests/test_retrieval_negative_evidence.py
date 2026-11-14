"""Measure candidate recall separately from the authorization of cited evidence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.types import ProviderResult, RunMetrics, SourceChunk
from app.research.pipeline import ResearchPipeline
from app.research.vanilla import answer_vanilla
from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import LocalHashEmbedder
from app.review.schemas import Requirement, ReviewCase, Verdict
from app.review_adapters.pipeline_engine import PipelineReviewEngine
from app.storage.vector_store import InMemoryVectorStore


CASES = json.loads(
    (Path(__file__).parent / "fixtures/retrieval_seeded/cases.json").read_text(encoding="utf-8")
)
TOP_K = 4
MIN_SCORE = 0.18  # The current runtime default, pinned for this measurement.
RECALL_FLOOR = 0.95  # Measured baseline 1.0, with a 0.05 margin.
ABSENT = [case for case in CASES if case["kind"] == "absent"]


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    monkeypatch.setenv("INDEX_STRICT", "1")


def _chunks(case):
    return [
        SourceChunk(item["id"], item["source_id"], f"{item['source_id']}.txt", item["text"], i)
        for i, item in enumerate(case["chunks"])
    ]


def _source_store(chunks):
    return SimpleNamespace(
        source=lambda sid: {"source_id": sid, "status": "READY"},
        chunks=lambda ids: [chunk for chunk in chunks if chunk.source_id in ids],
    )


def _retrieve(case, *, indexed=True):
    chunks = _chunks(case)
    store = _source_store(chunks)
    source_ids = list(dict.fromkeys(chunk.source_id for chunk in chunks))
    index = CandidateIndex(
        store, InMemoryVectorStore(), owner_user_id="seed-owner", embedder=LocalHashEmbedder(),
    )
    # Index through the public writer so strict identity checking needs no disk manifest.
    for source_id in source_ids:
        index.index_source(source_id)
    if not indexed:
        index.vector_store.delete(f"seed-owner:{chunk.chunk_id}" for chunk in chunks)
    pipeline = ResearchPipeline(store, None, candidate_index=index, retrieval_backend="vector")
    trace = {}
    found = pipeline._retrieve_candidates(
        case["query"], chunks, top_k=TOP_K, min_score=MIN_SCORE,
        source_ids=source_ids, fallback_trace=trace,
    )
    return found, trace


def test_seeded_truth_is_explicit_and_well_formed():
    assert len(CASES) >= 12
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert {case["kind"] for case in CASES} == {
        "present", "absent", "near_miss_conflicting", "distractor_heavy",
    }
    for case in CASES:
        ids = [item["id"] for item in case["chunks"]]
        assert ids and len(ids) == len(set(ids))
        assert case["query"] and all(item["source_id"] and item["text"] for item in case["chunks"])
        assert set(case["relevant_ids"]) <= set(ids)
        if case["kind"] in {"present", "distractor_heavy"}:
            assert case["relevant_ids"]
        else:
            assert case["relevant_ids"] == []
        if case["kind"] == "distractor_heavy":
            assert len(ids) > TOP_K


def test_recall_at_four_prints_all_seeded_cases():
    recalls = []
    print("\ncase | kind | retrieved ids | hit | recall@4")
    for case in CASES:
        found, _ = _retrieve(case)
        retrieved = [chunk.chunk_id for chunk in found]
        relevant = set(case["relevant_ids"])
        hits = len(relevant.intersection(retrieved))
        recall = hits / len(relevant) if relevant else None
        print(f"{case['id']} | {case['kind']} | {','.join(retrieved) or '-'} | "
              f"{hits} | {recall if recall is not None else 'n/a'}")
        assert len(retrieved) <= TOP_K
        assert len(retrieved) == len(set(retrieved))
        assert set(retrieved) <= {item["id"] for item in case["chunks"]}
        assert all(chunk.score >= MIN_SCORE for chunk in found)
        if case["kind"] == "present":
            recalls.append(recall)
    measured = sum(recalls) / len(recalls)
    print(f"present macro recall@4={measured:.3f}; floor={RECALL_FLOOR:.3f}")
    assert measured >= RECALL_FLOOR


def test_absent_false_support_measurement():
    # Retrieval is a candidate selector, so count returned chunks as potential
    # false support; this does not claim they became validated review evidence.
    counts = {}
    for case in ABSENT:
        found, _ = _retrieve(case)
        counts[case["id"]] = len(found)
        assert all(chunk.score >= MIN_SCORE for chunk in found)
    print(f"\nabsent false-support retrievals (min_score={MIN_SCORE}): {counts}")
    print(f"absent false-support chunks={sum(counts.values())}; "
          f"affected cases={sum(count > 0 for count in counts.values())}/{len(ABSENT)}")
    assert counts == {
        "absent_retention_duration": 2,
        "absent_backup_region": 2,
        "absent_session_vi": 1,
        "absent_unrelated": 0,
    }


@pytest.mark.xfail(
    strict=False,
    reason="SUSPECTED DEFECT: min_score accepts topical chunks that do not contain the requested fact",
)
def test_absent_facts_have_no_support_candidates():
    assert {case["id"]: len(_retrieve(case)[0]) for case in ABSENT} == {
        case["id"]: 0 for case in ABSENT
    }


def test_empty_index_lexical_fallback_preserves_present_fact():
    case = next(case for case in CASES if case["id"] == "present_retention")
    found, trace = _retrieve(case, indexed=False)
    assert [chunk.chunk_id for chunk in found] == case["relevant_ids"]
    assert trace == {
        "backend": "lexical", "reason": "no_vector_candidate_met_min_score", "candidate_count": 1,
    }


def test_unretrieved_citation_never_becomes_review_evidence():
    case = next(case for case in CASES if case["id"] == "present_notifications")
    chunks = _chunks(case)
    pipeline = SimpleNamespace(source_store=_source_store(chunks))
    # The SMS chunk exists in a selected source but was not retrieved. Unknown
    # IDs and uncited retrieved IDs must also fail to authorize evidence.
    result = {"status": "COMPLETE", "task_results": [{
        "answer": "Notifications use SMS [notify_sms] [invented].",
        "citations": ["notify_sms", "invented"], "evidence_ids": ["notify_email"],
    }]}
    sources = [chunk.source_id for chunk in chunks]
    assert PipelineReviewEngine._evidence(pipeline, result, sources) == []
    result["task_results"][0]["citations"].extend(["notify_email", "notify_email"])
    evidence = PipelineReviewEngine._evidence(pipeline, result, sources)
    assert [item.evidence_id for item in evidence] == ["notify_email"]
    assert evidence[0].excerpt == chunks[0].text


def test_vanilla_rejects_a_synthetic_outside_evidence_citation():
    chunks = _chunks(next(case for case in CASES if case["id"] == "present_notifications"))

    async def generate(*, system, user):
        return ProviderResult(text=json.dumps({
            "status": "COMPLETE", "answer": "SMS is supported [notify_sms].",
            "citations": ["notify_sms"], "missing_information": [],
        }))

    metrics = RunMetrics()
    task = asyncio.run(answer_vanilla(
        SimpleNamespace(generate=generate), "Which notification channels?", chunks[:1], metrics,
    ))
    assert task.status == "PARTIAL"
    assert task.citations == []
    assert task.invalid_citations == ["notify_sms"]
    assert task.evidence_ids == ["notify_email"]
    assert (metrics.citations_valid, metrics.citations_emitted) == (0, 1)
    pipeline = SimpleNamespace(source_store=_source_store(chunks))
    assert PipelineReviewEngine._evidence(
        pipeline, {"task_results": [asdict(task)]}, [chunk.source_id for chunk in chunks],
    ) == []


@pytest.mark.parametrize("case", ABSENT, ids=lambda case: case["id"])
def test_fully_absent_evidence_maps_to_not_found(case):
    chunks = _chunks(case)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    review = ReviewCase(
        id=case["id"], owner_user_id="seed-owner", title="Absent evidence",
        request_text=case["query"], source_ids=list(dict.fromkeys(c.source_id for c in chunks)),
        created_at=now, updated_at=now,
    )
    requirement = Requirement(
        id="requirement", case_id=review.id, text=case["query"], origin="USER", confirmed=True, order=0,
    )
    calls = []

    async def run(query, *, source_ids, condition="A"):
        calls.append((query, source_ids))
        # Exercise the real answerer's empty-evidence path; no provider call.
        task = await answer_vanilla(None, query, [], RunMetrics())
        return {"status": task.status, "task_results": [asdict(task)]}

    pipeline = SimpleNamespace(run=run, source_store=_source_store(chunks))
    events = []
    finding, = PipelineReviewEngine(pipeline).run(
        review, [requirement], None, lambda *event: events.append(event),
    )
    assert calls == [(requirement.text, review.source_ids)]
    assert finding.verdict == Verdict.NOT_FOUND
    assert finding.verdict != Verdict.DEVIATES
    assert finding.evidence == []
    assert [name for name, _ in events] == ["task.started", "finding.created"]
