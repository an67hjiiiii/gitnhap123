import asyncio
import json

import pytest

from app.core.types import ProviderResult, RunMetrics, SourceChunk, Task, TaskResult, Usage
from app.research.pipeline import ResearchPipeline
from app.research.synthesizer import synthesize
from app.research.worker import execute_task
from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import LocalHashEmbedder
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore


class PlanningProvider:
    name = "fake"
    model = "planning-wl"

    def __init__(self, failure=None):
        self.failure = failure
        self.plan_calls = 0

    async def generate(self, *, system, user):
        if "OBLIGATION_CONCERN_EXTRACTOR" in system:
            obligations = ([{"obligation_id": "O1", "description": "Review authentication", "required": True}]
                           if self.failure == "semantic" else [])
            text = json.dumps({"obligations": obligations, "concerns": []})
        elif "TASK_PLAN_BUILDER" in system:
            self.plan_calls += 1
            if self.failure == "exception":
                raise RuntimeError("planner unavailable")
            if self.failure == "json":
                return ProviderResult("not valid JSON", Usage(3, 2))
            tasks = [
                {"task_id": "T1", "goal": "Review authentication", "domain": "security",
                 "depends_on": [], "evidence_needs": ["authentication"]},
                {"task_id": "T2", "goal": "Review database query", "domain": "database",
                 "depends_on": [], "evidence_needs": ["database query"]},
            ]
            if self.failure == "semantic":
                tasks = [dict(tasks[1], task_id="T1", covers_obligations=["O1"], covers_concerns=[])]
            text = json.dumps({"tasks": tasks})
        elif "SYNTHESIZER" in system:
            text = "Đã tổng hợp các kết quả."
        else:
            text = "{}"  # Optional multi-query generation may fall back to the original query.
        return ProviderResult(text, Usage(3, 2))

    async def generate_grounded(self, *, system, user, evidence_ids):
        return ProviderResult(json.dumps({
            "status": "COMPLETE", "answer": f"Grounded answer [{evidence_ids[0]}]",
            "citations": evidence_ids[:1], "missing_information": [],
        }), Usage(7, 5))


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "dev")
    monkeypatch.setenv("MIN_RETRIEVAL_SCORE", "0")
    monkeypatch.setenv("MAX_RUN_TOKENS", "12000")
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "700")


def run_plan(tmp_path, monkeypatch, provider):
    monkeypatch.setattr("app.research.pipeline.get_provider", lambda name=None: provider)
    store = SourceStore(str(tmp_path / "sources"))
    store.import_text("Guide.md", "Review authentication and database query requirements.")
    index = CandidateIndex(None, InMemoryVectorStore(), owner_user_id="owner", embedder=LocalHashEmbedder())
    pipeline = ResearchPipeline(store, RunStore(str(tmp_path / "run-store")), candidate_index=index)
    return asyncio.run(pipeline.run(
        "Review authentication and database query", "C", provider_name="fake",
        product_mode=True, force_plan=True,
    ))


# "semantic" left this list on purpose: plan_anchoring now repairs a semantic gap, so that case ends COMPLETE
# (see test_anchoring_repairs_semantic_gap_and_completes). Plans that cannot be repaired still degrade here / in
# test_unanchorable_plan_still_degrades.
@pytest.mark.parametrize("failure", ["json", "exception", "normalization"])
def test_planning_failure_degrades_after_one_repair(tmp_path, monkeypatch, failure):
    provider = PlanningProvider(failure)
    if failure == "normalization":
        monkeypatch.setattr("app.research.pipeline.normalize_tasks", lambda tasks: ([], len(tasks)))
    run = run_plan(tmp_path, monkeypatch, provider)
    assert run["status"] == "PARTIAL"
    assert run["lifecycle_status"] == "COMPLETED"
    assert run["answer"]
    assert provider.plan_calls == 2
    repairs = [event for event in run["events"] if event["stage"] == "planning_repair"]
    assert len(repairs) == 1
    assert repairs[0]["attempt"] == 1
    degraded = [event for event in run["events"] if event["stage"] == "planning_degraded"]
    assert len(degraded) == 1
    assert degraded[0]["fallback"] == "C_MULTI"
    assert degraded[0]["reason"]
    assert degraded[0]["errors"]
    assert "kế hoạch phân tích không hợp lệ, đã chuyển sang trả lời trực tiếp" in run["task_results"][0]["missing_information"]
    assert not any(event["stage"] == "run_failed" for event in run["events"])
    assert {"run_id", "status", "answer", "tasks", "task_results", "metrics", "events", "provenance"} <= run.keys()


def test_two_task_run_serializes_metrics(tmp_path, monkeypatch):
    run = run_plan(tmp_path, monkeypatch, PlanningProvider())
    assert run["status"] == "COMPLETE"
    assert len(run["task_results"]) == 2
    for task in run["task_results"]:
        assert set(task["metrics"]) == {
            "input_tokens", "output_tokens", "latency_ms", "valid_citations",
            "invalid_citations", "retrieved_chunks",
        }
        assert all(type(value) is int and value >= 0 for value in task["metrics"].values())
        assert task["metrics"]["valid_citations"] == len(task["citations"])
        assert task["metrics"]["retrieved_chunks"] >= len(task["evidence_ids"])
    for key in ("input_tokens", "output_tokens"):
        assert sum(task["metrics"][key] for task in run["task_results"]) <= run["metrics"][key]


class SummaryProvider:
    def __init__(self, text="Đã xác nhận [a]; thiếu dữ liệu [unknown].", *, fail=False, output_tokens=8):
        self.text, self.fail, self.output_tokens = text, fail, output_tokens
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("summary unavailable")
        return ProviderResult(self.text, Usage(5, self.output_tokens))


@pytest.mark.parametrize("fail", [False, True])
def test_synthesis_preserves_task_answers_and_missing_guidance(fail):
    results = [
        TaskResult("T2", "security", "COMPLETE", "Exact answer [a].\nNguồn: [a]  \n", citations=["a"]),
        TaskResult("T1", "database", "NO_EVIDENCE", "Exact missing answer [b].", citations=["b"],
                   missing_information=["giới hạn tải tệp"]),
    ]
    provider = SummaryProvider(fail=fail)
    answer = asyncio.run(synthesize(provider, "question", results, RunMetrics()))
    assert provider.calls == 1
    assert answer.index("**Bảo mật**") < answer.index("**Cơ sở dữ liệu**")
    for result in results:
        assert result.answer in answer
        for cid in result.citations:
            assert f"[{cid}]" in answer
    assert "Mình chưa tìm thấy giới hạn tải tệp. Bạn hãy tải thêm tài liệu liên quan đến phần này." in answer
    assert "[unknown]" not in answer
    assert ("**Tóm tắt**" in answer) is not fail


def test_synthesis_groups_repeated_domains_in_first_seen_order():
    results = [
        TaskResult("T3", "security", "COMPLETE", "first"),
        TaskResult("T1", "database", "COMPLETE", "second"),
        TaskResult("T2", "security", "COMPLETE", "third"),
    ]
    answer = asyncio.run(synthesize(SummaryProvider(fail=True), "question", results, RunMetrics()))
    assert answer == "**Bảo mật**\nfirst\n\nthird\n\n**Cơ sở dữ liệu**\nsecond"


@pytest.mark.parametrize("output_tokens,text", [(161, "short"), (1, "word " * 61)])
def test_synthesis_omits_summary_exceeding_budget(output_tokens, text):
    result = TaskResult("T1", "database", "COMPLETE", "Original answer")
    provider = SummaryProvider(text, output_tokens=output_tokens)
    answer = asyncio.run(synthesize(provider, "question", [result], RunMetrics()))
    assert answer == "**Cơ sở dữ liệu**\nOriginal answer"
    assert provider.calls == 1


def test_synthesis_skips_summary_after_run_budget_exhausted():
    provider = SummaryProvider()
    answer = asyncio.run(synthesize(provider, "question", [TaskResult("T1", "database", "COMPLETE", "Answer")],
                                    RunMetrics(input_tokens=12000)))
    assert answer == "**Cơ sở dữ liệu**\nAnswer"
    assert provider.calls == 0


def test_worker_metrics_count_invalid_citations_and_no_evidence():
    class WorkerProvider:
        async def generate(self, **kwargs):
            return ProviderResult(json.dumps({"status": "COMPLETE", "answer": "Answer",
                                               "citations": ["a", "unknown"]}), Usage(7, 3))

    task = Task("T1", "Review authentication", "security")
    metrics = RunMetrics()
    result = asyncio.run(execute_task(WorkerProvider(), task, [SourceChunk("a", "s", "S", "Text", 0)], metrics))
    assert result.metrics["valid_citations"] == len(result.citations) == 1
    assert result.metrics["invalid_citations"] == 1
    assert result.metrics["input_tokens"] == metrics.input_tokens == 7
    assert result.metrics["output_tokens"] == metrics.output_tokens == 3
    empty = asyncio.run(execute_task(WorkerProvider(), task, [], metrics))
    assert empty.status == "NO_EVIDENCE"
    assert all(value == 0 for key, value in empty.metrics.items() if key != "latency_ms")
    assert empty.metrics["latency_ms"] >= 0


def test_worker_latency_measures_the_worker_call(monkeypatch):
    ticks = iter([10.0, 10.125])
    monkeypatch.setattr("app.research.worker.time.perf_counter", lambda: next(ticks))
    result = asyncio.run(execute_task(
        PlanningProvider(), Task("T1", "Review authentication", "security"),
        [SourceChunk("a", "s", "S", "Text", 0)], RunMetrics(),
    ))
    assert result.metrics["latency_ms"] == 125


def test_summary_uses_standard_generate_signature_even_with_structured_token_support():
    class StandardProvider:
        supports_per_call_output_tokens = True

        async def generate(self, *, system, user):
            return ProviderResult("Short summary", Usage(2, 2))

    answer = asyncio.run(synthesize(StandardProvider(), "question", [
        TaskResult("T1", "database", "COMPLETE", "Answer")], RunMetrics()))
    assert answer.endswith("**Tóm tắt**\nShort summary")

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _always_summarise(monkeypatch):
    """These tests exercise the summary call itself; production skips it for short/single-domain bodies."""
    monkeypatch.setenv("SYNTH_MIN_BODY_CHARS", "0")


def test_anchoring_repairs_semantic_gap_and_completes(tmp_path, monkeypatch):
    provider = PlanningProvider("semantic")
    run = run_plan(tmp_path, monkeypatch, provider)

    assert run["status"] == "COMPLETE"
    anchors = [event for event in run["events"] if event["stage"] == "plan_anchoring"]
    assert len(anchors) == 1
    assert anchors[0]["accepted"] is True
    assert anchors[0]["changes"]
    assert not any(event["stage"] == "planning_degraded" for event in run["events"])
    assert not any(event["stage"] == "run_failed" for event in run["events"])
    assert run["answer"]
    assert any("Review authentication" in task["goal"] for task in run["tasks"])


def test_unanchorable_plan_still_degrades(tmp_path, monkeypatch):
    """When anchoring cannot repair the plan (here: anchoring is a no-op), the run still degrades after one repair."""
    from app.research import pipeline as pipeline_module
    from app.research.plan_verification import verify_task_plan

    monkeypatch.setattr(pipeline_module, "anchor_and_verify", lambda plan: (plan, verify_task_plan(plan), []))
    provider = PlanningProvider("semantic")
    run = run_plan(tmp_path, monkeypatch, provider)

    assert run["status"] == "PARTIAL"
    assert run["lifecycle_status"] == "COMPLETED"
    assert run["answer"]
    assert provider.plan_calls == 2
    repairs = [event for event in run["events"] if event["stage"] == "planning_repair"]
    assert len(repairs) == 1
    assert repairs[0]["attempt"] == 1
    degraded = [event for event in run["events"] if event["stage"] == "planning_degraded"]
    assert len(degraded) == 1
    assert degraded[0]["fallback"] == "C_MULTI"
    assert degraded[0]["reason"]
    assert degraded[0]["errors"]
    anchors = [event for event in run["events"] if event["stage"] == "plan_anchoring"]
    assert anchors and all(event["accepted"] is False for event in anchors)
    assert "kế hoạch phân tích không hợp lệ, đã chuyển sang trả lời trực tiếp" in run["task_results"][0]["missing_information"]
    assert not any(event["stage"] == "run_failed" for event in run["events"])
    assert {"run_id", "status", "answer", "tasks", "task_results", "metrics", "events", "provenance"} <= run.keys()


def test_anchor_and_verify_repairs_required_obligation_text():
    from app.core.types import Obligation, TaskPlan
    from app.research.plan_anchoring import anchor_and_verify

    plan = TaskPlan(
        request="Review authentication",
        obligations=[Obligation("O1", "Review authentication", required=True)],
        tasks=[Task("T1", "Review database query", "security", covers_obligations=["O1"])],
    )

    anchored, verification, changes = anchor_and_verify(plan)

    assert verification.valid is True
    assert verification.errors == ()
    assert verification.covered_obligations == ("O1",)
    assert changes
    assert "Review authentication" in anchored.tasks[0].goal
    assert anchored.tasks[0].covers_obligations == ["O1"]
    assert plan.tasks[0].goal == "Review database query"


def test_anchor_and_verify_preserves_unknown_obligation_error():
    from app.core.types import Obligation, TaskPlan
    from app.research.plan_anchoring import anchor_and_verify

    plan = TaskPlan(
        request="Review authentication",
        obligations=[Obligation("O1", "Review authentication", required=True)],
        tasks=[Task("T1", "Review database query", "security",
                    covers_obligations=["O1", "O_UNKNOWN"])],
    )

    anchored, verification, changes = anchor_and_verify(plan)

    assert verification.valid is False
    assert verification.errors == ("task T1 references unknown obligation O_UNKNOWN",)
    assert changes
    assert "Review authentication" in anchored.tasks[0].goal
    assert anchored.tasks[0].covers_obligations == ["O1", "O_UNKNOWN"]
