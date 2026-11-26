"""Batch 138.3 Evidence-Driven RAG & AI Reasoning Improvement Tests (Test-First RED -> GREEN, Zero Ollama).

Covers Workstreams A-E across generalized fixtures & recorded B138 patterns:
- WS-A: Multi-source retrieval & source_focus cross-doc preservation + subquestion coverage + ACL.
- WS-B: Evidence-aware context allocation (multi-source + continuation under tight token caps) & Research parity.
- WS-C: Intent & agent routing calibration + general-concept non-anchoring.
- WS-D: Deterministic calculation input quantities + unsafe expr guard + rule consistency contradiction check.
- WS-E: Evidence coverage completeness guard (out-of-corpus law claims, missing subquestions) + Quiz topic alignment.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from app.analysis.domain_tools import generate_items
from app.core.answer_checks import (
    IMG_MARK,
    apply_calc,
    check_product_evidence_claims,
    evidence_with_case_image_only,
)
from app.core.types import ProviderResult, RunMetrics, SourceChunk, TaskResult, Usage
from app.providers.fake import FakeProvider
from app.research.agent_selection import select_agents
from app.research.knowledge_source import BOTH, DOCUMENTS, GENERAL, choose_source, doc_bound
from app.research.pipeline import ResearchPipeline
from app.research.registry import OFFICE_PACK, use_pack
from app.research.token_context import TokenContextController
from app.research.vanilla import answer_vanilla
from app.retrieval.source_focus import focus_sources
from app.retrieval.text import apply_token_budget
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _chunk(src: str, name: str, idx: int, text: str, *, score: float = 0.5, doc_type: str = "other") -> SourceChunk:
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
# WORKSTREAM A — MULTI-SOURCE RETRIEVAL
# ==============================================================================


def test_ws_a_source_focus_preserves_companion_law_doc_on_cross_doc_rate_query():
    chunks = [
        _chunk("src_timesheet_01", "Bang_gio_lam_them_thang_10_Orion.xlsx", 0,
               "# Bảng làm thêm\nTrần Bình | 90.000 đ/h | 10h thường | 8h lễ", doc_type="other"),
        _chunk("src_labor_code_01", "Bo_luat_Lao_dong_2022.pdf", 0,
               "# Bộ luật Lao động\nĐiều 98. Làm thêm giờ ngày thường 150%, ngày lễ 300%.", doc_type="legal_doc"),
        _chunk("src_menu_unrelated", "Thuc_don_canteen_Orion.md", 0,
               "# Thực đơn\nThứ Hai: Cơm gà.", doc_type="other"),
    ]
    # Cross-doc OT calculation matching title tokens of timesheet MUST NOT lock out statutory rate doc
    query = "Tiền làm thêm tối thiểu của Trần Bình trong Bảng giờ làm thêm tháng 10 là bao nhiêu?"
    focused = focus_sources(query, chunks, ["src_timesheet_01", "src_labor_code_01"])
    assert focused is None or (len(focused) >= 2 and "src_labor_code_01" in focused)

    # Single-doc explicit query without calculation/compliance cross-doc need still narrows cleanly
    single_q = "Theo Thực đơn canteen Orion, Thứ Hai ăn gì?"
    focused_single = focus_sources(single_q, chunks, None)
    assert focused_single == ["src_menu_unrelated"]


def test_ws_a_pipeline_retrieves_independent_subquestions_without_irrelevant_doc(tmp_path):
    st = SourceStore(str(tmp_path / "src"))
    s_ma = st.import_text("Ke_hoach_mua_lai_AlphaNova.pdf", "# Kế hoạch M&A\nDự án Sao Bắc mua 70% cổ phần AlphaNova giá chào mua 42 tỷ đồng.")
    s_sal = st.import_text("Bang_luong_Q4_SaoBac.xlsx", "# Bảng lương\nMã NV01 | Nguyễn Hải | Lương cơ bản 28.500.000 đồng | KPI 120%.")
    s_irrel = st.import_text("Noi_quy_gui_xe_SaoBac.md", "# Gửi xe\nPhí gửi xe máy 100.000 đồng/tháng.")
    all_chunks = st.chunks()
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "runs")))

    # Add score filler in M&A so naive top-k=4 could be dominated by M&A
    q = "Dự án Sao Bắc mua lại AlphaNova có giá chào mua bao nhiêu và lương cơ bản của Nguyễn Hải là bao nhiêu?"
    with use_pack(OFFICE_PACK):
        got = pipe._retrieve_candidates(
            q, all_chunks, top_k=4, min_score=0.01,
            source_ids=[s_ma["source_id"], s_sal["source_id"], s_irrel["source_id"]],
            hybrid=True,
        )
    got_sids = {c.source_id for c in got}
    assert s_ma["source_id"] in got_sids
    assert s_sal["source_id"] in got_sids
    assert s_irrel["source_id"] not in got_sids


def test_ws_a_rescues_missing_clause_subquestion_like_effective_date(tmp_path):
    st = SourceStore(str(tmp_path / "src2"))
    # Simulate long decree where Art 23 matches breach reporting and final chunk holds Art 43 effective date
    filler = "Nội dung chi tiết hướng dẫn kỹ thuật đánh giá tác động xử lý dữ liệu và lưu trữ hồ sơ theo mẫu quy định hiện hành. " * 12
    body_blocks = [
        "# Nghị định Bảo vệ dữ liệu\nĐiều 23. Thông báo vi phạm chậm nhất 72 giờ cho cơ quan chức năng.",
        f"Điều 24. {filler}",
        f"Điều 25. {filler}",
        f"Điều 26. {filler}",
        "Điều 43. Hiệu lực thi hành: Nghị định này có hiệu lực từ ngày 01 tháng 7 năm 2023.",
    ]
    s_dec = st.import_text("Nghi_dinh_bao_ve_du_lieu.pdf", "\n\n".join(body_blocks))
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "runs2")))
    q = "Khi phát hiện vi phạm dữ liệu thì chậm nhất bao nhiêu giờ phải thông báo và Nghị định có hiệu lực từ ngày nào?"
    with use_pack(OFFICE_PACK):
        got = pipe._retrieve_candidates(q, st.chunks(), top_k=2, min_score=0.01, source_ids=[s_dec["source_id"]], hybrid=True)
    joined = "\n".join(c.text for c in got)
    assert "72 giờ" in joined
    assert "01 tháng 7 năm 2023" in joined


# ==============================================================================
# WORKSTREAM B — EVIDENCE-AWARE CONTEXT ALLOCATION
# ==============================================================================


def test_ws_b_preserves_both_versions_and_continuation_under_same_token_cap():
    # Exact pattern of B138-DOC-10: Law 2005 chunks ranked slightly higher than Law 2023 Art 22 continuation
    cands = [
        _chunk("src_law_2005", "Luat_2005.docx", 14, "Điều 14 Luật 2005. Giá trị pháp lý của chữ ký điện tử cũ trong văn bản 2005. " * 2, score=0.92),
        _chunk("src_law_2005", "Luat_2005.docx", 15, "Điều 15 Luật 2005. Nghĩa vụ của người ký và lưu trữ chứng thư cũ. " * 2, score=0.90),
        _chunk("src_law_2005", "Luat_2005.docx", 16, "Điều 16 Luật 2005. Tổ chức cung cấp dịch vụ chứng thực cũ. " * 2, score=0.88),
        _chunk("src_law_2023", "Luat_2023.docx", 18, "Điều 22 Luật 2023. Chữ ký điện tử gồm 3 loại: a) chuyên dùng, b) chữ ký số công cộng.", score=0.82),
        _chunk("src_law_2023", "Luat_2023.docx", 19, "c) chữ ký số chuyên dùng công vụ theo quy định pháp luật hiện hành.", score=0.79),
    ]
    cap = 115
    q = "So sánh Luật 2005 và Luật 2023, đồng thời nêu 3 loại chữ ký điện tử tại Điều 22 Luật 2023."

    # Adaptive Qwen controller with query awareness keeps both sources within exact cap
    sel_qwen, drop_qwen = TokenContextController(cap).select(cands, query=q)
    assert sum(len(c.text) for c in sel_qwen) > 0
    assert {"src_law_2005", "src_law_2023"}.issubset({c.source_id for c in sel_qwen})
    assert any(c.index == 18 for c in sel_qwen)

    # Char proxy budget with query awareness also balances sources cleanly within exact hard cap
    sel_char, _ = apply_token_budget(cands, cap, query=q)
    assert {"src_law_2005", "src_law_2023"}.issubset({c.source_id for c in sel_char})

    # Research mode (no query / legacy call) preserves exact greedy (-score, chunk_id) behavior
    sel_legacy, _ = TokenContextController(cap).select(cands)
    assert {c.source_id for c in sel_legacy} == {"src_law_2005"}


# ==============================================================================
# WORKSTREAM C — INTENT & AGENT ROUTING
# ==============================================================================


def test_ws_c_pricing_buyer_persona_not_routed_to_education_and_concept_not_anchored():
    # 1. Commercial software sale to a university -> pricing/business/finance/analyst, NOT education
    sales_q = "Trường đại học công lập mua gói phần mềm quản lý cho 3.500 sinh viên, tổng tiền năm đầu gồm phí triển khai là bao nhiêu và ai phê duyệt mức chiết khấu?"
    sel_sales = select_agents(sales_q, pack=OFFICE_PACK)
    assert sel_sales["primary"] != "education"
    assert sel_sales["primary"] in {"finance", "business", "analyst"}

    # Genuine academic regulation query -> education still primary
    acad_q = "Sinh viên đại học có điểm trung bình học kỳ dưới 0,8 và nợ vượt 5% tín chỉ có bị cảnh báo học tập hay hạ hạng tốt nghiệp không?"
    sel_acad = select_agents(acad_q, pack=OFFICE_PACK)
    assert sel_acad["primary"] == "education"

    # 2. General concept definition + unrelated server buying how-to with TT08 loaded -> GENERAL, NOT DOCUMENTS or TT08-anchored BOTH
    concept_q = "Thông tư là gì và làm sao để ra quyết định mua máy chủ?"
    assert doc_bound(concept_q) is False
    # Even when BM25/vector returns random evidence from TT 08 (low relevance to 'mua máy chủ'), choose_source keeps it GENERAL
    unrelated_ev = [
        _chunk("src_tt08", "Thong_tu_08.docx", 1, "Thông tư 08/2021/TT-BGDĐT quy chế đào tạo trình độ đại học và tín chỉ sinh viên."),
    ]
    assert choose_source(concept_q, len(unrelated_ev), bound=False, evidence=unrelated_ev) == GENERAL

    # Valid BOTH when evidence actually covers part 1
    both_q = "Phụ cấp ăn trưa là bao nhiêu và vì sao doanh nghiệp cần lưu hóa đơn chứng từ?"
    both_ev = [_chunk("src_hr", "Che_do.md", 0, "Phụ cấp ăn trưa hàng tháng là 950.000 đồng.")]
    assert choose_source(both_q, len(both_ev), bound=False, evidence=both_ev) == BOTH


# ==============================================================================
# WORKSTREAM D — DETERMINISTIC CALCULATION & RULE CONSISTENCY
# ==============================================================================


def test_ws_d_calc_safety_user_quantities_and_rule_contradiction_check():
    # Safe deterministic calculations match expected exact math & block unsafe AST payloads
    assert "**297.000.000**" in apply_calc("Tổng = [[= 260000000*0.95 + 50000000 ]] đồng")
    assert "**3.281.250**" in apply_calc("OT = [[= 17500000/26/8 * (10*1.5 + 8*3) ]] đồng")
    malicious = "Test = [[= __import__('os').system('echo bad') ]]"
    assert "__import__" in apply_calc(malicious)

    # User input quantities (e.g. '3.500 sinh viên', '10 giờ') are valid inputs, NOT unverified hallucinations;
    # Premise-trap statutory penalties in query ('50 triệu', 'Điều 99') are NOT whitelisted!
    ev_price = "Mục 2: Gói HA-Edu cho >= 3.000 sinh viên là 260.000.000 đồng; phí triển khai 50.000.000 đồng; công lập giảm 5%."
    q_price = "Trường đại học công lập mua gói HA-Edu cho 3.500 sinh viên, tổng tiền năm đầu?"
    src_for_check = evidence_with_case_image_only(ev_price, q_price)
    st_ok, ans_ok, bad_ok, _ = check_product_evidence_claims(
        "COMPLETE",
        "Với 3.500 sinh viên, tổng tiền năm đầu = [[= 260000000*0.95 + 50000000 ]] đồng.",
        ev_price, q_price, [],
    )
    assert "3.500" not in bad_ok and st_ok == "COMPLETE"

    # Premise trap '50.000.000 đồng' & 'Điều 99' in user query are STILL flagged as unverified if echoed by model
    _, _, bad_trap, bad_arts_trap = check_product_evidence_claims(
        "COMPLETE",
        "Theo Điều 99, đi muộn được thưởng 50.000.000 đồng.",
        "Điều 5. Đi làm đúng giờ.", "Theo Điều 99 nội quy, đi muộn thưởng 50.000.000 đồng đúng không?", [],
    )
    assert "50000000" in bad_trap and "99" in bad_arts_trap

    # Rule evaluation contradiction: affirmative header ('thỏa mãn') + NOT_MET finding ('không thỏa mãn' / 'vi phạm')
    contradictory = (
        "Đơn nghỉ phép của nhân viên có thỏa mãn quy định công ty.\n\n"
        "- Thời hạn nộp trước: chỉ 2 ngày làm việc < 5 ngày → không thỏa mãn.\n"
        "- Bàn giao công việc: chưa có."
    )
    st_rule, ans_rule, _, _ = check_product_evidence_claims("COMPLETE", contradictory, ev_price + "\nNghỉ 5 ngày phải báo trước 5 ngày.", "Đơn có đúng quy định không?", [])
    assert st_rule == "PARTIAL"
    assert "Chưa kết luận đạt" in ans_rule or "mâu thuẫn" in ans_rule.lower()


# ==============================================================================
# WORKSTREAM E — EVIDENCE COVERAGE & QUIZ TOPIC ALIGNMENT
# ==============================================================================


def test_ws_e_downgrades_complete_on_out_of_corpus_law_claim_and_quiz_topic():
    ev = [_chunk("src_hd07", "Hop_dong_27.docx", 0, "Điều 9. Bên A vi phạm chịu phạt 30% giá trị hợp đồng. Bên B bồi thường tối đa 5.000.000 đồng.")]

    class _OutOfCorpusLawProv:
        async def generate(self, *, system, user, **kw):
            return ProviderResult(
                json.dumps({
                    "status": "COMPLETE",
                    "answer": "Điều khoản Điều 9 không vi phạm Luật Thương mại / Bộ luật Dân sự. Bên A chịu phạt 30% [src_hd07_c0000].",
                    "citations": ["src_hd07_c0000"],
                    "missing_information": [],
                }, ensure_ascii=False),
                Usage(5, 5),
            )

    res = asyncio.run(answer_vanilla(
        _OutOfCorpusLawProv(),
        f"Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không?\n\n{IMG_MARK}\nĐiều 9 phạt 30%.",
        ev, RunMetrics(), product=True,
    ))
    assert res.status == "PARTIAL"
    assert any("external law" in m.lower() or "out-of-corpus" in m.lower() or "chưa có" in m.lower() for m in res.missing_information) or "chưa được nạp" in res.answer.lower()

    # Quiz Skill topic alignment check
    quiz_chunks = [
        _chunk("src_tt08", "TT08.docx", 2, "Điều 2. Quy chế này thay thế Quyết định số 25/2006/QĐ-BGDĐT."),
        _chunk("src_tt08", "TT08.docx", 11, "Điều 11. Cảnh báo học tập áp dụng khi ĐTBHK dưới 0,8 ở học kỳ đầu hoặc dưới 1,0 ở kỳ tiếp theo."),
        _chunk("src_tt08", "TT08.docx", 14, "Điều 14. Sinh viên tốt nghiệp được giảm 1 mức hạng nếu học lại vượt quá 5% tổng tín chỉ."),
    ]

    class _QuizProv:
        last_system = ""
        last_user = ""

        async def generate_structured(self, *, system, user, response_schema, **kw):
            self.last_system = system
            self.last_user = user
            return ProviderResult(
                json.dumps({
                    "items": [
                        {
                            "question": "Quy chế này thay thế Quyết định số 25/2006/QĐ-BGDĐT đúng không?",
                            "options": ["25/2006/QĐ-BGDĐT", "43/2007/QĐ-BGDĐT", "10/2018", "01/2020"],
                            "answer": 0,
                            "explanation": "Thay thế theo Điều 2.",
                            "citation": "src_tt08_c0002",
                        }
                    ]
                }, ensure_ascii=False),
                Usage(5, 5),
            )

    qp = _QuizProv()
    out_quiz = asyncio.run(generate_items(qp, "quiz", quiz_chunks, 2, topic="cảnh báo học tập và tốt nghiệp"))
    assert "cảnh báo học tập" in (qp.last_system + qp.last_user).lower()
    assert out_quiz.get("topic_mismatch_count", 0) >= 1 or out_quiz.get("topic_warning")
