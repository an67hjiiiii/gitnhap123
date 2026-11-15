"""Hiển thị kết quả: grounding, [n]/sources, thẻ thừa, tóm tắt, tổng quan kho."""
import asyncio
import sys

import pytest

from app.chat.intent import classify_intent
from app.chat.sources import number_sources
from app.core.text_clean import strip_placeholder_tags
from tests.test_chat_endpoint import chat_http  # noqa: F401

CID = "src_016855f8947d6bcf_c0000"
CID2 = "src_f4e3a774bd39c208_c0001"
CHUNKS = {
    CID: {"source_name": "ghi_chu.txt", "text": "Nhật ký ghi thời điểm tải lên.", "provenance": {"section_path": "Nhật ký"}},
    CID2: {"source_name": "requirements_en.txt", "text": "Personal data must be restricted.", "provenance": {}},
}


def test_exact_strings_from_the_screenshot_are_cleaned():
    raw = (f"Nhật ký cần ghi thời điểm tải lên, theo tài liệu ghi_chu.txt ghi_chu.txt <{CID}>.\n\n"
           f"Nguồn: [{CID}], [{CID2}]")
    body, sources = number_sources(raw, CHUNKS.get)
    body = strip_placeholder_tags(body)
    assert "src_" not in body and "Nguồn:" not in body and "<" not in body
    assert body.count("ghi_chu.txt") == 1
    assert "[1]" in body
    assert [s["n"] for s in sources] == [1, 2] and sources[0]["doc_name"] == "ghi_chu.txt"
    assert sources[0]["section"] == "Nhật ký" and sources[0]["chunk_id"] == CID and sources[0]["snippet"]


def test_duplicate_file_name_variants():
    for raw in ("theo tài liệu x.txt.x.txt ok", "theo tài liệu x.txt x.txt ok", "theo tài liệu x.txt, x.txt ok"):
        assert strip_placeholder_tags(raw).count("x.txt") == 1
    assert strip_placeholder_tags("a.txt và b.txt") == "a.txt và b.txt"


def test_unknown_chunk_id_is_never_shown():
    body, sources = number_sources(f"Có [{CID}] và [src_deadbeef_c0009].", {CID: CHUNKS[CID]}.get)
    assert "src_" not in body and len(sources) == 1


def test_overview_intent_rules():
    for q in ("Trong tài liệu có gì?", "Có những tài liệu nào?", "Kho có gì?", "What documents do I have?"):
        assert classify_intent(q).intent == "corpus_overview", q
    assert classify_intent("Mật khẩu hết hạn sau bao lâu?").intent == "document_question"


def test_direct_answers_have_grounding_none_and_no_note(chat_http):  # noqa: F811
    body = chat_http.post("/api/chat", json={"message": "REST là gì?", "product_mode": True}).json()
    assert body["grounding"] == "none" and body["sources"] == []
    assert "Không dựa trên tài liệu" not in body["answer"] and "Not based on" not in body["answer"]


def test_overview_is_built_by_code_and_empty_store_says_so(chat_http):  # noqa: F811
    empty = chat_http.post("/api/chat", json={"message": "Trong tài liệu có gì?", "product_mode": True}).json()
    assert empty["events"][0]["path"] == "OVERVIEW" and "chưa có tài liệu" in empty["answer"]
    chat_http.post("/api/sources/text", json={"source_name": "quy_dinh.md",
                                              "text": "# Bảo mật\n\nMật khẩu hết hạn sau 90 ngày.\n\n# Sao lưu\n\nSao lưu hằng đêm."})
    body = chat_http.post("/api/chat", json={"message": "Kho có gì?", "product_mode": True}).json()
    assert body["events"][0]["path"] == "OVERVIEW" and body["run_id"] is None
    assert "Kho hiện có 1 tài liệu" in body["answer"] and "quy_dinh.md" in body["answer"]
    assert "Bảo mật" in body["answer"] and body["grounding"] == "document"
    assert not any(e["stage"] == "request_understanding" for e in body["events"])  # no pipeline, no Analysis


def test_document_answer_has_numbered_sources_and_no_chunk_ids(chat_http):  # noqa: F811
    chat_http.post("/api/sources/text", json={"source_name": "quy_dinh.md", "text": "Mật khẩu hết hạn sau 90 ngày."})
    body = chat_http.post("/api/chat", json={"message": "Mật khẩu hết hạn sau bao lâu?", "product_mode": True}).json()
    assert body["grounding"] == "document" and isinstance(body["sources"], list)
    assert "src_" not in body["answer"] and "Nguồn:" not in body["answer"]
    for s in body["sources"]:
        assert set(s) == {"n", "doc_name", "section", "snippet", "chunk_id"}
    assert body["task_results"]  # old fields untouched


def _result(task_id, domain, answer):
    from app.core.types import TaskResult
    return TaskResult(task_id=task_id, domain=domain, status="COMPLETE", answer=answer, citations=[], evidence_ids=[],
                      missing_information=[])


class Summarizer:
    calls = 0

    async def generate(self, *, system, user):
        Summarizer.calls += 1
        from app.core.types import Usage
        return type("R", (), {"text": "Hai miền đều được đáp ứng đầy đủ.", "usage": Usage(output_tokens=10),
                              "done_reason": "stop"})()


def test_summary_only_for_long_multi_domain_bodies():
    from app.core.types import RunMetrics
    from app.research.synthesizer import synthesize

    short = [_result("t1", "security", "Ngắn."), _result("t2", "database", "Ngắn nữa.")]
    Summarizer.calls = 0
    out = asyncio.run(synthesize(Summarizer(), "q", short, RunMetrics()))
    assert "Tóm tắt" not in out and Summarizer.calls == 0
    long_text = "Nội dung chi tiết về yêu cầu. " * 15
    one_domain = [_result("t1", "security", long_text), _result("t2", "security", long_text)]
    assert "Tóm tắt" not in asyncio.run(synthesize(Summarizer(), "q", one_domain, RunMetrics()))
    two = [_result("t1", "security", long_text), _result("t2", "database", long_text)]
    out = asyncio.run(synthesize(Summarizer(), "q", two, RunMetrics()))
    assert "**Tóm tắt**" in out and out.count("Hai miền") == 1


def test_summary_that_repeats_the_body_is_dropped():
    from app.core.types import RunMetrics
    from app.research.synthesizer import synthesize

    long_text = "Hai miền đều được đáp ứng đầy đủ theo yêu cầu. " * 15

    two = [_result("t1", "security", long_text), _result("t2", "database", long_text)]
    out = asyncio.run(synthesize(Summarizer(), "q", two, RunMetrics()))
    assert "Tóm tắt" not in out


def test_cross_sentence_subject_number_is_supported():
    from app.chat.answer_guard import guard_answer

    src = "Requests use a Bearer token. A token expires after 24 hours."
    out = guard_answer("Bearer token hết hạn sau 24 giờ, theo tài liệu api_guide_en.md.", status="COMPLETE",
                       evidence_texts=[src], cited_texts=[src])
    assert out.removed_claims == [] and "24" in out.answer


def test_wrong_subject_number_is_still_flagged():
    from app.chat.answer_guard import guard_answer

    a, b = "Mật khẩu hết hạn sau 90 ngày.", "Nhật ký truy cập giữ 90 ngày."
    out = guard_answer("Mật khẩu hết hạn sau 90 ngày.", status="COMPLETE", evidence_texts=[a, b], cited_texts=[b])
    assert out.removed_claims
