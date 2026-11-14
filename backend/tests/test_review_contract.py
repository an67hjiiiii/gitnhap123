"""Drift checks for the versioned review API contract."""

import json
from pathlib import Path

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
        ("get", "/api/review/cases/{case_id}/requirements/{requirement_id}/suggestions"),
    }
    available = {(method.lower(), path) for path, methods in snapshot["paths"].items()
                 for method in methods if method.lower() in {"get", "post", "put", "delete", "patch"}}
    missing = sorted(promised - available)
    assert not missing, f"Contract draft endpoints missing from implementation: {missing}"


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
                if "$ref" in schema:
                    name = schema["$ref"].rsplit("/", 1)[-1]
                    schema = snapshot["components"]["schemas"].get(name, {})
                properties = schema.get("properties", {})
                if not {"code", "message", "details"}.issubset(properties):
                    missing.append(f"{method.upper()} {path} {status}")
    assert not missing, f"Error responses without documented {{code,message,details}} JSON schema: {missing}"


def test_review_snapshot_preserves_previous_paths_methods_and_input_fields():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    # Minimal compatibility anchors copied from the previous v0 snapshot.
    prior_operations = {
        "/api/review/cases": {"get", "post"},
        "/api/review/cases/{case_id}": {"get"},
        "/api/review/cases/{case_id}/export": {"get"},
        "/api/review/cases/{case_id}/inspector": {"get"},
        "/api/review/cases/{case_id}/requirements": {"put"},
        "/api/review/cases/{case_id}/requirements:propose": {"post"},
        "/api/review/cases/{case_id}/runs": {"post"},
        "/api/review/findings/{finding_id}/decision": {"put"},
        "/api/review/runs/{job_id}": {"get"},
        "/api/review/runs/{job_id}/events": {"get"},
        "/api/review/runs/{job_id}:cancel": {"post"},
    }
    for path, methods in prior_operations.items():
        assert path in snapshot["paths"]
        assert methods <= snapshot["paths"][path].keys()
    assert {"get"} <= snapshot["paths"][
        "/api/review/cases/{case_id}/requirements/{requirement_id}/suggestions"
    ].keys()
    prior_fields = {
        "CaseInput": {"title", "source_ids", "request_text"},
        "DecisionInput": {"review", "edited_text"},
        "RequirementInput": {"id", "text", "confirmed"},
        "RequirementsInput": {"requirements"},
        "RunInput": {"budget"},
    }
    schemas = snapshot["components"]["schemas"]
    for name, fields in prior_fields.items():
        assert fields <= schemas[name]["properties"].keys()


def test_spec_change_contract_fields_are_optional_and_additive():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    case = snapshot["components"]["schemas"]["CaseInput"]
    assert case["required"] == ["title", "request_text"]
    assert case["properties"]["kind"]["default"] == "requirement_review"
    assert case["properties"]["kind"]["enum"] == ["requirement_review", "spec_change"]
    assert {"old_source_id", "new_source_id"} <= case["properties"].keys()
