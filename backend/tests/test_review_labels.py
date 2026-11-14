import json
from pathlib import Path

from app.review.labels import label, load_labels


def test_label_file_is_utf8_without_bom_and_contains_all_enums():
    path = Path(__file__).resolve().parents[2] / "contracts" / "review" / "labels.vi.json"
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    labels = json.loads(raw.decode("utf-8"))
    assert set(labels["verdict"]) == {"SATISFIED", "PARTIAL", "NOT_FOUND", "DEVIATES", "UNDETERMINED", "SKIPPED_BUDGET"}
    assert set(labels["case_status"]) == {"DRAFT", "CONFIRMING", "READY", "RUNNING", "PARTIAL", "COMPLETE", "FAILED"}
    assert set(labels["job_state"]) == {"QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}
    assert set(labels["decision"]) == {"NONE", "ACCEPT", "REJECT", "EDIT"}
    assert label("verdict", "SATISFIED") == "Đã đáp ứng"
    assert label("verdict", "UNKNOWN") == "UNKNOWN"


def test_error_codes_are_labeled():
    from app.api.review import ErrorCode
    labels = load_labels()["errors"]
    assert {item.value for item in ErrorCode} == set(labels)
