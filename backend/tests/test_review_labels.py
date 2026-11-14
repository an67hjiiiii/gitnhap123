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
    assert set(labels["route_reason"]) == {
        "SINGLE_IDEA", "MULTI_IDEA", "MULTI_QUANTITY", "SHORT_REQUEST", "C_NOT_AVAILABLE",
    }
    assert label("verdict", "SATISFIED") == "Đã đáp ứng"
    assert label("verdict", "UNKNOWN") == "UNKNOWN"


def test_error_codes_are_labeled():
    from app.api.review import ErrorCode
    labels = load_labels()["errors"]
    assert {item.value for item in ErrorCode} == set(labels)


def _strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}")


def test_labels_are_clean_vietnamese_utf8():
    from app.api.review import ErrorCode
    from app.review.schemas import Decision, JobState, Verdict
    path = Path(__file__).resolve().parents[2] / "contracts" / "review" / "labels.vi.json"
    text = path.read_bytes().decode("utf-8")  # strict decode: invalid UTF-8 raises
    labels = json.loads(text)
    bad = [(p, s) for p, s in _strings(labels)
           if not s.strip() or "?" in s or "\ufffd" in s or any(m in s for m in ("\u00c3", "\u00c4", "\u00e1\u00bb"))]
    assert bad == []
    assert set(labels["verdict"]) == {item.value for item in Verdict}
    assert set(labels["job_state"]) == {item.value for item in JobState}
    assert set(labels["decision"]) == {item.value for item in Decision}
    assert set(labels["errors"]) == {item.value for item in ErrorCode}
    for code, entry in labels["errors"].items():
        assert entry.get("what") and entry.get("todo"), code

def test_progress_and_friendly_error_labels_are_complete():
    labels = load_labels()
    assert set(labels["progress"]) == {
        "understanding", "planning", "plan_ready", "searching", "step_done", "writing", "failed",
        "multi_search", "retrying", "verifying",
    }
    assert set(labels["friendly_errors"]) == {
        "PLAN_REJECTED", "PROVIDER_LIMIT", "CONDITION_NOT_AVAILABLE", "PIPELINE_RUN_FAILED",
        "UNKNOWN", "RATE_LIMITED", "SOURCE_NOT_FOUND", "CONVERSATION_NOT_FOUND",
        "MESSAGE_REQUIRED", "PRODUCT_PROVIDER_NOT_CONFIGURED", "DERIVED_INDEX_UNAVAILABLE",
    }
    for entry in labels["friendly_errors"].values():
        assert entry["message"] and entry["hint"]


