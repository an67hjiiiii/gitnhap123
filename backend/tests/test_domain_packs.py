"""Bộ lĩnh vực: Phần mềm giữ nguyên prompt CAP1; ngành khác không giao nhầm cho tác tử phần mềm."""
import asyncio

import pytest

from app.research.decomposer import build_task_plan_prompt, detect_domains, task_plan_response_schema
from app.research.obligation_concern_extraction import build_extraction_prompt, extraction_response_schema
from app.research.planning_retrieval import PlanningRetriever
from app.research.registry import PACKS, active_pack_name, profile, use_pack
from app.research.pipeline import ResearchPipeline
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore
from tests.test_org_api import env  # noqa: F401  (fixture CSDL tổ chức dùng chung)

OLD_LINE = "- Use only security, database, or api_architecture task domains.\n"


def test_software_is_default_and_prompts_unchanged():
    assert active_pack_name() == "software"
    prompt = build_task_plan_prompt("Review JWT login and SQL schema")
    assert OLD_LINE in prompt and "Domain scopes" not in prompt and "same language" not in prompt
    extraction = build_extraction_prompt("Review JWT login")
    assert '"domain":"security|database|api_architecture"' in extraction and "same language" not in extraction
    assert task_plan_response_schema()["properties"]["tasks"]["items"]["properties"]["domain"]["enum"] == [
        "security", "database", "api_architecture"]
    assert detect_domains("Hiệu trưởng ký quyết định") == ["security"]  # hành vi cũ giữ nguyên ở bộ Phần mềm


@pytest.mark.parametrize("text, expected", [
    ("Hiệu trưởng ký quyết định công nhận tốt nghiệp", ["academic_affairs"]),
    ("Sinh viên bị cảnh báo học tập khi nào?", ["academic_affairs"]),
    ("Điều kiện xét học bổng là gì?", ["student_affairs"]),
    ("Giảng viên phải đủ bao nhiêu giờ chuẩn?", ["faculty_research"]),
])
def test_education_routes_without_software_agents(text, expected):
    with use_pack("education"):
        assert detect_domains(text) == expected


def test_everyday_words_no_longer_hit_software_domains():
    with use_pack("business_hr"):
        assert detect_domains("Kế toán ghi nhận giao dịch thu chi") == []
        assert detect_domains("Thủ tục nghỉ phép năm") == ["hr_policy"]
    with use_pack("legal_admin"):
        assert detect_domains("Hồ sơ xin giấy phép nộp ở đâu?") == ["procedure"]


def test_non_software_prompts_have_general_agent_and_language_rule():
    with use_pack("education"):
        prompt = build_task_plan_prompt("Phân tích quy trình xét học bổng")
        assert "general, academic_affairs, student_affairs, or faculty_research task domains" in prompt
        assert "same language as the CURRENT REQUEST" in prompt and "Domain scopes:" in prompt
        assert "same language" in build_extraction_prompt("Phân tích quy trình xét học bổng")
        assert "general" in extraction_response_schema()["properties"]["concerns"]["items"]["properties"]["domain"]["enum"]
        assert profile("general")["name"] == "General Analyst"
    assert active_pack_name() == "software"  # trả lại sau khối with


def test_every_pack_is_consistent():
    for name, pack in PACKS.items():
        assert set(pack["hints"]) == set(pack["agents"]), name
        assert pack["default_domain"] in pack["agents"], name
        assert set(pack["anchors"]) == {p for p, _ in pack["patterns"]}, name
    with pytest.raises(ValueError):
        with use_pack("nope"):
            pass


def test_planning_patterns_follow_pack():
    retriever = PlanningRetriever()
    assert retriever.search("Review JWT authentication") and all(
        c.source_name.startswith("planning_") for c in retriever.search("Review JWT authentication"))
    with use_pack("education"):
        hits = retriever.search("Quy trình xét học bổng và học phí")
        assert hits and hits[0].source_name == "planning_student_affairs.md"
        assert "học bổng" not in hits[0].text  # từ khóa chỉ để chấm điểm, không lọt vào prompt


def test_task_query_adds_request_on_language_mismatch():
    from app.core.types import Task
    from app.research.pipeline import _task_query
    task = Task(task_id="T1", goal="Identify academic warning criteria", domain="academic_affairs", evidence_needs=["academic warning"])
    vi = "Sinh viên bị cảnh báo học tập khi nào?"
    assert _task_query(task, vi) == "Identify academic warning criteria academic warning"  # bộ Phần mềm: như cũ
    with use_pack("education"):
        assert _task_query(task, vi).endswith(vi)
        same = Task(task_id="T2", goal="Điều kiện cảnh báo học tập", domain="academic_affairs", evidence_needs=[])
        assert _task_query(same, vi) == "Điều kiện cảnh báo học tập"


def test_org_space_domain_pack(env):
    _, u = env
    school = u["an"].post("/api/org/spaces", json={"name": "Trường A", "preset": "school"}).json()
    assert school["space_id"]
    assert u["an"].get(f"/api/org/spaces/{school['space_id']}").json()["domain_pack"] == "education"  # gợi ý theo mẫu
    sp = u["an"].post("/api/org/spaces", json={"name": "Nhóm B", "preset": "team", "domain_pack": "software"}).json()["space_id"]
    assert u["an"].get(f"/api/org/spaces/{sp}").json()["domain_pack"] == "software"
    assert u["an"].patch(f"/api/org/spaces/{sp}", json={"domain_pack": "legal_admin"}).json()["domain_pack"] == "legal_admin"
    assert u["an"].patch(f"/api/org/spaces/{sp}", json={"domain_pack": "y_te"}).status_code == 422


def test_pipeline_records_domain_pack(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    store = SourceStore(str(tmp_path / "src"))
    store.import_text("quy_che.md", "Sinh viên bị cảnh báo học tập khi điểm trung bình học kỳ dưới 1,0.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    run = asyncio.run(pipe.run("Khi nào bị cảnh báo học tập?", "A", domain_pack="education"))
    assert run["effective_config"]["domain_pack"] == "education"
    assert asyncio.run(pipe.run("Khi nào bị cảnh báo học tập?", "A"))["effective_config"]["domain_pack"] == "software"
    assert active_pack_name() == "software"
