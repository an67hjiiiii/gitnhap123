"""24/11: câu hỏi về chính kho tài liệu trả lời từ danh sách tài liệu thật, không tìm đoạn gần nghĩa, không hỏi lại lĩnh vực."""
import asyncio

import pytest

from app.research.pipeline import ResearchPipeline
from app.research.product_intents import is_library_question, library_answer
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


@pytest.mark.parametrize("q", ["cho tôi biết kho đang có những tài liệu gì", "Xin hỏi kho đang có những tài liệu gì",
                               "cho hỏi kho hiện tại đang có những câu trả lời gì", "Liệt kê các tài liệu đã tải lên",
                               "Hiện có bao nhiêu tài liệu trong kho?"])
def test_library_questions_detected(q):
    assert is_library_question(q)


@pytest.mark.parametrize("q", ["Tài liệu nào nói về nghỉ phép?", "Theo tài liệu, tạm ứng 7 triệu ai duyệt?",
                               "Hợp đồng có những điều khoản gì bất lợi?", "Thủ đô của Úc là gì?"])
def test_content_questions_not_detected(q):
    assert not is_library_question(q)


def test_answer_lists_real_documents():
    out = library_answer([{"source_name": "Noi_quy.docx", "chunk_count": 8, "doc_type": "internal_rules"}], {"internal_rules": "Nội quy"})
    assert "1 tài liệu" in out and "Noi_quy.docx" in out and "Nội quy, 8 đoạn" in out
    assert "chưa có tài liệu" in library_answer([], {})


def test_pipeline_answers_from_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    store = SourceStore(str(tmp_path / "src"))
    store.import_text("noi_quy.md", "Nhân viên chính thức được nghỉ phép năm 12 ngày.")
    store.import_text("hop_dong.md", "Giá trị hợp đồng 120 triệu đồng.")
    run = asyncio.run(ResearchPipeline(store, RunStore(str(tmp_path / "runs"))).run(
        "cho tôi biết kho đang có những tài liệu gì", "C", product_mode=True))
    assert run["status"] == "COMPLETE" and "2 tài liệu" in run["answer"]
    assert "noi_quy.md" in run["answer"] and "hop_dong.md" in run["answer"]
