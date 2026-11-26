"""Regression tests cho lỗi câu hỏi SLA 2026 bị đá sang luồng 8 bước, bỏ sót Uptime và cụt đuôi sau dấu ':'."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.core.answer_checks import clean
from app.core.types import RunMetrics, SourceChunk, TaskResult, Usage
from app.research.product_intents import is_simple_project_question
from app.research.synthesizer import synthesize
from app.retrieval.hybrid import continue_articles, fuse


def _chunk(src: str, idx: int, text: str) -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{src}_c{idx:04d}",
        source_id=src,
        source_name=src,
        text=text,
        index=idx,
        provenance={},
    )


def test_simple_question_cho_toi_biet_routes_to_simple():
    q_simple = (
        "Cho tôi biết cam kết SLA năm 2026 của NovaTech AI Platform v3.0 "
        "về độ khả dụng Uptime, độ trễ P95 truy vấn đơn giản và chuẩn mã hóa dữ liệu."
    )
    assert is_simple_project_question(q_simple, ["software"]) is True

    q_complex = (
        "Hãy phân tích và so sánh hiệu quả chi phí hạ tầng Cloud năm 2026 "
        "với phương án đầu tư cụm GPU nội bộ."
    )
    assert is_simple_project_question(q_complex, ["software", "finance"]) is False


def test_hybrid_fuse_prioritizes_rare_term_and_markdown_heading_continuation():
    c1 = _chunk("03_Kien_Truc.md", 0, "# ĐẶC TẢ KIẾN TRÚC HỆ THỐNG NOVATECH AI PLATFORM v3.0\nTổng quan kiến trúc.")
    c2 = _chunk(
        "03_Kien_Truc.md",
        1,
        "1. Auth Gateway...\n2. Orchestrator...\n\n## 2. Cam kết chất lượng dịch vụ (SLA) & Bảo mật",
    )
    c3 = _chunk(
        "03_Kien_Truc.md",
        2,
        "| Chỉ số kỹ thuật | Mục tiêu cam kết SLA 2026 |\n"
        "| Độ khả dụng hệ thống (Uptime) | **99,95%** |\n"
        "| Độ trễ P95 — Truy vấn đơn giản | **<= 2,5 giây** |\n"
        "| Chuẩn mã hóa dữ liệu | **TLS 1.3** & **AES-256** |",
    )
    noise = _chunk("01_Nhan_Su.docx", 0, "# SỔ TAY NHÂN SỰ NOVATECH 2026\nPhụ cấp chuyên cần và nghỉ phép năm.")
    all_chunks = [c1, c2, c3, noise]

    # 1. continue_articles phải tự kéo đoạn bảng c3 ngay sau tiêu đề Markdown ## 2. ở cuối c2
    pulled = continue_articles([c2], all_chunks)
    assert [c.chunk_id for c in pulled] == [c2.chunk_id, c3.chunk_id]

    # 2. Truy vấn theo từng chỉ số SLA phải đưa c3 lên hạng đầu (không bị file nhân sự hay tiêu đề chung đè)
    for q in ("cam kết SLA năm 2026 độ khả dụng Uptime", "độ trễ P95 truy vấn đơn giản", "chuẩn mã hóa dữ liệu TLS AES"):
        out, _ = fuse(q, all_chunks, [], top_k=3)
        assert out[0].chunk_id == c3.chunk_id


def test_clean_chunk_id_junk_does_not_wipe_following_content():
    raw = (
        "Dưới đây là chi tiết:\n\n"
        "Các chunk ID liên quan:\n"
        "- src_abc123_c0002\n\n"
        "| Chỉ số | Giá trị |\n| Uptime | 99,95% |"
    )
    cleaned = clean(raw)
    assert "99,95%" in cleaned and "Uptime" in cleaned


def test_synthesizer_repairs_dangling_colon_ending():
    class _TruncatedStub:
        supports_per_call_output_tokens = True

        async def generate_structured(self, **_kw):
            return SimpleNamespace(
                text=json.dumps(
                    {"answer": "Dưới đây là chi tiết theo tài liệu đã xác minh:"},
                    ensure_ascii=False,
                ),
                usage=Usage(input_tokens=50, output_tokens=20),
            )

    tr = TaskResult(
        task_id="T1",
        domain="software",
        status="COMPLETE",
        answer="Độ khả dụng hệ thống (Uptime) là 99,95% [src_03_c0002].",
        evidence_ids=["src_03_c0002"],
        citations=["src_03_c0002"],
    )
    ans = asyncio.run(
        synthesize(
            _TruncatedStub(),
            "Cho tôi biết cam kết SLA năm 2026.",
            [tr],
            RunMetrics(),
            reply_language="vi",
            max_output_tokens=1800,
        )
    )
    assert not ans.rstrip().endswith(":")
    assert "99,95%" in ans


def test_single_domain_two_question_marks_routes_to_simple():
    """Câu 1A (2 dấu '?' nhưng cùng 1 chủ đề HR) phải đi nhánh nhanh thay vì luồng 8 bước."""
    q_1a = (
        "Nhân viên chính thức của NovaTech VN được hưởng bao nhiêu ngày nghỉ phép năm? "
        "Nếu làm đủ 6 năm thâm niên thì được tổng cộng bao nhiêu ngày và phép tồn được "
        "chuyển sang năm sau tối đa mấy ngày?"
    )
    assert is_simple_project_question(q_1a, ["hr"]) is True

    # Câu nhiều lĩnh vực có 2 dấu '?' vẫn phải đi nhánh phức tạp
    q_multi = (
        "Mức thưởng KPI bậc A là bao nhiêu? "
        "Đồng thời hãy phân tích ngân sách Marketing Q4/2025 và đề xuất tái phân bổ?"
    )
    assert is_simple_project_question(q_multi, ["hr", "marketing", "finance"]) is False


def test_answer_checks_accepts_verified_inline_arithmetic():
    """Số kết quả phép tính hợp lệ (14 = 12 + 2; 120.000 = (5 - 3) * 60.000) không bị báo oan, số bịa vẫn bị bắt."""
    from app.core.answer_checks import unsupported_numbers

    # Ca 1A: nguồn có 12 ngày, cứ 3 năm thêm 1 ngày, câu hỏi có 6 năm -> 6 // 3 = 2, 12 + 2 = 14
    sources_1a = (
        "Nhân viên chính thức được 12 ngày phép năm. Cứ 3 năm thâm niên cộng 1 ngày. Tối đa chuyển 4 ngày. "
        "Làm đủ 6 năm được bao nhiêu ngày phép?"
    )
    ans_1a = "Thâm niên 6 // 3 = 2 ngày. Tổng số ngày phép sau 6 năm là 12 + 2 = 14 ngày (chuyển tối đa 4 ngày)."
    assert unsupported_numbers(ans_1a, sources_1a) == []

    # Ca 2A: nguồn có quá 3 lần, mỗi lần 60.000 VNĐ; câu hỏi 5 lần -> (5 - 3) * 60000 = 120.000
    sources_2a = (
        "Đi muộn quá 3 lần/tháng bị trừ 5% phụ cấp (60.000 VNĐ) cho mỗi lần tiếp theo. "
        "Đi muộn 5 lần bị trừ bao nhiêu tiền?"
    )
    ans_2a = "Vượt 5 - 3 = 2 lần nên bị trừ (5 - 3) × 60.000 = 120.000 VNĐ."
    assert unsupported_numbers(ans_2a, sources_2a) == []

    # Số bịa (không nằm trong nguồn, câu hỏi hay phép tính hợp lệ) vẫn phải bị phát hiện!
    ans_fake = "Nhân viên được thưởng thêm 950.000 VNĐ."
    assert "950000" in unsupported_numbers(ans_fake, sources_2a)


def test_product_fallback_plan_builds_valid_tasks_for_complex_four_pillar_request():
    """Câu 5A (4 trụ cột rất khó) khi planner bị reject ở product_mode vẫn phải dựng được kế hoạch dự phòng an toàn."""
    from app.core.types import Obligation
    from app.research.pipeline import _product_fallback_plan

    query = (
        "Lập Báo cáo Thẩm định Kế hoạch Tổng thể 2026 trên 4 trụ cột: "
        "Tài chính 20 tỷ, Hạ tầng CNTT & SLA/ISO 27001, Nhân sự & đào tạo AI 3 cấp, Rủi ro Q1/2026."
    )
    extraction = SimpleNamespace(
        obligations=[
            Obligation(obligation_id="O1", description="Thẩm định tài chính và ngân sách 20 tỷ năm 2026"),
            Obligation(obligation_id="O2", description="Đánh giá hạ tầng CNTT, SLA và mốc ISO 27001"),
            Obligation(obligation_id="O3", description="Đối chiếu nhân sự và đào tạo AI 3 cấp độ"),
            Obligation(obligation_id="O4", description="Tổng hợp rủi ro ưu tiên triển khai Quý I/2026"),
        ],
        concerns=[],
    )
    plan = _product_fallback_plan(query, extraction, candidate=None)
    assert len(plan.tasks) == 4
    assert all(t.evidence_needs for t in plan.tasks)
    assert all(t.task_id for t in plan.tasks)
