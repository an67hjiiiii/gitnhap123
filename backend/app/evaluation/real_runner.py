"""Serial, bounded model experiment using one shared grounded result per item.

The research pipeline's default condition A is grounded vanilla RAG. It is used
for B0/B/C here; experiment A is a separate, source-free direct provider call.
Run this module through scripts/run_experiment_real.py for the process watchdog.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
from statistics import median
import tempfile
from threading import Lock
from time import monotonic
from unittest.mock import patch

from .metrics import LABELS, score
from .harness import CONDITION_FLAG_MAP
from .experiment import config_hash

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "backend/tests/fixtures/real_exp/corpus.json"
LIMITATIONS = (
    "n=6, single model, single repeat; results are not statistically meaningful. "
    "Dry-run results are not evidence of real-model quality. Synthetic test data only. "
    "Evidence locators identify the single policy chunk, not individual claims. "
    "B0/B/C reuse exactly the same grounded model output. C uses the review router "
    "(advisory; it retains the configured engine), requirement budget and memory recall. "
    "With six affordable requirements and empty test memory, these switches do not "
    "change B's verdicts; this does not measure a benefit from routing or memory. "
    "ResearchPipeline's separate multi-task condition C is not evaluated. "
    "Missing/failed items are UNDETERMINED and count as wrong in all six-item denominators."
)


class LimitExceeded(RuntimeError):
    """A latched invocation or wall-clock limit; no subsequent work is allowed."""


def authorize(*, real=False, dry_run=False):
    if not dry_run and not (real and os.getenv("REVIEW_EXPERIMENT_ALLOW_REAL") == "1"):
        raise PermissionError("Require --real AND REVIEW_EXPERIMENT_ALLOW_REAL=1")


def validate_limits(max_invocations, max_minutes):
    if type(max_invocations) is not int or not 0 <= max_invocations <= 24:
        raise ValueError("max_invocations must be an integer between 0 and the hard cap 24")
    if (isinstance(max_minutes, bool) or not isinstance(max_minutes, (int, float))
            or not math.isfinite(max_minutes) or not 0 < max_minutes <= 60):
        raise ValueError("max_minutes must be finite, positive and at most the hard cap 60")


def validate_output(out):
    out = Path(out).resolve()
    for name in ("data", "backend/data", "runs", "backend/runs"):
        forbidden = REPO / name
        if out == forbidden or forbidden in out.parents:
            raise ValueError("Refusing repository data/ or runs/ output")
    return out


def validate_qdrant_dir(path):
    path = Path(path).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if (REPO == path or REPO in path.parents or temp not in path.parents):
        raise ValueError("qdrant-dir must be under a temp path outside the repository")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("qdrant-dir must be new or empty; existing indexes are refused")
    return path


def load_corpus(path=CORPUS):
    item = json.loads(Path(path).read_text(encoding="utf-8"))
    requirements = item["requirements"]
    if (len(requirements) != 6 or len({r["id"] for r in requirements}) != 6
            or any(r["expected"] not in LABELS for r in requirements)):
        raise ValueError("Require exactly six uniquely labelled requirements")
    if not item["source"]["text"].strip() or not item["source"]["locator"]:
        raise ValueError("Require a synthetic source and evidence locator")
    return item


def parse_baseline(text):
    """Read the last explicit verdict line, ignoring any model thinking block."""
    value = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", str(text),
                   flags=re.IGNORECASE | re.DOTALL)
    matches = list(re.finditer(r"\bVERDICT\s*:\s*([^\r\n]*)", value, flags=re.IGNORECASE))
    if not matches:
        return "UNDETERMINED"
    label = matches[-1].group(1).strip().strip("`*_\"'“”‘’ ")
    if label.endswith("**"):
        label = label[:-2].strip()
    label = label.upper()
    if label in {"SATISFIED", "PARTIAL", "DEVIATES", "NOT_FOUND"}:
        return label
    return "UNDETERMINED"


BASELINE_SYSTEM = (
    "Judge the requirement directly, without source documents. Do not provide extended reasoning, "
    "analysis, or a preamble. Return a one-line reason and then exactly one final verdict line. "
    "The only allowed verdicts are SATISFIED, PARTIAL, DEVIATES, and NOT_FOUND. "
    "Use this one-shot format example:\n"
    "Reason: The requirement is explicitly met.\n"
    "VERDICT: SATISFIED"
)


def _field(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


class CountingProvider:
    """Count dispatches, including structured/grounded calls, before invoking.

    Provider convenience methods delegate on the underlying instance, so one
    dispatch corresponds to one inference, without double-counting _generate.
    The supported providers have no internal retries. Failed dispatches count.
    No threads are started. Re-entrant/concurrent dispatches are refused.
    """

    def __init__(self, provider, max_invocations=24, max_seconds=3600, *, clock=monotonic):
        validate_limits(max_invocations, max_seconds / 60)
        self.provider = provider
        self.max_invocations, self.max_seconds = max_invocations, max_seconds
        self.clock, self.started = clock, clock()
        self.calls, self.embedding_calls = [], []
        self.failure = None
        self.slot = Lock()
        self.context = {}
        self.on_update = lambda: None

    @property
    def count(self):
        return len(self.calls)

    @property
    def elapsed(self):
        return max(0.0, self.clock() - self.started)

    def stop(self, reason):
        self.failure = self.failure or reason
        raise LimitExceeded(self.failure)

    def check(self):
        if self.failure:
            raise LimitExceeded(self.failure)
        if self.elapsed >= self.max_seconds:
            self.stop("Wall-clock limit exhausted")

    def __getattr__(self, name):
        target = getattr(self.provider, name)
        if callable(target) and (name in {"generate", "chat"} or name.startswith("generate_")):
            async def counted(*args, **kwargs):
                return await self._call(name, target, args, kwargs)
            return counted
        return target

    async def _call(self, name, target, args, kwargs):
        if not self.slot.acquire(blocking=False):
            raise RuntimeError("Concurrent inference refused")
        record = None
        try:
            self.check()
            if self.count >= self.max_invocations:
                self.stop(f"Invocation cap {self.max_invocations} exhausted before next call")
            prompt = "".join(str(v) for v in args) + "".join(
                str(kwargs.get(k, "")) for k in ("system", "user", "messages"))
            record = {"index": self.count + 1, "method": name, **self.context,
                      "latency_seconds": None, "prompt_chars": len(prompt), "completion_chars": 0,
                      "prompt_tokens": None, "completion_tokens": None,
                      "usage_estimated": True, "usage_unit": "characters", "error": None}
            self.calls.append(record)
            started = self.clock()
            self.on_update()  # Checkpoint the dispatch even if the watchdog kills it.
            try:
                result = await asyncio.wait_for(target(*args, **kwargs),
                                                timeout=self.max_seconds - self.elapsed)
            except asyncio.TimeoutError:
                self.stop("Wall-clock limit reached during model call")
            record["completion_chars"] = len(_field(result, "text", ""))
            usage = _field(result, "usage")
            inp = _field(usage, "input_tokens", _field(usage, "prompt_tokens"))
            output = _field(usage, "output_tokens", _field(usage, "completion_tokens"))
            if (getattr(self.provider, "name", "") != "fake"
                    and type(inp) is int and type(output) is int and inp + output > 0):
                record.update(prompt_tokens=inp, completion_tokens=output,
                              usage_estimated=False, usage_unit="tokens")
            self.check()
            return result
        except BaseException as exc:
            if record is not None:
                record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            try:
                if record is not None:
                    record["latency_seconds"] = max(0.0, self.clock() - started)
                    self.on_update()
            finally:
                self.slot.release()

    def snapshot(self):
        times = [r["latency_seconds"] for r in self.calls if r["latency_seconds"] is not None]
        return {
            "total_calls": self.count, "embedding_calls": len(self.embedding_calls),
            "calls": deepcopy(self.calls), "embeddings": deepcopy(self.embedding_calls),
            "latency_seconds": {"min": min(times) if times else None,
                                "median": median(times) if times else None,
                                "max": max(times) if times else None},
            "usage": {"prompt_tokens": sum(r["prompt_tokens"] or 0 for r in self.calls),
                      "completion_tokens": sum(r["completion_tokens"] or 0 for r in self.calls),
                      "prompt_chars": sum(r["prompt_chars"] for r in self.calls),
                      "completion_chars": sum(r["completion_chars"] for r in self.calls),
                      "estimated_calls": sum(r["usage_estimated"] for r in self.calls),
                      "note": "Character counts are estimates, not measured tokens; fake usage is estimated."},
            "wall_seconds": self.elapsed,
        }


class CountingEmbedder:
    def __init__(self, embedder, counter):
        self.embedder, self.counter = embedder, counter
        self.dimension, self.version = embedder.dimension, embedder.version

    def embed(self, text):
        counter = self.counter
        counter.check()
        started = counter.clock()
        record = {**counter.context, "input_chars": len(text), "usage_estimated": True,
                  "latency_seconds": None, "error": None}
        counter.embedding_calls.append(record)
        counter.on_update()
        try:
            embedder = self.embedder
            # OllamaEmbedder is synchronous: bound its HTTP timeout by remaining time.
            from app.retrieval.embeddings import OllamaEmbedder
            if isinstance(embedder, OllamaEmbedder):
                embedder = replace(embedder, timeout=min(embedder.timeout,
                                   counter.max_seconds - counter.elapsed))
            result = embedder.embed(text)
            counter.check()
            return result
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["latency_seconds"] = max(0.0, counter.clock() - started)
            counter.on_update()


def empty_result(corpus, *, dry_run, max_invocations, max_minutes, baseline_only=False):
    names = ("A",) if baseline_only else ("A", "B0", "B", "C")
    condition_map = {name: {"condition": name, "rows": [
        {"requirement_id": r["id"], "expected": r["expected"], "predicted": "UNDETERMINED",
         "expected_locators": r["expected_locators"], "cited_locators": [], "completed": False}
        for r in corpus["requirements"]]} for name in names}
    return {
        "schema_version": 1, "corpus_id": corpus["id"], "dry_run": dry_run,
        "config_hash": config_hash({"conditions": {name: CONDITION_FLAG_MAP[name]
            for name in names}, "dry_run": dry_run, "max_invocations": max_invocations,
            "max_minutes": max_minutes, "baseline_only": baseline_only}),
        "mode": "baseline-only" if baseline_only else "full",
        "partial": True, "stop_reason": "Experiment has not completed", "errors": [],
        "total_calls": 0, "embedding_calls": 0, "calls": [], "embeddings": [],
        "latency_seconds": {"min": None, "median": None, "max": None},
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "prompt_chars": 0,
                  "completion_chars": 0, "estimated_calls": 0}, "wall_seconds": 0,
        "limits": {"max_invocations": max_invocations, "max_seconds": max_minutes * 60,
                   "max_concurrent_inferences": 1},
        "limitations": LIMITATIONS, "grounded_runs": [], "conditions": condition_map,
    }


def markdown(result):
    lines = ["# Real-model review experiment", "", f'Config hash: {result["config_hash"]}', "",
             f"Mode: {result.get('mode', 'full')}", "", result["limitations"], "",
             f"Dry run: {result['dry_run']}; partial: {result['partial']}; stop: {result['stop_reason']}",
             "", "| Condition | Accuracy | False-DEVIATES | Evidence hit |", "|---|---|---|---|"]
    def rate(value):
        return f"{value['numerator']}/{value['denominator']}"
    for name, condition in result["conditions"].items():
        m = condition["metrics"]
        lines.append(f"| {condition['condition']} | {rate(m['exact_match_accuracy'])} | "
                     f"{rate(m['false_deviates_rate'])} | {rate(m['evidence_hit_rate'])} |")
    lines.extend(["", "Counts below are experiment-wide; B0/B/C calls are shared, not added three times.",
                  "", f"Total calls: {result.get('total_calls', 0)}; embeddings: {result.get('embedding_calls', 0)}; "
                  f"wall seconds: {result.get('wall_seconds', 0):.3f}", ""])
    for key in ("latency_seconds", "usage", "errors", "grounded_runs"):
        lines.extend([f"{key}: {json.dumps(result.get(key), ensure_ascii=False)}", ""])
    for name, condition in result["conditions"].items():
        lines.extend([f"{name} per-verdict confusion: "
                      f"{json.dumps(condition['metrics']['confusion_matrix'])}", ""])
    lines.extend(["Per-call accounting:", "", "```json",
                  json.dumps(result.get("calls", []), ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def write_report(result, out):
    out = validate_output(out)
    out.mkdir(parents=True, exist_ok=True)
    for condition in result["conditions"].values():
        condition["metrics"] = score(condition["rows"])
    # Atomic checkpoint: a watchdog always sees either the old or new JSON.
    target = out / "experiment_real.json"
    pending = out / "experiment_real.json.tmp"
    pending.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(target)
    (out / "experiment_real.md").write_text(markdown(result), encoding="utf-8")


async def run_experiment(*, out, qdrant_dir=None, real=False, dry_run=False,
                         max_invocations=24, max_minutes=60, provider=None, baseline_only=False,
                         clock=monotonic, scratch_dir=None, corpus_path=CORPUS):
    """Build/index once. Tests use dry_run, tmp_path scratch and memory vectors.

    The CLI adds a killable-process deadline for synchronous or stalled work.
    Application providers are injected only during this serial experiment.
    """
    authorize(real=real, dry_run=dry_run)
    validate_limits(max_invocations, max_minutes)
    out = validate_output(out)
    if qdrant_dir is not None:
        qdrant_dir = validate_qdrant_dir(qdrant_dir)
    elif not dry_run and not baseline_only:
        raise ValueError("Real experiments require qdrant-dir")
    corpus = load_corpus(corpus_path)
    result = empty_result(corpus, dry_run=dry_run, max_invocations=max_invocations,
                          max_minutes=max_minutes, baseline_only=baseline_only)
    write_report(result, out)
    # Never load a repository .env, including on first import of RuntimeConfig.
    with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
        from app.providers.factory import get_provider
        provider = provider or get_provider("fake" if dry_run else None)
        if dry_run and provider.name != "fake":
            raise PermissionError("Dry-run accepts fake providers only")
        if not dry_run and provider.name == "fake":
            raise ValueError("Real experiment requires PROVIDER=ollama (or local)")
        counter = CountingProvider(provider, max_invocations, max_minutes * 60, clock=clock)
        result.update(provider=provider.name, model=provider.model)

        def checkpoint():
            result.update(counter.snapshot())
            write_report(result, out)

        counter.on_update = checkpoint
        vector_store = None
        try:
            if baseline_only:
                for pos, requirement in enumerate(corpus["requirements"]):
                    counter.check()
                    counter.context = {"stage": "baseline", "requirement_id": requirement["id"]}
                    baseline = await counter.generate(system=BASELINE_SYSTEM, user=requirement["text"])
                    predicted = parse_baseline(baseline.text)
                    result["conditions"]["A"]["rows"][pos].update(
                        predicted=predicted, completed=True, raw_output=baseline.text)
                    if predicted == "UNDETERMINED":
                        result["errors"].append({**counter.context,
                            "error": f"Unparseable baseline output: {baseline.text[:200]}"})
                    checkpoint()
                counter.check()
                result.update(partial=False, stop_reason=None)
                return result

            from app.research import pipeline as pipeline_module
            from app.retrieval.candidate_index import CandidateIndex
            from app.retrieval.embeddings import LocalHashEmbedder, make_embedder
            from app.review_adapters.pipeline_engine import PipelineReviewEngine
            from app.review_adapters.verdict_rules import assess
            from app.review.schemas import ReviewCase
            from app.review.service import review_route_decision
            from app.review.memory.recall import recall
            from app.review.memory.store import InMemoryMemoryStore
            from app.orchestration.budget import BudgetCost, BudgetManager
            from app.storage.source_store import SourceStore
            from app.storage.run_store import RunStore
            from app.storage.vector_store import InMemoryVectorStore, QdrantVectorStore

            # An injected pytest tmp_path is already isolated and managed by pytest.
            scratch_context = (nullcontext(str(scratch_dir)) if scratch_dir is not None else
                               tempfile.TemporaryDirectory(prefix="real-exp-"))
            with scratch_context as scratch:
                sources = SourceStore(str(Path(scratch) / "sources"))
                source = corpus["source"]
                imported = sources.import_text(source["name"], source["text"],
                                               provenance={"locator": source["locator"]})
                dimension = int(os.getenv("VECTOR_SIZE", "768"))
                embedder = LocalHashEmbedder(dimension) if dry_run else make_embedder(dimension)
                result["embedding_version"] = embedder.version
                vector_store = (InMemoryVectorStore(vector_size=dimension) if dry_run else
                                QdrantVectorStore(path=str(qdrant_dir), collection="real_exp_test",
                                                  vector_size=dimension))
                index = CandidateIndex(sources, vector_store, owner_user_id="test-experiment",
                                       embedder=CountingEmbedder(embedder, counter))
                counter.context = {"stage": "index"}
                counter.check()
                result["index"] = index.index_source(imported["source_id"])
                pipeline = pipeline_module.ResearchPipeline(
                    sources, RunStore(str(Path(scratch) / "outputs")), candidate_index=index,
                    retrieval_backend="memory" if dry_run else "qdrant")
                adapter = PipelineReviewEngine(pipeline)
                now = datetime(2026, 1, 1, tzinfo=timezone.utc)
                case = ReviewCase(id=corpus["id"], owner_user_id="test-experiment", title="Test policy",
                                  request_text="\n".join(r["text"] for r in corpus["requirements"]),
                                  source_ids=[imported["source_id"]], created_at=now, updated_at=now)
                result["c_switches"] = {"router": review_route_decision(case, 6),
                                        "budget": "six requirement reservations; nonbinding token budget",
                                        "memory": "empty isolated test memory; suggestions only",
                                        "changes_outcome": False}
                budget = BudgetManager(2**63 - 1, max_minutes * 60, 6, clock=clock)
                memory = InMemoryMemoryStore()
                with patch.object(pipeline_module, "get_provider", return_value=counter):
                    for pos, requirement in enumerate(corpus["requirements"]):
                        counter.check()
                        counter.context = {"stage": "grounded", "requirement_id": requirement["id"]}
                        before = counter.count
                        cost = BudgetCost(tokens=max(1, (len(requirement["text"]) + 2) // 3))
                        c_skip = budget.should_skip(cost).skip
                        if not c_skip:
                            budget.reserve("requirements", cost.tokens)
                        raw = await pipeline.run(requirement["text"], source_ids=case.source_ids)
                        counter.check()  # Pipeline may catch a provider LimitExceeded.
                        evidence = adapter._evidence(pipeline, raw, case.source_ids)
                        status = raw.get("status")
                        legacy = {"COMPLETE": "SATISFIED" if evidence else "UNDETERMINED",
                                  "PARTIAL": "PARTIAL", "NO_EVIDENCE": "NOT_FOUND"}.get(status, "UNDETERMINED")
                        ruled, ruled_evidence = legacy, evidence
                        if status in {"COMPLETE", "PARTIAL"} and any(e.excerpt for e in evidence):
                            assessment = assess(requirement["text"], evidence)
                            if assessment.conflicting:
                                ruled = "DEVIATES"
                                ruled_evidence = list(assessment.conflicting)
                                ruled_evidence.extend(e for e in assessment.supporting if e not in ruled_evidence)
                        for name, verdict, cited in (("B0", legacy, evidence), ("B", ruled, ruled_evidence),
                                                    ("C", "SKIPPED_BUDGET" if c_skip else ruled,
                                                     [] if c_skip else ruled_evidence)):
                            row = result["conditions"][name]["rows"][pos]
                            row.update(predicted=verdict, cited_locators=[e.locator for e in cited],
                                       completed=True, raw_status=status)
                        suggestions = recall(memory, case.owner_user_id, case.id, requirement["text"])
                        result["conditions"]["C"]["rows"][pos]["memory_suggestions"] = len(suggestions)
                        result["c_switches"]["changes_outcome"] |= c_skip
                        result["grounded_runs"].append({"requirement_id": requirement["id"],
                            "calls": counter.count - before, "raw_status": status,
                            "evidence": [e.model_dump(mode="json") for e in evidence],
                            "task_results": raw.get("task_results", [])})
                        if status == "FAILED":
                            result["errors"].append({"stage": "grounded", "requirement_id": requirement["id"],
                                                      "error": raw.get("answer", "Pipeline failed")})
                        checkpoint()
                        counter.context = {"stage": "baseline", "requirement_id": requirement["id"]}
                        baseline = await counter.generate(system=BASELINE_SYSTEM, user=requirement["text"])
                        predicted = parse_baseline(baseline.text)
                        result["conditions"]["A"]["rows"][pos].update(
                            predicted=predicted, completed=True, raw_output=baseline.text)
                        if predicted == "UNDETERMINED":
                            result["errors"].append({**counter.context,
                                "error": f"Unparseable baseline output: {baseline.text[:200]}"})
                        checkpoint()
                counter.check()
                result.update(partial=False, stop_reason=None)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {counter.failure or exc}"
            result.update(partial=True, stop_reason=reason)
            result["errors"].append({**counter.context, "error": reason})
        finally:
            if vector_store is not None and not dry_run:
                vector_store.client.close()
            checkpoint()
    return result


def mark_watchdog_timeout(out, *, seconds, dry_run=False, max_invocations=24):
    """Finalize the last atomic worker checkpoint without invoking any model."""
    out = validate_output(out)
    path = out / "experiment_real.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_result(
        load_corpus(), dry_run=dry_run, max_invocations=max_invocations, max_minutes=seconds / 60)
    reason = "LimitExceeded: process watchdog wall-clock limit"
    result.update(partial=True, stop_reason=reason, wall_seconds=seconds)
    result["errors"].append({"stage": "watchdog", "error": reason})
    for call in result.get("calls", []):
        if call["latency_seconds"] is None:
            call["error"] = "Watchdog stopped process before response; latency and usage unavailable"
    write_report(result, out)
    return result
