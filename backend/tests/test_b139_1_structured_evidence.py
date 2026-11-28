"""B139.1 Test-First Suite: Structured Evidence, Operand Grounding & Rule Evidence (Zero Ollama).

Covers Categories A through M using synthetic & held-out fixtures (no Owner/restricted corpus data,
no memorized B138 answers) plus experimental OFF-by-default integration & quality metric assertions.
"""
from __future__ import annotations

import asyncio
import json

from unittest.mock import patch

import pytest

from app.core.answer_checks import IMG_MARK
from app.core.operand_grounding import (
    are_units_compatible,
    derive_hourly_rate,
    ground_operand,
    identifier_numbers_in_text,
    verify_expression_grounding,
)
from app.core.rule_evidence import (
    RULE_SCHEMA_VERSION,
    RuleConditionEvidence,
    assess_rule_conditions,
)
from app.core.structured_evidence import (
    SCHEMA_VERSION,
    EvidenceRole,
    StructuredEvidence,
    ValidationStatus,
    evaluate_extraction_quality,
    extract_structured_evidence,
    parse_localized_number,
)
from app.core.types import ProviderResult, SourceChunk, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.structured_evidence_hook import (
    build_grounding_snapshot,
    structured_evidence_enabled,
)
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _chunk(
    src: str,
    name: str,
    idx: int,
    text: str,
    *,
    doc_type: str = "other",
    score: float = 0.8,
) -> SourceChunk:
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
# CATEGORY A & B & C: Numerical Extraction, VI/EN Unit Normalization, % & Currency
# ==============================================================================


def test_cat_abc_number_formats_and_ambiguous_locale():
    assert parse_localized_number("3.500", locale_hint="vi", unit_hint="sinh viên")[:2] == (3500, "integer")
    assert parse_localized_number("3500", locale_hint="vi")[:2] == (3500, "integer")
    assert parse_localized_number("1,5", locale_hint="vi")[:2] == (1.5, "decimal")
    assert parse_localized_number("1.5", locale_hint="en")[:2] == (1.5, "decimal")
    # Standalone "1.234" without locale or unit/count context is genuinely ambiguous
    val, dtype, status = parse_localized_number("1.234", locale_hint="auto", unit_hint="")
    assert val is None and dtype == "unknown" and status == ValidationStatus.AMBIGUOUS


def test_cat_abc_vi_and_en_currency_percentage_duration_ranges():
    c = _chunk(
        "src_1111111111111111",
        "Compensation_Policy.md",
        0,
        (
            "# CHÍNH SÁCH LƯƠNG VÀ PHỤ CẤP\n"
            "Mức lương cơ bản: 17,5 triệu đồng/tháng cho 26 ngày công.\n"
            "Đơn giá gói Pro (từ 100 đến 500 tài khoản): 260.000.000 VND/năm.\n"
            "Chiết khấu ưu đãi đối tác công lập: 5%.\n"
            "Thời hạn thông báo sự cố: 72 giờ kể từ khi phát hiện.\n"
            "Standard support response time: 4 hours on weekdays; overtime multiplier: 150%.\n"
            "Effective date: 01/07/2023. Range: 8-10 giờ/ngày.\n"
        ),
        doc_type="legal_doc",
    )
    items = extract_structured_evidence([c])
    assert all(i.schema_version == SCHEMA_VERSION for i in items)
    assert all(i.confidence is None for i in items)  # Must never invent confidence scores

    # 17,5 triệu đồng/tháng
    sal = [i for i in items if i.data_type == "currency" and i.value == 17_500_000]
    assert sal and sal[0].currency == "VND" and sal[0].unit == "VND/month"
    assert sal[0].evidence_role == EvidenceRole.OFFICIAL_RULE

    # 260.000.000 VND/năm + quantity range 100..500
    vnd_yr = [i for i in items if i.data_type == "currency" and i.value == 260_000_000]
    assert vnd_yr and vnd_yr[0].currency == "VND" and vnd_yr[0].unit == "VND/year"
    ranges = [i for i in items if i.data_type == "range"]
    assert any(r.value == {"min": 100, "max": 500, "min_inclusive": True, "max_inclusive": True} for r in ranges)
    assert any(r.value == {"min": 8, "max": 10, "min_inclusive": True, "max_inclusive": True} and r.unit == "hour/day" for r in ranges)

    # Percentages & hours (VI + EN)
    pcts = [i for i in items if i.data_type == "percentage"]
    assert {p.value for p in pcts} >= {5.0, 150.0}
    durations = [i for i in items if i.data_type == "duration"]
    assert any(d.value == 72 and d.unit == "hour" for d in durations)
    assert any(d.value == 4 and d.unit == "hour" for d in durations)
    assert any(d.value == 26 and d.unit == "working_day" for d in durations)


# ==============================================================================
# CATEGORY D: Document Identifiers and Dates (Never Treat Doc IDs as Operands)
# ==============================================================================


def test_cat_d_document_identifiers_and_dates_excluded_from_operands():
    c = _chunk(
        "src_2222222222222222",
        "Nghi_dinh_99.pdf",
        0,
        (
            "Nghị định 13/2023/NĐ-CP và Thông tư 08/2021/TT-BGDĐT (Điều 23, Khoản 1).\n"
            "Báo cáo tháng 11 năm 2026: thời hạn gửi là 72 giờ. Hiệu lực từ ngày 01/07/2023."
        ),
        doc_type="legal_doc",
    )
    items = extract_structured_evidence([c])
    ids = [i for i in items if i.data_type == "identifier"]
    id_spans = " | ".join(i.source_span for i in ids)
    assert "13/2023" in id_spans
    assert "08/2021" in id_spans
    assert "Điều 23" in id_spans

    dates = [i for i in items if i.data_type == "date"]
    assert any(d.value == "2023-07-01" and d.effective_date == "2023-07-01" for d in dates)

    # Identifier numbers ("13", "2023", "08", "2021", "23", "11") must NOT masquerade as arithmetic operands
    non_ops = identifier_numbers_in_text(c.text)
    assert {"13", "23", "11"} <= non_ops
    assert "72" not in non_ops


# ==============================================================================
# CATEGORY E & F: Official Rule vs Example + Same Numeric Value Different Entities
# ==============================================================================


def test_cat_ef_official_rule_vs_example_and_entity_isolation():
    c_rules = _chunk(
        "src_3333333333333333",
        "Pricing_Guide_2026.md",
        0,
        (
            "# BẢNG GIÁ CHÍNH THỨC\n"
            "| Khách hàng / Gói | Giá niêm yết | Chiết khấu tối đa | Phí triển khai |\n"
            "|---|---|---|---|\n"
            "| Gói Enterprise (trên 1.000 nhân sự) | 200.000.000 VND/năm | 10% | 40.000.000 VND |\n"
            "| Khách hàng B (nhóm đối tác mới) | 200.000.000 VND/năm | 5% | 40.000.000 VND |\n\n"
            "Quy định chung: Không chiết khấu phí triển khai.\n"
            "Ví dụ minh họa: Hợp đồng cũ năm 2024 với Khách hàng Alpha từng áp dụng mức chiết khấu 22% và phí triển khai 25.000.000 VND.\n"
        ),
        doc_type="other",
    )
    items = extract_structured_evidence([c_rules])

    # Illustrative/historical sentence must be tagged DOCUMENT_EXAMPLE, never OFFICIAL_RULE
    ex_22 = [i for i in items if i.value == 22.0]
    assert ex_22 and all(i.evidence_role == EvidenceRole.DOCUMENT_EXAMPLE for i in ex_22)

    # Official row A (10%) vs Official row B (5%)
    res_b = ground_operand(
        items,
        attribute="discount_rate",
        entity="Khách hàng B",
        target_unit="percent",
        allow_examples=False,
    )
    assert res_b.status == ValidationStatus.VALIDATED
    assert res_b.operand_value == 5.0
    assert res_b.evidence_role == EvidenceRole.OFFICIAL_RULE

    # Numeric value 10 belongs to Enterprise / Customer A, MUST NOT be grounded for Khách hàng B!
    bad_try = ground_operand(
        items,
        attribute="discount_rate",
        entity="Khách hàng B",
        target_unit="percent",
        expected_value=10.0,
        allow_examples=False,
    )
    assert bad_try.status in {ValidationStatus.UNSUPPORTED, ValidationStatus.CONFLICT}

    # Example value 22% MUST NOT be accepted as official discount
    ex_try = ground_operand(
        items,
        attribute="discount_rate",
        entity="Khách hàng B",
        target_unit="percent",
        expected_value=22.0,
        allow_examples=False,
    )
    assert ex_try.status == ValidationStatus.UNSUPPORTED


# ==============================================================================
# CATEGORY G & H: Conflicting Data & Unsupported Operands / Unit Mismatch
# ==============================================================================


def test_cat_gh_conflicting_rules_and_unit_mismatch_detection():
    c1 = _chunk(
        "src_4444444444444444",
        "Policy_A.md",
        0,
        "# Quy định phạt chậm tiến độ\nMức phạt chậm bàn giao: 1% giá trị hợp đồng/ngày.",
        doc_type="legal_doc",
    )
    c2 = _chunk(
        "src_5555555555555555",
        "Policy_B.md",
        0,
        "# Quy định phạt chậm tiến độ\nMức phạt chậm bàn giao: 2% giá trị hợp đồng/ngày.",
        doc_type="legal_doc",
    )
    items = extract_structured_evidence([c1, c2])
    conflict_res = ground_operand(items, attribute="penalty_rate", target_unit="percent")
    assert conflict_res.status == ValidationStatus.CONFLICT

    # Effective-date disambiguation when newer official rule exists
    c2_newer = _chunk(
        "src_5555555555555556",
        "Policy_2026.md",
        0,
        "# Quy định phạt chậm tiến độ (Hiệu lực từ 01/01/2026)\nMức phạt chậm bàn giao: 2% giá trị hợp đồng/ngày.",
        doc_type="legal_doc",
    )
    items_dated = extract_structured_evidence([c1, c2_newer])
    resolved = ground_operand(
        items_dated,
        attribute="penalty_rate",
        target_unit="percent",
        effective_date="2026-06-01",
    )
    assert resolved.status == ValidationStatus.VALIDATED
    assert resolved.operand_value == 2.0

    # Unit compatibility & OT R-03 bug trap: monthly salary + 26 workdays WITHOUT hours_per_day
    assert are_units_compatible("VND/hour", "VND/hour") is True
    assert are_units_compatible("VND/day", "VND/hour") is False
    assert are_units_compatible("VND/month", "VND/hour") is False

    sal_month = StructuredEvidence(
        evidence_id="ev_sal",
        source_id="user",
        chunk_id="user_ocr",
        source_span="Lương 17.500.000 đ/tháng",
        entity="Nhân viên X",
        attribute="salary_monthly",
        value=17_500_000.0,
        data_type="currency",
        unit="VND/month",
        currency="VND",
        evidence_role=EvidenceRole.USER_INPUT,
        validation_status=ValidationStatus.VALIDATED,
    )
    wd_month = StructuredEvidence(
        evidence_id="ev_wd",
        source_id="user",
        chunk_id="user_ocr",
        source_span="26 ngày công",
        entity="Nhân viên X",
        attribute="workdays_per_month",
        value=26,
        data_type="duration",
        unit="working_day",
        evidence_role=EvidenceRole.USER_INPUT,
        validation_status=ValidationStatus.VALIDATED,
    )
    # Missing hours_per_day -> CANNOT silently assume /8
    derived_missing, drv_res = derive_hourly_rate([sal_month, wd_month], entity="Nhân viên X")
    assert derived_missing is None and drv_res.status == ValidationStatus.UNKNOWN

    # Expression grounding MUST reject dividing monthly by 26 (VND/day) and calling it hourly OT
    bad_daily = StructuredEvidence(
        evidence_id="ev_daily",
        source_id="derived",
        chunk_id="user_ocr",
        source_span="17.500.000 / 26",
        entity="Nhân viên X",
        attribute="daily_rate",
        value=17_500_000 / 26,
        data_type="currency",
        unit="VND/day",
        currency="VND",
        evidence_role=EvidenceRole.DERIVED_VALUE,
        validation_status=ValidationStatus.VALIDATED,
    )
    ot_hours = StructuredEvidence(
        evidence_id="ev_ot_h",
        source_id="user",
        chunk_id="user_ocr",
        source_span="10 giờ",
        entity="Nhân viên X",
        attribute="overtime_hours",
        value=10.0,
        data_type="duration",
        unit="hour",
        evidence_role=EvidenceRole.USER_INPUT,
        validation_status=ValidationStatus.VALIDATED,
    )
    check_bad = verify_expression_grounding(
        "rate * hours * 1.5",
        expected_target_unit="VND",
        bindings={"rate": bad_daily, "hours": ot_hours},
    )
    assert check_bad["valid"] is False
    assert check_bad["status"] == ValidationStatus.UNSUPPORTED
    assert "unit_mismatch" in check_bad["reason"]

    # When explicit hours_per_day=8 comes from document evidence -> valid DERIVED_VALUE with trace!
    h_per_day = StructuredEvidence(
        evidence_id="ev_hpd",
        source_id="src_rule",
        chunk_id="src_rule_c0001",
        source_span="08 giờ/ngày",
        entity="",
        attribute="hours_per_day",
        value=8,
        data_type="duration",
        unit="hour/day",
        evidence_role=EvidenceRole.OFFICIAL_RULE,
        validation_status=ValidationStatus.VALIDATED,
    )
    derived_ok, ok_res = derive_hourly_rate([sal_month, wd_month, h_per_day], entity="Nhân viên X")
    assert derived_ok is not None and ok_res.status == ValidationStatus.VALIDATED
    assert derived_ok.unit == "VND/hour"
    assert derived_ok.evidence_role == EvidenceRole.DERIVED_VALUE
    assert derived_ok.derivation["input_evidence_ids"] == ["ev_sal", "ev_wd", "ev_hpd"]
    assert abs(derived_ok.value - (17_500_000 / 26 / 8)) < 1e-6


# ==============================================================================
# CATEGORY I: Missing Rule Conditions & Retrieval vs Extraction vs Rule Split
# ==============================================================================


def test_cat_i_missing_conditions_never_assumed_met_and_distinguishes_retrieval_gap():
    chunks_without_leave_rule = [
        _chunk("src_6666666666666666", "Company_Handbook.md", 0, "Thời giờ làm việc 40 giờ/tuần từ thứ Hai đến thứ Sáu."),
    ]
    res_missing = assess_rule_conditions(
        conditions=[],
        required_rule_topics=["nghỉ phép", "bàn giao khách hàng"],
        evidence_chunks=chunks_without_leave_rule,
        requested_statutes=["Luật Thương mại"],
    )
    assert res_missing.schema_version == RULE_SCHEMA_VERSION
    assert res_missing.overall in {"NO_EVIDENCE_FOR_RULE", "INSUFFICIENT_INFO"}
    assert res_missing.overall != "ELIGIBLE"
    assert res_missing.failure_classification == "RETRIEVAL_MISSING_EVIDENCE"
    assert "nghỉ phép" in res_missing.missing_rule_topics
    assert "Luật Thương mại" in res_missing.missing_statutes

    # Partial conditions: 1 MET + 1 UNKNOWN -> NEVER ELIGIBLE
    conds = [
        RuleConditionEvidence(
            condition_id="C1",
            description="Nhân sự gửi đơn trước ít nhất 3 ngày làm việc",
            kind="mandatory",
            verdict="MET",
            case_fact="Gửi trước 4 ngày làm việc",
            source_id="src_7777777777777777",
            chunk_id="src_7777777777777777_c0001",
            source_span="gửi đơn trước ít nhất 3 ngày làm việc",
        ),
        RuleConditionEvidence(
            condition_id="C2",
            description="Phải có người trực thay nhận bàn giao công việc",
            kind="mandatory",
            verdict="UNKNOWN",
            case_fact="",
            source_id="src_7777777777777777",
            chunk_id="src_7777777777777777_c0002",
            source_span="bàn giao cho người trực thay",
            missing_evidence_reason="Đơn không nêu người trực thay",
        ),
    ]
    res_partial = assess_rule_conditions(conditions=conds)
    assert res_partial.overall == "INSUFFICIENT_INFO"
    assert any(c.verdict == "UNKNOWN" for c in res_partial.conditions)


# ==============================================================================
# CATEGORY J & K & L: Provenance, Unauthorized Evidence (ACL), User Premise Traps
# ==============================================================================


def test_cat_jkl_provenance_acl_enforcement_and_user_premise_traps():
    c_public = _chunk("src_pub", "Public_Policy.md", 0, "# Quy định\nChiết khấu cơ bản: 5%.", doc_type="legal_doc")
    c_secret = _chunk("src_sec", "Executive_Secret.md", 0, "# Chính sách Mật\nChiết khấu tối đa: 35%.", doc_type="legal_doc")

    # User premise trap ("mỗi nhân viên được nghỉ 30 ngày đúng không?") MUST stay UNKNOWN/UNSUPPORTED
    trap_query = (
        "Mỗi nhân viên được nghỉ 30 ngày đúng không? Tính cho đơn 4 ngày phép.\n\n"
        f"{IMG_MARK}\nSố ngày phép đã dùng: 2 ngày"
    )
    items = extract_structured_evidence(
        [c_public, c_secret],
        query=trap_query,
        allowed_source_ids={"src_pub"},  # ACL excludes src_sec!
    )
    # Unauthorized secret source MUST be excluded during extraction or rejected by grounding
    assert not any(i.source_id == "src_sec" and i.validation_status == ValidationStatus.VALIDATED for i in items)

    sec_check = ground_operand(
        items,
        attribute="discount_rate",
        target_unit="percent",
        expected_value=35.0,
        allowed_source_ids={"src_pub"},
    )
    assert sec_check.status == ValidationStatus.UNSUPPORTED

    # Premise trap "30 ngày" MUST NOT be accepted as OFFICIAL_RULE or VALIDATED USER_INPUT
    assert not any(
        i.value == 30 and i.validation_status == ValidationStatus.VALIDATED and i.evidence_role in {EvidenceRole.OFFICIAL_RULE, EvidenceRole.USER_INPUT}
        for i in items
    )
    # Valid user OCR data ("2 ngày") and typed fact ("4 ngày") MUST be USER_INPUT with provenance
    assert any(i.value == 2 and i.evidence_role == EvidenceRole.USER_INPUT and i.chunk_id == "user_ocr" for i in items)
    assert any(i.value == 4 and i.evidence_role == EvidenceRole.USER_INPUT for i in items)


# ==============================================================================
# CATEGORY M: Generalization on Unseen Held-Out Domains & Quality Metrics
# ==============================================================================


def test_cat_m_held_out_generalization_and_quality_metrics():
    # Unseen English & Vietnamese logistics/cloud contract scenarios
    c_unseen = _chunk(
        "src_8888888888888888",
        "Cloud_SLA_And_Logistics_2027.md",
        0,
        (
            "# SERVICE SLA 2027 (Effective date: 15/03/2027)\n"
            "Cloud Node Base Price: 1,250 USD/month for up to 500 GB storage.\n"
            "Latency penalty: 0.5% per hour of downtime above 2 hours.\n"
            "Ví dụ: Dự án thử nghiệm Q1 từng giảm 18% phí tháng đầu.\n"
        ),
        doc_type="contract",
    )
    items = extract_structured_evidence([c_unseen])
    gold = [
        {"value": 1250.0, "unit": "USD/month", "evidence_role": EvidenceRole.OFFICIAL_RULE, "chunk_id": "src_8888888888888888_c0000"},
        {"value": 500, "unit": "GB", "evidence_role": EvidenceRole.OFFICIAL_RULE, "chunk_id": "src_8888888888888888_c0000"},
        {"value": 0.5, "unit": "percent", "evidence_role": EvidenceRole.OFFICIAL_RULE, "chunk_id": "src_8888888888888888_c0000"},
        {"value": 2, "unit": "hour", "evidence_role": EvidenceRole.OFFICIAL_RULE, "chunk_id": "src_8888888888888888_c0000"},
        {"value": 18.0, "unit": "percent", "evidence_role": EvidenceRole.DOCUMENT_EXAMPLE, "chunk_id": "src_8888888888888888_c0000"},
        {"value": "2027-03-15", "unit": "", "evidence_role": EvidenceRole.OFFICIAL_RULE, "chunk_id": "src_8888888888888888_c0000"},
    ]
    metrics = evaluate_extraction_quality(items, gold)
    assert metrics["precision"] >= 0.80
    assert metrics["recall"] >= 0.80
    assert metrics["provenance_accuracy"] == 1.0


# ==============================================================================
# EXPERIMENTAL INTEGRATION: Default OFF & Zero Impact on Research A/B/C
# ==============================================================================


def test_experimental_hook_default_off_and_pipeline_parity(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.delenv("PRODUCT_STRUCTURED_EVIDENCE", raising=False)
    assert structured_evidence_enabled() is False

    c = _chunk("src_9999999999999999", "Policy.md", 0, "Thời hạn phê duyệt là 5 ngày làm việc.", doc_type="legal_doc")
    snap = build_grounding_snapshot("Thời hạn duyệt là bao nhiêu ngày?", [c], answer="Thời hạn duyệt là 5 ngày làm việc.")
    assert snap["schema_version"] == SCHEMA_VERSION
    assert snap["evidence_count"] >= 1

    # Verify default pipeline behavior emits ZERO structured_evidence_grounding events when OFF
    st = SourceStore(str(tmp_path / "src"))
    runs = RunStore(str(tmp_path / "runs"))
    st.import_text("Policy.md", "Thời hạn phê duyệt là 5 ngày làm việc.")
    cid = st.chunks()[0].chunk_id
    pipe = ResearchPipeline(st, runs)
    # Round-trip schema compatibility check
    rt = StructuredEvidence.from_dict(
        StructuredEvidence(
            evidence_id="ev_rt", source_id="s1", chunk_id="s1_c0000", source_span="5 ngày",
            entity="E", attribute="notice", value=5, data_type="duration", unit="day",
            evidence_role=EvidenceRole.OFFICIAL_RULE, validation_status=ValidationStatus.VALIDATED,
        ).to_dict()
    )
    assert rt.schema_version == SCHEMA_VERSION and rt.confidence is None
    class _FixedFake(FakeProvider):
        def __init__(self, payload_text: str):
            self._payload_text = payload_text

        async def generate(self, *, system: str, user: str, **kw) -> ProviderResult:
            return ProviderResult(text=self._payload_text, usage=Usage(input_tokens=10, output_tokens=10), model="fake")

        async def generate_structured(self, *, system: str, user: str, response_schema: dict, **kw) -> ProviderResult:
            return await self.generate(system=system, user=user, **kw)

    payload_vi = json.dumps({
        "status": "COMPLETE",
        "answer": f"Thời hạn phê duyệt là 5 ngày làm việc [{cid}].",
        "citations": [cid],
        "missing_information": [],
    })
    with patch("app.research.pipeline.get_provider", return_value=_FixedFake(payload_vi)):
        run = asyncio.run(pipe.run("Thời hạn phê duyệt là bao nhiêu ngày?", "C", "fake", product_mode=True))
    stages = [e["stage"] for e in run["events"]]
    assert "structured_evidence_grounding" not in stages

    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    assert structured_evidence_enabled() is True
    with patch("app.research.pipeline.get_provider", return_value=_FixedFake(payload_vi)):
        run_on = asyncio.run(pipe.run("Thời hạn phê duyệt là bao nhiêu ngày?", "C", "fake", product_mode=True))
    stages_on = [e["stage"] for e in run_on["events"]]
    assert "structured_evidence_grounding" in stages_on
    # Research Mode (product_mode=False) remains untouched even if env var is set
    payload_res = json.dumps({
        "status": "COMPLETE",
        "answer": f"5 working days [{cid}].",
        "citations": [cid],
        "missing_information": [],
    })
    with patch("app.research.pipeline.get_provider", return_value=_FixedFake(payload_res)):
        run_research = asyncio.run(pipe.run("Thời hạn phê duyệt là bao nhiêu ngày?", "C", "fake", product_mode=False))
    assert "structured_evidence_grounding" not in [e["stage"] for e in run_research["events"]]
