"""Đợt 4 kế hoạch Văn phòng 3D (23/11): bộ tác tử "office" khớp nhân vật 3D, mặc định ô chat từ Đợt 9, PRODUCT_AGENT_PACK=work để quay về bộ cũ."""
import asyncio

import pytest

from app.research.agent_selection import OFFICE_DESCRIPTIONS, PACK_CLARIFY, forced_selection, select_agents
from app.research.pipeline import ResearchPipeline
from app.research.progress import progress_sink
from app.research.registry import (OFFICE_PACK, PACKS, WORK_PACK, active_domains, product_agent_pack, profile, use_pack,
                                   use_work_context)
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore

OFFICE_3D_IDS = {"software", "business", "marketing", "hr", "finance", "education", "analyst"}  # frontend office3d/types.ts


def test_office_pack_matches_3d_characters_and_work_pack_untouched():
    assert set(PACKS[OFFICE_PACK]["agents"]) == OFFICE_3D_IDS | {"general"}
    assert set(OFFICE_DESCRIPTIONS) == OFFICE_3D_IDS == set(PACK_CLARIFY[OFFICE_PACK])
    assert set(PACKS[WORK_PACK]["agents"]) == {"general", "conditions", "procedure", "terms", "figures"}


def test_product_pack_defaults_to_office(monkeypatch):
    monkeypatch.delenv("PRODUCT_AGENT_PACK", raising=False)
    assert product_agent_pack() == OFFICE_PACK
    monkeypatch.setenv("PRODUCT_AGENT_PACK", " Work ")
    assert product_agent_pack() == WORK_PACK
    monkeypatch.setenv("PRODUCT_AGENT_PACK", "software")  # chỉ bộ chọn theo ý nghĩa mới hợp lệ
    assert product_agent_pack() == OFFICE_PACK


@pytest.mark.parametrize("question, expected", [
    ("Nhân viên thử việc có được nghỉ phép năm không?", "hr"),
    ("Ngân sách quảng cáo cho chiến dịch thương hiệu quý IV là gì?", "marketing"),
    ("Sinh viên cần bao nhiêu tín chỉ để tốt nghiệp?", "education"),
    ("API đăng nhập của hệ thống lưu mật khẩu trong cơ sở dữ liệu thế nào?", "software"),
    ("Hóa đơn công tác phí phải nộp kế toán khi nào?", "finance"),
])
def test_keyword_selection_picks_the_field(question, expected):
    sel = select_agents(question, None, pack=OFFICE_PACK)
    assert expected in sel["agents"] and sel["agents"][-1] == "general" and sel["pack"] == OFFICE_PACK, sel


def test_everyday_question_goes_to_general_only():
    sel = select_agents("Cách nấu canh chua cá lóc ngon?", None, pack=OFFICE_PACK)
    assert sel["agents"] == ["general"] and sel["ambiguous"]


def test_tinh_nang_does_not_wake_the_data_analyst():
    sel = select_agents("Phần mềm có tính năng xuất báo cáo không?", None, pack=OFFICE_PACK)
    assert "analyst" not in sel["agents"] and "software" in sel["agents"]


def test_forced_selection_is_checked_per_pack():
    assert forced_selection("hr", OFFICE_PACK)["agents"] == ["hr", "general"]
    with pytest.raises(ValueError):
        forced_selection("conditions", OFFICE_PACK)


def test_office_domains_and_knowledge():
    with use_pack(OFFICE_PACK):
        with use_work_context(["contract"], ["hr", "general"]):
            assert active_domains() == ("general", "hr")
            assert "Article 398" in profile("hr")["scope"]  # ghi chú theo loại tài liệu nạp cho mọi chuyên gia
        with use_work_context([], None):
            assert "Domain knowledge" not in profile("finance")["scope"]


def test_pipeline_runs_office_pack_and_emits_start_events(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")  # hồ sơ có điều kiện C như máy chạy thật
    store = SourceStore(str(tmp_path / "src"))
    store.import_text("noi_quy.md", "Nhân viên chính thức được nghỉ phép năm 12 ngày. Nhân viên thử việc không được nghỉ phép năm.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    seen: list[dict] = []

    async def go():
        progress_sink.set(seen.append)  # luồng tiến trình gửi giao diện (ô chat stream)
        return await pipe.run("Nhân viên thử việc có được nghỉ phép năm không?", "C", product_mode=True, domain_pack=OFFICE_PACK)

    run = asyncio.run(go())
    stages = [e["stage"] for e in run["events"]]
    selection = next(e for e in run["events"] if e["stage"] == "agent_selection")
    assert run["effective_config"]["domain_pack"] == OFFICE_PACK
    assert "hr" in selection["agents"]
    if "task_completed" in stages:  # khi kế hoạch chạy tới bước thực hiện
        assert stages.index("task_started") < stages.index("task_completed")
        if run["effective_config"].get("request_route") != "SIMPLE_PROJECT_QUESTION":  # câu đơn giản: chuyên gia trả lời thẳng, không tổng hợp
            assert stages.index("task_completed") < stages.index("synthesis_started")
        started = next(e for e in run["events"] if e["stage"] == "task_started")
        assert started["domain"] in PACKS[OFFICE_PACK]["agents"]
        assert any(e.get("stage") == "task_started" and "domain" in e for e in seen)  # luồng gửi giao diện có tên tác tử
