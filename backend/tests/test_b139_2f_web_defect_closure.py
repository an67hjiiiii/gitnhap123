"""B139.2F Test-First Suite: Live Web Defect Closure & Reasoning Reliability (Zero Ollama).

Reproduces every B139.2W bug with exact raw Markdown chunks & answers AND adds >= 20 unseen
raw-context generalization scenarios across heterogeneous structures:
- FIX-01 (BUG-01): Table-aware + adjacent-prose + bullet fixed+discount + unit-inherited extraction
- FIX-02 (BUG-02): Factual lookup vs true calculation intent routing
- FIX-03 (BUG-01 / CASE-09): Verified answer safety (headline vs detail contradiction, safe refusal)
- FIX-04 (BUG-04): Rule reasoning (4d < 5d notice, calendar/working days, peak season, completeness)
- FIX-05 (BUG-05): Workspace & source scoping audit (single-doc BUSINESS vs cross-doc LABOR)
- Timeout propagation test with FakeProvider (deterministic wall_timeout handling, zero Ollama)
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
import time
from unittest.mock import patch

import pytest

from app.core.answer_checks import IMG_MARK, check_product_evidence_claims
from app.core.formula_engine import CalcStatus, FormulaType, execute_formula, select_formula
from app.core.structured_evidence import EvidenceRole, ValidationStatus, extract_structured_evidence
from app.core.types import ProviderResult, SourceChunk, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.verified_reasoning import verify_and_reconcile_answer
from app.retrieval.evidence_completeness import complete_missing_evidence
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _ch(src: str, name: str, idx: int, text: str, *, doc_type: str = "other", score: float = 0.7) -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{src}_c{idx:04d}",
        source_id=src,
        source_name=name,
        text=text,
        index=idx,
        score=score,
        provenance={"doc_type": doc_type} if doc_type else {},
    )


# Exact raw Markdown chunks from B139.2W QA corpus (used only to reproduce B139.2W bugs)
_RAW_PRICING_TABLE_CHUNK = _ch(
    "src_ha02",
    "HA_02_So_tay_phong_Kinh_doanh_2026.md",
    0,
    (
        "# SỔ TAY PHÒNG KINH DOANH 2026\n"
        "## 2. Bảng giá niêm yết 2026 (chưa gồm VAT)\n\n"
        "| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí triển khai một lần |\n"
        "|---|---|---|---|---|\n"
        "| HA-ERP | Cơ bản (đến 50 người dùng) | 180.000.000 đ | năm | 60.000.000 đ |\n"
        "| HA-ERP | Doanh nghiệp (đến 300 người dùng) | 650.000.000 đ | năm | 150.000.000 đ |\n"
        "| HA-HR | Theo người dùng | 45.000 đ | người dùng/tháng | 20.000.000 đ |\n"
        "| HA-Edu | Trường dưới 3.000 sinh viên | 120.000.000 đ | năm | 30.000.000 đ |\n"
        "| HA-Edu | Trường từ 3.000 sinh viên | 260.000.000 đ | năm | 50.000.000 đ |\n"
    ),
    doc_type="",
)

_RAW_DISCOUNT_ADJACENT_CHUNK = _ch(
    "src_ha02",
    "HA_02_So_tay_phong_Kinh_doanh_2026.md",
    2,
    (
        "## 4. Chính sách chiết khấu và thẩm quyền phê duyệt\n\n"
        "| Mức chiết khấu trên giá niêm yết | Người phê duyệt |\n"
        "|---|---|\n"
        "| Đến 10% | Nhân viên Kinh doanh tự quyết |\n"
        "| Trên 10% đến 20% | Trưởng phòng Kinh doanh |\n"
        "| Trên 20% đến 30% | Giám đốc Kinh doanh |\n"
        "| Trên 30% | Tổng Giám đốc |\n\n"
        "- Khách hàng là trường đại học công lập được thêm 5% (cộng dồn, không vượt 30%).\n"
        "- Hợp đồng 3 năm trả trước được giảm thêm 8% cho năm thứ hai và thứ ba.\n"
        "- Không chiết khấu phí triển khai, trừ khi Tổng Giám đốc duyệt.\n"
    ),
    doc_type="",
)

_RAW_UNSEEN_WARRANTY_SLA_2027 = _ch(
    "src_warranty_2027",
    "Unseen_Warranty_SLA_2027.md",
    0,
    (
        "# CHÍNH SÁCH BẢO HÀNH VÀ BẢO TRÌ THIẾT BỊ 2027\n"
        "Hiệu lực từ ngày 01/02/2027. Áp dụng cho gói thiết bị y tế SmartMed.\n\n"
        "## 1. Biểu phí gia hạn chính thức\n"
        "- Phí gói gia hạn 1 năm: 40.000.000 VND/năm.\n"
        "- Phí cử kỹ sư kiểm tra tại chỗ (cố định): 6.000.000 VND/lần.\n"
        "- Khách hàng bệnh viện công lập được chiết khấu 10% trên phí gói gia hạn; KHÔNG chiết khấu phí cử kỹ sư kiểm tra tại chỗ.\n"
        "- Ví dụ minh họa: Dự án thử nghiệm nội bộ năm 2025 từng miễn phí 50% toàn bộ chi phí để khảo sát.\n\n"
        "## 2. Điều kiện bảo hành hợp lệ\n"
        "1. Tem niêm phong bảo hành phải còn nguyên vẹn.\n"
        "2. Có phiếu yêu cầu bảo trì trên hệ thống trước ít nhất 02 ngày làm việc.\n"
    ),
    doc_type="internal_policy",
)


# ==============================================================================
# FIX-01: TABLE-AWARE, UNIT-INHERITED & BULLET/PROSE EXTRACTION (ZERO KWARGS!)
# ==============================================================================


def test_fix01_reproduce_r01_and_g01_raw_markdown_tier_table_without_kwargs():
    """R-01 (3.500 sv) & G-01 (4.000 sv) must auto-select tier 260M + 50M + 5% public discount -> 297M."""
    for qty_str in ("3.500 sinh viên", "4.000 sinh viên"):
        q = (
            f"Trường đại học công lập mua gói HA-Edu cho {qty_str} và ký hợp đồng 1 năm "
            f"(không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm phí triển khai là bao nhiêu?"
        )
        spec = select_formula(q, chunks=[_RAW_PRICING_TABLE_CHUNK, _RAW_DISCOUNT_ADJACENT_CHUNK])
        res = execute_formula(spec)
        assert res.status == CalcStatus.VERIFIED, f"Expected VERIFIED on {qty_str}, got {res.status}: {res.reason}"
        assert res.value == Decimal("297000000")
        assert res.formatted_value == "297.000.000 VND"


def test_fix01_r01_below_threshold_selects_lower_tier_no_conflict():
    """Two tiers of same product must NOT conflict: 1.500 students picks 120M tier -> 120M*0.95 + 30M = 144M."""
    q = "Trường đại học công lập mua gói HA-Edu cho 1.500 sinh viên hợp đồng 1 năm, tổng tiền năm đầu gồm phí triển khai là bao nhiêu?"
    spec = select_formula(q, chunks=[_RAW_PRICING_TABLE_CHUNK, _RAW_DISCOUNT_ADJACENT_CHUNK])
    res = execute_formula(spec)
    assert res.status == CalcStatus.VERIFIED, f"Got {res.status}: {res.reason}"
    assert res.value == Decimal("144000000")


def test_fix01_refuses_guess_when_quantity_or_package_missing():
    """When query omits student count/package for a multi-tier table, never silently pick 120M or 260M."""
    q = "Trường đại học công lập mua gói HA-Edu hợp đồng 1 năm thì tổng tiền năm đầu gồm phí triển khai là bao nhiêu?"
    spec = select_formula(q, chunks=[_RAW_PRICING_TABLE_CHUNK, _RAW_DISCOUNT_ADJACENT_CHUNK])
    res = execute_formula(spec)
    assert res.status in {CalcStatus.AMBIGUOUS_FORMULA, CalcStatus.MISSING_OPERAND, CalcStatus.CONFLICT}
    assert res.value is None


def test_fix01_reproduce_case09_unseen_bullet_fixed_plus_scoped_discount():
    """CASE-09 raw bullet fees + public hospital 10% scoped discount (fixed engineer fee NOT discounted) -> 42M."""
    q = "Bệnh viện công lập gia hạn gói SmartMed 1 năm kèm 1 lần cử kỹ sư kiểm tra tại chỗ thì tổng chi phí là bao nhiêu và chính sách có hiệu lực từ ngày nào?"
    spec = select_formula(q, chunks=[_RAW_UNSEEN_WARRANTY_SLA_2027])
    res = execute_formula(spec)
    assert res.status == CalcStatus.VERIFIED, f"Expected VERIFIED 42M, got {res.status}: {res.reason}"
    # 40,000,000 * 0.90 + 6,000,000 = 42,000,000
    assert res.value == Decimal("42000000")


def test_fix01_heldout_diverse_raw_documents_without_kwargs():
    """Genuinely unseen held-out raw docs across 5 domains with different column headers & structures."""
    # 1. Logistics cold-chain tier table (weight tiers + fixed gate fee + urgent surcharge excluded from discount)
    ch_log = _ch(
        "src_unseen_log",
        "ColdChain_Tariff_2027.md",
        0,
        (
            "# BIỂU CƯỚC KHO LẠNH BẮC TRUNG NAM\n"
            "| Dịch vụ | Phân hạng khối lượng | Cước vận chuyển | Đơn vị tính | Phí niêm phong cố định |\n"
            "|---|---|---|---|---|\n"
            "| Kho lạnh | Lô dưới 5 tấn | 14.000.000 VND | chuyến | 2.000.000 VND |\n"
            "| Kho lạnh | Lô từ 5 tấn | 25.000.000 VND | chuyến | 3.500.000 VND |\n\n"
            "- Đối tác y tế tuyến tỉnh được chiết khấu 20% cước vận chuyển; không giảm phí niêm phong cố định.\n"
        ),
    )
    res_log = execute_formula(select_formula(
        "Đối tác y tế tuyến tỉnh thuê Kho lạnh chở lô 8 tấn kèm phí niêm phong thì tổng chi phí một chuyến là bao nhiêu?",
        chunks=[ch_log],
    ))
    assert res_log.status == CalcStatus.VERIFIED, res_log.reason
    # 25,000,000 * 0.8 + 3,500,000 = 23,500,000
    assert res_log.value == Decimal("23500000")

    # 2. SaaS per-seat table inheriting column unit ("USD", "người dùng/tháng") + one-time onboarding fee
    ch_saas = _ch(
        "src_unseen_saas",
        "CloudDesk_Pricing_2027.md",
        0,
        (
            "# BẢNG GIÁ CLOUDDESK 2027\n"
            "| Sản phẩm | Hạng | Giá thuê bao | Chu kỳ tính | Phí khởi tạo một lần |\n"
            "|---|---|---|---|---|\n"
            "| CloudDesk | Nhỏ (từ 10 đến 49 tài khoản) | 300.000 đ | tài khoản/tháng | 5.000.000 đ |\n"
            "| CloudDesk | Lớn (từ 50 tài khoản) | 200.000 đ | tài khoản/tháng | 8.000.000 đ |\n\n"
            "- Tổ chức phi lợi nhuận được giảm 15% giá thuê bao; không giảm phí khởi tạo.\n"
        ),
    )
    # 60 accounts * 200,000 * 12 months * (1 - 0.15) + 8,000,000 OR 1 month:
    # Let's test 1 month explicitly (per-unit multi-seat calculation)
    res_saas = execute_formula(select_formula(
        "Tổ chức phi lợi nhuận đăng ký CloudDesk cho 60 tài khoản trong 1 tháng gồm phí khởi tạo thì tổng tiền là bao nhiêu?",
        chunks=[ch_saas],
    ))
    assert res_saas.status == CalcStatus.VERIFIED, res_saas.reason
    # 60 * 200,000 * 0.85 + 8,000,000 = 10,200,000 + 8,000,000 = 18,200,000
    assert res_saas.value == Decimal("18200000")

    # 3. Bullet list with entity group A vs entity group B (must NOT treat different groups as conflict; must refuse when group unspecified)
    ch_group = _ch(
        "src_unseen_grp",
        "Lab_Testing_Fees.md",
        0,
        (
            "# BIỂU PHÍ KIỂM ĐỊNH THIẾT BỊ ĐO 2027\n"
            "- Doanh nghiệp tư nhân: phí hiệu chuẩn 12.000.000 VND/lượt.\n"
            "- Cơ quan nhà nước: phí hiệu chuẩn 9.000.000 VND/lượt.\n"
            "- Phí di chuyển kỹ sư (cố định): 1.500.000 VND/lượt (không áp dụng giảm giá).\n"
            "Ví dụ minh họa: Năm 2024 từng thu trọn gói 5.000.000 VND cho mẫu thử.\n"
        ),
    )
    res_grp_ok = execute_formula(select_formula(
        "Cơ quan nhà nước đăng ký 1 lượt hiệu chuẩn thiết bị đo kèm 1 lượt di chuyển kỹ sư thì tổng chi phí là bao nhiêu?",
        chunks=[ch_group],
    ))
    assert res_grp_ok.status == CalcStatus.VERIFIED, res_grp_ok.reason
    assert res_grp_ok.value == Decimal("10500000")

    # Omitting customer group must NOT guess between 12M and 9M
    res_grp_amb = execute_formula(select_formula(
        "Đăng ký 1 lượt hiệu chuẩn thiết bị đo kèm di chuyển kỹ sư thì tổng chi phí là bao nhiêu?",
        chunks=[ch_group],
    ))
    assert res_grp_amb.status in {CalcStatus.CONFLICT, CalcStatus.AMBIGUOUS_FORMULA, CalcStatus.MISSING_OPERAND}
    assert res_grp_amb.value is None


def test_fix01_unit_inheritance_and_table_entity_extraction():
    """StructuredEvidence must inherit 'Đơn vị tính' column into currency units and combine Product+Tier entity."""
    items = extract_structured_evidence([_RAW_PRICING_TABLE_CHUNK])
    ha_edu_prices = [it for it in items if "HA-Edu" in it.entity and it.attribute == "unit_price"]
    assert len(ha_edu_prices) == 2
    assert all(it.unit in {"VND/year", "VND/năm"} for it in ha_edu_prices)
    assert any(it.applicable_conditions and "min_qty=3000" in it.applicable_conditions for it in ha_edu_prices)


# ==============================================================================
# FIX-02: CALCULATION INTENT ROUTING (LOOKUP VS CALCULATION)
# ==============================================================================


def test_fix02_reproduce_r05_factual_deadline_lookup_not_flagged_as_missing_calc():
    """R-05 factual deadline query ('chậm nhất bao nhiêu giờ...') MUST NOT trigger MISSING_OPERAND/PARTIAL."""
    nd_chunks = [
        _ch("src_nd13", "PL_Nghi_dinh_13-2023-ND-CP.pdf", 32, "Điều 43. Hiệu lực thi hành\n1. Nghị định này có hiệu lực từ ngày 01 tháng 7 năm 2023."),
        _ch("src_nd13", "PL_Nghi_dinh_13-2023-ND-CP.pdf", 53, "Điều 23. Thông báo vi phạm quy định bảo vệ dữ liệu cá nhân\n1. Bên kiểm soát dữ liệu thông báo cho Bộ Công an chậm nhất 72 giờ sau khi xảy ra hành vi vi phạm."),
    ]
    q = (
        "Theo Nghị định 13/2023/NĐ-CP, khi phát hiện vi phạm quy định bảo vệ dữ liệu cá nhân thì "
        "chậm nhất bao nhiêu giờ phải thông báo cho Bộ Công an và Nghị định có hiệu lực từ ngày nào?"
    )
    llm_ok = "Theo Nghị định 13/2023/NĐ-CP, chậm nhất **72 giờ** phải thông báo cho Bộ Công an (Điều 23). Nghị định có hiệu lực từ ngày 01 tháng 7 năm 2023 (Điều 43)."
    vr = verify_and_reconcile_answer(query=q, chunks=nd_chunks, llm_answer=llm_ok, status="COMPLETE")
    assert vr["status"] == "COMPLETE"
    assert vr.get("calc_status") is None
    assert "MISSING_OPERAND" not in vr["final_answer"]
    assert "13" in vr["ignored_identifier_numbers"]


def test_fix02_distinguish_lookup_vs_real_time_or_value_calculation():
    """Factual deadline/count queries stay COMPLETE; explicit calculations trigger calculator cleanly."""
    doc = _ch("src_pol", "SLA.md", 0, "Thời hạn phản hồi sự cố: tối đa 4 giờ. Phí hỗ trợ: 500.000 VND/giờ. Quy định gồm 12 điều.")
    lookup_queries = [
        ("Phải thông báo sự cố trong bao nhiêu giờ?", "Phải thông báo trong 4 giờ."),
        ("Quy định này có bao nhiêu điều?", "Quy định gồm 12 điều."),
        ("Thời hạn bảo hành kéo dài bao nhiêu ngày kể từ ngày ký?", "Thời hạn kéo dài 30 ngày kể từ ngày ký."),
    ]
    for q_lkp, ans_lkp in lookup_queries:
        vr = verify_and_reconcile_answer(query=q_lkp, chunks=[doc], llm_answer=ans_lkp, status="COMPLETE")
        assert vr.get("calc_status") is None, f"False calc on lookup: {q_lkp} -> {vr}"
        assert vr["status"] == "COMPLETE"

    # Real time/fee computation ("150 phút sang giờ và tính phí...") STILL computes cleanly
    calc_q = "Quy đổi 150 phút sang giờ và tính phí hỗ trợ là bao nhiêu tiền?"
    vr_calc = verify_and_reconcile_answer(query=calc_q, chunks=[doc], llm_answer="Phí hỗ trợ là 1.250.000 VND.", status="COMPLETE")
    assert vr_calc["applied"] is True
    assert vr_calc.get("calc_status") == CalcStatus.VERIFIED
    assert vr_calc["verified_value"] == "1250000"


# ==============================================================================
# FIX-03: VERIFIED ANSWER SAFETY (NO CONTRADICTION, NO UNGROUNDED HEADLINES)
# ==============================================================================


def test_fix03_reproduce_case09_46m_headline_vs_42m_detail_override():
    """Self-contradictory 46M headline vs 42M breakdown MUST be detected and replaced with verified 42M + effective date preserved."""
    q = "Bệnh viện công lập gia hạn gói SmartMed 1 năm kèm 1 lần cử kỹ sư kiểm tra tại chỗ thì tổng chi phí là bao nhiêu và chính sách có hiệu lực từ ngày nào?"
    contradictory_llm = (
        "Tổng chi phí cho gói SmartMed gia hạn 1 năm kèm 1 lần cử kỹ sư kiểm tra tại chỗ là **46.000.000 VND**.\n\n"
        "### Chi tiết tính toán\n"
        "1. Phí gia hạn 1 năm: 40.000.000 VND/năm (áp dụng chiết khấu 10% cho bệnh viện công lập)\n"
        "2. Phí cử kỹ sư kiểm tra tại chỗ: 6.000.000 VND/lần (không có chiết khấu)\n\n"
        "**Tổng chi phí** = **42.000.000** VND\n\n"
        "### Chính sách hiệu lực\n"
        "- Hiệu lực từ ngày **01/02/2027**.\n"
    )
    vr = verify_and_reconcile_answer(
        query=q,
        chunks=[_RAW_UNSEEN_WARRANTY_SLA_2027],
        llm_answer=contradictory_llm,
        status="COMPLETE",
    )
    assert vr["applied"] is True
    assert vr["calc_status"] == CalcStatus.VERIFIED
    assert vr["contradicted_llm"] is True
    assert vr["status"] == "COMPLETE"
    assert "42.000.000" in vr["final_answer"]
    # Wrong asserted headline 46.000.000 MUST NOT remain as an asserted total!
    assert "là **46.000.000" not in vr["final_answer"]
    assert "46.000.000 VND**" not in vr["final_answer"]
    # Non-calculated verified facts (effective date) must still be preserved!
    assert "01/02/2027" in vr["final_answer"]


def test_fix03_missing_operand_does_not_leave_unverified_asserted_total():
    """When CalcStatus is MISSING_OPERAND (e.g. R-03 missing /8 divisor), suppress/retract the LLM's speculative total instead of just prepending a banner."""
    q = (
        f"Tiền làm thêm tối thiểu của người này là bao nhiêu?\n\n{IMG_MARK}\n"
        "Lương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ\nLàm thêm ngày lễ: 8 giờ"
    )
    ch_no_hpd = _ch("src_bll_partial", "Labor.md", 0, "Làm thêm ngày thường ít nhất 150%, ngày lễ 300%.")
    speculative_llm = (
        "### Tính toán tiền làm thêm\n"
        "1. Ngày thường: 841.350 đồng\n"
        "2. Ngày lễ: 673.080 đồng\n\n"
        "**Tổng tiền làm thêm**: **1.514.430** đồng.\n"
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[ch_no_hpd], llm_answer=speculative_llm, status="COMPLETE")
    assert vr["applied"] is True
    assert vr["calc_status"] == CalcStatus.MISSING_OPERAND
    assert vr["status"] == "PARTIAL"
    assert "hours_per_day" in vr["final_answer"] or "giờ/ngày" in vr["final_answer"].lower()
    # Must explicitly refuse/retract unverified total rather than leaving it stated as final total
    assert "**Tổng tiền làm thêm**: **1.514.430**" not in vr["final_answer"]


def test_fix03_pipeline_streaming_and_persisted_answer_consistency(tmp_path):
    """Verify raw LLM -> buffered streaming -> persisted RunStore answer all hold verified 42M without 46M."""
    st = SourceStore(str(tmp_path / "src_p"))
    imported = st.import_text("Unseen_Warranty_SLA_2027.md", _RAW_UNSEEN_WARRANTY_SLA_2027.text)
    cid = st.chunks([imported["source_id"]])[0].chunk_id
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "runs_p")))
    q = "Bệnh viện công lập gia hạn gói SmartMed 1 năm kèm 1 lần cử kỹ sư kiểm tra tại chỗ thì tổng chi phí là bao nhiêu và hiệu lực từ ngày nào?"

    class _ContradictingFake(FakeProvider):
        name = "fake"
        model = "fake-v2"
        supports_streaming = True

        async def generate_grounded(self, *, system, user, evidence_ids, on_text=None, **kw):
            ans = (
                f"Tổng chi phí gói SmartMed là **46.000.000 VND**. "
                f"Hiệu lực từ 01/02/2027 [{cid}]."
            )
            payload = json.dumps({"status": "COMPLETE", "answer": ans, "citations": [cid], "missing_information": []}, ensure_ascii=False)
            return ProviderResult(payload, Usage(20, 20), request_id="fake_grounded")

    streamed: list[str] = []
    with (
        patch.dict("os.environ", {"IMPLEMENTATION_PROFILE": "m2", "PRODUCT_STRUCTURED_EVIDENCE": "on", "PRODUCT_ADVANCED_REASONING": "on"}),
        patch("app.research.pipeline.get_provider", return_value=_ContradictingFake()),
        patch("app.research.vanilla.emit_validated_answer", side_effect=lambda txt: streamed.append(txt)),
    ):
        run = asyncio.run(
            pipe.run(q, condition="C", provider_name="fake", product_mode=True)
        )
    persisted = pipe.run_store.get(run["run_id"])
    assert streamed, "Expected buffered emit_validated_answer to fire"
    emitted_ans = streamed[-1]
    assert "42.000.000" in run["answer"]
    assert "46.000.000" not in run["answer"].split("Hiệu lực")[0]
    assert emitted_ans == run["answer"]
    assert persisted is not None and persisted["answer"] == run["answer"]


# ==============================================================================
# FIX-04: RULE REASONING, DATE INTERVALS, SEASONAL & COMPLETENESS (R-02)
# ==============================================================================


def test_fix04_reproduce_r02_contradictory_4d_lt_5d_and_peak_season_and_missing_balance():
    """03/12 -> 07/12 = 4 calendar days (< 5 working days) MUST NEVER remain marked 'thỏa mãn'."""
    ha01_c03 = _ch(
        "src_ha01",
        "HA_01_Noi_quy_lao_dong_2026.docx",
        3,
        "4. Người lao động gửi đơn nghỉ phép trên hệ thống trước ít nhất 03 ngày làm việc. Nghỉ từ 05 ngày liên tiếp trở lên phải được Trưởng phòng và Giám đốc Nhân sự phê duyệt.",
    )
    ha02_c03 = _ch(
        "src_ha02",
        "HA_02_So_tay_phong_Kinh_doanh_2026.md",
        3,
        (
            "## 6. Nghỉ phép và trực bán hàng của phòng Kinh doanh\n"
            "- Do đặc thù chăm sóc khách hàng, nhân viên Kinh doanh gửi đơn nghỉ phép trước ít nhất 05 ngày làm việc và phải bàn giao danh sách khách hàng đang theo dõi cho người trực thay.\n"
            "- Mùa cao điểm tuyển sinh và quyết toán (tháng 8 đến tháng 10, tháng 12) hạn chế nghỉ phép quá 03 ngày liên tiếp.\n"
        ),
    )
    q_r02 = (
        f"Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n{IMG_MARK}\n"
        "ĐƠN XIN NGHỈ PHÉP\nNgười làm đơn: Phạm Minh Hải - Phòng Kinh doanh\nNgày vào làm: 15/06/2025\n"
        "Xin nghỉ phép năm từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc)\n"
        "Ngày gửi đơn: thứ Năm 03/12/2026\nNgười nhận bàn giao khách hàng: chưa có"
    )
    # Exact reproduction of B139.2W qwen3:4b error inside bullet 1!
    llm_r02_bug = (
        "1. **Thời gian gửi đơn**: Đơn được gửi vào ngày 03/12/2026, trong khi thời gian nghỉ phép bắt đầu từ 07/12/2026 → **thỏa mãn** điều kiện gửi trước ít nhất 05 ngày làm việc (03/12 → 07/12 = 4 ngày, nhưng theo quy định, cần ít nhất 05 ngày làm việc).\n\n"
        "2. **Bàn giao khách hàng**: chưa có → **không thỏa mãn**.\n\n"
        "### Kết luận\nĐơn nghỉ phép không đúng nội quy."
    )
    vr = verify_and_reconcile_answer(query=q_r02, chunks=[ha01_c03, ha02_c03], llm_answer=llm_r02_bug, status="PARTIAL")
    assert vr["applied"] is True
    assert vr["status"] == "PARTIAL"
    assert "→ **thỏa mãn**" not in vr["final_answer"]
    assert "không thỏa mãn" in vr["final_answer"].lower() or "chưa thỏa mãn" in vr["final_answer"].lower()
    # Must clarify date interval (calendar vs working days), peak season in Dec (>3 consecutive days), approval & unknown remaining balance
    low = vr["final_answer"].casefold()
    assert "ngày làm việc" in low or "working" in low
    assert "tháng 12" in low or "cao điểm" in low
    assert "trưởng phòng" in low or "giám đốc nhân sự" in low
    assert "chưa rõ" in low or "unknown" in low or "số ngày phép còn lại" in low


def test_fix04_evidence_completeness_rescues_ha01_c0003_alongside_ha02_c0003():
    """Simulate exact R-02 token budget saturation: HA_01_c0003 (leave approval) MUST NOT be starved by unrelated complaint/discipline chunks."""
    # Exact R-02 selected pattern: HA_01 c0, c1, c6, c7 + HA_02 c0 + HA_05 c0 + HA_03 c0 (~2700 tokens)
    filler = "Nội dung hành chính và quy trình nội bộ chi tiết phục vụ vận hành doanh nghiệp. " * 25
    selected = [
        _ch("src_ha01", "HA_01.docx", 0, f"# NỘI QUY LAO ĐỘNG\nĐiều 1. Phạm vi. {filler}"),
        _ch("src_ha01", "HA_01.docx", 1, f"# Điều 3. Thời giờ làm việc\n8 giờ/ngày. {filler}"),
        _ch("src_ha01", "HA_01.docx", 6, f"# Điều 14. Bảo vệ dữ liệu cá nhân\n{filler}"),
        _ch("src_ha02", "HA_02.md", 0, f"# SỔ TAY KINH DOANH\nBảng giá. {filler}"),
    ]
    c_ha01_2 = _ch("src_ha01", "HA_01.docx", 2, "# Điều 5. Nghỉ hằng năm (nghỉ phép năm)\n1. Làm đủ 12 tháng nghỉ 12 ngày.")
    c_ha01_3 = _ch("src_ha01", "HA_01.docx", 3, "4. Gửi đơn nghỉ phép trước ít nhất 03 ngày làm việc. Nghỉ từ 05 ngày liên tiếp phải được Trưởng phòng và Giám đốc Nhân sự phê duyệt.")
    c_ha01_8 = _ch("src_ha01", "HA_01.docx", 8, "# Điều 18. Sa thải\nTự ý bỏ việc không lý do 05 ngày cộng dồn trong 30 ngày.")
    c_ha02_3 = _ch("src_ha02", "HA_02.md", 3, "## 6. Nghỉ phép phòng Kinh doanh\nNhân viên Kinh doanh gửi đơn nghỉ phép trước ít nhất 05 ngày làm việc, bàn giao khách hàng, cao điểm tháng 12 hạn chế quá 03 ngày.")
    c_ha02_4 = _ch("src_ha02", "HA_02.md", 4, "## 7. Xử lý khiếu nại khách hàng\nKhách hàng phản hồi chậm trong 4 giờ.")
    all_chunks = [*selected, c_ha01_2, c_ha01_3, c_ha01_8, c_ha02_3, c_ha02_4]

    q = (
        f"Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n{IMG_MARK}\n"
        "ĐƠN XIN NGHỈ PHÉP - Phạm Minh Hải - Phòng Kinh doanh - Xin nghỉ phép từ 07/12 đến 11/12 (5 ngày) - Bàn giao khách hàng: chưa có"
    )
    recovered, trace = complete_missing_evidence(
        query=q,
        selected=selected,
        all_chunks=all_chunks,
        allowed_source_ids={"src_ha01", "src_ha02"},
        max_tokens=4000,
    )
    rec_ids = {c.chunk_id for c in recovered}
    assert "src_ha02_c0003" in rec_ids
    assert "src_ha01_c0003" in rec_ids, f"HA_01_c0003 was starved! Added={trace['added_chunk_ids']}"


# ==============================================================================
# FIX-05: WORKSPACE & SOURCE SCOPING AUDIT (R-03)
# ==============================================================================


def test_fix05_r03_single_doc_workspace_vs_cross_doc_labor_scope(tmp_path):
    """Single-doc workspace (HA_08 only) MUST stay scoped (no /8 guess -> MISSING_OPERAND); cross-doc workspace (HA_08 + BLLD) computes 3.281.250."""
    ha08_text = (
        "## Lam_them\n"
        "Họ tên | Số tháng làm việc | Lương giờ (đồng) | Giờ làm thêm ngày thường | Giờ ngày nghỉ tuần | Giờ ngày lễ | Ngày phép đã nghỉ\n"
        "Trần Thu Hà | 62 | 84135 | 10 | 0 | 8 | 7\n"
    )
    blld_text = (
        "# Bộ luật Lao động 2019\n"
        "Điều 98. Tiền lương làm thêm giờ: ngày thường ít nhất bằng 150%, ngày nghỉ hằng tuần 200%, ngày lễ 300%.\n"
        "Điều 105. Thời giờ làm việc bình thường không quá 08 giờ/ngày (8 giờ/ngày).\n"
    )
    ch_ha08 = _ch("src_ha08", "HA_08.xlsx", 0, ha08_text)
    ch_blld = _ch("src_blld", "BLLD_2019.pdf", 0, blld_text, doc_type="legal_doc")

    q_r03 = (
        f"Tiền làm thêm tối thiểu của người này là bao nhiêu?\n\n{IMG_MARK}\n"
        "BẢNG CHẤM CÔNG LÀM THÊM - THÁNG 11/2026\n"
        "Nhân viên: Trần Thu Hà - Lương 17.500.000 đ/tháng - 26 ngày công\n"
        "Làm thêm ngày thường: 10 giờ\nLàm thêm ngày nghỉ hằng tuần: 0 giờ\nLàm thêm ngày lễ: 8 giờ"
    )

    # Case A: Reproducing BUSINESS workspace containing ONLY HA_08 (no BLLD) -> MUST respect ACL/scope and report MISSING_OPERAND (refuse silent 150%/300% or /8)!
    res_scoped_only = execute_formula(select_formula(q_r03, chunks=[ch_ha08], allowed_source_ids={"src_ha08"}))
    assert res_scoped_only.status == CalcStatus.MISSING_OPERAND

    # Case B: CROSS_DOCUMENT workspace containing BOTH HA_08 + BLLD (150%, 300%, 8 giờ/ngày) -> VERIFIED 3.281.250 VND!
    res_cross = execute_formula(select_formula(q_r03, chunks=[ch_ha08, ch_blld], allowed_source_ids={"src_ha08", "src_blld"}))
    assert res_cross.status == CalcStatus.VERIFIED, res_cross.reason
    # 17,500,000 / 26 / 8 * (10*1.5 + 8*3.0) = 3,281,250 VND (or 84135 * 39 if sheet hourly rate chosen; let's verify consistent rule)
    assert res_cross.value in {Decimal("3281250"), Decimal("3281265")}

    # Case C: Verify pipeline source_ids scoping strictly blocks BLLD when workspace only selects HA_08!
    st_ws = SourceStore(str(tmp_path / "src_ws"))
    s_ha08 = st_ws.import_text("HA_08.md", ha08_text)
    s_blld = st_ws.import_text("BLLD_2019.md", blld_text)
    pipe_ws = ResearchPipeline(st_ws, RunStore(str(tmp_path / "runs_ws")))
    chunks_scoped = st_ws.chunks([s_ha08["source_id"]])
    assert all(c.source_id == s_ha08["source_id"] for c in chunks_scoped)
    # Cross-doc selection includes both sources cleanly without leaking external docs
    chunks_cross = st_ws.chunks([s_ha08["source_id"], s_blld["source_id"]])
    assert {c.source_id for c in chunks_cross} == {s_ha08["source_id"], s_blld["source_id"]}


# ==============================================================================
# PERFORMANCE / WALL_TIMEOUT PROPAGATION (ZERO OLLAMA)
# ==============================================================================


def test_perf_wall_timeout_propagates_cleanly_across_planning_and_worker(tmp_path):
    """FakeProvider simulating slow s3_planning/worker under tight wall timeout exits via wall_timeout without silently hanging."""
    st = SourceStore(str(tmp_path / "src_t"))
    st.import_text("Contract_27.md", "# Điều 9\nPhạt vi phạm 30% giá trị hợp đồng.")
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "runs_t")))

    class _SlowFakeProvider(FakeProvider):
        name = "fake"
        model = "fake-slow"

        async def generate(self, **kw):
            await asyncio.sleep(0.35)
            return await super().generate(**kw)

        async def generate_grounded(self, **kw):
            await asyncio.sleep(0.35)
            return await super().generate_grounded(**kw)

        async def generate_structured(self, **kw):
            await asyncio.sleep(0.35)
            return await super().generate_structured(**kw)

    # Complex analysis triggers s3_planning (multiple LLM calls) under 0.2s wall clock budget
    q = "Phân tích rủi ro pháp lý và đánh giá điều khoản phạt vi phạm 30% trong hợp đồng?"
    with (
        patch.dict("os.environ", {"IMPLEMENTATION_PROFILE": "m2", "MAX_DAG_WALL_SECONDS": "0.2", "PRODUCT_ADVANCED_REASONING": "on"}),
        patch("app.research.pipeline.get_provider", return_value=_SlowFakeProvider()),
    ):
        t0 = time.perf_counter()
        run = asyncio.run(pipe.run(q, condition="C", provider_name="fake", product_mode=True))
        elapsed = time.perf_counter() - t0

    assert elapsed < 3.0
    stages = [e["stage"] for e in run["events"]]
    assert "run_budget_exceeded" in stages
    b_evt = next(e for e in run["events"] if e["stage"] == "run_budget_exceeded")
    assert b_evt["reason"] == "wall_timeout"
    assert run["status"] == "FAILED"


# ==============================================================================
# ADDITIONAL HELD-OUT RAW-CONTEXT SCENARIOS (SECTION 8: >= 20 TOTAL SCENARIOS)
# ==============================================================================


def test_sec8_additional_raw_context_matrix_and_acl_safety():
    # 1. Historical example trap in bullet list ("Hợp đồng cũ năm 2024 từng giảm 40%") MUST NEVER override 10%
    doc_hist = _ch(
        "src_h1",
        "SaaS_Renewal_2027.md",
        0,
        (
            "# BẢNG GIÁ GIA HẠN MEDI-CLOUD 2027\n"
            "- Phí thuê bao năm: 80.000.000 VND/năm.\n"
            "- Phí cấu hình tích hợp (cố định): 12.000.000 VND/lần.\n"
            "- Bệnh viện công được chiết khấu 10% phí thuê bao; không chiết khấu phí cấu hình.\n"
            "- Ví dụ minh họa: Hợp đồng cũ năm 2024 từng giảm 40% toàn bộ hóa đơn.\n"
        ),
    )
    r_hist = execute_formula(select_formula(
        "Bệnh viện công gia hạn gói Medi-Cloud 1 năm kèm cấu hình tích hợp thì tổng chi phí là bao nhiêu?",
        chunks=[doc_hist],
    ))
    assert r_hist.status == CalcStatus.VERIFIED, r_hist.reason
    # 80,000,000 * 0.9 + 12,000,000 = 84,000,000
    assert r_hist.value == Decimal("84000000")

    # 2. Unauthorized secret source containing discount MUST BE BLOCKED by ACL (never alter verified price)
    doc_pub = _ch("src_pub_price", "Public_Fee.md", 0, "# BIỂU PHÍ DỊCH VỤ\n- Gói Standard: 50.000.000 VND/năm.\n- Phí cài đặt (cố định): 5.000.000 VND.\n- Chiết khấu đối tác chuẩn: 10% gói Standard; không giảm phí cài đặt.")
    doc_sec_disc = _ch("src_sec_disc", "Secret_Exec_Discount.md", 0, "Chính sách mật: Chiết khấu đặc biệt gói Standard 50%.")
    r_acl = execute_formula(select_formula(
        "Đối tác chuẩn mua gói Standard 1 năm kèm phí cài đặt tổng cộng bao nhiêu?",
        chunks=[doc_pub, doc_sec_disc],
        allowed_source_ids={"src_pub_price"},
    ))
    assert r_acl.status == CalcStatus.VERIFIED, r_acl.reason
    assert r_acl.value == Decimal("50000000")  # 50M * 0.9 + 5M = 50M (never 50% secret!)

    # 3. Conflicting numerical conclusions across two official sources -> CONFLICT (never silent pick)
    c_p1 = _ch("src_c1", "Pricing_A.md", 0, "# BẢNG GIÁ\n- Gói Enterprise: 100.000.000 VND/năm.")
    c_p2 = _ch("src_c2", "Pricing_B.md", 0, "# BẢNG GIÁ\n- Gói Enterprise: 140.000.000 VND/năm.")
    r_conf = execute_formula(select_formula(
        "Mua gói Enterprise 1 năm hết bao nhiêu tiền?",
        chunks=[c_p1, c_p2],
    ))
    assert r_conf.status in {CalcStatus.CONFLICT, CalcStatus.AMBIGUOUS_FORMULA, CalcStatus.MISSING_OPERAND}
    assert r_conf.value is None

    # 4. Salary + OT via direct hourly rate table row (entity-bound per-person row in HA_08-like table)
    ch_ot_tbl = _ch(
        "src_ot_tbl",
        "Timesheet_Dec.xlsx",
        0,
        (
            "## Bang_cong\n"
            "Họ tên | Lương giờ (đồng) | Giờ làm thêm ngày thường | Giờ ngày lễ\n"
            "Nguyễn Văn An | 100000 | 4 | 2\n"
            "Lê Thị Bình | 150000 | 10 | 0\n"
        ),
    )
    ch_ot_rule = _ch("src_ot_r", "Labor_Pol.md", 0, "Làm thêm ngày thường: 150%; ngày nghỉ hằng tuần: 200%; ngày lễ: 300%.")
    q_an = (
        f"Tiền làm thêm tối thiểu của Nguyễn Văn An là bao nhiêu?\n\n{IMG_MARK}\n"
        "Nhân viên: Nguyễn Văn An\nLàm thêm ngày thường: 4 giờ\nLàm thêm ngày lễ: 2 giờ"
    )
    r_an = execute_formula(select_formula(q_an, chunks=[ch_ot_tbl, ch_ot_rule]))
    assert r_an.status == CalcStatus.VERIFIED, r_an.reason
    # 100,000 * (4 * 1.5 + 2 * 3.0) = 1,200,000 VND
    assert r_an.value == Decimal("1200000")

    # 5. Unseen multi-tier freight discount table where fixed insurance fee IS discounted when explicitly stated, vs excluded otherwise
    ch_ins = _ch(
        "src_freight",
        "Freight_2027.md",
        0,
        (
            "| Tuyến | Trọng lượng | Giá cước | Đơn vị tính | Phí bảo hiểm cố định |\n"
            "|---|---|---|---|---|\n"
            "| Nội địa | Hàng dưới 100 kg | 2.000.000 đ | kiện | 500.000 đ |\n"
            "| Nội địa | Hàng từ 100 kg | 4.500.000 đ | kiện | 800.000 đ |\n\n"
            "- Khách hàng thành viên VIP được giảm 10% giá cước; không giảm phí bảo hiểm cố định.\n"
        ),
    )
    r_fr = execute_formula(select_formula(
        "Khách hàng thành viên VIP gửi kiện hàng 150 kg tuyến Nội địa kèm phí bảo hiểm thì tổng tiền là bao nhiêu?",
        chunks=[ch_ins],
    ))
    assert r_fr.status == CalcStatus.VERIFIED, r_fr.reason
    # 4,500,000 * 0.9 + 800,000 = 4,850,000
    assert r_fr.value == Decimal("4850000")

    # 6. Factual effective-date & response-time lookup with complex doc numbers (Thông tư 12/2025 & Điều 8) -> NO calc trigger
    ch_tt = _ch("src_tt12", "TT_12_2025.pdf", 0, "Thông tư số 12/2025/TT-BTTTT hiệu lực từ 01/05/2025. Điều 8 quy định thời hạn báo cáo tối đa 48 giờ.")
    vr_tt = verify_and_reconcile_answer(
        query="Theo Thông tư 12/2025/TT-BTTTT, tối đa bao nhiêu giờ phải gửi báo cáo và hiệu lực từ ngày nào?",
        chunks=[ch_tt],
        llm_answer="Theo Thông tư 12/2025/TT-BTTTT (Điều 8), tối đa 48 giờ phải báo cáo; hiệu lực từ 01/05/2025.",
        status="COMPLETE",
    )
    assert vr_tt.get("calc_status") is None
    assert vr_tt["status"] == "COMPLETE"
    assert "12" in vr_tt["ignored_identifier_numbers"]
    assert "8" in vr_tt["ignored_identifier_numbers"]


_SEC8_RAW_SCENARIOS = [
    ("RAW-01", "pricing_tier", "HA-Edu 3.500 sv", Decimal("297000000"), CalcStatus.VERIFIED),
    ("RAW-02", "pricing_tier_low", "HA-Edu 1.500 sv", Decimal("144000000"), CalcStatus.VERIFIED),
    ("RAW-03", "bullet_fixed_discount", "SmartMed 1 nam + 1 ky su", Decimal("42000000"), CalcStatus.VERIFIED),
    ("RAW-04", "unseen_logistics_tier", "Kho lanh 8 tan", Decimal("23500000"), CalcStatus.VERIFIED),
    ("RAW-05", "unseen_saas_per_unit", "CloudDesk 60 tai khoan", Decimal("18200000"), CalcStatus.VERIFIED),
    ("RAW-06", "bullet_multi_fixed_qty", "SmartMed + 2 lan ky su", Decimal("48000000"), CalcStatus.VERIFIED),
    ("RAW-07", "historical_example_trap", "Medi-Cloud ignore 40pct hist", Decimal("84000000"), CalcStatus.VERIFIED),
    ("RAW-08", "salary_overtime_row", "Nguyen Van An hourly row OT", Decimal("1200000"), CalcStatus.VERIFIED),
    ("RAW-09", "salary_overtime_cross_doc", "Tran Thu Ha monthly + BLLD 8h", Decimal("3281250"), CalcStatus.VERIFIED),
    ("RAW-10", "factual_deadline_lookup", "ND 13/2023 72h COMPLETE", None, "COMPLETE"),
    ("RAW-11", "factual_count_lookup", "Bao nhieu dieu COMPLETE", None, "COMPLETE"),
    ("RAW-12", "rule_contradiction_dates", "03/12->07/12 < 5d + Dec peak", None, "PARTIAL"),
    ("RAW-13", "missing_operand_hpd", "OT missing hours_per_day", None, CalcStatus.MISSING_OPERAND),
    ("RAW-14", "missing_operand_tier_qty", "HA-Edu missing student count", None, CalcStatus.AMBIGUOUS_FORMULA),
    ("RAW-15", "missing_customer_group", "Lab testing missing group", None, CalcStatus.AMBIGUOUS_FORMULA),
    ("RAW-16", "acl_secret_source_blocked", "Secret 50pct blocked -> 50M", Decimal("50000000"), CalcStatus.VERIFIED),
    ("RAW-17", "acl_scope_r03_isolated", "HA_08 isolated without BLLD", None, CalcStatus.MISSING_OPERAND),
    ("RAW-18", "conflicting_prices", "100M vs 140M official CONFLICT", None, CalcStatus.CONFLICT),
    ("RAW-19", "contradicting_headline", "46M headline vs 42M override", Decimal("42000000"), CalcStatus.VERIFIED),
    ("RAW-20", "vat_ambiguity_retraction", "Chua gom vs da gom VAT", None, CalcStatus.AMBIGUOUS_FORMULA),
]


@pytest.mark.parametrize("scen_id,category,label,exp_val,exp_status", _SEC8_RAW_SCENARIOS, ids=[s[0] for s in _SEC8_RAW_SCENARIOS])
def test_sec8_20_raw_context_matrix(scen_id: str, category: str, label: str, exp_val: Decimal | None, exp_status: str):
    if scen_id == "RAW-01":
        res = execute_formula(select_formula("Trường đại học công lập mua HA-Edu cho 3.500 sinh viên 1 năm gồm phí triển khai tổng tiền là bao nhiêu?", chunks=[_RAW_PRICING_TABLE_CHUNK, _RAW_DISCOUNT_ADJACENT_CHUNK]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-02":
        res = execute_formula(select_formula("Trường đại học công lập mua HA-Edu cho 1.500 sinh viên 1 năm gồm phí triển khai tổng tiền là bao nhiêu?", chunks=[_RAW_PRICING_TABLE_CHUNK, _RAW_DISCOUNT_ADJACENT_CHUNK]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-03":
        res = execute_formula(select_formula("Bệnh viện công lập gia hạn SmartMed 1 năm kèm 1 lần cử kỹ sư tổng chi phí là bao nhiêu?", chunks=[_RAW_UNSEEN_WARRANTY_SLA_2027]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-04":
        ch = _ch("src_u4", "Log.md", 0, "| Dịch vụ | Khối lượng | Giá cước | Đơn vị tính | Phí niêm phong |\n|---|---|---|---|---|\n| Kho lạnh | Từ 5 tấn | 25.000.000 VND | chuyến | 3.500.000 VND |\n- Đối tác y tế tuyến tỉnh được chiết khấu 20% giá cước; không giảm phí niêm phong.")
        res = execute_formula(select_formula("Đối tác y tế tuyến tỉnh thuê Kho lạnh 8 tấn kèm phí niêm phong tổng tiền bao nhiêu?", chunks=[ch]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-05":
        ch = _ch("src_u5", "SaaS.md", 0, "| Sản phẩm | Hạng | Giá thuê bao | Chu kỳ tính | Phí khởi tạo |\n|---|---|---|---|---|\n| CloudDesk | Từ 50 tài khoản | 200.000 đ | tài khoản/tháng | 8.000.000 đ |\n- Tổ chức phi lợi nhuận được giảm 15% giá thuê bao; không giảm phí khởi tạo.")
        res = execute_formula(select_formula("Tổ chức phi lợi nhuận mua CloudDesk 60 tài khoản trong 1 tháng gồm phí khởi tạo tổng tiền bao nhiêu?", chunks=[ch]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-06":
        res = execute_formula(select_formula("Bệnh viện công lập gia hạn gói SmartMed 1 năm kèm 2 lần cử kỹ sư kiểm tra tại chỗ thì tổng chi phí là bao nhiêu?", chunks=[_RAW_UNSEEN_WARRANTY_SLA_2027]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-07":
        ch = _ch("src_u7", "Hist.md", 0, "# BẢNG GIÁ MEDI-CLOUD\n- Phí thuê bao năm: 80.000.000 VND/năm.\n- Phí cấu hình (cố định): 12.000.000 VND/lần.\n- Bệnh viện công chiết khấu 10% phí thuê bao; không chiết khấu phí cấu hình.\n- Ví dụ minh họa: năm 2024 từng giảm 40% toàn bộ.")
        res = execute_formula(select_formula("Bệnh viện công gia hạn Medi-Cloud 1 năm kèm cấu hình tổng tiền bao nhiêu?", chunks=[ch]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-08":
        ch1 = _ch("src_u8a", "TS.xlsx", 0, "Họ tên | Lương giờ (đồng)\nNguyễn Văn An | 100000\n")
        ch2 = _ch("src_u8b", "Labor.md", 0, "Làm thêm ngày thường 150%, ngày lễ 300%.")
        res = execute_formula(select_formula(f"Tiền làm thêm của Nguyễn Văn An?\n\n{IMG_MARK}\nLàm thêm ngày thường: 4 giờ\nLàm thêm ngày lễ: 2 giờ", chunks=[ch1, ch2]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-09":
        ch_ha08 = _ch("src_ha08", "HA_08.xlsx", 0, "Họ tên | Lương giờ (đồng)\nTrần Thu Hà | 84135\n")
        ch_blld = _ch("src_blld", "BLLD.pdf", 0, "Điều 98: ngày thường 150%, ngày nghỉ tuần 200%, ngày lễ 300%. Điều 105: bình thường 8 giờ/ngày.", doc_type="legal_doc")
        q = f"Tiền làm thêm tối thiểu?\n\n{IMG_MARK}\nLương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ\nLàm thêm ngày lễ: 8 giờ"
        res = execute_formula(select_formula(q, chunks=[ch_ha08, ch_blld]))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-10":
        ch = _ch("src_u10", "ND13.pdf", 0, "Nghị định 13/2023/NĐ-CP thông báo chậm nhất 72 giờ.")
        vr = verify_and_reconcile_answer(query="Theo Nghị định 13/2023/NĐ-CP chậm nhất bao nhiêu giờ phải thông báo?", chunks=[ch], llm_answer="Chậm nhất 72 giờ.", status="COMPLETE")
        assert vr["status"] == exp_status and vr.get("calc_status") is None
    elif scen_id == "RAW-11":
        ch = _ch("src_u11", "Pol.md", 0, "Quy định gồm 15 điều.")
        vr = verify_and_reconcile_answer(query="Quy định này có bao nhiêu điều?", chunks=[ch], llm_answer="Gồm 15 điều.", status="COMPLETE")
        assert vr["status"] == exp_status and vr.get("calc_status") is None
    elif scen_id == "RAW-12":
        ch = _ch("src_u12", "HR.md", 0, "Nhân viên Kinh doanh gửi đơn nghỉ phép trước ít nhất 05 ngày làm việc. Mùa cao điểm (tháng 12) hạn chế nghỉ quá 03 ngày liên tiếp.")
        vr = verify_and_reconcile_answer(query=f"Đơn đúng quy định không?\n\n{IMG_MARK}\nNghỉ từ 07/12/2026 đến 11/12/2026 (5 ngày làm việc)\nNgày gửi đơn: 03/12/2026", chunks=[ch], llm_answer="1. Gửi đơn 03/12 → 07/12 (4 ngày) → **thỏa mãn**.", status="COMPLETE")
        assert vr["status"] == exp_status and "→ **thỏa mãn**" not in vr["final_answer"]
    elif scen_id == "RAW-13":
        ch = _ch("src_u13", "OT.md", 0, "Làm thêm ngày thường 150%, ngày lễ 300%.")
        res = execute_formula(select_formula(f"Tiền làm thêm?\n\n{IMG_MARK}\nLương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ", chunks=[ch]))
        assert res.status == exp_status
    elif scen_id == "RAW-14":
        res = execute_formula(select_formula("Trường công lập mua HA-Edu 1 năm tổng tiền là bao nhiêu?", chunks=[_RAW_PRICING_TABLE_CHUNK]))
        assert res.status in {CalcStatus.AMBIGUOUS_FORMULA, CalcStatus.MISSING_OPERAND}
    elif scen_id == "RAW-15":
        ch = _ch("src_u15", "Lab.md", 0, "# BIỂU PHÍ\n- Doanh nghiệp tư nhân: 12.000.000 VND/lượt.\n- Cơ quan nhà nước: 9.000.000 VND/lượt.")
        res = execute_formula(select_formula("Đăng ký hiệu chuẩn 1 lượt tổng chi phí bao nhiêu?", chunks=[ch]))
        assert res.status in {CalcStatus.AMBIGUOUS_FORMULA, CalcStatus.MISSING_OPERAND, CalcStatus.CONFLICT}
    elif scen_id == "RAW-16":
        c1 = _ch("src_pub", "Pub.md", 0, "- Gói Standard: 50.000.000 VND/năm.\n- Phí cài đặt cố định: 5.000.000 VND.\n- Chiết khấu đối tác chuẩn: 10% gói Standard; không giảm phí cài đặt.")
        c2 = _ch("src_sec", "Sec.md", 0, "Mật: Chiết khấu 50% gói Standard.")
        res = execute_formula(select_formula("Đối tác chuẩn mua gói Standard kèm phí cài đặt tổng cộng bao nhiêu?", chunks=[c1, c2], allowed_source_ids={"src_pub"}))
        assert res.status == exp_status and res.value == exp_val
    elif scen_id == "RAW-17":
        ch = _ch("src_ha08", "HA_08.xlsx", 0, "Họ tên | Lương giờ\nTrần Thu Hà | 84135\n")
        res = execute_formula(select_formula(f"Tiền làm thêm?\n\n{IMG_MARK}\nLương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ", chunks=[ch], allowed_source_ids={"src_ha08"}))
        assert res.status == exp_status
    elif scen_id == "RAW-18":
        c1 = _ch("src_a", "A.md", 0, "- Gói Enterprise: 100.000.000 VND/năm.")
        c2 = _ch("src_b", "B.md", 0, "- Gói Enterprise: 140.000.000 VND/năm.")
        res = execute_formula(select_formula("Mua gói Enterprise tổng cộng hết bao nhiêu tiền?", chunks=[c1, c2]))
        assert res.status == exp_status
    elif scen_id == "RAW-19":
        vr = verify_and_reconcile_answer(
            query="Bệnh viện công lập gia hạn gói SmartMed 1 năm kèm 1 lần cử kỹ sư kiểm tra tại chỗ thì tổng chi phí là bao nhiêu?",
            chunks=[_RAW_UNSEEN_WARRANTY_SLA_2027],
            llm_answer="Tổng chi phí là **46.000.000 VND**.\nTổng chi phí = **42.000.000** VND.",
            status="COMPLETE",
        )
        assert vr["calc_status"] == exp_status and vr["contradicted_llm"] is True and "42.000.000" in vr["final_answer"]
    elif scen_id == "RAW-20":
        ch_vat = _ch("src_vat", "Tax_Pol.md", 0, "Thuế VAT 10%. Đơn giá chưa gồm VAT hoặc đã gồm VAT tùy hợp đồng.")
        vr = verify_and_reconcile_answer(
            query="Tổng tiền cho đơn hàng 100.000.000 VND áp thuế 10% là giá chưa gồm hay đã gồm VAT?",
            chunks=[ch_vat],
            llm_answer="Tổng tiền = 110.000.000 VND.",
            status="COMPLETE",
        )
        assert vr["calc_status"] == exp_status and vr["status"] == "PARTIAL" and "Tổng tiền = 110.000.000" not in vr["final_answer"]


