"""Đợt 2b (19/11): hiện chữ dần và tiến trình từng bước ở ô chat sản phẩm (/api/chat/stream).

Không có người nghe (thực nghiệm, /api/chat) thì không gửi gì và provider không nhận on_text.
"""
from __future__ import annotations

import asyncio
import json

from app.core.structured_output import partial_answer
from app.core.types import ProviderResult, RunMetrics, TaskResult, Usage
from app.research.progress import answer_streamer, emit, ndjson_run, progress_sink
from app.research.synthesizer import synthesize


def test_partial_answer_reads_unfinished_json():
    assert partial_answer('{"status":"COMPLETE","ans') is None
    assert partial_answer('{"answer": "Thử việc tối đa 60') == "Thử việc tối đa 60"
    assert partial_answer('{"answer": "Dòng 1\\nDòng 2 \\"trích\\" \\') == 'Dòng 1\nDòng 2 "trích" '


def test_no_listener_means_no_streaming_kwargs():
    class P:
        supports_streaming = True

    assert answer_streamer(P()) == {}
    emit({"type": "progress", "stage": "x"})  # không có người nghe: không lỗi, không làm gì


class StreamingProvider:
    supports_per_call_output_tokens = True
    supports_streaming = True

    def __init__(self):
        self.got_on_text = False

    async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None, on_text=None):
        full = '{"answer": "Ý 1 [c1]. Ý 2 [c1]."}'
        if on_text:
            self.got_on_text = True
            for i in range(5, len(full) + 1, 6):
                on_text(full[:i])
        return ProviderResult(text=full, usage=Usage(1, 1), request_id="r", model="m")


def _results():
    return [TaskResult(task_id="T1", domain="general", status="COMPLETE", answer="a", citations=["c1"], evidence_ids=["c1"])]


def test_synthesis_does_not_stream_draft_answer_before_verification():
    items: list[dict] = []
    provider = StreamingProvider()

    async def go():
        token = progress_sink.set(items.append)
        try:
            return await synthesize(provider, "q", _results(), RunMetrics(), max_output_tokens=1800)
        finally:
            progress_sink.reset(token)

    assert asyncio.run(go()) == "Ý 1 [c1]. Ý 2 [c1]."
    assert provider.got_on_text is False
    assert not any(i.get("type") == "answer" for i in items)

    quiet = StreamingProvider()
    asyncio.run(synthesize(quiet, "q", _results(), RunMetrics(), max_output_tokens=1800))
    assert quiet.got_on_text is False


async def _collect(factory):
    return [json.loads(line) async for line in ndjson_run(factory)]


def test_ndjson_run_sends_progress_then_done():
    async def run():
        emit({"type": "progress", "stage": "vanilla_retrieval"})
        emit({"type": "answer", "text": "Th"})
        return {"run_id": "r1", "status": "COMPLETE"}

    lines = asyncio.run(_collect(run))
    assert [line["type"] for line in lines] == ["progress", "done"]
    assert lines[-1]["run"]["run_id"] == "r1"


def test_ndjson_stream_drops_unverified_citation_and_keeps_final_run():
    async def run():
        emit({"type": "answer", "text": "Nháp có citation [not_allowed]"})
        emit({"type": "progress", "stage": "verifying"})
        return {"run_id": "r2", "status": "PARTIAL", "answer": "Kết quả đã lọc [c1]"}

    events = asyncio.run(_collect(run))
    assert [e["type"] for e in events] == ["progress", "done"]
    assert "not_allowed" not in json.dumps(events)
    assert events[-1]["run"]["answer"] == "Kết quả đã lọc [c1]"


def test_ndjson_stream_drops_unverified_draft_on_failure():
    async def run():
        emit({"type": "answer", "text": "Bản nháp [bad_source]"})
        raise ValueError("failed")

    events = asyncio.run(_collect(run))
    assert len(events) == 1 and events[0]["type"] == "error"
    assert "bad_source" not in json.dumps(events)


def test_ndjson_run_reports_errors_instead_of_cutting_stream():
    class Http(Exception):
        status_code = 404
        detail = "conversation not found"

    async def not_found():
        raise Http()

    async def boom():
        raise RuntimeError("x")

    assert asyncio.run(_collect(not_found)) == [{"type": "error", "status": 404, "detail": "conversation not found"}]
    assert asyncio.run(_collect(boom)) == [{"type": "error", "status": 500, "detail": "RuntimeError"}]


def test_ollama_stream_assembles_text_and_reads_usage(monkeypatch):
    from app.providers import ollama as mod

    chunks = [
        {"message": {"content": '{"answer": "Xin '}},
        {"message": {"content": 'chào"}'}},
        {"message": {"content": ""}, "done": True, "prompt_eval_count": 12, "eval_count": 7},
    ]
    sent: list[dict] = []

    class Resp:
        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            for c in chunks:
                yield json.dumps(c)

    class Ctx:
        async def __aenter__(self):
            return Resp()

        async def __aexit__(self, *a):
            return False

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, json):
            sent.append(json)
            return Ctx()

    monkeypatch.setattr(mod.httpx, "AsyncClient", Client)
    seen: list[str] = []
    result = asyncio.run(mod.OllamaProvider(model="m").generate_structured(
        system="s", user="u", response_schema={"type": "object"}, on_text=seen.append))
    assert sent[0]["stream"] is True
    assert result.text == '{"answer": "Xin chào"}' and seen[-1] == result.text
    assert (result.usage.input_tokens, result.usage.output_tokens) == (12, 7)
