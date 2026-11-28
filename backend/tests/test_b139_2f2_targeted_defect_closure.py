"""B139.2F2 Test-First Suite: Targeted Real-AI Defect Closure (Zero Ollama).

RED -> GREEN test suite covering:
- FIX-01: S3 planning evidence preservation (decomposition/retrieval/completeness/budget/nonlocal snapshot)
- FIX-02: Natural-language unit extraction ('08 giờ trong 01 ngày', EN equivalents, weekly/scope distinction)
- FIX-03: Robust structured numerical claim reconciliation ('4.000 sinh viên', EN/VN, tables, 36000000 vs 36000000.0)
- FIX-04: Rule verdict & prose/bullet/stream/persisted consistency (generalized, zero company hardcoding)
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
import re
from unittest.mock import patch

import pytest

from app.core.answer_checks import IMG_MARK, check_product_evidence_claims
from app.core.formula_engine import CalcStatus, execute_formula, select_formula
from app.core.structured_evidence import EvidenceRole, ValidationStatus, extract_structured_evidence
from app.core.types import ProviderResult, SourceChunk, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.registry import use_pack
from app.research.verified_reasoning import verify_and_reconcile_answer
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


# ==============================================================================
# FIX-01: S3 PLANNING EVIDENCE PRESERVATION (MULTI-CHUNK PRICING + NONLOCAL FIX)
# ==============================================================================


class _PlanningPricingFake(FakeProvider):
    """Simulates S3 planning translating goal to English & omitting 5% discount in worker/synth."""

    name = "fake"
    model = "fake-planning"
    supports_streaming = True
    supports_num_ctx = True
    supports_per_call_output_tokens = True
    supports_per_call_timeout = True

    def __init__(self, pricing_chunk_id: str):
        self.pricing_chunk_id = pricing_chunk_id
        self.worker_seen_evidence_ids: list[str] = []

    async def generate(self, *, system, user, **kw):
        if "OBLIGATION_CONCERN_EXTRACTOR" in system.upper():
            return await super().generate(system=system, user=user)
        if "TASK_PLAN_BUILDER" in system.upper() or "TASK_DECOMPOSER" in system.upper():
            return ProviderResult(
                json.dumps({
                    "tasks": [{
                        "task_id": "t1",
                        "goal": "Calculate total first-year cost for 4000 seats including onboarding fee for a public hospital",
                        "domain": "analyst",
                        "depends_on": [],
                        "evidence_needs": ["Tier pricing table", "Public policy discount and approval rules"],
                    }]
                }, ensure_ascii=False),
                Usage(15, 15),
            )
        return ProviderResult("Tổng tiền năm đầu là 310.000.000 VND.", Usage(10, 10))

    async def generate_grounded(self, *, system, user, evidence_ids, on_text=None, **kw):
        self.worker_seen_evidence_ids = list(evidence_ids)
        ans = f"Tổng tiền cho 4.000 tài khoản là **310.478.564,31** đồng [{self.pricing_chunk_id}]."
        return ProviderResult(
            json.dumps({"status": "COMPLETE", "answer": ans, "citations": [self.pricing_chunk_id], "missing_information": []}, ensure_ascii=False),
            Usage(20, 20),
        )

    async def generate_structured(self, *, system, user, response_schema=None, on_text=None, **kw):
        props = (response_schema or {}).get("properties") or {}
        if "obligations" in props:
            return await super().generate(system="OBLIGATION_CONCERN_EXTRACTOR", user=user)
        if "tasks" in props:
            return ProviderResult(
                json.dumps({
                    "tasks": [{
                        "task_id": "t1",
                        "goal": "Calculate total first-year cost for 4000 seats including onboarding fee for a public hospital",
                        "domain": "analyst",
                        "depends_on": [],
                        "evidence_needs": ["Tier pricing table", "Public policy discount and approval rules"],
                    }]
                }, ensure_ascii=False),
                Usage(15, 15),
            )
        ans = f"Tổng tiền năm đầu cho 4.000 tài khoản là **310.478.564,31** đồng [{self.pricing_chunk_id}]."
        return ProviderResult(json.dumps({"answer": ans}, ensure_ascii=False), Usage(20, 20))


def test_fix01_red_s3_planning_preserves_adjacent_discount_chunk_and_populates_pipeline_grounding(tmp_path):
    """Unseen multi-chunk doc where c0=table, c1=unrelated SLA filler, c2=public discount+approval.

    Reproduces S3 planning dropping c2 when top_k/candidates only pick c0+c1 AND pipeline grounded_chunks_snapshot staying empty.
    """
    st = SourceStore(str(tmp_path / "src_s3"))
    c0_txt = (
        "# BẢNG GIÁ NỀN TẢNG QUẢN TRỊ Y TẾ MEDI-OPS 2027\n"
        "| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí triển khai một lần |\n"
        "|---|---|---|---|---|\n"
        "| MediOps | Cơ sở dưới 3.000 tài khoản | 120.000.000 đ | năm | 30.000.000 đ |\n"
        "| MediOps | Cơ sở từ 3.000 tài khoản | 260.000.000 đ | năm | 50.000.000 đ |\n"
    )
    c1_txt = (
        "## 3. Cam kết vận hành và sao lưu định kỳ\n"
        "Hệ thống sao lưu dữ liệu mỗi 06 giờ tại trung tâm dữ liệu dự phòng đạt chuẩn ISO-27001. " * 4
    )
    c2_txt = (
        "## 4. Chính sách chiết khấu và thẩm quyền phê duyệt\n"
        "| Mức chiết khấu | Thẩm quyền phê duyệt |\n"
        "|---|---|\n"
        "| Đến 10% | Trưởng nhóm Kinh doanh |\n"
        "| Trên 10% | Giám đốc Kinh doanh |\n\n"
        "- Khách hàng bệnh viện công lập được chiết khấu 5% trên đơn giá niêm yết; không chiết khấu phí triển khai một lần.\n"
    )
    s_doc = st.import_text("MediOps_Policy_2027.md", f"{c0_txt}\n\n{c1_txt}\n\n{c2_txt}")
    chunks = st.chunks([s_doc["source_id"]])
    # Split cleanly if import_text merged chunks: create explicit multi-chunk store for deterministic top_k=2 test
    assert len(chunks) >= 1
    ch0 = _ch(s_doc["source_id"], "MediOps_Policy_2027.md", 0, c0_txt, score=0.92)
    ch1 = _ch(s_doc["source_id"], "MediOps_Policy_2027.md", 1, c1_txt, score=0.80)
    ch2 = _ch(s_doc["source_id"], "MediOps_Policy_2027.md", 2, c2_txt, score=0.40)

    st_other = st.import_text("Secret_Promo.md", "Khuyến mãi nội bộ bí mật: giảm 40% toàn bộ gói MediOps.")
    sec_ch = _ch(st_other["source_id"], "Secret_Promo.md", 0, "Khuyến mãi nội bộ bí mật: giảm 40% toàn bộ gói MediOps.", score=0.95)

    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "runs_s3")))
    fake = _PlanningPricingFake(ch0.chunk_id)
    q = (
        "Phân tích điều khoản hợp đồng và tính tổng tiền năm đầu khi một bệnh viện công lập mua gói MediOps "
        "cho 4.000 tài khoản kèm phí triển khai (không có chiết khấu khác ngoài chính sách công lập)?"
    )

    # Simulate Qdrant/hybrid initial retrieval returning ONLY ch0 & ch1 (missing sibling c2!) within TASK_TOP_K=2
    with (
        patch.dict("os.environ", {
            "IMPLEMENTATION_PROFILE": "m2",
            "PRODUCT_STRUCTURED_EVIDENCE": "on",
            "PRODUCT_ADVANCED_REASONING": "on",
        }),
        patch("app.research.pipeline.get_provider", return_value=fake),
        patch.object(st, "chunks", return_value=[ch0, ch1, ch2, sec_ch]),
        patch.object(pipe, "_retrieve_candidates", return_value=[ch0, ch1]),
    ):
        run = asyncio.run(
            pipe.run(q, condition="C", provider_name="fake", domain_pack="office", source_ids=[s_doc["source_id"]], product_mode=True)
        )

    assert ch2.chunk_id in fake.worker_seen_evidence_ids, f"Worker missed sibling discount chunk c2! Saw={fake.worker_seen_evidence_ids}"
    assert sec_ch.chunk_id not in fake.worker_seen_evidence_ids
    se_ev = next(e for e in run["events"] if e["stage"] == "structured_evidence_grounding")
    assert se_ev["role_counts"].get("OFFICIAL_RULE", 0) > 0, f"Pipeline grounding snapshot was empty! {se_ev}"
    vr_ev = next(e for e in run["events"] if e["stage"] == "verified_reasoning")
    assert vr_ev["calc_status"] == CalcStatus.VERIFIED, f"Expected VERIFIED at pipeline finish, got {vr_ev}"
    # 260M * 0.95 + 50M = 297,000,000 VND
    assert "297.000.000" in run["answer"]
    assert "310.478.564,31" not in run["answer"]


# ==============================================================================
# FIX-02: NATURAL LANGUAGE UNIT EXTRACTION ('08 giờ trong 01 ngày', EN/VI)
# ==============================================================================


@pytest.mark.parametrize(
    "doc_phrase",
    [
        "Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày và không quá 48 giờ trong 01 tuần.",
        "Thời giờ làm việc bình thường là 8 giờ mỗi ngày (không quá 48 giờ/tuần).",
        "Quy định công ty: làm việc chuẩn 8 giờ/ngày từ thứ Hai đến thứ Sáu.",
        "Thời lượng làm việc hành chính: 8 tiếng một ngày.",
        "Standard working hours shall not exceed Eight hours per day and 40 hours per week.",
        "Normal working schedule is 8 hours in one working day.",
    ],
)
def test_fix02_red_natural_language_working_hours_per_day_extracted_distinct_from_weekly(doc_phrase: str):
    """All grounded VN/EN working-hours-per-day phrasings must yield hours_per_day=8 without picking up 48h/week."""
    ch = _ch("src_labor", "Labor_Rule.pdf", 0, doc_phrase, doc_type="legal_doc")
    items = extract_structured_evidence([ch])
    hpd = [it for it in items if it.attribute == "hours_per_day" and it.unit == "hour/day"]
    assert len(hpd) == 1, f"Failed on phrase={doc_phrase!r}; extracted={[(i.attribute, i.value, i.unit) for i in items]}"
    assert float(hpd[0].value) == 8.0


def test_fix02_red_reproduce_r03_full_pipeline_with_bll_exact_wording():
    """Exact R-03 wording: '08 giờ trong 01 ngày và 48 giờ trong 01 tuần' -> 3.281.250 VND."""
    ha08 = _ch("src_ha08", "HA_08.xlsx", 0, "## Lam_them\nHọ tên | Lương giờ (đồng)\nTrần Thu Hà | 84135\n")
    blld_c89 = _ch("src_blld", "BLLD_2019.pdf", 89, "Điều 98. Tiền lương làm thêm giờ: Vào ngày thường ít nhất bằng 150%; ngày nghỉ hằng tuần ít nhất bằng 200%; ngày lễ ít nhất bằng 300%.", doc_type="legal_doc")
    blld_c93 = _ch("src_blld", "BLLD_2019.pdf", 93, "Điều 105. Thời giờ làm việc bình thường\n1. Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày và không quá 48 giờ trong 01 tuần.", doc_type="legal_doc")
    q_r03 = (
        f"Tiền làm thêm tối thiểu của người này là bao nhiêu?\n\n{IMG_MARK}\n"
        "Nhân viên: Trần Thu Hà - Lương 17.500.000 đ/tháng - 26 ngày công\n"
        "Làm thêm ngày thường: 10 giờ\nLàm thêm ngày lễ: 8 giờ"
    )
    res = execute_formula(select_formula(q_r03, chunks=[ha08, blld_c89, blld_c93]))
    assert res.status == CalcStatus.VERIFIED, res.reason
    assert res.value == Decimal("3281250")


def test_fix02_red_scope_guard_minor_worker_vs_standard_adult_and_daily_salary():
    """Special minor-worker 07h/day rule must NOT overwrite/conflict adult 08h/day; daily salary / hours_per_day derives cleanly."""
    ch_scope = _ch(
        "src_sc",
        "Labor_2019.pdf",
        0,
        (
            "Điều 105. Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày và 48 giờ trong 01 tuần.\n"
            "Điều 146. Thời giờ làm việc của người chưa thành niên từ đủ 15 tuổi đến dưới 18 tuổi không được quá 08 giờ trong 01 ngày; "
            "người chưa đủ 15 tuổi không được quá 04 giờ trong 01 ngày.\n"
            "Làm thêm ngày thường ít nhất 150%, ngày lễ ít nhất 300%.\n"
        ),
        doc_type="legal_doc",
    )
    q = (
        f"Tiền làm thêm tối thiểu của nhân viên là bao nhiêu?\n\n{IMG_MARK}\n"
        "Lương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ\nLàm thêm ngày lễ: 8 giờ"
    )
    res = execute_formula(select_formula(q, chunks=[ch_scope]))
    assert res.status == CalcStatus.VERIFIED, res.reason
    assert res.value == Decimal("3281250")


# ==============================================================================
# FIX-03: ROBUST NUMERICAL CLAIM RECONCILIATION (NO DOT TRUNCATION / NO .0 BUG)
# ==============================================================================


def test_fix03_red_dot_in_4000_sinh_vien_still_retracts_310_million_claim_and_tables():
    """Must strip 'Tổng tiền năm đầu cho 4.000 sinh viên HA-Edu là **310.478.564,31** đồng' + contradicting tables."""
    ch0 = _ch(
        "src_ha02",
        "HA_02.md",
        0,
        "| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí triển khai |\n|---|---|---|---|---|\n| HA-Edu | Từ 3.000 sinh viên | 260.000.000 đ | năm | 50.000.000 đ |",
    )
    ch2 = _ch("src_ha02", "HA_02.md", 2, "- Khách hàng là trường đại học công lập được thêm 5% chiết khấu; không chiết khấu phí triển khai.")
    q = "Trường đại học công lập mua gói HA-Edu cho 4.000 sinh viên hợp đồng 1 năm gồm phí triển khai thì tổng tiền là bao nhiêu?"
    llm_bug = (
        "Tổng tiền năm đầu cho 4.000 sinh viên HA-Edu là **310.478.564,31** đồng.\n\n"
        "| Hạng mục | Thành tiền |\n|---|---|\n| Tổng cộng năm đầu | **310.478.564,31 đồng** |\n\n"
        "Mức chiết khấu 5% cho trường công lập hợp lệ."
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[ch0, ch2], llm_answer=llm_bug, status="COMPLETE")
    assert vr["applied"] is True
    assert vr["calc_status"] == CalcStatus.VERIFIED
    assert vr["contradicted_llm"] is True
    assert "297.000.000" in vr["final_answer"]
    assert "310.478.564,31" not in vr["final_answer"]


def test_fix03_red_verified_intermediate_36m_float_does_not_trigger_can_kiem_tra_lai():
    """CASE-05: 40M * (1 - 10%) = 36.000.000 VND must NOT produce '36000000 không có nguyên văn -> PARTIAL'."""
    doc = _ch(
        "src_med",
        "Warranty_SLA_2027.md",
        0,
        (
            "# CHÍNH SÁCH 2027\nHiệu lực từ 01/02/2027.\n"
            "- Phí gói gia hạn SmartMed 1 năm: 40.000.000 VND/năm.\n"
            "- Phí cử kỹ sư kiểm tra tại chỗ (cố định): 6.000.000 VND/lần.\n"
            "- Bệnh viện công lập được chiết khấu 10% phí gói gia hạn; không chiết khấu phí cử kỹ sư.\n"
        ),
    )
    q = "Bệnh viện công lập gia hạn gói SmartMed 1 năm kèm 1 lần cử kỹ sư kiểm tra tại chỗ thì tổng chi phí là bao nhiêu và hiệu lực từ ngày nào?"
    llm = "Tổng chi phí là **46.000.000 VND**.\nHiệu lực từ ngày 01/02/2027."
    vr = verify_and_reconcile_answer(query=q, chunks=[doc], llm_answer=llm, status="COMPLETE")
    ignored = set(vr.get("ignored_identifier_numbers") or [])
    status, checked_ans, bad_nums, _ = check_product_evidence_claims(
        "COMPLETE",
        vr["final_answer"],
        doc.text,
        q,
        [],
        evidence_chunks=[doc],
        ignored_identifiers=ignored,
    )
    assert "36000000" not in bad_nums, f"False positive unsupported number 36000000! bad={bad_nums}"
    assert "Cần kiểm tra lại" not in checked_ans
    assert status == "COMPLETE"
    assert "42.000.000" in checked_ans
    assert "01/02/2027" in checked_ans


# ==============================================================================
# FIX-04: RULE VERDICT & PROSE / BULLET / STREAM CONSISTENCY
# ==============================================================================


def test_fix04_red_rule_reconciler_strips_contradictory_bullets_and_ungrounded_conclusion():
    """Exact B139.2R R-02 failure: bullet '→ **đúng quy định**', 'chưa có → **không vi phạm**', & 'Đã gửi đơn trước...' MUST be reconciled."""
    pol_a = _ch(
        "src_pol_a",
        "Company_Handbook.docx",
        3,
        "4. Người lao động gửi đơn xin phép trước ít nhất 03 ngày làm việc. Nghỉ từ 05 ngày liên tiếp phải được Trưởng phòng và Giám đốc Nhân sự phê duyệt.",
    )
    pol_b = _ch(
        "src_pol_b",
        "Dept_Rules.md",
        3,
        (
            "## Quy định nghỉ phép bộ phận Kinh doanh\n"
            "- Nhân viên gửi đơn trước ít nhất 05 ngày làm việc và phải bàn giao công việc cho người trực thay.\n"
            "- Mùa cao điểm (tháng 8 đến tháng 10, tháng 12) hạn chế nghỉ quá 03 ngày liên tiếp.\n"
        ),
    )
    q = (
        f"Đơn này có đúng quy định và nội quy không?\n\n{IMG_MARK}\n"
        "ĐƠN XIN NGHỈ PHÉP\nPhạm Minh Hải - Phòng Kinh doanh\n"
        "Xin nghỉ từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc)\n"
        "Ngày gửi đơn: thứ Năm 03/12/2026\nNgười nhận bàn giao: chưa có"
    )
    llm_contradiction = (
        "Đơn này chưa đủ điều kiện:\n"
        "**Phân tích**:\n"
        "- Số ngày nghỉ: 5 ngày (đúng yêu cầu)\n"
        "- Ngày gửi đơn: 03/12/2026 (trước 03 ngày so với ngày nghỉ đầu tiên 07/12/2026) → **đúng quy định**\n"
        "- Người nhận bàn giao: chưa có → **không vi phạm** (quy định chỉ yêu cầu bàn giao khi nghỉ từ 05 ngày)\n\n"
        "### Kết luận\n"
        "Đơn xin nghỉ phép đạt yêu cầu vì:\n"
        "- Đã gửi đơn trước ít nhất 03 ngày làm việc\n"
        "- Số ngày nghỉ 5 ngày thuộc phạm vi được phê duyệt [src_pol_a_c0003]\n"
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[pol_a, pol_b], llm_answer=llm_contradiction, status="COMPLETE")
    ans = vr["final_answer"]
    assert vr["applied"] is True
    assert vr["status"] == "PARTIAL"
    assert "→ **đúng quy định**" not in ans
    assert "→ **không vi phạm**" not in ans
    assert not re.search(r"(?<!không\s)(?<!chưa\s)\bđạt yêu cầu\b", ans)
    assert "chưa có" in ans.lower()
    assert "không thỏa mãn" in ans.lower() or "chưa đáp ứng" in ans.lower()
    assert "[src_pol_a_c0003]" in ans


# ==============================================================================
# SECTION 6: 22 HELD-OUT RAW-CONTEXT GENERALIZATION SCENARIOS (POS + NEG)
# ==============================================================================

_SEC6_HELD_OUT = [
    ("F2-01", "multi_doc_pricing", "Unseen multi-doc pricing+discount S3 merge", "VERIFIED"),
    ("F2-02", "multi_doc_pricing", "Conflicting official rates across docs -> CONFLICT", "CONFLICT"),
    ("F2-03", "missing_planning_ev", "S3 planning misses sibling c2 -> completeness rescue", "VERIFIED"),
    ("F2-04", "missing_planning_ev", "Truly missing pricing/rate evidence -> safe MISSING", "MISSING_OPERAND"),
    ("F2-05", "unit_conversion", "90 minutes at 400k VND/hour -> 600k VND", "VERIFIED"),
    ("F2-06", "unit_conversion", "VND/day * hour mismatch -> INVALID_UNIT", "INVALID_UNIT"),
    ("F2-07", "nl_working_hours", "08 gio trong 01 ngay & 48 gio trong 01 tuan -> 3.281.250", "VERIFIED"),
    ("F2-08", "nl_working_hours", "Eight hours per day + daily salary + 150% OT -> 600k", "VERIFIED"),
    ("F2-09", "nl_working_hours", "Weekly hours present but daily norm absent -> MISSING_OPERAND", "MISSING_OPERAND"),
    ("F2-10", "number_formats", "VN/EN formats & 36000000.0==36000000 zero false PARTIAL", "COMPLETE"),
    ("F2-11", "number_formats", "Ambiguous '1.500' without unit/locale -> AMBIGUOUS", "AMBIGUOUS"),
    ("F2-12", "numeric_reconcile", "Dot in '4.000 sinh vien' + wrong table row stripped -> 297M", "VERIFIED"),
    ("F2-13", "numeric_reconcile", "46M headline overridden -> 42M preserving 01/02/2027", "VERIFIED"),
    ("F2-14", "numeric_reconcile", "MISSING_OPERAND cleans orphaned empty comparison table", "MISSING_OPERAND"),
    ("F2-15", "rule_consistency", "Pipeline stream + persisted rule verdict consistency", "PARTIAL"),
    ("F2-16", "rule_consistency", "Approval threshold unmet record stays UNKNOWN never approved", "PARTIAL"),
    ("F2-17", "rule_consistency", "Valid 5 working days notice >=3 not falsely flagged NOT_MET", "NOT_MET_ABSENT"),
    ("F2-18", "missing_evidence", "Two-part query preserves verified date despite partial calc gap", "DATE_PRESERVED"),
    ("F2-19", "missing_evidence", "Historical illustrative example 50% ignored vs official 10%", "VERIFIED"),
    ("F2-20", "acl_security", "Unauthorized secret source blocked in S3 planning & completeness", "ACL_BLOCKED"),
    ("F2-21", "acl_security", "Isolated payroll table without external labor doc -> MISSING", "MISSING_OPERAND"),
    ("F2-22", "factual_lookup", "ND 13/2023 lookup bypasses calc cleanly with status COMPLETE", "COMPLETE"),
]


@pytest.mark.parametrize("scen_id,category,desc,expected_outcome", _SEC6_HELD_OUT, ids=[s[0] for s in _SEC6_HELD_OUT])
def test_sec6_22_heldout_raw_context_matrix(scen_id: str, category: str, desc: str, expected_outcome: str, tmp_path):
    if scen_id == "F2-01":
        c_tbl = _ch("src_m1", "Price_Catalog.md", 0, "| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí khởi tạo một lần |\n|---|---|---|---|---|\n| CoreMed | Từ 2.000 tài khoản | 200.000.000 VND | năm | 40.000.000 VND |")
        c_pol = _ch("src_m2", "Discount_Policy.md", 0, "- Khách hàng bệnh viện công được giảm 10% đơn giá niêm yết CoreMed; không giảm phí khởi tạo một lần.")
        res = execute_formula(select_formula("Bệnh viện công mua gói CoreMed cho 2.500 tài khoản kèm phí khởi tạo tổng tiền là bao nhiêu?", chunks=[c_tbl, c_pol]))
        assert res.status == CalcStatus.VERIFIED and res.value == Decimal("220000000")
    elif scen_id == "F2-02":
        c1 = _ch("src_a", "A.md", 0, "- Gói AlphaNet: 100.000.000 VND/năm.")
        c2 = _ch("src_b", "B.md", 0, "- Gói AlphaNet: 135.000.000 VND/năm.")
        res = execute_formula(select_formula("Mua gói AlphaNet 1 năm hết bao nhiêu tiền?", chunks=[c1, c2]))
        assert res.status == CalcStatus.CONFLICT
    elif scen_id == "F2-03":
        from app.retrieval.evidence_completeness import complete_missing_evidence
        t0 = _ch("src_p", "Pricing.md", 0, "| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí triển khai |\n|---|---|---|---|---|\n| SuiteX | Từ 1.000 tài khoản | 300.000.000 đ | năm | 20.000.000 đ |")
        t1 = _ch("src_p", "Pricing.md", 1, "## Vận hành\nHỗ trợ 24/7.")
        t2 = _ch("src_p", "Pricing.md", 2, "## Chính sách chiết khấu\n- Cơ quan nhà nước được giảm 10%; không giảm phí triển khai.")
        rescued, tr = complete_missing_evidence(query="Cơ quan nhà nước mua SuiteX 1.200 tài khoản tổng tiền gồm phí triển khai là bao nhiêu?", selected=[t0, t1], all_chunks=[t0, t1, t2], max_tokens=2000)
        res = execute_formula(select_formula("Cơ quan nhà nước mua SuiteX 1.200 tài khoản tổng tiền gồm phí triển khai là bao nhiêu?", chunks=rescued))
        assert t2.chunk_id in {c.chunk_id for c in rescued} and res.status == CalcStatus.VERIFIED and res.value == Decimal("290000000")
    elif scen_id == "F2-04":
        ch = _ch("src_empty", "Intro.md", 0, "Giới thiệu sản phẩm nền tảng số.")
        res = execute_formula(select_formula("Tổng chi phí gia hạn 1 năm là bao nhiêu?", chunks=[ch]))
        assert res.status == CalcStatus.MISSING_OPERAND
    elif scen_id == "F2-05":
        ch = _ch("src_rate", "Consult.md", 0, "Phí tư vấn kỹ thuật: 400.000 VND/giờ.")
        res = execute_formula(select_formula("Quy đổi 90 phút sang giờ và tính phí tư vấn là bao nhiêu?", chunks=[ch]))
        assert res.status == CalcStatus.VERIFIED and res.value == Decimal("600000")
    elif scen_id == "F2-06":
        res = execute_formula(select_formula("Unit test", formula="UNIT_MISMATCH_TEST", left_unit="VND/day", right_unit="hour"))
        assert res.status == CalcStatus.INVALID_UNIT
    elif scen_id == "F2-07":
        ha = _ch("src_ha", "TS.xlsx", 0, "Họ tên | Lương giờ (đồng)\nTrần Thu Hà | 84135\n")
        law = _ch("src_law", "BLLD.pdf", 0, "Điều 98: ngày thường ít nhất 150%, ngày lễ 300%. Điều 105: bình thường không quá 08 giờ trong 01 ngày và 48 giờ trong 01 tuần.", doc_type="legal_doc")
        q = f"Tiền làm thêm tối thiểu?\n\n{IMG_MARK}\nLương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ\nLàm thêm ngày lễ: 8 giờ"
        res = execute_formula(select_formula(q, chunks=[ha, law]))
        assert res.status == CalcStatus.VERIFIED and res.value == Decimal("3281250")
    elif scen_id == "F2-08":
        law = _ch("src_law_en", "Labor_EN.pdf", 0, "Normal working schedule is Eight hours per day. Overtime on weekday is 150%.", doc_type="legal_doc")
        q = f"Tính tiền làm thêm?\n\n{IMG_MARK}\nLương ngày: 800.000 VND/ngày\nLàm thêm ngày thường: 4 giờ"
        res = execute_formula(select_formula(q, chunks=[law]))
        assert res.status == CalcStatus.VERIFIED and res.value == Decimal("600000")
    elif scen_id == "F2-09":
        law = _ch("src_wk_only", "Labor_Wk.pdf", 0, "Standard workweek is 40 hours per week. Weekday overtime 150%.", doc_type="legal_doc")
        q = f"Tiền làm thêm?\n\n{IMG_MARK}\nLương 20.000.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 5 giờ"
        res = execute_formula(select_formula(q, chunks=[law]))
        assert res.status == CalcStatus.MISSING_OPERAND
    elif scen_id == "F2-10":
        from app.core.structured_evidence import parse_localized_number
        assert parse_localized_number("1.250,50", locale_hint="vi", unit_hint="VND")[0] == 1250.5
        assert parse_localized_number("1,250,000.50", locale_hint="en", unit_hint="USD")[0] == 1250000.5
        doc = _ch("src_s10", "Fee.md", 0, "- Phí gói năm: 40.000.000 VND/năm.\n- Phí kiểm tra: 6.000.000 VND/lần.\n- Bệnh viện công được giảm 10% phí gói năm; không giảm phí kiểm tra.")
        vr = verify_and_reconcile_answer(query="Bệnh viện công gia hạn 1 năm kèm kiểm tra hết bao nhiêu tiền?", chunks=[doc], llm_answer="Tổng tiền: **42.000.000 VND**.", status="COMPLETE")
        st_chk, ans_chk, bad_n, _ = check_product_evidence_claims("COMPLETE", vr["final_answer"], doc.text, "Bệnh viện công gia hạn 1 năm kèm kiểm tra hết bao nhiêu tiền?", [], evidence_chunks=[doc], ignored_identifiers=set(vr["ignored_identifier_numbers"]))
        assert not bad_n and st_chk == "COMPLETE"
    elif scen_id == "F2-11":
        from app.core.structured_evidence import parse_localized_number
        _, _, st_amb = parse_localized_number("1.500", locale_hint="auto", unit_hint="")
        assert st_amb == ValidationStatus.AMBIGUOUS
    elif scen_id == "F2-12":
        c0 = _ch("src_p", "Cat.md", 0, "| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí triển khai |\n|---|---|---|---|---|\n| HA-Edu | Từ 3.000 sinh viên | 260.000.000 đ | năm | 50.000.000 đ |")
        c2 = _ch("src_p", "Cat.md", 2, "- Trường đại học công lập được giảm 5%; không giảm phí triển khai.")
        vr = verify_and_reconcile_answer(
            query="Trường đại học công lập mua HA-Edu cho 4.000 sinh viên tổng tiền là bao nhiêu?",
            chunks=[c0, c2],
            llm_answer="Tổng tiền năm đầu cho 4.000 sinh viên là **310.478.564,31** đồng.\n| Tổng | **310.478.564,31** đ |",
            status="COMPLETE",
        )
        assert vr["calc_status"] == CalcStatus.VERIFIED and "297.000.000" in vr["final_answer"] and "310.478.564,31" not in vr["final_answer"]
    elif scen_id == "F2-13":
        doc = _ch("src_m", "Med.md", 0, "Hiệu lực từ 01/02/2027.\n- Phí gói SmartMed: 40.000.000 VND/năm.\n- Phí kiểm tra: 6.000.000 VND.\n- Bệnh viện công giảm 10% phí gói; không giảm phí kiểm tra.")
        vr = verify_and_reconcile_answer(
            query="Bệnh viện công gia hạn SmartMed 1 năm kèm kiểm tra hết bao nhiêu tiền và hiệu lực từ ngày nào?",
            chunks=[doc],
            llm_answer="Tổng tiền là **46.000.000 VND**. Hiệu lực từ 01/02/2027.",
            status="COMPLETE",
        )
        assert "42.000.000" in vr["final_answer"] and "46.000.000" not in vr["final_answer"] and "01/02/2027" in vr["final_answer"]
    elif scen_id == "F2-14":
        doc = _ch("src_ot", "Labor.md", 0, "Làm thêm ngày thường 150%.")
        llm = "### So sánh\n| Loại | Tiền |\n|---|---|\n| Ngày thường | 841.350 đ |\n\n**Kết luận**: đạt vì:\n"
        vr = verify_and_reconcile_answer(query=f"Tiền làm thêm?\n\n{IMG_MARK}\nLương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ", chunks=[doc], llm_answer=llm, status="COMPLETE")
        assert vr["calc_status"] == CalcStatus.MISSING_OPERAND and "| Loại |" not in vr["final_answer"] and "841.350" not in vr["final_answer"]
    elif scen_id == "F2-15":
        st = SourceStore(str(tmp_path / "src_r15"))
        pol = st.import_text("Dept_Policy.md", "Gửi đơn nghỉ phép trước ít nhất 05 ngày làm việc và phải bàn giao công việc cho người trực thay.")
        cid = st.chunks([pol["source_id"]])[0].chunk_id
        pipe = ResearchPipeline(st, RunStore(str(tmp_path / "runs_r15")))

        class _BadRuleFake(FakeProvider):
            name = "fake"
            model = "fake-r"
            supports_streaming = True
            async def generate_grounded(self, *, system, user, evidence_ids, on_text=None, **kw):
                ans = f"- Ngày gửi đơn: 03/12/2026 → **đúng quy định** [{cid}]\n- Bàn giao: chưa có → **không vi phạm**"
                return ProviderResult(json.dumps({"status": "COMPLETE", "answer": ans, "citations": [cid], "missing_information": []}, ensure_ascii=False), Usage(10, 10))

        streamed: list[str] = []
        q = f"Đơn này có đúng quy định không?\n\n{IMG_MARK}\nXin nghỉ từ 07/12/2026 đến 09/12/2026 (3 ngày làm việc)\nNgày gửi đơn: 03/12/2026\nNgười nhận bàn giao: chưa có"
        with (
            patch.dict("os.environ", {"IMPLEMENTATION_PROFILE": "m2", "PRODUCT_STRUCTURED_EVIDENCE": "on", "PRODUCT_ADVANCED_REASONING": "on"}),
            patch("app.research.pipeline.get_provider", return_value=_BadRuleFake()),
            patch("app.research.vanilla.emit_validated_answer", side_effect=lambda txt: streamed.append(txt)),
        ):
            run = asyncio.run(pipe.run(q, condition="C", provider_name="fake", product_mode=True))
        assert run["status"] == "PARTIAL"
        assert streamed and streamed[-1] == run["answer"]
        assert "→ **đúng quy định**" not in run["answer"] and "→ **không vi phạm**" not in run["answer"]
    elif scen_id == "F2-16":
        ch = _ch("src_ap", "Rules.md", 0, "Nghỉ từ 05 ngày liên tiếp trở lên phải được Giám đốc phê duyệt.")
        q = f"Đơn này có đúng quy định không?\n\n{IMG_MARK}\nXin nghỉ từ 01/06/2026 đến 05/06/2026 (5 ngày làm việc)\nNgày gửi đơn: 15/05/2026"
        vr = verify_and_reconcile_answer(query=q, chunks=[ch], llm_answer="Nghỉ 5 ngày → **đã được phê duyệt**.", status="COMPLETE")
        assert vr["status"] == "PARTIAL" and "UNKNOWN" in vr["final_answer"] and "→ **đã được phê duyệt**" not in vr["final_answer"]
    elif scen_id == "F2-17":
        ch = _ch("src_ok", "Rules_OK.md", 0, "Gửi đơn xin phép trước ít nhất 03 ngày làm việc.")
        q = f"Đơn này có đúng quy định không?\n\n{IMG_MARK}\nXin nghỉ từ 08/12/2026 đến 09/12/2026 (2 ngày làm việc)\nNgày gửi đơn: 01/12/2026"
        vr = verify_and_reconcile_answer(query=q, chunks=[ch], llm_answer="- Ngày gửi đơn: 01/12/2026 thỏa mãn trước ít nhất 03 ngày làm việc.", status="COMPLETE")
        assert "NOT_MET" not in vr["final_answer"]
    elif scen_id == "F2-18":
        doc = _ch("src_par", "SLA_Partial.md", 0, "Chính sách có hiệu lực từ 15/03/2027. Phí kiểm tra: chưa công bố bảng giá.")
        vr = verify_and_reconcile_answer(query="Tổng chi phí dịch vụ là bao nhiêu và chính sách có hiệu lực từ ngày nào?", chunks=[doc], llm_answer="Chính sách có hiệu lực từ 15/03/2027.", status="PARTIAL")
        assert "15/03/2027" in vr["final_answer"]
    elif scen_id == "F2-19":
        doc = _ch("src_ex", "Promo.md", 0, "- Gói Pro: 60.000.000 VND/năm.\n- Phí cài đặt: 10.000.000 VND.\n- Cơ quan nhà nước giảm 10% gói Pro; không giảm phí cài đặt.\n- Ví dụ minh họa: từng áp dụng giảm 50% cho bản thử nghiệm.")
        res = execute_formula(select_formula("Cơ quan nhà nước mua gói Pro 1 năm kèm cài đặt hết bao nhiêu tiền?", chunks=[doc]))
        assert res.status == CalcStatus.VERIFIED and res.value == Decimal("64000000")
    elif scen_id == "F2-20":
        c_pub = _ch("src_pub", "Pub.md", 0, "| Sản phẩm | Gói | Đơn giá | Đơn vị tính |\n|---|---|---|---|\n| Vault | Chuẩn | 100.000.000 VND | năm |\n- Khách hàng công lập giảm 5%.")
        c_sec = _ch("src_sec", "Sec.md", 0, "- Khách hàng công lập giảm 50%.")
        res = execute_formula(select_formula("Khách hàng công lập mua gói Vault 1 năm hết bao nhiêu?", chunks=[c_pub, c_sec], allowed_source_ids={"src_pub"}))
        assert res.status == CalcStatus.VERIFIED and res.value == Decimal("95000000")
    elif scen_id == "F2-21":
        ch = _ch("src_iso", "Sheet.xlsx", 0, "Họ tên | Lương giờ\nLê B | 75000\n")
        res = execute_formula(select_formula(f"Tiền làm thêm tối thiểu?\n\n{IMG_MARK}\nLàm thêm ngày thường: 6 giờ", chunks=[ch], allowed_source_ids={"src_iso"}))
        assert res.status == CalcStatus.MISSING_OPERAND
    elif scen_id == "F2-22":
        ch = _ch("src_nd", "ND13.pdf", 0, "Nghị định 13/2023/NĐ-CP: thông báo chậm nhất 72 giờ; hiệu lực từ 01 tháng 7 năm 2023.")
        vr = verify_and_reconcile_answer(query="Theo Nghị định 13/2023/NĐ-CP chậm nhất bao nhiêu giờ phải thông báo và hiệu lực từ ngày nào?", chunks=[ch], llm_answer="Chậm nhất 72 giờ, hiệu lực 01 tháng 7 năm 2023.", status="COMPLETE")
        assert vr["mode"] == "bypassed_general_or_lookup" and vr["status"] == "COMPLETE"

