"""Test-First RED->GREEN suite for B139.2F3: Conditional Evidence, Approval Authority & Verified Consistency.

All tests run 100% offline (Zero LLM / FakeProvider / APP_STORAGE_BACKEND=file) on raw document text.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest

from app.core.answer_checks import IMG_MARK, check_product_evidence_claims
from app.core.formula_engine import CalcStatus, execute_formula, select_formula
from app.core.operand_grounding import ground_operand
from app.core.structured_evidence import extract_structured_evidence
from app.core.types import SourceChunk
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.progress import progress_sink
from app.research.verified_reasoning import verify_and_reconcile_answer
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


# ---------------------------------------------------------------------------
# Raw real-world fixtures (exact reproductions from B139.2O-R & unseen domains)
# ---------------------------------------------------------------------------

RAW_HA_02_C0000 = """# SỔ TAY PHÒNG KINH DOANH 2026
## 2. Bảng giá niêm yết 2026 (chưa gồm VAT)

| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí triển khai một lần |
|---|---|---|---|---|
| HA-Edu | Trường dưới 3.000 sinh viên | 120.000.000 đ | năm | 30.000.000 đ |
| HA-Edu | Trường từ 3.000 sinh viên | 260.000.000 đ | năm | 50.000.000 đ |"""

RAW_HA_02_C0002 = """## 4. Chính sách chiết khấu và thẩm quyền phê duyệt

| Mức chiết khấu trên giá niêm yết | Người phê duyệt |
|---|---|
| Đến 10% | Nhân viên Kinh doanh tự quyết |
| Trên 10% đến 20% | Trưởng phòng Kinh doanh |
| Trên 20% đến 30% | Giám đốc Kinh doanh |
| Trên 30% | Tổng Giám đốc |

- Khách hàng là trường đại học công lập được thêm 5% (cộng dồn, không vượt 30%).
- Hợp đồng 3 năm trả trước được giảm thêm 8% cho năm thứ hai và thứ ba.
- Không chiết khấu phí triển khai, trừ khi Tổng Giám đốc duyệt."""

RAW_BLLD_C0089 = """Điều 98. Tiền lương làm thêm giờ, làm việc vào ban đêm
1. Người lao động làm thêm giờ được trả lương tính theo đơn giá tiền lương hoặc tiền lương thực trả theo công việc đang làm như sau:
a) Vào ngày thường, ít nhất bằng 150%;
b) Vào ngày nghỉ hằng tuần, ít nhất bằng 200%;
c) Vào ngày nghỉ lễ, tết, ngày nghỉ có hưởng lương, ít nhất bằng 300% chưa kể tiền lương ngày lễ, tết, ngày nghỉ có hưởng lương đối với người lao động hưởng lương ngày."""

RAW_BLLD_C0093 = """2. Quy chế thưởng do người sử dụng lao động quyết định.
Điều 105. Thời giờ làm việc bình thường
1. Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày và không quá 48 giờ trong 01 tuần.
2. Người sử dụng lao động có quyền quy định thời giờ làm việc theo ngày hoặc tuần nhưng phải thông báo cho người lao động biết; trường hợp theo tuần thì thời giờ làm việc bình thường không quá 10 giờ trong 01 ngày và không quá 48 giờ trong 01 tuần.
Nhà nước khuyến khích người sử dụng lao động thực hiện tuần làm việc 40 giờ đối với người lao động."""

RAW_HA_08_C0000 = """## Lam_them
Họ tên | Số tháng làm việc | Lương giờ (đồng) | Giờ làm thêm ngày thường | Giờ ngày nghỉ tuần | Giờ ngày lễ | Ngày phép đã nghỉ
Phạm Minh Hải | 17 | 67308 | 6 | 8 | 0 | 4
Trần Thu Hà | 62 | 84135 | 10 | 0 | 8 | 7"""

RAW_HA_01_C0003 = """4. Người lao động gửi đơn nghỉ phép trên hệ thống trước ít nhất 03 ngày làm việc. Nghỉ từ 05 ngày liên tiếp trở lên phải được Trưởng phòng và Giám đốc Nhân sự phê duyệt."""

RAW_HA_02_C0003 = """## 6. Nghỉ phép và trực bán hàng của phòng Kinh doanh
- Do đặc thù chăm sóc khách hàng, nhân viên Kinh doanh gửi đơn nghỉ phép trước ít nhất 05 ngày làm việc và phải bàn giao danh sách khách hàng đang theo dõi cho người trực thay.
- Mùa cao điểm tuyển sinh và quyết toán (tháng 8 đến tháng 10, tháng 12) hạn chế nghỉ phép quá 03 ngày liên tiếp."""


def _ch(cid: str, sid: str, text: str, *, doc_type: str = "policy", name: str = "doc.md") -> SourceChunk:
    return SourceChunk(cid, sid, name, text, 0, provenance={"doc_type": doc_type})


# ===========================================================================
# 1. FIX-01: Conditional Approval Authority (R-01, G-01, Unseen VN/EN, ACL)
# ===========================================================================

def test_fix01_r01_reconciles_wrong_approver_and_keeps_297m() -> None:
    chunks = [
        _ch("src_79ae8c1e4c8cbd14_c0000", "src_79ae8c1e4c8cbd14", RAW_HA_02_C0000, doc_type="contract"),
        _ch("src_79ae8c1e4c8cbd14_c0002", "src_79ae8c1e4c8cbd14", RAW_HA_02_C0002, doc_type="contract"),
    ]
    q = (
        "Trường đại học công lập mua gói HA-Edu cho 3.500 sinh viên và ký hợp đồng 1 năm "
        "(không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm phí triển khai là bao nhiêu "
        "và ai phê duyệt mức chiết khấu này?"
    )
    wrong_llm = (
        "Tổng tiền năm đầu gồm phí triển khai là 260.000.000 đ + 50.000.000 đ = 310.000.000 đ. "
        "Mức chiết khấu được phê duyệt bởi Giám đốc Kinh doanh. [src_79ae8c1e4c8cbd14_c0000]"
    )
    out = verify_and_reconcile_answer(query=q, chunks=chunks, llm_answer=wrong_llm)
    ans = out["final_answer"]
    assert "297.000.000" in ans
    assert "Nhân viên Kinh doanh tự quyết" in ans
    assert "Giám đốc Kinh doanh" not in ans
    assert out["contradicted_llm"] is True


def test_fix01_g01_reconciles_4000_students_wrong_approver() -> None:
    chunks = [
        _ch("src_79ae8c1e4c8cbd14_c0000", "src_79ae8c1e4c8cbd14", RAW_HA_02_C0000, doc_type="contract"),
        _ch("src_79ae8c1e4c8cbd14_c0002", "src_79ae8c1e4c8cbd14", RAW_HA_02_C0002, doc_type="contract"),
    ]
    q = (
        "Trường đại học Bách Khoa Miền Trung là trường công lập muốn mua gói HA-Edu cho 4.000 sinh viên "
        "và ký hợp đồng 1 năm (không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm phí triển khai "
        "là bao nhiêu và ai phê duyệt mức chiết khấu này?"
    )
    wrong_llm = (
        "Tổng cộng cho 4.000 sinh viên là 310.478.564,31 đ. "
        "Mức chiết khấu này được phê duyệt bởi Giám đốc Kinh doanh."
    )
    out = verify_and_reconcile_answer(query=q, chunks=chunks, llm_answer=wrong_llm)
    ans = out["final_answer"]
    assert "297.000.000" in ans
    assert "310.478.564" not in ans
    assert "Nhân viên Kinh doanh tự quyết" in ans
    assert "Giám đốc Kinh doanh" not in ans


def test_fix01_unseen_vn_saas_upper_tier_authority() -> None:
    raw = """# CHÍNH SÁCH BÁN HÀNG CLOUDOPS 2027
| Hạng mục | Đơn giá | Phí cài đặt |
|---|---|---|
| Gói Team | 100.000.000 đ | 10.000.000 đ |

- Đối tác chiến lược được chiết khấu 18% trên đơn giá; không giảm phí cài đặt.

| Mức chiết khấu | Cấp phê duyệt |
|---|---|
| Đến 10% | Chuyên viên Kinh doanh tự quyết |
| Trên 10% đến 20% | Trưởng bộ phận Thương mại |
| Trên 20% | Phó Tổng Giám đốc |"""
    chunks = [_ch("c_saas_0", "s_saas", raw)]
    q = "Đối tác chiến lược mua Gói Team kèm phí cài đặt hết bao nhiêu tiền và ai phê duyệt mức chiết khấu?"
    wrong_llm = "Tổng cộng 92.000.000 đ, do Chuyên viên Kinh doanh tự quyết."
    out = verify_and_reconcile_answer(query=q, chunks=chunks, llm_answer=wrong_llm)
    ans = out["final_answer"]
    assert "92.000.000" in ans
    assert "Trưởng bộ phận Thương mại" in ans
    assert "Chuyên viên Kinh doanh tự quyết" not in ans


def test_fix01_en_original_price_vs_final_amount_threshold() -> None:
    from app.core.approval_authority import resolve_approval_authority

    raw = """# PROCUREMENT POLICY 2027
| Original List Price | Approving Authority |
|---|---|
| Up to $10,000 | Team Lead (self-authorized) |
| Above $10,000 to $50,000 | Procurement Director |
| Above $50,000 | Chief Financial Officer |

| Final Contract Value | Approving Authority |
|---|---|
| Up to $10,000 | Operations Lead |
| Above $10,000 | VP Finance |"""
    chunks = [_ch("c_en_0", "s_en", raw)]
    res_orig = resolve_approval_authority(
        "If original list price is $12,000 and final contract value after discount is $9,500, who approves?",
        chunks,
        calc_context={"base": Decimal("12000"), "total": Decimal("9500"), "currency": "USD"},
    )
    assert res_orig.status == "VERIFIED"
    assert "Procurement Director" in res_orig.authority or "Operations Lead" in res_orig.authority
    # Explicitly verify threshold on original list price resolves to Procurement Director
    res_list_only = resolve_approval_authority(
        "Who approves an item with original list price $12,000?",
        [_ch("c_en_1", "s_en1", raw.split("| Final Contract Value")[0])],
        calc_context={"base": Decimal("12000"), "currency": "USD"},
    )
    assert res_list_only.status == "VERIFIED"
    assert res_list_only.metric_kind == "original_price"
    assert "Procurement Director" in res_list_only.authority


def test_fix01_sequential_approval_and_fixed_fee_exception() -> None:
    from app.core.approval_authority import resolve_approval_authority

    chunks = [_ch("src_79ae8c1e4c8cbd14_c0002", "src_79ae8c1e4c8cbd14", RAW_HA_02_C0002)]
    res_exc = resolve_approval_authority(
        "Khách hàng xin chiết khấu phí triển khai thì ai duyệt?",
        chunks,
        calc_context={"discount_pct": Decimal("5")},
    )
    assert res_exc.status == "VERIFIED"
    assert "Tổng Giám đốc" in res_exc.authority

    seq_raw = """## Quy trình phê duyệt hợp đồng vượt khung
- Hợp đồng trên 500.000.000 đ phải được Trưởng phòng Pháp chế và Giám đốc Tài chính phê duyệt theo thứ tự."""
    res_seq = resolve_approval_authority(
        "Hợp đồng giá trị 600.000.000 đ cần ai phê duyệt?",
        [_ch("c_seq", "s_seq", seq_raw)],
        calc_context={"total": Decimal("600000000"), "currency": "VND"},
    )
    assert res_seq.status == "VERIFIED"
    assert len(res_seq.sequential_roles) >= 2
    assert any("Pháp chế" in r for r in res_seq.sequential_roles)
    assert any("Tài chính" in r for r in res_seq.sequential_roles)


def test_fix01_missing_threshold_metric_and_acl_blocked() -> None:
    from app.core.approval_authority import resolve_approval_authority

    chunks = [_ch("src_79ae8c1e4c8cbd14_c0002", "src_79ae8c1e4c8cbd14", RAW_HA_02_C0002)]
    res_missing = resolve_approval_authority("Ai phê duyệt mức chiết khấu này?", chunks, calc_context={})
    assert res_missing.status == "UNKNOWN"
    assert res_missing.missing_condition

    res_acl = resolve_approval_authority(
        "Ai phê duyệt mức chiết khấu 5%?",
        chunks,
        allowed_source_ids={"other_allowed_src"},
        calc_context={"discount_pct": Decimal("5")},
    )
    assert res_acl.status == "UNKNOWN"


# ===========================================================================
# 2. FIX-02: Conditional Working-Hour Disambiguation (R-03, Actual vs Statutory)
# ===========================================================================

def test_fix02_c0093_disambiguates_daily_8_and_weekly_10_without_unconditional_conflict() -> None:
    chunks = [_ch("src_1791660bc8f54d33_c0093", "src_1791660bc8f54d33", RAW_BLLD_C0093, doc_type="legal_doc")]
    items = extract_structured_evidence(chunks)
    hpds = [i for i in items if i.attribute == "hours_per_day"]
    assert {int(i.value) for i in hpds} == {8, 10}
    it8 = next(i for i in hpds if int(i.value) == 8)
    it10 = next(i for i in hpds if int(i.value) == 10)
    assert "statutory_max" in it8.applicable_conditions
    assert "statutory_max" in it10.applicable_conditions
    assert "weekly_schedule" in it10.applicable_conditions
    assert "weekly_schedule" not in it8.applicable_conditions

    # Grounding for weekly schedule selects 10 (not unconditional conflict!)
    g_week = ground_operand(items, attribute="hours_per_day", target_unit="hour/day", active_conditions=["weekly_schedule"])
    assert g_week.status == "VALIDATED"
    assert int(g_week.operand_value) == 10


def test_fix02_r03_with_ha08_direct_hourly_rate_computes_verified_total() -> None:
    chunks = [
        _ch("src_f4d8c24ed56dead2_c0000", "src_f4d8c24ed56dead2", RAW_HA_08_C0000, doc_type="other"),
        _ch("src_1791660bc8f54d33_c0089", "src_1791660bc8f54d33", RAW_BLLD_C0089, doc_type="legal_doc"),
        _ch("src_1791660bc8f54d33_c0093", "src_1791660bc8f54d33", RAW_BLLD_C0093, doc_type="legal_doc"),
    ]
    q = (
        "Tiền làm thêm tối thiểu của người này là bao nhiêu?\n\n"
        f"{IMG_MARK}\n"
        "BẢNG CHẤM CÔNG LÀM THÊM - THÁNG 11/2026\n"
        "Nhân viên: Trần Thu Hà - Lương 17.500.000 đ/tháng - 26 ngày công\n"
        "Làm thêm ngày thường: 10 giờ\nLàm thêm ngày nghỉ hằng tuần: 0 giờ\nLàm thêm ngày lễ: 8 giờ"
    )
    spec = select_formula(q, chunks=chunks)
    res = execute_formula(spec)
    assert res.status == CalcStatus.VERIFIED
    # Direct company table HA_08 gives 84.135 VND/hour -> 84135 * (10*1.5 + 8*3.0) = 3.281.265 VND
    assert res.value == Decimal("3281265")
    assert "3.281.265" in res.formatted_value


def test_fix02_r03_without_ha08_refuses_blind_8_from_statutory_max_and_flags_oracle_review() -> None:
    chunks = [
        _ch("src_1791660bc8f54d33_c0089", "src_1791660bc8f54d33", RAW_BLLD_C0089, doc_type="legal_doc"),
        _ch("src_1791660bc8f54d33_c0093", "src_1791660bc8f54d33", RAW_BLLD_C0093, doc_type="legal_doc"),
    ]
    q = (
        "Tiền làm thêm tối thiểu của người này là bao nhiêu?\n\n"
        f"{IMG_MARK}\n"
        "Nhân viên: Trần Thu Hà - Lương 17.500.000 đ/tháng - 26 ngày công\n"
        "Làm thêm ngày thường: 10 giờ\nLàm thêm ngày lễ: 8 giờ"
    )
    out = verify_and_reconcile_answer(
        query=q,
        chunks=chunks,
        llm_answer="Tổng tiền làm thêm là 3.281.250 đ.",
    )
    assert out["mode"] == "calculator_guarded"
    assert out["calc_status"] == CalcStatus.MISSING_OPERAND
    assert out.get("oracle_review_required") is True
    assert "actual_hours_per_day" in out["final_answer"] or "thời giờ làm việc thực tế" in out["final_answer"].casefold()
    assert "17.500.000" in out["final_answer"]  # Verified formula retained cleanly


def test_fix02_company_actual_hours_beats_statutory_max_and_weekly_10h_works() -> None:
    company_daily_8 = "Nội quy công ty: Thời giờ làm việc thực tế của nhân viên là 8 giờ/ngày."
    chunks_8 = [
        _ch("c_co8", "s_co8", company_daily_8),
        _ch("src_1791660bc8f54d33_c0089", "src_1791660bc8f54d33", RAW_BLLD_C0089, doc_type="legal_doc"),
        _ch("src_1791660bc8f54d33_c0093", "src_1791660bc8f54d33", RAW_BLLD_C0093, doc_type="legal_doc"),
    ]
    q = (
        "Tiền làm thêm của nhân viên là bao nhiêu?\n\n"
        f"{IMG_MARK}\n"
        "Lương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ\nLàm thêm ngày lễ: 8 giờ"
    )
    res_8 = execute_formula(select_formula(q, chunks=chunks_8))
    assert res_8.status == CalcStatus.VERIFIED
    assert abs(res_8.value - Decimal("3281250")) <= Decimal("1")

    company_weekly_10 = "Quy định ca theo tuần của xưởng sản xuất: thời giờ làm việc thực tế áp dụng theo tuần là 10 giờ/ngày."
    chunks_10 = [
        _ch("c_co10", "s_co10", company_weekly_10),
        _ch("src_1791660bc8f54d33_c0089", "src_1791660bc8f54d33", RAW_BLLD_C0089, doc_type="legal_doc"),
        _ch("src_1791660bc8f54d33_c0093", "src_1791660bc8f54d33", RAW_BLLD_C0093, doc_type="legal_doc"),
    ]
    q10 = (
        "Tiền làm thêm theo ca làm việc theo tuần là bao nhiêu?\n\n"
        f"{IMG_MARK}\n"
        "Lương 13.000.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 4 giờ"
    )
    res_10 = execute_formula(select_formula(q10, chunks=chunks_10))
    assert res_10.status == CalcStatus.VERIFIED
    # 13,000,000 / 26 / 10 * 4 * 1.5 = 300,000 (NOT 375,000 from /8!)
    assert res_10.value == Decimal("300000")


def test_fix02_en_contractual_7_5_hours_and_daily_salary_guard() -> None:
    en_doc = """Overtime policy: Weekday overtime rate is 150%.
Statutory cap: maximum 10 hours per day.
Company actual contractual shift: regular working schedule is 7.5 hours/day."""
    q_en = f"Calculate overtime pay:\n{IMG_MARK}\nDaily salary: 600,000 VND/day\nWeekday overtime: 3 hours"
    res_en = execute_formula(select_formula(q_en, chunks=[_ch("c_en_ot", "s_en_ot", en_doc)]))
    assert res_en.status == CalcStatus.VERIFIED
    assert res_en.value == Decimal("360000")  # (600,000 / 7.5) * 3 * 1.5 = 360,000

    stat_only = "Bộ luật: Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày. Làm thêm ngày thường ít nhất 150%."
    q_d = f"Tính tiền làm thêm:\n{IMG_MARK}\nLương ngày: 600.000 đ/ngày\nLàm thêm ngày thường: 2 giờ"
    res_d = execute_formula(select_formula(q_d, chunks=[_ch("c_st", "s_st", stat_only, doc_type="legal_doc")]))
    assert res_d.status == CalcStatus.MISSING_OPERAND


# ===========================================================================
# 3. FIX-03: Structured Final Answer Consistency (R-02 verbatim + English + Stream==Persisted)
# ===========================================================================

def test_fix03_r02_reconciles_verbatim_contradictory_middle_bullets() -> None:
    chunks = [
        _ch("src_00d7e739cefcc3c2_c0003", "src_00d7e739cefcc3c2", RAW_HA_01_C0003),
        _ch("src_79ae8c1e4c8cbd14_c0003", "src_79ae8c1e4c8cbd14", RAW_HA_02_C0003),
    ]
    q = (
        "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        f"{IMG_MARK}\n"
        "ĐƠN XIN NGHỈ PHÉP\n"
        "Người làm đơn: Phạm Minh Hải - Phòng Kinh doanh\n"
        "Ngày vào làm: 15/06/2025\n"
        "Xin nghỉ phép năm từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc)\n"
        "Ngày gửi đơn: thứ Năm 03/12/2026\n"
        "Người nhận bàn giao khách hàng: chưa có"
    )
    verbatim_b139_2or_llm = """Đơn nghỉ phép của Phạm Minh Hải (Phòng Kinh doanh) chưa đủ điều kiện kết luận đạt do còn điều kiện chưa thỏa mãn theo quy định của Công ty về nghỉ phép.

### Kiểm tra điều kiện nghỉ phép
1. **Thời gian gửi đơn**: Người lao động phải gửi đơn nghỉ phép trên hệ thống trước ít nhất 03 ngày làm việc (Điều 6, Chương III, Nội quy lao động) [src_00d7e739cefcc3c2_c0003]. Trong đơn, ngày gửi đơn là thứ Năm 03/12/2026, và thời gian nghỉ phép từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc). Điều này đảm bảo đơn được gửi trước ít nhất 03 ngày làm việc (03/12 → 07/12 = 4 ngày làm việc).

2. **Bàn giao khách hàng**: Theo quy định, nhân viên Kinh doanh phải bàn giao danh sách khách hàng đang theo dõi cho người trực thay khi nghỉ phép [src_79ae8c1e4c8cbd14_c0003]. Trong đơn, người nhận bàn giao khách hàng được ghi là "chưa có", nhưng điều này **không thỏa mãn** nội quy vì quy định chỉ yêu cầu **bàn giao khi nghỉ phép** (không yêu cầu phải có người nhận cụ thể trước khi gửi đơn).

3. **Thời gian nghỉ phép**: Thời gian nghỉ phép từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc) phù hợp với quy định về nghỉ phép liên tiếp (không vượt quá 3 ngày liên tiếp trong mùa cao điểm tuyển sinh và quyết toán từ tháng 8 đến tháng 10, tháng 12)."""

    out = verify_and_reconcile_answer(query=q, chunks=chunks, llm_answer=verbatim_b139_2or_llm)
    ans = out["final_answer"]
    assert "NOT_ELIGIBLE" in ans
    assert "đảm bảo đơn được gửi trước" not in ans
    assert "không yêu cầu phải có người nhận cụ thể" not in ans
    assert "phù hợp với quy định về nghỉ phép liên tiếp" not in ans
    assert "[src_00d7e739cefcc3c2_c0003]" in ans
    assert "[src_79ae8c1e4c8cbd14_c0003]" in ans
    assert out["contradicted_llm"] is True
    assert out["structured_result"]["overall_verdict"] == "NOT_ELIGIBLE"


def test_fix03_general_lookup_not_forced_into_rigid_form() -> None:
    chunks = [_ch("c_nd", "s_nd", "Nghị định 13/2023/NĐ-CP: thông báo Bộ Công an chậm nhất 72 giờ; hiệu lực 01/07/2023.", doc_type="legal_doc")]
    q = "Theo Nghị định 13/2023/NĐ-CP chậm nhất bao nhiêu giờ phải thông báo cho Bộ Công an?"
    llm = "Chậm nhất **72 giờ** phải thông báo cho Bộ Công an [c_nd]."
    out = verify_and_reconcile_answer(query=q, chunks=chunks, llm_answer=llm)
    assert out["mode"] == "bypassed_general_or_lookup"
    assert out["final_answer"] == llm


def test_fix03_stream_equals_final_equals_persisted_in_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", "on")

    sources = SourceStore(str(tmp_path / "data"))
    runs = RunStore(str(tmp_path / "runs"))
    s1 = sources.import_text("HA_01_Noi_quy.md", RAW_HA_01_C0003)
    s2 = sources.import_text("HA_02_Kinh_doanh.md", RAW_HA_02_C0003)
    cids = [c.chunk_id for c in sources.chunks([s1["source_id"], s2["source_id"]])]

    bad_json = json.dumps({
        "status": "COMPLETE",
        "answer": (
            f"Đơn nghỉ phép hợp lệ [{cids[0]}].\n"
            f"- Thời gian gửi đơn đảm bảo trước ít nhất 03 ngày làm việc [{cids[0]}].\n"
            f"- Thời gian nghỉ 5 ngày phù hợp với quy định về nghỉ phép liên tiếp [{cids[1]}]."
        ),
        "citations": cids,
    }, ensure_ascii=False)
    from unittest.mock import patch

    class _ContradictFakeProvider(FakeProvider):
        async def generate(self, *, system: str, user: str):
            marker = system.upper()
            if any(k in marker for k in ("WORKER", "SYNTHESIZER", "VANILLA_RAG_ANSWERER")):
                from app.core.types import ProviderResult, Usage
                if "SYNTHESIZER" in marker:
                    bad_syn = (
                        f"Đơn nghỉ phép hợp lệ [{cids[0]}].\n"
                        f"- Thời gian gửi đơn đảm bảo trước ít nhất 03 ngày làm việc [{cids[0]}].\n"
                        f"- Thời gian nghỉ 5 ngày phù hợp với quy định về nghỉ phép liên tiếp [{cids[1]}]."
                    )
                    return ProviderResult(text=bad_syn, usage=Usage(10, 10), request_id="fake_r02_s", model=self.model)
                return ProviderResult(text=bad_json, usage=Usage(10, 10), request_id="fake_r02_w", model=self.model)
            return await super().generate(system=system, user=user)

    fake = _ContradictFakeProvider()
    pipe = ResearchPipeline(sources, runs)

    q = (
        "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        f"{IMG_MARK}\n"
        "Ngày gửi đơn: thứ Năm 03/12/2026\n"
        "Xin nghỉ phép năm từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc)\n"
        "Người nhận bàn giao khách hàng: chưa có"
    )
    captured_chunks: list[str] = []

    async def _run():
        tok = progress_sink.set(lambda ev: captured_chunks.append(ev["text"]) if ev.get("type") == "answer" else None)
        try:
            with patch("app.research.pipeline.get_provider", return_value=fake):
                return await pipe.run(q, "C", "fake", product_mode=True)
        finally:
            progress_sink.reset(tok)

    run_rec = asyncio.run(_run())
    persisted = runs.get(run_rec["run_id"])
    streamed_text = captured_chunks[-1] if captured_chunks else ""
    assert streamed_text == run_rec["answer"] == persisted["answer"]
    assert "NOT_ELIGIBLE" in persisted["answer"]
    assert "đảm bảo trước ít nhất 03 ngày" not in persisted["answer"]
    assert "phù hợp với quy định về nghỉ phép liên tiếp" not in persisted["answer"]


# ===========================================================================
# 4. FIX-04: Warning Deduplication & Decimal/Locale Normalization
# ===========================================================================

def test_fix04_deduplicates_repeated_260_warning_and_preserves_distinct_warnings() -> None:
    inherited_with_dup = (
        "Giá gốc 260 triệu đồng [src_79ae8c1e4c8cbd14_c0000].\n\n"
        "> **Cần kiểm tra lại:** các con số 260 không có nguyên văn trong đoạn tài liệu đã dùng. Hãy bấm vào nguồn để đối chiếu."
    )
    _, ans1, bad1, _ = check_product_evidence_claims(
        "COMPLETE", inherited_with_dup, RAW_HA_02_C0000, "Tổng tiền?", []
    )
    _, ans2, _, _ = check_product_evidence_claims(
        "COMPLETE", ans1, RAW_HA_02_C0000, "Tổng tiền?", []
    )
    assert ans2.count("Cần kiểm tra lại:") == 1
    assert "260" in bad1

    # Distinct warnings (different unverified numbers AND unsupported article) MUST both be preserved!
    mixed = (
        "Theo Điều 99, giá gốc 260 triệu và phí thêm 777 đồng.\n\n"
        "> **Cần kiểm tra lại:** các con số 260 không có nguyên văn trong đoạn tài liệu đã dùng. Hãy bấm vào nguồn để đối chiếu."
    )
    _, ans_dist, _, arts_dist = check_product_evidence_claims(
        "COMPLETE", mixed, RAW_HA_02_C0000, "Tổng tiền?", []
    )
    assert "Điều 99" in ans_dist
    assert "777" in ans_dist
    assert len(arts_dist) == 1
    assert ans_dist.count("các con số 260 không có nguyên văn") <= 1


def test_fix04_decimal_locale_and_repeated_citations_regression() -> None:
    src = "Đơn giá: 36.000.000 đ (36000000). Phí kỹ sư: 6.000.000 đ. Tổng cộng 42.000.000 đ."
    ans = "Chi phí sau giảm là 36000000.0 đ [c1] [c1], tổng cộng 42.000.000 đ [c1]."
    _, out, bad, _ = check_product_evidence_claims("COMPLETE", ans, src, "Tổng chi phí?", [])
    assert "36000000" not in bad
    assert "Cần kiểm tra lại:" not in out


# ===========================================================================
# 5. Held-out Unfamiliar Domains & Negative/Ambiguous Matrix (>= 24 scenarios total)
# ===========================================================================

@pytest.mark.parametrize(
    "domain_name,raw_doc,query,llm_ans,must_have,must_not_have",
    [
        (
            "VN_LOGISTICS_TIER_APPROVAL",
            """| Tuyến | Trọng lượng | Đơn giá | Phí niêm phong |
|---|---|---|---|
| Nội địa | Từ 5 tấn trở lên | 20.000.000 đ | 2.000.000 đ |
- Khách hàng VIP giảm 12% trên đơn giá; không giảm phí niêm phong.
| Mức chiết khấu | Người phê duyệt |
|---|---|
| Đến 10% | Điều phối viên tự quyết |
| Trên 10% đến 20% | Trưởng phòng Vận tải |""",
            "Khách hàng VIP gửi lô hàng 6 tấn tuyến Nội địa kèm phí niêm phong tổng tiền bao nhiêu và ai phê duyệt chiết khấu?",
            "Tổng tiền là 22.000.000 đ, do Điều phối viên tự quyết.",
            ["19.600.000", "Trưởng phòng Vận tải"],
            ["Điều phối viên tự quyết"],
        ),
        (
            "EN_RETAIL_DISCOUNT_SELF_AUTH",
            """| Plan | Tier | Unit Price | Setup Fee |
|---|---|---|---|
| POS-Pro | Up to 10 stores | $5,000 | $500 |
- Non-profit buyer receives 8% discount on unit price; setup fee excluded.
| Discount Rate | Approving Authority |
|---|---|
| Up to 10% | Account Executive (self-authorized) |
| Above 10% | Regional VP |""",
            "Non-profit buyer orders POS-Pro for 5 stores including setup fee: what is total cost and who approves the discount?",
            "Total is $5,500, approved by Regional VP.",
            ["5.100", "Account Executive"],
            ["Regional VP"],
        ),
        (
            "VN_CLINIC_OVERTIME_ACTUAL_7H",
            """Quy chế phòng khám: Thời giờ làm việc thực tế của điều dưỡng là 7 giờ/ngày.
Điều 98: Làm thêm ngày thường ít nhất 150%.""",
            f"Tính tiền làm thêm:\n{IMG_MARK}\nLương 14.000.000 đ/tháng - 25 ngày công\nLàm thêm ngày thường: 5 giờ",
            "Tiền làm thêm: 500.000 đ.",
            ["600.000"],
            ["500.000"],
        ),
        (
            "EN_TRAVEL_EXPENSE_PROSE_CONSISTENCY",
            """Travel policy: Expense requests must be submitted at least 05 working days prior and must include receipt handoff.
Requests above 3 days during peak month 12 are restricted.""",
            f"Is this expense request compliant?\n{IMG_MARK}\nSubmitted: 03/12/2026\nTrip: 07/12/2026 to 11/12/2026 (5 working days)\nHandoff: chưa có",
            "The request is compliant.\n- Thời gian gửi đơn đảm bảo trước ít nhất 05 ngày làm việc.\n- Bàn giao chưa có nhưng không sao.",
            ["NOT_ELIGIBLE"],
            ["đảm bảo trước ít nhất 05 ngày"],
        ),
    ],
)
def test_heldout_generalization_unseen_domains(
    domain_name: str,
    raw_doc: str,
    query: str,
    llm_ans: str,
    must_have: list[str],
    must_not_have: list[str],
) -> None:
    chunks = [_ch(f"c_{domain_name}", f"s_{domain_name}", raw_doc)]
    out = verify_and_reconcile_answer(query=query, chunks=chunks, llm_answer=llm_ans)
    ans = out["final_answer"]
    for token in must_have:
        assert token in ans, f"[{domain_name}] expected {token!r} in:\n{ans}"
    for bad_tok in must_not_have:
        assert bad_tok not in ans, f"[{domain_name}] unexpected {bad_tok!r} in:\n{ans}"


def test_fix03_eligible_leave_preserves_positive_explanation() -> None:
    # 1. Eligible leave case (all conditions MET) preserves positive explanation
    rule_doc = """- Nhân viên gửi đơn nghỉ phép trước ít nhất 03 ngày làm việc và phải bàn giao công việc cho người trực thay.
- Nghỉ từ 05 ngày liên tiếp trở lên phải được Trưởng phòng phê duyệt."""
    q_ok = (
        "Đơn này có đúng quy định không?\n\n"
        f"{IMG_MARK}\n"
        "Ngày gửi đơn: 01/12/2026\n"
        "Xin nghỉ phép năm từ 10/12/2026 đến 12/12/2026 (3 ngày làm việc)\n"
        "Người nhận bàn giao khách hàng: Nguyễn Văn A"
    )
    ok_llm = "Đơn nghỉ phép hợp lệ và đảm bảo gửi trước 03 ngày làm việc [c_ok]."
    out_ok = verify_and_reconcile_answer(query=q_ok, chunks=[_ch("c_ok", "s_ok", rule_doc)], llm_answer=ok_llm)
    assert "NOT_ELIGIBLE" not in out_ok["final_answer"]
    assert "đảm bảo gửi trước 03 ngày làm việc" in out_ok["final_answer"]


def test_fix01_acl_unauthorized_source_blocked() -> None:
    # 2. Unauthorized source must NOT resolve approval authority
    priv_auth = """| Mức chiết khấu | Người phê duyệt |
|---|---|
| Đến 10% | Chuyên viên tự quyết |"""
    out_acl = verify_and_reconcile_answer(
        query="Chiết khấu 5% thì ai phê duyệt?",
        chunks=[_ch("c_priv", "s_priv", priv_auth)],
        llm_answer="Chưa rõ.",
        allowed_source_ids={"s_other"},
    )
    assert "Chuyên viên tự quyết" not in out_acl["final_answer"]


def test_fix01_conflicting_approval_tables_return_conflict() -> None:
    # 3. Conflicting approval tables across two authorized docs -> CONFLICT / UNKNOWN (not blind pick)
    from app.core.approval_authority import resolve_approval_authority
    t1 = "| Mức chiết khấu | Người phê duyệt |\n|---|---|\n| Đến 10% | Trưởng nhóm |"
    t2 = "| Mức chiết khấu | Người phê duyệt |\n|---|---|\n| Đến 10% | Giám đốc |"
    res_conf = resolve_approval_authority(
        "Ai duyệt mức chiết khấu 5%?",
        [_ch("c1", "s1", t1), _ch("c2", "s2", t2)],
        calc_context={"discount_pct": Decimal("5")},
    )
    assert res_conf.status == "CONFLICT"


def test_fix02_hazardous_6h_vs_standard_8h_distinct() -> None:
    # 4. Working-time exception (hazardous work 6h/day statutory cap vs 8h/day standard) stays distinct
    raw_haz = """Điều 105: Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày.
Đối với người làm công việc đặc biệt nặng nhọc, độc hại, nguy hiểm: không quá 06 giờ trong 01 ngày."""
    items_haz = extract_structured_evidence([_ch("c_haz", "s_haz", raw_haz, doc_type="legal_doc")])
    g_std = ground_operand(items_haz, attribute="hours_per_day", target_unit="hour/day")
    g_haz = ground_operand(items_haz, attribute="hours_per_day", target_unit="hour/day", active_conditions=["hazardous_work"])
    assert int(g_std.operand_value) == 8
    assert int(g_haz.operand_value) == 6
    assert g_std.status == "VALIDATED" and g_haz.status == "VALIDATED"


def test_fix01_multi_document_pricing_and_approval() -> None:
    # 5. Multi-document pricing + approval across separate chunks (no single-chunk assumption)
    c_price = _ch("c_p", "s_p", "| Sản phẩm | Gói | Đơn giá | Phí cài đặt |\n|---|---|---|---|\n| ERP | Standard | 100.000.000 đ | 10.000.000 đ |")
    c_disc = _ch("c_d", "s_d", "- Cơ quan nhà nước được chiết khấu 15% trên đơn giá; không chiết khấu phí cài đặt.")
    c_appr = _ch("c_a", "s_a", "| Mức chiết khấu | Người phê duyệt |\n|---|---|\n| Đến 10% | Chuyên viên |\n| Trên 10% đến 20% | Giám đốc Khối |")
    out_multi = verify_and_reconcile_answer(
        query="Cơ quan nhà nước mua gói ERP Standard kèm phí cài đặt tổng tiền bao nhiêu và ai phê duyệt?",
        chunks=[c_price, c_disc, c_appr],
        llm_answer="Tổng tiền là 110.000.000 đ, do Chuyên viên phê duyệt.",
    )
    assert "95.000.000" in out_multi["final_answer"]
    assert "Giám đốc Khối" in out_multi["final_answer"]
    assert "Chuyên viên" not in out_multi["final_answer"]
