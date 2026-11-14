"""Review Case HTTP error and lifecycle acceptance scenarios."""

import importlib.util
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import dotenv
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.ratelimit import review_rate_limiter
from app.review.engine import FakeReviewEngine
from app.review.schemas import JobState, Requirement
from app.review.service import ReviewCaseService
from app.review_adapters.durable_jobs import DurableJobRunner
from app.review_adapters.pg_repository import PostgresCaseRepository
from app.storage.postgres.base import Base


@pytest.fixture
def review_http(monkeypatch, tmp_path, sf1_fake_provider_env, sf1_vector_store):
    import app.auth.store as auth_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(auth_module, "AuthStore", lambda *args: SimpleNamespace(
        resolve=lambda token: {"user_id": token, "role": "USER"},
    ))
    for key, value in {
        "APP_STORAGE_BACKEND": "file", "APP_ENV": "test",
        "APP_DATA_DIR": str(tmp_path / "documents"), "RUNS_DIR": str(tmp_path / "outputs"),
        "VECTOR_BACKEND": "memory", "REVIEW_ENGINE": "fake",
        "REVIEW_RATE_RUNS_PER_MIN": "0", "REVIEW_RATE_READS_PER_MIN": "0",
        "REVIEW_RATE_STATUS_PER_MIN": "0",
    }.items():
        monkeypatch.setenv(key, value)
    name = "app._acceptance_review_errors_main"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[2] / "app" / "main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_session_token", lambda request: request.headers.get("x-user", "alice"))
    monkeypatch.setattr(module, "_configured_vector_store", lambda: sf1_vector_store)
    with TestClient(module.app) as client:
        yield client, module
    module.review_runtime.runner.shutdown()


def _upload(client, name="policy.txt", text="Policy checks access.", mime="text/plain"):
    return client.post("/api/sources/file", files={"file": (name, text.encode("utf-8"), mime)})


def _ready(client, source_id, user="alice"):
    headers = {"x-user": user}
    created = client.post("/api/review/cases", headers=headers, json={
        "title": "Error acceptance", "source_ids": [source_id], "request_text": "Check access. Check approval.",
    })
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    proposed = client.post(f"/api/review/cases/{case_id}/requirements:propose", headers=headers)
    assert proposed.status_code == 200, proposed.text
    confirmed = client.put(f"/api/review/cases/{case_id}/requirements", headers=headers, json={
        "requirements": [{"id": item["id"], "text": item["text"], "confirmed": True}
                         for item in proposed.json()],
    })
    assert confirmed.status_code == 200, confirmed.text
    return case_id


def test_empty_upload_has_stable_error(review_http):
    response = _upload(review_http[0], text="")
    assert response.status_code in {400, 422}
    assert response.json()["code"] in {"EMPTY_FILE", "EMPTY_TEXT"}


def test_oversized_upload_has_stable_error_code(review_http):
    response = _upload(review_http[0], text="x" * 2_000_001)
    assert response.status_code == 413
    assert response.json()["code"] == "FILE_TOO_LARGE"


def test_wrong_upload_file_type_has_stable_error(review_http):
    response = _upload(review_http[0], name="policy.exe", mime="application/octet-stream")
    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_DOCUMENT_TYPE"


def test_run_rate_limit_returns_retry_after(review_http, monkeypatch):
    client, _ = review_http
    uploaded = _upload(client)
    case_id = _ready(client, uploaded.json()["source_id"])
    monkeypatch.setenv("REVIEW_RATE_RUNS_PER_MIN", "1")
    review_rate_limiter._entries.clear()
    assert client.post(f"/api/review/cases/{case_id}/runs").status_code == 202
    limited = client.post(f"/api/review/cases/{case_id}/runs")
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1


@pytest.mark.parametrize("provider_error", ["ConnectError", "TimeoutException"])
def test_provider_failure_is_reported_as_task_failed(review_http, monkeypatch, provider_error):
    client, module = review_http
    uploaded = _upload(client)
    case_id = _ready(client, uploaded.json()["source_id"])

    class FailedFakePipeline:
        async def run(self, *args, **kwargs):
            return {"status": "FAILED", "events": [{"stage": "run_failed", "error_type": provider_error}]}

    monkeypatch.setattr(module, "owner_pipeline", lambda *args, **kwargs: FailedFakePipeline())
    monkeypatch.setenv("REVIEW_ENGINE", "pipeline")
    run = client.post(f"/api/review/cases/{case_id}/runs")
    assert run.status_code == 202, run.text
    job_id = run.json()["id"]
    assert module.review_runtime.runner.wait(job_id, timeout=5).value in {"SUCCEEDED", "PARTIAL"}
    events = client.get(f"/api/review/runs/{job_id}/events").text
    assert '"error_type":"PROVIDER_LIMIT"' in events
    assert "event: task.failed" in events


def test_second_active_run_is_conflict(review_http):
    client, module = review_http
    uploaded = _upload(client)
    case_id = _ready(client, uploaded.json()["source_id"])
    entered, release = Event(), Event()

    class BlockingFake(FakeReviewEngine):
        def run(self, *args):
            entered.set()
            assert release.wait(5), "Test did not release fake engine"
            return super().run(*args)

    module.review_runtime.case_engine = lambda case, selected=None: BlockingFake()
    try:
        first = client.post(f"/api/review/cases/{case_id}/runs")
        assert first.status_code == 202
        job_id = first.json()["id"]
        assert entered.wait(5)
        assert client.post(f"/api/review/cases/{case_id}/runs").status_code == 409
    finally:
        release.set()
    assert module.review_runtime.runner.wait(job_id, timeout=5).value == "SUCCEEDED"


def test_another_user_cannot_read_case(review_http):
    client, _ = review_http
    uploaded = _upload(client)
    case_id = _ready(client, uploaded.json()["source_id"])
    response = client.get(f"/api/review/cases/{case_id}", headers={"x-user": "bob"})
    assert response.status_code == 404
    assert response.json()["code"] == "CASE_NOT_FOUND"


def test_restart_recovers_a_mid_run_durable_job():
    from datetime import datetime, timezone

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    tables = [table for table in Base.metadata.sorted_tables if table.name.startswith("review_")]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(engine, expire_on_commit=False)
    owner = "acceptance-restart"
    repo = PostgresCaseRepository(factory, owner)
    service = ReviewCaseService(repo, None, id_factory=lambda: "acceptance-restart-case")
    case = service.create_case(owner, "Restart audit", "Check access")
    repo.save_requirements(owner, case.id, [Requirement(
        id="restart-requirement", case_id=case.id, text="Check access", origin="USER",
        confirmed=True, order=0,
    )])

    class Interrupted(BaseException):
        pass

    def interrupted_work(*args):
        raise Interrupted()

    first = DurableJobRunner(repo, interrupted_work, "first-worker", 10,
                             lambda: datetime(2026, 11, 14, tzinfo=timezone.utc))
    clock = first.clock
    job_id = first.submit({"owner": owner, "case_id": case.id, "budget": None})
    with pytest.raises(Interrupted):
        first._futures[0].result(timeout=5)
    assert first.status(job_id) == JobState.RUNNING
    first.shutdown()

    second = DurableJobRunner(repo, lambda *args: JobState.SUCCEEDED, "replacement", 10, clock)
    try:
        from datetime import timedelta
        assert second.recover(clock() + timedelta(seconds=11)) == [job_id]
        second.start()
        assert second.wait(job_id, timeout=5) == JobState.SUCCEEDED
        assert repo.job_record(job_id)["attempt"] == 2
    finally:
        second.shutdown()
        engine.dispose()
