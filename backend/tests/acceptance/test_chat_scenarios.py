from __future__ import annotations

from app.core.types import Usage
from app.research.conversation_context import build_conversation_context
from app.research.pipeline import ResearchPipeline
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.usage = Usage(input_tokens=1, output_tokens=1)


class DeterministicFakeProvider:
    name = "fake"
    model = "acceptance-fake"

    async def generate(self, *, system, user):
        if "VANILLA_RAG_ANSWERER" in system:
            evidence = user.split("EVIDENCE:", 1)[-1]
            return FakeResponse('{"status":"NO_EVIDENCE","answer":"No evidence.","citations":[],"missing_information":["relevant evidence"]}' if not evidence.strip() else '{"status":"PARTIAL","answer":"Evidence reviewed.","citations":[],"missing_information":["complete detail"]}')
        return FakeResponse('{"tasks":[{"task_id":"T1","goal":"Answer request","domain":"general","depends_on":[],"evidence_needs":["request"]}]}')

    async def generate_grounded(self, *, system, user, evidence_ids):
        return await self.generate(system=system, user=user)


def test_short_greeting_and_ambiguous_queries_record_pipeline_trace(monkeypatch, tmp_path, sf1_fake_provider_env):
    monkeypatch.setattr("app.research.pipeline.get_provider", lambda name=None: DeterministicFakeProvider())
    pipeline = ResearchPipeline(SourceStore(str(tmp_path / "sources")), RunStore(str(tmp_path / "runs")))
    for query in ("Hi", "?", "Can you help?"):
        run = __import__("asyncio").run(pipeline.run(query, condition="A", provider_name="fake"))
        assert run["provider"] == "fake"
        assert any(event["stage"] == "vanilla_retrieval" for event in run["events"])
        assert run["status"] == "NO_EVIDENCE"


def test_context_window_limits_six_messages_and_six_thousand_chars():
    messages = [{"message_id": str(i), "role": "USER", "content": f"message-{i}"} for i in range(8)]
    bounded = build_conversation_context({"messages": messages})
    assert len(bounded.message_ids) == 6
    assert bounded.truncated is True
    huge = build_conversation_context({"messages": [{"message_id": "x", "role": "USER", "content": "x" * 7000}]})
    assert huge.truncated is True
    assert len(huge.text) <= 6000


def test_follow_up_reference_uses_last_user_request_for_retrieval(tmp_path, monkeypatch, sf1_fake_provider_env):
    from app.research.pipeline import _retrieval_query_with_conversation_context
    context = build_conversation_context({"messages": [{"message_id": "1", "role": "USER", "content": "Explain the Aurora retention rule"}]})
    assert "Aurora retention rule" in _retrieval_query_with_conversation_context("What about that approach?", context)
    assert _retrieval_query_with_conversation_context("Explain something else", context) == "Explain something else"


def test_reply_language_detection_for_english_and_vietnamese(sf1_fake_provider_env):
    from app.retrieval.multilingual import detect_language
    assert detect_language("What is the retention period?") == "en"
    assert detect_language("Thời hạn lưu trữ là bao lâu?") == "vi"



import pytest


@pytest.mark.xfail(strict=True, reason="LIMITATION: bare deictic 'that?'/'what about it' without a listed noun is matched only for it/they/this one; 'What about that?' is not resolved to the last user request")
def test_bare_that_follow_up_is_not_resolved(sf1_fake_provider_env):
    from app.research.pipeline import _retrieval_query_with_conversation_context
    context = build_conversation_context({"messages": [{"message_id": "1", "role": "USER", "content": "Explain the Aurora retention rule"}]})
    assert "Aurora retention rule" in _retrieval_query_with_conversation_context("What about that?", context)
