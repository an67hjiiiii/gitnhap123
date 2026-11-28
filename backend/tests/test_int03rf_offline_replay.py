"""INT-03RF Test-First RED/GREEN Offline Replay Suite.

Uses raw task outputs & failure modes captured from INT-03R (R-08A, R-02, G-01)
without calling Ollama (ZERO POST) or relaxing assertions.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.answer_checks import IMG_MARK
from app.core.citations import resolve_citations
from app.core.types import Concern, Obligation, ObligationConcernExtraction, ProviderResult, SourceChunk, Task, TaskPlan, Usage
from app.providers.fake import FakeProvider
from app.providers import ollama as ollama_mod
from app.research.knowledge_source import GENERAL, choose_source, doc_bound
from app.research.pipeline import OFFICE_PACK, ResearchPipeline, classify_run_error
from app.research.plan_verification import verify_task_plan
from app.research.progress import ndjson_run
from app.research.registry import use_pack
from app.research.run_queue import product_runs
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


# ---------------------------------------------------------------------------
# 1. Knowledge Policy (R-02 doc_bound, no general fallback, keep Quick/General)
# ---------------------------------------------------------------------------


def test_int03rf_01_r02_and_policy_queries_doc_bound_while_general_remains_unbound() -> None:
    q_r02 = (
        "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        f"{IMG_MARK}\nĐƠN XIN NGHỈ PHÉP\nNgày gửi đơn: 03/12/2026\nTừ 07/12/2026 đến 11/12/2026\nNgười nhận bàn giao: chưa có"
    )
    assert doc_bound(q_r02) is True
    assert doc_bound("Kiểm tra bảng chấm công này có đúng quy định công ty không?") is True
    # General / concept queries MUST remain unbound
    assert doc_bound("Thủ đô của Úc là thành phố nào?") is False
    assert doc_bound("Thông tư là gì?") is False
    assert doc_bound("Làm sao để ra quyết định mua máy chủ?") is False


def test_int03rf_02_r02_missing_internal_policy_does_not_fallback_to_general_hallucination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", "on")

    ss = SourceStore(tmp_path / "src")
    # PRIVATE scope has BLLD only (missing HA_01/HA_02 internal rules!)
    ss.import_text(
        "LD_Bo_luat_Lao_dong_2019.pdf",
        "Điều 113. Nghỉ hằng năm: Người lao động làm việc đủ 12 tháng được nghỉ 12 ngày.",
    )
    rs = RunStore(tmp_path / "runs")
    pipe = ResearchPipeline(ss, rs)

    general_called = False

    class ReplayNoEvidenceWorker(FakeProvider):
        async def generate_grounded(self, *, system: str, user: str, evidence_ids: list[str], **kwargs: Any):
            return ProviderResult(
                text=json.dumps(
                    {
                        "status": "NO_EVIDENCE",
                        "answer": "Tài liệu hiện có không chứa quy định nội bộ phòng Kinh doanh về đơn xin nghỉ phép.",
                        "citations": [],
                        "missing_information": ["Nội quy lao động HA_01 / Sổ tay phòng Kinh doanh HA_02"],
                    },
                    ensure_ascii=False,
                ),
                model=self.model,
                usage=Usage(20, 20),
            )

        async def generate(self, *, system: str, user: str, **kwargs: Any) -> ProviderResult:
            nonlocal general_called
            if "GENERAL_KNOWLEDGE_ANSWERER" in system:
                general_called = True
                return ProviderResult(
                    text='{"answer":"1. Ngày vào làm không khớp ngày hiện tại (2024).\\n2. 03/12/2026 nằm trong khoảng 07/12-11/12."}',
                    model=self.model,
                    usage=Usage(10, 10),
                )
            return await super().generate(system=system, user=user, **kwargs)

    q_r02 = (
        "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        f"{IMG_MARK}\nĐƠN XIN NGHỈ PHÉP\nNgày vào làm: 15/06/2025\n"
        "Xin nghỉ phép năm từ thứ Hai 07/12/2026 đến thứ Sáu 11/12/2026 (5 ngày làm việc)\n"
        "Ngày gửi đơn: thứ Năm 03/12/2026\nNgười nhận bàn giao khách hàng: chưa có"
    )
    with use_pack(OFFICE_PACK), patch("app.research.pipeline.get_provider", return_value=ReplayNoEvidenceWorker()):
        run = asyncio.run(pipe.run(q_r02, "C", provider_name="fake", product_mode=True))

    assert run["effective_config"]["knowledge_source"]["document_bound"] is True
    assert general_called is False
    assert "ngày hiện tại (2024)" not in run["answer"].casefold()
    assert "nằm trong khoảng" not in run["answer"].casefold()


def test_int03rf_03_general_knowledge_still_works_for_unbound_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PROVIDER", "fake")
    ss = SourceStore(tmp_path / "src")
    ss.import_text("HA_07.docx", "Hợp đồng cung cấp phần mềm HA-Edu.")
    rs = RunStore(tmp_path / "runs")
    pipe = ResearchPipeline(ss, rs)

    with use_pack(OFFICE_PACK), patch("app.research.pipeline.get_provider", return_value=FakeProvider()):
        run = asyncio.run(pipe.run("Thủ đô của Úc là thành phố nào?", "C", provider_name="fake", product_mode=True))

    assert run["effective_config"]["knowledge_source"]["document_bound"] is False
    assert run["task_results"][0]["source"] == GENERAL


# ---------------------------------------------------------------------------
# 2. Obligation & Plan Coverage against Original Multi-Part Query (G-01)
# ---------------------------------------------------------------------------


def test_int03rf_04_plan_verification_catches_missing_conjunction_approval_clause() -> None:
    q_g01 = (
        "Trường đại học Bách Khoa Miền Trung là trường công lập muốn mua gói HA-Edu cho 4.000 sinh viên "
        "và ký hợp đồng 1 năm (không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm "
        "phí triển khai là bao nhiêu và ai phê duyệt mức chiết khấu này?"
    )
    # Exact INT-03R capture: extractor omitted "ai phê duyệt mức chiết khấu này"
    incomplete_ext = ObligationConcernExtraction(
        obligations=[
            Obligation("O1", "calculate total annual cost including implementation fee for 4000 students for HA-Edu package", True)
        ],
        concerns=[],
    )
    bad_plan = TaskPlan(
        request=q_g01,
        obligations=incomplete_ext.obligations,
        concerns=[],
        tasks=[
            Task(
                task_id="t1",
                goal="calculate total annual cost including implementation fee for 4000 students for HA-Edu package",
                domain="analyst",
                depends_on=[],
                evidence_needs=["HA-Edu package annual cost"],
                covers_obligations=["O1"],
                covers_concerns=[],
            )
        ],
    )
    rep = verify_task_plan(bad_plan)
    assert rep.valid is False
    assert any("request" in err.lower() or "approval" in err.lower() or "phê duyệt" in err.lower() for err in rep.errors)

    # Supplementing obligations preserves both calculation & approval obligations
    from app.research.obligation_concern_extraction import supplement_missing_request_obligations
    fixed_ext = supplement_missing_request_obligations(q_g01, incomplete_ext)
    assert len(fixed_ext.obligations) >= 2
    assert any("phê duyệt" in ob.description.casefold() or "approv" in ob.description.casefold() for ob in fixed_ext.obligations)


def test_int03rf_05_multi_part_conjunction_coverage_bilingual() -> None:
    q_en = "Calculate total first-year cost for 4000 seats and identify who approves the public university discount?"
    ext = ObligationConcernExtraction(obligations=[Obligation("O1", "Calculate total first-year cost for 4000 seats", True)], concerns=[])
    p = TaskPlan(
        request=q_en,
        obligations=ext.obligations,
        concerns=[],
        tasks=[Task("t1", "Calculate total first-year cost for 4000 seats", "analyst", [], ["pricing table"], ["O1"], [])],
    )
    assert verify_task_plan(p).valid is False
    from app.research.obligation_concern_extraction import supplement_missing_request_obligations
    sup = supplement_missing_request_obligations(q_en, ext)
    assert len(sup.obligations) >= 2


# ---------------------------------------------------------------------------
# 3. Verified Output Gate across ALL Pipeline Exit Paths & Proxy429 vs Prov429
# ---------------------------------------------------------------------------


def test_int03rf_06_classify_proxy_429_vs_provider_429() -> None:
    req = httpx.Request("POST", "http://127.0.0.1:11439/api/chat")
    proxy_resp = httpx.Response(429, request=req, json={"error": "HARD_BUDGET_EXCEEDED:gen_used"})
    prov_resp = httpx.Response(429, request=req, json={"error": "rate limit exceeded, try again later"})

    cat_px, code_px = classify_run_error(httpx.HTTPStatusError("429", request=req, response=proxy_resp))
    cat_pr, code_pr = classify_run_error(httpx.HTTPStatusError("429", request=req, response=prov_resp))
    assert cat_px == "proxy_budget_exceeded" and code_px == 429
    assert cat_pr == "provider_rate_limit" and code_pr == 429


def test_int03rf_07_g01_proxy429_run_failed_gate_retracts_speculative_worker_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PROVIDER", "ollama")
    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", "on")
    monkeypatch.setenv("OLLAMA_CONNECT_RETRIES", "0")

    ss = SourceStore(tmp_path / "src")
    ss.import_text(
        "HA_07_Hop_dong_HA-Edu.docx",
        "Hợp đồng cung cấp phần mềm HA-Edu. Chiết khấu trường công lập 12% do Ban Giám hiệu phê duyệt.",
    )
    rs = RunStore(tmp_path / "runs")
    pipe = ResearchPipeline(ss, rs)

    q_g01 = (
        "Trường đại học Bách Khoa Miền Trung là trường công lập muốn mua gói HA-Edu cho 4.000 sinh viên "
        "và ký hợp đồng 1 năm (không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm "
        "phí triển khai là bao nhiêu và ai phê duyệt mức chiết khấu này?"
    )

    call_n = 0
    req = httpx.Request("POST", "http://127.0.0.1:11439/api/chat")

    class ReplayG01Proxy429Client:
        def stream(self, method, url, **kw):
            resp = httpx.Response(429, request=req, json={"error": "HARD_BUDGET_EXCEEDED:gen_used"})

            class _StreamCM:
                async def __aenter__(self):
                    return resp

                async def __aexit__(self, *args):
                    return False

            return _StreamCM()

        async def post(self, url, **kw):
            nonlocal call_n
            call_n += 1
            payload = kw.get("json") or {}
            msgs = payload.get("messages") or []
            sys_msg = (msgs[0].get("content") or "") if msgs else ""
            if "OBLIGATION_CONCERN_EXTRACTOR" in sys_msg:
                txt = json.dumps({
                    "obligations": [
                        {"obligation_id": "O1", "description": "calculate total annual cost for 4000 students", "required": True},
                        {"obligation_id": "O2", "description": "identify who approves the discount", "required": True},
                    ],
                    "concerns": [],
                })
            elif "TASK_PLAN_BUILDER" in sys_msg:
                txt = json.dumps({
                    "tasks": [
                        {
                            "task_id": "t1",
                            "goal": "calculate total annual cost for 4000 students",
                            "domain": "analyst",
                            "depends_on": [],
                            "evidence_needs": ["HA-Edu price"],
                            "covers_obligations": ["O1"],
                            "covers_concerns": [],
                        },
                        {
                            "task_id": "t2",
                            "goal": "identify who approves the discount",
                            "domain": "business",
                            "depends_on": ["t1"],
                            "evidence_needs": ["discount approver"],
                            "covers_obligations": ["O2"],
                            "covers_concerns": [],
                        },
                    ]
                })
            elif "task_id=t1" in str(msgs[-1].get("content", "")) or "4000" in str(msgs[-1].get("content", "")):
                if call_n <= 3:
                    # Exact raw unverified numbers emitted by INT-03R t1 worker
                    txt = json.dumps({
                        "status": "COMPLETE",
                        "answer": "Tổng chi phí năm đầu cho 4000 sinh viên: **270.400.000**. Phí triển khai: 50.000.000 đồng. Tổng giá trị năm đầu: 252.800.000 đồng.",
                        "citations": [],
                        "missing_information": [],
                    }, ensure_ascii=False)
                else:
                    return httpx.Response(429, request=req, json={"error": "HARD_BUDGET_EXCEEDED:gen_used"})
            else:
                return httpx.Response(429, request=req, json={"error": "HARD_BUDGET_EXCEEDED:gen_used"})
            return httpx.Response(200, request=req, json={"message": {"content": txt}, "prompt_eval_count": 50, "eval_count": 20})

    monkeypatch.setattr(ollama_mod, "_async_client", lambda *a, **k: ReplayG01Proxy429Client())

    events_seen: list[dict] = []

    async def _collect():
        async for raw in ndjson_run(lambda: pipe.run(q_g01, "C", provider_name="ollama", product_mode=True)):
            events_seen.append(json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw))

    with use_pack(OFFICE_PACK):
        asyncio.run(_collect())

    done = next(e for e in events_seen if e.get("type") == "done")
    run = done["run"]
    assert run["status"] == "FAILED"
    assert run["lifecycle_status"] == "FAILED"
    assert "270.400.000" not in run["answer"]
    assert "252.800.000" not in run["answer"]
    persisted = rs.get(run["run_id"])
    assert persisted is not None and persisted["answer"] == run["answer"]
    assert "270.400.000" not in persisted["answer"]
    failed_ev = next(e for e in run["events"] if e.get("stage") == "run_failed")
    assert failed_ev["error_category"] == "proxy_budget_exceeded"


# ---------------------------------------------------------------------------
# 4. Citation & Grounding Consistency + Queue Counter Release
# ---------------------------------------------------------------------------


def test_int03rf_08_unrelated_decree_not_cited_and_inline_citations_match_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A) Unrelated PDPA chunk MUST NOT survive grounded citation check for contract 30% / 5M summary
    c_nd13 = SourceChunk(
        "src_fe6a508650e0d0a8_c0013",
        "src_fe6a508650e0d0a8",
        "PL_Nghi_dinh_13-2023-ND-CP_Bao_ve_du_lieu_ca_nhan.pdf",
        "Điều 13. Xử lý dữ liệu cá nhân trong trường hợp không cần sự đồng ý của chủ thể dữ liệu.",
        13,
        provenance={"doc_type": "legal_doc"},
    )
    ans_r08a = "Bên A vi phạm chịu phạt 30% tổng giá trị hợp đồng. Tổng trách nhiệm bồi thường của Bên B tối đa 5.000.000 đồng."
    valid, _ = resolve_citations(["src_fe6a508650e0d0a8_c0013"], [c_nd13], ans_r08a, allow_grounded_fallback=True)
    assert "src_fe6a508650e0d0a8_c0013" not in valid

    # B) Inline citation added by verified_reasoning MUST be reflected in run["citations"]
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", "on")

    ss = SourceStore(tmp_path / "src")
    imported = ss.import_text(
        "HA_01_Noi_quy.md",
        "Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc và bàn giao cho người trực thay.",
    )
    rs = RunStore(tmp_path / "runs")
    pipe = ResearchPipeline(ss, rs)
    q = (
        "Đơn này có đúng nội quy không?\n\n"
        f"{IMG_MARK}\nĐƠN XIN NGHỈ PHÉP\nTừ 07/12/2026 đến 11/12/2026 (5 ngày)\n"
        "Ngày gửi đơn: 03/12/2026\nBàn giao: chưa có"
    )
    with use_pack(OFFICE_PACK), patch("app.research.pipeline.get_provider", return_value=FakeProvider()):
        run = asyncio.run(pipe.run(q, "C", provider_name="fake", product_mode=True))

    import re
    inline_cids = set(re.findall(r"src_[0-9a-f]+_c\d{4}", run["answer"]))
    assert inline_cids <= set(run["citations"])


def test_int03rf_09_queue_slots_released_after_completion_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert product_runs.active == 0 and product_runs.waiting == 0
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PROVIDER", "fake")
    ss = SourceStore(tmp_path / "src")
    ss.import_text("doc.md", "Nội quy công ty.")
    pipe = ResearchPipeline(ss, RunStore(tmp_path / "runs"))

    async def _run_queued():
        async with product_runs.slot():
            return await pipe.run("Tóm tắt nội quy", "C", provider_name="fake", product_mode=True)

    run = asyncio.run(_run_queued())
    assert run["status"] in {"COMPLETE", "PARTIAL"}
    assert product_runs.active == 0 and product_runs.waiting == 0

    class _FailingProvider(FakeProvider):
        async def generate(self, system: str, user: str, **kwargs):
            raise RuntimeError("simulated queue failure")

    async def _run_failed_queued():
        async with product_runs.slot():
            with patch("app.research.pipeline.get_provider", return_value=_FailingProvider()):
                return await pipe.run("Tóm tắt nội quy", "C", provider_name="fake", product_mode=True)

    failed_run = asyncio.run(_run_failed_queued())
    assert failed_run["status"] in {"FAILED", "PARTIAL"}
    assert product_runs.active == 0 and product_runs.waiting == 0
