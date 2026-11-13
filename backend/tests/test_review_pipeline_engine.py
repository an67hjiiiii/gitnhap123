from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.core.types import TaskResult
from app.research import pipeline as research_module
from app.retrieval.candidate_index import CandidateIndex
from app.review.schemas import Confidence, Decision, Requirement, ReviewCase, Verdict
from app.review_adapters import PipelineReviewEngine
from app.review_adapters import pipeline_engine as adapter_module


@pytest.fixture
def setup_review(sf1_fake_provider_env, sf1_pipeline_factory, sf1_vector_store, monkeypatch):
    pipeline = sf1_pipeline_factory()
    source = pipeline.source_store.import_text("selected.txt", "Authentication requires a valid token.")
    foreign = pipeline.source_store.import_text("foreign.txt", "Foreign authentication requirements.")
    pipeline.candidate_index = CandidateIndex(
        pipeline.source_store, sf1_vector_store, owner_user_id="owner-1",
    )
    pipeline.candidate_index.index_source(source["source_id"])
    pipeline.candidate_index.index_source(foreign["source_id"])
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = ReviewCase(
        id="case-1", owner_user_id="owner-1", title="Review",
        request_text="Require authentication. Validate tokens!", source_ids=[source["source_id"]],
        created_at=now, updated_at=now,
    )
    chunk = pipeline.source_store.chunks(case.source_ids)[0]
    foreign_chunk = pipeline.source_store.chunks([foreign["source_id"]])[0]
    calls = []
    original = pipeline.run

    async def record(query, **kwargs):
        calls.append((query, kwargs))
        return await original(query, **kwargs)

    monkeypatch.setattr(pipeline, "run", record)
    return pipeline, case, chunk, foreign_chunk, calls


def requirements(case, count=1):
    return [
        Requirement(id=f"r{i}", case_id=case.id, text=f"Authentication requirement {i}",
                    origin="USER", confirmed=True, order=i)
        for i in range(count)
    ]


def control_result(monkeypatch, status, citations=()):
    async def answer(provider, query, evidence, metrics, reply_language=None):
        if status == "FAILED":
            raise RuntimeError("Controlled pipeline failure")
        return TaskResult(
            task_id="T1", domain="general", status=status, answer="Controlled answer",
            evidence_ids=[chunk.chunk_id for chunk in evidence], citations=list(citations),
        )

    monkeypatch.setattr(research_module, "answer_vanilla", answer)


@pytest.mark.parametrize("status,cited,verdict", [
    ("COMPLETE", True, Verdict.SATISFIED),
    ("COMPLETE", False, Verdict.UNDETERMINED),
    ("PARTIAL", True, Verdict.PARTIAL),
    ("NO_EVIDENCE", False, Verdict.NOT_FOUND),
    ("FAILED", False, Verdict.UNDETERMINED),
])
def test_pipeline_status_mapping(setup_review, monkeypatch, status, cited, verdict):
    pipeline, case, chunk, _, calls = setup_review
    control_result(monkeypatch, status, [chunk.chunk_id] if cited else [])
    events = []
    reqs = requirements(case)
    finding, = PipelineReviewEngine(pipeline).run(case, reqs, None, lambda *args: events.append(args))
    assert finding.verdict == verdict
    assert finding.confidence == Confidence.L1
    assert finding.review == Decision.NONE
    assert reqs[0].confirmed is True
    assert calls == [(reqs[0].text, {"source_ids": case.source_ids})]
    assert [event[0] for event in events] == ["task.started", "finding.created"]
    assert events[1][1] == finding.model_dump(mode="json")


def test_only_cited_retrieved_scoped_chunks_become_evidence(setup_review, monkeypatch):
    pipeline, case, chunk, foreign_chunk, _ = setup_review
    extra = pipeline.source_store.import_text("extra.txt", "Authentication also requires audit logging.")
    case.source_ids.append(extra["source_id"])
    control_result(monkeypatch, "COMPLETE", [chunk.chunk_id, chunk.chunk_id, foreign_chunk.chunk_id, "unknown"])
    finding, = PipelineReviewEngine(pipeline).run(case, requirements(case), None, lambda _: None)
    assert [item.evidence_id for item in finding.evidence] == [chunk.chunk_id]
    assert finding.evidence[0].source_id == chunk.source_id
    assert finding.evidence[0].locator == chunk.chunk_id
    assert finding.evidence[0].excerpt == chunk.text


@pytest.mark.parametrize("budget,expected_calls", [
    ({"max_requirements": 1}, 1), ({"max_requirements": 0}, 0), ({"max_seconds": 0}, 0),
])
def test_budget_skips_without_pipeline_calls(setup_review, monkeypatch, budget, expected_calls):
    pipeline, case, _, _, calls = setup_review
    control_result(monkeypatch, "NO_EVIDENCE")
    events = []
    reqs = requirements(case, 3)
    reqs[0].confirmed = False
    findings = PipelineReviewEngine(pipeline).run(case, reqs, budget, lambda *args: events.append(args))
    assert len(calls) == expected_calls
    assert [f.requirement_id for f in findings] == ["r1", "r2"]
    assert [f.verdict for f in findings] == (
        [Verdict.NOT_FOUND] * expected_calls + [Verdict.SKIPPED_BUDGET] * (2 - expected_calls)
    )
    assert sum(name == "budget.skipped" for name, _ in events) == 2 - expected_calls
    assert sum(name == "finding.created" for name, _ in events) == 2


def test_elapsed_budget_checked_between_calls(setup_review, monkeypatch):
    pipeline, case, _, _, calls = setup_review
    control_result(monkeypatch, "NO_EVIDENCE")
    ticks = iter([10, 10, 12])
    # Replace only the adapter's clock, leaving the pipeline's time module intact.
    class Clock:
        monotonic = staticmethod(lambda: next(ticks))

    monkeypatch.setattr(adapter_module, "time", Clock)
    findings = PipelineReviewEngine(pipeline).run(
        case, requirements(case, 2), {"max_seconds": 1}, lambda _: None,
    )
    assert [f.verdict for f in findings] == [Verdict.NOT_FOUND, Verdict.SKIPPED_BUDGET]
    assert len(calls) == 1


def test_exception_isolated_and_sequential_execution_continues(setup_review, monkeypatch):
    pipeline, case, _, _, calls = setup_review
    control_result(monkeypatch, "NO_EVIDENCE")
    original = pipeline.run
    trace = []

    async def sometimes_fails(query, **kwargs):
        trace.append(("start", query))
        if query.endswith("0"):
            trace.append(("error", query))
            raise RuntimeError("Controlled failure")
        result = await original(query, **kwargs)
        trace.append(("end", query))
        return result

    monkeypatch.setattr(pipeline, "run", sometimes_fails)
    delivered = []
    findings = PipelineReviewEngine(pipeline).run(case, requirements(case, 2), None, delivered.append)
    assert [f.verdict for f in findings] == [Verdict.UNDETERMINED, Verdict.NOT_FOUND]
    assert delivered == findings
    assert [event for event, _ in trace] == ["start", "error", "start", "end"]
    assert len(calls) == 1


def test_injected_owner_factory_and_source_getter(setup_review, monkeypatch):
    pipeline, case, _, foreign_chunk, calls = setup_review
    control_result(monkeypatch, "NO_EVIDENCE")
    owners = []

    def factory(owner):
        owners.append(owner)
        return pipeline

    engine = PipelineReviewEngine(
        pipeline_factory=factory, owner_user_id=lambda c: c.owner_user_id,
        source_ids_getter=lambda c: [*c.source_ids, foreign_chunk.source_id],
    )
    engine.run(case, requirements(case), None, lambda _: None)
    assert owners == [case.owner_user_id]
    assert calls[0][1]["source_ids"] == case.source_ids
    engine = PipelineReviewEngine(pipeline, source_ids_getter=lambda c: [])
    engine.run(case, requirements(case), None, lambda _: None)
    assert calls[1][1]["source_ids"] == []


def test_wrong_owner_fails_closed(setup_review):
    pipeline, case, _, _, calls = setup_review
    finding, = PipelineReviewEngine(pipeline, owner_user_id="other").run(
        case, requirements(case), None, lambda _: None,
    )
    assert finding.verdict == Verdict.UNDETERMINED
    assert calls == []


def test_async_entry_and_sync_loop_guard(setup_review, monkeypatch):
    pipeline, case, _, _, calls = setup_review
    control_result(monkeypatch, "NO_EVIDENCE")
    engine = PipelineReviewEngine(pipeline)

    async def run():
        with pytest.raises(RuntimeError, match="run_async"):
            engine.run(case, requirements(case), None, lambda _: None)
        return await engine.run_async(case, requirements(case), None, lambda _: None)

    findings = asyncio.run(run())
    assert findings[0].verdict == Verdict.NOT_FOUND
    assert len(calls) == 1


def test_proposals_are_deterministic_deduplicated_and_capped(setup_review):
    pipeline, case, _, _, calls = setup_review
    case.request_text = "- Require tokens. Validate access!\n* require tokens?\n1. Keep logs\n• Reject expired tokens"
    engine = PipelineReviewEngine(pipeline)
    proposed = engine.propose_requirements(case)
    assert proposed == engine.propose_requirements(case)
    assert [r.text for r in proposed] == ["Require tokens", "Validate access", "Keep logs", "Reject expired tokens"]
    assert all(r.origin == "AI_PROPOSED" and not r.confirmed and r.case_id == case.id for r in proposed)
    assert [r.order for r in proposed] == list(range(4))
    case.request_text = "\n".join(f"- Requirement {i}" for i in range(20))
    assert len(engine.propose_requirements(case)) == 12
    case.request_text = " \n- \n"
    assert engine.propose_requirements(case) == []
    assert calls == []
