"""B139.2F5 Test-First RED/GREEN suite: Authoritative Structured Rule Rendering & Legal Claim Grounding.

Covers 14 independent scenarios across:
1. R-02 verbatim reproduction ("đủ 05 ngày làm việc", "không vượt quá 03 ngày liên tiếp", "được ghi rõ").
2. Rule requirements vs actual case observations (general non-HA Vietnamese & English policies).
3. Valid positive policy descriptions preserved when NOT asserting case satisfaction.
4. Eligible rule path preserves positive explanation without false override.
5. Duplicate warning banner & empty heading elimination + unsupported approval claim stripping.
6. R-08A verbatim reproduction ("Bộ luật Dân sự Điều 398", mangled "?" echo, HA_07_c0003 flow).
7. Incorrect legal document identity (statute mentioned in passing inside another legal_doc must NOT count as loaded).
8. Unsupported article number in a loaded statute vs article appearing only in a different statute.
9. Correct legal reference (loaded statute + exact article present in that statute) preserved cleanly.
10. Legal review containing numerical values (30%, 5.000.000 đ, $5,000, 99.9%) never triggers calculation.
11. Quoted contract clauses and interrogative question echoes never corrupted by compliance rewriting.
12. Worker -> Synthesizer HA_07_c0003 evidence flow when worker cites contract header but states Art 9 terms.
13. End-to-end ResearchPipeline `stream == final == persisted` consistency for both rule & legal cases.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.answer_checks import IMG_MARK, check_product_evidence_claims
from app.core.types import RunMetrics, SourceChunk, Task
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.verified_reasoning import _needs_calculation, verify_and_reconcile_answer
from app.research.worker import execute_task
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


# ---------------------------------------------------------------------------
# FIX-01: Authoritative Structured Rule Rendering (R-02 & multi-domain rules)
# ---------------------------------------------------------------------------

def test_f5_01_r02_replaces_inverted_middle_bullets_with_authoritative_rendering() -> None:
    ha_01_c3 = SourceChunk(
        "src_00d7e739cefcc3c2_c0003", "src_00d7e739cefcc3c2", "HA_01",
        "Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc.", 3
    )
    ha_02_c3 = SourceChunk(
        "src_79ae8c1e4c8cbd14_c0003", "src_79ae8c1e4c8cbd14", "HA_02",
        "Nhân viên Kinh doanh phải bàn giao danh sách khách hàng đang theo dõi cho người trực thay trước khi nghỉ. "
        "Mùa cao điểm (tháng 12) hạn chế nghỉ quá 03 ngày liên tiếp. Nghỉ từ 05 ngày liên tiếp phải được Trưởng phòng và Giám đốc Nhân sự phê duyệt.", 3
    )
    q_r02 = (
        "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        f"{IMG_MARK}\n"
        "ĐƠN XIN NGHỈ PHÉP\nPhòng: Kinh doanh\nNgày gửi đơn: thứ Năm 03/12/2026\n"
        "Xin nghỉ phép năm từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc)\n"
        "Người nhận bàn giao khách hàng: chưa có"
    )
    llm_raw = (
        "Đơn nghỉ phép đạt yêu cầu.\n\n"
        "### Kiểm tra điều kiện nghỉ phép\n"
        "1. **Thời gian gửi đơn**: Ngày gửi đơn là thứ Năm 03/12/2026, đủ 05 ngày làm việc trước khi nghỉ (theo quy định: phải gửi đơn trước ít nhất 03 ngày làm việc). [src_00d7e739cefcc3c2_c0003]\n"
        "2. **Thời gian nghỉ phép**: Xin nghỉ từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc), trong khoảng thời gian mùa cao điểm (tháng 12) nên không vượt quá 03 ngày liên tiếp. [src_79ae8c1e4c8cbd14_c0003]\n"
        "3. **Bàn giao khách hàng**: Người nhận bàn giao khách hàng được ghi rõ (theo quy định: phải bàn giao danh sách khách hàng đang theo dõi cho người trực thay). [src_79ae8c1e4c8cbd14_c0003]\n\n"
        "### Kết luận\n"
    )
    vr = verify_and_reconcile_answer(
        query=q_r02,
        chunks=[ha_01_c3, ha_02_c3],
        llm_answer=llm_raw,
        status="COMPLETE",
        allowed_source_ids={"src_00d7e739cefcc3c2", "src_79ae8c1e4c8cbd14"},
    )
    ev_text = "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in [ha_01_c3, ha_02_c3])
    _, final_out, _, _ = check_product_evidence_claims(
        "COMPLETE", vr["final_answer"], ev_text, q_r02, [], evidence_chunks=[ha_01_c3, ha_02_c3]
    )
    low = final_out.casefold()
    assert "đủ 05 ngày làm việc" not in low
    assert "không vượt quá 03 ngày liên tiếp" not in low
    assert "người nhận bàn giao khách hàng được ghi rõ" not in low
    assert final_out.count("Cảnh báo nhất quán") == 1
    assert "NOT_MET" in final_out and "UNKNOWN" in final_out
    assert "src_00d7e739cefcc3c2_c0003" in final_out
    assert "src_79ae8c1e4c8cbd14_c0003" in final_out
    assert "### Kết luận\n\n### Đối chiếu" not in final_out
    # Structured representation fields present
    sr = vr["structured_result"]
    assert sr["overall_verdict"] == "NOT_ELIGIBLE"
    assert len(sr["condition_verdicts"]) >= 4


def test_f5_02_unseen_en_deployment_rule_contradiction_replaced_deterministically() -> None:
    policy = SourceChunk(
        "src_sre_01_c0001", "src_sre_01", "SRE Change Policy",
        "All production deployments must be submitted at least 05 working days prior and must include rollback handoff. "
        "Above 3 days during peak month 12 is restricted.", 1
    )
    q_sre = (
        "Is this deployment change request compliant with SRE policy?\n\n"
        f"{IMG_MARK}\n"
        "Submitted: 03/12/2026\nTrip: 07/12/2026 to 11/12/2026 (5 working days)\nHandoff: chưa có"
    )
    llm_bad = (
        "### Evaluation\n"
        "1. **Notice window**: Submitted 03/12/2026, meets the 05 working days advance notice requirement [src_sre_01_c0001].\n"
        "2. **Peak freeze**: Does not exceed 03 days during peak month 12.\n"
        "3. **Rollback handoff**: Rollback owner is clearly specified.\n"
    )
    vr = verify_and_reconcile_answer(query=q_sre, chunks=[policy], llm_answer=llm_bad, status="COMPLETE")
    ev_txt = f"[{policy.chunk_id}] {policy.text}"
    _, out, _, _ = check_product_evidence_claims("COMPLETE", vr["final_answer"], ev_txt, q_sre, [], evidence_chunks=[policy])
    assert "meets the 05 working days" not in out.casefold()
    assert "does not exceed 03 days" not in out.casefold()
    assert "clearly specified" not in out.casefold()
    assert out.count("Cảnh báo nhất quán") == 1
    assert "NOT_MET" in out
    assert "src_sre_01_c0001" in out


def test_f5_03_valid_positive_policy_description_preserved_when_separate_from_case_assertion() -> None:
    policy = SourceChunk(
        "src_hr_gen_c0001", "src_hr_gen", "HR Handbook",
        "Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc. Phải bàn giao công việc trước khi nghỉ.", 1
    )
    q_hr = (
        "Đơn này có đúng quy định không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 03/12/2026\nTừ 07/12/2026 đến 11/12/2026 (5 ngày)\nBàn giao: chưa có"
    )
    # Policy statement describes what the rule requires (valid positive wording), NOT claiming the employee satisfied it
    llm_mixed = (
        "### Quy định áp dụng\n"
        "- Theo chính sách công ty, đơn hợp lệ khi nộp trước ít nhất 05 ngày làm việc và bàn giao đầy đủ [src_hr_gen_c0001].\n\n"
        "### Kiểm tra trường hợp\n"
        "- Thời hạn nộp đơn: chưa đủ 05 ngày làm việc.\n"
    )
    vr = verify_and_reconcile_answer(query=q_hr, chunks=[policy], llm_answer=llm_mixed, status="COMPLETE")
    out = vr["final_answer"]
    assert "Theo chính sách công ty, đơn hợp lệ khi nộp trước ít nhất 05 ngày làm việc" in out
    assert "NOT_MET" in out
    assert "src_hr_gen_c0001" in out


def test_f5_04_eligible_case_preserves_positive_explanation() -> None:
    policy = SourceChunk(
        "src_elig_c0001", "src_elig", "Leave Policy",
        "Nghỉ phép phải nộp đơn trước ít nhất 03 ngày làm việc.", 1
    )
    q_ok = (
        "Đơn này có đúng quy định không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 01/12/2026\nTừ 10/12/2026 đến 11/12/2026 (2 ngày)\nNgày phép đã nghỉ: 2"
    )
    llm_ok = "Đơn hợp lệ vì nộp trước 07 ngày làm việc, đáp ứng quy định tối thiểu 03 ngày làm việc [src_elig_c0001]."
    vr = verify_and_reconcile_answer(query=q_ok, chunks=[policy], llm_answer=llm_ok, status="COMPLETE")
    assert "NOT_ELIGIBLE" not in vr["final_answer"]
    assert "đáp ứng quy định" in vr["final_answer"]


def test_f5_05_duplicate_banner_and_unsupported_approval_claim_prevented() -> None:
    policy = SourceChunk(
        "src_proc_c0001", "src_proc", "Procurement Policy",
        "| Mức chiết khấu | Cấp phê duyệt |\n|---|---|\n| 0% - 5% | Nhân viên Kinh doanh tự quyết |\n| Trên 5% - 15% | Trưởng phòng Kinh doanh |", 1
    )
    q = "Đơn này chiết khấu 4% có hợp lệ không và ai phê duyệt?"
    llm = (
        "> **Cảnh báo nhất quán:** Banner thừa.\n\n"
        "Khoản chiết khấu được phê duyệt bởi Giám đốc Kinh doanh [src_proc_c0001]."
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[policy], llm_answer=llm, status="COMPLETE")
    assert "Giám đốc Kinh doanh" not in vr["final_answer"]
    assert "Nhân viên Kinh doanh" in vr["final_answer"]
    assert vr["final_answer"].count("Cảnh báo nhất quán") <= 1


# ---------------------------------------------------------------------------
# FIX-02: Conservative Legal Claim Grounding (R-08A & general legal docs)
# ---------------------------------------------------------------------------

def test_f5_06_r08a_refuses_blds_and_luat_thuong_mai_and_preserves_question_echo() -> None:
    c_nd13 = SourceChunk(
        "src_fe6a508650e0d0a8_c0001", "src_fe6a508650e0d0a8", "PL Nghi dinh 13-2023-ND-CP Bao ve du lieu ca nhan",
        "Điều 1. Căn cứ Bộ luật Dân sự 2015 và Luật An ninh mạng, Nghị định này quy định bảo vệ dữ liệu cá nhân.", 1,
        provenance={"doc_type": "legal_doc"},
    )
    c_ha07 = SourceChunk(
        "src_aadf23faaa3faec1_c0003", "src_aadf23faaa3faec1", "HA 07 Hop dong cung cap phan mem HA-Edu",
        "Điều 9.1: Bên A vi phạm chịu phạt 30% giá trị hợp đồng. Điều 9.2: Tổng trách nhiệm bồi thường của Bên B tối đa 5.000.000 đồng.", 3,
        provenance={"doc_type": "contract"},
    )
    q_r08a = (
        "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không? Rủi ro cho bên A là gì?\n\n"
        f"{IMG_MARK}\nTRÍCH HỢP ĐỒNG 27/2026/HĐ-HAEDU\n"
        "Điều 9.1: Phạt 30% tổng giá trị hợp đồng.\nĐiều 9.2: Bồi thường tối đa 5.000.000 đồng."
    )
    llm_r08a = (
        "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không?\n\n"
        "Điều khoản 'Tổng trách nhiệm bồi thường của Bên B không vượt quá 5.000.000 đồng' vi phạm quy định về trách nhiệm bồi thường trong Bộ luật Dân sự 2015 (Điều 398).\n\n"
        "Rủi ro cho Bên A:\n- Phạt 30% tổng giá trị hợp đồng [src_aadf23faaa3faec1_c0003]\n- Bồi thường bị giới hạn 5.000.000 đồng [src_aadf23faaa3faec1_c0003]\n\n"
        "| Điều khoản | Quy định pháp lý | Kết luận | Nguồn |\n|---|---|---|---|\n"
        "| Phạt 30% | Điều 398 Bộ luật Dân sự 2015: mức phạt tối đa | Vi phạm pháp luật | src_fe6a508650e0d0a8_c0001 |"
    )
    ev_txt = f"[{c_nd13.chunk_id}] {c_nd13.text}\n[{c_ha07.chunk_id}] {c_ha07.text}"
    st, out, _, bad_arts = check_product_evidence_claims(
        "COMPLETE", llm_r08a, ev_txt, q_r08a, [], evidence_chunks=[c_nd13, c_ha07]
    )
    # 1. Question echo NOT mangled
    assert "có chưa đủ căn cứ kết luận" not in out
    # 2. Both Luật Thương mại AND Bộ luật Dân sự recognized as NOT loaded (even though NĐ 13 mentions Bộ luật Dân sự in preamble!)
    assert "Luật Thương mại" in out and "Bộ luật Dân sự" in out
    assert "Lưu ý phạm vi pháp lý" in out
    # 3. Unsupported Điều 398 flagged & unverified BLDS assertion not left as verified fact
    assert "398" in bad_arts or "chưa đủ căn cứ" in out.casefold()
    assert st == "PARTIAL"
    # 4. Supported contract risks preserved
    assert "30%" in out and "5.000.000" in out


def test_f5_07_article_appearing_in_different_document_is_rejected_as_unverified() -> None:
    # Chunk A (NĐ 13) has Điều 23, Chunk B is a contract; LLM falsely claims "Điều 23 Bộ luật Dân sự"!
    c_nd13 = SourceChunk(
        "src_nd13_c0023", "src_nd13", "Nghị định 13/2023/NĐ-CP",
        "Điều 23. Thông báo vi phạm quy định bảo vệ dữ liệu cá nhân trong 72 giờ.", 23,
        provenance={"doc_type": "legal_doc"},
    )
    q = "Điều khoản hợp đồng này có vi phạm Bộ luật Dân sự không?"
    llm = "Theo Điều 23 Bộ luật Dân sự 2015, điều khoản này vi phạm quy định bồi thường [src_nd13_c0023]."
    st, out, _, _ = check_product_evidence_claims(
        "COMPLETE", llm, f"[{c_nd13.chunk_id}] {c_nd13.text}", q, [], evidence_chunks=[c_nd13]
    )
    assert st == "PARTIAL"
    assert "Bộ luật Dân sự" in out
    assert "chưa được nạp" in out.casefold() or "chưa có" in out.casefold()


def test_f5_08_correct_legal_reference_with_matching_doc_and_article_is_preserved() -> None:
    c_blld = SourceChunk(
        "src_blld_c0098", "src_blld", "Bộ luật Lao động 2019",
        "Bộ luật Lao động 2019 - Điều 98. Tiền lương làm thêm giờ vào ngày thường ít nhất bằng 150%, ngày lễ ít nhất bằng 300%.", 98,
        provenance={"doc_type": "legal_doc"},
    )
    q = "Làm thêm ngày thường theo Bộ luật Lao động có đúng pháp luật không?"
    llm = "Theo Điều 98 Bộ luật Lao động 2019, làm thêm ngày thường được trả ít nhất 150% [src_blld_c0098]."
    st, out, bad_nums, bad_arts = check_product_evidence_claims(
        "COMPLETE", llm, f"[{c_blld.chunk_id}] {c_blld.text}", q, [], evidence_chunks=[c_blld]
    )
    assert st == "COMPLETE"
    assert not bad_nums and not bad_arts
    assert "Lưu ý phạm vi pháp lý" not in out
    assert "Điều 98 Bộ luật Lao động 2019" in out


def test_f5_09_legal_review_with_numbers_never_triggers_calculation_and_preserves_quotes() -> None:
    q_legal_nums = (
        "Điều khoản phạt này có hợp lệ theo Luật Thương mại không và rủi ro cho Bên Mua là gì?\n\n"
        f"{IMG_MARK}\nĐiều 12.1: Phạt vi phạm 25% giá trị hợp đồng; bồi thường tối đa 10.000.000 đồng."
    )
    assert _needs_calculation(q_legal_nums, {}) is False

    c_contract = SourceChunk(
        "src_msa_c0004", "src_msa", "Master Service Agreement",
        "Điều 12.1: Phạt vi phạm 25% giá trị hợp đồng; bồi thường tối đa 10.000.000 đồng.", 4,
        provenance={"doc_type": "contract"},
    )
    llm = (
        "> Trích dẫn: \"Điều 12.1: không vi phạm pháp luật nếu hai bên thỏa thuận\".\n\n"
        "Rủi ro cho Bên Mua là mức phạt 25% và trần bồi thường 10.000.000 đồng [src_msa_c0004]."
    )
    st, out, _, _ = check_product_evidence_claims(
        "COMPLETE", llm, f"[{c_contract.chunk_id}] {c_contract.text}", q_legal_nums, [], evidence_chunks=[c_contract]
    )
    # Blockquote preserved verbatim; scope warning appended cleanly
    assert '> Trích dẫn: "Điều 12.1: không vi phạm pháp luật nếu hai bên thỏa thuận".' in out
    assert "25%" in out and "10.000.000" in out


def test_f5_10_worker_retains_ha07_c0003_citation_when_discussing_clause_9_terms() -> None:
    c_hdr = SourceChunk("src_aadf23faaa3faec1_c0000", "src_aadf23faaa3faec1", "HA_07", "HỢP ĐỒNG CUNG CẤP PHẦN MỀM HA-EDU số 27/2026/HĐ-HAEDU.", 0)
    c_art9 = SourceChunk("src_aadf23faaa3faec1_c0003", "src_aadf23faaa3faec1", "HA_07", "Điều 9.1 Phạt vi phạm 30% tổng giá trị hợp đồng. Điều 9.2 Tổng trách nhiệm bồi thường của Bên B tối đa 5.000.000 đồng.", 3)

    class _WorkerFake(FakeProvider):
        async def generate_grounded(self, system: str, user: str, evidence_ids: list[str], **kwargs: Any):
            from app.core.types import Usage
            from app.providers.base import ProviderResult
            # Simulates qwen3:4b citing only c0000 while writing Điều 9.1 (30%) & Điều 9.2 (5.000.000 đồng) from c0003
            payload = (
                '{"status":"PARTIAL","answer":"Hợp đồng có Điều 9.1 phạt 30% tổng giá trị hợp đồng và Điều 9.2 giới hạn bồi thường 5.000.000 đồng.",'
                '"citations":["src_aadf23faaa3faec1_c0000"],"missing_information":["Luật Thương mại"]}'
            )
            return ProviderResult(text=payload, model=self.model, usage=Usage(10, 10))

    from app.research.registry import use_pack
    task = Task(task_id="T2", domain="business", goal="Phân tích rủi ro Điều 9 hợp đồng HA-Edu")
    with use_pack("office"):
        res = asyncio.run(
            execute_task(
                _WorkerFake(),
                task,
                [c_hdr, c_art9],
                RunMetrics(),
                product=True,
                user_request="Rủi ro Điều 9.1 (30%) và Điều 9.2 (5.000.000 đồng) là gì?",
            )
        )
    assert "src_aadf23faaa3faec1_c0003" in res.citations


def test_f5_11_pipeline_stream_equals_final_equals_persisted_for_rule_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", "on")

    ss = SourceStore(str(tmp_path / "src"))
    rs = RunStore(str(tmp_path / "runs"))
    ss.import_text(
        "HA_01",
        "Nghị định / Nội quy: Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc. Phải bàn giao công việc trước khi nghỉ.",
        provenance={"owner_user_id": "usr_1"},
    )

    chunks = ss.chunks()
    cid = chunks[0].chunk_id
    captured: list[str] = []

    class _StreamFake(FakeProvider):
        async def generate(self, *, system: str, user: str):
            from app.core.types import ProviderResult, Usage
            if any(k in system.upper() for k in ("WORKER", "SYNTHESIZER", "VANILLA_RAG_ANSWERER")):
                import json as _json
                ans = (
                    f"Đơn đạt yêu cầu [{cid}].\n"
                    f"1. Thời gian gửi đơn: đủ 05 ngày làm việc [{cid}].\n"
                    f"2. Bàn giao công việc: được ghi rõ [{cid}]."
                )
                txt = ans if "SYNTHESIZER" in system.upper() else _json.dumps({"status": "COMPLETE", "answer": ans, "citations": [cid]}, ensure_ascii=False)
                return ProviderResult(text=txt, model=self.model, usage=Usage(10, 10))
            return await super().generate(system=system, user=user)

    from app.research import pipeline as pl_mod
    from app.research.progress import progress_sink
    pipe = ResearchPipeline(ss, rs)
    orig_get_provider = pl_mod.get_provider
    pl_mod.get_provider = lambda name=None: _StreamFake()
    q = (
        "Đơn này có đúng quy định không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 03/12/2026\nTừ 07/12/2026 đến 11/12/2026 (5 ngày)\nBàn giao: chưa có"
    )
    async def _run():
        tok = progress_sink.set(lambda ev: captured.append(ev["text"]) if ev.get("type") == "answer" else None)
        try:
            return await pipe.run(q, condition="C", provider_name="fake", product_mode=True)
        finally:
            progress_sink.reset(tok)
    try:
        run_res = asyncio.run(_run())
    finally:
        pl_mod.get_provider = orig_get_provider

    persisted = rs.get(run_res["run_id"])
    assert persisted is not None
    streamed_text = captured[-1] if captured else ""
    assert streamed_text == run_res["answer"] == persisted["answer"]
    assert "đủ 05 ngày làm việc" not in run_res["answer"].casefold()
    assert "được ghi rõ" not in run_res["answer"].casefold()
    assert run_res["answer"].count("Cảnh báo nhất quán") == 1


def test_f5_12_partial_statute_loaded_does_not_auto_declare_missing_statute_compliant() -> None:
    c_nd13 = SourceChunk(
        "src_nd13_c0023", "src_nd13", "Nghị định 13/2023/NĐ-CP",
        "Điều 23. Thông báo vi phạm dữ liệu cá nhân trong 72 giờ.", 23,
        provenance={"doc_type": "legal_doc"},
    )
    q = "Hợp đồng này có vi phạm Nghị định 13/2023 và Luật Thương mại không?"
    llm = "Hợp đồng đáp ứng Điều 23 Nghị định 13/2023 và không vi phạm Luật Thương mại [src_nd13_c0023]."
    st, out, _, _ = check_product_evidence_claims(
        "COMPLETE", llm, f"[{c_nd13.chunk_id}] {c_nd13.text}", q, [], evidence_chunks=[c_nd13]
    )
    assert st == "PARTIAL"
    assert "Luật Thương mại" in out
    assert "chưa đủ căn cứ kết luận có vi phạm hay không" in out
    assert "Lưu ý phạm vi pháp lý" in out
