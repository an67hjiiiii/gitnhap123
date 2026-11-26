"""Luồng stream ô chat gửi đủ cờ trạng thái để văn phòng 3D Trực tiếp diễn giống Xem lại (23/11)."""
import asyncio

from app.research.pipeline import ResearchPipeline
from app.research.progress import progress_sink
from app.research.registry import OFFICE_PACK
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore

FLAGS = ("has_documents", "document_bound", "source", "review_status", "waves", "limit", "tool", "added", "before", "after", "revision")


def _run(tmp_path, monkeypatch, query, docs=()):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    store = SourceStore(str(tmp_path / "src"))
    for name, text in docs:
        store.import_text(name, text)
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    items = []
    token = progress_sink.set(items.append)
    try:
        run = asyncio.run(pipe.run(query, "C", product_mode=True, domain_pack=OFFICE_PACK, source_ids=None if docs else []))
    finally:
        progress_sink.reset(token)
    return run, [i for i in items if i.get("type") == "progress"]


def _check_matches_saved_events(run, streamed):
    saved = [e for e in run["events"]]
    assert [s["stage"] for s in streamed] == [e["stage"] for e in saved]
    for s, e in zip(streamed, saved):
        for k in FLAGS:
            assert s.get(k) == e.get(k), (e["stage"], k)
        if isinstance(e.get("selected"), list):
            assert s["selected_count"] == len(e["selected"]) and "selected" not in s  # chỉ số lượng, không gửi mã đoạn
        if isinstance(e.get("tasks"), list):
            assert s["task_count"] == len(e["tasks"]) and "tasks" not in s
        # 25/11: số lượng cho cơ chế điều phối, không gửi mã đoạn / nội dung
        if isinstance(e.get("candidates"), list):
            assert s["candidate_count"] == len(e["candidates"]) and "candidates" not in s
        if isinstance(e.get("dropped"), list):
            assert s["dropped_count"] == len(e["dropped"]) and "dropped" not in s
        for k in ("removed", "checked"):
            if isinstance(e.get(k), int):
                assert s[k] == e[k]
        if isinstance(e.get("limits"), dict):
            assert s["budget_tasks"] == len(e["limits"]) and "limits" not in s and "needs" not in s
        if isinstance(e.get("unsupported"), list):
            assert s["unsupported"] == len(e["unsupported"])  # chỉ số lượng, không gửi câu trích
        if isinstance(e.get("result"), dict):
            assert s["result"].get("status") == e["result"].get("status")
            assert "answer" not in s["result"] and "citations" not in s["result"]


def test_stream_carries_source_flags_without_documents(tmp_path, monkeypatch):
    run, streamed = _run(tmp_path, monkeypatch, "Thủ đô của Úc là thành phố nào?")
    _check_matches_saved_events(run, streamed)
    policy = next(s for s in streamed if s["stage"] == "knowledge_source_policy")
    assert policy["has_documents"] is False and policy["document_bound"] is False
    assert any(s["stage"] == "knowledge_source" and s["source"] == "general" for s in streamed)


def test_stream_never_carries_answer_or_document_text(tmp_path, monkeypatch):
    secret = "Mã nội bộ XK-7781 chỉ có trong tài liệu"
    run, streamed = _run(tmp_path, monkeypatch, "Theo nội quy, mã nội bộ là gì?", docs=[("noi_quy.md", secret)])
    _check_matches_saved_events(run, streamed)
    blob = repr(streamed)
    assert "XK-7781" not in blob
    if run["answer"]:
        assert run["answer"][:40] not in blob


def test_task_completed_streams_result_status(tmp_path, monkeypatch):
    run, streamed = _run(tmp_path, monkeypatch, "Xin chào")
    _check_matches_saved_events(run, streamed)
    done = [s for s in streamed if s["stage"] == "task_completed"]
    assert done and done[0]["result"] == {"task_id": "T1", "domain": "general", "status": "COMPLETE"}


def test_simple_vanilla_retrieval_streams_target_domain(tmp_path, monkeypatch):
    run, streamed = _run(
        tmp_path,
        monkeypatch,
        "Nhân viên nghỉ phép năm bao nhiêu ngày?",
        docs=[("chinh_sach_nhan_su.docx", "Nhân viên chính thức được 12 ngày nghỉ phép năm.")],
    )
    _check_matches_saved_events(run, streamed)
    vr = [s for s in streamed if s["stage"] == "vanilla_retrieval"]
    assert vr and vr[0].get("domain") in ("hr", "general")
    fin = [s for s in streamed if s["stage"] == "run_finished"]
    assert fin and fin[0].get("status") in ("COMPLETE", "PARTIAL", "NO_EVIDENCE")
