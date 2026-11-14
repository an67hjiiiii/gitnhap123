"""Bounded experiment contracts using synthetic data and fake inference only."""

import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
import re
import subprocess
from threading import Lock
from types import SimpleNamespace

import pytest

from app.core.types import ProviderResult, TaskResult, Usage
from app.evaluation import real_runner as runner


@pytest.fixture(autouse=True)
def fake_environment(sf1_fake_provider_env, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.delenv("REVIEW_EXPERIMENT_ALLOW_REAL", raising=False)


class FakeModel:
    name, model = "fake", "deterministic-unit-model"

    def __init__(self, baseline="unparseable", advance=None):
        self.baseline, self.advance = baseline, advance
        self.requests, self.lock = [], Lock()
        self.counter = None

    async def generate(self, *, system, user):
        assert self.lock.acquire(blocking=False), "Inference must be sequential"
        try:
            if self.counter is not None:
                assert self.counter.slot.locked()
            self.requests.append((system, user))
            if self.advance:
                self.advance()
            if "VANILLA_RAG_ANSWERER" in system:
                citations = list(dict.fromkeys(re.findall(r"\[(src_[0-9a-f]{16}_c\d{4})\]", user)))
                request = user.split("EVIDENCE:")[0]
                status = "PARTIAL" if "SMS" in request else "COMPLETE"
                if "Quantum" in request:
                    status, citations = "NO_EVIDENCE", []
                text = json.dumps({"status": status, "answer": "Synthetic answer",
                                   "citations": citations, "missing_information": []})
            else:
                text = self.baseline
            return ProviderResult(text, Usage(17, 5), model=self.model)
        finally:
            self.lock.release()

    async def chat(self, **kwargs):
        return await self.generate(**kwargs)

    async def generate_structured(self, **kwargs):
        kwargs.pop("response_schema")
        return await self.generate(**kwargs)

    async def generate_grounded(self, **kwargs):
        kwargs.pop("evidence_ids")
        return await self.generate(**kwargs)


def run_fake(tmp_path, **kwargs):
    return asyncio.run(runner.run_experiment(out=tmp_path / "report", dry_run=True,
                                           scratch_dir=tmp_path, **kwargs))


@pytest.fixture
def in_memory_run(monkeypatch):
    """Exercise the actual pipeline without relying on filesystem permissions.

    Disk/report integration remains covered separately by the tmp_path tests.
    Only persistence is replaced; chunking, indexing, retrieval and rules run.
    """
    from app.storage import source_store, run_store

    class MemorySources(source_store.SourceStore):
        imports = 0

        def __init__(self, root):
            self._chunks, self._sources = [], {}

        def _save(self):
            pass

        def import_text(self, *args, **kwargs):
            type(self).imports += 1
            return super().import_text(*args, **kwargs)

    def report(result, out):
        for condition in result["conditions"].values():
            condition["metrics"] = runner.score(condition["rows"])
        # Check JSON serialization on every checkpoint as the disk writer does.
        json.dumps(result)

    monkeypatch.setattr(source_store, "SourceStore", MemorySources)
    monkeypatch.setattr(run_store, "RunStore", lambda root: SimpleNamespace(save=lambda record: None))
    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", lambda **kw: nullcontext("unused-memory-root"))
    monkeypatch.setattr(runner, "write_report", report)

    def execute(**kwargs):
        result = asyncio.run(runner.run_experiment(out=Path.cwd(), dry_run=True, **kwargs))
        assert MemorySources.imports == 1
        assert runner.markdown(result).startswith("# Real-model")
        return result

    return execute


def test_actual_pipeline_in_memory_shares_outputs_and_applies_only_rules(in_memory_run):
    fake = FakeModel()
    result = in_memory_run(provider=fake)
    assert result["partial"] is False, result["errors"]
    assert result["total_calls"] == len(fake.requests) <= 12
    assert len(result["grounded_runs"]) == 6
    assert sum(r["stage"] == "baseline" for r in result["calls"]) == 6
    assert result["total_calls"] == 6 + sum(r["calls"] for r in result["grounded_runs"])
    assert result["embedding_calls"] > 1 and result["index"]["chunks_indexed"] == 1
    conditions = result["conditions"]
    assert conditions["B"]["metrics"]["exact_match_accuracy"]["numerator"] == 6
    assert conditions["B0"]["metrics"]["exact_match_accuracy"]["numerator"] == 4
    assert conditions["A"]["metrics"]["exact_match_accuracy"]["numerator"] == 0
    assert [r["predicted"] for r in conditions["C"]["rows"]] == [r["predicted"] for r in conditions["B"]["rows"]]
    assert result["c_switches"]["changes_outcome"] is False
    assert {"calls", "latency_seconds", "usage", "wall_seconds", "errors", "limitations"} <= result.keys()
    assert {"min", "median", "max"} == result["latency_seconds"].keys()
    for condition in conditions.values():
        assert {"false_deviates_rate", "confusion_matrix", "per_verdict", "evidence_hit_rate"} <= condition["metrics"].keys()


def test_actual_pipeline_in_memory_aborts_cleanly_before_25th(in_memory_run, monkeypatch):
    from app.research import pipeline as module

    async def five_calls(provider, query, evidence, metrics, **kwargs):
        for _ in range(5):
            await provider.generate(system="controlled fake pipeline", user=query)
        ids = [c.chunk_id for c in evidence]
        return TaskResult(task_id="T1", domain="general", status="COMPLETE", answer="Test",
                          evidence_ids=ids, citations=ids)

    monkeypatch.setattr(module, "answer_vanilla", five_calls)
    fake = FakeModel("SATISFIED")
    result = in_memory_run(provider=fake)
    assert result["partial"] and "Invocation cap 24" in result["stop_reason"]
    assert result["total_calls"] == len(fake.requests) == 24
    assert len(result["grounded_runs"]) == 4
    assert all(r["calls"] == 5 for r in result["grounded_runs"])


def test_actual_pipeline_in_memory_wall_expiry_is_partial(in_memory_run):
    now = [0.0]
    fake = FakeModel(advance=lambda: now.__setitem__(0, 61))
    result = in_memory_run(provider=fake, clock=lambda: now[0], max_minutes=1)
    assert result["partial"] and "Wall-clock" in result["stop_reason"]
    assert result["total_calls"] == len(fake.requests) == 1


def test_counter_caps_before_25th_and_counts_all_dispatch_methods():
    fake = FakeModel("SATISFIED")
    counter = runner.CountingProvider(fake)
    fake.counter = counter

    async def exercise():
        for _ in range(6):
            await counter.generate(system="unit", user="requirement")
            await counter.chat(system="unit", user="requirement")
            await counter.generate_structured(system="unit", user="requirement", response_schema={})
            await counter.generate_grounded(system="unit", user="requirement", evidence_ids=[])
        with pytest.raises(runner.LimitExceeded, match="24"):
            await counter.generate(system="unit", user="requirement")

    asyncio.run(exercise())
    assert counter.count == len(fake.requests) == 24
    assert counter.failure and not counter.slot.locked()
    assert all(call["latency_seconds"] >= 0 for call in counter.calls)
    assert counter.snapshot()["usage"]["estimated_calls"] == 24


def test_counter_refuses_overlapping_coroutines_without_threads():
    async def exercise():
        entered, finish = asyncio.Event(), asyncio.Event()

        async def generate(**kwargs):
            entered.set()
            await finish.wait()
            return ProviderResult("SATISFIED")

        counter = runner.CountingProvider(SimpleNamespace(generate=generate))
        first = asyncio.create_task(counter.generate(system="", user=""))
        await entered.wait()
        with pytest.raises(RuntimeError, match="Concurrent inference"):
            await counter.generate(system="", user="")
        finish.set()
        await first
        assert counter.count == 1 and not counter.slot.locked()

    asyncio.run(exercise())


def test_wall_limit_is_latched_with_injected_clock():
    now = [0.0]
    fake = FakeModel(advance=lambda: now.__setitem__(0, 61))
    counter = runner.CountingProvider(fake, max_seconds=60, clock=lambda: now[0])
    with pytest.raises(runner.LimitExceeded, match="Wall-clock"):
        asyncio.run(counter.generate(system="unit", user="requirement"))
    with pytest.raises(runner.LimitExceeded):
        asyncio.run(counter.chat(system="unit", user="requirement"))
    assert counter.count == len(fake.requests) == 1
    assert counter.calls[0]["latency_seconds"] == 61
    assert counter.calls[0]["error"].startswith("LimitExceeded")


def test_embedding_accounted_separately_and_checks_wall_limit():
    now = [0.0]

    def embed(text):
        now[0] = 61
        return (1.0,)

    counter = runner.CountingProvider(FakeModel(), max_invocations=0, max_seconds=60,
                                      clock=lambda: now[0])
    embedder = runner.CountingEmbedder(SimpleNamespace(dimension=1, version="test", embed=embed), counter)
    with pytest.raises(runner.LimitExceeded, match="Wall-clock"):
        embedder.embed("synthetic text")
    assert counter.count == 0 and len(counter.embedding_calls) == 1
    assert counter.embedding_calls[0]["input_chars"] == 14


def test_usage_records_provider_tokens_and_falls_back_to_char_estimates():
    fake = FakeModel("SATISFIED")
    fake.name = "unit-stub-with-measured-usage"
    counter = runner.CountingProvider(fake)
    asyncio.run(counter.generate(system="unit", user="requirement"))
    assert counter.calls[0]["prompt_tokens"] == 17
    assert counter.calls[0]["completion_tokens"] == 5
    assert counter.calls[0]["usage_estimated"] is False
    async def no_usage(**kwargs):
        return SimpleNamespace(text="abcd")

    fake.generate = no_usage
    asyncio.run(counter.generate(system="unit", user="requirement"))
    assert counter.calls[1]["usage_unit"] == "characters"
    assert counter.calls[1]["completion_chars"] == 4


def test_shared_grounding_rules_and_report_fields(tmp_path, monkeypatch):
    from app.retrieval.candidate_index import CandidateIndex
    from app.review.schemas import Evidence
    from app.review_adapters.verdict_rules import assess

    indexed = []
    original = CandidateIndex.index_source

    def index_once(self, source_id):
        indexed.append(source_id)
        return original(self, source_id)

    monkeypatch.setattr(CandidateIndex, "index_source", index_once)
    fake = FakeModel()
    result = run_fake(tmp_path, provider=fake)
    assert result["partial"] is False and result["stop_reason"] is None
    assert len(indexed) == result["index"]["chunks_indexed"] == 1
    assert len(result["grounded_runs"]) == 6
    assert all(row["calls"] in (0, 1) for row in result["grounded_runs"])
    baseline = [r for r in result["calls"] if r["stage"] == "baseline"]
    assert len(baseline) == 6
    assert result["total_calls"] == len(fake.requests) == 6 + sum(r["calls"] for r in result["grounded_runs"])
    assert result["total_calls"] <= 12
    assert result["embedding_calls"] > 1
    assert sum(r["stage"] == "index" for r in result["embeddings"]) == 1
    corpus = runner.load_corpus()
    baseline_requests = [user for system, user in fake.requests if "VANILLA_RAG_ANSWERER" not in system]
    assert baseline_requests == [r["text"] for r in corpus["requirements"]]
    assert result["conditions"]["A"]["metrics"]["exact_match_accuracy"]["numerator"] == 0
    assert all(row["predicted"] == "UNDETERMINED" for row in result["conditions"]["A"]["rows"])
    differences = []
    for req, raw, b0, b, c in zip(corpus["requirements"], result["grounded_runs"],
                                *(result["conditions"][k]["rows"] for k in ("B0", "B", "C"))):
        evidence = [Evidence.model_validate(e) for e in raw["evidence"]]
        expected = {"COMPLETE": "SATISFIED" if evidence else "UNDETERMINED",
                    "PARTIAL": "PARTIAL", "NO_EVIDENCE": "NOT_FOUND"}[raw["raw_status"]]
        assert b0["predicted"] == expected
        if evidence and raw["raw_status"] in {"COMPLETE", "PARTIAL"} and assess(req["text"], evidence).conflicting:
            expected = "DEVIATES"
        assert b["predicted"] == c["predicted"] == expected
        if b["predicted"] != b0["predicted"]:
            differences.append(req["id"])
    assert differences == ["log-retention", "plaintext-passwords"]
    assert result["c_switches"]["changes_outcome"] is False
    for condition in result["conditions"].values():
        assert condition["metrics"]["exact_match_accuracy"]["denominator"] == 6
        assert {"false_deviates_rate", "confusion_matrix", "per_verdict", "evidence_hit_rate"} <= condition["metrics"].keys()
    assert {"calls", "latency_seconds", "usage", "wall_seconds", "errors", "limitations"} <= result.keys()
    assert {"min", "median", "max"} == result["latency_seconds"].keys()
    assert json.loads((tmp_path / "report/experiment_real.json").read_text(encoding="utf-8")) == result
    markdown = (tmp_path / "report/experiment_real.md").read_text(encoding="utf-8")
    for value in ("n=6", "single model", "single repeat", "not statistically meaningful", "not evidence", "per-verdict confusion", "Per-call"):
        assert value in markdown


def test_runner_aborts_at_24_with_partial_flag_even_when_pipeline_catches_limit(tmp_path, monkeypatch):
    from app.research import pipeline as module

    async def five_calls(provider, query, evidence, metrics, **kwargs):
        for _ in range(5):
            await provider.generate(system="controlled fake pipeline", user=query)
        citations = [c.chunk_id for c in evidence]
        return TaskResult(task_id="T1", domain="general", status="COMPLETE", answer="Test",
                          evidence_ids=citations, citations=citations)

    monkeypatch.setattr(module, "answer_vanilla", five_calls)
    fake = FakeModel("SATISFIED")
    result = run_fake(tmp_path, provider=fake)
    assert result["partial"] is True
    assert "Invocation cap 24" in result["stop_reason"]
    assert result["total_calls"] == len(fake.requests) == 24
    assert len(result["grounded_runs"]) == 4
    assert [r["calls"] for r in result["grounded_runs"]] == [5] * 4
    assert result["conditions"]["A"]["metrics"]["exact_match_accuracy"]["denominator"] == 6
    saved = json.loads((tmp_path / "report/experiment_real.json").read_text(encoding="utf-8"))
    assert saved["partial"] and saved["total_calls"] == 24


@pytest.mark.parametrize("cap", [0, 1, 2])
def test_lower_caps_also_preserve_partial_reports(tmp_path, cap):
    result = run_fake(tmp_path, provider=FakeModel(), max_invocations=cap)
    assert result["partial"] and result["total_calls"] == cap


def test_runner_wall_expiry_returns_partial_report(tmp_path):
    now = [0.0]
    fake = FakeModel(advance=lambda: now.__setitem__(0, 61))
    result = run_fake(tmp_path, provider=fake, clock=lambda: now[0], max_minutes=1)
    assert result["partial"] and "Wall-clock" in result["stop_reason"]
    assert result["total_calls"] == 1


@pytest.mark.parametrize("text,expected", [
    ("VERDICT: SATISFIED", "SATISFIED"),
    ("Reason: uncertain\nVERDICT: partial", "PARTIAL"),
    ("VERDICT: PARTIAL\nReason: reconsidered\nVERDICT: DEVIATES", "DEVIATES"),
    ("**VERDICT: `NOT_FOUND`**", "NOT_FOUND"),
    ("<think>VERDICT: DEVIATES</think>\nVERDICT: SATISFIED", "SATISFIED"),
    ("Maybe SATISFIED or DEVIATES", "UNDETERMINED"),
    ('{"verdict":"PARTIAL"}', "UNDETERMINED"), ("[]", "UNDETERMINED"),
])
def test_baseline_parser_is_deterministic(text, expected):
    assert runner.parse_baseline(text) == expected


def test_verbose_baseline_output_ignores_thinking_and_reads_trailing_verdict():
    output = ("<think>" + "reasoning " * 400 + "VERDICT: DEVIATES</think>\n"
              "Reason: The policy explicitly covers the request.\nVERDICT: SATISFIED")
    assert runner.parse_baseline(output) == "SATISFIED"


def test_baseline_only_runs_six_calls_without_pipeline_or_index(monkeypatch):
    def memory_report(result, out):
        for condition in result["conditions"].values():
            condition["metrics"] = runner.score(condition["rows"])
    monkeypatch.setattr(runner, "write_report", memory_report)
    fake = FakeModel("Reason: Covered.\nVERDICT: SATISFIED")
    result = asyncio.run(runner.run_experiment(out=Path.cwd(), dry_run=True,
                                               provider=fake, baseline_only=True))
    assert result["mode"] == "baseline-only"
    assert result["partial"] is False
    assert result["total_calls"] == len(fake.requests) == 6
    assert result["embedding_calls"] == 0 and result["grounded_runs"] == []
    assert all(call["stage"] == "baseline" for call in result["calls"])
    assert all(row["predicted"] == "SATISFIED" for row in result["conditions"]["A"]["rows"])
    assert "Mode: baseline-only" in runner.markdown(result)


def test_baseline_only_stops_at_lower_invocation_cap(monkeypatch):
    def memory_report(result, out):
        for condition in result["conditions"].values():
            condition["metrics"] = runner.score(condition["rows"])
    monkeypatch.setattr(runner, "write_report", memory_report)
    garbage = "unstructured verbose response " * 12
    fake = FakeModel(garbage)
    result = asyncio.run(runner.run_experiment(out=Path.cwd(), dry_run=True,
                                               provider=fake, baseline_only=True,
                                               max_invocations=3))
    assert result["mode"] == "baseline-only"
    assert result["partial"] is True and "Invocation cap 3" in result["stop_reason"]
    assert result["total_calls"] == len(fake.requests) == 3
    assert result["embedding_calls"] == 0 and result["grounded_runs"] == []
    output_errors = [error for error in result["errors"]
                     if error["error"].startswith("Unparseable baseline output:")]
    assert len(output_errors) == 3
    assert all(error["error"] == f"Unparseable baseline output: {garbage[:200]}"
               for error in output_errors)


@pytest.mark.parametrize("real,env", [(False, None), (True, None), (False, "1")])
def test_real_refused_without_both_opt_ins(monkeypatch, real, env):
    if env:
        monkeypatch.setenv("REVIEW_EXPERIMENT_ALLOW_REAL", env)
    with pytest.raises(PermissionError, match="--real AND"):
        asyncio.run(runner.run_experiment(out=Path.cwd(), real=real))


@pytest.mark.parametrize("calls,minutes", [(25, 60), (24, 61), (24, float("nan")), (-1, 1), (True, 1), (1, 0)])
def test_owner_hard_caps_cannot_be_relaxed(calls, minutes):
    with pytest.raises(ValueError):
        runner.validate_limits(calls, minutes)


@pytest.mark.parametrize("relative", ["data", "data/nested", "backend/data/nested", "runs", "backend/runs"])
def test_output_refuses_repository_data_without_writing(relative):
    with pytest.raises(ValueError, match="Refusing repository"):
        runner.validate_output(runner.REPO / relative)


def test_qdrant_path_constraints_and_existing_index_refusal(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="outside the repository"):
        runner.validate_qdrant_dir(tmp_path / "index")
    monkeypatch.setattr(runner, "REPO", tmp_path / "pretend-repo")
    monkeypatch.setattr(runner.tempfile, "gettempdir", lambda: str(tmp_path))
    assert runner.validate_qdrant_dir(tmp_path / "new-index") == tmp_path / "new-index"
    existing = tmp_path / "index"
    existing.mkdir()
    (existing / "test-marker").write_text("synthetic", encoding="utf-8")
    with pytest.raises(ValueError, match="new or empty"):
        runner.validate_qdrant_dir(existing)
    with pytest.raises(ValueError, match="under a temp"):
        runner.validate_qdrant_dir(tmp_path.parent / "not-under-temp")


def test_cli_refuses_real_without_opt_in_before_launch(monkeypatch):
    from scripts import run_experiment_real as cli

    def unexpected_launch(*args, **kwargs):
        pytest.fail("Refused CLI must not start a process")

    monkeypatch.setattr(cli.subprocess, "Popen", unexpected_launch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--real", "--out", str(Path.cwd()), "--qdrant-dir", str(Path.cwd() / "unused-index")])
    assert exc.value.code == 2


def test_cli_watchdog_enforces_timeout_without_filesystem(monkeypatch):
    from scripts import run_experiment_real as cli

    events = []

    class StalledWorker:
        def wait(self, timeout=None):
            if timeout is not None:
                events.append(timeout)
                raise subprocess.TimeoutExpired("unit fake worker", timeout)
            return 0

        def kill(self):
            events.append("kill")

        def poll(self):
            return 0

    monkeypatch.setattr(cli, "validate_qdrant_dir", lambda path: path)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *args, **kwargs: StalledWorker())
    monkeypatch.setattr(cli, "mark_watchdog_timeout", lambda out, **kwargs: events.append(kwargs))
    code = cli.main(["--dry-run", "--out", str(Path.cwd()), "--qdrant-dir", "unused-memory-index",
                     "--max-invocations", "7", "--max-minutes", "1"])
    assert code == 2
    assert events == [60, "kill", {"seconds": 60, "dry_run": True, "max_invocations": 7}]


def test_cli_watchdog_kills_worker_and_finalizes_checkpoint(tmp_path, monkeypatch):
    from scripts import run_experiment_real as cli

    result = run_fake(tmp_path, provider=FakeModel())
    monkeypatch.setattr(runner, "REPO", tmp_path / "pretend-repo")
    monkeypatch.setattr(runner.tempfile, "gettempdir", lambda: str(tmp_path))
    events = []

    class StalledWorker:
        def wait(self, timeout=None):
            if timeout is not None:
                events.append(timeout)
                raise subprocess.TimeoutExpired("unit fake worker", timeout)
            return 0

        def kill(self):
            events.append("kill")

        def poll(self):
            return 0

    monkeypatch.setattr(cli.subprocess, "Popen", lambda *args, **kwargs: StalledWorker())
    code = cli.main(["--dry-run", "--out", str(tmp_path / "report"),
                     "--qdrant-dir", str(tmp_path / "index"), "--max-minutes", "1"])
    assert code == 2 and events == [60, "kill"]
    saved = json.loads((tmp_path / "report/experiment_real.json").read_text(encoding="utf-8"))
    assert saved["partial"] and "watchdog" in saved["stop_reason"]
    assert saved["total_calls"] == result["total_calls"]


def test_corpus_is_short_synthetic_and_has_required_label_coverage():
    corpus = runner.load_corpus()
    assert len(re.findall(r"\.(?:\s|$)", corpus["source"]["text"])) == 7
    labels = [r["expected"] for r in corpus["requirements"]]
    assert labels.count("SATISFIED") == labels.count("DEVIATES") == 2
    assert labels.count("PARTIAL") == labels.count("NOT_FOUND") == 1
    assert all(r["expected_locators"] == ([corpus["source"]["locator"]]
                                        if r["expected"] != "NOT_FOUND" else [])
               for r in corpus["requirements"])
