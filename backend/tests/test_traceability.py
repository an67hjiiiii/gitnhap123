"""Truy vết yêu cầu: trích yêu cầu, quy tắc trung thực khi kết luận, và API (không cần PostgreSQL/Ollama)."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis.traceability import Requirement, assign_agent, check_requirement, extract_requirements
from app.api.analysis import build_router
from app.core.types import SourceChunk, Usage

SRS = """# ĐẶC TẢ
## 3. Yêu cầu chức năng
### FR-01 Đăng ký merchant
- Merchant đăng ký bằng email doanh nghiệp.
- Mã xác minh hiệu lực 15 phút.

### FR-02 Quản lý khóa API
- Khóa bị thu hồi mất hiệu lực trong vòng 60 giây.
## 4. Yêu cầu phi chức năng
| Mã | Yêu cầu | Chỉ tiêu |
|---|---|---|
| NFR-01 | Hiệu năng API tạo đơn | 95% dưới 300 ms |
| NFR-02 | Sẵn sàng | 99,9% mỗi tháng |
- 100% ca kiểm thử FR-03 đến FR-07 đạt.
### FR-01 Đăng ký merchant (nhắc lại)
**UC_01** Người mua bấm thanh toán hai lần
"""


def test_extract_requirements_from_headings_tables_and_bold_ids():
    reqs = extract_requirements(SRS)
    assert [r.req_id for r in reqs] == ["FR-01", "FR-02", "NFR-01", "NFR-02", "UC-01"]
    fr1 = reqs[0]
    assert fr1.title == "Đăng ký merchant" and "15 phút" in fr1.body and "60 giây" not in fr1.body
    assert reqs[2].title == "Hiệu năng API tạo đơn · 95% dưới 300 ms" and reqs[2].body == ""
    assert "FR-03" not in [r.req_id for r in reqs]  # mã nằm giữa câu không phải yêu cầu


def test_requirement_ending_at_next_heading():
    reqs = extract_requirements(SRS)
    assert "Yêu cầu phi chức năng" not in reqs[1].body


def test_assign_agent_prefers_strongest_domain_and_defaults():
    assert assign_agent("Bảng payments có khóa chính, chỉ mục và transaction database")[1] == "database"
    assert assign_agent("Trang chủ hiển thị logo")[1] == "api_architecture"


CHUNKS = [SourceChunk("d1", "s9", "api.md", "Khóa bị thu hồi mất hiệu lực trong 60 giây.", 0, 0.7)]
REQ = Requirement("FR-02", "Quản lý khóa API", "Khóa bị thu hồi mất hiệu lực trong vòng 60 giây.", ["api_architecture"], "api_architecture")


class StructuredProvider:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    async def generate_structured(self, *, system, user, response_schema):
        self.calls += 1
        assert response_schema["properties"]["citations"]["items"]["enum"] == ["d1"]
        return SimpleNamespace(text=json.dumps(self.payload), usage=Usage(120, 30))


def _check(payload, evidence=CHUNKS):
    provider = StructuredProvider(payload)
    return asyncio.run(check_requirement(provider, REQ, evidence)), provider


def test_covered_with_valid_citation_is_kept():
    result, _ = _check({"status": "COVERED", "citations": ["d1"], "covered_points": ["60 giây"], "missing_points": [], "note": "Đủ."})
    assert result["status"] == "COVERED" and result["citations"] == ["d1"]
    assert result["input_tokens"] == 120 and result["output_tokens"] == 30 and result["agent_name"]


def test_covered_without_valid_citation_is_downgraded():
    result, _ = _check({"status": "COVERED", "citations": ["khong-co"], "covered_points": [], "missing_points": [], "note": ""})
    assert result["status"] == "PARTIAL"
    assert "no_valid_citation" in result["flags"] and "invalid_citation_removed" in result["flags"]


def test_invalid_model_status_becomes_partial():
    result, _ = _check({"status": "YES", "citations": [], "note": ""})
    assert result["status"] == "PARTIAL" and "invalid_model_output" in result["flags"]


def test_no_evidence_is_missing_without_calling_model():
    result, provider = _check({}, evidence=[])
    assert result["status"] == "MISSING" and provider.calls == 0 and "no_evidence" in result["flags"]


class FakeStore:
    def chunks(self, source_ids=None):
        if source_ids == ["srs"]:
            return [SourceChunk("srs_c1", "srs", "srs.md", SRS.split("## 4.")[0], 1),
                    SourceChunk("srs_c0", "srs", "srs.md", "# Tiêu đề", 0)]
        if source_ids == ["design"]:
            return CHUNKS
        return []


class FakePipeline:
    source_store = FakeStore()

    def _retrieve_candidates(self, query, chunks, *, top_k, min_score, source_ids, fallback_trace):
        return chunks[:top_k]


def _client(session=None, payload=None):
    app = FastAPI()
    provider = StructuredProvider(payload or {"status": "COVERED", "citations": ["d1"], "covered_points": [], "missing_points": [], "note": ""})
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: FakePipeline(),
                                    session_factory=lambda: session, provider_factory=lambda: provider))
    return TestClient(app)


def test_extract_api_orders_chunks_and_404s_unknown_source():
    c = _client()
    body = c.post("/api/studio/traceability/extract", json={"source_id": "srs"}).json()
    assert body["source_name"] == "srs.md" and [r["req_id"] for r in body["requirements"]] == ["FR-01", "FR-02"]
    assert c.post("/api/studio/traceability/extract", json={"source_id": "nope"}).status_code == 404


def test_check_api_returns_grounded_result():
    r = _client().post("/api/studio/traceability/check", json={"requirement": {"req_id": "FR-02", "title": "Quản lý khóa API",
                                                                              "body": "60 giây"}, "source_ids": ["design"]})
    assert r.status_code == 200 and r.json()["status"] == "COVERED"
    assert _client().post("/api/studio/traceability/check", json={"requirement": {"req_id": "X", "title": "t"},
                                                                  "source_ids": ["missing"]}).status_code == 404


def test_reports_need_postgres():
    assert _client(session=None).get("/api/studio/reports").status_code == 503


def test_covered_with_missing_points_is_downgraded():
    result, _ = _check({"status": "COVERED", "citations": ["d1"], "covered_points": ["60 giây"], "missing_points": ["Chưa nêu nhật ký"], "note": ""})
    assert result["status"] == "PARTIAL" and "has_missing_points" in result["flags"]


def test_quantitative_target_must_appear_in_cited_evidence():
    req = Requirement("NFR-01", "Hiệu năng API tạo đơn · 95% dưới 300 ms", "", [], "api_architecture")
    webhook = [SourceChunk("d1", "s9", "api.md", "Merchant phải trả 2xx trong 10 giây.", 0, 0.7)]
    payload = {"status": "COVERED", "citations": ["d1"], "covered_points": [], "missing_points": [], "note": ""}
    result = asyncio.run(check_requirement(StructuredProvider(payload), req, webhook))
    assert result["status"] == "PARTIAL" and "numbers_not_in_evidence" in result["flags"]
    ok = [SourceChunk("d1", "s9", "api.md", "95% yêu cầu phản hồi dưới 300 ms.", 0, 0.7)]
    assert asyncio.run(check_requirement(StructuredProvider(payload), req, ok))["status"] == "COVERED"


def test_number_normalization():
    from app.analysis.traceability import _numbers
    assert _numbers("1.000 đến 500.000.000 VND, TLS 1.2, 99,9% theo FR-04") == {"1000", "500000000", "1.2", "99.9"}


def test_evidence_prefers_bm25_and_fills_from_vector():
    from app.analysis.traceability import evidence_for
    refunds = SourceChunk("r1", "s1", "db.md", "Bảng refunds lưu yêu cầu hoàn tiền một phần và requires_approval.", 2, 0.0)
    title = SourceChunk("t0", "s1", "db.md", "THIẾT KẾ CƠ SỞ DỮ LIỆU – CỔNG THANH TOÁN", 0, 0.0)

    class VectorOnlyTitle:
        def _retrieve_candidates(self, query, chunks, *, top_k, min_score, source_ids, fallback_trace):
            return [SourceChunk(**{**title.__dict__, "score": 0.74})]

    found = evidence_for(VectorOnlyTitle(), "hoàn tiền một phần refunds", [title, refunds], top_k=2, min_score=0.1, source_ids=["s1"])
    assert [c.chunk_id for c in found] == ["r1", "t0"]  # r1 khớp BM25 trước, t0 bù từ vector


def test_security_controls_are_unique_and_routed_to_security_agent():
    from app.analysis.security_review import asvs_controls
    controls = asvs_controls()
    ids = [c["req_id"] for c in controls]
    assert len(ids) == len(set(ids)) >= 25
    assert all(c["agent"] == "security" and c["group"] and c["title"] and c["body"] for c in controls)
    assert _client().get("/api/studio/security/controls").json()["standard"] == "OWASP ASVS 4.0.3"


def test_check_api_honours_forced_agent():
    r = _client().post("/api/studio/traceability/check", json={"requirement": {"req_id": "V3.4.2", "title": "Cookie HttpOnly", "body": "60 giây"},
                                                               "source_ids": ["design"], "agent": "security"})
    assert r.status_code == 200 and r.json()["agent"] == "security"


def test_report_update_is_owner_scoped():
    calls = []

    class Db:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            calls.append((str(sql), params)); return type("R", (), {"rowcount": 1 if params.get("r") == "rpt_1" else 0})()
        def commit(self): pass

    c = _client(session=lambda: Db())
    assert c.patch("/api/studio/reports/rpt_1", json={"payload": {"grades": {}}}).status_code == 200
    sql, params = calls[-1]
    assert "owner_user_id = :o" in sql and params["o"] == "u1" and params["t"] is None
    assert c.patch("/api/studio/reports/khac", json={"payload": {}}).status_code == 404


def test_required_terms_downgrade_unsupported_security_claims():
    from app.analysis.traceability import missing_term_groups
    assert missing_term_groups("Cookie có thuộc tính HttpOnly, Secure, SameSite=Lax", [["httponly"], ["samesite"]]) == []
    assert missing_term_groups("Phiên hết hạn sau 30 phút không hoạt động", [["dang xuat", "logout"]]) == [["dang xuat", "logout"]]
    assert missing_term_groups("Lỗi hệ thống", [["lo"]]) == [["lo"]]  # so nguyên từ: "lỗi" không khớp "lo"
    req = Requirement("V3.3.1", "Đăng xuất làm mất hiệu lực phiên", "logout invalidate session", ["security"], "security")
    payload = {"status": "COVERED", "citations": ["d1"], "covered_points": [], "missing_points": [], "note": ""}
    idle = [SourceChunk("d1", "s9", "sec.md", "Phiên đăng nhập web hết hạn sau 30 phút không hoạt động.", 0, 0.7)]
    out = asyncio.run(check_requirement(StructuredProvider(payload), req, idle, required_terms=[["dang xuat", "logout"]]))
    assert out["status"] == "PARTIAL" and "terms_not_in_evidence" in out["flags"]
    ok = [SourceChunk("d1", "s9", "sec.md", "Đăng xuất thu hồi phiên ngay lập tức.", 0, 0.7)]
    assert asyncio.run(check_requirement(StructuredProvider(payload), req, ok, required_terms=[["dang xuat", "logout"]]))["status"] == "COVERED"


def test_requirement_quality_api_reviews_source_and_404s():
    c = _client()
    body = c.post("/api/studio/req-quality", json={"source_id": "srs"}).json()
    assert body["source_name"] == "srs.md" and body["summary"]["total"] == 2 and "29148" in body["standard"]
    assert c.post("/api/studio/req-quality", json={"source_id": "nope"}).status_code == 404
