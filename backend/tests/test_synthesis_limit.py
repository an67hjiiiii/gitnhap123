"""Việc 1 (19/11): câu trả lời nhiều ý bị cắt vì bước tổng hợp chạm giới hạn 700 token.

Ô chat sản phẩm truyền giới hạn riêng (mặc định 1800); thực nghiệm A/B/C không truyền gì
nên vẫn dùng max_output_tokens cũ, giữ tái lập được kết quả trước đây.
"""
from __future__ import annotations

import asyncio

from app.core.config import RuntimeConfig
from app.core.types import ProviderResult, RunMetrics, TaskResult, Usage
from app.research.synthesizer import synthesize


class RecordingProvider:
    supports_per_call_output_tokens = True

    def __init__(self):
        self.calls: list[dict] = []

    async def generate(self, *, system, user, **kwargs):
        self.calls.append({"generate": kwargs})
        return ProviderResult(text="Ý 1 [c1]. Ý 2 [c1]. Ý 3 [c1].", usage=Usage(10, 10), request_id="r", model="m")

    async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None):
        self.calls.append({"structured": max_output_tokens, "schema": sorted(response_schema["properties"])})
        return ProviderResult(text='{"answer": "Ý 1 [c1]. Ý 2 [c1]. Ý 3 [c1]."}', usage=Usage(10, 10), request_id="r", model="m")


class LegacyProvider:
    """Provider kịch bản cũ chỉ nhận system/user: không được vỡ."""

    async def generate(self, *, system, user):
        return ProviderResult(text="ok [c1]", usage=Usage(1, 1), request_id="r", model="m")


def _results():
    return [TaskResult(task_id="T1", domain="general", status="COMPLETE", answer="a", citations=["c1"], evidence_ids=["c1"], missing_information=[])]


def test_product_limit_is_passed_to_provider():
    provider = RecordingProvider()
    text = asyncio.run(synthesize(provider, "3 ý", _results(), RunMetrics(), max_output_tokens=1800))
    assert provider.calls == [{"structured": 1800, "schema": ["answer"]}]
    assert text == "Ý 1 [c1]. Ý 2 [c1]. Ý 3 [c1]."  # lấy trường answer, không trả JSON thô


def test_experiment_path_passes_no_override():
    provider = RecordingProvider()
    asyncio.run(synthesize(provider, "3 ý", _results(), RunMetrics()))
    assert provider.calls == [{"generate": {}}]


def test_legacy_provider_still_works_with_limit():
    text = asyncio.run(synthesize(LegacyProvider(), "q", _results(), RunMetrics(), max_output_tokens=1800))
    assert "c1" in text


def test_default_synthesis_limit_above_old_cap(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("MAX_OUTPUT_TOKENS", raising=False)
    cfg = RuntimeConfig.from_env()
    assert cfg.max_output_tokens == 700  # thực nghiệm giữ nguyên
    assert cfg.synthesis_max_output_tokens == 1800


def test_ollama_synthesizer_uses_answer_schema_only_in_product(monkeypatch):
    """Prompt SYNTHESIZER chứa chữ "workers" từng khớp nhầm và ép format=json làm câu trả lời bị cắt giữa JSON."""
    from app.providers import ollama as mod

    sent: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}, "prompt_eval_count": 1, "eval_count": 1}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            sent.append(json)
            return FakeResponse()

    monkeypatch.setattr(mod.httpx, "AsyncClient", FakeClient)
    provider = mod.OllamaProvider(model="m")
    asyncio.run(synthesize(provider, "q", _results(), RunMetrics()))
    asyncio.run(synthesize(provider, "q", _results(), RunMetrics(), max_output_tokens=1800))
    assert sent[0].get("format") == "json" and sent[0]["options"]["num_predict"] == 700  # thực nghiệm: như cũ
    assert sent[1]["format"]["required"] == ["answer"] and sent[1]["options"]["num_predict"] == 1800  # sản phẩm
