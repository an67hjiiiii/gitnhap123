from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

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
    assert calls == [(reqs[0].text, {"source_ids": case.source_ids, "condition": "A"})]
    expected_events = ["task.started", "pipeline.trace", "finding.created"]
    if status == "FAILED":  # was: no task.failed; now a stable-coded failure event precedes the finding
        expected_events = ["task.started", "pipeline.trace", "task.failed", "finding.created"]
    assert [event[0] for event in events] == expected_events
    assert events[-1][1] == finding.model_dump(mode="json")


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


def add_cited_excerpts(pipeline, case, texts):
    chunks = []
    for index, text in enumerate(texts):
        source = pipeline.source_store.import_text(f"verdict-{index}.txt", text)
        case.source_ids.append(source["source_id"])
        pipeline.candidate_index.index_source(source["source_id"])
        chunks.extend(pipeline.source_store.chunks([source["source_id"]]))
    return chunks


@pytest.mark.parametrize("status,text,expected", [
    ("COMPLETE", "Authentication logs retained for 180 days", Verdict.SATISFIED),
    ("COMPLETE", "Authentication logs retained for 90 days", Verdict.DEVIATES),
    ("PARTIAL", "Authentication logs retained for 180 days", Verdict.PARTIAL),
    ("PARTIAL", "Authentication logs retained for 90 days", Verdict.DEVIATES),
    ("NO_EVIDENCE", "Authentication logs retained for 90 days", Verdict.NOT_FOUND),
    ("FAILED", "Authentication logs retained for 90 days", Verdict.UNDETERMINED),
    ("COMPLETE", "Authentication backups retained for 90 days", Verdict.NOT_FOUND),
    ("PARTIAL", "Authentication backups retained for 90 days", Verdict.NOT_FOUND),
])
def test_evidence_backed_status_mapping(setup_review, monkeypatch, status, text, expected):
    pipeline, case, _, _, _ = setup_review
    chunks = add_cited_excerpts(pipeline, case, [text])
    control_result(monkeypatch, status, [c.chunk_id for c in chunks])
    reqs = requirements(case)
    reqs[0].text = "retain logs for 180 days"
    events = []
    finding, = PipelineReviewEngine(pipeline).run(case, reqs, None, lambda *args: events.append(args))
    assert finding.verdict == expected
    assert finding.confidence == Confidence.L1
    conflicts = [payload for name, payload in events if name == "verdict.conflict"]
    assert bool(conflicts) == (expected == Verdict.DEVIATES)
    if expected == Verdict.DEVIATES:
        assert finding.evidence and finding.evidence[0].excerpt == text
        assert conflicts[0]["conflicting_evidence_ids"] == [chunks[0].chunk_id]
        assert conflicts[0]["code"] == "CONFLICTING_CLAIM"
        assert "180 days" in str(conflicts[0]["params"])
        assert "90 days" in str(conflicts[0]["params"])
    assert events[-1] == ("finding.created", finding.model_dump(mode="json"))


def test_mixed_evidence_lists_conflict_first_and_keeps_support(setup_review, monkeypatch):
    pipeline, case, _, _, _ = setup_review
    chunks = add_cited_excerpts(pipeline, case, [
        "Authentication logs retained for 180 days",
        "Authentication logs retained for 90 days",
    ])
    control_result(monkeypatch, "COMPLETE", [c.chunk_id for c in chunks])
    reqs = requirements(case)
    reqs[0].text = "retain logs for 180 days"
    delivered = []
    engine = PipelineReviewEngine(pipeline)
    finding, = engine.run(case, reqs, None, delivered.append)
    assert finding.verdict == Verdict.DEVIATES
    assert [e.evidence_id for e in finding.evidence] == [chunks[1].chunk_id, chunks[0].chunk_id]
    assert delivered == [finding]
    repeated, = engine.run(case, reqs, None, lambda _: None)
    assert repeated == finding


@pytest.mark.parametrize("text,evidence_text", [
    ("Mật khẩu tối thiểu 12 ký tự", "Mật khẩu có ít nhất 8 ký tự"),
    ("Services must not store plaintext passwords", "Services must store plaintext passwords"),
])
def test_bilingual_and_polarity_conflicts_in_engine(setup_review, monkeypatch, text, evidence_text):
    pipeline, case, _, _, _ = setup_review
    chunks = add_cited_excerpts(pipeline, case, [evidence_text])
    control_result(monkeypatch, "PARTIAL", [c.chunk_id for c in chunks])
    reqs = requirements(case)
    reqs[0].text = text
    finding, = PipelineReviewEngine(pipeline).run(case, reqs, None, lambda _: None)
    assert finding.verdict == Verdict.DEVIATES
    assert [e.excerpt for e in finding.evidence] == [evidence_text]


@pytest.mark.parametrize("status,expected", [
    ("COMPLETE", Verdict.UNDETERMINED), ("PARTIAL", Verdict.NOT_FOUND),
    ("NO_EVIDENCE", Verdict.NOT_FOUND),
])
def test_uncited_conflicts_cannot_produce_deviates(setup_review, monkeypatch, status, expected):
    pipeline, case, _, _, _ = setup_review
    add_cited_excerpts(pipeline, case, ["Authentication logs retained for 90 days"])
    control_result(monkeypatch, status, [])
    reqs = requirements(case)
    reqs[0].text = "retain logs for 180 days"
    finding, = PipelineReviewEngine(pipeline).run(case, reqs, None, lambda _: None)
    assert finding.verdict == expected
    assert finding.evidence == []


def test_missing_excerpt_cannot_cover_required_slot(setup_review, monkeypatch):
    pipeline, case, _, _, _ = setup_review
    chunk, = add_cited_excerpts(pipeline, case, ["Logs retained for 180 days"])
    control_result(monkeypatch, "COMPLETE", [chunk.chunk_id])
    engine = PipelineReviewEngine(pipeline)
    original = engine._evidence

    def without_excerpt(*args):
        return [item.model_copy(update={"excerpt": ""}) for item in original(*args)]

    monkeypatch.setattr(engine, "_evidence", without_excerpt)
    reqs = requirements(case)
    reqs[0].text = "retain logs for 180 days"
    finding, = engine.run(case, reqs, None, lambda _: None)
    assert finding.verdict == Verdict.NOT_FOUND
    assert finding.evidence == []


@pytest.mark.parametrize("failure_stage", ["pipeline", "evidence", "assessment"])
def test_unexpected_exception_emits_diagnostics_and_continues(
    sf1_fake_provider_env, monkeypatch, caplog, failure_stage,
):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = ReviewCase(
        id="error-case", owner_user_id="owner-1", title="Retention",
        request_text="Retention", source_ids=["source-1"],
        created_at=now, updated_at=now,
    )
    chunk = SimpleNamespace(
        chunk_id="chunk-1", source_id="source-1", text="Logs retained for 180 days",
        provenance={},
    )
    calls = []

    def fail(*args):
        raise RuntimeError("Controlled adapter failure")

    async def run(query, *, source_ids, condition="A"):
        calls.append(query)
        if len(calls) == 2:
            return {"status": "NO_EVIDENCE", "task_results": []}
        if failure_stage == "pipeline":
            fail()
        return {"status": "COMPLETE", "task_results": [{
            "citations": [chunk.chunk_id], "evidence_ids": [chunk.chunk_id],
        }]}

    def chunks(source_ids):
        if failure_stage == "evidence" and len(calls) == 1:
            fail()
        return [chunk]

    if failure_stage == "assessment":
        monkeypatch.setattr(adapter_module, "assess", fail)
    pipeline = SimpleNamespace(run=run, source_store=SimpleNamespace(chunks=chunks))
    reqs = requirements(case, 2)
    reqs[0].text = "retain logs for 180 days"
    events = []
    findings = PipelineReviewEngine(pipeline).run(
        case, reqs, None, lambda *args: events.append(args),
    )
    assert calls == [req.text for req in reqs]
    assert [finding.verdict for finding in findings] == [Verdict.UNDETERMINED, Verdict.NOT_FOUND]
    assert findings[0].evidence == []
    first_trace = [] if failure_stage == "pipeline" else ["pipeline.trace"]
    assert [name for name, _ in events] == [
        "task.started", *first_trace, "task.failed", "finding.created",
        "task.started", "pipeline.trace", "finding.created",
    ]
    assert events[1 + len(first_trace)][1] == {
        "case_id": case.id, "requirement_id": reqs[0].id,
        "error_type": "UNKNOWN", "error": "Requirement execution failed",
    }
    assert "Controlled adapter failure" in caplog.text
    assert "RuntimeError" not in str(events[1 + len(first_trace)][1])
    assert events[2 + len(first_trace)][1] == findings[0].model_dump(mode="json")


@pytest.mark.parametrize("status,texts,expected", [
    ("COMPLETE", ["Logs retained for 180 days"], Verdict.SATISFIED),
    ("PARTIAL", ["Logs retained for 180 days"], Verdict.PARTIAL),
    ("NO_EVIDENCE", ["Logs retained for 90 days"], Verdict.NOT_FOUND),
    ("FAILED", ["Logs retained for 90 days"], Verdict.UNDETERMINED),
    ("COMPLETE", ["Logs retained for 90 days"], Verdict.DEVIATES),
    ("PARTIAL", ["Logs retained for 90 days"], Verdict.DEVIATES),
    ("COMPLETE", ["Logs retained for 180 days", "Logs retained for 90 days"], Verdict.DEVIATES),
    ("COMPLETE", ["Backups retained for 90 days"], Verdict.NOT_FOUND),
    ("COMPLETE", ["Logs retained for 4320 hours"], Verdict.SATISFIED),
    ("COMPLETE", ["Logs retained for 180 days. Logs retained for 90 days."], Verdict.DEVIATES),
    ("COMPLETE", [""], Verdict.NOT_FOUND),
    ("COMPLETE", [], Verdict.UNDETERMINED),
    ("PARTIAL", [], Verdict.NOT_FOUND),
    ("NO_EVIDENCE", [], Verdict.NOT_FOUND),
])
def test_in_memory_pipeline_verdict_contract(sf1_fake_provider_env, status, texts, expected):
    """Exercise resolved citations without disk I/O or a provider call."""
    from app.review_adapters.verdict_rules import assess

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = ReviewCase(
        id="memory-case", owner_user_id="owner-1", title="Retention", request_text="Retention",
        source_ids=["source-1"], created_at=now, updated_at=now,
    )
    chunks = [SimpleNamespace(chunk_id=f"chunk-{i}", source_id="source-1", text=text, provenance={})
              for i, text in enumerate(texts)]

    async def run(query, *, source_ids, condition="A"):
        assert source_ids == case.source_ids
        assert query == "retain logs for 180 days"
        ids = [c.chunk_id for c in chunks]
        return {"status": status, "task_results": [{"citations": ids, "evidence_ids": ids}]}

    pipeline = SimpleNamespace(run=run, source_store=SimpleNamespace(chunks=lambda ids: chunks))
    reqs = requirements(case)
    reqs[0].text = "retain logs for 180 days"
    events = []
    finding, = PipelineReviewEngine(pipeline).run(case, reqs, None, lambda *args: events.append(args))
    assert finding.verdict == expected
    assert finding.confidence == Confidence.L1
    conflict_events = [payload for name, payload in events if name == "verdict.conflict"]
    if expected == Verdict.DEVIATES:
        assessment = assess(reqs[0].text, finding.evidence)
        assert assessment.conflicting
        assert finding.evidence[:len(assessment.conflicting)] == assessment.conflicting
        assert len({e.evidence_id for e in finding.evidence}) == len(finding.evidence)
        assert conflict_events[0]["conflicting_evidence_ids"] == [
            e.evidence_id for e in assessment.conflicting
        ]
        assert conflict_events[0]["code"] == "CONFLICTING_CLAIM"
        assert "180 days" in str(conflict_events[0]["params"])
        assert "90 days" in str(conflict_events[0]["params"])
    else:
        assert conflict_events == []


@pytest.fixture
def answer_review(sf1_fake_provider_env):
    """A fake pipeline using resolved in-memory chunks and explicit task answers."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = ReviewCase(
        id="answer-case", owner_user_id="owner-1", title="Answer consistency",
        request_text="Review answers", source_ids=["source-1"],
        created_at=now, updated_at=now,
    )
    chunk = SimpleNamespace(
        chunk_id="chunk-1", source_id="source-1", text="", provenance={"locator": "Section 1"},
    )
    result = {"status": "COMPLETE", "task_results": [{
        "answer": None, "citations": [chunk.chunk_id], "evidence_ids": [chunk.chunk_id],
    }]}

    async def run(query, *, source_ids, condition="A"):
        assert source_ids == case.source_ids
        return result

    pipeline = SimpleNamespace(run=run, source_store=SimpleNamespace(chunks=lambda ids: [chunk]))
    return pipeline, case, chunk, result


@pytest.mark.parametrize("requirement,answer,expected", [
    ("Sessions must expire within 30 minutes", "Sessions must expire within 3:00 minutes.",
     Verdict.PARTIAL),
    ("Incident notifications must be sent by email",
     "Incident notifications must be sent by email and SMS.", Verdict.PARTIAL),
    ("Phiên phải hết hạn trong vòng 30 phút", "Phiên phải hết hạn trong vòng 3:00 phút.",
     Verdict.PARTIAL),
    ("Thông báo sự cố phải gửi qua email", "Thông báo sự cố phải gửi qua email và SMS.",
     Verdict.PARTIAL),
    ("Sessions must expire within 30 minutes", "Sessions must expire within 30 minutes.",
     Verdict.SATISFIED),
    ("Sessions must expire within 30 minutes", "Sessions must expire within 0.5 hours.",
     Verdict.SATISFIED),
    ("Incident notifications must be sent by email",
     "Incident notifications must be sent by email.", Verdict.SATISFIED),
    ("Phiên phải hết hạn trong vòng 30 phút", "Phiên phải hết hạn trong vòng 30 phút.",
     Verdict.SATISFIED),
    ("Sessions must expire within 30 minutes", "Unrelated answer", Verdict.SATISFIED),
    ("Sessions must expire within 30 minutes", None, Verdict.SATISFIED),
    ("Sessions must expire within 30 minutes", "", Verdict.SATISFIED),
    ("Sessions must expire within 30 minutes", 42, Verdict.SATISFIED),
])
def test_answer_consistency_status_and_diagnostic_event(answer_review, requirement, answer, expected):
    pipeline, case, chunk, result = answer_review
    chunk.text = requirement
    result["task_results"][0]["answer"] = answer
    reqs = requirements(case)
    reqs[0].text = requirement
    events = []
    engine = PipelineReviewEngine(pipeline)
    finding, = engine.run(case, reqs, None, lambda *args: events.append(args))
    assert finding.verdict == expected
    assert finding.confidence == Confidence.L1
    assert [e.evidence_id for e in finding.evidence] == [chunk.chunk_id]
    assert finding.evidence[0].excerpt == requirement
    assert finding.evidence[0].locator == "Section 1"
    diagnostics = [payload for name, payload in events if name == "verdict.answer_inconsistent"]
    assert bool(diagnostics) == (expected == Verdict.PARTIAL)
    if diagnostics:
        assert diagnostics[0]["case_id"] == case.id
        assert diagnostics[0]["requirement_id"] == reqs[0].id
        assert diagnostics[0]["evidence_ids"] == [chunk.chunk_id]
        assert diagnostics[0]["code"] in {"UNSUPPORTED_ANSWER_QUANTITY", "UNSUPPORTED_ANSWER_ALTERNATIVE"}
        claims = diagnostics[0]["params"]["claims"]
        assert claims and all(claim["kind"] in {"quantity", "alternative"} for claim in claims)
        assert any(("3:00" in str(claim.get("span")) or claim.get("value") == "SMS") for claim in claims)
    assert events[-1] == ("finding.created", finding.model_dump(mode="json"))
    delivered = []
    repeated, = engine.run(case, reqs, None, delivered.append)
    assert repeated == finding
    assert delivered == [finding]
    assert result["status"] == "COMPLETE"


@pytest.mark.parametrize("status,text,cited,expected", [
    ("COMPLETE", "Sessions expire within 30 minutes", True, Verdict.PARTIAL),
    ("PARTIAL", "Sessions expire within 30 minutes", True, Verdict.PARTIAL),
    ("NO_EVIDENCE", "Sessions expire within 30 minutes", True, Verdict.NOT_FOUND),
    ("FAILED", "Sessions expire within 30 minutes", True, Verdict.UNDETERMINED),
    ("COMPLETE", "Sessions expire within 45 minutes", True, Verdict.DEVIATES),
    ("PARTIAL", "Sessions expire within 45 minutes", True, Verdict.DEVIATES),
    ("COMPLETE", "Sessions expire within 30 minutes", False, Verdict.UNDETERMINED),
])
def test_answer_check_never_upgrades_or_overrides_evidence_conflict(
    answer_review, status, text, cited, expected,
):
    pipeline, case, chunk, result = answer_review
    chunk.text = text
    result["status"] = status
    result["task_results"][0]["answer"] = "Sessions expire within 3:00 minutes"
    if not cited:
        result["task_results"][0]["citations"] = []
    reqs = requirements(case)
    reqs[0].text = "Sessions expire within 30 minutes"
    events = []
    finding, = PipelineReviewEngine(pipeline).run(case, reqs, None, lambda *args: events.append(args))
    assert finding.verdict == expected
    # A FAILED run has no usable answer: evidence is cleared and task.failed is emitted (was: kept).
    assert [e.evidence_id for e in finding.evidence] == ([chunk.chunk_id] if cited and status != "FAILED" else [])
    assert any(name == "verdict.answer_inconsistent" for name, _ in events) == (
        status == "COMPLETE" and expected == Verdict.PARTIAL
    )


def test_each_task_answer_is_checked_against_only_resolved_evidence(answer_review):
    pipeline, case, chunk, result = answer_review
    chunk.text = "Incident notifications must be sent by email"
    # Unretrieved and foreign citations must not authorize the extra channel.
    result["task_results"].append({
        "answer": "Incident notifications must be sent by email and SMS.",
        "evidence_ids": ["unresolved-sms"], "citations": ["unresolved-sms"],
    })
    result["task_results"][0]["answer"] = chunk.text
    reqs = requirements(case)
    reqs[0].text = chunk.text
    finding, = PipelineReviewEngine(pipeline).run(case, reqs, None, lambda _: None)
    assert finding.verdict == Verdict.PARTIAL
    assert [e.evidence_id for e in finding.evidence] == [chunk.chunk_id]
