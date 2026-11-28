"""B139.2F6 Test-First RED/GREEN suite: Authoritative Answer Generation & Claim Safety.

Covers 13 independent adversarial scenarios (separate from F5) proving:
1. R-02 exact B139.2R4 reproduction: `### Phân tích`, fabricated `10/12/2026`, and `→ đúng` eliminated via VerifiedStructuredResult SSoT.
2. Unheaded flat narrative rule contradiction replaced cleanly without relying on section headings.
3. Novel/arbitrary headings (`### Tóm tắt đánh giá`, `## Detailed Assessment`) with `✓` / `PASS` / `→ đúng` eliminated.
4. Fabricated case dates and fabricated approval confirmations (`đã được Giám đốc phê duyệt`) rejected when absent from case & evidence.
5. Pure abstract policy descriptions preserved cleanly alongside authoritative case verdicts.
6. Missing condition facts remain explicitly `UNKNOWN` (never coerced to `MET` or `NOT_MET`).
7. FIX-04 (`worker.py`): Unrelated documents sharing identical numbers (`30%`, `5.000.000`) are NOT promoted to citations; clause + semantic overlap IS promoted.
8. R-08A exact B139.2R4 reproduction: mangled opening (`Thương mại và Bộ luật Dân sự 2015...`) eliminated and unverified exceedance (`vượt quá giới hạn cho phép theo Bộ luật Dân sự 2015 (Điều 398)`) retracted while factual contract risks (`30%`, `5.000.000 đồng`) remain intact.
9. Loaded statute + article with valid wording preserved; unverified interpretation/external statute rejected; English & non-HA legal review covered.
10. Partial legal evidence (one loaded statute + one missing statute) preserves loaded applicability and qualifies/retracts missing statute conclusion.
11. General non-rule / non-legal lookup (product spec / SOP) bypasses structured rule/legal overrides cleanly (`COMPLETE`).
12. FIX-05 Single Validated Answer Artifact across buffered NDJSON stream == final return == persisted `RunStore` even when `knowledge_label` or `reviewer` runs in `ResearchPipeline`, and in `vanilla` buffered path.
13. ACL enforcement: unauthorized chunks excluded from rule evaluation, approval authority resolution, and citation promotion.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.answer_checks import IMG_MARK, check_product_evidence_claims
from app.core.types import RunMetrics, SourceChunk, Task, Usage
from app.providers.base import ProviderResult
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.progress import ndjson_run
from app.research.registry import use_pack
from app.research.verified_reasoning import verify_and_reconcile_answer
from app.research.worker import execute_task
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


# ---------------------------------------------------------------------------
# FIX-01 & FIX-02: Single Source of Truth + Fabricated Case Fact Prevention
# ---------------------------------------------------------------------------


def test_f6_01_r02_live_repro_phan_tich_and_fabricated_date_eliminated() -> None:
    ha_01 = SourceChunk(
        "src_00d7e739cefcc3c2_c0003", "src_00d7e739cefcc3c2", "HA_01",
        "Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc.", 3,
    )
    ha_02 = SourceChunk(
        "src_79ae8c1e4c8cbd14_c0003", "src_79ae8c1e4c8cbd14", "HA_02",
        "Nhân viên Kinh doanh phải bàn giao danh sách khách hàng đang theo dõi cho người trực thay trước khi nghỉ. "
        "Mùa cao điểm (tháng 12) hạn chế nghỉ quá 03 ngày liên tiếp. Nghỉ từ 05 ngày liên tiếp phải được Trưởng phòng và Giám đốc Nhân sự phê duyệt.", 3,
    )
    q_r02 = (
        "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        f"{IMG_MARK}\n"
        "ĐƠN XIN NGHỈ PHÉP\nPhòng: Kinh doanh\nNgày gửi đơn: thứ Năm 03/12/2026\n"
        "Xin nghỉ phép năm từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc)\n"
        "Người nhận bàn giao khách hàng: chưa có"
    )
    # Exact pattern observed in B139.2R4 run_4aec84033c55
    llm_r02_live = (
        "### Phân tích\n"
        "- **Điều kiện 1**: Đơn được gửi trước 03 ngày làm việc (03/12/2026 → 10/12/2026) → **đúng**. [src_00d7e739cefcc3c2_c0003]\n"
        "- **Điều kiện 2**: Không có dữ liệu về thời gian nghỉ quá 03 ngày liên tiếp trong tháng 12 → **chưa đủ dữ liệu**. [src_79ae8c1e4c8cbd14_c0003]\n\n"
        "### Điều kiện nghỉ phép\n"
        "Nhân viên đủ điều kiện nghỉ phép nếu đáp ứng quy định báo trước 03 ngày làm việc [src_00d7e739cefcc3c2_c0003].\n\n"
        "### Kết luận\n"
        "Đơn xin nghỉ phép đạt yêu cầu về thời gian gửi đơn và bàn giao."
    )
    vr = verify_and_reconcile_answer(
        query=q_r02,
        chunks=[ha_01, ha_02],
        llm_answer=llm_r02_live,
        status="COMPLETE",
        allowed_source_ids={"src_00d7e739cefcc3c2", "src_79ae8c1e4c8cbd14"},
    )
    out = vr["final_answer"]
    low = out.casefold()
    assert vr["structured_result"]["overall_verdict"] == "NOT_ELIGIBLE"
    # Fabricated date 10/12/2026 and false "→ đúng" MUST NOT survive
    assert "10/12/2026" not in out
    assert "→ **đúng**" not in low and "→ đúng" not in low
    assert "được gửi trước 03 ngày làm việc" not in low
    assert "đạt yêu cầu về thời gian gửi đơn" not in low
    assert "NOT_ELIGIBLE" in out or "không đủ điều kiện" in low or "chưa đạt" in low
    assert "NOT_MET" in out and "UNKNOWN" in out
    assert "src_00d7e739cefcc3c2_c0003" in out and "src_79ae8c1e4c8cbd14_c0003" in out


def test_f6_02_unheaded_flat_narrative_contradiction_replaced_wholesale() -> None:
    policy = SourceChunk(
        "src_fin_c0001", "src_fin", "Finance Travel Policy",
        "Đề nghị công tác phải nộp đơn trước ít nhất 05 ngày làm việc. Phải có kế hoạch bàn giao trước khi đi.", 1,
    )
    q = (
        "Đơn công tác này có hợp lệ không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 03/12/2026\nTừ 07/12/2026 đến 10/12/2026 (4 ngày)\nBàn giao: chưa có"
    )
    # Zero markdown headings, pure narrative paragraph contradicting VerifiedStructuredResult
    llm_flat = (
        "Đơn công tác này hoàn toàn hợp lệ và đáp ứng đầy đủ quy định công ty vì nhân viên đã gửi trước hạn "
        "và đã có kế hoạch bàn giao công việc rõ ràng [src_fin_c0001]."
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[policy], llm_answer=llm_flat, status="COMPLETE")
    out = vr["final_answer"]
    assert "hoàn toàn hợp lệ" not in out.casefold()
    assert "đáp ứng đầy đủ" not in out.casefold()
    assert "kế hoạch bàn giao công việc rõ ràng" not in out.casefold()
    assert vr["structured_result"]["overall_verdict"] == "NOT_ELIGIBLE"
    assert "NOT_MET" in out
    assert "src_fin_c0001" in out


def test_f6_03_arbitrary_headings_with_checkmarks_and_pass_tokens_eliminated() -> None:
    policy = SourceChunk(
        "src_sec_c0001", "src_sec", "SecOps Change Standard",
        "All production releases must be submitted at least 05 working days prior and must include rollback handoff.", 1,
    )
    q = (
        "Does this release ticket satisfy SecOps policy?\n\n"
        f"{IMG_MARK}\nSubmitted: 03/12/2026\nTrip: 07/12/2026 to 11/12/2026 (5 working days)\nRollback: missing"
    )
    llm_arbitrary = (
        "### Executive Snapshot\n"
        "- Lead time window: 03/12/2026 to 09/12/2026 ✓ PASS [src_sec_c0001]\n"
        "- Rollback owner verified: YES -> compliant.\n"
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[policy], llm_answer=llm_arbitrary, status="COMPLETE")
    out = vr["final_answer"]
    assert "09/12/2026" not in out
    assert "✓ PASS" not in out
    assert "compliant" not in out.casefold() or "non-compliant" in out.casefold()
    assert "rollback owner verified: yes" not in out.casefold()
    assert "NOT_MET" in out
    assert "src_sec_c0001" in out


def test_f6_04_fabricated_dates_and_fabricated_approval_status_rejected() -> None:
    policy = SourceChunk(
        "src_capex_c0001", "src_capex", "Capex Policy",
        "Mua sắm từ 5 ngày liên tiếp hoặc vượt ngưỡng phải được Giám đốc Tài chính phê duyệt. "
        "Phải nộp đơn trước ít nhất 05 ngày làm việc.", 1,
    )
    q = (
        "Đơn nghỉ triển khai này có đúng quy định không và ai phê duyệt?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 03/12/2026\nTừ 07/12/2026 đến 11/12/2026 (5 ngày làm việc)"
    )
    # Hallucinates date 18/12/2026 and claims CFO already approved
    llm_fab = (
        "### Tóm tắt đánh giá\n"
        "- Đơn nộp ngày 03/12/2026 cho đợt từ 18/12/2026 nên đạt thời hạn [src_capex_c0001].\n"
        "- Đơn đã được Giám đốc Tài chính phê duyệt đầy đủ."
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[policy], llm_answer=llm_fab, status="COMPLETE")
    out = vr["final_answer"]
    assert "18/12/2026" not in out
    assert "đã được giám đốc tài chính phê duyệt" not in out.casefold()
    assert "UNKNOWN" in out


def test_f6_05_pure_abstract_policy_statements_preserved_alongside_ssot_verdict() -> None:
    policy = SourceChunk(
        "src_hr_abs_c0001", "src_hr_abs", "HR Standard",
        "Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc. Phải bàn giao công việc trước khi nghỉ.", 1,
    )
    q = (
        "Đơn này có đúng quy định không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 03/12/2026\nTừ 07/12/2026 đến 11/12/2026 (5 ngày)\nBàn giao: chưa có"
    )
    llm_mixed = (
        "- Theo chính sách công ty, đơn hợp lệ khi nộp trước ít nhất 05 ngày làm việc và bàn giao đầy đủ [src_hr_abs_c0001].\n"
        "- Trường hợp này đơn nộp trước 10/12/2026 nên đạt điều kiện!"
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[policy], llm_answer=llm_mixed, status="COMPLETE")
    out = vr["final_answer"]
    assert "Theo chính sách công ty, đơn hợp lệ khi nộp trước ít nhất 05 ngày làm việc" in out
    assert "10/12/2026" not in out
    assert "NOT_MET" in out


def test_f6_06_insufficient_info_keeps_unknown_conditions_never_coerces_met_or_not_met() -> None:
    policy = SourceChunk(
        "src_trv_c0001", "src_trv", "Travel Leave Policy",
        "Nghỉ từ 05 ngày liên tiếp phải được Trưởng phòng và Giám đốc Nhân sự phê duyệt.", 1,
    )
    # Submits plenty early, no handoff issue, missing remaining balance + approval confirmation -> INSUFFICIENT_INFO
    q = (
        "Đơn này có đủ điều kiện nghỉ phép không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 01/12/2026\nTừ 14/12/2026 đến 18/12/2026 (5 ngày làm việc)"
    )
    llm_overclaim = (
        "### Kết quả kiểm tra\n"
        "Đơn đủ điều kiện và đã được phê duyệt tự động, nhân viên còn dư 10 ngày phép [src_trv_c0001]."
    )
    vr = verify_and_reconcile_answer(query=q, chunks=[policy], llm_answer=llm_overclaim, status="COMPLETE")
    out = vr["final_answer"]
    assert vr["structured_result"]["overall_verdict"] == "INSUFFICIENT_INFO"
    assert "UNKNOWN" in out
    assert "đã được phê duyệt" not in out.casefold()
    assert "10 ngày phép" not in out


# ---------------------------------------------------------------------------
# FIX-04: Worker Citation Integrity (no numeric-only promotion across docs)
# ---------------------------------------------------------------------------


def test_f6_07_worker_does_not_promote_unrelated_doc_sharing_same_numbers() -> None:
    c_ha07 = SourceChunk(
        "src_aadf23faaa3faec1_c0003", "src_aadf23faaa3faec1", "HA_07 Hợp đồng HA-Edu",
        "Điều 9.1 Phạt vi phạm 30% tổng giá trị hợp đồng. Điều 9.2 Tổng trách nhiệm bồi thường của Bên B tối đa 5.000.000 đồng.", 3,
        provenance={"doc_type": "contract"},
    )
    # Unrelated SLA document that coincidentally contains BOTH "30%" and "5.000.000"!
    c_unrelated_sla = SourceChunk(
        "src_unrelated_sla_c0002", "src_unrelated_sla", "SLA Băng thông Internet 2025",
        "Mục tiêu dịch vụ: giảm trừ cước 30% phí tháng nếu gián đoạn kéo dài, trần hỗ trợ sự cố đường truyền 5.000.000 đồng/năm.", 2,
        provenance={"doc_type": "policy"},
    )

    class _WorkerDualFake(FakeProvider):
        async def generate_grounded(self, system: str, user: str, evidence_ids: list[str], **kwargs: Any):
            payload = (
                '{"status":"PARTIAL","answer":"Theo Điều 9.1 hợp đồng phần mềm, Bên A chịu phạt 30% tổng giá trị hợp đồng '
                'và theo Điều 9.2 trách nhiệm bồi thường của Bên B tối đa 5.000.000 đồng.",'
                '"citations":["src_aadf23faaa3faec1_c0003"],"missing_information":["Luật Thương mại"]}'
            )
            return ProviderResult(text=payload, model=self.model, usage=Usage(10, 10))

    task = Task(task_id="T2", domain="business", goal="Phân tích Điều 9.1 và Điều 9.2 hợp đồng phần mềm")
    with use_pack("office"):
        res = asyncio.run(
            execute_task(
                _WorkerDualFake(),
                task,
                [c_ha07, c_unrelated_sla],
                RunMetrics(),
                product=True,
                user_request="Rủi ro Điều 9.1 (30%) và Điều 9.2 (5.000.000 đồng) trong hợp đồng phần mềm là gì?",
            )
        )
    assert "src_aadf23faaa3faec1_c0003" in res.citations
    assert "src_unrelated_sla_c0002" not in res.citations


# ---------------------------------------------------------------------------
# FIX-03: Conservative Legal Claim Safety (R-08A & general legal docs)
# ---------------------------------------------------------------------------


def test_f6_08_r08a_live_repro_clean_opening_and_unverified_limit_retraction() -> None:
    c_nd13 = SourceChunk(
        "src_fe6a508650e0d0a8_c0001", "src_fe6a508650e0d0a8", "PL Nghi dinh 13-2023-ND-CP",
        "Điều 1. Căn cứ Bộ luật Dân sự 2015, Nghị định này quy định về bảo vệ dữ liệu cá nhân.", 1,
        provenance={"doc_type": "legal_doc"},
    )
    c_ha07 = SourceChunk(
        "src_aadf23faaa3faec1_c0003", "src_aadf23faaa3faec1", "HA 07 Hop dong HA-Edu",
        "Điều 9.1: Bên A vi phạm chịu phạt 30% tổng giá trị hợp đồng. Điều 9.2: Tổng trách nhiệm bồi thường của Bên B tối đa 5.000.000 đồng.", 3,
        provenance={"doc_type": "contract"},
    )
    q_r08a = (
        "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không? Rủi ro cho bên A là gì?\n\n"
        f"{IMG_MARK}\nTRÍCH HỢP ĐỒNG 27/2026/HĐ-HAEDU\n"
        "Điều 9.1: Phạt 30% tổng giá trị hợp đồng.\nĐiều 9.2: Bồi thường tối đa 5.000.000 đồng."
    )
    # Exact ungrounded phrasing patterns observed in B139.2R4 run_4ecb896ca646
    llm_r08a_live = (
        "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không?\n\n"
        "Điều khoản này có thể vi phạm Luật Thương mại và Bộ luật Dân sự 2015 do mức phạt 30% tổng giá trị hợp đồng "
        "vượt quá giới hạn cho phép và giới hạn bồi thường 5.000.000 đồng là bất lợi.\n\n"
        "Rủi ro cho Bên A:\n"
        "- Phạt 30% tổng giá trị hợp đồng có thể vượt quá giới hạn cho phép theo Bộ luật Dân sự 2015 (Điều 398) [src_aadf23faaa3faec1_c0003]\n"
        "- Giới hạn bồi thường 5.000.000 đồng cho Bên B làm Bên A chịu thiệt hại lớn [src_aadf23faaa3faec1_c0003]\n"
    )
    ev_txt = f"[{c_nd13.chunk_id}] {c_nd13.text}\n[{c_ha07.chunk_id}] {c_ha07.text}"
    st, out, _, _ = check_product_evidence_claims(
        "COMPLETE", llm_r08a_live, ev_txt, q_r08a, [], evidence_chunks=[c_nd13, c_ha07]
    )
    low = out.casefold()
    # 1. Opening must NEVER be mangled ("...chưa được nạp) Thương mại và Bộ luật Dân sự 2015 do...")
    assert ") thương mại" not in low
    assert "có thể chưa đủ căn cứ kết luận" not in low
    # 2. Question line stays clean
    assert "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không?" in out
    # 3. Unverified exceedance / BLDS Art 398 conclusion must NOT remain as a positive legal conclusion
    assert "vượt quá giới hạn cho phép theo bộ luật dân sự" not in low
    assert "mức phạt 30% tổng giá trị hợp đồng vượt quá giới hạn cho phép" not in low
    # 4. Contract facts & commercial risks ARE preserved
    assert "30%" in out and "5.000.000" in out
    assert st == "PARTIAL"
    assert "Lưu ý phạm vi pháp lý" in out


def test_f6_09_partial_legal_evidence_keeps_loaded_law_and_neutralizes_missing_law() -> None:
    c_labor = SourceChunk(
        "src_blld_c0098", "src_blld", "Bộ luật Lao động 2019",
        "Điều 98. Tiền lương làm thêm giờ vào ngày thường ít nhất bằng 150%, ngày lễ ít nhất bằng 300%.", 98,
        provenance={"doc_type": "legal_doc"},
    )
    q = "Thỏa thuận làm thêm giờ 150% và phạt vi phạm 20% có vi phạm Bộ luật Lao động hay Luật Thương mại không?"
    llm = (
        "Theo Điều 98 Bộ luật Lao động 2019, mức trả làm thêm ngày thường 150% là phù hợp [src_blld_c0098].\n"
        "Mức phạt 20% vượt quá giới hạn tối đa theo Luật Thương mại (Điều 301)."
    )
    st, out, _, _ = check_product_evidence_claims(
        "COMPLETE", llm, f"[{c_labor.chunk_id}] {c_labor.text}", q, [], evidence_chunks=[c_labor]
    )
    assert "Điều 98 Bộ luật Lao động 2019" in out
    assert "150%" in out
    assert "vượt quá giới hạn tối đa theo luật thương mại" not in out.casefold()
    assert st == "PARTIAL"
    assert "Luật Thương mại" in out


def test_f6_10_correct_loaded_statute_and_article_cleanly_preserved() -> None:
    c_statute = SourceChunk(
        "src_nd13_c0011", "src_nd13", "Nghị định 13/2023/NĐ-CP",
        "Điều 11. Sự đồng ý của chủ thể dữ liệu phải được thể hiện rõ ràng, cụ thể cho từng mục đích.", 11,
        provenance={"doc_type": "legal_doc"},
    )
    q = "Việc lấy đồng ý mặc định có đúng Điều 11 Nghị định 13/2023/NĐ-CP không?"
    llm = "Theo Điều 11 Nghị định 13/2023/NĐ-CP, sự đồng ý phải thể hiện rõ ràng cho từng mục đích [src_nd13_c0011]."
    st, out, bad_nums, bad_arts = check_product_evidence_claims(
        "COMPLETE", llm, f"[{c_statute.chunk_id}] {c_statute.text}", q, [], evidence_chunks=[c_statute]
    )
    assert st == "COMPLETE"
    assert not bad_nums and not bad_arts
    assert "Lưu ý phạm vi pháp lý" not in out
    assert "Điều 11 Nghị định 13/2023/NĐ-CP" in out


# ---------------------------------------------------------------------------
# FIX-01 + FIX-05: General RAG Preservation & Single Validated Answer Artifact
# ---------------------------------------------------------------------------


def test_f6_11_general_product_lookup_preserves_answer_without_false_banners() -> None:
    c_spec = SourceChunk(
        "src_spec_c0001", "src_spec", "API Gateway Spec",
        "Rate limit mặc định là 1.200 request/phút mỗi tenant, thời gian timeout upstream 30 giây.", 1,
    )
    q = "Rate limit mặc định và timeout upstream của API Gateway là bao nhiêu?"
    llm = "Rate limit mặc định là 1.200 request/phút mỗi tenant và upstream timeout là 30 giây [src_spec_c0001]."
    vr = verify_and_reconcile_answer(query=q, chunks=[c_spec], llm_answer=llm, status="COMPLETE")
    assert vr["applied"] is False
    assert vr["mode"] == "bypassed_general_or_lookup"
    st, out, bad_nums, bad_arts = check_product_evidence_claims(
        "COMPLETE", vr["final_answer"], f"[{c_spec.chunk_id}] {c_spec.text}", q, [], evidence_chunks=[c_spec]
    )
    assert st == "COMPLETE"
    assert not bad_nums and not bad_arts
    assert out == llm


def test_f6_12_single_validated_artifact_across_stream_final_and_persisted_with_reviewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", "on")
    monkeypatch.setenv("PRODUCT_REVIEWER", "on")

    ss = SourceStore(str(tmp_path / "sources"))
    rs = RunStore(str(tmp_path / "runs"))
    chunk_text = "Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc. Phải bàn giao công việc trước khi nghỉ."
    ss.import_text("HR Policy", chunk_text, provenance={"doc_type": "policy", "owner_user_id": "usr_1"})
    chunks = ss.chunks()
    cid = chunks[0].chunk_id
    sid = chunks[0].source_id

    q = (
        "Đơn này có đúng nội quy không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 03/12/2026\nTừ 07/12/2026 đến 11/12/2026 (5 ngày làm việc)\nBàn giao: chưa có"
    )

    class _StreamingPipelineFake(FakeProvider):
        supports_streaming = True

        async def generate(self, system: str, user: str, **kwargs: Any) -> ProviderResult:
            sys_u = system.upper()
            if "REVIEWER" in sys_u or "ĐỐI CHIẾU" in sys_u or "UNSUPPORTED" in system.lower():
                return ProviderResult(
                    text='{"checked":1,"unsupported":[{"claim":"Kiểm tra bổ sung","reason":"test reviewer annotation"}]}',
                    model=self.model,
                    usage=Usage(5, 5),
                )
            if "SYNTHESIZER" in sys_u:
                draft = (
                    "### Phân tích\n"
                    f"- Đơn gửi trước 03 ngày (03/12/2026 → 10/12/2026) → **đúng**. [{cid}]\n\n"
                    "### Kết luận\nĐơn đạt yêu cầu."
                )
                return ProviderResult(text=draft, model=self.model, usage=Usage(15, 20))
            if "WORKER" in sys_u or "VANILLA_RAG_ANSWERER" in sys_u:
                worker_payload = json.dumps(
                    {"status": "COMPLETE", "answer": f"Theo quy định phải nộp trước 05 ngày làm việc [{cid}].", "citations": [cid], "missing_information": []},
                    ensure_ascii=False,
                )
                return ProviderResult(text=worker_payload, model=self.model, usage=Usage(10, 10))
            return await super().generate(system, user, **kwargs)

    from app.research import pipeline as pl_mod
    pipe = ResearchPipeline(ss, rs)
    orig_get_provider = pl_mod.get_provider
    pl_mod.get_provider = lambda name=None: _StreamingPipelineFake()

    async def _collect() -> list[dict]:
        frames: list[dict] = []
        async for line in ndjson_run(lambda: pipe.run(q, condition="C", provider_name="fake", product_mode=True, source_ids=[sid])):
            frames.append(json.loads(line))
        return frames

    try:
        frames = asyncio.run(_collect())
    finally:
        pl_mod.get_provider = orig_get_provider

    ans_frames = [f["text"] for f in frames if f.get("type") == "answer"]
    done_run = next(f["run"] for f in frames if f.get("type") == "done")
    persisted = rs.get(done_run["run_id"])
    assert persisted is not None
    # Single Validated Answer Artifact: exactly one validated answer frame === done_run["answer"] === persisted["answer"]
    assert len(ans_frames) == 1
    assert ans_frames[0] == done_run["answer"] == persisted["answer"]
    # Zero unvalidated draft leakage across streamed frame
    assert "10/12/2026" not in ans_frames[0]
    assert "→ **đúng**" not in ans_frames[0]


def test_f6_13_acl_restricts_rule_and_approval_chunks_outside_allowed_sources() -> None:
    allowed = SourceChunk(
        "src_public_c0001", "src_public", "Public Policy",
        "Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc.", 1,
    )
    secret = SourceChunk(
        "src_secret_c0001", "src_secret", "Executive Override",
        "Mùa cao điểm (tháng 12) hạn chế nghỉ quá 02 ngày liên tiếp. Nghỉ từ 03 ngày phải được Tổng Giám đốc tối cao phê duyệt.", 1,
    )
    q = (
        "Đơn này có đúng quy định không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 03/12/2026\nTừ 07/12/2026 đến 11/12/2026 (5 ngày làm việc)"
    )
    llm = "Đơn đạt yêu cầu."
    vr = verify_and_reconcile_answer(
        query=q,
        chunks=[allowed, secret],
        llm_answer=llm,
        status="COMPLETE",
        allowed_source_ids={"src_public"},
    )
    out = vr["final_answer"]
    assert "Tổng Giám đốc tối cao" not in out
    assert "src_secret_c0001" not in out
    assert "src_public_c0001" in out
