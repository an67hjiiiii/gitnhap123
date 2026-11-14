import asyncio
import json

import pytest

from app.core.types import ProviderResult, RunMetrics, SourceChunk, Task, TaskResult
from app.research.synthesizer import synthesize
from app.research.vanilla import REPLY_LANGUAGE_HINT, answer_vanilla
from app.research.worker import execute_task

SCHEMA = ('Schema: {"status":"COMPLETE|PARTIAL|NO_EVIDENCE","answer":"...",'
          '"citations":["chunk_id"],"missing_information":[]}')


class CapturingFakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def generate(self, *, system, user):
        self.calls.append((system, user))
        return ProviderResult(text=self.response)


class GroundedFakeProvider(CapturingFakeProvider):
    async def generate_grounded(self, *, system, user, evidence_ids):
        self.evidence_ids = evidence_ids
        return await self.generate(system=system, user=user)


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")


def run_answer(answerer, provider, evidence, metrics):
    if answerer == "vanilla":
        return asyncio.run(answer_vanilla(provider, "Khóa giữ bao lâu?", evidence, metrics))
    return asyncio.run(execute_task(provider, Task("T2", "Khóa giữ bao lâu?"), evidence, metrics))


@pytest.mark.parametrize("answerer,marker", [("vanilla", "VANILLA_RAG_ANSWERER"), ("worker", "WORKER")])
@pytest.mark.parametrize("provider_type", [CapturingFakeProvider, GroundedFakeProvider])
@pytest.mark.parametrize("source_name,source_id,expected_name", [
    ("Hướng dẫn API.md", "s1", "Hướng dẫn API.md"),
    ("", "s1", "s1"),
    ("", "", "id"),
])
def test_answer_prompt_contract(answerer, marker, provider_type, source_name, source_id, expected_name):
    provider = provider_type(json.dumps({
        "status": "COMPLETE", "answer": "Khóa được giữ 24 giờ.",
        "citations": ["id"], "missing_information": [],
    }))
    evidence = [SourceChunk("id", source_id, source_name, "Keys expire after 24 hours.", 0)]
    metrics = RunMetrics()
    result = run_answer(answerer, provider, evidence, metrics)
    system, user = provider.calls[0]

    assert marker in system
    assert SCHEMA in user
    assert f"[id] Tài liệu: {expected_name}\nKeys expire after 24 hours." in user
    assert "theo tài liệu <source name>" in system
    assert "tối đa 4 câu, khoảng 100 từ" in system
    assert "đúng một bước tiếp theo cụ thể" in system
    assert system.count("Ví dụ") == 2
    examples = [json.loads(line) for line in system.splitlines() if line.startswith("{")]
    assert examples[0]["answer"] == "Khóa được giữ 24 giờ, theo tài liệu API.md."
    assert examples[0]["citations"] == ["c1"]
    assert examples[1]["answer"] == "Mình chưa tìm thấy giới hạn tải tệp. Bạn hãy tải lên tài liệu quy định dung lượng tệp."
    assert examples[1]["status"] == "NO_EVIDENCE"
    assert examples[1]["citations"] == []
    if answerer == "vanilla":
        assert SCHEMA in system
        assert len(system) <= 1800
        assert result.answer == "Khóa được giữ 24 giờ.\n\nNguồn: [id]"
    if isinstance(provider, GroundedFakeProvider):
        assert provider.evidence_ids == ["id"]
    assert result.status == "COMPLETE"
    assert result.evidence_ids == result.citations == ["id"]
    assert result.invalid_citations == result.missing_information == []
    assert metrics.llm_calls == metrics.citations_valid == metrics.citations_emitted == 1


def test_vanilla_no_evidence_exact_answer_without_provider_call():
    provider = CapturingFakeProvider("must not be used")
    metrics = RunMetrics()
    result = asyncio.run(answer_vanilla(provider, "Giới hạn tải tệp?", [], metrics))
    assert result.answer == "Mình chưa tìm thấy thông tin này trong các tài liệu đã tải lên. Bạn có thể tải thêm tài liệu liên quan hoặc hỏi cụ thể hơn (ví dụ nêu tên mục hoặc giá trị cần tìm), mình sẽ tra lại."
    assert result.status == "NO_EVIDENCE"
    assert result.evidence_ids == result.citations == result.invalid_citations == []
    assert result.missing_information == ["relevant evidence"]
    assert provider.calls == []
    assert metrics.llm_calls == 0


def test_worker_no_evidence_gives_next_step_without_provider_call():
    provider = CapturingFakeProvider("must not be used")
    result = run_answer("worker", provider, [], RunMetrics())
    assert result.answer == "Mình chưa tìm thấy thông tin cho phần này trong tài liệu đã tải lên. Bạn hãy tải thêm tài liệu liên quan đến phần này."
    assert result.status == "NO_EVIDENCE"
    assert result.citations == result.evidence_ids == []
    assert result.missing_information == ["relevant evidence"]
    assert provider.calls == []


@pytest.mark.parametrize("answerer", ["vanilla", "worker"])
@pytest.mark.parametrize("citations", [["id", "unknown"], []])
def test_invalid_or_absent_citations_still_downgrade_complete(answerer, citations):
    provider = CapturingFakeProvider(json.dumps({
        "status": "COMPLETE", "answer": "Khóa được giữ 24 giờ.",
        "citations": citations, "missing_information": [],
    }))
    evidence = [SourceChunk("id", "s1", "API.md", "Keys expire after 24 hours.", 0)]
    result = run_answer(answerer, provider, evidence, RunMetrics())
    assert result.status == "PARTIAL"
    assert result.citations == (["id"] if citations else [])
    assert result.invalid_citations == (["unknown"] if citations else [])
    expected_missing = ("invalid citation locator(s) removed" if citations else
                        "answer has no valid citation" if answerer == "vanilla" else
                        "worker answer has no valid citation")
    assert result.missing_information == [expected_missing]
    if answerer == "vanilla":
        if citations:
            assert result.answer.endswith("\n\nNguồn: [id]")
        else:
            assert "Nguồn:" not in result.answer


@pytest.mark.parametrize("language,phrase", [("vi", "4 câu, khoảng 100 từ"), ("en", "4 sentences, about 100 words")])
def test_language_hint_keeps_short_answer_budget(language, phrase):
    assert phrase in REPLY_LANGUAGE_HINT[language]


def test_synthesizer_prompt_preserves_order_missing_parts_and_footer():
    provider = CapturingFakeProvider("Bản tổng hợp.")
    results = [
        TaskResult("T2", "general", "COMPLETE", "Khóa giữ 24 giờ, theo tài liệu API.md.",
                   evidence_ids=["id"], citations=["id"]),
        TaskResult("T1", "general", "NO_EVIDENCE", "Chưa tìm thấy giới hạn tải tệp.",
                   missing_information=["giới hạn tải tệp"]),
    ]
    answer = asyncio.run(synthesize(provider, "Thời hạn khóa và giới hạn tải tệp?", results, RunMetrics()))
    system, user = provider.calls[0]
    assert "SYNTHESIZER" in system
    assert "một đoạn ngắn theo đúng thứ tự TASK RESULTS" in system
    assert "một câu kết luận chung" in system
    assert "PARTIAL/NO_EVIDENCE" in system
    assert "nói rõ phần chưa tìm thấy" in system
    assert "theo tài liệu <source name>" in system
    assert system.count("Ví dụ") == 2
    assert user.index("TASK T2") < user.index("TASK T1")
    assert "theo tài liệu API.md" in user
    assert "missing=giới hạn tải tệp" in user
    assert answer == "Bản tổng hợp.\n\nNguồn: [id]"
