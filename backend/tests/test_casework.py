"""Công cụ theo ngành: luật cố định lọc mục thiếu căn cứ và suy ra kết luận tổng, không tin lời tự đánh giá của mô hình."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis.casework import check_conditions, extract_procedure, overall_verdict
from app.analysis.traceability import criteria_from_lines, extract_checklist
from app.api.analysis import build_router
from app.core.types import SourceChunk, Usage
from app.research.registry import use_pack

RULE = SourceChunk("q1", "quy_che", "quy_che.md",
                   "Xét học bổng cho sinh viên có điểm trung bình học kỳ từ 3,2 trở lên, điểm rèn luyện từ 70 trở lên. "
                   "Khoa lập danh sách trong 10 ngày làm việc; Phòng Công tác sinh viên thẩm định; Hội đồng phê duyệt.", 0)
CASE = "Điểm trung bình học kỳ 3,4; điểm rèn luyện 65."


class Provider:
    def __init__(self, payload):
        self.payload, self.system = payload, ""

    async def generate_structured(self, *, system, user, response_schema):
        self.system = system
        return SimpleNamespace(text=json.dumps(self.payload, ensure_ascii=False), usage=Usage(200, 50))


def _cond(**kw):
    return {"condition": "", "citation": "q1", "case_fact": "", "verdict": "MET", "reason": "", **kw}


def test_overall_verdict_rules():
    assert overall_verdict([]) == "NO_RULE"
    assert overall_verdict([{"verdict": "MET"}, {"verdict": "UNKNOWN"}]) == "INSUFFICIENT_INFO"
    assert overall_verdict([{"verdict": "MET"}, {"verdict": "NOT_MET"}, {"verdict": "UNKNOWN"}]) == "NOT_ELIGIBLE"
    assert overall_verdict([{"verdict": "MET"}, {"verdict": "MET"}]) == "ELIGIBLE"


def test_conditions_are_grounded_and_overall_is_derived():
    payload = {"note": "", "conditions": [
        _cond(condition="Điểm trung bình học kỳ từ 3,2", case_fact="điểm trung bình 3,4", verdict="MET"),
        _cond(condition="Điểm rèn luyện từ 70", case_fact="điểm rèn luyện 65", verdict="NOT_MET"),
        _cond(condition="Không có học phần dưới D", citation="khong_co", verdict="MET"),          # không có căn cứ: bỏ
        _cond(condition="Có chứng chỉ IELTS 6.5", case_fact="", verdict="MET"),                   # số không có trong quy định
        _cond(condition="Điểm rèn luyện từ 70", case_fact="điểm rèn luyện 80", verdict="MET"),     # số không có trong tình huống
    ]}
    with use_pack("education"):
        out = asyncio.run(check_conditions(Provider(payload), "Có đủ điều kiện học bổng không?", CASE, [RULE]))
    verdicts = [(c["verdict"], c["flags"]) for c in out["conditions"]]
    assert out["removed"] == 1 and len(verdicts) == 4
    assert verdicts[0] == ("MET", []) and verdicts[1] == ("NOT_MET", [])
    assert verdicts[2] == ("UNKNOWN", ["numbers_not_in_source"])
    # mô hình bịa "rèn luyện 80"; luật cố định đọc đúng tình huống (65 < 70) → Không đạt, vẫn giữ cờ cảnh báo (20/11)
    assert verdicts[3] == ("NOT_MET", ["fact_not_in_case", "numeric_rule"])
    assert out["overall"] == "NOT_ELIGIBLE" and out["agent"] == "student_affairs"  # "học bổng" thuộc Công tác sinh viên


def test_met_without_case_fact_is_unknown_and_no_evidence_short_circuits():
    with use_pack("education"):
        out = asyncio.run(check_conditions(Provider({"note": "", "conditions": [_cond(condition="Điểm trung bình học kỳ từ 3,2")]}),
                                           "Có đủ điều kiện học bổng không?", CASE, [RULE]))
        # mô hình không nêu dữ kiện; luật cố định đọc "3,4" trong tình huống → Đạt (20/11), cờ "no_case_fact" vẫn giữ
        assert out["conditions"][0]["flags"] == ["no_case_fact", "numeric_rule"] and out["overall"] == "ELIGIBLE"
        empty = asyncio.run(check_conditions(Provider({}), "Có đủ điều kiện không?", CASE, []))
    assert empty["overall"] == "NO_RULE" and empty["conditions"] == []


def test_procedure_drops_uncited_steps_and_unsupported_deadlines():
    payload = {"note": "", "steps": [
        {"action": "Khoa lập danh sách đề cử", "actor": "Khoa", "deadline": "10 ngày làm việc", "outputs": "Danh sách", "citation": "q1"},
        {"action": "Bước bịa", "actor": "", "deadline": "", "outputs": "", "citation": "zzz"},
        {"action": "Phòng Công tác sinh viên thẩm định", "actor": "Phòng CTSV", "deadline": "5 ngày", "outputs": "", "citation": "q1"},
    ], "documents": [{"name": "Bảng điểm", "citation": "q1"}, {"name": "bảng điểm", "citation": "q1"}, {"name": "Giấy bịa", "citation": "x"}]}
    with use_pack("education"):
        out = asyncio.run(extract_procedure(Provider(payload), "Xét học bổng", [RULE]))
    assert [s["order"] for s in out["steps"]] == [1, 2] and out["removed"] == 2
    assert out["steps"][0]["deadline"] == "10 ngày làm việc"
    assert out["steps"][1]["deadline"] == "" and out["steps"][1]["flags"] == ["deadline_not_in_source"]
    assert [d["name"] for d in out["documents"]] == ["Bảng điểm"]


def test_criteria_from_lines_and_checklist_extraction():
    with use_pack("legal_admin"):
        items = criteria_from_lines(["Hợp đồng ghi rõ thời hạn thanh toán", "", "hợp đồng ghi rõ thời hạn thanh toán", "Có điều khoản giải quyết tranh chấp"])
        assert [(r.req_id, r.agent) for r in items] == [("TC-01", "contract"), ("TC-02", "contract")]
        listed = extract_checklist("# Danh mục\n- Có chữ ký hai bên\n1. Ghi giá trị hợp đồng\nĐoạn văn thường\na) Thời hạn hiệu lực\n- ok")
    assert [r.title for r in listed] == ["Có chữ ký hai bên", "Ghi giá trị hợp đồng", "Thời hạn hiệu lực"]


class Store:
    def chunks(self, source_ids):
        return [RULE] if source_ids == ["doc"] else []


class Pipeline:
    source_store = Store()

    def _retrieve_candidates(self, query, chunks, *, top_k, min_score, source_ids, fallback_trace):
        return chunks[:top_k]


def _client(payload):
    provider = Provider(payload)
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: Pipeline(),
                                    session_factory=lambda: None, provider_factory=lambda: provider))
    return TestClient(app), provider


def test_casework_api_uses_domain_pack_and_validates():
    c, provider = _client({"note": "", "conditions": [_cond(condition="Điểm trung bình học kỳ từ 3,2", case_fact="điểm trung bình 3,4")]})
    r = c.post("/api/studio/casework/conditions", json={"question": "Đủ điều kiện học bổng?", "case": CASE, "source_ids": ["doc"], "domain_pack": "education"})
    assert r.status_code == 200 and r.json()["overall"] == "ELIGIBLE" and "Student Affairs" in provider.system
    assert c.post("/api/studio/casework/conditions", json={"question": "Đủ điều kiện?", "case": CASE, "source_ids": ["nope"]}).status_code == 404
    assert c.post("/api/studio/casework/conditions", json={"question": "Đủ điều kiện?", "case": CASE, "source_ids": ["doc"], "domain_pack": "y_te"}).status_code == 422
    c2, _ = _client({"note": "", "steps": [], "documents": []})
    body = c2.post("/api/studio/casework/procedure", json={"topic": "Xét học bổng", "source_ids": ["doc"], "domain_pack": "education"}).json()
    assert body["steps"] == [] and body["agent"] == "student_affairs"
    listed = c2.post("/api/studio/traceability/extract", json={"source_id": "doc", "mode": "list"})
    assert listed.status_code == 200 and listed.json()["requirements"] == []  # đoạn quy định không có dòng danh mục


ARTICLE10 = SourceChunk("q0", "quy_che", "quy_che.md", "## Điều 10. Cảnh báo học tập\n1. Điểm trung bình học kỳ dưới 1,0 thì bị cảnh báo.", 0)
HR_RULE = SourceChunk("h1", "noi_quy", "noi_quy.md", "## Mục 8. Nghỉ phép\n1. Gửi đơn trước ít nhất 3 ngày làm việc; nghỉ từ 3 ngày trở lên gửi trước 7 ngày.\n2. Trưởng phòng duyệt.", 0)


def test_wrong_neighbour_citation_is_corrected():
    # chạy thật: mô hình dẫn Điều 10 cho điều kiện của Điều 15 -> phải tự chuyển về đoạn chứa con số
    payload = {"note": "", "conditions": [_cond(condition="Điểm rèn luyện từ 70 trở lên", citation="q0", case_fact="điểm rèn luyện 65", verdict="NOT_MET")]}
    with use_pack("education"):
        out = asyncio.run(check_conditions(Provider(payload), "Có đủ điều kiện học bổng không?", CASE, [ARTICLE10, RULE]))
    c = out["conditions"][0]
    assert c["citation"] == "q1" and c["flags"] == ["citation_corrected"] and out["overall"] == "NOT_ELIGIBLE"


def test_case_facts_copied_as_conditions_are_dropped():
    # chạy thật: mô hình chép dữ kiện tình huống thành "điều kiện" rồi tự chấm Đạt -> kết luận sai "Đủ điều kiện"
    case = "Đã làm việc 3 năm; còn 8 ngày phép; gửi đơn trên hệ thống trước 2 ngày làm việc."
    payload = {"note": "", "conditions": [
        _cond(condition="Đã làm việc 3 năm", citation="h1", case_fact="Đã làm việc 3 năm"),
        _cond(condition="Còn 8 ngày phép", citation="h1", case_fact="còn 8 ngày phép"),
        _cond(condition="Gửi đơn trên hệ thống trước 2 ngày làm việc", citation="h1", case_fact="gửi đơn trước 2 ngày làm việc"),
    ]}
    with use_pack("business_hr"):
        out = asyncio.run(check_conditions(Provider(payload), "Có được nghỉ phép 6 ngày không?", case, [HR_RULE]))
    assert out["overall"] != "ELIGIBLE" and out["removed"] >= 2
    assert not any(c["verdict"] == "MET" and c["condition"].lower() in case.lower() for c in out["conditions"])


class SeqProvider:
    def __init__(self, *payloads):
        self.payloads, self.users = list(payloads), []

    async def generate_structured(self, *, system, user, response_schema):
        self.users.append(user)
        return SimpleNamespace(text=json.dumps(self.payloads[min(len(self.users), len(self.payloads)) - 1], ensure_ascii=False), usage=Usage(100, 20))


def test_retry_once_when_model_only_repeats_the_case():
    case = "Đã làm việc 3 năm; gửi đơn trên hệ thống trước 2 ngày làm việc."
    copied = {"note": "", "conditions": [_cond(condition="Gửi đơn trên hệ thống trước 2 ngày làm việc", citation="h1", case_fact="gửi đơn trước 2 ngày làm việc")]}
    real = {"note": "", "conditions": [_cond(condition="Nghỉ từ 3 ngày trở lên gửi đơn trước 7 ngày", citation="h1",
                                             case_fact="gửi đơn trên hệ thống trước 2 ngày làm việc", verdict="NOT_MET")]}
    with use_pack("business_hr"):
        p = SeqProvider(copied, real)
        out = asyncio.run(check_conditions(p, "Có được nghỉ phép 6 ngày không?", case, [HR_RULE]))
        assert len(p.users) == 2 and "REJECTED" in p.users[1] and p.users[0].startswith("RULE EVIDENCE")
        assert out["overall"] == "NOT_ELIGIBLE" and out["removed"] == 1 and out["input_tokens"] == 200
        stuck = asyncio.run(check_conditions(SeqProvider(copied), "Có được nghỉ phép 6 ngày không?", case, [HR_RULE]))
    assert stuck["overall"] == "UNRESOLVED" and stuck["conditions"] == []
    assert overall_verdict([], removed=2) == "UNRESOLVED"


def test_retry_once_when_model_returns_no_conditions():
    real = {"note": "", "conditions": [_cond(condition="Điểm rèn luyện từ 70 trở lên", citation="q1", case_fact="điểm rèn luyện 65", verdict="NOT_MET")]}
    with use_pack("education"):
        p = SeqProvider({"note": "", "conditions": []}, real)
        out = asyncio.run(check_conditions(p, "Có đủ điều kiện học bổng không?", CASE, [RULE]))
    assert len(p.users) == 2 and "listed no conditions" in p.users[1] and out["overall"] == "NOT_ELIGIBLE"


def test_no_retry_and_no_rule_when_documents_do_not_mention_question():
    """P1-1: tài liệu không nhắc tới nội dung câu hỏi thì báo không có quy định, không hỏi lại mô hình."""
    from app.analysis.casework import mentions_question
    off = SourceChunk("s1", "bao_mat", "bao_mat.md", "Mật khẩu tối thiểu 12 ký tự, đổi định kỳ 90 ngày, khóa sau 5 lần sai.", 0)
    assert not mentions_question("Có được nghỉ phép 6 ngày không?", [off])
    assert mentions_question("Có đủ điều kiện học bổng không?", [RULE])
    p = SeqProvider({"note": "", "conditions": []})
    out = asyncio.run(check_conditions(p, "Có được nghỉ phép 6 ngày không?", "Đã làm 3 năm.", [off]))
    assert len(p.users) == 0 and out["overall"] == "NO_RULE" and "không nói tới" in out["note"]  # không gọi mô hình


def test_generic_pairs_do_not_count_as_mentioning():
    from app.analysis.casework import mentions_question
    sec = SourceChunk("s2", "su_co", "su_co.md", "Nhân viên trực ca xác nhận cảnh báo trong 5 phút; 3 lần liên tiếp thất bại thì báo động.", 0)
    assert not mentions_question("Nhân viên làm 2 năm có được nghỉ phép 6 ngày liên tiếp không?", [sec])


def test_numeric_verdict_by_fixed_rule():
    """Thử theo vai 20/11: so con số bằng luật cố định thay vì để mô hình kết luận "chưa rõ"."""
    from app.analysis.casework import numeric_verdict
    cond = "Sinh viên được xét học bổng khi điểm trung bình học kỳ từ 3,2 trở lên (thang 4) và điểm rèn luyện từ 70 trở lên."
    assert numeric_verdict(cond, "Điểm trung bình học kỳ 3,4; điểm rèn luyện 65.") == "NOT_MET"
    assert numeric_verdict(cond, "Điểm trung bình học kỳ 3,4; điểm rèn luyện 80.") == "MET"
    assert numeric_verdict(cond, "Điểm trung bình học kỳ 3,4.") is None          # thiếu số rèn luyện: không kết luận
    assert numeric_verdict("Tạm ứng tối đa 70% dự toán", "Xin tạm ứng 80% dự toán") == "NOT_MET"
    assert numeric_verdict("Có giấy của cơ sở y tế", "Nghỉ ốm 2 ngày") is None     # không có ngưỡng số


def test_check_conditions_overrides_unknown_with_numbers():
    payload = {"note": "", "conditions": [_cond(condition="Điểm trung bình học kỳ từ 3,2 trở lên và điểm rèn luyện từ 70 trở lên",
                                                case_fact="", verdict="UNKNOWN")]}
    with use_pack("education"):
        out = asyncio.run(check_conditions(Provider(payload), "Có đủ điều kiện học bổng không?", CASE, [RULE]))
    assert out["overall"] == "NOT_ELIGIBLE" and out["conditions"][0]["verdict"] == "NOT_MET" and "numeric_rule" in out["conditions"][0]["flags"]


def test_numeric_verdict_skips_negated_conditions_and_facts():
    from app.analysis.casework import numeric_verdict
    assert numeric_verdict("Sinh viên có học phần dưới 5,0 trong học kỳ không được xét học bổng.", "Không có học phần dưới 5.") is None
    assert numeric_verdict("Học phần đạt khi điểm từ 4,0 trở lên", "Chưa có điểm học phần") is None
