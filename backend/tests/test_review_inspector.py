import pytest
from types import SimpleNamespace
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.review.engine import FakeReviewEngine
from app.review.schemas import Evidence


@pytest.fixture
def inspector_api(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    runtime = ReviewRuntime()
    chunk = SimpleNamespace(chunk_id="ev1", source_id="source-1", text="Policy text",
                            provenance={"locator": "p. 1"})
    store = SimpleNamespace(source=lambda source_id: object() if source_id == "source-1" else None,
                            chunks=lambda source_ids: [chunk] if "source-1" in source_ids else [])
    runtime.source_store_factory = lambda owner: store
    app = FastAPI()

    def current_user(request: Request):
        return {"user_id": request.headers.get("x-user", "alice")}

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine(evidence=[
        Evidence(evidence_id="ev1", source_id="source-1", locator="p. 1", excerpt="Policy text"),
    ])
    with TestClient(app) as client:
        yield client, runtime, app
    runtime.runner.shutdown()


def ready_and_run(client, runtime, case_title="Audit", budget=None):
    case_id = client.post("/api/review/cases", json={
        "title": case_title, "source_ids": ["source-1"],
        "request_text": "Check policy. Check approval.",
    }).json()["id"]
    proposed = client.post(f"/api/review/cases/{case_id}/requirements:propose").json()
    assert client.put(f"/api/review/cases/{case_id}/requirements", json={
        "requirements": [{"id": item["id"], "text": item["text"], "confirmed": True}
                         for item in proposed],
    }).status_code == 200
    response = client.post(f"/api/review/cases/{case_id}/runs", json={"budget": budget})
    job_id = response.json()["id"]
    runtime.runner.wait(job_id, timeout=5)
    return case_id, job_id


def test_inspector_returns_stable_requirement_finding_evidence_chain(inspector_api):
    client, runtime, _ = inspector_api
    case_id, job_id = ready_and_run(client, runtime)
    first = client.get(f"/api/review/cases/{case_id}/inspector")
    second = client.get(f"/api/review/cases/{case_id}/inspector")
    assert first.status_code == 200 and first.json() == second.json()
    body = first.json()
    assert body["run"]["id"] == job_id and body["run"]["seq"]["count"] > 0
    req = body["requirements"][0]
    assert req["confirmed"] and req["origin"] == "AI_PROPOSED"
    assert req["finding"]["verdict"] == "SATISFIED"
    assert req["finding"]["confidence"] == "L0"
    assert req["evidence"] == [{"source_id": "source-1", "locator": "p. 1",
                                "excerpt": "Policy text"}]
    assert body["events"] == sorted(body["events"], key=lambda event: event["seq"])
    assert body["budget"]["given"] is None


def test_inspector_marks_budget_skipped_and_supports_selected_run(inspector_api):
    client, runtime, app = inspector_api
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine(skip_budget=True)
    case_id, job_id = ready_and_run(client, runtime, budget={"max_requirements": 1})
    body = client.get(f"/api/review/cases/{case_id}/inspector?run={job_id}").json()
    assert body["budget"]["given"] == {"max_requirements": 1}
    assert [item["finding"]["verdict"] for item in body["requirements"]] == [
        "SKIPPED_BUDGET", "SKIPPED_BUDGET",
    ]
    assert body["budget"]["skipped_requirement_ids"] == [
        item["id"] for item in body["requirements"]
    ]


def test_inspector_hides_foreign_case_and_unknown_run(inspector_api):
    client, runtime, _ = inspector_api
    case_id, job_id = ready_and_run(client, runtime)
    foreign = client.get(f"/api/review/cases/{case_id}/inspector", headers={"x-user": "bob"})
    assert foreign.status_code == 404 and foreign.json()["code"] == "CASE_NOT_FOUND"
    unknown = client.get(f"/api/review/cases/{case_id}/inspector?run=unknown")
    assert unknown.status_code == 404 and unknown.json()["code"] == "RUN_NOT_FOUND"
