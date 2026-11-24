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
