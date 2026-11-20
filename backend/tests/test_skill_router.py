"""Đợt 4 (bản làm thử): ô chat Tự động chọn kỹ năng bằng luật cố định; không chắc thì để pipeline xử lý."""
from app.analysis.skill_router import route_skill

ALL = ["contract", "regulation", "internal_rules", "legal_doc"]


def skill(q, types=ALL):
    r = route_skill(q, types)
    return r and r["skill"]


def test_single_intent_goes_to_one_skill():
    assert skill("Sinh viên điểm 3,4, rèn luyện 65 có được học bổng khuyến khích không?") == "conditions"
    assert skill("Thủ tục cấp giấy phép biển quảng cáo cần những gì?") == "procedure"
    assert skill("Xin nghỉ phép 6 ngày thì ai duyệt?") == "approver"
    assert skill("Rà soát hợp đồng mua máy chiếu giúp tôi") == "contract_review"
    assert skill("Quyết định 12/2020 còn hiệu lực không?") == "validity"


def test_works_without_diacritics():
    assert skill("thu tuc xet tot nghiep gom cac buoc nao") == "procedure"


def test_skill_needing_a_document_type_is_skipped_without_it():
    # không có hợp đồng trong phạm vi hỏi → không gọi kỹ năng rà soát hợp đồng
    assert skill("Rà soát hợp đồng này", ["internal_rules"]) is None


def test_multi_part_request_goes_to_multi_agent_pipeline():
    # ví dụ mục 3.4: hai mảng (điều khoản phạt + cấp duyệt) → không chọn một kỹ năng
    q = "Hợp đồng mua máy chiếu có điều khoản phạt nào bất lợi, và việc mua có cần Hiệu trưởng duyệt, ai duyệt theo quy chế chi tiêu?"
    assert skill(q) is None


def test_plain_questions_stay_with_pipeline():
    assert skill("Thời gian thử việc tối đa bao lâu?") is None
    assert skill("Tóm tắt nội quy lao động") is None


def test_reason_is_returned_for_display():
    r = route_skill("Ai duyệt đơn nghỉ phép 3 ngày?", ALL)
    assert r["label"] == "Ai duyệt" and "Ai duyệt" in r["reason"]


def test_route_endpoint_filters_sources_by_needed_type():
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.analysis import build_router

    rows = [{"source_id": "s1", "doc_type": "contract"}, {"source_id": "s2", "doc_type": "internal_rules"},
            {"source_id": "s3", "doc_type": "contract"}]
    store = SimpleNamespace(list_sources=lambda: rows)
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u"},
                                    owner_pipeline=lambda user, *a: SimpleNamespace(source_store=store),
                                    session_factory=lambda: None))
    c = TestClient(app)
    r = c.post("/api/studio/route", json={"message": "Rà soát hợp đồng này", "source_ids": ["s1", "s2"]}).json()
    assert r["route"] == "skill" and r["skill"] == "contract_review" and r["source_ids"] == ["s1"]  # s3 ngoài phạm vi hỏi
    r = c.post("/api/studio/route", json={"message": "Ai duyệt đơn nghỉ 6 ngày?", "source_ids": ["s1", "s2"]}).json()
    assert r["skill"] == "approver" and r["source_ids"] == ["s1", "s2"]
    assert c.post("/api/studio/route", json={"message": "Tóm tắt nội quy"}).json() == {"route": "pipeline"}
    forced = c.post("/api/studio/route", json={"message": "xem giúp", "source_ids": ["s1", "s2"], "skill": "contract_review"}).json()
    assert forced["skill"] == "contract_review" and forced["source_ids"] == ["s1"]
    assert c.post("/api/studio/route", json={"message": "x", "skill": "bogus"}).status_code == 400


def test_compose_requests_are_not_forced_into_lookup_skills():
    # "quy trình", "hợp đồng" chỉ là chủ đề của yêu cầu soạn nội dung: để pipeline trả lời
    assert route_skill("Tạo 5 câu hỏi trắc nghiệm ôn tập về quy trình xử lý sự cố", []) is None
    assert route_skill("Soạn email nhắc các bước thủ tục nghỉ phép", []) is None
    assert route_skill("Tóm tắt hợp đồng và rà soát hợp đồng", ["contract"]) is None
    assert route_skill("Quy trình xử lý sự cố gồm các bước nào?", [])["skill"] == "procedure"


def test_compare_versions_intent():
    for q in ("So sánh quy chế 2024 với bản 2026", "Bản mới khác gì so với bản cũ?", "Đối chiếu hai phiên bản quy định nghỉ phép"):
        assert route_skill(q, [])["skill"] == "compare", q
    assert route_skill("Quy chế có hiệu lực từ ngày nào?", ["regulation"])["skill"] == "validity"
