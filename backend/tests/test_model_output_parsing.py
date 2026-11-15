"""Đầu ra mô hình bị cắt hoặc chỉ chép lại mẫu "..." không được làm sập lượt chạy hay bị báo COMPLETE."""
import asyncio
from types import SimpleNamespace

from app.core.types import RunMetrics, SourceChunk, Task
from app.research.vanilla import answer_vanilla
from app.research.worker import execute_task

CHUNK = SourceChunk(chunk_id="c1", source_id="s1", source_name="doc.md", text="Webhooks are retried 8 times.", index=0)


class FixedProvider:
    def __init__(self, text):
        self.text = text

    async def generate(self, system, user):
        return SimpleNamespace(text=self.text, usage=None)


def _metrics():
    metrics = RunMetrics()
    metrics.add_usage = lambda usage: None
    return metrics


def _worker(text):
    return asyncio.run(execute_task(FixedProvider(text), Task(task_id="T1", goal="How many retries?"), [CHUNK], _metrics()))


def _vanilla(text):
    return asyncio.run(answer_vanilla(FixedProvider(text), "Gửi lại mấy lần?", [CHUNK], _metrics()))


TRUNCATED = '{"status":"COMPLETE","citations":["c1"],"answer":"Webhook được gửi lại tối đa 8 lần, lịch gồm 1 phút, 5 ph'


def test_truncated_worker_output_keeps_readable_answer_as_partial():
    result = _worker(TRUNCATED)
    assert result.status == "PARTIAL"
    assert result.answer.startswith("Webhook được gửi lại tối đa 8 lần")
    assert result.citations == ["c1"]
    assert any("truncated" in item for item in result.missing_information)


def test_truncated_vanilla_output_does_not_raise():
    result = _vanilla(TRUNCATED)
    assert result.status == "PARTIAL"
    assert "8 lần" in result.answer


def test_braces_inside_unterminated_string_do_not_raise():
    result = _worker('{"status":"COMPLETE","answer":"Dùng {merchant_id} và {key} để khó')
    assert result.status == "PARTIAL" and "merchant_id" in result.answer


def test_placeholder_answer_is_not_complete():
    result = _worker('{"status":"COMPLETE","answer":"...","citations":["c1"],"missing_information":[]}')
    assert result.status == "PARTIAL"
    assert result.answer == ""


def test_valid_output_unchanged():
    result = _worker('{"status":"COMPLETE","answer":"8 lần.","citations":["c1"],"missing_information":[]}')
    assert result.status == "COMPLETE" and result.answer == "8 lần." and result.citations == ["c1"]
