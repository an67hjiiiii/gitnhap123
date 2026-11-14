"""Durability and HTTP replay without external providers or a process kill."""

import hashlib
import importlib.util
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import dotenv
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.jobs import format_sse
from app.review.engine import FakeReviewEngine
from app.review.schemas import Finding, JobState, Requirement
from app.review.service import ReviewCaseService
from app.review_adapters.durable_jobs import DurableJobRunner
from app.review_adapters.pg_repository import PostgresCaseRepository
from app.storage.postgres.base import Base
from app.storage.postgres.review_models import ReviewCaseRecord


NOW = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)
TABLES = [table for table in Base.metadata.sorted_tables if table.name.startswith("review_")]


class Crash(BaseException):
    """Leave the job leased, as a killed process would."""


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class Engine:
    def __init__(self, calls, crash_on=None):
        self.calls, self.crash_on = calls, crash_on

    def run(self, case, requirements, budget, emit):
        requirement, = requirements
        self.calls.append((requirement.id, dict(budget or {})))
        if requirement.order == self.crash_on:
            raise Crash()
        verdict = "SKIPPED_BUDGET" if (budget or {}).get("max_requirements") == 0 else "SATISFIED"
        finding = Finding(id=f"f-{requirement.id}", case_id=case.id,
                          requirement_id=requirement.id, verdict=verdict, confidence="L1")
        emit(finding)
        return [finding]


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch, sf1_vector_store):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    monkeypatch.setenv("REVIEW_ENGINE", "pipeline")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)


@pytest.fixture
def database(request):
    backend = getattr(request, "param", "memory")
    postgres = backend == "postgres"
    if postgres:
        url = os.environ["TEST_DATABASE_URL"]
    elif backend == "sqlite":
        tmp_path = request.getfixturevalue("tmp_path")
        url = f"sqlite+pysqlite:///{tmp_path / 'review.sqlite'}"
    else:
        url = "sqlite+pysqlite:///:memory:"
    digest = hashlib.sha256(f"{request.node.nodeid}:{os.getpid()}".encode()).hexdigest()[:16]
    owner = f"durable-{digest}"
    engines = []

    def connect():
        if backend == "memory" and engines:
            return sessionmaker(engines[0], expire_on_commit=False)
        options = {} if postgres else {"connect_args": {"check_same_thread": False}}
        if backend == "memory":
            options["poolclass"] = StaticPool
        engine = create_engine(url, **options)
        engines.append(engine)
        Base.metadata.create_all(engine, tables=TABLES)
        return sessionmaker(engine, expire_on_commit=False)

    factory = connect()
    yield SimpleNamespace(factory=factory, connect=connect, owner=owner, engines=engines, backend=backend)
    with factory.begin() as db:
        # Only this test's rows; never drop shared tables or unrelated owners.
        from app.storage.postgres.review_models import (
            ReviewFindingRecord, ReviewRequirementRecord, ReviewRunEventRecord, ReviewRunJobRecord,
        )
        from sqlalchemy import select
        ids = select(ReviewRunJobRecord.id).where(ReviewRunJobRecord.owner_user_id == owner)
        db.execute(delete(ReviewRunEventRecord).where(ReviewRunEventRecord.job_id.in_(ids)))
        for model in (ReviewRunJobRecord, ReviewFindingRecord, ReviewRequirementRecord, ReviewCaseRecord):
            db.execute(delete(model).where(model.owner_user_id == owner))
    for engine in engines:
        engine.dispose()


def seed(database, count=3):
    repo = PostgresCaseRepository(database.factory, database.owner)
    service = ReviewCaseService(repo, None, clock=lambda: NOW,
                                id_factory=lambda: f"case-{database.owner}")
    case = service.create_case(database.owner, "Audit", "Review requirements")
    requirements = [Requirement(id=f"{case.id}:r{i}", case_id=case.id, text=f"Check {i}",
                                origin="USER", confirmed=True, order=i) for i in range(count)]
    repo.save_requirements(database.owner, case.id, requirements)
    return repo, case, requirements


def runner_for(repo, engine, clock, worker="worker"):
    def work(job_id, run, emit, cancelled):
        service = ReviewCaseService(repo, engine, clock=clock)
        findings = service.start_run(
            run["case_id"], run["owner"], run["budget"], job_id=job_id,
            attempt=run["attempt"], cancelled=cancelled,
            checkpoint=lambda finding: runner.checkpoint(job_id, finding),
            emit=lambda finding: emit("task.done", {"requirement_id": finding.requirement_id}),
        )
        requirements = repo.get_requirements(run["owner"], run["case_id"])
        return JobState.SUCCEEDED if service.is_complete(requirements, findings) else JobState.PARTIAL

    runner = DurableJobRunner(repo, work, worker, 10, clock)
    return runner


DATABASES = ["memory", "sqlite", pytest.param("postgres", marks=pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"))]


@pytest.mark.parametrize("database", DATABASES, indirect=True)
@pytest.mark.parametrize("budget,crash_on", [(None, 1), ({"max_requirements": 2}, 1),
                                           ({"max_requirements": 1}, 2)])
def test_crash_resume_preserves_findings_budget_and_sse(database, budget, crash_on):
    repo, case, requirements = seed(database)
    clock, calls = Clock(), []
    first = runner_for(repo, Engine(calls, crash_on=crash_on), clock)
    try:
        job_id = first.submit({"owner": database.owner, "case_id": case.id, "budget": budget})
        with pytest.raises(Crash):
            first._futures[0].result(timeout=5)
        original = repo.get_findings(database.owner, case.id)
        assert [item.requirement_id for item in original] == [item.id for item in requirements[:crash_on]]
        assert first.status(job_id) == JobState.RUNNING
    finally:
        first.shutdown()
    if database.backend != "memory":
        for engine in database.engines:
            engine.dispose()
    factory = database.connect()
    repo = PostgresCaseRepository(factory, database.owner)
    second = runner_for(repo, Engine(calls), clock, worker="replacement")
    try:
        clock.advance(11)
        assert second.recover(clock()) == [job_id]
        assert second.recover(clock()) == []
        second.start()
        expected = JobState.SUCCEEDED if budget is None else JobState.PARTIAL
        assert second.wait(job_id, timeout=5) == expected
        assert repo.job_record(job_id)["attempt"] == 2
        assert repo.get_case(database.owner, case.id).status.value == (
            "COMPLETE" if budget is None else "PARTIAL")
        findings = repo.get_findings(database.owner, case.id)
        assert findings[:crash_on] == original
        for requirement in requirements[:crash_on]:
            assert [rid for rid, _ in calls].count(requirement.id) == 1
        assert [rid for rid, _ in calls].count(requirements[crash_on].id) == 2
        if budget:
            assert calls[-1][1]["max_requirements"] == 0
            assert findings[-1].verdict.value == "SKIPPED_BUDGET"
        events = second.read_since(job_id, 0)
        assert [event.seq for event in events] == list(range(1, len(events) + 1))
        assert sum(event.type == "job.resumed" for event in events) == 1
        assert events[-1].type == "job.done"
        assert len([event for event in events if event.type == "finding.created"]) == 3

        # A fresh HTTP runtime has no process-local run or event map.
        runtime = ReviewRuntime(storage_backend="postgres", session_factory=factory)
        app = FastAPI()
        app.include_router(build_router(current_user=lambda request: {
            "user_id": request.headers.get("x-user", database.owner),
        }, runtime=runtime))
        with TestClient(app) as client:
            response = client.get(f"/api/review/runs/{job_id}/events", headers={"Last-Event-ID": "2"})
            assert response.text == "".join(format_sse(event) for event in events[2:])
            assert client.get(f"/api/review/runs/{job_id}").json()["state"] == expected.value
            inspector = client.get(f"/api/review/cases/{case.id}/inspector").json()
            assert inspector["run"]["id"] == job_id
            assert inspector["budget"]["given"] == budget
            for path in (f"/runs/{job_id}", f"/runs/{job_id}/events", f"/cases/{case.id}"):
                assert client.get("/api/review" + path, headers={"x-user": "other"}).status_code == 404
            assert client.post(f"/api/review/runs/{job_id}:cancel",
                               headers={"x-user": "other"}).status_code == 404
        runtime.runner.shutdown()
        foreign = PostgresCaseRepository(factory, "other")
        assert foreign.get_job("other", job_id) is None
        assert foreign.read_events(job_id) == []
        with pytest.raises(KeyError):
            foreign.job_record(job_id)
    finally:
        second.shutdown()


def test_attempt_cap_is_atomic_and_idempotent(database):
    repo, case, _ = seed(database)
    clock = Clock()
    runner = DurableJobRunner(repo, lambda *args: None, "worker", 10, clock)
    repo.enqueue_job(database.owner, case.id, "capped", None)
    for attempt in range(1, 4):
        claimed = repo.claim_next_job(f"worker-{attempt}", 10, clock())
        assert claimed["attempt"] == attempt
        clock.advance(11)
        assert runner.recover(clock()) == ["capped"]
        assert runner.recover(clock()) == []
    assert runner.status("capped") == JobState.FAILED
    assert repo.job_record("capped")["error"]
    assert repo.get_case(database.owner, case.id).status.value == "FAILED"
    assert [event.type for event in runner.read_since("capped", 0)] == ["job.failed"]
    assert repo.claim_next_job("new-worker", 10, clock()) is None
    runner.shutdown()


@pytest.mark.parametrize("running", [False, True])
def test_cancellation_survives_restart_and_fences_stale_checkpoint(database, running):
    repo, case, requirements = seed(database)
    clock = Clock()
    repo.enqueue_job(database.owner, case.id, "cancelled", None)
    if running:
        repo.claim_next_job("old-worker", 10, clock(), prepare_case=True)
    runner = runner_for(repo, Engine([]), clock, worker="old-worker")
    runner.cancel("cancelled")
    runner.shutdown()
    fresh = runner_for(PostgresCaseRepository(database.connect(), database.owner), Engine([]), clock)
    try:
        assert fresh.status("cancelled") == JobState.CANCELLED
        finding = Finding(id="stale", case_id=case.id, requirement_id=requirements[0].id,
                          verdict="SATISFIED", confidence="L0")
        assert not repo.checkpoint_finding("cancelled", "old-worker", clock(), finding)
        clock.advance(11)
        assert fresh.recover(clock()) == []
        assert [event.type for event in fresh.read_since("cancelled", 0)] == ["job.cancelled"]
        assert repo.get_findings(database.owner, case.id) == []
        assert not repo.finish_job("cancelled", "old-worker", "SUCCEEDED", clock())
        with pytest.raises(KeyError):
            PostgresCaseRepository(database.factory, "other").cancel_job("cancelled", clock())
    finally:
        fresh.shutdown()


def test_heartbeat_renews_lease_during_work(database, monkeypatch):
    repo, case, _ = seed(database)
    clock = Clock()
    entered, release, renewed = Event(), Event(), Event()
    heartbeat = repo.heartbeat

    def record_heartbeat(*args, **kwargs):
        valid = heartbeat(*args, **kwargs)
        if valid:
            renewed.set()
        return valid

    monkeypatch.setattr(repo, "heartbeat", record_heartbeat)

    def work(*args):
        entered.set()
        assert release.wait(5)

    runner = DurableJobRunner(repo, work, "worker", 1, clock)
    try:
        job_id = runner.submit({"owner": database.owner, "case_id": case.id, "budget": None})
        assert entered.wait(5)
        clock.advance(0.2)
        assert renewed.wait(5)
        assert repo.job_record(job_id)["lease_expires_at"] == clock() + timedelta(seconds=1)
    finally:
        release.set()
        runner.shutdown()
    assert runner.status(job_id) == JobState.SUCCEEDED


def test_main_selects_postgres_review_runtime(database, monkeypatch):
    import app.storage.postgres as postgres
    import app.storage.postgres.runtime as stores

    monkeypatch.setenv("APP_STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(postgres, "create_postgres_engine", lambda: database.engines[0])
    monkeypatch.setattr(postgres, "create_session_factory", lambda engine: database.factory)
    monkeypatch.setattr(stores, "PostgresAuthStore", lambda factory: SimpleNamespace())
    name = "app._durable_review_main"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app" / "main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    assert module.review_runtime.repository.session_factory is module.app.state.session_factory
    assert isinstance(module.review_runtime.runner, DurableJobRunner)
    with TestClient(module.app):
        assert module.review_runtime.runner._executor is not None


@pytest.mark.parametrize("partial", [False, True])
def test_durable_api_submits_one_job_and_keeps_response_shape(database, monkeypatch, partial):
    monkeypatch.setenv("REVIEW_ENGINE", "fake")
    runtime = ReviewRuntime(storage_backend="postgres", session_factory=database.factory)
    app = FastAPI()
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine(skip_budget=partial)
    app.include_router(build_router(current_user=lambda request: {"user_id": database.owner}, runtime=runtime))
    try:
        with TestClient(app) as client:
            created = client.post("/api/review/cases", json={
                "title": "Audit", "request_text": "Check policy. Check approval.",
            })
            assert created.status_code == 201
            case_id = created.json()["id"]
            proposed = client.post(f"/api/review/cases/{case_id}/requirements:propose")
            assert proposed.status_code == 200
            requirements = [{**item, "confirmed": True} for item in proposed.json()]
            assert client.put(f"/api/review/cases/{case_id}/requirements", json={
                "requirements": [{key: value for key, value in item.items()
                                  if key in {"id", "text", "confirmed"}} for item in requirements],
            }).status_code == 200
            submitted = client.post(f"/api/review/cases/{case_id}/runs", json={"budget": {"tasks": 2}})
            assert submitted.status_code == 202
            job_id = submitted.json()["id"]
            expected = JobState.PARTIAL if partial else JobState.SUCCEEDED
            assert runtime.runner.wait(job_id, timeout=5) == expected
            jobs = runtime.repository.get_jobs(database.owner, case_id)
            assert len(jobs) == 1 and jobs[0].id == job_id
            case = client.get(f"/api/review/cases/{case_id}").json()
            assert len({item["id"] for item in case["findings"]}) == 2
            assert case["status"] == ("PARTIAL" if partial else "COMPLETE")
            status = client.get(f"/api/review/runs/{job_id}").json()
            assert set(status) == {"id", "case_id", "state", "seq", "budget", "started_at", "finished_at"}
            assert status["budget"] == {"tasks": 2}
    finally:
        runtime.runner.shutdown()


def test_new_runtime_guards_persisted_active_run(database):
    repo, case, _ = seed(database)
    repo.enqueue_job(database.owner, case.id, "queued", None)
    runtime = ReviewRuntime(storage_backend="postgres", session_factory=database.factory)
    app = FastAPI()
    app.include_router(build_router(current_user=lambda request: {"user_id": database.owner}, runtime=runtime))
    try:
        with TestClient(app) as client:
            response = client.put(f"/api/review/cases/{case.id}/requirements", json={"requirements": []})
            assert response.status_code == 409 and response.json()["code"] == "CASE_RUNNING"
            with pytest.raises(ValueError, match="active run"):
                repo.enqueue_job(database.owner, case.id, "duplicate", None)
    finally:
        runtime.runner.shutdown()


def test_running_work_polls_persisted_cancellation_between_requirements(database):
    repo, case, requirements = seed(database)
    entered, release = Event(), Event()
    calls = []

    class BlockingEngine(Engine):
        def run(self, case, requirements, budget, emit):
            if requirements[0].order == 1:
                entered.set()
                assert release.wait(5)
            return super().run(case, requirements, budget, emit)

    runner = runner_for(repo, BlockingEngine(calls), Clock())
    try:
        job_id = runner.submit({"owner": database.owner, "case_id": case.id, "budget": None})
        assert entered.wait(5)
        runner.cancel(job_id)
    finally:
        release.set()
        runner.shutdown()
    assert runner.status(job_id) == JobState.CANCELLED
    assert [item.requirement_id for item in repo.get_findings(database.owner, case.id)] == [requirements[0].id]
    assert requirements[2].id not in [rid for rid, _ in calls]
    assert runner.read_since(job_id, 0)[-1].type == "job.cancelled"


def test_concurrent_recovery_only_requeues_once(database):
    repo, case, _ = seed(database)
    repo.enqueue_job(database.owner, case.id, "expired", None)
    repo.claim_next_job("lost", 10, NOW)
    barrier = Barrier(2)

    def recover(_):
        local = PostgresCaseRepository(database.factory, database.owner)
        barrier.wait(timeout=5)
        return local.recover_jobs(NOW + timedelta(seconds=11))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(recover, range(2)))
    assert sorted(results, key=len) == [[], ["expired"]]
    assert repo.job_record("expired")["state"] == "QUEUED"


def test_fake_engine_proposals_should_support_multiple_persisted_cases(database):
    ids = iter(["fake-case-1", "fake-case-2"])
    service = ReviewCaseService(PostgresCaseRepository(database.factory), FakeReviewEngine(),
                                clock=lambda: NOW, id_factory=lambda: next(ids))
    for _ in range(2):
        case = service.create_case(database.owner, "Audit", "Check policy.")
        assert len(service.propose_requirements(case.id, database.owner)) == 1
