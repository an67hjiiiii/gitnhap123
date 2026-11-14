import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.run_review_mock import DEV_TOKEN, create_mock_app, seed_complete_case


ROOT = Path(__file__).resolve().parents[2]


def test_types_cover_snapshot_schemas():
    snapshot = json.loads((ROOT / "contracts/review/openapi.review.v0.json").read_text())
    types = (ROOT / "contracts/review/ts/review-types.ts").read_text()
    for schema in snapshot["components"]["schemas"]:
        assert re.search(rf"\b(?:interface|type)\s+{re.escape(schema)}\b", types), schema
    for name in ("Verdict", "CaseStatus", "JobState", "Decision", "ErrorCode"):
        assert re.search(rf"\btype\s+{name}\s*=", types), name


def test_client_covers_snapshot_operations():
    snapshot = json.loads((ROOT / "contracts/review/openapi.review.v0.json").read_text())
    client = (ROOT / "contracts/review/ts/review-client.ts").read_text()
    for path, operations in snapshot["paths"].items():
        for method, operation in operations.items():
            assert operation["operationId"] in client, operation["operationId"]
            normalized = re.sub(r"\{([^}]+)\}", r"${encodeURIComponent(\1)}", path)
            # The client may add query strings; its literal route prefix must still match.
            route = path.split("{")[0]
            assert route in client, f"{method.upper()} {path}"


def test_mock_serves_cases_with_bearer_token():
    app = create_mock_app()
    case_id = seed_complete_case(app)
    with TestClient(app) as client:
        response = client.get("/api/review/cases", headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    assert response.status_code == 200
    assert any(case["id"] == case_id and case["status"] == "COMPLETE" for case in response.json())
