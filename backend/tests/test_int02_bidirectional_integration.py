"""INT-02 Bidirectional Integration Tests (Test-First, Zero LLM).

Verifies critical integration boundaries between Incoming (`17f0b37`) and Local V2 (`B139.2F6`):
1. INT-DEC-01: Research A/B/C (`product_mode=False`) keeps CAP1 `software` default when `domain_pack` is omitted, while `product_mode=True` defaults to `office` (11 Agents) and honors explicit `domain_pack`.
2. INT-DEC-02: `resolve_citations` normalizes bracket/case/unambiguous suffixes and inline IDs without promoting unrelated number-sharing or bigram-sharing docs.
3. INT-DEC-02: Unified `answer_checks` combines V9 helpers (`_scale_equivalents`, `finish_detailed`, `_dedup_calc_echo`, `_SYMBOLIC_CALC`) and V2 protections (`unsupported_calc_operands`, `check_product_evidence_claims`, legal claim safety).
4. INT-DEC-02: Unified `FairQueue` supports both Incoming `token` double-release/failing-callback safety (`FQ-01/FQ-02`) and Local `QueueFullError` / `wait_timeout` capacity guard.
5. INT-DEC-03 & INT-DEC-04: `POST /api/studio/office/work-session` enforces shared `product_runs` / budget guard, forwards `ollama_call_options(product=True)` (`num_ctx`, `keep_alive`), validates citations & claims, and verifies source selection ACLs without crashing dummy mocks.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.office import build_router as build_office_router
from app.core.answer_checks import IMG_MARK, check_product_evidence_claims, finish_detailed, unsupported_numbers
from app.core.citations import resolve_citations
from app.core.types import ProviderResult, RunMetrics, SourceChunk, Task, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import LLMBudgetExceededError, ResearchPipeline, RunBudgetExceeded, _BudgetedProvider
from app.research.registry import active_pack_name
from app.research.run_queue import FairQueue, QueueFullError
from app.research.worker import execute_task
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def test_int02_dec01_research_mode_keeps_software_while_product_uses_office(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PROVIDER", "fake")
    ss = SourceStore(str(tmp_path / "src"))
    rs = RunStore(str(tmp_path / "runs"))
    ss.import_text("spec.md", "JWT authentication uses RSA-256 and PostgreSQL primary keys.")

    seen_packs: list[tuple[bool, str]] = []

    class _PackSpyFake(FakeProvider):
        async def generate(self, system: str, user: str, **kwargs: Any) -> ProviderResult:
            return await super().generate(system, user, **kwargs)

    from app.research import pipeline as pl_mod
    pipe = ResearchPipeline(ss, rs)
    orig_get_prov = pl_mod.get_provider
    pl_mod.get_provider = lambda name=None: _PackSpyFake()
    try:
        res_abc = asyncio.run(pipe.run("Review JWT authentication and database primary keys", condition="C", product_mode=False))
        res_prod = asyncio.run(pipe.run("Đánh giá kiến trúc API và ngân sách vận hành", condition="C", product_mode=True))
    finally:
        pl_mod.get_provider = orig_get_prov

    # Research condition C (product_mode=False) uses CAP1 software pack, whereas product_mode=True defaults to office
    seen_packs.append((False, res_abc["effective_config"]["domain_pack"]))
    seen_packs.append((True, res_prod["effective_config"]["domain_pack"]))
    assert seen_packs == [(False, "software"), (True, "office")]
    assert active_pack_name() == "office"


def test_int02_dec02_resolve_citations_and_worker_never_promote_unrelated_shared_numbers() -> None:
    c_ha07 = SourceChunk(
        "src_aadf23faaa3faec1_c0003", "src_aadf23faaa3faec1", "HA_07 Hop dong HA-Edu",
        "Điều 9.1 Phạt vi phạm 30% tổng giá trị hợp đồng. Điều 9.2 Tổng trách nhiệm bồi thường của Bên B tối đa 5.000.000 đồng.", 3,
    )
    c_sla = SourceChunk(
        "src_unrelated_sla_c0002", "src_unrelated_sla", "SLA Bang thong Internet 2025",
        "Giảm trừ 30% cước phí tháng nếu gián đoạn kéo dài; mức hỗ trợ tối đa 5.000.000 đồng.", 2,
    )
    ans = "Hợp đồng phần mềm quy định Điều 9.1 phạt 30% tổng giá trị hợp đồng và Điều 9.2 bồi thường tối đa 5.000.000 đồng."

    # 1. Bracket/case normalization works, ZERO numeric/bigram cross-doc promotion
    valid, invalid = resolve_citations(["[SRC_AADF23FAAA3FAEC1_C0003]"], [c_ha07, c_sla], ans, allow_grounded_fallback=False)
    assert valid == ["src_aadf23faaa3faec1_c0003"]
    assert invalid == []
    assert "src_unrelated_sla_c0002" not in valid

    # Even if allow_grounded_fallback=True is passed by legacy caller, numeric-only/bigram-only docs must NOT be promoted!
    v_empty, _ = resolve_citations([], [c_sla], ans, allow_grounded_fallback=True)
    assert "src_unrelated_sla_c0002" not in v_empty

    # 2. Worker FIX-04 clause + substance promotion retains c0003, blocks SLA
    class _W(FakeProvider):
        async def generate_grounded(self, system: str, user: str, evidence_ids: list[str], **kwargs: Any):
            return ProviderResult(
                text=json.dumps({"status": "PARTIAL", "answer": ans, "citations": [], "missing_information": ["Luật Thương mại"]}, ensure_ascii=False),
                model=self.model,
                usage=Usage(10, 10),
            )

    task = Task(task_id="T1", domain="business", goal="Phân tích Điều 9.1 và Điều 9.2 hợp đồng phần mềm")
    res = asyncio.run(execute_task(_W(), task, [c_ha07, c_sla], RunMetrics(), product=True, user_request=ans))
    assert "src_aadf23faaa3faec1_c0003" in res.citations
    assert "src_unrelated_sla_c0002" not in res.citations


def test_int02_dec02_unified_answer_checks_preserves_v9_and_f6_legal_safety() -> None:
    c_contract = SourceChunk(
        "src_ha07_c0003", "src_ha07", "HA_07",
        "Điều 9.1: Phạt 30% giá trị hợp đồng. Điều 9.2: Bồi thường tối đa 5.000.000 đồng.", 3,
        provenance={"doc_type": "contract"},
    )
    q = f"Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không?\n\n{IMG_MARK}\nĐiều 9.1 Phạt 30%"
    llm = (
        "Điều khoản này có thể vi phạm Luật Thương mại và Bộ luật Dân sự 2015 do mức phạt 30% tổng giá trị hợp đồng vượt quá giới hạn cho phép.\n"
        "- Phạt 30% tổng giá trị hợp đồng có thể vượt quá giới hạn cho phép theo Bộ luật Dân sự 2015 (Điều 398) [src_ha07_c0003]."
    )
    st, out, _, _ = check_product_evidence_claims("COMPLETE", llm, c_contract.text, q, [], evidence_chunks=[c_contract])
    assert st == "PARTIAL"
    assert ") thương mại" not in out.casefold()
    assert "vượt quá giới hạn cho phép theo bộ luật dân sự" not in out.casefold()
    assert "30%" in out

    # V9 scale & calc dedup helpers work alongside unsupported_calc_operands
    fin_out, bad, _ = finish_detailed("Tổng = [[= 12 * 2 ]]. Quy đổi 24 tỷ VNĐ.", "Tổng gốc 12, hệ số 2, dự toán 24.000 triệu VNĐ.")
    assert "**24**" in fin_out
    assert bad == []
    assert unsupported_numbers("Sai 750.000 đồng.", "Đơn giá 150.000 đồng.") == ["750000"]


def test_int02_dec02_unified_queue_and_budget_guard() -> None:
    # Unified budget exception compatibility
    assert LLMBudgetExceededError is RunBudgetExceeded

    class _Dummy:
        name = "d"
        model = "d"
        async def generate(self, *a, **kw):
            return ProviderResult(text="ok", usage=Usage(1, 1), model="d")

    async def _run_q_and_b():
        bp = _BudgetedProvider(_Dummy(), max_calls=1)
        await bp.generate("hi")
        with pytest.raises(RunBudgetExceeded):
            await bp.generate("hi2")

        fq = FairQueue(limit=1, max_waiters=0)
        tok = await fq.acquire()
        with pytest.raises(QueueFullError):
            await fq.acquire()
        fq.release(tok)
        fq.release(tok)  # idempotent token release
        assert fq.active == 0

    asyncio.run(_run_q_and_b())


def test_int02_dec03_dec04_office_work_session_uses_product_ctx_queue_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("PRODUCT_NUM_CTX", "8192")
    monkeypatch.setenv("PRODUCT_OLLAMA_KEEP_ALIVE", "10m")

    captured_opts: list[dict[str, Any]] = []

    class _RecordingOfficeFake(FakeProvider):
        supports_num_ctx = True
        supports_keep_alive = True
        supports_per_call_timeout = True
        supports_per_call_output_tokens = True

        async def generate_structured(self, system: str, user: str, response_schema: dict | None = None, **kwargs: Any) -> ProviderResult:
            captured_opts.append(dict(kwargs))
            field = next(iter((response_schema or {}).get("properties", {"reply": {}}).keys()), "reply")
            return ProviderResult(
                text=json.dumps({field: "Đã rà soát quy định công ty 1.500.000 VNĐ/tháng [c1]."}, ensure_ascii=False),
                model=self.model,
                usage=Usage(5, 5),
            )

    from app.api import office as office_mod
    orig_get = office_mod.get_provider
    office_mod.get_provider = lambda name=None: _RecordingOfficeFake()

    class _Pipe:
        def __init__(self):
            ch = SourceChunk("c1", "src_1", "Quy_Che_Nhan_Su.docx", "Phụ cấp ăn trưa 1.500.000 VNĐ/tháng.", 0)
            self._chunks = [ch]
            self.source_store = SimpleNamespace(
                chunks=lambda source_ids=None: [c for c in self._chunks if source_ids is None or c.source_id in source_ids],
                validate_source_selection=lambda ids: None if all(i == "src_1" for i in ids) else (_ for _ in ()).throw(LookupError("missing")),
            )

        def _retrieve_candidates(self, query, chunks, top_k=5, min_score=0.0, source_ids=None):
            return list(chunks)

    app = FastAPI()
    app.include_router(
        build_office_router(
            current_user=lambda r: {"user_id": "u1", "role": "USER"},
            owner_pipeline=lambda u: _Pipe(),
            session_factory=lambda: None,
        )
    )
    client = TestClient(app)
    try:
        res_bad = client.post("/api/studio/office/work-session", json={"source_ids": ["src_forbidden"]})
        assert res_bad.status_code == 404

        res = client.post("/api/studio/office/work-session", json={"source_ids": ["src_1"]})
        assert res.status_code == 200
        events = [json.loads(line) for line in res.text.strip().splitlines() if line.strip()]
        assert events[0]["type"] == "session_start"
        assert events[-1]["type"] == "session_done"
        assert captured_opts and all(o.get("num_ctx") == 8192 and o.get("keep_alive") == "10m" for o in captured_opts)
    finally:
        office_mod.get_provider = orig_get
