from __future__ import annotations

import asyncio

import pytest

from app.core.graph import topological_order, validate_tasks
from app.core.types import ObligationConcernExtraction, ProviderResult, SourceChunk, Task, TaskPlan, Usage
from app.research import pipeline as pipeline_module
from app.research.decomposer import canonicalize_task_plan
from app.research.normalizer import normalize_tasks
from app.research.plan_verification import verify_task_plan


def _result(task_id, status="COMPLETE", answer="controlled result"):
    from app.core.types import TaskResult
    return TaskResult(task_id=task_id, domain="api_architecture", status=status, answer=answer)


def test_run_status_reflects_all_complete_and_mixed_task_results(
    monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory
):
    async def answer(provider, query, evidence, metrics, reply_language=None):
        return _result("T1", "COMPLETE")

    monkeypatch.setattr(pipeline_module, "answer_vanilla", answer)
    run = asyncio.run(sf1_pipeline_factory().run("Question", condition="A"))
    assert run["status"] == "COMPLETE"

    tasks = [
        Task("T1", "API policy", "api_architecture"),
        Task("T2", "API behavior", "api_architecture"),
    ]
    _patch_plan(monkeypatch, TaskPlan("Question", tasks=tasks))
    async def task_result(provider, task, evidence, metrics):
        return _result(task.task_id, "PARTIAL" if task.task_id == "T2" else "COMPLETE")
    monkeypatch.setattr(pipeline_module, "execute_task", task_result)
    run = asyncio.run(sf1_pipeline_factory().run("Question", condition="C-P"))
    assert run["status"] == "PARTIAL"


def test_all_no_evidence_tasks_return_no_evidence(
    monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory
):
    tasks = [Task("T1", "API policy", "api_architecture"), Task("T2", "API behavior", "api_architecture")]
    _patch_plan(monkeypatch, TaskPlan("Question", tasks=tasks))
    async def no_evidence(provider, task, evidence, metrics):
        return _result(task.task_id, "NO_EVIDENCE")
    monkeypatch.setattr(pipeline_module, "execute_task", no_evidence)
    run = asyncio.run(sf1_pipeline_factory().run("Question", condition="C-P"))
    assert run["status"] == "NO_EVIDENCE"


def test_invalid_worker_citation_is_dropped_and_recorded(
    monkeypatch, sf1_fake_provider_env
):
    from app.research.worker import execute_task

    class Provider:
        async def generate_grounded(self, **kwargs):
            return ProviderResult('{"status":"COMPLETE","answer":"answer","citations":["outside"]}', Usage())

    chunk = SourceChunk("inside", "source", "source", "evidence", 0)
    from app.core.types import RunMetrics
    result = asyncio.run(execute_task(Provider(), Task("T1", "API", "api_architecture"), [chunk], RunMetrics()))
    assert result.citations == []
    assert result.invalid_citations == ["outside"]


def test_run_token_budget_emits_event_and_finalizes_partial(
    monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory
):
    monkeypatch.setenv("MAX_RUN_TOKENS", "512")
    tasks = [Task("T1", "API policy", "api_architecture"), Task("T2", "API behavior", "api_architecture")]
    _patch_plan(monkeypatch, TaskPlan("Question", tasks=tasks))
    async def expensive(provider, task, evidence, metrics):
        metrics.input_tokens = 513
        return _result(task.task_id, "COMPLETE")
    monkeypatch.setattr(pipeline_module, "execute_task", expensive)
    run = asyncio.run(sf1_pipeline_factory().run("Question", condition="C-P"))
    assert any(event["stage"] == "run_budget_exceeded" for event in run["events"])
    assert [r["task_id"] for r in run["task_results"]] == ["T1"]  # loop breaks; T2 is never executed
    assert run["status"] == "PARTIAL"  # fixed: was COMPLETE (status ignored unexecuted tasks)


def test_dependency_context_order_validation_and_normalization(
    monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory
):
    upstream = Task("T1", "Review upstream API", "api_architecture")
    downstream = Task("T2", "Review downstream API", "api_architecture", depends_on=["T1"])
    assert [task.task_id for task in topological_order([downstream, upstream])] == ["T1", "T2"]
    normalized, removed = normalize_tasks([upstream, downstream])
    assert removed == 0
    assert normalized[1].depends_on == ["T1"]
    canonical = canonicalize_task_plan(TaskPlan("Review upstream then downstream API", tasks=[upstream, downstream]))
    assert canonical.tasks[1].depends_on == ["T1"]
    with pytest.raises(ValueError, match="Unknown dependency"):
        validate_tasks([Task("T2", "Review API", "api_architecture", depends_on=["missing"])])

    plan = TaskPlan("Review upstream then downstream API", tasks=[upstream, downstream])
    assert verify_task_plan(plan).valid
    extraction = ObligationConcernExtraction()
    monkeypatch.setattr(pipeline_module, "extract_obligations_and_concerns", lambda *args, **kwargs: _async_value(extraction))
    monkeypatch.setattr(pipeline_module, "decompose_plan", lambda *args, **kwargs: _async_value(type("PlanResult", (), {"plan": plan, "status": "COMPLETE", "repair_attempted": False, "warnings": []})()))
    queries = []
    pipeline = sf1_pipeline_factory()
    def record_retrieval(query, *args, **kwargs):
        queries.append(query)
        return []
    monkeypatch.setattr(pipeline, "_retrieve_candidates", record_retrieval)
    async def answer(provider, task, evidence, metrics):
        return _result(task.task_id, answer="upstream answer" if task.task_id == "T1" else "downstream answer")
    monkeypatch.setattr(pipeline_module, "execute_task", answer)
    asyncio.run(pipeline.run("Review upstream then downstream API", condition="C-P"))
    assert len(queries) == 2
    assert "upstream answer" in queries[1]


def _patch_plan(monkeypatch, plan):
    """Replace extraction + planning with a fixed verified plan (both are awaited by pipeline.run)."""
    monkeypatch.setattr(pipeline_module, "extract_obligations_and_concerns",
                        lambda *args, **kwargs: _async_value(ObligationConcernExtraction()))
    monkeypatch.setattr(pipeline_module, "decompose_plan", lambda *args, **kwargs: _async_value(
        type("PlanResult", (), {"plan": plan, "status": "COMPLETE", "repair_attempted": False, "warnings": []})()))


async def _async_value(value):
    return value
