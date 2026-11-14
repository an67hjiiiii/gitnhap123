"""Review API error behavior using isolated in-memory state."""

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.review.engine import FakeReviewEngine
from app.retrieval.index_identity import (
    IndexIncompatibleError,
    IndexLegacyUnverifiedError,
    IndexingError,
)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    runtime = ReviewRuntime()
    app = FastAPI()

    def current_user(request: Request):
        if request.headers.get("x-user") == "anonymous":
            raise HTTPException(401, "Authentication is required")
        return {"user_id": "alice", "role": "USER"}

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine()
    with TestClient(app) as client:
        yield client, runtime, app
    runtime.runner.shutdown()


def ready_case(client):
    case_id = client.post("/api/review/cases", json={
        "title": "Audit", "request_text": "Check approval.",
    }).json()["id"]
    proposed = client.post(f"/api/review/cases/{case_id}/requirements:propose")
    assert proposed.status_code == 200, proposed.text
    requirements = proposed.json()
    confirmed = client.put(f"/api/review/cases/{case_id}/requirements", json={
        "requirements": [
            {"id": item["id"], "text": item["text"], "confirmed": True}
            for item in requirements
        ],
    })
    assert confirmed.status_code == 200, confirmed.text
    return case_id


@pytest.mark.parametrize("budget", [
    {"max_requirements": 0},
    {"max_requirements": -1},
    {"max_seconds": 0},
    {"max_seconds": -0.5},
])
def test_run_budget_that_cannot_cover_one_requirement_returns_409(api, budget):
    client, _, _ = api
    case_id = ready_case(client)
    response = client.post(f"/api/review/cases/{case_id}/runs", json={"budget": budget})
    assert response.status_code == 409, response.text
    assert response.json() == {
        "code": "RUN_BUDGET_EXCEEDED",
        "message": "Run budget cannot cover one requirement",
    }


@pytest.mark.parametrize(("error_type", "expected_code"), [
    (IndexIncompatibleError, "INDEX_INCOMPATIBLE"),
    (IndexLegacyUnverifiedError, "INDEX_LEGACY_UNVERIFIED"),
    (IndexingError, "DERIVED_INDEX_UNAVAILABLE"),
])
def test_index_errors_fail_run_and_emit_code(api, error_type, expected_code):
    client, runtime, app = api

    class FailingIndexEngine(FakeReviewEngine):
        def run(self, *args):
            raise error_type("index cannot be used")

    app.dependency_overrides[get_review_engine] = lambda: FailingIndexEngine()
    case_id = ready_case(client)
    response = client.post(f"/api/review/cases/{case_id}/runs")
    assert response.status_code == 202
    job_id = response.json()["id"]
    assert runtime.runner.wait(job_id, timeout=5).value == "FAILED"

    events = runtime.events.read_since(job_id, 0)
    error_event = next(event for event in events if event.type == "error")
    assert error_event.data == {"code": expected_code, "message": "index cannot be used"}
    assert events[-1].type == "job.failed"


def test_indexing_error_code_is_forwarded_from_engine(api):
    client, runtime, app = api

    class CodedIndexError(IndexingError):
        code = "INDEX_INCOMPATIBLE"

    class FailingIndexEngine(FakeReviewEngine):
        def run(self, *args):
            raise CodedIndexError("coded index failure")

    app.dependency_overrides[get_review_engine] = lambda: FailingIndexEngine()
    case_id = ready_case(client)
    job_id = client.post(f"/api/review/cases/{case_id}/runs").json()["id"]
    assert runtime.runner.wait(job_id, timeout=5).value == "FAILED"
    error_event = next(event for event in runtime.events.read_since(job_id, 0)
                       if event.type == "error")
    assert error_event.data["code"] == "INDEX_INCOMPATIBLE"
