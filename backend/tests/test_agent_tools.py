"""23/11: công cụ tìm kiếm của tác tử và Reviewer trả bài (chỉ ô chat sản phẩm)."""
import inspect

from app.research.agent_tools import agent_tools_enabled, status_rank, tool_query
from app.research.pipeline import ResearchPipeline
from app.research.reviewer import reviewer_revise_enabled, revision_note


def test_tool_query_keeps_user_needs_drops_internal_notes():
    q = tool_query("Ngân sách quý I", ["invalid citation locator(s) removed", "phân bổ theo kênh", "relevant evidence"])
    assert q == "Ngân sách quý I phân bổ theo kênh"


def test_status_rank_and_switches(monkeypatch):
    assert status_rank("COMPLETE") > status_rank("PARTIAL") > status_rank("NO_EVIDENCE")
    monkeypatch.delenv("PRODUCT_AGENT_TOOLS", raising=False)
    monkeypatch.delenv("PRODUCT_REVIEWER_REVISE", raising=False)
    assert not agent_tools_enabled() and reviewer_revise_enabled()  # công cụ tắt mặc định (đo 23/11 làm sai thêm)
    monkeypatch.setenv("PRODUCT_AGENT_TOOLS", "on")
    assert agent_tools_enabled()


def test_revision_note_lists_flagged_claims():
    note = revision_note(["CTR là 5%", "ngân sách 200 triệu"])
    assert "CTR là 5%" in note and "Do not add new facts" in note


def test_tool_runs_before_general_fallback_and_only_in_product_mode():
    src = inspect.getsource(ResearchPipeline._run)
    assert src.index('event("agent_tool"') < src.index('"knowledge_source_retry"') < src.index("result = await general(True)")
    assert "search=search_more if product_mode else None" in src
    assert 'all(r.source == "documents" for r in task_results)' in src  # không soát phần kiến thức chung


def test_product_retrieval_runs_off_the_event_loop(monkeypatch):
    """23/11: truy xuất đồng bộ giữ vòng lặp sự kiện làm luồng stream tới trình duyệt muộn tới 5 s; sản phẩm chạy ở luồng phụ."""
    import asyncio
    import threading

    seen = []
    monkeypatch.setattr(ResearchPipeline, "_retrieve_candidates", lambda self, *a, **k: seen.append(threading.current_thread()) or [])
    pipe = ResearchPipeline.__new__(ResearchPipeline)
    asyncio.run(pipe._retrieve_async(True, "q"))
    asyncio.run(pipe._retrieve_async(False, "q"))
    assert seen[0] is not threading.main_thread() and seen[1] is threading.main_thread()
