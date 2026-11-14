"""Drift checks for the versioned review API contract."""

import json
from pathlib import Path

import pytest

from scripts.export_review_openapi import filtered_openapi


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "contracts" / "review" / "openapi.review.v0.json"


def test_review_openapi_matches_committed_snapshot():
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert filtered_openapi() == committed, (
        "Review OpenAPI drift detected. Regenerate with: "
        "python scripts/export_review_openapi.py (from backend/)."
    )


def test_review_draft_endpoints_exist_in_snapshot():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    promised = {
        ("post", "/api/review/cases"),
        ("get", "/api/review/cases"),
        ("get", "/api/review/cases/{case_id}"),
        ("post", "/api/review/cases/{case_id}/requirements:propose"),
        ("put", "/api/review/cases/{case_id}/requirements"),
        ("post", "/api/review/cases/{case_id}/runs"),
        ("get", "/api/review/runs/{job_id}"),
        ("get", "/api/review/runs/{job_id}/events"),
        ("post", "/api/review/runs/{job_id}:cancel"),
        ("put", "/api/review/findings/{finding_id}/decision"),
        ("get", "/api/review/cases/{case_id}/export"),
    }
    available = {(method.lower(), path) for path, methods in snapshot["paths"].items()
                 for method in methods if method.lower() in {"get", "post", "put", "delete", "patch"}}
    missing = sorted(promised - available)
    assert not missing, f"Contract draft endpoints missing from implementation: {missing}"


@pytest.mark.xfail(strict=False, reason="SUSPECTED DEFECT: generated error responses do not consistently document the API {code, message, details?} JSON error shape")
def test_review_error_responses_document_json_error_shape():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    missing = []
    for path, methods in snapshot["paths"].items():
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch"}:
                continue
            for status, response in operation.get("responses", {}).items():
                if not (status.isdigit() and int(status) >= 400):
                    continue
                schema = response.get("content", {}).get("application/json", {}).get("schema", {})
                properties = schema.get("properties", {})
                if not {"code", "message"}.issubset(properties):
                    missing.append(f"{method.upper()} {path} {status}")
    assert not missing, f"Error responses without documented {{code,message}} JSON schema: {missing}"
