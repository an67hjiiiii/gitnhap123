"""B139.2 Test-First Suite: Formula Selection, Unit Calculator, Rule Evaluation,
Evidence Completeness & Verified Reasoning (Zero Ollama).

Covers Categories A-T + 24 diverse held-out unseen scenarios across 6 domains
(Enterprise, Education, Technical, Logistics, SaaS, Operational Workflows).
Frozen Oracle: assertions MUST NOT be weakened during implementation.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.core.answer_checks import IMG_MARK
from app.core.formula_engine import (
    CalcStatus,
    FormulaType,
    TierBracket,
    execute_formula,
    safe_eval_decimal_ast,
    select_formula,
)
from app.core.rule_evaluator import (
    RuleGroup,
    RuleLeaf,
    evaluate_rule_tree,
)
from app.core.structured_evidence import EvidenceRole, extract_structured_evidence
from app.core.types import ProviderResult, SourceChunk, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.structured_evidence_hook import advanced_reasoning_enabled
from app.research.verified_reasoning import verify_and_reconcile_answer
from app.retrieval.evidence_completeness import complete_missing_evidence
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _ch(src: str, name: str, idx: int, text: str, *, doc_type: str = "legal_doc", score: float = 0.7) -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{src}_c{idx:04d}",
        source_id=src,
        source_name=name,
        text=text,
        index=idx,
        score=score,
        provenance={"doc_type": doc_type},
    )


# ==============================================================================
# CATEGORIES A, B, C: Pricing, Discount, Fixed/Variable Fees & Tiered Pricing
# ==============================================================================


def test_cat_abc_tiered_pricing_discount_and_non_discountable_fixed_fee():
    doc = _ch(
        "src_tier",
        "Catalog_2027.md",
        0,
        (
            "# BẢNG GIÁ CHÍNH THỨC\n"
            "| Gói | Đơn giá | Phí triển khai cố định |\n"
            "|---|---|---|\n"
            "| Nhỏ (dưới 500 học viên) | 80.000.000 VND/năm | 15.000.000 VND |\n"
            "| Lớn (từ 500 học viên) | 180.000.000 VND/năm | 30.000.000 VND |\n\n"
            "Chính sách ưu đãi: Tổ chức giáo dục công lập được giảm thêm 5% trên đơn giá niêm yết; "
            "không chiết khấu phí triển khai.\n"
        ),
    )
    query = "Học viện công lập đăng ký 650 học viên trong 1 năm thì tổng chi phí năm đầu là bao nhiêu?"
    spec = select_formula(
        query,
        chunks=[doc],
        tier_brackets=[
            TierBracket(label="Nhỏ", min_qty=0, max_qty=500, max_inclusive=False, unit_price=Decimal("80000000"), fixed_fee=Decimal("15000000"), unit="VND/year"),
            TierBracket(label="Lớn", min_qty=500, max_qty=None, min_inclusive=True, unit_price=Decimal("180000000"), fixed_fee=Decimal("30000000"), unit="VND/year"),
        ],
        discount_pct=Decimal("5"),
        discount_applies_to_fixed_fee=False,
    )
    assert spec.formula_type == FormulaType.TIERED_PRICING
    res = execute_formula(spec)
    assert res.status == CalcStatus.VERIFIED
    # 180,000,000 * 0.95 + 30,000,000 = 171,000,000 + 30,000,000 = 201,000,000
    assert res.value == Decimal("201000000")
    assert res.currency == "VND" and res.unit == "VND"
    assert len(res.steps) >= 2


# ==============================================================================
# CATEGORIES D, E: Salary / Overtime & Time / Unit Conversion
# ==============================================================================


def test_cat_de_salary_overtime_and_unit_conversions():
    sal_doc = _ch(
        "src_sal",
        "Labor_Norms.md",
        0,
        "# QUY ĐỊNH LÀM THÊM GIỜ\nGiờ làm việc chuẩn: 8 giờ/ngày. Làm thêm ngày thường: 150%; ngày lễ: 300%.\n",
    )
    q = f"Tiền làm thêm tối thiểu của nhân sự này là bao nhiêu?\n\n{IMG_MARK}\nLương 20.800.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 6 giờ\nLàm thêm ngày lễ: 2 giờ"
    spec = select_formula(q, chunks=[sal_doc])
    assert spec.formula_type == FormulaType.OVERTIME_PAY
    res = execute_formula(spec)
    assert res.status == CalcStatus.VERIFIED
    # Hourly = 20,800,000 / 26 / 8 = 100,000 VND/hour
    # OT = 100,000 * (6 * 1.5 + 2 * 3.0) = 100,000 * 15 = 1,500,000 VND
    assert res.value == Decimal("1500000")

    # Unit & time conversion test: 150 minutes @ 120,000 VND/hour = 2.5h * 120,000 = 300,000 VND
    q_conv = "Quy đổi 150 phút sang giờ và tính phí tư vấn ở mức 120.000 VND/giờ?"
    spec_conv = select_formula(
        q_conv,
        chunks=[_ch("src_fee", "Consulting.md", 0, "Phí tư vấn tiêu chuẩn: 120.000 VND/giờ.")],
    )
    res_conv = execute_formula(spec_conv)
    assert res_conv.status == CalcStatus.VERIFIED
    assert res_conv.value == Decimal("300000")


# ==============================================================================
# CATEGORIES F, G, H, I: Entities, Examples, Ambiguous/Missing & Conflicts
# ==============================================================================


def test_cat_fghi_entities_example_traps_missing_and_conflicts():
    # Missing hours_per_day (refuse silent /8!)
    q_ot_no_hpd = f"Tiền làm thêm là bao nhiêu?\n\n{IMG_MARK}\nLương 17.500.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 10 giờ"
    doc_no_hpd = _ch("src_ot_bare", "OT.md", 0, "Làm thêm ngày thường tối thiểu 150% lương giờ thực trả.")
    spec_missing = select_formula(q_ot_no_hpd, chunks=[doc_no_hpd])
    res_missing = execute_formula(spec_missing)
    assert res_missing.status == CalcStatus.MISSING_OPERAND
    assert "hours_per_day" in res_missing.reason

    # Conflicting discount policies -> CONFLICT
    c1 = _ch("src_p1", "Pol_1.md", 0, "# Chính sách chiết khấu\nGiảm giá gói Cloud: 10%.")
    c2 = _ch("src_p2", "Pol_2.md", 0, "# Chính sách chiết khấu\nGiảm giá gói Cloud: 18%.")
    spec_conf = select_formula("Áp dụng chiết khấu gói Cloud cho đơn 100.000.000 VND?", chunks=[c1, c2])
    res_conf = execute_formula(spec_conf)
    assert res_conf.status == CalcStatus.CONFLICT

    # Historical example trap (22% example) ignored vs official 5%
    c_ex = _ch(
        "src_ex",
        "Sales.md",
        0,
        (
            "# BẢNG GIÁ CHÍNH THỨC\n| Khách hàng | Đơn giá | Chiết khấu |\n|---|---|---|\n"
            "| Nhóm Công | 100.000.000 VND/năm | 5% |\n"
            "Ví dụ minh họa: Khách hàng Alpha năm 2024 từng hưởng chiết khấu 22%.\n"
        ),
    )
    spec_ex = select_formula("Khách hàng thuộc Nhóm Công ký hợp đồng 1 năm giá 100.000.000 VND, sau chiết khấu còn bao nhiêu?", chunks=[c_ex])
    res_ex = execute_formula(spec_ex)
    assert res_ex.status == CalcStatus.VERIFIED
    assert res_ex.value == Decimal("95000000")

    # Ambiguous formula: tax inclusive vs exclusive unclear when both rules appear
    spec_amb = select_formula(
        "Tính tổng thanh toán cho đơn 100.000.000 VND áp thuế 10% hay giá đã gồm thuế?",
        chunks=[_ch("src_tax", "Tax.md", 0, "Thuế VAT 10%. Có hai phương thức: giá chưa gồm VAT hoặc giá đã gồm VAT.")],
    )
    res_amb = execute_formula(spec_amb)
    assert res_amb.status == CalcStatus.AMBIGUOUS_FORMULA


# ==============================================================================
# CATEGORIES J, K, L: Rule Tree, Exceptions, Approvals, AND/OR, Negation
# ==============================================================================


def test_cat_jkl_nested_rule_tree_exceptions_approvals_and_negation():
    # Nested AND(applicability, OR(leaf1, AND(leaf2, NOT(exception)))) + approval UNKNOWN
    tree = RuleGroup(
        op="AND",
        children=[
            RuleLeaf(rule_id="R_APP", description="Nhân sự chính thức", kind="applicability", verdict="MET", case_fact="NV chính thức", chunk_id="s1_c0"),
            RuleGroup(
                op="OR",
                children=[
                    RuleLeaf(rule_id="R_FAST", description="Nghỉ dưới 3 ngày", kind="mandatory", verdict="NOT_MET", case_fact="5 ngày", chunk_id="s1_c1"),
                    RuleGroup(
                        op="AND",
                        children=[
                            RuleLeaf(rule_id="R_ADV", description="Báo trước >= 5 ngày làm việc", kind="mandatory", verdict="MET", case_fact="6 ngày", chunk_id="s1_c1"),
                            RuleLeaf(rule_id="R_PEAK", description="Không rơi vào kỳ cao điểm", kind="exception", negated=True, verdict="MET", case_fact="tháng 12 là kỳ cao điểm", chunk_id="s1_c2"),
                        ],
                    ),
                ],
            ),
            RuleLeaf(rule_id="R_APPR", description="Phê duyệt Giám đốc Nhân sự", kind="approval", verdict="UNKNOWN", case_fact="", approval_roles=["Giám đốc Nhân sự"], chunk_id="s1_c1"),
        ],
    )
    res = evaluate_rule_tree(tree)
    # Peak exception negated=True & MET violation -> inner branch FAILS -> NOT_ELIGIBLE!
    assert res["overall"] == "NOT_ELIGIBLE"

    # Without peak exception violation, approval UNKNOWN keeps overall INSUFFICIENT_INFO (never ELIGIBLE!)
    tree_unk = RuleGroup(
        op="AND",
        children=[
            RuleLeaf(rule_id="R_ADV", description="Báo trước >= 5 ngày", kind="mandatory", verdict="MET", case_fact="6 ngày", chunk_id="s1_c1"),
            RuleLeaf(rule_id="R_APPR", description="Phê duyệt Giám đốc Nhân sự", kind="approval", verdict="UNKNOWN", case_fact="", approval_roles=["Giám đốc Nhân sự"], chunk_id="s1_c1"),
        ],
    )
    res_unk = evaluate_rule_tree(tree_unk)
    assert res_unk["overall"] == "INSUFFICIENT_INFO"


# ==============================================================================
# CATEGORY M & O: Retrieval Completeness Recovery Within ACL & Token Budget
# ==============================================================================


def test_cat_mo_targeted_evidence_completeness_recovers_missing_rule_within_acl():
    # Simulate R-02 style miss: intro chunks retrieved, mid-chunk rule buried below section header,
    # PLUS an unauthorized secret source that MUST NOT be leaked!
    ch_intro = _ch("src_rulebook", "Handbook.md", 0, "# NỘI QUY CÔNG TY\nÁp dụng cho toàn thể nhân viên.")
    ch_cut_head = _ch("src_rulebook", "Handbook.md", 1, "# Điều 3. Thời giờ làm việc\nLàm 40 giờ/tuần.\n\n# Điều 5. Nghỉ phép")
    ch_buried_rule = _ch(
        "src_rulebook",
        "Handbook.md",
        2,
        "4. Người lao động gửi đơn nghỉ phép trước ít nhất 05 ngày làm việc và bàn giao người trực thay.",
    )
    ch_secret = _ch("src_secret", "Executive_Only.md", 0, "Quy định mật về nghỉ phép giám đốc và bàn giao tài sản mật.")

    initial_selected = [ch_intro, ch_cut_head]
    all_authorized = [ch_intro, ch_cut_head, ch_buried_rule, ch_secret]
    recovered, trace = complete_missing_evidence(
        query="Đơn xin nghỉ phép chưa có người bàn giao và gửi trước 2 ngày có đúng quy định không?",
        selected=initial_selected,
        all_chunks=all_authorized,
        allowed_source_ids={"src_rulebook"},  # ACL blocks src_secret!
        max_tokens=2000,
    )
    rec_ids = [c.chunk_id for c in recovered]
    assert "src_rulebook_c0000" in rec_ids and "src_rulebook_c0001" in rec_ids  # Old selected preserved!
    assert "src_rulebook_c0002" in rec_ids  # Buried continuation/rule recovered!
    assert "src_secret_c0000" not in rec_ids  # ACL enforced!
    assert trace["added_count"] >= 1


# ==============================================================================
# CATEGORIES N, P, Q, R: Reconcile LLM Contradiction, Safe AST, Doc IDs, General Q
# ==============================================================================


def test_cat_npqr_llm_contradiction_unsafe_ast_doc_id_and_general_routing():
    # Category P: Reject unsafe AST, huge exponent, excessive depth, division by zero
    for bad_expr in ("__import__('os').system('echo x')", "2**99999", "1/0", "+".join(["1"] * 80)):
        val, err = safe_eval_decimal_ast(bad_expr)
        assert val is None and err is not None

    # Category N: LLM emits wrong formula (*1.05 -> 325.5M) vs verified 201M -> verified overrides!
    doc = _ch(
        "src_tier",
        "Catalog_2027.md",
        0,
        "# BẢNG GIÁ\n- Gói Pro (từ 500 học viên): 180.000.000 VND/năm; phí triển khai 30.000.000 VND; công lập giảm 5%, không giảm phí triển khai.\n",
    )
    vr = verify_and_reconcile_answer(
        query="Học viện công lập 650 học viên 1 năm tổng tiền là bao nhiêu?",
        chunks=[doc],
        llm_answer="Tổng tiền là (180.000.000 + 30.000.000) * 1.05 = 220.500.000 VND.",
        tier_brackets=[
            TierBracket(label="Pro", min_qty=500, max_qty=None, unit_price=Decimal("180000000"), fixed_fee=Decimal("30000000"), unit="VND/year"),
        ],
        discount_pct=Decimal("5"),
        discount_applies_to_fixed_fee=False,
    )
    assert vr["applied"] is True
    assert vr["contradicted_llm"] is True
    assert "201.000.000" in vr["final_answer"]
    assert "220.500.000" not in vr["verified_summary"]

    # Category Q: Document identifier token "13" in Nghị định 13/2023 not falsely flagged
    nd = _ch("src_nd", "Decree.pdf", 0, "Điều 23: thông báo chậm nhất 72 giờ. Hiệu lực 01/07/2023.")
    vr_q = verify_and_reconcile_answer(
        query="Theo Nghị định 13/2023/NĐ-CP chậm nhất bao nhiêu giờ và hiệu lực ngày nào?",
        chunks=[nd],
        llm_answer="Theo Nghị định 13/2023/NĐ-CP chậm nhất 72 giờ và hiệu lực từ 01/07/2023.",
    )
    assert "13" in vr_q["ignored_identifier_numbers"]

    # Category R: General conceptual question MUST NOT enter Calculator or Rule Engine
    vr_gen = verify_and_reconcile_answer(
        query="Thông tư là gì và quy trình chọn mua thiết bị văn phòng thế nào?",
        chunks=[_ch("src_g", "Doc.md", 0, "Thông tư hướng dẫn thi hành nghị định.")],
        llm_answer="Thông tư là văn bản quy phạm pháp luật do Bộ trưởng ban hành.",
    )
    assert vr_gen["applied"] is False


# ==============================================================================
# CATEGORIES S & T: Feature Flags OFF Parity, Streaming & Persistence
# ==============================================================================


def test_cat_st_feature_flag_off_on_streaming_and_research_parity(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.delenv("PRODUCT_ADVANCED_REASONING", raising=False)
    monkeypatch.delenv("PRODUCT_STRUCTURED_EVIDENCE", raising=False)
    assert advanced_reasoning_enabled() is False

    st = SourceStore(str(tmp_path / "src"))
    runs = RunStore(str(tmp_path / "runs"))
    st.import_text(
        "Labor_Norms.md",
        "# QUY ĐỊNH LÀM THÊM GIỜ\nGiờ làm việc chuẩn: 8 giờ/ngày. Làm thêm ngày thường: 150%.\n",
    )
    cid = st.chunks()[0].chunk_id
    pipe = ResearchPipeline(st, runs)

    # Simulate FakeProvider returning wrong OT calculation (forgetting /8 hours/day!)
    wrong_llm_json = json.dumps({
        "status": "COMPLETE",
        "answer": f"Tiền làm thêm = 20.800.000 / 26 * 6 * 1.5 = **7.200.000** đồng [{cid}].",
        "citations": [cid],
        "missing_information": [],
    })

    class _MockProv(FakeProvider):
        async def generate(self, *, system: str, user: str, **kw) -> ProviderResult:
            return ProviderResult(text=wrong_llm_json, usage=Usage(10, 10), model="fake")

        async def generate_grounded(self, *, system: str, user: str, **kw) -> ProviderResult:
            return await self.generate(system=system, user=user, **kw)

    query_ot = f"Tiền làm thêm tối thiểu của nhân sự này là bao nhiêu?\n\n{IMG_MARK}\nLương 20.800.000 đ/tháng - 26 ngày công\nLàm thêm ngày thường: 6 giờ"

    # 1. OFF: V1 behavior preserved (no verified_reasoning event; LLM number stays)
    with patch("app.research.pipeline.get_provider", return_value=_MockProv()):
        run_off = asyncio.run(pipe.run(query_ot, "C", "fake", product_mode=True))
    assert "verified_reasoning" not in [e["stage"] for e in run_off["events"]]

    # 2. ON (Product Mode): Verified deterministic result overrides contradicting 7.200.000 -> 900.000!
    monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", "on")
    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    streamed: list[str] = []
    with patch("app.research.pipeline.get_provider", return_value=_MockProv()):
        with patch("app.research.vanilla.emit_validated_answer", side_effect=lambda txt: streamed.append(txt)):
            run_on = asyncio.run(pipe.run(query_ot, "C", "fake", product_mode=True))
    assert "verified_reasoning" in [e["stage"] for e in run_on["events"]]
    assert "900.000" in run_on["answer"]
    assert streamed and "900.000" in streamed[-1]  # Streaming parity!

    # 3. ON in Research Mode (product_mode=False): Research A/B/C stays 100% untouched!
    with patch("app.research.pipeline.get_provider", return_value=_MockProv()):
        run_res = asyncio.run(pipe.run(query_ot, "C", "fake", product_mode=False))
    assert "verified_reasoning" not in [e["stage"] for e in run_res["events"]]


# ==============================================================================
# PHASE H: 24 DIVERSE HELD-OUT UNSEEN SCENARIOS ACROSS 6 DOMAINS (FROZEN ORACLE)
# ==============================================================================

HELD_OUT_24_SCENARIOS = [
    # --- Domain 1: Enterprise (4) ---
    {
        "id": "HO-ENT-01",
        "domain": "Enterprise",
        "kind": "calc",
        "query": "Công ty mua 40 ghế bản Enterprise có giảm 10% phí bản quyền và cộng phí cài đặt cố định 12.000.000 VND (không giảm phí cài đặt), tổng là bao nhiêu?",
        "chunk": _ch("src_ho_e1", "Ent_License.md", 0, "Đơn giá: 2.500.000 VND/ghế/năm. Chiết khấu số lượng từ 30 ghế: 10%. Phí cài đặt cố định: 12.000.000 VND (không chiết khấu)."),
        "params": {"formula": FormulaType.DISCOUNT_WITH_FIXED_FEE, "unit_price": Decimal("2500000"), "quantity": Decimal("40"), "discount_pct": Decimal("10"), "fixed_fee": Decimal("12000000"), "discount_applies_to_fixed_fee": False},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("102000000"),  # 40*2.5M*0.9 + 12M = 90M + 12M
    },
    {
        "id": "HO-ENT-02",
        "domain": "Enterprise",
        "kind": "calc",
        "query": "Tính tổng thanh toán gồm thuế VAT 8% cho hợp đồng bảo trì 75.000.000 VND?",
        "chunk": _ch("src_ho_e2", "Tax_Policy.md", 0, "Giá trị bảo trì chưa VAT: 75.000.000 VND. Thuế VAT áp dụng: 8%."),
        "params": {"formula": FormulaType.TAX_OR_SURCHARGE, "base": Decimal("75000000"), "tax_pct": Decimal("8")},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("81000000"),
    },
    {
        "id": "HO-ENT-03",
        "domain": "Enterprise",
        "kind": "calc",
        "query": "Tính lương làm thêm 5 giờ ngày nghỉ tuần khi lương tháng 19.200.000 VND (24 ngày công)?",
        "chunk": _ch("src_ho_e3", "HR_Shift.md", 0, "Ngày làm việc chuẩn 8 giờ/ngày. Làm thêm ngày nghỉ tuần hưởng 200%."),
        "params": {"ocr_override": f"{IMG_MARK}\nLương 19.200.000 đ/tháng - 24 ngày công\nLàm thêm ngày nghỉ hằng tuần: 5 giờ"},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("1000000"),  # 19.2M/24/8 = 100k/h * 5 * 2.0
    },
    {
        "id": "HO-ENT-04",
        "domain": "Enterprise",
        "kind": "rule",
        "tree": RuleGroup("AND", [
            RuleLeaf("E4-1", "Hợp đồng có giá trị > 200 triệu", "mandatory", verdict="MET", case_fact="250 triệu", chunk_id="s_e4"),
            RuleLeaf("E4-2", "Có chữ ký Giám đốc Tài chính", "approval", verdict="NOT_MET", case_fact="chỉ có Trưởng phòng ký", chunk_id="s_e4"),
        ]),
        "expected_overall": "NOT_ELIGIBLE",
    },
    # --- Domain 2: Education (4) ---
    {
        "id": "HO-EDU-01",
        "domain": "Education",
        "kind": "calc",
        "query": "Tính điểm trung bình tích lũy có trọng số của 3 học phần: 3 tín chỉ điểm 8.0, 4 tín chỉ điểm 7.5, 3 tín chỉ điểm 9.0?",
        "chunk": _ch("src_ho_ed1", "Grading.md", 0, "Điểm trung bình trọng số bằng tổng (tín chỉ * điểm) chia tổng số tín chỉ."),
        "params": {"formula": FormulaType.AVERAGE, "values": [Decimal("8.0"), Decimal("7.5"), Decimal("9.0")], "weights": [Decimal("3"), Decimal("4"), Decimal("3")]},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("8.1"),  # (24 + 30 + 27) / 10 = 8.1
    },
    {
        "id": "HO-EDU-02",
        "domain": "Education",
        "kind": "calc",
        "query": "Sinh viên đăng ký 18 tín chỉ ở mức 620.000 VND/tín chỉ và đóng phí phòng lab cố định 1.500.000 VND, học bổng miễn giảm 25% trên học phí tín chỉ (không giảm phí lab), phải đóng bao nhiêu?",
        "chunk": _ch("src_ho_ed2", "Tuition.md", 0, "Đơn giá 620.000 VND/tín chỉ. Phí lab cố định 1.500.000 VND. Miễn giảm học bổng chỉ tính trên học phí tín chỉ."),
        "params": {"formula": FormulaType.DISCOUNT_WITH_FIXED_FEE, "unit_price": Decimal("620000"), "quantity": Decimal("18"), "discount_pct": Decimal("25"), "fixed_fee": Decimal("1500000"), "discount_applies_to_fixed_fee": False},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("9870000"),  # 18*620k*0.75 + 1.5M = 8.37M + 1.5M
    },
    {
        "id": "HO-EDU-03",
        "domain": "Education",
        "kind": "rule",
        "tree": RuleGroup("AND", [
            RuleLeaf("ED3-1", "GPA >= 3.2", "mandatory", verdict="MET", case_fact="GPA 3.55", chunk_id="s_ed3"),
            RuleLeaf("ED3-2", "Không bị kỷ luật trong năm học", "exception", negated=True, verdict="NOT_MET", case_fact="không vi phạm kỷ luật", chunk_id="s_ed3"),
            RuleLeaf("ED3-3", "Hoàn thành tối thiểu 24 tín chỉ", "mandatory", verdict="MET", case_fact="28 tín chỉ", chunk_id="s_ed3"),
        ]),
        "expected_overall": "ELIGIBLE",
    },
    {
        "id": "HO-EDU-04",
        "domain": "Education",
        "kind": "calc",
        "query": "Tính tỷ lệ phần trăm sinh viên đạt trên 900 chỗ dự thi thực tế 720 thí sinh?",
        "chunk": _ch("src_ho_ed4", "Exam_Stats.md", 0, "Tỷ lệ đạt = (số thí sinh đạt / tổng thí sinh dự thi) * 100%."),
        "params": {"formula": FormulaType.RATIO, "numerator": Decimal("720"), "denominator": Decimal("900"), "as_percent": True},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("80"),
    },
    # --- Domain 3: Technical (4) ---
    {
        "id": "HO-TEC-01",
        "domain": "Technical",
        "kind": "calc",
        "query": "Hệ thống lưu 3 TB ảnh sang đơn vị GB với 1 TB = 1024 GB và nhân đơn giá 1.500 VND/GB thì tốn bao nhiêu tiền?",
        "chunk": _ch("src_ho_t1", "Infra.md", 0, "Quy đổi dung lượng nhị phân: 1 TB = 1024 GB. Chi phí lưu trữ: 1.500 VND/GB/tháng."),
        "params": {"formula": FormulaType.MULTI_STEP, "steps_expr": "3 * 1024 * 1500", "unit": "VND"},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("4608000"),
    },
    {
        "id": "HO-TEC-02",
        "domain": "Technical",
        "kind": "calc",
        "query": "API timeout trong 4500 ms là bao nhiêu giây?",
        "chunk": _ch("src_ho_t2", "API_Spec.md", 0, "1 giây = 1000 ms."),
        "params": {"formula": FormulaType.UNIT_CONVERSION, "amount": Decimal("4500"), "from_unit": "ms", "to_unit": "second", "factor": Decimal("0.001")},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("4.5"),
    },
    {
        "id": "HO-TEC-03",
        "domain": "Technical",
        "kind": "calc",
        "query": "Nhân băng thông 100 Mbps/giây với số giờ 2 mà chưa có hệ số thời gian?",
        "chunk": _ch("src_ho_t3", "Net.md", 0, "Tốc độ truyền 100 Mbps."),
        "params": {"formula": FormulaType.UNIT_MISMATCH_TEST, "left_unit": "VND/day", "right_unit": "hour"},
        "expected_status": CalcStatus.INVALID_UNIT,
    },
    {
        "id": "HO-TEC-04",
        "domain": "Technical",
        "kind": "rule",
        "tree": RuleGroup("AND", [
            RuleLeaf("T4-1", "Mã hóa TLS 1.3", "mandatory", verdict="MET", case_fact="TLS 1.3", chunk_id="s_t4"),
            RuleGroup("OR", [
                RuleLeaf("T4-2A", "SSO OIDC", "mandatory", verdict="NOT_MET", case_fact="chưa bật OIDC", chunk_id="s_t4"),
                RuleLeaf("T4-2B", "SAML 2.0", "mandatory", verdict="MET", case_fact="đã bật SAML 2.0", chunk_id="s_t4"),
            ]),
        ]),
        "expected_overall": "ELIGIBLE",
    },
    # --- Domain 4: Logistics (4) ---
    {
        "id": "HO-LOG-01",
        "domain": "Logistics",
        "kind": "calc",
        "query": "Lô hàng 420 kg theo bảng giá từ 300 kg trở lên là 18.000 VND/kg cộng phí bốc xếp 350.000 VND, tổng cước bao nhiêu?",
        "chunk": _ch("src_ho_l1", "Freight.md", 0, "Cước bậc >= 300 kg: 18.000 VND/kg. Phí bốc xếp cố định: 350.000 VND."),
        "params": {
            "formula": FormulaType.TIERED_PRICING,
            "quantity": Decimal("420"),
            "tier_brackets": [
                TierBracket("Chuẩn", min_qty=0, max_qty=300, max_inclusive=False, unit_price=Decimal("22000"), fixed_fee=Decimal("350000"), unit="VND/kg", per_unit=True),
                TierBracket("Lớn", min_qty=300, max_qty=None, min_inclusive=True, unit_price=Decimal("18000"), fixed_fee=Decimal("350000"), unit="VND/kg", per_unit=True),
            ],
        },
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("7910000"),  # 420*18000 + 350000 = 7,560,000 + 350,000
    },
    {
        "id": "HO-LOG-02",
        "domain": "Logistics",
        "kind": "calc",
        "query": "Đơn hàng 12.000.000 VND giao trễ 6 giờ phạt 0,5%/giờ?",
        "chunk": _ch("src_ho_l2", "SLA_Delivery.md", 0, "Phạt chậm giao hàng: 0,5% giá trị đơn hàng cho mỗi giờ trễ."),
        "params": {"formula": FormulaType.MULTI_STEP, "steps_expr": "12000000 * (0.5 / 100) * 6", "unit": "VND"},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("360000"),
    },
    {
        "id": "HO-LOG-03",
        "domain": "Logistics",
        "kind": "calc",
        "query": "Quy đổi 2,5 tấn hàng sang kg?",
        "chunk": _ch("src_ho_l3", "Weight.md", 0, "1 tấn = 1000 kg."),
        "params": {"formula": FormulaType.UNIT_CONVERSION, "amount": Decimal("2.5"), "from_unit": "ton", "to_unit": "kg", "factor": Decimal("1000")},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("2500"),
    },
    {
        "id": "HO-LOG-04",
        "domain": "Logistics",
        "kind": "rule",
        "tree": RuleGroup("AND", [
            RuleLeaf("L4-1", "Xe tải có giấy phép lưu hành nội đô", "applicability", verdict="NOT_APPLICABLE", case_fact="giao hàng ngoại thành", chunk_id="s_l4"),
            RuleLeaf("L4-2", "Có biên bản bàn giao niêm phong", "mandatory", verdict="MET", case_fact="đủ niêm phong", chunk_id="s_l4"),
        ]),
        "expected_overall": "ELIGIBLE",  # NOT_APPLICABLE item does not fail applicable mandatory check
    },
    # --- Domain 5: SaaS (4) ---
    {
        "id": "HO-SAAS-01",
        "domain": "SaaS",
        "kind": "calc",
        "query": "Thuê 120 tài khoản mức 12 USD/tài khoản/tháng trong 12 tháng, giảm 15% cho trả trước năm?",
        "chunk": _ch("src_ho_s1", "SaaS_Plan.md", 0, "12 USD/tài khoản/tháng. Trả trước 1 năm giảm 15%."),
        "params": {"formula": FormulaType.MULTI_STEP, "steps_expr": "120 * 12 * 12 * 0.85", "unit": "USD", "currency": "USD"},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("14688"),  # 17280 * 0.85
    },
    {
        "id": "HO-SAAS-02",
        "domain": "SaaS",
        "kind": "calc",
        "query": "Phí vượt hạn mức API 250.000 lượt gọi khi gói miễn phí cho 100.000 lượt và vượt tính 40 VND/lượt?",
        "chunk": _ch("src_ho_s2", "API_Billing.md", 0, "Hạn mức gói: 100.000 lượt/tháng. Phí vượt: 40 VND/lượt."),
        "params": {"formula": FormulaType.MULTI_STEP, "steps_expr": "(250000 - 100000) * 40", "unit": "VND"},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("6000000"),
    },
    {
        "id": "HO-SAAS-03",
        "domain": "SaaS",
        "kind": "calc",
        "query": "Chia chi phí SaaS 60.000.000 VND đều cho 0 phòng ban?",
        "chunk": _ch("src_ho_s3", "Allocation.md", 0, "Chi phí chung chia đều cho số phòng ban hoạt động."),
        "params": {"formula": FormulaType.MULTI_STEP, "steps_expr": "60000000 / 0", "unit": "VND"},
        "expected_status": CalcStatus.UNSUPPORTED,
    },
    {
        "id": "HO-SAAS-04",
        "domain": "SaaS",
        "kind": "rule",
        "tree": RuleGroup("AND", [
            RuleLeaf("S4-1", "Uptime tháng đạt >= 99,9%", "mandatory", verdict="NOT_MET", case_fact="uptime 99,4%", chunk_id="s_s4"),
            RuleLeaf("S4-2", "Báo cáo RCA trong 5 ngày", "optional", verdict="MET", case_fact="gửi sau 2 ngày", chunk_id="s_s4"),
        ]),
        "expected_overall": "NOT_ELIGIBLE",
    },
    # --- Domain 6: Operational Workflows (4) ---
    {
        "id": "HO-OPS-01",
        "domain": "Operations",
        "kind": "calc",
        "query": "Phụ cấp trực đêm 3 đêm ngày thường (300.000 đ/đêm) và 2 đêm ngày lễ (500.000 đ/đêm)?",
        "chunk": _ch("src_ho_o1", "Oncall.md", 0, "Trực đêm ngày thường: 300.000 đồng/đêm; ngày lễ: 500.000 đồng/đêm."),
        "params": {"formula": FormulaType.MULTI_STEP, "steps_expr": "3 * 300000 + 2 * 500000", "unit": "VND"},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("1900000"),
    },
    {
        "id": "HO-OPS-02",
        "domain": "Operations",
        "kind": "calc",
        "query": "Thời gian xử lý trung bình 4 phiếu sự cố: 30 phút, 45 phút, 60 phút, 25 phút?",
        "chunk": _ch("src_ho_o2", "MTTR.md", 0, "MTTR tính bằng trung bình cộng thời gian khắc phục các phiếu."),
        "params": {"formula": FormulaType.AVERAGE, "values": [Decimal("30"), Decimal("45"), Decimal("60"), Decimal("25")], "unit": "minute"},
        "expected_status": CalcStatus.VERIFIED,
        "expected_value": Decimal("40"),
    },
    {
        "id": "HO-OPS-03",
        "domain": "Operations",
        "kind": "rule",
        "tree": RuleGroup("AND", [
            RuleLeaf("O3-1", "Có người thứ hai xác nhận thao tác production", "mandatory", verdict="MET", case_fact="đã xác nhận", chunk_id="s_o3"),
            RuleLeaf("O3-2", "Đã tạo ticket thay đổi", "mandatory", verdict="MET", case_fact="CHG-1042", chunk_id="s_o3"),
            RuleLeaf("O3-3", "Không nằm trong khung đóng băng phát hành", "exception", negated=True, verdict="NOT_MET", case_fact="ngày bình thường", chunk_id="s_o3"),
        ]),
        "expected_overall": "ELIGIBLE",
    },
    {
        "id": "HO-OPS-04",
        "domain": "Operations",
        "kind": "rule",
        "tree": RuleGroup("AND", [
            RuleLeaf("O4-1", "Yêu cầu mua sắm được duyệt bởi Trưởng bộ phận", "approval", verdict="MET", case_fact="Trưởng bộ phận đã duyệt", chunk_id="s_o4"),
            RuleLeaf("O4-2", "Kiểm tra tuân thủ Luật Đấu thầu (chưa nạp văn bản luật)", "mandatory", verdict="UNKNOWN", case_fact="", chunk_id=""),
        ]),
        "expected_overall": "INSUFFICIENT_INFO",
    },
]


@pytest.mark.parametrize("sc", HELD_OUT_24_SCENARIOS, ids=[s["id"] for s in HELD_OUT_24_SCENARIOS])
def test_phase_h_held_out_24_scenarios(sc):
    assert len(HELD_OUT_24_SCENARIOS) >= 24
    if sc["kind"] == "calc":
        p = sc["params"]
        if "ocr_override" in p:
            spec = select_formula(f"{sc['query']}\n\n{p['ocr_override']}", chunks=[sc["chunk"]])
        else:
            spec = select_formula(sc["query"], chunks=[sc["chunk"]], **p)
        res = execute_formula(spec)
        assert res.status == sc["expected_status"]
        if "expected_value" in sc:
            assert res.value == sc["expected_value"]
    else:
        res = evaluate_rule_tree(sc["tree"])
        assert res["overall"] == sc["expected_overall"]
