"""Bước điều phối "chọn nguồn tri thức" (23/11): tài liệu / kiến thức chung / cả hai, chỉ ô chat sản phẩm."""
import asyncio

from app.core.types import RunMetrics, Usage
from app.research.knowledge_source import BOTH, DOCUMENTS, GENERAL, answer_general, choose_source, doc_bound
from app.research.pipeline import ResearchPipeline
from app.research.registry import OFFICE_PACK
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def test_document_bound_questions():
    assert doc_bound("Theo nội quy, tạm ứng 7 triệu thì ai duyệt?")
    assert doc_bound("Trong hợp đồng, bên B phải bồi thường không?")
    assert doc_bound("Nồi chiên có nấu cơm được không?", ["Huong_dan_noi_chien.md"])  # nêu tên tài liệu
    assert not doc_bound("Thủ đô của Úc là thành phố nào?")
    assert not doc_bound("Lập kế hoạch ôn thi 2 tuần cho môn Toán cao cấp.")


def test_choose_source():
    assert choose_source("Thủ đô của Úc?", 0, bound=False) == GENERAL
    assert choose_source("Theo nội quy ai duyệt?", 0, bound=True) == DOCUMENTS  # tài liệu không có thì vẫn nói không có
    assert choose_source("Khoai chiên bao nhiêu độ?", 3, bound=False) == DOCUMENTS
    assert choose_source("Khoai chiên bao nhiêu độ, vì sao ngâm nước muối?", 3, bound=False) == BOTH


class _Fake:
    def __init__(self, text):
        self.text = text

    async def generate(self, system, user):
        class R:
            pass
        r = R()
        r.text, r.usage = self.text, Usage()
        self.user = user
        return r


def test_general_answer_is_labelled_and_has_no_citations():
    res = asyncio.run(answer_general(_Fake('{"answer": "Canberra là thủ đô của Úc."}'), "Thủ đô của Úc?", RunMetrics()))
    assert res.status == "COMPLETE" and res.source == GENERAL and res.citations == []
    assert res.answer.startswith("**Kiến thức chung**") and "Canberra" in res.answer
    had_docs = asyncio.run(answer_general(_Fake('{"answer": "x"}'), "q", RunMetrics(), had_documents=True))
    assert had_docs.answer.startswith("Tài liệu bạn gửi không có thông tin này")  # vẫn nói rõ tài liệu không có
    en = asyncio.run(answer_general(_Fake('{"answer": "Canberra."}'), "Capital of Australia?", RunMetrics(), reply_language="en"))
    assert en.answer.startswith("**General knowledge**")
    calc = asyncio.run(answer_general(_Fake('{"answer": "Nhận [[= 100*1.06*1.06 ]] triệu."}'), "q", RunMetrics()))
    assert "112,36" in calc.answer or "112.36" in calc.answer


def _pipe(tmp_path, monkeypatch, docs=()):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    store = SourceStore(str(tmp_path / "src"))
    for name, text in docs:
        store.import_text(name, text)
    return ResearchPipeline(store, RunStore(str(tmp_path / "runs")))


def test_no_documents_product_chat_answers_from_general_knowledge(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch)
    run = asyncio.run(pipe.run("Thủ đô của Úc là thành phố nào?", "C", product_mode=True, domain_pack=OFFICE_PACK, source_ids=[]))
    sources = [e for e in run["events"] if e["stage"] == "knowledge_source"]
    assert sources and all(e["source"] == GENERAL for e in sources)
    assert run["status"] != "NO_EVIDENCE" and "iến thức chung" in run["answer"]


def test_document_bound_question_without_documents_still_refuses(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch)
    run = asyncio.run(pipe.run("Theo nội quy, nhân viên thử việc có được nghỉ phép năm không?", "C", product_mode=True,
                               domain_pack=OFFICE_PACK, source_ids=[]))
    assert run["status"] == "NO_EVIDENCE" and "iến thức chung" not in run["answer"]


def test_experiments_stay_document_only(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch)
    run = asyncio.run(pipe.run("Thủ đô của Úc là thành phố nào?", "A", source_ids=[]))
    assert run["status"] == "NO_EVIDENCE"
    assert not any(e["stage"].startswith("knowledge_source") for e in run["events"])


def test_task_miss_retries_documents_before_general_knowledge():
    """K29 (23/11): tác tử có đoạn tài liệu mà báo không có thì hỏi lại trên chính các đoạn đó trước khi dùng kiến thức chung."""
    import inspect
    src = inspect.getsource(ResearchPipeline._run)
    assert src.index('"knowledge_source_retry"') < src.index("result = await general(True)")
