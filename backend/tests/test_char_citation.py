import asyncio

import pytest

from app.core.types import RunMetrics, SourceChunk, TaskResult
from app.providers.ollama import OllamaProvider
from app.research.synthesizer import synthesize


class FixedProvider:
    def __init__(self, text):
        self.text = text

    async def generate(self, *, system, user):
        return type("Result", (), {"text": self.text, "usage": type("Usage", (), {"input_tokens": 1, "output_tokens": 1})()})()


@pytest.fixture(autouse=True)
def fake_provider_env(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")


def test_synthesizer_keeps_existing_task_citation():
    result = TaskResult("T1", "api_architecture", "COMPLETE", "Answer [e1]", evidence_ids=["e1"], citations=["e1"])
    text = asyncio.run(synthesize(FixedProvider("Summary [e1]"), "question", [result], RunMetrics()))
    assert "[e1]" in text


def test_synthesizer_appends_citation_when_text_has_no_locator():
    result = TaskResult("T1", "api_architecture", "COMPLETE", "Answer", evidence_ids=["e1"], citations=["e1"])
    text = asyncio.run(synthesize(FixedProvider("Summary without locator"), "question", [result], RunMetrics()))
    assert "Answer\n\nNguồn: [e1]" in text
    assert text.endswith("**Tóm tắt**\nSummary without locator")


def test_synthesizer_does_not_add_unknown_ids():
    result = TaskResult("T1", "api_architecture", "COMPLETE", "Answer", evidence_ids=["e1"], citations=["e1"])
    text = asyncio.run(synthesize(FixedProvider("Summary [unknown]"), "question", [result], RunMetrics()))
    assert "[unknown]" not in text
    assert "[e1]" in text


def test_synthesizer_removes_only_unknown_markers_in_mixed_text():
    result = TaskResult("T1", "api_architecture", "COMPLETE", "Answer", evidence_ids=["e1"], citations=["e1"])
    summary = "Known [e1]; unknown [e10][UNKNOWN], repeated [UNKNOWN]. Known again [e1]."
    text = asyncio.run(synthesize(FixedProvider(summary), "question", [result], RunMetrics()))
    assert text.startswith("**API / Kiến trúc**\nAnswer\n\nNguồn: [e1]")
    assert text.split("**Tóm tắt**\n", 1)[1] == "Known [e1]; unknown , repeated . Known again [e1]."


def test_synthesizer_preserves_all_known_locators_across_tasks_exactly():
    locator = "src_0123456789abcdef_c0001"
    results = [
        TaskResult("T1", "api_architecture", "COMPLETE", "Answer", evidence_ids=["e1"], citations=["e1"]),
        TaskResult("T2", "security", "COMPLETE", "Answer", evidence_ids=[locator], citations=[locator]),
    ]
    summary = f"First [e1], second [{locator}].\nRepeat [e1][{locator}]."
    text = asyncio.run(synthesize(FixedProvider(summary), "question", results, RunMetrics()))
    assert "**API / Kiến trúc**\nAnswer\n\nNguồn: [e1]" in text
    assert f"**Bảo mật**\nAnswer\n\nNguồn: [{locator}]" in text
    assert text.split("**Tóm tắt**\n", 1)[1] == summary


def test_synthesizer_preserves_evidence_locator_without_worker_citation():
    result = TaskResult("T1", "api_architecture", "PARTIAL", "Answer", evidence_ids=["e2"])
    text = asyncio.run(synthesize(FixedProvider("Evidence [e2]; unknown [e3]."), "question", [result], RunMetrics()))
    assert text.startswith("**API / Kiến trúc**\nAnswer")
    assert text.split("**Tóm tắt**\n", 1)[1] == "Evidence [e2]; unknown ."


@pytest.mark.parametrize("results", [[], [TaskResult("T1", "api_architecture", "NO_EVIDENCE", "Answer")]])
def test_synthesizer_removes_locators_when_no_evidence_is_available(results):
    text = asyncio.run(synthesize(FixedProvider("Unsupported [unknown]."), "question", results, RunMetrics()))
    assert text.split("**Tóm tắt**\n", 1)[1] == "Unsupported ."
    assert "[unknown]" not in text


def test_grounded_generation_schema_limits_citations_to_allowed_ids(monkeypatch):
    provider = OllamaProvider()
    captured = {}

    async def capture(*, system, user, response_schema=None, max_output_tokens=None):
        captured["schema"] = response_schema
        return type("Result", (), {"text": "{}", "usage": type("Usage", (), {"input_tokens": 0, "output_tokens": 0})()})()

    monkeypatch.setattr(provider, "_generate", capture)
    asyncio.run(provider.generate_grounded(system="grounded", user="prompt", evidence_ids=["e1", "e2", "e1"]))
    citation_schema = captured["schema"]["properties"]["citations"]
    assert citation_schema["items"]["enum"] == ["e1", "e2"]
    assert "e3" not in citation_schema["items"]["enum"]
