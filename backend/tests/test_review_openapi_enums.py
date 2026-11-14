import json
import subprocess
import sys
from pathlib import Path

from app.api.review import ErrorCode
from app.review.schemas import CaseStatus, Decision, JobState, Verdict


ROOT = Path(__file__).resolve().parents[2]


def test_openapi_snapshot_matches_export_and_contract_enums():
    subprocess.run([sys.executable, "scripts/export_review_openapi.py"], cwd=ROOT / "backend", check=True)
    snapshot = json.loads((ROOT / "contracts/review/openapi.review.v0.json").read_text(encoding="utf-8"))
    schemas = snapshot["components"]["schemas"]
    expected = {"Verdict": Verdict, "CaseStatus": CaseStatus, "JobState": JobState, "Decision": Decision,
                "ErrorCode": ErrorCode}
    for name, enum in expected.items():
        assert schemas[name]["enum"] == [value.value for value in enum]
    labels = json.loads((ROOT / "contracts/review/labels.vi.json").read_text(encoding="utf-8"))
    assert set(labels["errors"]) == {item.value for item in ErrorCode}
