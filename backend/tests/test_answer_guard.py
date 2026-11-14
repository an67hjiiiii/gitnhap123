import asyncio

from app.chat.answer_guard import guard_answer
from app.chat.language import document_language, text_language, translate_query

EVIDENCE = ["Mỗi khoá API được gọi tối đa 100 yêu cầu mỗi phút. Khi vượt giới hạn, API trả mã 429."]


def test_trailing_negative_filler_is_dropped_when_answer_is_complete():
    answer = ("API giới hạn 100 yêu cầu mỗi phút, theo tài liệu orion_api.md. "
              "Không có thông tin khác về giới hạn yêu cầu theo phút trong các tài liệu khác.")
    result = guard_answer(answer, status="COMPLETE", evidence_texts=EVIDENCE)
    assert result.answer == "API giới hạn 100 yêu cầu mỗi phút, theo tài liệu orion_api.md."
    assert result.notes == ["TRAILING_NEGATIVE_DROPPED:1"]


def test_negative_sentence_is_kept_for_partial_answers_and_when_it_is_the_only_content():
    partial = "Có nêu 100 yêu cầu mỗi phút. Không có thông tin về hạn mức theo ngày."
    assert guard_answer(partial, status="PARTIAL", evidence_texts=EVIDENCE).answer == partial
    only = "Không có thông tin về chủ đề này."
    assert guard_answer(only, status="COMPLETE", evidence_texts=EVIDENCE).answer == only


def test_sentence_with_unsupported_number_is_dropped_and_event_note_recorded():
    answer = "Giới hạn là 100 yêu cầu mỗi phút. Khoá hết hạn sau 45 ngày."
    result = guard_answer(answer, status="COMPLETE", evidence_texts=EVIDENCE)
    assert result.answer == "Giới hạn là 100 yêu cầu mỗi phút."
    assert result.notes[0].startswith("UNSUPPORTED_NUMBER_DROPPED:") and "45" in result.notes[0]


def test_answer_with_only_unsupported_numbers_becomes_grounded_excerpt():
    result = guard_answer("Giới hạn là 500 yêu cầu mỗi phút.", status="COMPLETE", evidence_texts=EVIDENCE,
                          source_label="orion_api.md")
    assert result.answer.startswith("Mình chưa kiểm chứng được số liệu")
    assert "orion_api.md" in result.answer and "100 yêu cầu" in result.answer
    assert "ANSWER_REPLACED_BY_EXCERPT" in result.notes


def test_supported_numbers_with_equivalent_units_are_kept():
    answer = "Phiên hết hạn sau 0,5 giờ."
    result = guard_answer(answer, status="COMPLETE", evidence_texts=["Phiên hết hạn sau 30 phút."])
    assert result.answer == answer and result.notes == []


def test_text_and_document_language():
    assert text_language("What is the maximum size of an uploaded file?") == "en"
    assert text_language("Kích thước tệp tối đa là bao nhiêu?") == "vi"
    assert document_language(["Mật khẩu phải có ít nhất 12 ký tự.", "Phiên hết hạn sau 30 phút."]) == "vi"
    assert document_language(["The key rotates every 12 days.", "Backups are kept 14 days."]) == "en"
    assert document_language([]) is None


class FakeProvider:
    def __init__(self, text="", error=None):
        self.text, self.error, self.calls = text, error, 0

    async def generate(self, *, system, user):
        self.calls += 1
        if self.error:
            raise self.error
        return type("R", (), {"text": self.text})()


def test_translate_query_one_call_and_safe_fallbacks():
    provider = FakeProvider("  Kích thước tối đa của tệp tải lên là bao nhiêu?\n")
    out = asyncio.run(translate_query(provider, "What is the maximum size of an uploaded file?", "vi"))
    assert out == "Kích thước tối đa của tệp tải lên là bao nhiêu?" and provider.calls == 1
    assert asyncio.run(translate_query(FakeProvider(error=RuntimeError("x")), "hello?", "vi")) == "hello?"
    assert asyncio.run(translate_query(FakeProvider(""), "hello?", "vi")) == "hello?"
    assert asyncio.run(translate_query(FakeProvider("x"), "hello?", "fr")) == "hello?"
