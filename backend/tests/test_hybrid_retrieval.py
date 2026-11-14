import asyncio

from app.chat.answer_guard import needs_verification, verify_sentences
from app.core.types import RunMetrics, SourceChunk, Usage
from app.research.product_retrieval import product_retrieve, rewrite_query, split_ideas
from app.retrieval.hybrid import bm25_rank, rrf_merge, weakness


def chunk(cid, text, score=None):
    return SourceChunk(chunk_id=cid, source_id="s", source_name="doc.md", text=text, index=0, score=score)


CHUNKS = [
    chunk("c1", "Mỗi khoá API được gọi tối đa 100 yêu cầu mỗi phút."),
    chunk("c2", "Tệp PDF, DOCX hoặc PNG kích thước tối đa 20 MB, quét mã độc trước khi lưu."),
    chunk("c3", "Nhật ký kiểm toán giữ 365 ngày và chỉ đọc."),
    chunk("c4", "Bản sao lưu mã hoá AES-256, giữ 14 ngày."),
]


def test_bm25_ranks_relevant_first_and_drops_weak_partial_matches():
    ranked = bm25_rank("Dung lượng tệp tối đa 20 MB là bao nhiêu", CHUNKS, 4)
    assert ranked[0].chunk_id == "c2"
    assert all((c.score or 0) >= 0.4 * (ranked[0].score or 0) for c in ranked)


def test_rrf_merge_dedupes_and_prefers_items_found_by_several_lists():
    a = [chunk("x", "a"), chunk("y", "b")]
    b = [chunk("y", "b"), chunk("z", "c")]
    merged = rrf_merge([a, b], 3)
    assert [c.chunk_id for c in merged][0] == "y" and len({c.chunk_id for c in merged}) == 3
    assert merged[0].score == 1.0 and rrf_merge([], 3) == []


def test_weakness_rules():
    assert weakness("q", [], min_score=0.18) == ["NO_CANDIDATES"]
    assert weakness("Giới hạn bao nhiêu?", [chunk("a", "không có số", 0.3)], min_score=0.18) == ["FEW_STRONG", "MISSING_QUANTITY"]
    assert weakness("Giới hạn bao nhiêu?", [chunk("a", "tối đa 50", 0.9)], min_score=0.18) == []
    assert weakness("Quy định là gì?", [chunk("a", "x", 0.3), chunk("b", "y", 0.25)], min_score=0.18) == []


def test_split_ideas_and_dependency():
    ideas, dependent = split_ideas("Tệp cho phép định dạng nào, dung lượng tối đa bao nhiêu và có quét mã độc không?")
    assert len(ideas) >= 2 and not dependent
    assert split_ideas("Giới hạn là bao nhiêu?") == ([], False)
    _, dep = split_ideas("Lấy giới hạn của API; sau đó so sánh với kích thước tệp tối đa")
    assert dep


class Provider:
    def __init__(self, text):
        self.text, self.calls = text, 0

    async def generate(self, *, system, user):
        self.calls += 1
        return type("R", (), {"text": self.text, "usage": Usage()})()


class Cfg:
    task_top_k = 4
    retrieval_min_score = 0.18


class FakePipeline:
    candidate_index = None

    def _retrieve_candidates(self, q, chunks, *, top_k, min_score, source_ids, fallback_trace=None):
        from app.retrieval.text import retrieve
        return retrieve(q, chunks, top_k=top_k, min_score=min_score)


def test_multi_idea_merges_per_idea_results_into_one_context_and_retries_once_when_weak(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_RETRY", "1")
    events = []
    provider = Provider("api yêu cầu mỗi phút giới hạn")
    out = asyncio.run(product_retrieve(
        FakePipeline(), provider, RunMetrics(), query="Khoá API gọi tối đa bao nhiêu yêu cầu mỗi phút và nhật ký kiểm toán giữ bao lâu?",
        retrieval_query="Khoá API gọi tối đa bao nhiêu yêu cầu mỗi phút và nhật ký kiểm toán giữ bao lâu?",
        chunks=CHUNKS, cfg=Cfg(), source_ids=None, trace={}, event=lambda stage, **d: events.append((stage, d)),
        multi=True, retry=True))
    ids = {c.chunk_id for c in out}
    assert {"c1", "c3"} <= ids
    assert len(ids) == len(out)
    assert any(stage == "retrieval.multi" for stage, _ in events)
    assert provider.calls <= 1


def test_retry_happens_at_most_once_and_records_event(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_RETRY", "1")
    events = []
    provider = Provider("sao lưu mã hoá")
    out = asyncio.run(product_retrieve(
        FakePipeline(), provider, RunMetrics(), query="Dữ liệu dự phòng được bảo vệ thế nào?",
        retrieval_query="Dữ liệu dự phòng được bảo vệ thế nào?", chunks=CHUNKS, cfg=Cfg(), source_ids=None, trace={},
        event=lambda stage, **d: events.append((stage, d)), multi=False, retry=True))
    retries = [d for stage, d in events if stage == "retrieval.retry"]
    assert len(retries) == 1 and provider.calls == 1
    assert "c4" in {c.chunk_id for c in out}


def test_rewrite_query_falls_back_on_error():
    class Broken:
        async def generate(self, **_):
            raise RuntimeError("x")
    assert asyncio.run(rewrite_query(Broken(), "abc?", RunMetrics())) == "abc?"


def test_verifier_drops_flagged_sentences_but_keeps_one_and_survives_garbage():
    answer = "Giới hạn là 100 yêu cầu mỗi phút. Khoá hết hạn sau 45 ngày."
    metrics = RunMetrics()
    new, notes = asyncio.run(verify_sentences(Provider('{"unsupported":[2]}'), answer, ["100 yêu cầu"], metrics))
    assert new == "Giới hạn là 100 yêu cầu mỗi phút." and notes == ["VERIFY_DROPPED:1"]
    same, notes = asyncio.run(verify_sentences(Provider('{"unsupported":[1,2]}'), answer, ["x"], metrics))
    assert same == answer and notes == ["VERIFY_ALL_UNSUPPORTED_KEPT"]
    # the model flags a sentence that the sources do support: rules veto the drop
    kept, notes = asyncio.run(verify_sentences(Provider('{"unsupported":[1]}'), answer, ["Giới hạn là 100 yêu cầu mỗi phút, khoá hết hạn sau 45 ngày"], metrics))
    assert kept == answer and notes == ["VERIFY_FLAGGED_KEPT:1"]
    same, notes = asyncio.run(verify_sentences(Provider("không biết"), answer, ["x"], metrics))
    assert same == answer and notes == []


def test_needs_verification_only_for_risky_answers(monkeypatch):
    monkeypatch.setenv("ANSWER_LLM_VERIFY", "1")
    assert needs_verification("Mật khẩu thế nào?", "Mật khẩu dài 12 ký tự.")
    assert not needs_verification("Mật khẩu thế nào?", "Mật khẩu phải đủ mạnh.")
    assert needs_verification("Tệp nào được phép, dung lượng bao nhiêu và có quét không?", "Chỉ PDF.")


def test_progress_labels_for_new_orchestration_events():
    from app.chat.progress import stage_label

    multi = stage_label({"stage": "retrieval.multi", "ideas": ["a", "b"]})
    assert multi["step"] == "multi_search" and "2 ý" in multi["text"]
    assert stage_label({"stage": "retrieval.retry"})["step"] == "retrying"
    assert stage_label({"stage": "answer_guard", "notes": ["TRAILING_NEGATIVE_DROPPED:1"]}) is None
    assert stage_label({"stage": "answer_guard", "notes": ["VERIFY_RAN"]})["step"] == "verifying"


def test_temporary_defaults_are_off(monkeypatch):
    from app.research.product_retrieval import fusion_mode

    for name in ("RETRIEVAL_FUSION", "RETRIEVAL_RETRY", "ANSWER_LLM_VERIFY"):
        monkeypatch.delenv(name, raising=False)
    assert fusion_mode() == "off"
    assert not needs_verification("Mật khẩu bao nhiêu ký tự và hết hạn sau bao lâu?", "Mật khẩu dài 12 ký tự.")
    events = []
    asyncio.run(product_retrieve(
        FakePipeline(), Provider("x"), RunMetrics(), query="Dữ liệu dự phòng được bảo vệ thế nào?",
        retrieval_query="Dữ liệu dự phòng được bảo vệ thế nào?", chunks=CHUNKS, cfg=Cfg(), source_ids=None, trace={},
        event=lambda stage, **d: events.append(stage), multi=False, retry=True))
    assert "retrieval.retry" not in events


def test_split_keeps_proper_names_and_lists_together():
    assert split_ideas("Phòng Research and Development nằm ở đâu?") == ([], False)
    assert split_ideas("Hệ thống chấp nhận PDF, DOCX và PNG đúng không?") == ([], False)
    ideas, _ = split_ideas("Mật khẩu phải có bao nhiêu ký tự và hết hạn sau bao lâu?")
    assert len(ideas) == 2
