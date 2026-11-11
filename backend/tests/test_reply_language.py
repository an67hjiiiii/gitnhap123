import asyncio
from types import SimpleNamespace

from app.core.types import RunMetrics, SourceChunk
from app.research.vanilla import answer_vanilla


class CapturingProvider:
    def __init__(self):
        self.user = ""

    async def generate(self, system, user):
        self.user = user
        return SimpleNamespace(text='{"status":"COMPLETE","answer":"ok","citations":["c1"],"missing_information":[]}', usage=None)


def _run(reply_language):
    provider = CapturingProvider()
    chunk = SourceChunk(chunk_id="c1", source_id="s1", source_name="doc.md", text="Idempotency keys are kept for 24 hours.", index=0)
    metrics = RunMetrics()
    metrics.add_usage = lambda usage: None
    asyncio.run(answer_vanilla(provider, "Khóa giữ bao lâu?", [chunk], metrics, reply_language=reply_language))
    return provider.user


def test_product_mode_adds_vietnamese_hint_at_end():
    assert _run("vi").rstrip().endswith("chunk ID.")
    assert "tiếng Việt" in _run("vi")


def test_research_condition_prompt_unchanged_without_language():
    user = _run(None)
    assert "NGÔN NGỮ" not in user and "LANGUAGE:" not in user
