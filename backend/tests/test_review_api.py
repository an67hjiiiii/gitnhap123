"""HTTP contracts using fake engines and isolated in-memory review state."""

import json
from threading import Event

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.review.engine import FakeReviewEngine


@pytest.fixture
def api(monkeypatch, sf1_vector_store):
    monkeypatch.setenv("PROVIDER", "fake")
    runtime = ReviewRuntime()
    app = FastAPI()

    def current_user(request: Request):
        user = request.headers.get("x-user", "alice")
        if user == "anonymous":
            raise HTTPException(401, "Authentication is required")
        return {"user_id": user, "role": "USER"}

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine()
    with TestClient(app) as client:
        yield client, runtime, app
    runtime.runner.shutdown()


def create(client, title="Audit"):
    response = client.post("/api/review/cases", json={
        "title": title, "source_ids": ["source-1"], "request_text": "Check policy. Check approval.",
    })
    assert response.status_code == 201
    return response.json()["id"]


def ready(client):
    case_id = create(client)
    response = client.post(f"/api/review/cases/{case_id}/requirements:propose")
    assert response.status_code == 200
    assert all(not item["confirmed"] and item["origin"] == "AI_PROPOSED" for item in response.json())
    requirements = [{"id": r["id"], "text": r["text"], "confirmed": True} for r in response.json()]
    assert client.put(f"/api/review/cases/{case_id}/requirements",
                      json={"requirements": requirements}).status_code == 200
    return case_id


def run(client, runtime, case_id):
    response = client.post(f"/api/review/cases/{case_id}/runs", json={"budget": {"tasks": 2}})
    assert response.status_code == 202
    job_id = response.json()["id"]
    runtime.runner.wait(job_id, timeout=5)
    return job_id


@pytest.mark.parametrize("partial", [False, True])
def test_flow_propose_confirm_run_decision_export(api, partial):
    client, runtime, app = api
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine(skip_budget=partial)
    case_id = ready(client)
    assert client.get("/api/review/cases").json()[0]["id"] == case_id
    job_id = run(client, runtime, case_id)
    status = client.get(f"/api/review/runs/{job_id}").json()
    assert status["state"] == ("PARTIAL" if partial else "SUCCEEDED")
    assert status["case_id"] == case_id and status["seq"] > 0
    assert status["budget"] == {"tasks": 2, "max_requirements": 100, "max_seconds": 3600}
    assert status["started_at"] and status["finished_at"]
    case = client.get(f"/api/review/cases/{case_id}").json()
    assert case["status"] == ("PARTIAL" if partial else "COMPLETE")
    finding = case["findings"][0]
    assert finding["review"] == "NONE"
    response = client.put(f"/api/review/findings/{finding['id']}/decision",
                          json={"review": "EDIT", "edited_text": "Reviewed policy"})
    assert response.status_code == 200
    assert response.json()["edited_text"] == "Reviewed policy"
    assert response.json()["verdict"] == finding["verdict"]
    export = client.get(f"/api/review/cases/{case_id}/export?format=md")
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/markdown")
    assert "# Audit" in export.text and "Decision: EDIT" in export.text


def test_unconfirmed_and_empty_requirements_refuse_run(api):
    client, _, _ = api
    case_id = create(client)
    for propose in (False, True):
        if propose:
            client.post(f"/api/review/cases/{case_id}/requirements:propose")
        response = client.post(f"/api/review/cases/{case_id}/runs")
        assert response.status_code == 409
        assert response.json()["code"] == "REQUIREMENTS_UNCONFIRMED"


def test_requirement_replace_edits_adds_removes_and_unconfirms(api):
    client, _, _ = api
    case_id = ready(client)
    existing = client.get(f"/api/review/cases/{case_id}").json()["requirements"]
    response = client.put(f"/api/review/cases/{case_id}/requirements", json={"requirements": [
        {"id": existing[0]["id"], "text": "Changed", "confirmed": False},
        {"text": "User requirement", "confirmed": True},
    ]})
    assert response.status_code == 200
    values = response.json()
    assert values[0]["text"] == "Changed" and not values[0]["confirmed"]
    assert values[1]["origin"] == "USER" and values[1]["confirmed"]
    assert existing[1]["id"] not in {r["id"] for r in values}
    assert client.get(f"/api/review/cases/{case_id}").json()["status"] == "CONFIRMING"
    assert client.post(f"/api/review/cases/{case_id}/runs").status_code == 409


def test_foreign_owner_cannot_access_any_resource(api):
    client, runtime, _ = api
    case_id = ready(client)
    job_id = run(client, runtime, case_id)
    finding = client.get(f"/api/review/cases/{case_id}").json()["findings"][0]
    requests = [
        ("GET", f"/cases/{case_id}", None),
        ("POST", f"/cases/{case_id}/requirements:propose", None),
        ("PUT", f"/cases/{case_id}/requirements", {"requirements": []}),
        ("POST", f"/cases/{case_id}/runs", {}),
        ("GET", f"/cases/{case_id}/export", None),
        ("GET", f"/runs/{job_id}", None),
        ("GET", f"/runs/{job_id}/events", None),
        ("POST", f"/runs/{job_id}:cancel", None),
        ("PUT", f"/findings/{finding['id']}/decision", {"review": "ACCEPT"}),
    ]
    for method, path, body in requests:
        response = client.request(method, "/api/review" + path, json=body, headers={"x-user": "bob"})
        assert response.status_code == 404, path
        assert response.json()["code"] == ("FINDING_NOT_FOUND" if path.startswith("/findings/") else "CASE_NOT_FOUND")
    assert client.get("/api/review/cases", headers={"x-user": "bob"}).json() == []


def test_sse_replays_only_later_events(api):
    client, runtime, _ = api
    job_id = run(client, runtime, ready(client))
    response = client.get(f"/api/review/runs/{job_id}/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    blocks = response.text.strip().split("\n\n")
    ids = [int(block.splitlines()[0].removeprefix("id: ")) for block in blocks]
    assert ids == list(range(1, len(ids) + 1))
    assert "event: task.started" in response.text
    assert "event: finding.created" in response.text
    assert "event: job.done" in blocks[-1]
    payload = next(block for block in blocks if "event: finding.created" in block)
    assert json.loads(payload.split("data: ")[1])["review"] == "NONE"
    replay = client.get(f"/api/review/runs/{job_id}/events", headers={"Last-Event-ID": "2"})
    assert replay.text == "\n\n".join(blocks[2:]) + "\n\n"
    assert client.get(f"/api/review/runs/{job_id}/events",
                      headers={"Last-Event-ID": str(ids[-1])}).text == ""


def test_running_and_queued_cancellation_and_active_case_guard(api):
    client, runtime, app = api
    entered, release = Event(), Event()

    class BlockingEngine(FakeReviewEngine):
        def run(self, *args):
            entered.set()
            assert release.wait(5), "Test did not release worker"
            return super().run(*args)

    case_id, second_case = ready(client), ready(client)
    app.dependency_overrides[get_review_engine] = lambda: BlockingEngine()
    try:
        first = client.post(f"/api/review/cases/{case_id}/runs").json()["id"]
        assert entered.wait(5)
        assert client.post(f"/api/review/cases/{case_id}/runs").status_code == 409
        assert client.put(f"/api/review/cases/{case_id}/requirements",
                          json={"requirements": []}).status_code == 409
        queued = client.post(f"/api/review/cases/{second_case}/runs").json()["id"]
        assert client.get(f"/api/review/runs/{queued}").json()["state"] == "QUEUED"
        assert client.post(f"/api/review/runs/{queued}:cancel").json()["state"] == "CANCELLED"
        assert client.post(f"/api/review/runs/{first}:cancel").status_code == 200
    finally:
        release.set()
    runtime.runner.wait(first, timeout=5)
    assert client.get(f"/api/review/runs/{first}").json()["state"] == "CANCELLED"
    assert client.get(f"/api/review/cases/{case_id}").json()["status"] == "PARTIAL"
    assert "event: job.cancelled" in client.get(f"/api/review/runs/{first}/events").text


def test_engine_failure_is_reported(api):
    client, runtime, app = api

    class FailingEngine(FakeReviewEngine):
        def run(self, *args):
            raise RuntimeError("Fake failure")

    case_id = ready(client)
    app.dependency_overrides[get_review_engine] = lambda: FailingEngine()
    job_id = run(client, runtime, case_id)
    assert client.get(f"/api/review/runs/{job_id}").json()["state"] == "FAILED"
    assert client.get(f"/api/review/cases/{case_id}").json()["status"] == "FAILED"
    assert "event: job.failed" in client.get(f"/api/review/runs/{job_id}/events").text


def test_validation_and_authentication_errors(api):
    client, runtime, _ = api
    case_id = ready(client)
    job_id = run(client, runtime, case_id)
    finding = client.get(f"/api/review/cases/{case_id}").json()["findings"][0]
    requests = [
        ("POST", "/cases", {"title": " ", "request_text": "x"}, {}),
        ("PUT", f"/cases/{case_id}/requirements", {"requirements": [{"id": "unknown", "text": "x"}]}, {}),
        ("PUT", f"/findings/{finding['id']}/decision", {"review": "EDIT"}, {}),
        ("PUT", f"/findings/{finding['id']}/decision", {"review": "NONE"}, {}),
        ("GET", f"/cases/{case_id}/export?format=pdf", None, {}),
        ("GET", f"/runs/{job_id}/events", None, {"Last-Event-ID": "invalid"}),
        ("GET", f"/runs/{job_id}/events", None, {"Last-Event-ID": "-1"}),
    ]
    for method, path, body, headers in requests:
        response = client.request(method, "/api/review" + path, json=body, headers=headers)
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "VALIDATION_ERROR"
    assert client.get("/api/review/cases", headers={"x-user": "anonymous"}).status_code == 401


def test_finding_decisions_are_scoped_to_the_right_case(api):
    client, runtime, _ = api
    cases = [ready(client), ready(client)]
    findings = []
    for case_id in cases:
        run(client, runtime, case_id)
        findings.append(client.get(f"/api/review/cases/{case_id}").json()["findings"][0])
    assert findings[0]["id"] != findings[1]["id"]
    assert client.put(f"/api/review/findings/{findings[1]['id']}/decision",
                      json={"review": "ACCEPT"}).status_code == 200
    assert client.get(f"/api/review/cases/{cases[0]}").json()["findings"][0]["review"] == "NONE"
