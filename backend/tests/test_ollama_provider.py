"""Offline Ollama wire contracts and fake-provider pipeline call accounting."""

import asyncio
from collections import Counter
import json
import os
from pathlib import Path

import httpx
import pytest

from app.core.types import Usage
from app.providers.base import OutputTruncatedError
from app.providers.fake import FakeProvider
from app.providers.ollama import OllamaProvider
from app.research import pipeline as pipeline_module
from app.research.decomposer import decompose_plan


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "dev")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("LOCAL_LLM_TEMPERATURE", "0.1")
    monkeypatch.delenv("LOCAL_LLM_CONTEXT_TOKENS", raising=False)
    monkeypatch.delenv("MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("TASK_PLAN_MAX_OUTPUT_TOKENS", raising=False)


@pytest.fixture(autouse=True, scope="session")
def inherited_windows_temp_acl(request):
    # Python's Windows mode=0700 ACL excludes this managed sandbox principal.
    # Keep inherited ACLs only for directories beneath this run's explicit temp.
    with pytest.MonkeyPatch.context() as patch:
        if os.name != "nt" or not request.config.getoption("basetemp"):
            yield
            return
        base = Path(request.config.getoption("basetemp")).resolve()
        mkdir = os.mkdir

        def inherited_temp_acl(path, mode=0o777, *, dir_fd=None):
            if Path(path).resolve().is_relative_to(base):
                mode = 0o777
            return mkdir(path, mode, dir_fd=dir_fd)

        patch.setattr(os, "mkdir", inherited_temp_acl)
        yield


def mock_chat(monkeypatch, *, text='{"ok":true}', done_reason="stop", count=10):
    payloads = []

    def respond(request):
        assert request.url.path == "/api/chat"
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": text},
                                       "prompt_eval_count": 17, "eval_count": count,
                                       "done_reason": done_reason})

    client = httpx.AsyncClient
    monkeypatch.setattr("app.providers.ollama.httpx.AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(respond), **kwargs))
    return payloads


@pytest.mark.parametrize("limit,expected", [(None, 700), (900, 900), (1, 64)])
def test_structured_payload_preserves_schema_think_and_token_cap(monkeypatch, limit, expected):
    payloads = mock_chat(monkeypatch)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    provider = OllamaProvider(model="test", base_url="http://offline.invalid")
    result = asyncio.run(provider.generate_structured(
        system="TASK_PLAN_BUILDER", user="test", response_schema=schema, max_output_tokens=limit))
    assert result.text == '{"ok":true}'
    assert result.usage == Usage(17, 10)
    assert payloads[0]["format"] == schema
    assert payloads[0]["think"] is False
    assert payloads[0]["options"] == {"temperature": 0.1, "num_predict": expected}
    assert provider.max_output_tokens == 700


def test_grounded_schema_is_sent_with_selected_ids(monkeypatch):
    payloads = mock_chat(monkeypatch)
    asyncio.run(OllamaProvider().generate_grounded(system="WORKER", user="test", evidence_ids=["c1", "c1"]))
    assert payloads[0]["format"]["properties"]["citations"]["items"]["enum"] == ["c1"]
    assert payloads[0]["think"] is False
    assert payloads[0]["options"]["num_predict"] == 700


@pytest.mark.parametrize(
    "context_value,expected_options",
    [
        (None, {"temperature": 0.1, "num_predict": 700}),
        ("8192", {"temperature": 0.1, "num_predict": 700, "num_ctx": 8192}),
    ],
)
def test_grounded_payload_has_optional_context_tokens(monkeypatch, context_value, expected_options):
    if context_value is None:
        monkeypatch.delenv("LOCAL_LLM_CONTEXT_TOKENS", raising=False)
    else:
        monkeypatch.setenv("LOCAL_LLM_CONTEXT_TOKENS", context_value)
    payloads = mock_chat(monkeypatch)

    asyncio.run(OllamaProvider().generate_grounded(system="WORKER", user="test", evidence_ids=["c1"]))

    assert payloads[0]["options"] == expected_options
    assert payloads[0]["format"]["properties"]["citations"]["items"]["enum"] == ["c1"]


@pytest.mark.parametrize("context_value", ["", "invalid", "0", "-1", "1.5"])
def test_invalid_context_tokens_are_rejected(monkeypatch, context_value):
    monkeypatch.setenv("LOCAL_LLM_CONTEXT_TOKENS", context_value)

    with pytest.raises(ValueError, match="LOCAL_LLM_CONTEXT_TOKENS must be a positive integer"):
        OllamaProvider()


@pytest.mark.parametrize("structured,reason,text,count,limit,truncated", [
    (False, "length", "partial prose", 700, None, False),  # was truncated=True: plain prose stays usable text
    (True, "length", '{"ok":true}', 5, None, True),
    (True, "stop", '{"ok":', 700, None, True),
    (True, None, '{"ok":', 900, 900, True),
    (True, "stop", '{"ok":', 699, None, False),
    (True, "stop", '{"ok":true}', 700, None, False),
    (False, "stop", "ordinary prose", 700, None, False),
])
def test_truncation_is_typed_and_keeps_partial_text_and_counts(
    monkeypatch, structured, reason, text, count, limit, truncated,
):
    mock_chat(monkeypatch, text=text, done_reason=reason, count=count)
    provider = OllamaProvider()
    call = (provider.generate_structured(system="test", user="test", response_schema={}, max_output_tokens=limit)
            if structured else provider.generate(system="test", user="test"))
    if truncated:
        with pytest.raises(OutputTruncatedError) as caught:
            asyncio.run(call)
        assert caught.value.partial_text == text
        assert caught.value.usage == Usage(17, count)
        assert caught.value.output_limit == (limit or 700)
        assert caught.value.done_reason == reason
    else:
        assert asyncio.run(call).text == text


def test_legacy_json_marker_also_detects_invalid_json_at_cap(monkeypatch):
    payloads = mock_chat(monkeypatch, text='{"answer":', count=700)
    with pytest.raises(OutputTruncatedError):
        asyncio.run(OllamaProvider().generate(system="VANILLA_RAG_ANSWERER", user="test"))
    assert payloads[0]["format"] == "json"


class CountingFake(FakeProvider):
    def __init__(self, fail_stage=None):
        self.calls = Counter()
        self.fail_stage = fail_stage

    async def generate(self, *, system, user):
        stage = system.split(".")[0]
        self.calls[stage] += 1
        if stage == self.fail_stage:
            raise OutputTruncatedError("partial", Usage(17, 700), 700, "length")
        return await super().generate(system=system, user=user)

    async def generate_structured(self, *, system, user, response_schema, **kwargs):
        return await self.generate(system=system, user=user)

    async def generate_grounded(self, *, system, user, evidence_ids):
        return await self.generate(system=system, user=user)


@pytest.fixture
def counted_pipeline(monkeypatch, tmp_path):
    from app.research.pipeline import ResearchPipeline
    from app.storage.run_store import RunStore
    from app.storage.source_store import SourceStore
    from app.storage.vector_store import InMemoryVectorStore
    from app.retrieval.candidate_index import CandidateIndex

    # Suppress the fake's artificial delay; tests never wait or use sockets.
    async def no_delay(*args, **kwargs):
        pass

    monkeypatch.setattr("app.providers.fake.asyncio.sleep", no_delay)
    monkeypatch.setenv("MIN_RETRIEVAL_SCORE", "0")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    sources = SourceStore(str(tmp_path / "sources"))
    source = sources.import_text("policy.txt", "API architecture uses endpoints and API services.")
    index = CandidateIndex(sources, InMemoryVectorStore(), owner_user_id="test")
    index.index_source(source["source_id"])
    pipeline = ResearchPipeline(sources, RunStore(str(tmp_path / "outputs")), candidate_index=index)
    return pipeline, [source["source_id"]]


@pytest.mark.parametrize("condition,expected", [("A", 1), ("C", 4)])
def test_call_counts_before_after_evidence_check(monkeypatch, counted_pipeline, condition, expected):
    from app.review_adapters import citation_check
    from app.review_adapters.pipeline_engine import PipelineReviewEngine

    pipeline, ids = counted_pipeline
    check = citation_check.excerpt_in_chunk
    counts = []
    for phase in ("before", "after"):
        provider = CountingFake()
        monkeypatch.setattr(pipeline_module, "get_provider", lambda name: provider)
        monkeypatch.setattr(citation_check, "excerpt_in_chunk", (lambda *args: True) if phase == "before" else check)
        result = asyncio.run(pipeline.run("Review API architecture", condition=condition, source_ids=ids))
        assert result["status"] == "COMPLETE", result.get("events")
        assert PipelineReviewEngine._evidence(pipeline, result, ids)
        counts.append(sum(provider.calls.values()))
        assert result["metrics"]["llm_calls"] == expected
        print(f"{condition} {phase}: {counts[-1]} calls; stages={dict(provider.calls)}")
    assert counts == [expected, expected]


@pytest.mark.parametrize("condition,stage", [
    ("A", "VANILLA_RAG_ANSWERER"), ("C", "OBLIGATION_CONCERN_EXTRACTOR"),
    ("C", "TASK_PLAN_BUILDER"), ("C", "WORKER"), ("C", "SYNTHESIZER"),
])
def test_truncation_stays_within_pipeline_failure_boundary(monkeypatch, counted_pipeline, condition, stage):
    pipeline, ids = counted_pipeline
    provider = CountingFake(fail_stage=stage)
    monkeypatch.setattr(pipeline_module, "get_provider", lambda name: provider)
    result = asyncio.run(pipeline.run("Review API architecture", condition=condition, source_ids=ids))
    if stage == "TASK_PLAN_BUILDER":
        assert result["status"] == "PARTIAL"
        assert result["lifecycle_status"] == "COMPLETED"
        assert provider.calls[stage] == 2
        assert result["answer"]
        assert sum(event["stage"] == "planning_repair" for event in result["events"]) == 1
        assert any(event["stage"] == "planning_degraded" for event in result["events"])
    elif stage == "SYNTHESIZER":
        assert result["status"] == "COMPLETE"
        assert result["lifecycle_status"] == "COMPLETED"
        assert provider.calls[stage] == 1
        assert result["task_results"][0]["answer"] in result["answer"]
        assert "**Tóm tắt**" not in result["answer"]
    else:
        assert result["status"] == "FAILED"
        assert result["lifecycle_status"] == "FAILED"
        assert provider.calls[stage] == 1


def test_planner_existing_exception_handler_accepts_typed_truncation():
    result = asyncio.run(decompose_plan(CountingFake(fail_stage="TASK_PLAN_BUILDER"), "Review API architecture"))
    assert result.plan is None
    assert result.warnings

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _always_summarise(monkeypatch):
    """These tests count/truncate the summary call; production skips it for short/single-domain bodies."""
    monkeypatch.setenv("SYNTH_MIN_BODY_CHARS", "0")
