"""Kiểm thử hồi quy cho đợt khắc phục 22 hạng mục kiểm toán ngày 2026-11-25."""
from __future__ import annotations

import asyncio
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis import casework, consistency, domain_tools
from app.analysis.skill_router import route_skill
from app.api.analysis import RoutingFeedbackBody
from app.api.auth import LOGIN_FAILURE_LIMIT, reset_login_rate_limit, router as auth_router
from app.auth.store import InvalidCredentialsError
from app.core.types import ProviderResult, RunMetrics, SourceChunk, TaskResult, Usage
from app.ingestion.doc_type import classify_document
from app.ingestion.documents import extract_document
from app.research import knowledge_source, product_intents, synthesizer
from app.retrieval.source_focus import focus_sources


# --- Đợt 1: RAG, ngôn ngữ, định tuyến, sản phẩm ---

def test_product_intents_branding_and_punctuation_guard():
    greet = product_intents.product_help_response("xin chào")
    assert greet is not None
    kind, reply = greet
    assert kind == "greeting"
    assert "OrchestrIQ Studio" in reply
    assert "CAP1_AI" not in reply

    junk = product_intents.product_help_response("???")
    assert junk is not None
    j_kind, j_reply = junk
    assert j_kind == "empty_or_punctuation"
    assert "câu hỏi cụ thể" in j_reply.lower()


def test_source_focus_ignores_xlsx_and_csv_extensions():
    chunks = [
        SourceChunk(chunk_id="s1_c0", source_id="s1", source_name="Ke_hoach_ngan_sach.xlsx", index=0, text="Bảng dự toán"),
        SourceChunk(chunk_id="s2_c0", source_id="s2", source_name="Chinh_sach_ngan_sach.md", index=0, text="Chính sách"),
        SourceChunk(chunk_id="s3_c0", source_id="s3", source_name="Chi_tieu_Q1.csv", index=0, text="Chi tiêu quý 1"),
    ]
    # Nhắc "xlsx" hay "csv" chung chung không khóa chặt vào tệp duy nhất nếu không trùng nội dung tên tệp
    assert focus_sources("Cho tôi xem dữ liệu trong file xlsx và csv", chunks, None) is None


def test_skill_router_detects_multi_part_with_nao():
    q = "Khi khách hàng gặp lỗi thanh toán thì nên dùng kênh liên hệ nào và cơ chế đền bù nào theo quy định?"
    assert route_skill(q, ["internal_policy", "regulation"]) is None


def test_routing_feedback_accepts_both_office_and_work_agents():
    for agent in ("software", "business", "marketing", "hr", "finance", "education", "analyst",
                  "conditions", "procedure", "terms", "figures"):
        body = RoutingFeedbackBody(query="Câu hỏi thử", agent=agent)
        assert body.agent == agent


def test_knowledge_source_org_label_avoids_claiming_nonexistent_in_reality():
    org_lbl = knowledge_source.label("vi", True, in_org=True)
    assert "được phép xem" in org_lbl.lower()
    assert "tài liệu bạn gửi không có" not in org_lbl.lower()

    personal_lbl = knowledge_source.label("vi", True, in_org=False)
    assert "tài liệu bạn gửi" in personal_lbl.lower()


def test_synthesizer_english_meta_leak_triggers_vietnamese_retry():
    class LeakThenViProvider:
        supports_per_call_output_tokens = True

        def __init__(self):
            self.calls = 0

        async def generate_structured(self, *, system: str, user: str, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ProviderResult(
                    text='{"answer": "The user asked about overtime pay. The task results show 150% on weekdays."}',
                    usage=Usage(10, 20),
                )
            return ProviderResult(
                text='{"answer": "Làm thêm giờ ngày thường được hưởng 150% đơn giá tiền lương [src_1_c0]."}',
                usage=Usage(10, 20),
            )

    provider = LeakThenViProvider()
    metrics = RunMetrics()
    task_res = TaskResult(
        task_id="t1",
        domain="hr",
        status="COMPLETE",
        answer="Ngày thường hưởng 150% [src_1_c0].",
        citations=["src_1_c0"],
        evidence_ids=["src_1_c0"],
    )
    out = asyncio.run(
        synthesizer.synthesize(
            provider,
            "Tiền làm thêm giờ ngày thường là bao nhiêu?",
            [task_res],
            metrics,
            reply_language="vi",
            max_output_tokens=700,
        )
    )
    assert provider.calls == 2
    assert "The user asked" not in out
    assert "150%" in out


# --- Đợt 2: CSV, phân loại tài liệu, công cụ nghiệp vụ ---

def test_extract_document_supports_csv():
    raw = "Ho ten,Phong ban,Luong\nNguyen Van A,Ky thuat,25000000\nTran Thi B,Nhan su,18000000\n".encode("utf-8-sig")
    doc = extract_document(raw, "bang_luong.csv")
    assert doc.source_format == "csv"
    assert doc.source_type == "text/csv"
    assert "Nguyen Van A | Ky thuat | 25000000" in doc.text
    assert doc.provenance["parser"] == "stdlib-csv-v1"


def test_doc_type_classifies_regulation_and_english_architecture():
    reg_text = (
        "QUY CHẾ ĐÀO TẠO ĐẠI HỌC CHÍNH QUY NĂM 2026\n"
        "Điều 1. Phạm vi điều chỉnh và kết quả học tập của sinh viên.\n"
        "Điều 2. Điểm trung bình học kỳ (GPA) và xếp loại học lực.\n"
        "Điều 3. Chương I học phần, tín chỉ và rèn luyện.\n"
    )
    assert classify_document("Quy_che_dao_tao_DH_2026.docx", reg_text) == "regulation"

    arch_text = (
        "TECHNICAL ARCHITECTURE AND DATABASE DESIGN\n"
        "PostgreSQL database schema with primary key and foreign key constraints.\n"
        "REST API endpoints enforce rate limiting and idempotency keys.\n"
    )
    assert classify_document("Technical_Architecture_v2.md", arch_text) == "software_spec"


def test_extract_thresholds_drops_cross_article_year_scope():
    class FakeThresholdProvider:
        async def generate(self, *, system: str, user: str, **kwargs):
            return ProviderResult(
                text='{"rules":[{"label":"Điểm trung bình học bổng","op":">=","value":"3.2","unit":"điểm","applies_to":"năm thứ nhất","citation":"src_1_c0"}]}',
                usage=Usage(10, 20),
            )

    chunk = SourceChunk(
        chunk_id="src_1_c0",
        source_id="src_1",
        source_name="quy_che.docx",
        index=0,
        text="Điều 4. Cảnh báo học tập: sinh viên năm thứ nhất có ĐTB dưới 1,2 bị cảnh báo.\nĐiều 5. Học bổng khuyến khích: đạt GPA từ 3,2 trở lên và rèn luyện từ 80 điểm.",
    )
    res = asyncio.run(domain_tools.extract_thresholds(FakeThresholdProvider(), "Xét học bổng khuyến khích", [chunk]))
    assert len(res["rules"]) == 1
    assert res["rules"][0]["applies_to"] == ""
    assert res["rules"][0]["year_min"] is None
    assert res["rules"][0]["year_max"] is None


def test_document_validity_parses_slash_dates():
    docs = [
        ("s1", "QD_2026.pdf", "QUYẾT ĐỊNH Số: 45/2026/QĐ-UBND ngày 10/06/2026.\nQuyết định này có hiệu lực từ ngày 01/07/2026."),
    ]
    res = domain_tools.document_validity(docs, today=date(2026, 11, 25))
    doc = res["documents"][0]
    assert doc["effective"] == "2026-07-01"
    assert doc["issued"] == "2026-06-10"
    assert doc["status"] == "IN_FORCE"


def test_contract_rule_risks_dynamic_interest_exemption_and_no_heading_dup():
    chunk = SourceChunk(
        chunk_id="c1",
        source_id="s1",
        source_name="hd.docx",
        index=0,
        text=(
            "Điều 5. Phạt vi phạm 12%\n"
            "Bên vi phạm chịu phạt vi phạm 12% giá trị hợp đồng nếu giao hàng chậm.\n"
            "Bên B được miễn trừ toàn bộ trách nhiệm bồi thường thiệt hại trong mọi trường hợp.\n"
            "Bên mua thanh toán chậm chịu lãi chậm trả 0,2%/ngày trên số tiền chậm trả.\n"
            "Thanh toán trước 30% và không phạt khi giao đúng hạn.\n"
        ),
    )
    risks = domain_tools.rule_risks([chunk])
    quotes = [r["quote"] for r in risks]
    assert not any(q.startswith("Điều 5.") for q in quotes)
    assert any("12%" in r["quote"] and r["level"] == "HIGH" for r in risks)
    assert any("miễn trừ toàn bộ trách nhiệm" in r["quote"].lower() and r["level"] == "HIGH" for r in risks)
    interest_risks = [r for r in risks if "0,2%" in r["quote"]]
    assert len(interest_risks) == 1
    assert "0,2%/ngày" in interest_risks[0]["reason"]
    assert "0,5%/ngày" not in interest_risks[0]["reason"]
    assert not any("Thanh toán trước 30%" in r["quote"] for r in risks)


def test_consistency_supports_single_document_internal_contradictions():
    chunks = [
        SourceChunk(
            chunk_id="s1_c0",
            source_id="s1",
            source_name="quy_dinh.md",
            index=0,
            text=(
                "Thời hạn hoàn tiền cho khách hàng tối đa là 3 ngày làm việc kể từ khi xác nhận.\n"
                "Thời hạn hoàn tiền cho khách hàng tối đa là 15 ngày làm việc kể từ khi xác nhận.\n"
            ),
        )
    ]
    stmts = consistency.extract_statements(chunks)
    pairs = consistency.candidate_pairs(stmts)
    assert len(pairs) >= 1
    assert pairs[0]["reason"] == "numbers_differ"


def test_procedure_filters_step_label_used_as_deadline():
    class FakeProcProvider:
        async def generate(self, *, system: str, user: str, **kwargs):
            return ProviderResult(
                text='{"steps":[{"action":"Nộp đơn xin nghỉ","actor":"Nhân viên","deadline":"Bước 1","outputs":"Đơn","citation":"c1"}],"documents":[],"fees":[],"note":""}',
                usage=Usage(10, 20),
            )

    chunk = SourceChunk(chunk_id="c1", source_id="s1", source_name="qt.md", index=0, text="Bước 1: Nhân viên nộp đơn xin nghỉ.")
    res = asyncio.run(casework.extract_procedure(FakeProcProvider(), "Quy trình xin nghỉ phép", [chunk]))
    assert len(res["steps"]) == 1
    assert res["steps"][0]["deadline"] == ""
    assert "deadline_is_step_label" in res["steps"][0]["flags"]


# --- Đợt 3: Bảo mật đăng nhập ---

def test_login_rate_limit_and_production_token_hiding(monkeypatch):
    reset_login_rate_limit()

    class StubAuthStore:
        def authenticate(self, *, identifier, password):
            if password == "good-pass":
                return {"user_id": "u1", "email": identifier}, "secret-tok", {"session_id": "s1"}
            raise InvalidCredentialsError("bad")

    app = FastAPI()
    app.state.auth_store = StubAuthStore()
    app.include_router(auth_router)
    client = TestClient(app)

    for _ in range(LOGIN_FAILURE_LIMIT):
        r = client.post("/api/auth/login", json={"identifier": "brute@example.com", "password": "wrong"})
        assert r.status_code == 401
    blocked = client.post("/api/auth/login", json={"identifier": "brute@example.com", "password": "wrong"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers

    # Môi trường production ẩn access_token/token khỏi JSON body nhưng vẫn set cookie HttpOnly
    reset_login_rate_limit()
    monkeypatch.setenv("APP_ENV", "production")
    ok_prod = client.post("/api/auth/login", json={"identifier": "ok@example.com", "password": "good-pass"})
    assert ok_prod.status_code == 200
    body_prod = ok_prod.json()
    assert "access_token" not in body_prod and "token" not in body_prod
    assert "session_token=secret-tok" in ok_prod.headers["set-cookie"].lower()

    # Môi trường development vẫn giữ tương thích cũ
    monkeypatch.setenv("APP_ENV", "development")
    ok_dev = client.post("/api/auth/login", json={"identifier": "ok@example.com", "password": "good-pass"})
    assert ok_dev.status_code == 200
    assert ok_dev.json()["access_token"] == "secret-tok"
    reset_login_rate_limit()
