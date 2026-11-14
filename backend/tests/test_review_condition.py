"""Condition selection and trace provenance for the review pipeline adapter."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.review import ReviewRuntime
from app.research.pipeline import CONDITIONS
from app.retrieval.candidate_index import CandidateIndex
from app.review.schemas import Requirement, ReviewCase
from app.review_adapters import PipelineReviewEngine


@pytest.fixture(autouse=True)
def fake_env(sf1_fake_provider_env):
    """Keep every test on the local fake provider."""


@pytest.fixture
def review_case():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = ReviewCase(
        id="condition-case", owner_user_id="owner-1", title="Authentication",
        request_text="Authentication requires a valid token.", source_ids=[],
        created_at=now, updated_at=now,
    )
    requirement = Requirement(
        id="requirement-1", case_id=case.id, text=case.request_text,
        origin="USER", confirmed=True, order=0,
    )
    return case, requirement


@pytest.mark.parametrize("condition", ["A", "c"])
def test_real_pipeline_trace(
    condition, review_case, sf1_pipeline_factory, sf1_vector_store, monkeypatch,
):
    monkeypatch.delenv("REVIEW_PIPELINE_CONDITION", raising=False)
    pipeline = sf1_pipeline_factory()
    source = pipeline.source_store.import_text(
        "authentication.txt", "Authentication requires a valid token.",
    )
    case, requirement = review_case
    case.source_ids = [source["source_id"]]
    pipeline.candidate_index = CandidateIndex(
        pipeline.source_store, sf1_vector_store, owner_user_id=case.owner_user_id,
    )
    pipeline.candidate_index.index_source(source["source_id"])
    original = pipeline.run
    returned = []

    async def record(query, **kwargs):
        assert kwargs == {"source_ids": case.source_ids, "condition": condition.upper()}
        result = await original(query, **kwargs)
        returned.append(result)
        return result

    monkeypatch.setattr(pipeline, "run", record)
    engine = PipelineReviewEngine(pipeline) if condition == "A" else PipelineReviewEngine(
        pipeline, condition=condition,
    )
    events = []
    findings = engine.run(case, [requirement], None, lambda *args: events.append(args))
    result, = returned
    assert result["status"] != "FAILED", result["answer"]
    if condition == "A":
        assert [name for name, _ in events] == ["task.started", "finding.created"]
        delivered = []
        assert engine.run(case, [requirement], None, delivered.append) == findings
        assert delivered == findings
        return
    trace, = [payload for name, payload in events if name == "pipeline.trace"]
    stages = {event["stage"]: event for event in result["events"]}
    assert trace == {
        "case_id": case.id, "requirement_id": requirement.id,
        "condition": result["condition"], "config_hash": result["config_hash"],
        "planning_retrieval": stages.get("planning_retrieval"),
        "normalization": stages.get("normalization"),
        "context_policy": result["effective_config"]["context_policy"],
    }
    assert trace["condition"] == condition.upper()
    assert trace["config_hash"]
    assert trace["context_policy"] is not None
    assert trace["planning_retrieval"] is not None
    assert trace["normalization"] is not None
    delivered = []
    assert engine.run(case, [requirement], None, delivered.append) == findings
    assert delivered == findings


@pytest.mark.parametrize("condition", sorted(CONDITIONS))
def test_all_known_conditions_are_case_insensitive(condition):
    assert PipelineReviewEngine(object(), condition=condition.lower()).condition == condition


@pytest.mark.parametrize("condition", ["", "unknown", " C "])
def test_unknown_condition_rejected(condition):
    with pytest.raises(ValueError, match="Unknown review pipeline condition"):
        PipelineReviewEngine(object(), condition=condition)


@pytest.mark.parametrize("value,expected", [(None, "A"), ("", "A"), ("c", "C"), ("C-N", "C-N")])
def test_api_reads_condition_env(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("REVIEW_PIPELINE_CONDITION", raising=False)
    else:
        monkeypatch.setenv("REVIEW_PIPELINE_CONDITION", value)
    runtime = ReviewRuntime(pipeline_factory=lambda owner: None, source_store_factory=lambda owner: None,
                            storage_backend="file")
    assert runtime.engine().condition == expected


def test_api_invalid_condition_is_construction_error(monkeypatch):
    monkeypatch.setenv("REVIEW_PIPELINE_CONDITION", "invalid")
    runtime = ReviewRuntime(pipeline_factory=lambda owner: None, source_store_factory=lambda owner: None,
                            storage_backend="file")
    with pytest.raises(ValueError, match="Unknown review pipeline condition 'INVALID'"):
        runtime.engine()


def test_missing_trace_values_are_not_invented(review_case):
    async def run(query, *, source_ids, condition):
        assert condition == "C"
        return {"status": "NO_EVIDENCE", "task_results": []}

    pipeline = SimpleNamespace(run=run, source_store=SimpleNamespace(chunks=lambda ids: []))
    case, requirement = review_case
    events = []
    PipelineReviewEngine(pipeline, condition="C").run(
        case, [requirement], None, lambda *args: events.append(args),
    )
    trace, = [payload for name, payload in events if name == "pipeline.trace"]
    assert trace == {
        "case_id": case.id, "requirement_id": requirement.id,
        "condition": None, "config_hash": None, "planning_retrieval": None,
        "normalization": None, "context_policy": None,
    }
