from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from app.chat.memory import (
    MemoryView,
    SummaryCache,
    build_memory,
    has_reference,
    render_context,
    rewrite_follow_up,
)
from app.core.types import ProviderResult


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")


class FakeProvider:
    def __init__(self, text="Tóm tắt quyết định: lưu 90 ngày.", *, raises=False):
        self.text = text
        self.raises = raises
        self.calls = []

    async def generate(self, *, system, user):
        self.calls.append({"system": system, "user": user})
        if self.raises:
            raise RuntimeError("fake provider unavailable")
        return ProviderResult(text=self.text)


def conversation(count):
    return {
        "conversation_id": "conversation-1",
        "messages": [
            {"message_id": str(i), "role": "USER" if i % 2 == 0 else "ASSISTANT",
             "content": f"Message {i}", "sequence_number": i}
            for i in range(count)
        ],
    }


def build(provider, history, **kwargs):
    kwargs.setdefault("cache", SummaryCache())
    return asyncio.run(build_memory(provider, "owner-1", history, **kwargs))


@pytest.mark.parametrize("message", [
    "What about that?", "it", "its", "they", "their", "them", "that",
    "this one", "this   one", "this approach", "this design", "this system",
    "this topic", "this question", "this request",
    "those", "same", "previous", "earlier", "follow-up",
    "How about retention?", "nó", "đó", "này", "ấy", "vậy", "thế",
    "Còn cái đó thì sao?", "ý đó", "như trên", "ở trên", "trước đó",
    "tiếp theo", "CON CAI DO THI SAO?", "NHU TREN", "TIEP THEO",
    "Còn thời hạn?", "And retention?", "  AND retention?",
])
def test_reference_phrases(message):
    assert has_reference(message) is True


@pytest.mark.parametrize("message", [
    "Explain the retention rule", "Mật khẩu phải có bao nhiêu ký tự?",
    "Giá trị mặc định là bao nhiêu?", "", "another approach", "nothing",
    "And explain retention policies across all archived audit logs please",
])
def test_independent_messages(message):
    # English articles must not be mistaken for Vietnamese deictics.
    assert has_reference(message) is False


@pytest.mark.parametrize("count", [0, 1, 6])
def test_short_history_needs_no_summary_call(count):
    provider = FakeProvider()
    history = conversation(count)
    memory = build(provider, history)
    assert memory.summary == ""
    assert memory.recent == history["messages"]
    assert provider.calls == []


@pytest.mark.parametrize("history", [None, {}, {"messages": None}, {"messages": "bad"}])
def test_missing_history(history):
    provider = FakeProvider()
    assert build(provider, history) == MemoryView("", [])
    assert provider.calls == []


def test_nine_messages_summarize_older_once_and_cache():
    provider, cache = FakeProvider(), SummaryCache()
    history = conversation(9)
    first = build(provider, history, cache=cache)
    assert first.summary == "Tóm tắt quyết định: lưu 90 ngày."
    assert first.recent == history["messages"][-6:]
    assert first.recent[0] is history["messages"][3]
    assert len(provider.calls) == 1
    assert provider.calls[0]["user"] == "[USER] Message 0\n[ASSISTANT] Message 1\n[USER] Message 2"
    assert "120 từ" in provider.calls[0]["system"]
    assert build(provider, history, cache=cache) == first
    assert len(provider.calls) == 1


def test_only_nonempty_user_and_assistant_messages_are_eligible():
    history = conversation(6)
    history["messages"].extend([
        None, {"role": "SYSTEM", "content": "ignored"},
        {"role": "USER", "content": "  "}, {"role": "USER", "content": 7},
    ])
    provider = FakeProvider()
    memory = build(provider, history)
    assert memory.recent == history["messages"][:6]
    assert provider.calls == []


def test_recent_content_and_role_are_verbatim():
    history = {"messages": [{"role": "user", "content": "  original\ntext  "}]}
    assert build(FakeProvider(), history).recent == history["messages"]


def test_summary_input_is_capped_and_contains_only_older_turns():
    history = conversation(9)
    history["messages"][0]["content"] = "x" * 5000
    provider = FakeProvider()
    build(provider, history)
    assert provider.calls[0]["user"] == "[USER] " + "x" * 3993
    assert len(provider.calls) == 1


def test_summary_limit_is_applied_after_cache_lookup():
    provider, cache = FakeProvider("abcdefghij"), SummaryCache()
    assert build(provider, conversation(9), cache=cache, max_summary_chars=4).summary == "abcd"
    assert build(provider, conversation(9), cache=cache, max_summary_chars=8).summary == "abcdefgh"
    assert len(provider.calls) == 1


def test_cache_separates_owners_conversations_counts_and_last_ids():
    provider, cache = FakeProvider(), SummaryCache()
    history = conversation(9)
    build(provider, history, cache=cache)
    asyncio.run(build_memory(provider, "owner-2", history, cache=cache))
    history["conversation_id"] = "conversation-2"
    build(provider, history, cache=cache)
    history["messages"][2]["message_id"] = "replacement"
    build(provider, history, cache=cache)
    build(provider, history, cache=cache, keep_recent=5)
    assert len(provider.calls) == 5


def test_cache_does_not_alias_histories_without_ids():
    provider, cache = FakeProvider(), SummaryCache()
    history = conversation(9)
    del history["conversation_id"]
    build(provider, history, cache=cache)
    build(provider, history, cache=cache)
    assert len(provider.calls) == 2


def test_fallback_uses_last_four_older_users_and_is_cached():
    history = conversation(19)
    for row in history["messages"]:
        row["content"] = row["message_id"] + "x" * 140
    provider, cache = FakeProvider(raises=True), SummaryCache()
    memory = build(provider, history, cache=cache)
    assert memory.summary == " | ".join(
        history["messages"][i]["content"][:120] for i in (6, 8, 10, 12)
    )
    assert build(provider, history, cache=cache) == memory
    assert len(provider.calls) == 1


def test_fallback_without_older_users_is_empty():
    history = conversation(9)
    for row in history["messages"]:
        row["role"] = "ASSISTANT"
    assert build(FakeProvider(raises=True), history).summary == ""


def test_zero_recent_summarizes_every_turn():
    provider = FakeProvider()
    memory = build(provider, conversation(2), keep_recent=0)
    assert memory.recent == []
    assert memory.summary == provider.text
    assert provider.calls[0]["user"] == "[USER] Message 0\n[ASSISTANT] Message 1"


def test_fifo_eviction_does_not_refresh_on_get():
    cache = SummaryCache()
    for i in range(256):
        cache.put(("o", "c", i, str(i)), str(i))
    assert cache.get(("o", "c", 0, "0")) == "0"
    cache.put(("o", "c", 256, "256"), "256")
    assert cache.get(("o", "c", 0, "0")) is None
    assert cache.get(("o", "c", 1, "1")) == "1"
    assert cache.get(("o", "c", 256, "256")) == "256"


def test_cache_thread_safety():
    cache = SummaryCache()

    def round_trip(i):
        key = ("o", "c", i, str(i))
        cache.put(key, str(i))
        return cache.get(key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(round_trip, range(100))) == [str(i) for i in range(100)]


def test_memory_view_is_frozen():
    with pytest.raises(FrozenInstanceError):
        MemoryView("", []).summary = "changed"


def test_independent_question_skips_rewrite():
    provider = FakeProvider()
    message = "Giá trị mặc định là bao nhiêu?"
    assert asyncio.run(rewrite_follow_up(provider, message, MemoryView("summary", []))) == message
    assert provider.calls == []


def test_reference_without_memory_skips_rewrite():
    provider = FakeProvider()
    assert asyncio.run(rewrite_follow_up(provider, "What about that?", MemoryView("", []))) == "What about that?"
    assert provider.calls == []


def test_vietnamese_follow_up_rewrites_once():
    question = "Thời hạn lưu nhật ký kiểm toán là bao lâu?"
    provider = FakeProvider(question)
    memory = MemoryView("", [{"role": "USER", "content": question}])
    assert asyncio.run(rewrite_follow_up(provider, "Còn cái đó thì sao?", memory)) == question
    assert len(provider.calls) == 1
    assert question in provider.calls[0]["user"]
    assert "Còn cái đó thì sao?" in provider.calls[0]["user"]


@pytest.mark.parametrize("text", ["", "  \n ", '""', '" "', "x" * 400])
def test_empty_or_excessive_rewrite_returns_original(text):
    provider = FakeProvider(text)
    message = "What about that?"
    assert asyncio.run(rewrite_follow_up(provider, message, MemoryView("summary", []))) == message
    assert len(provider.calls) == 1


def test_rewrite_exception_returns_original():
    provider = FakeProvider(raises=True)
    message = "What about that?"
    assert asyncio.run(rewrite_follow_up(provider, message, MemoryView("summary", []))) == message
    assert len(provider.calls) == 1


def test_rewrite_strips_quotes_and_newlines():
    provider = FakeProvider(' “What is\nthe retention period?”\n')
    assert asyncio.run(rewrite_follow_up(provider, "What about that?", MemoryView("summary", []))) == "What is the retention period?"


def test_rewrite_caps_accepted_output_at_300_chars():
    provider = FakeProvider("x" * 350)
    assert asyncio.run(rewrite_follow_up(provider, "What about " + "x" * 90, MemoryView("summary", []))) == "x" * 300


def test_render_labels_and_chronological_order():
    memory = MemoryView("Lưu 90 ngày.", [
        {"role": "USER", "content": "Thời hạn?"},
        {"role": "ASSISTANT", "content": "90 ngày."},
    ])
    assert render_context(memory) == (
        "TÓM TẮT HỘI THOẠI TRƯỚC: Lưu 90 ngày.\n"
        "[USER] Thời hạn?\n[ASSISTANT] 90 ngày."
    )


def test_render_drops_older_context_before_newest():
    memory = MemoryView("older summary", [
        {"role": "USER", "content": "older"},
        {"role": "ASSISTANT", "content": "newest"},
    ])
    assert render_context(memory, max_chars=18) == "[ASSISTANT] newest"


@pytest.mark.parametrize("limit", [0, 1, 10, 20, 35, 6000, -1])
def test_render_obeys_character_budget(limit):
    memory = MemoryView("summary", conversation(9)["messages"])
    rendered = render_context(memory, max_chars=limit)
    assert len(rendered) <= max(0, limit)
    if limit >= len("[USER] Message 8"):
        assert rendered.endswith("[USER] Message 8")


def test_empty_context_has_no_summary_label():
    assert render_context(MemoryView("", [])) == ""
