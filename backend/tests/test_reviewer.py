"""Đợt 5 kế hoạch Văn phòng 3D: Reviewer đối chiếu ý với bằng chứng, không tự sửa, lỗi thì không coi là đã duyệt."""
import asyncio
import json
from types import SimpleNamespace

from app.core.types import RunMetrics, Usage
from app.research.reviewer import annotate, review_answer, reviewer_enabled


class StubProvider:
    supports_per_call_output_tokens = True

    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    async def generate_structured(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(text=self.text, usage=Usage(input_tokens=10, output_tokens=5))


ANSWER = "Nhân viên thử việc không được nghỉ phép năm. Ngân sách quý IV là 300 triệu."
EVIDENCE = "Nhân viên thử việc không được nghỉ phép năm. Ngân sách quảng cáo quý IV là 200 triệu đồng."


def run(coro):
    return asyncio.run(coro)


def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("PRODUCT_REVIEWER", raising=False)
    assert reviewer_enabled() is False
    monkeypatch.setenv("PRODUCT_REVIEWER", "On")
    assert reviewer_enabled() is True


def test_unsupported_claims_are_listed_not_rewritten():
    p = StubProvider(json.dumps({"claims": [
        {"claim": "Thử việc không được nghỉ phép năm", "supported": True},
        {"claim": "Ngân sách quý IV là 300 triệu", "supported": False},
    ]}, ensure_ascii=False))
    m = RunMetrics()
    review = run(review_answer(p, ANSWER, EVIDENCE, m))
    assert review == {"status": "ok", "checked": 2, "unsupported": ["Ngân sách quý IV là 300 triệu"]}
    assert m.llm_calls == 1 and p.calls[0]["max_output_tokens"] > 0 and "EVIDENCE:" in p.calls[0]["user"]
    out = annotate(ANSWER, review, "vi")
    assert out.startswith(ANSWER) and "Reviewer" in out and "300 triệu" in out.split("Reviewer")[1]


def test_all_supported_leaves_answer_unchanged():
    p = StubProvider(json.dumps({"claims": [{"claim": "a", "supported": True}]}))
    review = run(review_answer(p, ANSWER, EVIDENCE, RunMetrics()))
    assert review["unsupported"] == [] and annotate(ANSWER, review, "vi") == ANSWER


def test_bad_model_output_is_an_error_not_a_pass():
    for bad in ("không phải JSON", json.dumps({"claims": "x"}), json.dumps([1, 2])):
        review = run(review_answer(StubProvider(bad), ANSWER, EVIDENCE, RunMetrics()))
        assert review["status"] == "error" and annotate(ANSWER, review, "vi") == ANSWER


def test_missing_supported_counts_as_unsupported():
    p = StubProvider(json.dumps({"claims": [{"claim": "Ý không rõ", "supported": None}]}))
    assert run(review_answer(p, ANSWER, EVIDENCE, RunMetrics()))["unsupported"] == ["Ý không rõ"]


def test_skipped_without_evidence_or_structured_output():
    assert run(review_answer(StubProvider("{}"), ANSWER, "", RunMetrics()))["status"] == "skipped"
    assert run(review_answer(object(), ANSWER, EVIDENCE, RunMetrics()))["status"] == "skipped"
