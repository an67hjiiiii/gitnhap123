"""Timing controls, deterministic lease recovery, and opt-in real process death."""

import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import dotenv
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.review.engine import FakeReviewEngine
from app.review.schemas import Requirement
from app.review.service import ReviewCaseService
from app.review_adapters.durable_jobs import DurableJobRunner
from app.review_adapters.pg_repository import PostgresCaseRepository
from app.storage.postgres.base import Base
from app.storage.postgres.models import SessionRecord, UserRecord
from app.storage.postgres.review_models import (
    ReviewCaseRecord, ReviewFindingRecord, ReviewRequirementRecord,
    ReviewRunEventRecord, ReviewRunJobRecord,
)
from support_kill_restart import ReviewServer, free_port, poll


NOW = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)
REVIEW_TABLES = [table for table in Base.metadata.sorted_tables
                 if table.name.startswith("review_")]


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch, sf1_vector_store):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    for name in ("REVIEW_FAKE_DELAY_MS", "REVIEW_LEASE_SECONDS",
                 "REVIEW_HEARTBEAT_SECONDS", "REVIEW_RECOVER_INTERVAL_SECONDS"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("raw,expected", [
    (None, 0), ("700", 700), ("0.5", 0.5), ("0", 0),
    ("-1", 0), ("invalid", 0), ("nan", 0), ("inf", 0), ("", 0),
])
def test_fake_delay_env_and_per_requirement_sleep(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv("REVIEW_FAKE_DELAY_MS", raw)
    sleeps, emitted = [], []
    monkeypatch.setattr("app.review.engine.sleep", sleeps.append)
    engine = FakeReviewEngine()
    requirements = [Requirement(id=f"r{i}", case_id="case", text="Check", origin="USER",
                                confirmed=True, order=i) for i in range(3)]
    findings = engine.run(SimpleNamespace(id="case"), requirements, None, emitted.append)
    assert engine.delay_ms == expected
    assert sleeps == ([expected / 1000] * 3 if expected else [])
    assert emitted == findings and len(findings) == 3


def test_fake_delay_constructor_overrides_env(monkeypatch):
    monkeypatch.setenv("REVIEW_FAKE_DELAY_MS", "700")
    assert FakeReviewEngine(delay_ms=0).delay_ms == 0
    assert FakeReviewEngine(delay_ms=12).delay_ms == 12
    for invalid in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="delay_ms"):
            FakeReviewEngine(delay_ms=invalid)


@pytest.mark.parametrize("raw", [None, "", "bad", "0", "-1", "nan", "inf"])
def test_durable_timing_safe_defaults(monkeypatch, raw):
    if raw is not None:
        for name in ("REVIEW_LEASE_SECONDS", "REVIEW_HEARTBEAT_SECONDS",
                     "REVIEW_RECOVER_INTERVAL_SECONDS"):
            monkeypatch.setenv(name, raw)
    runner = DurableJobRunner(None, None, "worker", 30, lambda: NOW)
    assert (runner.lease_seconds, runner.heartbeat_seconds,
            runner.recover_interval_seconds) == (30, 10, 5)
    runner.shutdown()


@pytest.mark.parametrize("heartbeat,expected", [("1", 1), ("0.25", 0.25), ("2", 2), ("9", 1)])
def test_durable_timing_env_keeps_heartbeat_within_lease(monkeypatch, heartbeat, expected):
    monkeypatch.setenv("REVIEW_LEASE_SECONDS", "3")
    monkeypatch.setenv("REVIEW_HEARTBEAT_SECONDS", heartbeat)
    monkeypatch.setenv("REVIEW_RECOVER_INTERVAL_SECONDS", "1")
    runner = DurableJobRunner(None, None, "worker", 30, lambda: NOW)
    assert (runner.lease_seconds, runner.heartbeat_seconds,
            runner.recover_interval_seconds) == (3, expected, 1)
    runner.shutdown()


def test_periodic_recovery_retries_after_database_error(monkeypatch, caplog):
    runner = DurableJobRunner(None, None, "worker", 30, lambda: NOW)
    waits, calls = [], []

    def wait(interval):
        waits.append(interval)
        return len(waits) > 2

    def recover(now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("Temporary database outage")

    monkeypatch.setattr(runner, "_stop", SimpleNamespace(wait=wait))
    monkeypatch.setattr(runner, "recover", recover)
    runner._recover_periodically()
    assert waits == [5, 5, 5] and calls == [NOW, NOW]
    assert "Periodic review recovery failed" in caplog.text


def test_periodic_recovery_keeps_renewed_lease_and_recovers_only_expired(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_LEASE_SECONDS", "3")
    monkeypatch.setenv("REVIEW_HEARTBEAT_SECONDS", "1")
    monkeypatch.setenv("REVIEW_RECOVER_INTERVAL_SECONDS", "1")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'review.sqlite'}")
    Base.metadata.create_all(engine, tables=REVIEW_TABLES)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = PostgresCaseRepository(factory, "lease-test")
    clock = SimpleNamespace(now=NOW)
    ids = iter(["alive-case", "dead-case"])
    service = ReviewCaseService(repo, None, clock=lambda: clock.now,
                                id_factory=lambda: next(ids))
    for job_id in ("alive", "dead"):
        case = service.create_case("lease-test", job_id, "Check")
        repo.enqueue_job("lease-test", case.id, job_id, None)
        assert repo.claim_next_job(job_id, 3, clock.now)["id"] == job_id
    runner = DurableJobRunner(repo, None, "alive", 30, lambda: clock.now)
    recovered = []
    recover = runner.recover

    def record_recovery(now):
        result = recover(now)
        recovered.append(result)
        assert repo.job_record("alive")["state"] == "RUNNING"
        assert repo.job_record("alive")["attempt"] == 1
        return result

    class Ticks:
        count = 0

        def wait(self, interval):
            assert interval == 1
            self.count += 1
            if self.count > 4:
                return True
            clock.now += timedelta(seconds=interval)
            assert repo.heartbeat("alive", "alive", runner.lease_seconds, clock.now)
            return False

    try:
        monkeypatch.setattr(runner, "_stop", Ticks())
        monkeypatch.setattr(runner, "recover", record_recovery)
        runner._recover_periodically()
        assert recovered == [[], [], ["dead"], []]
        assert repo.job_record("alive")["state"] == "RUNNING"
        assert repo.job_record("alive")["attempt"] == 1
        assert repo.job_record("alive")["lease_expires_at"] == NOW + timedelta(seconds=7)
        assert repo.job_record("dead")["state"] == "QUEUED"
        clock.now += timedelta(seconds=3)
        assert recover(clock.now) == ["alive"]
        assert recover(clock.now) == []
        assert repo.claim_next_job("replacement", 3, clock.now)["attempt"] == 2
    finally:
        engine.dispose()


def test_main_starts_and_stops_periodic_recovery(tmp_path, monkeypatch):
    import app.storage.postgres as postgres
    import app.storage.postgres.runtime as stores

    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessionmaker(engine)
    monkeypatch.setenv("APP_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "outputs"))
    monkeypatch.setattr(postgres, "create_postgres_engine", lambda: engine)
    monkeypatch.setattr(postgres, "create_session_factory", lambda engine: factory)
    monkeypatch.setattr(stores, "PostgresAuthStore", lambda factory: SimpleNamespace())
    name = "app._kill_restart_main"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app/main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    try:
        spec.loader.exec_module(module)
        runner = module.review_runtime.runner
        calls = []
        monkeypatch.setattr(module.review_runtime, "startup", lambda: calls.append("startup"))
        with TestClient(module.app):
            assert calls == ["startup"]
            thread = runner._recovery_thread
            assert thread is not None and thread.is_alive()
            runner.start_recovery()
            assert runner._recovery_thread is thread
        assert not thread.is_alive()
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL") or os.getenv("RUN_KILL_TEST") != "1",
    reason="Requires PostgreSQL TEST_DATABASE_URL and RUN_KILL_TEST=1; orchestrator only",
)
def test_real_process_kill_restart_preserves_checkpoints(tmp_path):
    deadline = monotonic() + 80
    url = make_url(os.environ["TEST_DATABASE_URL"])
    assert url.get_backend_name() == "postgresql", "Kill test requires PostgreSQL"
    url = url.set(drivername="postgresql+psycopg")
    engine = create_engine(url, connect_args={"connect_timeout": 3}, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    digest = hashlib.sha256(f"{tmp_path}:{os.getpid()}".encode()).hexdigest()[:20]
    username, password = f"kill-{digest}", "Kill-restart-test-2026"
    server = None
    registration_started = False
    try:
        # Authentication tables are needed by the real register/login HTTP flow.
        Base.metadata.create_all(engine, tables=[UserRecord.__table__, SessionRecord.__table__,
                                                 *REVIEW_TABLES])
        port = free_port()
        server = ReviewServer(tmp_path, url.render_as_string(hide_password=False), port)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            server.start(client, deadline)

            def request(method, path, **kwargs):
                return server.request(client, method, path, deadline, **kwargs)

            registration_started = True
            user = request("POST", "/api/auth/register", status=201,
                           json={"username": username, "password": password})["user"]
            login = request("POST", "/api/auth/login",
                            json={"identifier": username, "password": password})
            client.headers["Authorization"] = f"Bearer {login['access_token']}"
            case = request("POST", "/api/review/cases", status=201, json={
                "title": "Kill/restart audit", "request_text": "Check six requirements",
            })
            path = f"/api/review/cases/{case['id']}"
            request("PUT", path + "/requirements", json={"requirements": [
                {"text": f"Check requirement {i + 1}", "confirmed": True} for i in range(6)
            ]})
            requirements = request("GET", path)["requirements"]
            assert len(requirements) == 6 and all(item["confirmed"] for item in requirements)
            job_id = request("POST", path + "/runs", status=202, json={})["id"]
            snapshot = poll(lambda: request("GET", path),
                            lambda value: len(value["findings"]) >= 2, deadline)
            server.kill()
            assert 2 <= len(snapshot["findings"]) < 6, "Must kill an incomplete run"

            def serialized(value):
                return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")

            # Capture all committed rows after death, including any committed during the HTTP poll.
            repo = PostgresCaseRepository(factory, user["user_id"])
            before = {item.id: serialized(item.model_dump(mode="json"))
                      for item in repo.get_findings(user["user_id"], case["id"])}
            assert 2 <= len(before) < 6
            assert repo.job_record(job_id)["state"] == "RUNNING"
            assert repo.job_record(job_id)["attempt"] == 1
            first_pid = server.process.pid
            server.start(client, deadline)
            assert server.process.pid != first_pid
            status = poll(lambda: request("GET", f"/api/review/runs/{job_id}"),
                          lambda value: value["state"] in {
                              "SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}, deadline)
            # No budget and fake SATISFIED verdicts imply a complete successful run.
            assert status["state"] == "SUCCEEDED", status
            after = request("GET", path)["findings"]
            assert len(after) == 6
            assert {item["requirement_id"] for item in after} == {item["id"] for item in requirements}
            assert len({item["id"] for item in after}) == 6
            after_bytes = {item["id"]: serialized(item) for item in after}
            assert all(after_bytes[finding_id] == content for finding_id, content in before.items())
            events = request("GET", path + f"/inspector?run={job_id}")["events"]
            assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
            assert sum(event["type"] == "job.resumed" for event in events) == 1
            created = [event["data"] for event in events if event["type"] == "finding.created"]
            assert len(created) == 6
            assert {item["requirement_id"] for item in created} == {item["id"] for item in requirements}
            assert repo.job_record(job_id)["attempt"] == 2
    finally:
        try:
            if server is not None:
                server.kill()
            if registration_started:
                with factory.begin() as db:
                    owner = db.scalar(select(UserRecord.user_id).where(UserRecord.username == username))
                    if owner is not None:
                        jobs = select(ReviewRunJobRecord.id).where(ReviewRunJobRecord.owner_user_id == owner)
                        db.execute(delete(ReviewRunEventRecord).where(ReviewRunEventRecord.job_id.in_(jobs)))
                        for model in (ReviewRunJobRecord, ReviewFindingRecord,
                                      ReviewRequirementRecord, ReviewCaseRecord):
                            db.execute(delete(model).where(model.owner_user_id == owner))
                        db.execute(delete(SessionRecord).where(SessionRecord.user_id == owner))
                        db.execute(delete(UserRecord).where(UserRecord.user_id == owner))
        finally:
            engine.dispose()
