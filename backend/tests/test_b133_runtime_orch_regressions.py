"""Batch 133 Runtime & Orchestration regression tests (Phase 1B):
FQ-01, FQ-02, AI-GUARD-01/MA-01, OBS-W3-P82-01, MA-02, MA-03, MA-04,
WORK_PACK_ROUTING, NEW-04, NEW-05.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from app.core.types import ProviderResult, RunMetrics, Task, Usage
from app.providers.fake import FakeProvider
from app.providers.ollama import OllamaProvider
from app.research.decomposer import understand_request
from app.research.pipeline import ResearchPipeline
from app.research.product_intents import is_simple_project_question
from app.research.progress import ndjson_run
from app.research.registry import OFFICE_PACK, WORK_PACK, use_pack
from app.research.run_queue import FairQueue, QueueFullError, product_runs
from app.research.worker import execute_task
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _make_pipe(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("CONTEXT_POLICY", "char_proxy")
    monkeypatch.setenv("MAX_RUN_TOKENS", "12000")
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    src = SourceStore(str(tmp_path / "src"))
    src.import_text("policy.md", "Nhân viên thử việc tối đa 60 ngày. Database dùng PostgreSQL. API dùng JWT.")
    return ResearchPipeline(src, RunStore(str(tmp_path / "runs")))


# ---------------- FQ-01 & FQ-02 ----------------

def test_fq01_notify_callback_exception_does_not_leak_slot_or_deadlock():
    async def go():
        q = FairQueue(1)
        await q.acquire()

        def broken_cb(_pos: int) -> None:
            raise RuntimeError("broken stream sink")

        # Callback failure must NOT leave dead waiter or raise unhandled out of acquire when broken_cb only fails notification;
        # wait in background, cancel waiter cleanly, release holder, and verify zero leak & next acquire succeeds.
        t = asyncio.create_task(q.acquire(on_position=broken_cb))
        await asyncio.sleep(0)
        assert q.waiting == 1
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        q.release()
        assert q.active == 0 and q.waiting == 0
        await asyncio.wait_for(q.acquire(), timeout=0.1)
        assert q.active == 1
        q.release()
        assert q.active == 0

    asyncio.run(go())


def test_fq01_double_release_via_cancellation_cannot_overdecrement():
    async def go():
        q = FairQueue(1)
        tok = await q.acquire()
        q.release(tok)
        # Double-releasing the same token is a no-op; releasing while already 0 stays >=0
        q.release(tok)
        assert q.active == 0
        async with q.slot():
            assert q.active == 1
        assert q.active == 0

    asyncio.run(go())


def test_fq02_dynamic_limit_max_waiters_and_wait_timeout(monkeypatch):
    monkeypatch.setenv("PRODUCT_MAX_CONCURRENT_RUNS", "3")
    try:
        assert product_runs.limit == 3
    finally:
        monkeypatch.delenv("PRODUCT_MAX_CONCURRENT_RUNS", raising=False)

    async def go():
        # Bounded queue depth
        q_bounded = FairQueue(1, max_waiters=1)
        await q_bounded.acquire()
        waiter = asyncio.create_task(q_bounded.acquire())
        await asyncio.sleep(0)
        with pytest.raises(QueueFullError):
            await q_bounded.acquire()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        q_bounded.release()

        # Bounded wait timeout
        q_timed = FairQueue(1, wait_timeout=0.03)
        await q_timed.acquire()
        with pytest.raises(TimeoutError):
            await q_timed.acquire()
        assert q_timed.waiting == 0
        q_timed.release()
        assert q_timed.active == 0

    asyncio.run(go())


# ---------------- AI-GUARD-01/MA-01 & OBS-W3-P82-01 ----------------

def test_ai_guard01_budget_exceeded_marks_partial_never_complete(tmp_path, monkeypatch):
    pipe = _make_pipe(tmp_path, monkeypatch, MAX_RUN_TOKENS="2500")

    class HighTokenFake(FakeProvider):
        async def generate(self, *, system: str, user: str) -> ProviderResult:
            res = await super().generate(system=system, user=user)
            if system.startswith("WORKER."):
                res.usage = Usage(1500, 1500)
            return res

    with patch("app.research.pipeline.get_provider", return_value=HighTokenFake()):
        run = asyncio.run(pipe.run("Review API, database, and authentication security", "C", provider_name="fake"))

    assert len(run["tasks"]) >= 2
    assert 1 <= len(run["task_results"]) < len(run["tasks"])
    assert any(e["stage"] == "run_budget_exceeded" for e in run["events"])
    assert run["status"] == "PARTIAL"
    assert run["status"] != "COMPLETE"


def test_ai_guard01_max_llm_calls_and_dag_wall_timeout(tmp_path, monkeypatch):
    # Max LLM calls guard stops runaway DAG cleanly as PARTIAL/FAILED
    pipe_calls = _make_pipe(tmp_path / "calls", monkeypatch, MAX_RUN_LLM_CALLS="3")
    run_calls = asyncio.run(pipe_calls.run("Review API, database, and authentication security", "C", provider_name="fake"))
    assert any(e["stage"] == "run_budget_exceeded" and e.get("reason") == "max_llm_calls" for e in run_calls["events"])
    assert run_calls["status"] in ("PARTIAL", "FAILED")
    assert run_calls["status"] != "COMPLETE"

    # Wall timeout guard catches stalled DAG execution cleanly without hanging or leaking raw exc
    pipe_timeout = _make_pipe(tmp_path / "timeout", monkeypatch, MAX_DAG_WALL_SECONDS="0.05")

    class SlowWorkerFake(FakeProvider):
        async def generate(self, *, system: str, user: str) -> ProviderResult:
            if system.startswith("WORKER."):
                await asyncio.sleep(0.3)
            return await super().generate(system=system, user=user)

    with patch("app.research.pipeline.get_provider", return_value=SlowWorkerFake()):
        run_to = asyncio.run(pipe_timeout.run("Review API and database schema", "C", provider_name="fake"))
    assert run_to["status"] in ("PARTIAL", "FAILED")
    assert any(e["stage"] in ("run_budget_exceeded", "run_failed") for e in run_to["events"])


def test_obs_w3_p82_01_exception_preserves_tasks_and_hides_raw_error(tmp_path, monkeypatch):
    pipe = _make_pipe(tmp_path, monkeypatch)

    class FailSynthFake(FakeProvider):
        async def generate(self, *, system: str, user: str) -> ProviderResult:
            if system.startswith("SYNTHESIZER."):
                raise RuntimeError("secret_internal_db_error_token_123")
            return await super().generate(system=system, user=user)

    with patch("app.research.pipeline.get_provider", return_value=FailSynthFake()):
        run = asyncio.run(pipe.run("Review API and database schema", "C", provider_name="fake"))

    assert run["status"] == "FAILED"
    assert len(run["tasks"]) >= 2
    assert len(run["task_results"]) >= 1
    assert "secret_internal_db_error_token_123" not in run["answer"]
    failed_ev = next(e for e in run["events"] if e["stage"] == "run_failed")
    assert "secret_internal_db_error_token_123" not in failed_ev.get("error", "")


# ---------------- MA-02, MA-03, MA-04 ----------------

def test_ma02_worker_retries_within_limit_and_isolates_failure(tmp_path, monkeypatch):
    pipe = _make_pipe(tmp_path / "ok_retry", monkeypatch, RETRY_LIMIT="1")

    class TransientFailFake(FakeProvider):
        def __init__(self):
            self.worker_calls = 0

        async def generate(self, *, system: str, user: str) -> ProviderResult:
            if system.startswith("WORKER."):
                self.worker_calls += 1
                if self.worker_calls == 1:
                    raise TimeoutError("transient timeout")
            return await super().generate(system=system, user=user)

    prov = TransientFailFake()
    with patch("app.research.pipeline.get_provider", return_value=prov):
        run = asyncio.run(pipe.run("Review API architecture", "C", provider_name="fake"))
    assert prov.worker_calls == 2
    assert run["status"] == "COMPLETE"

    # Permanent failure in one task isolates gracefully instead of crashing whole run without task_results
    pipe2 = _make_pipe(tmp_path / "perm_fail", monkeypatch, RETRY_LIMIT="1")

    class AlwaysFailOneDomainFake(FakeProvider):
        def __init__(self):
            self.calls = 0

        async def generate(self, *, system: str, user: str) -> ProviderResult:
            if system.startswith("WORKER. Role=Database"):
                self.calls += 1
                raise ValueError("bad json forever")
            return await super().generate(system=system, user=user)

    prov2 = AlwaysFailOneDomainFake()
    with patch("app.research.pipeline.get_provider", return_value=prov2):
        run2 = asyncio.run(pipe2.run("Review API and database schema", "C", provider_name="fake"))
    assert prov2.calls == 2  # initial + 1 retry
    assert run2["status"] == "PARTIAL"
    assert any(r["status"] == "FAILED" for r in run2["task_results"])
    assert any(r["status"] == "COMPLETE" for r in run2["task_results"])


def test_ma03_adaptive_qwen_reuses_preview_retrieval_for_independent_tasks(tmp_path, monkeypatch):
    pipe = _make_pipe(tmp_path, monkeypatch, CONTEXT_POLICY="adaptive_qwen")
    calls: list[str] = []
    orig = ResearchPipeline._retrieve_candidates

    def spy(self, query, chunks, **kwargs):
        calls.append(query)
        return orig(self, query, chunks, **kwargs)

    with patch.object(ResearchPipeline, "_retrieve_candidates", spy):
        run = asyncio.run(pipe.run("Review API architecture and database schema", "C", provider_name="fake"))

    assert run["effective_config"]["context_policy"] == "adaptive_qwen"
    assert len(run["tasks"]) >= 2
    # Should NOT retrieve twice per independent task (was 2 * len(tasks))
    assert len(calls) < 2 * len(run["tasks"])


def test_ma04_product_worker_prompt_isolates_task_scope(tmp_path, monkeypatch):
    prompts: list[str] = []

    class SpyFake(FakeProvider):
        async def generate(self, *, system: str, user: str) -> ProviderResult:
            if system.startswith("WORKER."):
                prompts.append(user)
            return await super().generate(system=system, user=user)

    pipe = _make_pipe(tmp_path, monkeypatch)
    full_q = "Phân tích kiến trúc API và kiểm tra cơ sở dữ liệu PostgreSQL cùng bảo mật JWT."
    with patch("app.research.pipeline.get_provider", return_value=SpyFake()):
        asyncio.run(pipe.run(full_q, "C", provider_name="fake", product_mode=True, domain_pack="software"))

    assert len(prompts) >= 2
    # Must NOT prepend [USER_REQUEST] ahead of [TASK], while still respecting research mode A/B/C
    assert all(not p.startswith("[USER_REQUEST]") for p in prompts)
    assert all(p.index("[TASK]") < len(p) and f"[USER_REQUEST]{full_q}[/USER_REQUEST]" not in p for p in prompts)

    # Non-product Research Mode prompt format stays untouched
    async def non_prod_check():
        captured = []

        class P:
            async def generate(self, *, system, user):
                captured.append(user)
                return ProviderResult(text='{"status":"COMPLETE","answer":"ok","citations":["c1"],"missing_information":[]}', usage=Usage(1, 1))

        await execute_task(P(), Task("T1", "Check DB", "database"), [pipe.source_store.chunks()[0]], RunMetrics(), product=False, user_request=full_q)
        assert captured[0].startswith("[DOMAIN]database[/DOMAIN]\n[TASK]Check DB[/TASK]")

    asyncio.run(non_prod_check())


# ---------------- WORK_PACK_ROUTING ----------------

def test_work_pack_routing_vietnamese_dot_and_multi_domain_factual_stay_simple(tmp_path, monkeypatch):
    vi_dot = "Thời gian thử việc tối đa là bao nhiêu ngày."
    assert is_simple_project_question(vi_dot, ["hr"]) is True

    with use_pack(OFFICE_PACK):
        u_multi_office = understand_request("Sinh viên đi làm thêm có được hưởng bảo hiểm xã hội và miễn thuế thu nhập không?")
    assert is_simple_project_question(
        "Sinh viên đi làm thêm có được hưởng bảo hiểm xã hội và miễn thuế thu nhập không?",
        u_multi_office.domains,
    ) is True

    with use_pack(WORK_PACK):
        u_multi_work = understand_request("Nhân viên đủ điều kiện nghỉ phép thì tính lương bao nhiêu phần trăm?")
    assert is_simple_project_question(
        "Nhân viên đủ điều kiện nghỉ phép thì tính lương bao nhiêu phần trăm?",
        u_multi_work.domains,
    ) is True

    # Complex multi-step / comparative / planning requests MUST still route to s3_planning
    assert is_simple_project_question("Phân tích rủi ro hợp đồng và lập kế hoạch triển khai.", ["hr", "finance"]) is False
    assert is_simple_project_question("So sánh quy chế 2025 và quy chế 2026 về nghỉ phép?", ["hr"]) is False

    pipe = _make_pipe(tmp_path, monkeypatch)
    run_dot = asyncio.run(pipe.run(vi_dot, "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK))
    assert run_dot["effective_config"]["request_route"] == "SIMPLE_PROJECT_QUESTION"


# ---------------- NEW-04 & NEW-05 ----------------

def test_new04_ollama_connect_retry_bounded_and_stream_malformed_ndjson_handled(monkeypatch):
    prov = OllamaProvider(model="qwen3:4b", base_url="http://127.0.0.1:11434", timeout=1.0)

    class RetryThenOkClient:
        def __init__(self):
            self.post_calls = 0

        async def post(self, *a, **kw):
            self.post_calls += 1
            if self.post_calls == 1:
                raise httpx.ConnectError("transient disconnect")

            class Resp:
                def raise_for_status(self): pass
                def json(self): return {"message": {"content": "ok"}, "prompt_eval_count": 2, "eval_count": 3}

            return Resp()

    c1 = RetryThenOkClient()
    with patch("app.providers.ollama._async_client", return_value=c1):
        res = asyncio.run(prov.generate(system="s", user="u"))
    assert c1.post_calls == 2 and res.text == "ok"

    # Malformed NDJSON chunk raises controlled ValueError/RuntimeError instead of raw JSONDecodeError
    class BadStreamResp:
        def raise_for_status(self): pass
        async def aiter_lines(self):
            yield json.dumps({"message": {"content": "Xin "}, "done": False})
            yield "{corrupted-ndjson-line"
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class BadStreamClient:
        def stream(self, *a, **kw):
            return BadStreamResp()

    with patch("app.providers.ollama._async_client", return_value=BadStreamClient()):
        with pytest.raises(RuntimeError, match="ollama stream"):
            asyncio.run(prov.generate_structured(system="s", user="u", response_schema={"type": "object"}, on_text=lambda _: None))


def test_new05_ndjson_run_emits_error_on_inner_cancel():
    from app.research import progress as prog_mod

    async def go():
        gate = asyncio.Event()

        async def blocked_run():
            await gate.wait()
            return {"ok": True}

        gen = ndjson_run(blocked_run)
        read_task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.01)
        for t in list(prog_mod._running):
            if not t.done():
                t.cancel()
        raw = await asyncio.wait_for(read_task, timeout=0.5)
        event = json.loads(raw)
        assert event["type"] == "error"
        assert event["status"] in (499, 500)

    asyncio.run(go())
