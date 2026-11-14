"""Condition selection and trace provenance for the review pipeline adapter."""

import asyncio
from datetime import datetime, timezone
import os
from types import SimpleNamespace

import pytest

from app.api.review import ReviewRuntime
from app.research.pipeline import CONDITIONS
from app.research.token_context import plan_task_budgets
from app.retrieval.candidate_index import CandidateIndex
from app.review.schemas import Requirement, ReviewCase
from app.review_adapters import PipelineReviewEngine


@pytest.fixture(autouse=True)
def fake_env(sf1_fake_provider_env):
    """Keep every test on the local fake provider."""
    sf1_fake_provider_env.delenv("REVIEW_CONTEXT_POLICY", raising=False)
    sf1_fake_provider_env.delenv("CONTEXT_POLICY", raising=False)


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
        expected = {"source_ids": case.source_ids, "condition": condition.upper()}
        if condition.upper() != "A":
            expected["context_policy"] = "adaptive_qwen"
        assert kwargs == expected
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
        assert [name for name, _ in events] == ["task.started", "pipeline.trace", "finding.created"]
        assert result["effective_config"]["context_policy"] == "char_proxy"
        assert events[1][1] == {
            "case_id": case.id, "requirement_id": requirement.id,
            "condition": "A", "config_hash": result["config_hash"],
            "planning_retrieval": None, "normalization": None,
            "context_policy": None, "task_budget": None,
        }
        assert result["config_hash"]
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
        "task_budget": {
            key: stages["adaptive_budget_plan"][key]
            for key in ("policy", "total_tokens", "needs", "limits")
        },
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
    async def run(query, *, source_ids, condition, context_policy):
        assert condition == "C"
        assert context_policy == "adaptive_qwen"
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
        "normalization": None, "context_policy": None, "task_budget": None,
    }


@pytest.mark.parametrize("condition", ["C", "C-P", "C-N", "C-O"])
@pytest.mark.parametrize("override,env_policy,expected", [
    (None, None, "adaptive_qwen"),
    (None, "char_proxy", "char_proxy"),
    ("char_proxy", "adaptive_qwen", "char_proxy"),
    (" ADAPTIVE_QWEN ", "invalid", "adaptive_qwen"),
])
def test_context_policy_selection(condition, override, env_policy, expected, monkeypatch):
    if env_policy is not None:
        monkeypatch.setenv("REVIEW_CONTEXT_POLICY", env_policy)
    monkeypatch.setenv("CONTEXT_POLICY", "char_proxy")
    engine = PipelineReviewEngine(object(), condition=condition, context_policy=override)
    assert engine.context_policy == expected


@pytest.mark.parametrize("condition", ["C", "C-P", "C-N", "C-O"])
@pytest.mark.parametrize("override", [None, "char_proxy"])
def test_review_forwards_policy_and_traces_returned_values(review_case, condition, override):
    plan = {"policy": "adaptive_qwen", "total_tokens": 17,
            "needs": {"T1": 12, "T2": 9}, "limits": {"T1": 10, "T2": 7}}

    async def run(query, *, source_ids, condition, context_policy):
        assert context_policy == (override or "adaptive_qwen")
        return {
            "condition": condition, "config_hash": "returned-hash", "status": "NO_EVIDENCE",
            "effective_config": {"context_policy": "char_proxy"},
            "events": [{"stage": "adaptive_budget_plan", "ts": "recorded-time", **plan}],
        }

    pipeline = SimpleNamespace(run=run, source_store=SimpleNamespace(chunks=lambda ids: []))
    case, requirement = review_case
    events = []
    PipelineReviewEngine(pipeline, condition=condition, context_policy=override).run(
        case, [requirement], None, lambda *args: events.append(args),
    )
    trace, = [payload for name, payload in events if name == "pipeline.trace"]
    assert trace == {
        "case_id": case.id, "requirement_id": requirement.id,
        "condition": condition, "config_hash": "returned-hash",
        "planning_retrieval": None, "normalization": None,
        "context_policy": "char_proxy", "task_budget": plan,
    }


@pytest.mark.parametrize("condition", ["A", "C"])
@pytest.mark.parametrize("policy", ["", "unknown"])
def test_invalid_context_policy_is_construction_error(condition, policy, monkeypatch):
    with pytest.raises(ValueError, match="Unknown review context policy"):
        PipelineReviewEngine(object(), condition=condition, context_policy=policy)
    monkeypatch.setenv("REVIEW_CONTEXT_POLICY", policy)
    runtime = ReviewRuntime(pipeline_factory=lambda owner: None, source_store_factory=lambda owner: None,
                            storage_backend="file")
    monkeypatch.setenv("REVIEW_PIPELINE_CONDITION", condition)
    with pytest.raises(ValueError, match="Unknown review context policy"):
        runtime.engine()


def test_api_reads_review_context_policy(monkeypatch):
    monkeypatch.setenv("REVIEW_PIPELINE_CONDITION", "C")
    monkeypatch.setenv("REVIEW_CONTEXT_POLICY", "char_proxy")
    runtime = ReviewRuntime(pipeline_factory=lambda owner: None, source_store_factory=lambda owner: None,
                            storage_backend="file")
    assert runtime.engine().context_policy == "char_proxy"


@pytest.mark.parametrize("env_policy", ["char_proxy", "adaptive_qwen"])
def test_a_does_not_override_pipeline_policy(review_case, monkeypatch, env_policy):
    monkeypatch.setenv("CONTEXT_POLICY", env_policy)
    monkeypatch.setenv("REVIEW_CONTEXT_POLICY", "adaptive_qwen")
    calls = []

    async def run(query, **kwargs):
        calls.append(kwargs)
        return {
            "status": "NO_EVIDENCE", "condition": "A", "config_hash": "config-a",
            "effective_config": {"context_policy": env_policy},
            "events": [{"stage": "adaptive_budget_plan", "limits": {"T1": 5}}],
        }

    pipeline = SimpleNamespace(run=run, source_store=SimpleNamespace(chunks=lambda ids: []))
    case, requirement = review_case
    events = []
    PipelineReviewEngine(pipeline, context_policy="char_proxy").run(
        case, [requirement], None, lambda *args: events.append(args),
    )
    assert calls == [{"source_ids": case.source_ids, "condition": "A"}]
    trace, = [payload for name, payload in events if name == "pipeline.trace"]
    assert trace == {
        "case_id": case.id, "requirement_id": requirement.id,
        "condition": "A", "config_hash": "config-a", "planning_retrieval": None,
        "normalization": None, "context_policy": None, "task_budget": None,
    }


@pytest.mark.parametrize("condition", ["C", "C-P", "C-N", "C-O"])
def test_two_confirmed_requirements_record_actual_budget(
    review_case, sf1_pipeline_factory, sf1_vector_store, monkeypatch, condition,
):
    from app.research import pipeline as pipeline_module

    monkeypatch.setenv("CONTEXT_POLICY", "char_proxy")
    pipeline = sf1_pipeline_factory()
    source = pipeline.source_store.import_text(
        "requirements.txt",
        "Authentication requires a valid token. Authentication tokens must be validated.",
    )
    case, first = review_case
    case.source_ids = [source["source_id"]]
    second = first.model_copy(update={
        "id": "requirement-2", "text": "Authentication tokens must be validated", "order": 1,
    })
    pipeline.candidate_index = CandidateIndex(
        pipeline.source_store, sf1_vector_store, owner_user_id=case.owner_user_id,
    )
    pipeline.candidate_index.index_source(source["source_id"])
    computed = []
    returned = []
    original = pipeline.run

    def record_plan(candidates, total_tokens):
        plan = plan_task_budgets(candidates, total_tokens)
        computed.append(plan)
        return plan

    async def record_run(query, **kwargs):
        assert kwargs["context_policy"] == "adaptive_qwen"
        result = await original(query, **kwargs)
        returned.append(result)
        return result

    monkeypatch.setattr(pipeline_module, "plan_task_budgets", record_plan)
    monkeypatch.setattr(pipeline, "run", record_run)
    events = []
    findings = PipelineReviewEngine(pipeline, condition=condition).run(
        case, [first, second], None, lambda *args: events.append(args),
    )
    assert [finding.requirement_id for finding in findings] == [first.id, second.id]
    assert len(returned) == 2
    traces = [payload for name, payload in events if name == "pipeline.trace"]
    assert [trace["requirement_id"] for trace in traces] == [first.id, second.id]
    assert len(computed) == (0 if condition == "C-O" else 2)
    for index, (trace, result) in enumerate(zip(traces, returned)):
        assert result["status"] != "FAILED", result["answer"]
        assert trace["context_policy"] == result["effective_config"]["context_policy"] == "adaptive_qwen"
        if condition == "C-O":
            assert trace["task_budget"] is None
            continue
        plan = trace["task_budget"]
        assert plan == computed[index]
        assert plan["limits"] and set(plan["limits"]) == set(plan["needs"])
        assert set(plan["limits"]) == {task["task_id"] for task in result["tasks"]}
        assert all(limit >= 0 for limit in plan["limits"].values())
        assert sum(plan["limits"].values()) <= plan["total_tokens"]
    assert os.environ["CONTEXT_POLICY"] == "char_proxy"


@pytest.mark.parametrize("env_policy,override,expected", [
    ("char_proxy", None, "char_proxy"),
    ("adaptive_qwen", None, "adaptive_qwen"),
    ("invalid", "char_proxy", "char_proxy"),
    ("char_proxy", "adaptive_qwen", "adaptive_qwen"),
])
def test_pipeline_policy_override_is_per_run(sf1_pipeline_factory, monkeypatch, env_policy, override, expected):
    monkeypatch.setenv("CONTEXT_POLICY", env_policy)
    pipeline = sf1_pipeline_factory()
    result = asyncio.run(pipeline.run("Authentication", context_policy=override))
    assert result["effective_config"]["context_policy"] == expected
    assert os.environ["CONTEXT_POLICY"] == env_policy


def test_a_findings_match_direct_legacy_pipeline(review_case, sf1_pipeline_factory):
    pipeline = sf1_pipeline_factory()
    source = pipeline.source_store.import_text("authentication.txt", "Authentication requires a valid token.")
    case, requirement = review_case
    case.source_ids = [source["source_id"]]
    baseline = asyncio.run(pipeline.run(requirement.text, source_ids=case.source_ids, condition="A"))
    assert baseline["effective_config"]["context_policy"] == "char_proxy"
    baseline_pipeline = SimpleNamespace(source_store=pipeline.source_store)

    async def legacy_run(query, *, source_ids, condition):
        return baseline

    baseline_pipeline.run = legacy_run
    expected = PipelineReviewEngine(baseline_pipeline).run(case, [requirement], None, lambda _: None)
    events = []
    actual = PipelineReviewEngine(pipeline).run(case, [requirement], None, lambda *args: events.append(args))
    assert actual == expected
    assert events[-1] == ("finding.created", expected[0].model_dump(mode="json"))
