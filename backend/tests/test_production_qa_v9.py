"""V9 Production QA Hardening: regression tests cho 9 lỗi gốc (từ 4 ảnh test Q3/Q5/Q6/Q7 + quét codebase)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis.skill_router import is_multi_part, route_skill
from app.api.analysis import build_router
from app.core.answer_checks import apply_calc, clean, finish_detailed, unsupported_numbers
from app.core.types import SourceChunk
from app.ingestion.doc_type import classify_document
from app.research.conversation_context import ConversationContext, resolve_follow_up
from app.research.knowledge_source import doc_bound
from app.research.product_intents import is_library_question, is_simple_project_question
from app.retrieval.source_focus import focus_sources, has_same_family_for_years


# 1. Skill Router — Q5 không bị cướp sang skill "compare" hay báo lỗi đỏ
def test_q5_cost_comparison_not_hijacked_by_compare_skill():
    q5 = (
        "Phân tích hiệu quả tài chính và kỹ thuật của kế hoạch chuyển sang kiến trúc Hybrid Local-First năm 2026 "
        "của VietCore AI: (1) Chi phí Cloud & GPU Q4/2025 biến động ra sao? (2) So sánh chi phí năm 2026 giữa giữ "
        "Cloud 100% và chuyển sang Hybrid Local-First, tính số tiền tiết kiệm và thời gian hoàn vốn cụm GPU? "
        "(3) Nêu rủi ro nếu chậm lắp đặt quá Quý I/2026 và liên hệ với số liệu khảo sát thị trường."
    )
    assert is_multi_part(q5.lower()) is True
    assert route_skill(q5, ["regulation", "other", "software_spec", "other"]) is None

    # Ngay cả câu đơn có "so sánh chi phí năm 2026 giữa A và B" cũng không được cướp sang So sánh phiên bản tài liệu
    q_single_cost = "So sánh chi phí năm 2026 giữa phương án giữ Cloud 100% và đầu tư cụm GPU nội bộ."
    assert route_skill(q_single_cost, ["other", "software_spec"]) is None

    # So sánh 2 phiên bản văn bản thật sự vẫn đi vào skill compare
    assert route_skill("So sánh quy chế 2024 với bản 2026", ["regulation", "regulation"])["skill"] == "compare"


def test_route_endpoint_auto_compare_falls_back_to_pipeline_when_not_two_docs():
    rows = [
        {"source_id": "s1", "doc_type": "regulation"},
        {"source_id": "s2", "doc_type": "other"},
        {"source_id": "s3", "doc_type": "software_spec"},
        {"source_id": "s4", "doc_type": "other"},
    ]
    store = SimpleNamespace(list_sources=lambda: rows)
    app = FastAPI()
    app.include_router(
        build_router(
            current_user=lambda r: {"user_id": "u"},
            owner_pipeline=lambda user, *a: SimpleNamespace(source_store=store),
            session_factory=lambda: None,
        )
    )
    client = TestClient(app)

    # Auto-route (không gõ "/") khi đang chọn 4 tài liệu -> không ép skill compare, rơi về pipeline
    r4 = client.post(
        "/api/studio/route",
        json={"message": "So sánh bản mới với bản cũ của quy chế", "source_ids": ["s1", "s2", "s3", "s4"]},
    ).json()
    assert r4["route"] == "pipeline"

    # Khi chọn đúng 2 tài liệu -> auto-route vào skill compare bình thường
    r2 = client.post(
        "/api/studio/route",
        json={"message": "So sánh bản mới với bản cũ của quy chế", "source_ids": ["s1", "s2"]},
    ).json()
    assert r2["route"] == "skill" and r2["skill"] == "compare"

    # Khi người dùng chủ động gõ lệnh /compare -> vẫn trả skill compare để hiển thị hướng dẫn chọn 2 tài liệu
    r_explicit = client.post(
        "/api/studio/route",
        json={"message": "so sánh", "source_ids": ["s1", "s2", "s3", "s4"], "skill": "compare"},
    ).json()
    assert r_explicit["route"] == "skill" and r_explicit["skill"] == "compare"


# 2. Inventory Shortcut — Q7 không bị trả "Kho có 4 tài liệu"
def test_q7_based_on_existing_docs_is_not_library_question():
    q7 = (
        "Dựa trên các tài liệu hiện có của VietCore AI, hãy cho biết: "
        "(1) Tổng doanh thu thuần và lợi nhuận trước thuế Quý IV/2025 là bao nhiêu? "
        "(2) Chính sách bảo hiểm sức khỏe cho người thân nhân viên và mức phụ cấp ăn trưa hằng tháng năm 2026 là bao nhiêu?"
    )
    assert is_library_question(q7) is False
    assert is_library_question("Theo các tài liệu hiện có, mức phụ cấp ăn trưa là bao nhiêu?") is False
    assert is_library_question("Trong những file đã tải lên, doanh thu quý 4 là bao nhiêu?") is False

    # Câu hỏi kiểm kê kho thật sự vẫn hoạt động chính xác
    assert is_library_question("Kho hiện có những tài liệu nào?") is True
    assert is_library_question("Liệt kê các tài liệu đã tải lên") is True
    assert is_library_question("Hiện có bao nhiêu tài liệu trong kho?") is True


# 3. Follow-up Resolver — Q3 không bị dính câu SLA trước đó vì chữ "trong tháng đó"
def test_q3_independent_question_with_intra_sentence_do_not_followup():
    ctx = ConversationContext(
        last_user_request=(
            "Cho tôi biết cam kết SLA năm 2026 của VietCore AI Platform v4.0 "
            "về độ khả dụng Uptime, độ trễ P95 truy vấn đơn giản và chuẩn mã hóa dữ liệu."
        )
    )
    q3 = (
        "Một nhân viên chính thức tại VietCore AI đạt KPI bậc A (84 điểm) và trong tháng đi muộn quá 15 phút "
        "tổng cộng 5 lần không báo trước. Hãy cho biết mức thưởng KPI cuối năm và số tiền bị trừ vào phụ cấp "
        "chuyên cần trong tháng đó."
    )
    assert resolve_follow_up(q3, ctx) is None

    # Follow-up thật vẫn được nhận diện chính xác
    assert resolve_follow_up("Còn mức phạt nếu đi muộn 4 lần thì sao?", ctx) == ctx.last_user_request
    assert resolve_follow_up("Còn mục tiêu ISO 27001 thì sao?", ctx) == ctx.last_user_request
    assert resolve_follow_up("Chi tiết hơn?", ctx) == ctx.last_user_request


# 4. Answer Checks — Q3 không báo oan 450000, không rò [[= (X-N)*mức ]], không lặp "3 = 3 lần"
def test_answer_checks_handles_vietnamese_units_dedup_and_symbolic_calc():
    sources = (
        "KPI bậc A (80-89 điểm): thưởng 1,5 tháng lương gross. "
        "Đi muộn quá 15 phút không báo trước được miễn trừ tối đa 2 lần trong tháng. "
        "Từ lần vi phạm thứ 3 trở đi, mỗi lần bị trừ 10% phụ cấp chuyên cần (tương đương 150.000 VNĐ). "
        "Một nhân viên đạt KPI bậc A (84 điểm) đi muộn 5 lần trong tháng đó."
    )
    raw_answer = (
        "Mức thưởng KPI là **1,5 tháng lương gross**.\n"
        "- Số lần vượt ngưỡng: [[= 5 - 2 ]] = 3 lần.\n"
        "- Số tiền bị trừ: [[= (5 - 2) * 150000 ]] = 450.000 VNĐ.\n"
        "1. 5 lần vi phạm - 2 lần miễn trừ tối đa = 3 lần.\n"
        "2. 3 lần × 150.000 VNĐ = 450.000 VNĐ.\n"
        "Công thức áp dụng: [[= (X - N) * mức ]]."
    )
    final_text, bad, arts = finish_detailed(raw_answer, sources)
    assert bad == []
    assert arts == []
    assert "[[=" not in final_text
    assert "**3** = 3" not in final_text
    assert "**450.000** = 450.000" not in final_text
    assert "**450.000** VNĐ" in final_text
    assert "Cần kiểm tra lại" not in final_text

    # Phép quy đổi triệu <-> tỷ có căn cứ (24.000 triệu <-> 24 tỷ; 8.400 triệu <-> 8,4 tỷ) không bị báo oan
    fin_src = "Tổng ngân sách 24.000 triệu VNĐ. Hạ tầng CNTT 8.400 triệu VNĐ. Chương trình đào tạo 1.260 triệu và tuyển dụng 1.140 triệu."
    fin_ans = "Tổng ngân sách là 24 tỷ VNĐ (trong đó hạ tầng 8,4 tỷ VNĐ). Nhân sự = 1.260 triệu + 1.140 triệu = 2.400 triệu VNĐ."
    assert unsupported_numbers(fin_ans, fin_src) == []

    # Phép cộng/trừ diễn giải bằng lời tiếng Việt (vd. Q1: "12 ngày ... cộng thêm 2 ngày ..., tổng cộng 14 ngày")
    q1_src = "Nhân viên chính thức được nghỉ phép năm 12 ngày. Cứ đủ 4 năm thâm niên cộng thêm 1 ngày, tối đa 16 ngày. Chuyển phép tồn tối đa 3 ngày trước 30/04. Làm đủ 8 năm được bao nhiêu ngày?"
    q1_ans = "Nhân viên được hưởng 12 ngày nghỉ phép năm. Làm đủ 8 năm thâm niên được cộng thêm 2 ngày (8 năm / 4 năm = 2 ngày), tổng cộng 14 ngày phép năm. Phép tồn tối đa 3 ngày."
    assert unsupported_numbers(q1_ans, q1_src) == []

    # Cột (%) trong bảng Excel không có ký tự '%' cạnh số: câu trả lời viết 5.4%, 1.8%, 45% KHÔNG được sinh lỗi ảo 0.054000000000000006
    pct_src = "Kênh | ROAS | Chi phí | Tỷ lệ chuyển đổi (%) \n Google | 4.8 | 900 | 5.4 \n TikTok | 1.4 | 350 | 1 \n Cắt giảm 50% TikTok, dồn 75% ngân sách Marketing 2026 là 10.800 triệu"
    pct_ans = "### Tái phân bổ ngân sách Marketing 2026 (10.800 triệu VNĐ)\n1. Google đạt 5.4%, dồn 75% (8.100 triệu).\n2. Cắt giảm 50% TikTok (từ 350 triệu xuống 175 triệu)."
    assert unsupported_numbers(pct_ans, pct_src) == []
    assert "Đối với [TASK]" not in clean("Đối với [TASK] 'Hạ tầng CNTT': Ngân sách 8.400 triệu (xem Task T2 và T3).")

    # Số bịa vẫn phải bị bắt chặt!
    fake_ans = "Nhân viên bị trừ 3 lần × 250.000 VNĐ = 750.000 VNĐ."
    fake_bad = unsupported_numbers(fake_ans, sources)
    assert "250000" in fake_bad and "750000" in fake_bad


# 5. Doc Type — File Excel tài chính (kể cả có dòng "ký mới 11 hợp đồng B2B") không bị nhận nhầm là Hợp đồng
def test_financial_excel_not_classified_as_contract():
    excel_text = (
        "## KetQua_KinhDoanh_Q4\n"
        "Tháng | Doanh thu thuần (triệu VNĐ) | Chi phí hoạt động | Chi phí Cloud & GPU | Lợi nhuận | Ghi chú\n"
        "Tháng 10/2025 | 5200 | 3500 | 450 | 1700 | Triển khai 4 khách hàng\n"
        "Tháng 11/2025 | 5800 | 3900 | 500 | 1900 | Tăng tải truy vấn AI\n"
        "Tháng 12/2025 | 7000 | 4600 | 550 | 2400 | Tháng doanh thu cao nhất quý (ký mới 11 hợp đồng B2B)\n"
        "TỔNG Q4/2025 | 18000 | 12000 | 1500 | 6000 | Biên lợi nhuận 33,33%\n"
    )
    dtype = classify_document("02_Bao_Cao_Tai_Chinh_va_Marketing_Q4_2025_VietCore.xlsx", excel_text)
    assert dtype != "contract"


def test_hybrid_tokens_splits_snake_case_filenames_and_sheets():
    from app.retrieval.hybrid import tokens
    toks = set(tokens("02_Bao_Cao_Tai_Chinh_va_Marketing_Q4_2025_VietCore.xlsx"))
    assert {"bao_cao", "cao", "tai", "chinh", "marketing", "q4", "2025", "vietcore"}.issubset(toks)
    # Tách CamelCase cho tên Sheet Excel tiếng Việt
    sheet_toks = set(tokens("## NganSach_2026\n## KetQua_KinhDoanh_Q4\n## HieuQua_QuangCao_Q4"))
    assert {"ngan", "sach", "ngan_sach", "kinh", "doanh", "quang", "cao", "2026", "q4"}.issubset(sheet_toks)
    # Vẫn giữ nguyên định danh kỹ thuật ngắn như user_id
    assert "user_id" in set(tokens("Cột user_id trong bảng orders"))


# 6. Source Focus — Câu hỏi năm 2026 không loại file Báo cáo Tài chính Q4/2025 khác chủ đề
def test_year_filter_only_excludes_same_family_older_version():
    titles = {
        "s1": "01_Quy_Che_Nhan_Su_va_Phuc_Loi_VietCore_2026.docx",
        "s2": "02_Bao_Cao_Tai_Chinh_va_Marketing_Q4_2025_VietCore.xlsx",
        "s3": "01_Quy_Che_Nhan_Su_va_Phuc_Loi_VietCore_2024.docx",
    }
    # Quy chế 2024 cùng họ với Quy chế 2026 -> phải bị loại khi hỏi năm 2026
    assert has_same_family_for_years(titles["s3"], titles, {"2026"}, exclude_sid="s3") is True
    # Báo cáo Tài chính Q4/2025 khác họ hoàn toàn -> KHÔNG bị loại khi hỏi năm 2026
    assert has_same_family_for_years(titles["s2"], titles, {"2026"}, exclude_sid="s2") is False

    chunks = [
        SourceChunk("s1_c0", "s1", titles["s1"], "# QUY CHẾ NHÂN SỰ VIETCORE 2026\nNghỉ phép năm 14 ngày.", 0),
        SourceChunk("s2_c0", "s2", titles["s2"], "# BÁO CÁO TÀI CHÍNH VÀ MARKETING Q4/2025\nKế hoạch ngân sách 2026: 24.000 triệu.", 0),
    ]
    focused = focus_sources("Kế hoạch ngân sách năm 2026 và Báo cáo Tài chính Marketing của VietCore", chunks, None)
    assert focused is None or "s2" in focused


# 7. Knowledge Source — Q8 (hỏi đích danh VietCore AI / công ty) phải doc_bound=True, câu phổ thông vẫn False
def test_doc_bound_catches_company_entity_without_blocking_general_questions():
    corpus = [
        "01_Quy_Che_Nhan_Su_va_Phuc_Loi_VietCore_2026.docx",
        "02_Bao_Cao_Tai_Chinh_va_Marketing_Q4_2025_VietCore.xlsx",
        "03_Kien_Truc_Nen_Tang_va_SLA_VietCore_v4.md",
        "04_Chien_Luoc_Thi_Truong_va_Dao_Tao_AI_2026_VietCore.pdf",
    ]
    q8 = "Hãy cho tôi biết tỷ lệ chia cổ tức bằng tiền mặt năm 2026 của VietCore AI và danh sách 3 đối tác ngân hàng cho vay vốn của công ty?"
    assert doc_bound(q8, corpus_names=corpus) is True
    assert doc_bound("Thủ đô của Úc là gì?", corpus_names=corpus) is False


# 8. Simple routing — Q3 gọn 1 chủ đề đi nhánh nhanh, Q6/Q7 đa ý đánh số đi nhánh đa tác tử
def test_routing_simple_vs_complex_v9():
    q3 = (
        "Một nhân viên chính thức tại VietCore AI đạt KPI bậc A (84 điểm) và trong tháng đi muộn quá 15 phút "
        "tổng cộng 5 lần không báo trước. Hãy cho biết mức thưởng KPI cuối năm và số tiền bị trừ vào phụ cấp "
        "chuyên cần trong tháng đó."
    )
    assert is_simple_project_question(q3, ["hr"]) is True
    assert is_simple_project_question(q3, ["conditions", "figures"]) is True

    q7 = (
        "Dựa trên các tài liệu hiện có của VietCore AI, hãy cho biết: "
        "(1) Tổng doanh thu thuần và lợi nhuận trước thuế Quý IV/2025 là bao nhiêu? "
        "(2) Chính sách bảo hiểm sức khỏe cho người thân nhân viên và mức phụ cấp ăn trưa hằng tháng năm 2026 là bao nhiêu?"
    )
    assert is_simple_project_question(q7, ["finance", "hr"]) is False


# 9. Multi-Task Completeness Guard — chống recency bias bỏ sót các trụ cột đầu khi tổng hợp >= 3 tasks
def test_synthesizer_completeness_guard_recovers_dropped_pillars():
    import asyncio
    import json
    from app.core.types import RunMetrics, TaskResult, Usage
    from app.research.synthesizer import synthesize

    class _RecencyBiasStub:
        supports_per_call_output_tokens = True

        async def generate_structured(self, **_kw):
            # Giả lập mô hình 4B chỉ viết mỗi task cuối cùng (bỏ quên 3 task đầu)
            return SimpleNamespace(
                text=json.dumps({"answer": "Khuyến nghị rủi ro ưu tiên Quý I: lắp đặt GPU tránh phát sinh 375 triệu/tháng."}, ensure_ascii=False),
                usage=Usage(input_tokens=100, output_tokens=30),
            )

    results = [
        TaskResult("T1", "finance", "COMPLETE", "Doanh thu mục tiêu 90 tỷ VNĐ, tổng ngân sách 24.000 triệu VNĐ (Hạ tầng 8.400 triệu, Marketing 10.800 triệu).", ["s1_c0"], ["s1_c0"]),
        TaskResult("T2", "software", "COMPLETE", "SLA 2026 đạt Uptime 99,98%, P95 <= 2,0 giây, chứng nhận ISO/IEC 27001 Quý III/2026.", ["s2_c0"], ["s2_c0"]),
        TaskResult("T3", "hr", "COMPLETE", "Chương trình đào tạo AI 3 cấp tổng 1.260 triệu VNĐ trong ngân sách 2.400 triệu, ràng buộc 12 tháng.", ["s3_c0"], ["s3_c0"]),
        TaskResult("T4", "business", "COMPLETE", "Khuyến nghị rủi ro ưu tiên Quý I: lắp GPU sớm tránh phát sinh 375 triệu/tháng.", ["s4_c0"], ["s4_c0"]),
    ]
    ans = asyncio.run(
        synthesize(
            _RecencyBiasStub(),
            "Lập báo cáo 4 trụ cột: (1) Tài chính; (2) Hạ tầng; (3) Nhân sự; (4) Rủi ro.",
            results,
            RunMetrics(),
            reply_language="vi",
            max_output_tokens=1800,
        )
    )
    for must in ("90 tỷ", "8.400", "10.800", "99,98%", "1.260", "375"):
        assert must in ans, f"Thiếu nội dung trụ cột đã xác minh: {must}"
