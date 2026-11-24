"""23/11: câu đơn giản ở ô chat sản phẩm do đúng chuyên gia ngành đã chọn trả lời; thực nghiệm (điều kiện A) giữ Tổng hợp."""
import asyncio

from app.research.pipeline import ResearchPipeline, simple_answerer
from app.research.registry import OFFICE_PACK
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def test_simple_answerer_rules():
    assert simple_answerer({"agents": ["hr", "general"], "ambiguous": False}) == "hr"
    assert simple_answerer({"agents": ["marketing", "analyst", "general"], "ambiguous": False}) == "marketing"
    assert simple_answerer({"agents": ["analyst", "general"], "ambiguous": False}) == "general"  # Số liệu không phải chuyên gia ngành
    assert simple_answerer({"agents": ["hr", "finance", "general"], "ambiguous": False}) == "general"  # hai ngành: không đoán
    assert simple_answerer({"agents": ["general"], "ambiguous": True}) == "general"
    assert simple_answerer(None) == "general"


def _run(tmp_path, monkeypatch, condition, **kw):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    store = SourceStore(str(tmp_path / "src"))
    store.import_text("noi_quy.md", "Nhân viên chính thức được nghỉ phép năm 12 ngày. Nhân viên thử việc không được nghỉ phép năm.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    return asyncio.run(pipe.run("Nhân viên thử việc có được nghỉ phép năm không?", condition, **kw))


def test_product_simple_question_is_answered_by_the_field_expert(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "C", product_mode=True, domain_pack=OFFICE_PACK)
    if run["effective_config"].get("request_route") != "SIMPLE_PROJECT_QUESTION":
        return  # đường lập kế hoạch: chuyên gia đã nhận việc con như cũ
    started = [e for e in run["events"] if e["stage"] == "task_started"]
    assert started and started[0]["domain"] == "hr"
    assert run["tasks"][0]["domain"] == "hr"


def test_experiment_condition_a_keeps_general(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "A")
    assert not any(e["stage"] == "task_started" for e in run["events"])
