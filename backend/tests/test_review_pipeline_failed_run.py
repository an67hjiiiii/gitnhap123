from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pytest

from app.review.schemas import Requirement, ReviewCase, Verdict
from app.review_adapters import PipelineReviewEngine


class _Store:
    def chunks(self, source_ids):
        return []


class _FakePipeline:
    source_store = _Store()

    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    async def run(self, query, **kwargs):
        if self.error:
            raise self.error
        return self.result


def _case():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ReviewCase(id="c1", owner_user_id="u1", title="t", request_text="x",
                      source_ids=[], created_at=now, updated_at=now)


def _run(pipeline, condition="C"):
    case = _case()
    req = Requirement(id="r1", case_id="c1", text="Passwords must contain at least 12 characters.",
                      origin="USER", confirmed=True, order=0)
    events = []
    findings = asyncio.run(PipelineReviewEngine(pipeline, condition=condition).run_async(
        case, [req], None, lambda n, p=None: events.append((n, p))))
    return findings, events


def _failed(*extra, error_type="ValueError", error="boom secret text"):
    events = [{"stage": "planning_retrieval", "enabled": True, "selected": []}, *extra,
              {"stage": "run_failed", "error_type": error_type, "error": error}]
    return {"status": "FAILED", "condition": "C", "config_hash": "h", "events": events,
            "effective_config": {"context_policy": "adaptive_qwen"}, "task_results": []}


@pytest.mark.parametrize("extra,error_type,error,code", [
    ([{"stage": "planning_rejected", "reason": "task_plan_generation_failed"}], "ValueError", "TaskPlan generation failed", "PLAN_REJECTED"),
    ([], "LimitExceeded", "Invocation cap 3 exhausted before next call", "PROVIDER_LIMIT"),
    ([], "KeyError", "secret internal text", "PIPELINE_RUN_FAILED"),
])
def test_failed_run_emits_task_failed_with_stable_code(caplog, extra, error_type, error, code):
    caplog.set_level(logging.WARNING)
    findings, events = _run(_FakePipeline(_failed(*extra, error_type=error_type, error=error)))
    assert findings[0].verdict == Verdict.UNDETERMINED and findings[0].evidence == []
    names = [n for n, _ in events]
    assert names == ["task.started", "pipeline.trace", "task.failed", "finding.created"]
    failed = dict(events)["task.failed"]
    assert failed["error_type"] == code and failed["error"] == "Requirement execution failed"
    assert error not in str(failed) and error_type not in str(failed)
    assert error in caplog.text  # detail goes to the log only
    trace = dict(events)["pipeline.trace"]
    assert trace["condition"] == "C" and trace["config_hash"] == "h" and trace["task_budget"] is None


def test_condition_not_in_profile_has_its_own_code():
    findings, events = _run(_FakePipeline(error=ValueError("Condition C is not available in profile m0. Allowed: A")))
    assert dict(events)["task.failed"]["error_type"] == "CONDITION_NOT_AVAILABLE"
    assert findings[0].verdict == Verdict.UNDETERMINED


def test_condition_c_with_broken_planner_json_fails_with_plan_rejected(monkeypatch, sf1_fake_provider_env, sf1_pipeline_factory):
    """Real pipeline + fake provider whose planner returns broken JSON twice -> PLAN_REJECTED."""
    from app.providers.fake import FakeProvider
    from app.research import pipeline as research_module

    class BrokenPlanner(FakeProvider):
        async def generate(self, *, system, user):
            if "TASK_PLAN_BUILDER" in system.upper():
                return await super().generate(system="x", user="not json {")
            return await super().generate(system=system, user=user)

    pipeline = sf1_pipeline_factory()
    monkeypatch.setattr(research_module, "get_provider", lambda *_a, **_k: BrokenPlanner())
    findings, events = _run(pipeline)
    assert findings[0].verdict == Verdict.UNDETERMINED
    assert "task.failed" in dict(events)
    assert dict(events)["task.failed"]["error_type"] in {"PLAN_REJECTED", "PIPELINE_RUN_FAILED"}