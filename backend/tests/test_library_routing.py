"""Câu hỏi về kho tài liệu và câu chào khi kho đã có tài liệu: trả thẳng từ store, không qua Phân tích."""
import pytest

from app.chat.intent import classify_intent, library_reply
from tests.test_display_wl import chat_http  # noqa: F401

TEXT = {"source_name": "quy_dinh.md", "text": "# Bảo mật\n\nMật khẩu hết hạn sau 90 ngày.\n\n# Sao lưu\n\nSao lưu hằng đêm."}


@pytest.mark.parametrize("q", ["Đang có những tài liệu nào?", "Có tài liệu gì rồi?", "đang có tài liệu nào vậy", "What files do I have?"])
def test_library_questions_route_to_overview(q):
    assert classify_intent(q).intent == "corpus_overview", q


def test_content_question_is_not_overview():
    assert classify_intent("Tài liệu bảo mật nói mật khẩu hết hạn sau bao lâu?").intent != "corpus_overview"


def test_library_question_lists_names_and_chunks_without_model(chat_http):  # noqa: F811
    chat_http.post("/api/sources/text", json=TEXT)
    for q in ("Đang có những tài liệu nào?", "Có tài liệu gì rồi?"):
        body = chat_http.post("/api/chat", json={"message": q, "product_mode": True}).json()
        assert body["run_id"] is None and body["events"][0]["path"] == "OVERVIEW"
        assert "quy_dinh.md" in body["answer"] and " đoạn)" in body["answer"]
        assert not any(e["stage"] in {"request_understanding", "planning_retrieval"} for e in body["events"])


def test_greeting_with_documents_does_not_ask_to_upload(chat_http):  # noqa: F811
    empty = chat_http.post("/api/chat", json={"message": "Xin chào", "product_mode": True}).json()
    assert "tải tài liệu" in empty["answer"]
    chat_http.post("/api/sources/text", json=TEXT)
    body = chat_http.post("/api/chat", json={"message": "Xin chào", "product_mode": True}).json()
    assert body["run_id"] is None and "tải tài liệu" not in body["answer"] and "tải lên" not in body["answer"]
    assert "1 tài liệu" in body["answer"] and "quy_dinh.md" in body["answer"]


def test_library_reply_unit():
    assert library_reply("greeting", "vi", []) is None
    assert library_reply("out_of_scope", "vi", ["a"]) is None
    assert "2 tài liệu" in library_reply("greeting", "vi", ["a", "b"])
    assert "2 document(s)" in library_reply("greeting", "en", ["a", "b"])
