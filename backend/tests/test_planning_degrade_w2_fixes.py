"""Dedicated tests for the three integration fixes in the planning-degrade path."""
import asyncio
import dataclasses

import pytest

from app.research import pipeline as pipeline_module
from app.research.conversation_context import ConversationContext
from app.research.pipeline import ResearchPipeline
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore
from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import LocalHashEmbedder
from tests.test_planning_wl import PlanningProvider, fake_environment  # noqa: F401  (autouse fixture)


def _pipeline(tmp_path):
    store = SourceStore(str(tmp_path / "sources"))
    store.import_text("Guide.md", "Review authentication and database query requirements.")
    index = CandidateIndex(None, InMemoryVectorStore(), owner_user_id="owner", embedder=LocalHashEmbedder())
    return ResearchPipeline(store, RunStore(str(tmp_path / "run-store")), candidate_index=index)


def _run(tmp_path, monkeypatch, provider, **kwargs):
    monkeypatch.setattr("app.research.pipeline.get_provider", lambda name=None: provider)
    return asyncio.run(_pipeline(tmp_path).run(
        "Review authentication and database query", "C", provider_name="fake",
        product_mode=True, force_plan=True, **kwargs,
    ))


def _capture_vanilla(monkeypatch):
    seen = {}
    real = pipeline_module.answer_vanilla

    async def spy(provider, query, evidence, metrics, reply_language=None, checker=None, **kw):
        seen["query"], seen["reply_language"] = query, reply_language
        return await real(provider, query, evidence, metrics, reply_language=reply_language, checker=checker, **kw)

    monkeypatch.setattr(pipeline_module, "answer_vanilla", spy)
    return seen


def test_anchored_repair_must_preserve_original_plan(tmp_path, monkeypatch):
    """Anchoring may only rescue a plan that still passes validate_repaired_plan; otherwise degrade."""
    real_anchor = pipeline_module.anchor_and_verify

    def altering_anchor(plan):
        anchored, verification, changes = real_anchor(plan)
        return dataclasses.replace(anchored, request="a different request"), verification, changes

    monkeypatch.setattr(pipeline_module, "anchor_and_verify", altering_anchor)
    run = _run(tmp_path, monkeypatch, PlanningProvider("semantic"))
    assert run["status"] == "PARTIAL"
    rejected = [e for e in run["events"] if e["stage"] == "planning_rejected"]
    assert any(e.get("reason") == "anchored_repair_not_preserving_plan" for e in rejected)
    degraded = [e for e in run["events"] if e["stage"] == "planning_degraded"]
    assert degraded and degraded[0]["reason"] == "anchored_repair_not_preserving_plan"
    assert any("changed the request" in str(err) for err in degraded[0]["errors"])


@pytest.mark.parametrize("hint", ["vi", "en"])
def test_degrade_keeps_reply_language_hint(tmp_path, monkeypatch, hint):
    seen = _capture_vanilla(monkeypatch)
    run = _run(tmp_path, monkeypatch, PlanningProvider("json"), reply_language_hint=hint)
    assert any(e["stage"] == "planning_degraded" for e in run["events"])
    assert seen["reply_language"] == hint


def test_degrade_keeps_resolved_follow_up_query(tmp_path, monkeypatch):
    seen = _capture_vanilla(monkeypatch)
    ctx = ConversationContext(text="[USER] Explain JWT authentication", last_user_request="Explain JWT authentication")
    monkeypatch.setattr("app.research.pipeline.get_provider", lambda name=None: PlanningProvider("json"))
    run = asyncio.run(_pipeline(tmp_path).run(
        "What about it for the database query?", "C", provider_name="fake",
        product_mode=True, force_plan=True, conversation_context=ctx,
    ))
    assert any(e["stage"] == "planning_degraded" for e in run["events"])
    assert any(e["stage"] == "follow_up_resolved" for e in run["events"])
    assert "Explain JWT authentication" in seen["query"]
    assert seen["query"].startswith("What about it for the database query?")
