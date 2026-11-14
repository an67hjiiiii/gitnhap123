"""End-to-end Review Case acceptance flow using the local fake provider."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import dotenv
import pytest
from fastapi.testclient import TestClient

from app.review_adapters import PipelineReviewEngine


@pytest.fixture
def review_http(monkeypatch, tmp_path, sf1_fake_provider_env, sf1_vector_store):
    import app.auth.store as auth_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(auth_module, "AuthStore", lambda *args: SimpleNamespace(
        resolve=lambda token: {"user_id": token, "role": "USER"},
    ))
    for key, value in {
        "APP_STORAGE_BACKEND": "file", "APP_ENV": "test",
        "APP_DATA_DIR": str(tmp_path / "documents"),
        "RUNS_DIR": str(tmp_path / "outputs"), "VECTOR_BACKEND": "memory",
        "REVIEW_ENGINE": "pipeline", "REVIEW_RATE_RUNS_PER_MIN": "0",
        "REVIEW_RATE_READS_PER_MIN": "0", "REVIEW_RATE_STATUS_PER_MIN": "0",
    }.items():
        monkeypatch.setenv(key, value)
    name = "app._acceptance_review_main"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[2] / "app" / "main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_session_token", lambda request: request.headers.get("x-user", "alice"))
    monkeypatch.setattr(module, "_configured_vector_store", lambda: sf1_vector_store)
    with TestClient(module.app) as client:
        yield client, module
    module.review_runtime.runner.shutdown()


def _ready_case(client, source_id, request_text, user="alice"):
    headers = {"x-user": user}
    created = client.post("/api/review/cases", headers=headers, json={
        "title": "Acceptance policy review", "source_ids": [source_id], "request_text": request_text,
    })
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    proposed = client.post(f"/api/review/cases/{case_id}/requirements:propose", headers=headers)
    assert proposed.status_code == 200, proposed.text
    requirements = proposed.json()
    assert requirements and all(not item["confirmed"] for item in requirements)
    confirmed = client.put(f"/api/review/cases/{case_id}/requirements", headers=headers, json={
        "requirements": [{"id": item["id"], "text": item["text"], "confirmed": True}
                         for item in requirements],
    })
    assert confirmed.status_code == 200, confirmed.text
    return case_id


def test_upload_case_run_sse_decisions_and_markdown_export(review_http):
    client, module = review_http
    text = (
        "Access requires a valid token. Expired tokens are rejected. "
        "Administrators review access changes."
    )
    uploaded = client.post("/api/sources/file", files={
        "file": ("policy.txt", text.encode("utf-8"), "text/plain"),
    })
    assert uploaded.status_code == 200, uploaded.text
    source_id = uploaded.json()["source_id"]
    case_id = _ready_case(client, source_id, text)

    started = client.post(f"/api/review/cases/{case_id}/runs", json={})
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]
    assert module.review_runtime.runner.wait(job_id, timeout=5).value in {"SUCCEEDED", "PARTIAL"}

    events = client.get(f"/api/review/runs/{job_id}/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    blocks = events.text.strip().split("\n\n")
    assert "event: job.done" in blocks[-1]
    finding_events = [json.loads(block.split("data: ", 1)[1]) for block in blocks
                      if "event: finding.created" in block]
    case = client.get(f"/api/review/cases/{case_id}").json()
    findings = case["findings"]
    assert len(findings) == len(finding_events) and findings
    assert all(finding["evidence"] for finding in findings)
    assert all(evidence["source_id"] == source_id and evidence["locator"]
               for finding in findings for evidence in finding["evidence"])
    assert isinstance(module.review_runtime.runs[job_id]["engine"], PipelineReviewEngine)

    decisions = ("ACCEPT", "REJECT", "EDIT")
    for finding, decision in zip(findings, decisions, strict=False):
        response = client.put(f"/api/review/findings/{finding['id']}/decision", json={
            "review": decision,
            **({"edited_text": "Reviewed access policy"} if decision == "EDIT" else {}),
        })
        assert response.status_code == 200, response.text
    exported = client.get(f"/api/review/cases/{case_id}/export?format=md")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/markdown")
    for finding in findings:
        assert finding["evidence"][0]["locator"] in exported.text
        assert finding["evidence"][0]["locator"] in exported.text
    assert exported.text.count("Decision:") == len(findings)
    assert "Reviewed access policy" in exported.text
