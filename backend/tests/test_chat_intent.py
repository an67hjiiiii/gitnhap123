from __future__ import annotations
import json
import asyncio
import pytest
from app.chat.intent import INTENTS, classify_intent, classify_with_llm

@pytest.mark.parametrize(("message", "expected"), [
("Xin chào!","greeting"),("xin chao ban nhe","greeting"),("Hello there","greeting"),("hi","greeting"),("hey bạn","greeting"),("alo","greeting"),
("Cảm ơn bạn nhé","thanks"),("cam on","thanks"),("Thanks a lot","thanks"),("thank you","thanks"),
("tạm biệt","farewell"),("hen gap lai nhe","farewell"),("bye","farewell"),
("Bạn là ai?","about_system"),("ban lam duoc gi","about_system"),("Who are you?","about_system"),("what can you do","about_system"),("Hướng dẫn sử dụng","about_system"),
("Hôm nay thời tiết thế nào?","out_of_scope"),("Tell me a joke","out_of_scope"),("Write a poem","out_of_scope"),("Giá vàng hôm nay?","out_of_scope"),("Nấu ăn món gì?","out_of_scope"),
("Thời hạn lưu nhật ký kiểm toán là bao lâu?","document_question"),("What is the API timeout?","document_question"),("Bảo mật yêu cầu gì?","document_question"),("xyz","ambiguous"),
])
def test_classifies_common_intents(message, expected):
    assert classify_intent(message).intent == expected

def test_reply_language_and_content():
    vi, en = classify_intent("Xin chào!"), classify_intent("hello")
    assert vi.reply.startswith("Chào bạn")
    assert "upload" in en.reply.lower() and en.language == "en"
    assert classify_intent("Thời hạn lưu nhật ký kiểm toán là bao lâu?").reply is None

def test_history_follow_up_and_no_sources():
    assert classify_intent("Còn cái đó thì sao?", has_history=True).intent == "follow_up"
    d = classify_intent("API lưu nhật ký trong bao lâu?", has_sources=False)
    assert (d.intent, d.reason) == ("document_question", "NO_SOURCES")

class FakeProvider:
    def __init__(self, result=None, error=None): self.result, self.error, self.calls, self.kwargs = result, error, 0, None
    async def generate_structured(self, **kwargs):
        self.calls += 1; self.kwargs = kwargs
        if self.error: raise self.error
        return type("Result", (), {"text": self.result})()

def test_llm_valid_json_uses_enum_schema_and_one_call():
    p = FakeProvider(json.dumps({"intent":"follow_up"}))
    result = asyncio.run(classify_with_llm(p, "xyz"))
    assert result.intent == "follow_up" and p.calls == 1
    assert p.kwargs["max_output_tokens"] == 64
    assert p.kwargs["response_schema"]["properties"]["intent"]["enum"] == list(INTENTS)

@pytest.mark.parametrize("provider", [FakeProvider("not json"), FakeProvider(error=RuntimeError("failed"))])
def test_llm_invalid_or_exception_falls_back(provider):
    assert asyncio.run(classify_with_llm(provider, "xyz")).intent == "document_question"
    assert provider.calls == 1
