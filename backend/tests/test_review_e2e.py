"""Real review/chat wiring with fake generation and isolated owner stores."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import dotenv
import pytest
from fastapi.testclient import TestClient

from app.review.engine import FakeReviewEngine
from app.review_adapters import PipelineReviewEngine


@pytest.fixture
def review_app(monkeypatch, tmp_path, sf1_fake_provider_env, sf1_vector_store):
    import app.auth.store as auth_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(auth_module, "AuthStore", lambda *args: SimpleNamespace(
        resolve=lambda token: {"user_id": token, "role": "USER"},
    ))
    for key, value in {
        "APP_STORAGE_BACKEND": "file", "APP_ENV": "test",
        "APP_DATA_DIR": str(tmp_path / "documents"),
        "RUNS_DIR": str(tmp_path / "outputs"), "VECTOR_BACKEND": "memory",
        "REVIEW_ENGINE": "pipeline",
    }.items():
        monkeypatch.setenv(key, value)
    name = "app._review_e2e_main"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app" / "main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_session_token", lambda request: request.headers.get("x-user", "alice"))
    monkeypatch.setattr(module, "_configured_vector_store", lambda: sf1_vector_store)
    with TestClient(module.app) as client:
        yield client, module
    module.review_runtime.runner.shutdown()


def ready(client, source_ids, *, user="alice"):
    headers = {"x-user": user}
    response = client.post("/api/review/cases", headers=headers, json={
        "title": "Authentication audit", "source_ids": source_ids,
        "request_text": "Authentication requires a valid token. Authentication rejects expired tokens.",
    })
    assert response.status_code == 201, response.text
    case_id = response.json()["id"]
    response = client.post(f"/api/review/cases/{case_id}/requirements:propose", headers=headers)
    assert response.status_code == 200, response.text
    proposed = response.json()
    assert len(proposed) == 2 and all(not item["confirmed"] for item in proposed)
    response = client.put(f"/api/review/cases/{case_id}/requirements", headers=headers, json={
        "requirements": [{"id": item["id"], "text": item["text"], "confirmed": True}
                         for item in proposed],
    })
    assert response.status_code == 200, response.text
    return case_id


def run_case(client, module, case_id, *, user="alice", budget=None):
    headers = {"x-user": user}
    response = client.post(f"/api/review/cases/{case_id}/runs", headers=headers, json={"budget": budget})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    # Bound the worker wait, then poll the public terminal state without sleeps.
    module.review_runtime.runner.wait(job_id, timeout=5)
    status = client.get(f"/api/review/runs/{job_id}", headers=headers).json()
    assert status["state"] in {"SUCCEEDED", "PARTIAL"}, status
    case = client.get(f"/api/review/cases/{case_id}", headers=headers).json()
    return job_id, case


def test_pipeline_review_evidence_decision_export_and_replay(review_app, monkeypatch):
    client, module = review_app
    # Exercise the default engine selection even though PROVIDER=fake.
    monkeypatch.delenv("REVIEW_ENGINE")
    imported = client.post("/api/sources/text", json={
        "source_name": "policy.txt",
        "text": "Authentication requires a valid token. Authentication rejects expired tokens.",
    })
    assert imported.status_code == 200, imported.text
    source_id = imported.json()["source_id"]
    other = module.owner_source_store({"user_id": "alice"}).import_text(
        "unselected.txt", "Authentication requires secret administrator credentials.",
    )
    calls = []
    original = module.owner_pipeline

    def record_factory(user, *args):
        pipeline = original(user, *args)
        run = pipeline.run

        async def record(query, **kwargs):
            calls.append(("start", user["user_id"], kwargs["source_ids"]))
            result = await run(query, **kwargs)
            calls.append(("end", user["user_id"], kwargs["source_ids"]))
            return result

        pipeline.run = record
        return pipeline

    monkeypatch.setattr(module, "owner_pipeline", record_factory)
    case_id = ready(client, [source_id])
    job_id, case = run_case(client, module, case_id)
    assert isinstance(module.review_runtime.runs[job_id]["engine"], PipelineReviewEngine)
    assert calls == [(phase, "alice", [source_id]) for phase in ("start", "end", "start", "end")]
    assert case["status"] == "COMPLETE"
    assert len(case["findings"]) == 2
    chunks = module.owner_source_store({"user_id": "alice"}).chunks([source_id])
    allowed = {chunk.chunk_id for chunk in chunks}
    for finding in case["findings"]:
        assert finding["verdict"] == "SATISFIED"
        assert finding["evidence"]
        assert all(item["evidence_id"] in allowed and item["source_id"] == source_id
                   and item["source_id"] != other["source_id"] for item in finding["evidence"])
    finding = case["findings"][0]
    response = client.put(f"/api/review/findings/{finding['id']}/decision", json={"review": "ACCEPT"})
    assert response.status_code == 200 and response.json()["verdict"] == finding["verdict"]
    exported = client.get(f"/api/review/cases/{case_id}/export")
    assert exported.status_code == 200
    assert "Verdict: Đã đáp ứng" in exported.text and "Decision: Chấp nhận" in exported.text
    assert finding["evidence"][0]["evidence_id"] in exported.text and source_id in exported.text
    assert "Authentication requires a valid token" in exported.text

    events = client.get(f"/api/review/runs/{job_id}/events")
    assert events.status_code == 200 and events.headers["content-type"].startswith("text/event-stream")
    blocks = events.text.strip().split("\n\n")
    ids = [int(block.splitlines()[0].removeprefix("id: ")) for block in blocks]
    assert ids == list(range(1, len(ids) + 1))
    starts = [json.loads(block.split("data: ")[1]) for block in blocks if "event: task.started" in block]
    assert [item["requirement_id"] for item in starts] == [item["id"] for item in case["requirements"]]
    published = [json.loads(block.split("data: ")[1]) for block in blocks if "event: finding.created" in block]
    assert published == case["findings"]
    assert "event: job.done" in blocks[-1]
    replay = client.get(f"/api/review/runs/{job_id}/events", headers={"Last-Event-ID": "2"})
    assert replay.text == "\n\n".join(blocks[2:]) + "\n\n"
    assert client.get(f"/api/review/runs/{job_id}/events", headers={"Last-Event-ID": str(ids[-1])}).text == ""


def test_no_sources_is_not_found_and_complete(review_app):
    client, module = review_app
    assert client.get("/api/sources", headers={"x-user": "bob"}).json()["sources"] == []
    _, case = run_case(client, module, ready(client, [], user="bob"), user="bob")
    # Service completeness measures processed requirements; NOT_FOUND is terminal.
    assert case["status"] == "COMPLETE"
    assert len(case["findings"]) == 2
    assert all(item["verdict"] == "NOT_FOUND" and item["evidence"] == [] for item in case["findings"])


def test_missing_and_foreign_source_are_indistinguishable(review_app):
    client, module = review_app
    foreign = module.owner_source_store({"user_id": "bob"}).import_text("private.txt", "Private policy.")
    for source_id in (foreign["source_id"], "missing-source"):
        response = client.post("/api/review/cases", json={
            "title": "Audit", "request_text": "Check policy", "source_ids": [source_id],
        })
        assert response.status_code == 404
        assert response.json() == {"code": "SOURCE_NOT_FOUND", "message": "Source not found"}
    assert client.get("/api/review/cases").json() == []


def test_fake_engine_switch(review_app, monkeypatch):
    client, module = review_app
    monkeypatch.setenv("REVIEW_ENGINE", "fake")
    job_id, case = run_case(client, module, ready(client, []))
    assert isinstance(module.review_runtime.runs[job_id]["engine"], FakeReviewEngine)
    assert len(case["findings"]) == 2


def test_pipeline_budget_events_reach_job_log(review_app):
    client, module = review_app
    job_id, case = run_case(client, module, ready(client, []), budget={"max_requirements": 1})
    assert case["status"] == "PARTIAL"
    assert [item["verdict"] for item in case["findings"]] == ["NOT_FOUND", "SKIPPED_BUDGET"]
    events = module.review_runtime.events.read_since(job_id, 0)
    assert sum(event.type == "budget.skipped" for event in events) == 1
    assert sum(event.type == "task.started" for event in events) == 1
