"""Executable, schema-checked request/response examples for Review API v0."""

import json
import os
import re
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.review.engine import FakeReviewEngine
from app.storage.vector_store import InMemoryVectorStore


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = ROOT / "contracts" / "review" / "openapi.review.v0.json"
EXAMPLES = ROOT / "contracts" / "review" / "examples"


@pytest.fixture
def auth_api(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("REVIEW_ENGINE", "fake")
    assert InMemoryVectorStore() is not None
    runtime = ReviewRuntime()
    app = FastAPI()

    def current_user(request: Request):
        if request.headers.get("authorization") != "Bearer example-token":
            raise HTTPException(401, "Authentication is required")
        return {"user_id": "example-user"}

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine()
    class ExampleStore:
        @staticmethod
        def resolve(token):
            return {"user_id": "example-user"} if token == "example-token" else None

    with TestClient(app) as client:
        yield client, runtime, ExampleStore(), {"alice": "example-token"}, {"alice": None}
    runtime.runner.shutdown()


def _validate(value, schema, schemas):
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        _validate(value, schemas[name], schemas)
        return
    if "anyOf" in schema:
        assert any(_matches(value, option, schemas) for option in schema["anyOf"])
    kind = schema.get("type")
    if kind == "object":
        assert isinstance(value, dict)
        assert set(schema.get("required", [])) <= value.keys()
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert value.keys() <= props.keys()
        for key, item in value.items():
            if key in props:
                _validate(item, props[key], schemas)
    elif kind == "array":
        assert isinstance(value, list)
        for item in value:
            _validate(item, schema.get("items", {}), schemas)
    elif kind == "string":
        assert isinstance(value, str)
        if "enum" in schema:
            assert value in schema["enum"]
    elif kind == "integer":
        assert type(value) is int
    elif kind == "number":
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "boolean":
        assert isinstance(value, bool)
    elif kind == "null":
        assert value is None


def _matches(value, schema, schemas):
    try:
        _validate(value, schema, schemas)
        return True
    except AssertionError:
        return False


def _canonical(examples, dynamic_ids):
    replacements = sorted(((value, f"<{name}>") for name, value in dynamic_ids.items() if value),
                         key=lambda pair: len(pair[0]), reverse=True)
    timestamp = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:\+00:00|Z)")

    def clean(value):
        if isinstance(value, str):
            for actual, marker in replacements:
                value = value.replace(actual, marker)
            return timestamp.sub("<timestamp>", value)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value

    return clean(examples)


def _build_examples(auth_api):
    client, runtime, store, tokens, sources = auth_api
    token, source_id = tokens["alice"], sources["alice"]
    headers = {"Authorization": "Bearer <access_token>"}
    case_request = {"title": "Policy review", "request_text": "Review the policy.",
                    "source_ids": [source_id] if source_id else [], "kind": "requirement_review"}
    examples = {}

    def record(method, path, response, *, body=None, request_headers=None):
        operation_path = path.split("?", 1)[0]
        examples[(method.lower(), operation_path)] = {
            "request": {"method": method, "path": path, "headers": request_headers or headers, "body": body},
            "response": {"status": response.status_code,
                         "body": response.json() if "application/json" in response.headers.get("content-type", "")
                         else response.text},
        }

    response = client.get("/api/review/cases", headers={**headers, "Authorization": f"Bearer {token}"})
    record("GET", "/api/review/cases", response)

    response = client.post("/api/review/cases", json=case_request, headers={"Authorization": f"Bearer {token}"})
    record("POST", "/api/review/cases", response, body=case_request)
    case_id = response.json()["id"]

    path = f"/api/review/cases/{case_id}"
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    record("GET", "/api/review/cases/{case_id}", response)

    path = f"/api/review/cases/{case_id}/requirements:propose"
    response = client.post(path, headers={"Authorization": f"Bearer {token}"})
    record("POST", "/api/review/cases/{case_id}/requirements:propose", response)
    proposals = response.json()

    requirements_body = {"requirements": [{"id": item["id"], "text": item["text"], "confirmed": True}
                                           for item in proposals]}
    path = f"/api/review/cases/{case_id}/requirements"
    response = client.put(path, json=requirements_body, headers={"Authorization": f"Bearer {token}"})
    record("PUT", "/api/review/cases/{case_id}/requirements", response, body=requirements_body)

    requirement_id = requirements_body["requirements"][0]["id"]
    path = f"/api/review/cases/{case_id}/requirements/{requirement_id}/suggestions"
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    record("GET", "/api/review/cases/{case_id}/requirements/{requirement_id}/suggestions", response)

    path = f"/api/review/cases/{case_id}/runs"
    run_body = {}
    response = client.post(path, json=run_body, headers={"Authorization": f"Bearer {token}"})
    record("POST", "/api/review/cases/{case_id}/runs", response, body=run_body)
    job_id = response.json()["id"]
    runtime.runner.wait(job_id, timeout=5)

    path = f"/api/review/runs/{job_id}"
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    record("GET", "/api/review/runs/{job_id}", response)

    path = f"/api/review/runs/{job_id}/events"
    response = client.get(path, headers={"Authorization": f"Bearer {token}", "Last-Event-ID": "0"})
    record("GET", "/api/review/runs/{job_id}/events", response,
           request_headers={**headers, "Last-Event-ID": "0"})

    path = f"/api/review/cases/{case_id}/inspector"
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    record("GET", "/api/review/cases/{case_id}/inspector", response)

    case_response = client.get(f"/api/review/cases/{case_id}", headers={"Authorization": f"Bearer {token}"})
    finding_id = case_response.json()["findings"][0]["id"]
    decision_body = {"review": "ACCEPT"}
    path = f"/api/review/findings/{finding_id}/decision"
    response = client.put(path, json=decision_body, headers={"Authorization": f"Bearer {token}"})
    record("PUT", "/api/review/findings/{finding_id}/decision", response, body=decision_body)

    path = f"/api/review/cases/{case_id}/export?format=md"
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    record("GET", "/api/review/cases/{case_id}/export?format=md", response)

    path = f"/api/review/runs/{job_id}:cancel"
    response = client.post(path, headers={"Authorization": f"Bearer {token}"})
    record("POST", "/api/review/runs/{job_id}:cancel", response)

    user_id = store.resolve(token)["user_id"]
    dynamic_ids = {"case_id": case_id, "job_id": job_id, "finding_id": finding_id,
                   "source_id": source_id, "user_id": user_id}
    dynamic_ids.update({f"requirement_{index}": item["id"] for index, item in enumerate(proposals)})
    # Also normalize requirement IDs returned by the replacement operation.
    dynamic_ids.update({f"saved_requirement_{index}": item["id"]
                        for index, item in enumerate(examples[("put", "/api/review/cases/{case_id}/requirements")]["response"]["body"])})
    return _canonical(examples, dynamic_ids)


def test_review_examples_cover_and_validate_every_operation(auth_api):
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    expected = {(method.lower(), path) for path, operations in snapshot["paths"].items()
                for method in operations if method.lower() in {"get", "post", "put", "delete", "patch"}}
    generated = _build_examples(auth_api)
    assert set(generated) == expected
    for (method, path), example in generated.items():
        operation = snapshot["paths"][path][method]
        request_schema = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
        if request_schema is not None:
            _validate(example["request"]["body"], request_schema, snapshot["components"]["schemas"])
        response_schema = operation["responses"][str(example["response"]["status"])].get("content", {}).get("application/json", {}).get("schema")
        if response_schema and example["response"]["body"] is not None:
            _validate(example["response"]["body"], response_schema, snapshot["components"]["schemas"])

    if os.getenv("REVIEW_WRITE_EXAMPLES") == "1":
        EXAMPLES.mkdir(parents=True, exist_ok=True)
        for (method, path), value in generated.items():
            operation_id = snapshot["paths"][path][method]["operationId"]
            (EXAMPLES / f"{operation_id}.json").write_text(
                json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    expected_examples = {}
    for (method, path), example in generated.items():
        operation_id = snapshot["paths"][path][method]["operationId"]
        expected_examples[operation_id] = example
    actual_examples = {Path(operation_id).stem: json.loads((EXAMPLES / f"{operation_id}.json").read_text(encoding="utf-8"))
                       for operation_id in [snapshot["paths"][path][method]["operationId"]
                                            for method, path in generated]}
    assert actual_examples == expected_examples
