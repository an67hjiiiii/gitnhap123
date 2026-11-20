"""Đợt 5: 5 tác tử theo loại việc, chọn theo ý nghĩa + từ khóa, ngành là kiến thức nạp theo loại tài liệu."""
from app.research.agent_selection import DESCRIPTIONS, select_agents
from app.research.registry import PACKS, WORK_PACK, active_domains, profile, use_pack, use_work_context


def fake_embed(text: str):
    """Vector theo họ từ: đủ để thử phần so ý nghĩa mà không cần Ollama."""
    t = text.lower()
    fam = [("điều kiện", "được hưởng", "đủ", "ngưỡng"), ("bước", "duyệt", "thủ tục", "hồ sơ"),
           ("hợp đồng", "phạt", "nghĩa vụ", "điều khoản"), ("bao nhiêu", "tính", "tỷ lệ", "tiền")]
    return tuple(float(sum(w in t for w in f)) + 0.01 for f in fam)


def test_work_pack_has_four_specialists_plus_general_and_software_untouched():
    assert set(PACKS[WORK_PACK]["agents"]) == {"general", "conditions", "procedure", "terms", "figures"}
    assert set(PACKS["software"]["agents"]) == {"security", "database", "api_architecture"}
    assert set(DESCRIPTIONS) == {"conditions", "procedure", "terms", "figures"}


def test_clear_questions_pick_the_right_agent():
    cases = {
        "Sinh viên điểm 3,4 có được học bổng không?": "conditions",
        "Thủ tục xin cấp giấy phép gồm những bước nào?": "procedure",
        "Hợp đồng có điều khoản phạt nào bất lợi cho bên mua?": "terms",
        "Làm 8 tháng thì được bao nhiêu ngày phép, tính thế nào?": "figures",
    }
    for q, want in cases.items():
        assert select_agents(q, fake_embed)["primary"] == want, q


def test_example_3_4_gets_both_terms_and_procedure_without_knowing_the_industry():
    q = "Hợp đồng mua máy chiếu có điều khoản phạt nào bất lợi, và việc mua có cần Hiệu trưởng phê duyệt theo quy chế chi tiêu không?"
    sel = select_agents(q, fake_embed)
    assert {"terms", "procedure"} <= set(sel["agents"]) and sel["agents"][-1] == "general" and len(sel["agents"]) <= 4


def test_unsure_goes_to_general_only():
    sel = select_agents("Xin chào", None)
    assert sel["ambiguous"] and sel["agents"] == ["general"] and sel["primary"] == "general"


def test_selected_agents_limit_planner_domains_and_knowledge_follows_doc_type():
    with use_pack(WORK_PACK):
        with use_work_context(["contract", "internal_rules"], ["terms", "general"]):
            assert active_domains() == ("general", "terms")
            assert "Article 398" in profile("terms")["scope"]
        with use_work_context([], None):
            assert "Domain knowledge" not in profile("terms")["scope"]
            assert len(active_domains()) == 5
    with use_pack("software"):  # bộ Phần mềm không bị ảnh hưởng bởi ngữ cảnh work
        with use_work_context(["contract"], ["terms"]):
            assert active_domains() == ("security", "database", "api_architecture")


def test_clarify_only_when_ambiguous_semantic_and_long_enough():
    from app.research.agent_selection import clarify_options, forced_selection

    tie = {"ambiguous": True, "method": "semantic+keyword", "scores": {"terms": 0.61, "procedure": 0.605, "conditions": 0.4, "figures": 0.3}}
    assert clarify_options("Việc mua máy chiếu này cần xem những gì trước khi trình?", tie) == ["terms", "procedure"]
    assert clarify_options("Xin chào bạn", tie) is None                       # câu quá ngắn: giao Tổng hợp
    assert clarify_options("Việc mua máy chiếu này cần xem những gì?", {**tie, "ambiguous": False}) is None
    assert clarify_options("Việc mua máy chiếu này cần xem những gì?", {**tie, "method": "keyword"}) is None
    assert clarify_options("CSDL gồm những bảng nào?", tie) is None           # câu tra cứu: trả lời thẳng
    assert clarify_options("Thời gian thử việc là gì theo quy định?", tie) is None
    assert clarify_options("Công ty có những loại nghỉ phép nào được hưởng lương?", tie) is None
    sel = forced_selection("procedure")
    assert sel["agents"] == ["procedure", "general"] and sel["method"] == "user_choice"


def test_route_endpoint_asks_back_with_two_options():
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.analysis import build_router

    flat = SimpleNamespace(embed=lambda text: (1.0, 1.0, 1.0, 1.0))  # mọi mô tả giống nhau → hòa điểm, mơ hồ
    pipe = SimpleNamespace(source_store=SimpleNamespace(list_sources=lambda: []), candidate_index=SimpleNamespace(embedder=flat))
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u"}, owner_pipeline=lambda user, *a: pipe, session_factory=lambda: None))
    r = TestClient(app).post("/api/studio/route", json={"message": "Việc mua máy chiếu này cần xem những gì trước khi trình lên?"}).json()
    assert r["route"] == "clarify" and len(r["options"]) == 2 and r["question"].startswith("Bạn muốn hỏi về")
    assert TestClient(app).post("/api/studio/route", json={"message": "Xin chào"}).json() == {"route": "pipeline"}
