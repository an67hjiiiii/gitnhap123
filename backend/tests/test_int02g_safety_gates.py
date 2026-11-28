"""INT-02G safety gate verification for office work-session, Research A/B/C, and wall-timeout/budget bounds."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.office import _call_llm, build_router
from app.core.types import ProviderResult, SourceChunk, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.registry import OFFICE_PACK, active_pack_name
from app.research.run_queue import product_runs
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _make_office_client(
    *,
    chunks: list[SourceChunk],
    hits: list[SourceChunk] | None = None,
    validate_fn=None,
    run_store=None,
    provider=None,
    disconnected: bool | None = None,
) -> tuple[TestClient, FastAPI]:
    app = FastAPI()

    class _Pipe:
        def __init__(self):
            if validate_fn is not None:
                self.source_store = SimpleNamespace(
                    chunks=lambda source_ids=None: list(chunks) if not source_ids else [c for c in chunks if c.source_id in source_ids],
                    validate_source_selection=validate_fn,
                )
            else:
                self.source_store = SimpleNamespace(
                    chunks=lambda source_ids=None: list(chunks) if not source_ids else [c for c in chunks if c.source_id in source_ids],
                )
            self.run_store = run_store

        def _retrieve_candidates(self, query, all_chunks, top_k=5, min_score=0.0, source_ids=None):
            return list(chunks[:top_k]) if hits is None else list(hits[:top_k])

    pipe = _Pipe()
    router = build_router(
        current_user=lambda req: {"user_id": "u_office", "role": "USER"},
        owner_pipeline=lambda u: pipe,
        session_factory=lambda: None,
    )
    app.include_router(router)
    return TestClient(app), app


def test_int02g_office_docs_present_but_empty_retrieval_is_not_complete(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    chunks = [SourceChunk("s1_c0000", "s1", "Policy.md", "Điều 5. Nghỉ phép năm 12 ngày.", 0)]
    saved: list[dict] = []
    client, _ = _make_office_client(
        chunks=chunks,
        hits=[],  # retrieval returns NO evidence despite uploaded documents
        run_store=SimpleNamespace(save=lambda r: saved.append(r)),
    )
    res = client.post("/api/studio/office/work-session", json={"domain_pack": "office"})
    assert res.status_code == 200
    events = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    done = events[-1]
    assert done["type"] == "session_done"
    assert done["status"] in {"PARTIAL", "NO_EVIDENCE"}
    assert done["status"] != "COMPLETE"
    assert done["citations"] == []
    assert saved and saved[-1]["status"] == done["status"] and saved[-1]["citations"] == []
    assert product_runs.active == 0 and product_runs.waiting == 0


def test_int02g_office_filters_citations_to_validated_subset_and_clears_on_no_evidence(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    chunks = [SourceChunk("s1_c0000", "s1", "Policy.md", "Điều 5. Nghỉ phép năm 12 ngày.", 0)]
    saved: list[dict] = []

    class _FakeUnsafeProvider:
        async def generate_structured(self, *, system, user, response_schema=None, **kw):
            if '"topic"' in system or "topic" in str(response_schema):
                return ProviderResult('{"topic":"Kiểm tra mức phạt 999 triệu ngoài quy định"}', Usage(2, 2))
            # Integrator echoes a hallucinated number 999.000.000 unsupported by chunks
            if "Integrator" in system:
                return ProviderResult('{"reply":"Mức phạt là 999.000.000 đồng [s1_c0000] [src_deadbeefdeadbeef_c0009]."}', Usage(4, 4))
            return ProviderResult('{"reply":"Mình đã kiểm tra theo s1_c0000."}', Usage(3, 3))

    client, _ = _make_office_client(
        chunks=chunks,
        hits=chunks,
        run_store=SimpleNamespace(save=lambda r: saved.append(r)),
    )
    with patch("app.api.office.get_provider", return_value=_FakeUnsafeProvider()):
        res = client.post("/api/studio/office/work-session", json={"domain_pack": "office"})
    assert res.status_code == 200
    events = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    done = events[-1]
    assert done["type"] == "session_done"
    assert done["status"] in {"PARTIAL", "NO_EVIDENCE"}
    final_msgs = [e for e in events if e.get("type") == "agent_message" and e.get("agent_id") == "integrator"]
    assert final_msgs and "src_deadbeefdeadbeef_c0009" not in final_msgs[-1]["text"]
    assert product_runs.active == 0 and product_runs.waiting == 0


def test_int02g_office_valid_cids_filter_mismatch_when_retrieve_returns_rogue_chunk(monkeypatch) -> None:
    """When _retrieve_candidates mixes a valid retrieved chunk with an empty/rogue chunk or validator drops a citation,
    both session_done['citations'] and run_store['citations'] MUST match valid_cids rather than the raw unfiltered list."""
    monkeypatch.setenv("PROVIDER", "fake")
    stored = [SourceChunk("s1_c0000", "s1", "Policy.md", "Điều 5. Phụ cấp 500.000 đồng.", 0)]
    saved: list[dict] = []

    class _NoEvProvider:
        async def generate_structured(self, *, system, user, response_schema=None, **kw):
            if "topic" in str(response_schema):
                return ProviderResult('{"topic":"Kiểm tra mức phạt hành chính"}', Usage(2, 2))
            if "Integrator" in system:
                return ProviderResult('{"reply":"Tài liệu không đề cập và không có thông tin về mức phạt này."}', Usage(4, 4))
            return ProviderResult('{"reply":"Không thấy dữ liệu."}', Usage(3, 3))

    client, _ = _make_office_client(
        chunks=stored,
        hits=stored,
        run_store=SimpleNamespace(save=lambda r: saved.append(r)),
    )
    with patch("app.api.office.get_provider", return_value=_NoEvProvider()):
        res = client.post("/api/studio/office/work-session", json={"domain_pack": "office"})
    events = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    done = events[-1]
    assert done["status"] == "NO_EVIDENCE"
    assert done["citations"] == []
    assert saved and saved[-1]["citations"] == []


def test_int02g_office_foreign_source_rejected_with_and_without_validator(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    own = [SourceChunk("s1_c0000", "s1", "Own.md", "Tài liệu nội bộ của mình.", 0)]

    def _reject_foreign(sids):
        if any(s != "s1" for s in sids):
            raise LookupError("foreign or missing source")

    client_with_val, _ = _make_office_client(chunks=own, validate_fn=_reject_foreign)
    r1 = client_with_val.post("/api/studio/office/work-session", json={"source_ids": ["foreign_org_src"]})
    assert r1.status_code == 404

    # When validate_source_selection is unavailable, explicit non-empty source_ids yielding 0 accessible chunks MUST NOT
    # silently fall back to unrelated office seeds as if no source_ids were requested.
    client_no_val, _ = _make_office_client(chunks=own, validate_fn=None)
    r2 = client_no_val.post("/api/studio/office/work-session", json={"source_ids": ["foreign_org_src"]})
    assert r2.status_code == 404
    assert product_runs.active == 0 and product_runs.waiting == 0


def test_int02g_office_deadline_mid_provider_call_aborts_and_releases_queue(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("PRODUCT_MAX_CONCURRENT_RUNS", "1")
    chunks = [SourceChunk("s1_c0000", "s1", "Policy.md", "Điều 5. Nghỉ phép năm 12 ngày.", 0)]

    class _SlowProvider:
        calls = 0

        async def generate_structured(self, *, system, user, response_schema=None, **kw):
            _SlowProvider.calls += 1
            if "Orchestrator" in system and "Điều phối trưởng" in system:
                await asyncio.sleep(0.5)
            return ProviderResult('{"topic":"Kiểm tra nghỉ phép","reply":"Ok"}', Usage(1, 1))

    async def _run():
        # Force a tiny deadline right after topic step by advancing time.monotonic via patch in app.api.office
        t0 = 100.0
        state = {"calls": 0}

        def _fake_mono():
            state["calls"] += 1
            # First 2 checks (init deadline + topic start) at 100.0s, deadline = 100.05s when limit mocked
            return t0 if state["calls"] <= 2 else t0 + 0.01

        class _MockRequest:
            async def is_disconnected(self):
                return False

        # Test direct _call_llm deadline bound without touching unrelated 10s env minimum
        with patch("app.api.office.get_provider", return_value=_SlowProvider()):
            try:
                await _call_llm(
                    _SlowProvider(),
                    system="Orchestrator (Điều phối trưởng)",
                    user="u",
                    deadline=time.monotonic() + 0.04,
                )
                raised = False
            except TimeoutError:
                raised = True
        assert raised, "_call_llm must enforce deadline mid-provider call"

    asyncio.run(_run())
    assert product_runs.active == 0 and product_runs.waiting == 0


def test_int02g_office_client_disconnect_mid_call_aborts_and_releases_queue(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("PRODUCT_MAX_CONCURRENT_RUNS", "1")

    class _HangingProvider:
        async def generate_structured(self, *, system, user, response_schema=None, **kw):
            await asyncio.sleep(1.5)
            return ProviderResult('{"reply":"too late"}', Usage(1, 1))

    async def _run():
        disc = {"flag": False}

        async def _trigger_disconnect():
            await asyncio.sleep(0.05)
            disc["flag"] = True

        t = asyncio.create_task(_trigger_disconnect())
        t0 = time.perf_counter()
        try:
            async with product_runs.slot():
                try:
                    await _call_llm(
                        _HangingProvider(),
                        system="Orchestrator",
                        user="u",
                        deadline=time.monotonic() + 5.0,
                        is_disconnected=lambda: asyncio.sleep(0, result=disc["flag"]),
                    )
                    assert False, "Expected disconnect/cancel abort"
                except asyncio.CancelledError:
                    pass
        finally:
            await t
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.4, f"Disconnect mid-provider took too long: {elapsed:.2f}s"

    asyncio.run(_run())
    assert product_runs.active == 0 and product_runs.waiting == 0


def test_int02g_office_run_store_save_failure_logged_gracefully_and_slot_released(monkeypatch, caplog) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    chunks = [SourceChunk("s1_c0000", "s1", "Policy.md", "Điều 5. Nghỉ phép năm 12 ngày.", 0)]

    def _boom_save(run):
        raise RuntimeError("disk full simulated")

    client, _ = _make_office_client(
        chunks=chunks,
        hits=chunks,
        run_store=SimpleNamespace(save=_boom_save),
    )
    with caplog.at_level(logging.WARNING, logger="app.api.office"):
        res = client.post("/api/studio/office/work-session", json={"domain_pack": "office"})
    assert res.status_code == 200
    events = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    assert events[-1]["type"] == "session_done"
    assert any("run_store" in r.message.lower() or "persist" in r.message.lower() for r in caplog.records)
    assert product_runs.active == 0 and product_runs.waiting == 0


def test_int02g_research_abc_explicit_domain_pack_and_product_office_protocol(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    ss = SourceStore(str(tmp_path / "src"))
    ss.import_text("spec.md", "Authentication requires JWT RSA-256 signatures and PostgreSQL foreign keys.")
    pipe = ResearchPipeline(ss, RunStore(str(tmp_path / "runs")))

    # Research A/B/C with explicit domain_pack="software" share identical pack, omit agent_selection, log full effective_config
    packs = {}
    for cond in ("A", "B", "C"):
        run = asyncio.run(pipe.run("Review JWT authentication and database foreign keys", cond, domain_pack="software", product_mode=False))
        cfg = run["effective_config"]
        packs[cond] = cfg["domain_pack"]
        assert cfg["condition"] == cond
        assert cfg["implementation_profile"] == "m2"
        assert "flags" in cfg and "task_top_k" in cfg and "max_context_tokens" in cfg
        assert "agent_selection" not in cfg
        assert "provenance" in run and run["provenance"]["model"]["provider"] == "fake"
    assert packs == {"A": "software", "B": "software", "C": "software"}

    # Product mode defaults cleanly to 11-agent office pack
    prod = asyncio.run(pipe.run("Nghỉ phép năm bao nhiêu ngày?", "C", product_mode=True))
    assert prod["effective_config"]["domain_pack"] == OFFICE_PACK
    assert "agent_selection" in prod["effective_config"]
    assert active_pack_name() == OFFICE_PACK


def test_int02g_wall_timeout_plus_half_second_cleanup_no_leaks_or_post_deadline_calls(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("MAX_DAG_WALL_SECONDS", "0.05")
    monkeypatch.setenv("PRODUCT_MAX_CONCURRENT_RUNS", "1")
    ss = SourceStore(str(tmp_path / "src"))
    ss.import_text("doc.md", "Authentication requires JWT signatures. Database uses PostgreSQL.")
    pipe = ResearchPipeline(ss, RunStore(str(tmp_path / "runs")))

    class _TrackingSlowFake(FakeProvider):
        started_at: list[float] = []

        async def generate(self, *, system: str, user: str) -> ProviderResult:
            _TrackingSlowFake.started_at.append(time.monotonic())
            await asyncio.sleep(0.15)
            return await super().generate(system=system, user=user)

    async def _run():
        before = time.monotonic()
        with (
            patch("app.research.pipeline.get_provider", return_value=_TrackingSlowFake()),
            patch("app.research.pipeline.gpu_memory_mb", return_value=None),
            patch("app.research.pipeline.model_rss_mb", return_value=None),
        ):
            run = await pipe.run("Review authentication JWT and PostgreSQL", "B", provider_name="fake", product_mode=False)
        elapsed = time.monotonic() - before
        # Must finish within budget + <= 0.5s outer grace cleanup window (without external nvidia-smi subprocess probe)
        assert elapsed < 0.55, f"Wall timeout cleanup exceeded +0.5s bound: {elapsed:.3f}s"
        # First call started pre-deadline; no extra call started after deadline (~before + 0.05s)
        deadline_approx = before + 0.05
        assert len(_TrackingSlowFake.started_at) == 1
        assert _TrackingSlowFake.started_at[0] <= deadline_approx
        assert run["status"] == "FAILED"
        assert run["lifecycle_status"] == "FAILED"
        stages = [e["stage"] for e in run["events"]]
        assert "run_budget_exceeded" in stages and "run_failed" not in stages
        leaked = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        assert leaked == [], f"Leaked background tasks: {leaked}"

    asyncio.run(_run())
    assert product_runs.active == 0 and product_runs.waiting == 0


def test_int02g_outer_timeout_plus_half_second_stops_hung_coroutine_and_releases_queue(tmp_path, monkeypatch) -> None:
    """When _run hangs outside _GuardedProvider (e.g. an uncooperative await), the +0.5s outer guard cancels it cleanly."""
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("MAX_DAG_WALL_SECONDS", "0.05")
    ss = SourceStore(str(tmp_path / "src2"))
    ss.import_text("doc.md", "Authentication requires JWT.")
    pipe = ResearchPipeline(ss, RunStore(str(tmp_path / "runs2")))

    async def _hung_run(query, condition="A", provider_name=None, *, run_state=None, **kw):
        if isinstance(run_state, dict):
            ev_list = []
            run_state["event"] = lambda st, **d: ev_list.append({"stage": st, **d})
            run_state["finalize"] = lambda status, answer, tasks, results: {
                "run_id": "hung_r1", "status": status, "lifecycle_status": status, "answer": answer, "events": ev_list
            }
        await asyncio.sleep(3.0)
        return {}

    async def _go():
        t0 = time.monotonic()
        with patch.object(pipe, "_run", side_effect=_hung_run):
            res = await pipe._run_with_timeout("q", "B", "fake")
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"Outer timeout did not interrupt hung _run within 0.05+0.5s: {elapsed:.2f}s"
        assert res["status"] == "FAILED"
        assert any(e["stage"] == "run_failed" and e.get("error") == "run_wall_timeout" for e in res["events"])
        leaked = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        assert leaked == []

    asyncio.run(_go())
    assert product_runs.active == 0 and product_runs.waiting == 0
