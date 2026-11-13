from __future__ import annotations

import asyncio
import json

from app.core.types import TaskResult
from app.research import pipeline as pipeline_module
from app.storage.run_store import RunStore


def _result(status="COMPLETE"):
    return TaskResult(task_id="T1", domain="general", status=status, answer="controlled result")


def _run_with_status(monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory, status, **kwargs):
    async def answer_vanilla(provider, query, evidence, metrics, reply_language=None):
        return _result(status)

    monkeypatch.setattr(pipeline_module, "answer_vanilla", answer_vanilla)
    pipeline = sf1_pipeline_factory()
    return asyncio.run(pipeline.run("A deterministic question?", condition="A", **kwargs))


def test_run_all_tasks_complete_returns_complete(monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory):
    run = _run_with_status(monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory, "COMPLETE")
    assert run["status"] == "COMPLETE"
    assert [result["status"] for result in run["task_results"]] == ["COMPLETE"]


def test_run_all_tasks_without_evidence_returns_no_evidence(monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory):
    run = _run_with_status(monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory, "NO_EVIDENCE")
    assert run["status"] == "NO_EVIDENCE"
    assert [result["status"] for result in run["task_results"]] == ["NO_EVIDENCE"]


def test_run_non_complete_task_is_not_complete(monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory):
    run = _run_with_status(monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory, "PARTIAL")
    assert run["status"] == "PARTIAL"


def test_product_help_completes_without_source_grounding(sf1_fake_provider_env, sf1_pipeline_factory):
    pipeline = sf1_pipeline_factory()
    run = asyncio.run(pipeline.run("hello", condition="A", product_mode=True))

    assert run["status"] == "COMPLETE"
    event = next(event for event in run["events"] if event["stage"] == "product_help_response")
    assert event["source_grounding_required"] is False


def test_run_lifecycle_snapshots_and_final_record_round_trip(
    monkeypatch, sf1_fake_provider_env, sf1_data_dir, sf1_pipeline_factory
):
    class CapturingRunStore(RunStore):
        def __init__(self, root):
            super().__init__(str(root))
            self.snapshots = []

        def save(self, run):
            self.snapshots.append(json.loads(json.dumps(run)))
            super().save(run)

    async def answer_vanilla(provider, query, evidence, metrics, reply_language=None):
        return _result("COMPLETE")

    monkeypatch.setattr(pipeline_module, "answer_vanilla", answer_vanilla)
    store = CapturingRunStore(sf1_data_dir / "lifecycle-runs")
    pipeline = sf1_pipeline_factory(run_store=store)
    returned = asyncio.run(pipeline.run("A deterministic question?", condition="A"))

    assert [snapshot["lifecycle_status"] for snapshot in store.snapshots] == [
        "PENDING", "RUNNING", "COMPLETED"
    ]
    assert [snapshot["status"] for snapshot in store.snapshots] == [None, None, "COMPLETE"]
    persisted = store.get(returned["run_id"])
    assert persisted is not None
    for field in ("run_id", "created_at", "condition", "query", "status", "lifecycle_status", "tasks", "task_results", "events", "metrics"):
        assert persisted[field] == returned[field]
