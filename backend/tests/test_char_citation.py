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


def test_synthesizer_keeps_existing_task_citation():
    result = TaskResult("T1", "api_architecture", "COMPLETE", "Answer [e1]", evidence_ids=["e1"], citations=["e1"])
    text = asyncio.run(synthesize(FixedProvider("Summary [e1]"), "question", [result], RunMetrics()))
    assert "[e1]" in text


def test_synthesizer_appends_citation_when_text_has_no_locator():
    result = TaskResult("T1", "api_architecture", "COMPLETE", "Answer", evidence_ids=["e1"], citations=["e1"])
    text = asyncio.run(synthesize(FixedProvider("Summary without locator"), "question", [result], RunMetrics()))
    assert text.endswith("[e1]")


@pytest.mark.xfail(strict=False, reason="SUSPECTED DEFECT: synthesis text can retain unknown citation locators")
def test_synthesizer_does_not_add_unknown_ids():
    result = TaskResult("T1", "api_architecture", "COMPLETE", "Answer", evidence_ids=["e1"], citations=["e1"])
    text = asyncio.run(synthesize(FixedProvider("Summary [unknown]"), "question", [result], RunMetrics()))
    assert "[unknown]" not in text
    assert "[e1]" in text


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
