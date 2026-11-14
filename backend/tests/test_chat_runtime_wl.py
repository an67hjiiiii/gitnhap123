"""Chat runtime robustness with local providers and isolated persistence."""
import asyncio
import importlib.util
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import dotenv
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.chat.answer_guard import AnswerChecker
from app.core.config import RuntimeConfig
from app.core.types import ProviderResult, RunMetrics, SourceChunk, Usage
from app.research import pipeline as pipeline_module
from app.research import product_retrieval as retrieval
from app.storage.postgres.models import RunRecord
from app.storage.postgres.runtime import PostgresRunStore
from app.storage.run_store import RunStore


CHUNK = SourceChunk("c1", "s1", "policy.txt", "Access expires after 45 minutes.", 0, 0.2)
QUERY = "When does access expire?"


@pytest.fixture(autouse=True)
def local_env(monkeypatch, sf1_fake_provider_env):
    monkeypatch.setattr(pipeline_module, "gpu_memory_mb", lambda: None)
    monkeypatch.setattr(pipeline_module, "process_rss_mb", lambda: 1.0)
    monkeypatch.setenv("RETRIEVAL_RETRY", "0")
    monkeypatch.setenv("RETRIEVAL_FUSION", "off")
    monkeypatch.setenv("ANSWER_LLM_VERIFY", "0")
    monkeypatch.setenv("MAX_RUN_TOKENS", "12000")


@pytest.fixture
def pipeline(monkeypatch, sf1_pipeline_factory, sf1_vector_store):
    instance = sf1_pipeline_factory()
    monkeypatch.setattr(instance, "_retrieve_candidates", lambda *a, **kw: [CHUNK])
    return instance


@pytest.mark.parametrize("condition,product,force_plan", [
    ("A", False, False), ("B", False, False), ("C", False, False),
    ("A", True, False), ("B", True, False), ("C", True, True),
])
def test_cancel_persists_terminal_status(monkeypatch, pipeline, condition, product, force_plan):
    async def scenario():
        entered = asyncio.Event()

        class WaitingProvider:
            name, model = "fake", "waiting"

            async def generate(self, **kwargs):
                entered.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(pipeline_module, "get_provider", lambda _: WaitingProvider())
        task = asyncio.create_task(pipeline.run(
            QUERY, condition, product_mode=product, force_plan=force_plan))
        await asyncio.wait_for(entered.wait(), 1)
        assert pipeline.run_store.list()[0]["lifecycle_status"] == "RUNNING"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        run = pipeline.run_store.get(pipeline.run_store.list()[0]["run_id"])
        assert run["status"] == run["lifecycle_status"] == "FAILED"
        assert run["answer"] == "CLIENT_CANCELLED"

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["file", "postgres_sqlite"])
def test_stale_runs_preserve_fresh_terminal_and_other_owner(tmp_path, backend):
    engine = None
    if backend == "file":
        store = RunStore(str(tmp_path / "outputs"))
        other = RunStore(str(tmp_path / "other"))
    else:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        RunRecord.__table__.create(engine)
        factory = sessionmaker(engine)
        store, other = PostgresRunStore(factory, "alice"), PostgresRunStore(factory, "bob")
    now = datetime.now(timezone.utc)
    for run_id, age, status in [("old", 7200, "RUNNING"), ("fresh", 0, "RUNNING"), ("done", 7200, "COMPLETED")]:
        store.save({"run_id": run_id, "created_at": (now - timedelta(seconds=age)).isoformat(),
                    "lifecycle_status": status, "status": None if status == "RUNNING" else "COMPLETE"})
    other.save({"run_id": "other", "created_at": (now - timedelta(seconds=7200)).isoformat(),
                "lifecycle_status": "RUNNING", "status": None})
    assert store.mark_stale_running_runs(3600) == 1
    assert store.get("old")["answer"] == store.get("old")["error"] == "STALE_RUN"
    assert store.get("old")["status"] == store.get("old")["lifecycle_status"] == "FAILED"
    assert store.get("fresh")["lifecycle_status"] == "RUNNING"
    assert store.get("done")["status"] == "COMPLETE"
    assert other.get("other")["lifecycle_status"] == "RUNNING"
    assert store.mark_stale_running_runs(3600) == 0
    if engine is not None:
        engine.dispose()


class ScriptedProvider:
    name, model = "fake", "scripted"

    def __init__(self, *, rewrite_tokens=0, answer_tokens=0, fail=None):
        self.calls = []
        self.rewrite_tokens, self.answer_tokens, self.fail = rewrite_tokens, answer_tokens, fail

    async def generate(self, *, system, user):
        step = "rewrite" if "rewrite a question" in system else "verifier" if "fact checker" in system else "answer"
        self.calls.append(step)
        if step == self.fail:
            raise TimeoutError("fake timeout")
        if step == "rewrite":
            return ProviderResult("access expiry", Usage(output_tokens=self.rewrite_tokens))
        if step == "verifier":
            return ProviderResult('{"unsupported":[]}', Usage())
        return ProviderResult(json.dumps({"status": "COMPLETE", "answer": "Access expires after 45 minutes.",
                                          "citations": ["c1"]}), Usage(output_tokens=self.answer_tokens))


def test_rewrite_budget_skips_answer(monkeypatch, pipeline):
    monkeypatch.setenv("MAX_RUN_TOKENS", "512")
    monkeypatch.setenv("RETRIEVAL_RETRY", "1")
    provider = ScriptedProvider(rewrite_tokens=700)
    monkeypatch.setattr(pipeline_module, "get_provider", lambda _: provider)
    run = asyncio.run(pipeline.run(QUERY, "A", product_mode=True))
    assert provider.calls == ["rewrite"]
    assert run["status"] == "NO_EVIDENCE"
    assert "RUN_BUDGET_EXCEEDED" in run["answer"]
    assert [(e["total_tokens"], e["skipped_step"]) for e in run["events"]
            if e["stage"] == "run_budget_exceeded"] == [(700, "answer")]
    assert run["metrics"]["output_tokens"] == 700


def test_budget_before_rewrite(monkeypatch, pipeline):
    monkeypatch.setenv("RETRIEVAL_RETRY", "1")
    monkeypatch.setenv("MAX_RUN_TOKENS", "512")
    metrics, events, provider = RunMetrics(output_tokens=512), [], ScriptedProvider()
    asyncio.run(retrieval.product_retrieve(
        pipeline, provider, metrics, query=QUERY, retrieval_query=QUERY, chunks=[CHUNK],
        cfg=RuntimeConfig.from_env(), source_ids=None, trace={},
        event=lambda stage, **data: events.append({"stage": stage, **data})))
    assert provider.calls == []
    assert any(e.get("skipped_step") == "query_rewrite" and e["total_tokens"] == 512 for e in events)


def test_answer_budget_skips_verifier_and_keeps_answer(monkeypatch, pipeline):
    monkeypatch.setenv("MAX_RUN_TOKENS", "512")
    monkeypatch.setenv("ANSWER_LLM_VERIFY", "1")
    provider = ScriptedProvider(answer_tokens=700)
    monkeypatch.setattr(pipeline_module, "get_provider", lambda _: provider)
    run = asyncio.run(pipeline.run(QUERY, "A", product_mode=True, answer_checker=AnswerChecker()))
    assert provider.calls == ["answer"]
    assert run["status"] == "PARTIAL"
    assert "Access expires after 45 minutes." in run["answer"]
    assert any(e.get("skipped_step") == "verifier" and e["total_tokens"] == 700 for e in run["events"])


@pytest.mark.parametrize("step", ["rewrite", "answer", "verifier"])
def test_failed_attempt_is_counted_and_answer_survives(monkeypatch, pipeline, step):
    monkeypatch.setenv("RETRIEVAL_RETRY", "1" if step == "rewrite" else "0")
    monkeypatch.setenv("ANSWER_LLM_VERIFY", "1")
    provider = ScriptedProvider(fail=step)
    monkeypatch.setattr(pipeline_module, "get_provider", lambda _: provider)
    run = asyncio.run(pipeline.run(QUERY, "A", product_mode=True, answer_checker=AnswerChecker()))
    assert run["metrics"]["failed_llm_attempts"] == 1
    assert run["status"] != "FAILED" and run["answer"]
    assert pipeline.run_store.get(run["run_id"])["metrics"]["failed_llm_attempts"] == 1


@pytest.mark.parametrize("retry,multi", [(False, False), (True, False), (False, True)])
def test_product_retrieval_heartbeat_and_retry_order(monkeypatch, pipeline, retry, multi):
    monkeypatch.setenv("RETRIEVAL_RETRY", "1" if retry else "0")
    active = threading.Event()
    ticks, events, work_order = [], [], []
    original = retrieval._lists_for

    def slow(*args, **kwargs):
        work_order.append("work")
        active.set()
        try:
            time.sleep(0.15)
            return original(*args, **kwargs)
        finally:
            active.clear()

    def event(stage, **data):
        events.append({"stage": stage, **data})
        if stage == "retrieval.retry":
            work_order.append(data["phase"])

    monkeypatch.setattr(retrieval, "_lists_for", slow)

    async def scenario():
        query = "When does access expire and how is access granted" if multi else QUERY
        task = asyncio.create_task(retrieval.product_retrieve(
            pipeline, ScriptedProvider(), RunMetrics(), query=query, retrieval_query=query,
            chunks=[CHUNK], cfg=RuntimeConfig.from_env(), source_ids=None, trace={}, event=event, multi=multi))
        while not task.done():
            if active.is_set():
                ticks.append(len(work_order))
            await asyncio.sleep(0.02)
        await task

    asyncio.run(scenario())
    assert len(ticks) >= 2
    if retry:
        phases = [e for e in events if e["stage"] == "retrieval.retry"]
        assert [e["phase"] for e in phases] == ["start", "end"]
        assert phases[0]["reasons"] == phases[1]["reasons"]
        assert {"before", "after", "gained"} <= phases[1].keys()
        assert work_order == ["work", "start", "work", "end"]
        assert ticks.count(3) >= 2  # Heartbeat also ticks during the retry itself.


@pytest.mark.parametrize("condition,policy", [("A", "char_proxy"), ("B", "char_proxy"), ("C", "adaptive_qwen")])
def test_legacy_and_planning_retrieval_do_not_block(monkeypatch, pipeline, condition, policy):
    active = threading.Event()
    ticks, threads = [], []
    main_thread = threading.get_ident()

    def slow(*args, **kwargs):
        threads.append(threading.get_ident())
        active.set()
        try:
            time.sleep(0.15)
            return [CHUNK]
        finally:
            active.clear()

    monkeypatch.setattr(pipeline, "_retrieve_candidates", slow)

    async def scenario():
        task = asyncio.create_task(pipeline.run(QUERY, condition, context_policy=policy))
        while not task.done():
            if active.is_set():
                ticks.append(1)
            await asyncio.sleep(0.02)
        return await task

    run = asyncio.run(scenario())
    assert run["status"] != "FAILED", run["answer"]
    assert len(ticks) >= 2 and threads and all(t != main_thread for t in threads)
    if condition == "C":
        assert any(e["stage"] == "adaptive_budget_plan" for e in run["events"])
        assert len(threads) >= 2  # Preview and execution retrieval both ran off the loop.


@pytest.fixture
def chat_module(monkeypatch, tmp_path, sf1_vector_store):
    import app.auth.store as auth_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    monkeypatch.setattr(auth_module, "AuthStore", lambda *a: SimpleNamespace(resolve=lambda token: {"user_id": token}))
    for key, value in {"APP_STORAGE_BACKEND": "file", "APP_ENV": "test", "APP_DATA_DIR": str(tmp_path / "documents"),
                       "RUNS_DIR": str(tmp_path / "outputs"), "VECTOR_BACKEND": "memory"}.items():
        monkeypatch.setenv(key, value)
    name = "app._wl_runtime_main"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app" / "main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_configured_vector_store", lambda: sf1_vector_store)
    return module


def test_startup_recovers_owner_runs(chat_module, monkeypatch):
    store = chat_module.owner_run_store({"user_id": "alice"})
    store.save({"run_id": "old", "created_at": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
                "lifecycle_status": "RUNNING"})
    monkeypatch.setenv("CHAT_STALE_RUN_SECONDS", "60")
    chat_module.mark_stale_chat_runs()
    assert store.get("old")["answer"] == "STALE_RUN"


@pytest.mark.parametrize("chat_table", [False, True])
def test_sql_startup_handles_optional_chat_table(chat_module, monkeypatch, chat_table):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessionmaker(engine)
    monkeypatch.setattr(chat_module, "STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(chat_module.app.state, "session_factory", factory)
    store = PostgresRunStore(factory, "alice")
    try:
        if chat_table:
            RunRecord.__table__.create(engine)
            store.save({"run_id": "old", "created_at": (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat(),
                        "lifecycle_status": "RUNNING"})
        chat_module.mark_stale_chat_runs()
        if chat_table:
            assert store.get("old")["answer"] == "STALE_RUN"
    finally:
        engine.dispose()


def test_stream_close_waits_for_cancelled_pipeline(chat_module, monkeypatch, pipeline):
    async def scenario():
        entered = asyncio.Event()

        async def waiting_answer(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        async def core(*args, on_event, **kwargs):
            on_event({"stage": "request_understanding"})
            return await pipeline.run(QUERY, "A", on_event=on_event)

        monkeypatch.setattr(pipeline_module, "answer_vanilla", waiting_answer)
        monkeypatch.setattr(chat_module, "_chat_core", core)
        # The endpoint returns a StreamingResponse; closing its iterator models disconnect cleanup.
        response = await chat_module.chat_stream(chat_module.ChatRequest(message=QUERY), None)
        iterator = response.body_iterator
        await anext(iterator)
        await asyncio.wait_for(entered.wait(), 1)
        await iterator.aclose()
        row = pipeline.run_store.list()[0]
        assert row["status"] == row["lifecycle_status"] == "FAILED"
        assert pipeline.run_store.get(row["run_id"])["answer"] == "CLIENT_CANCELLED"

    asyncio.run(scenario())
