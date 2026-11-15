"""Chấm mù: người chấm không thấy điều kiện, thứ tự xáo theo người chấm, kiểm tra điểm, thống kê và độ đồng thuận."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis import blind_rating as br
from app.api.analysis import build_router

ROWS = [
    {"run_id": f"r{i}{c}", "condition": c, "question": f"Q{i}", "answer": f"trả lời {c}{i}", "status": "COMPLETE",
     "key_points": ["ý một", "ý hai"], "auto_hits": [True, False]}
    for i in range(4) for c in ("A", "C")
] + [{"run_id": "rf", "condition": "C", "question": "Q9", "answer": "Pipeline failed", "status": "FAILED", "key_points": ["x"]}]


def test_failed_runs_are_not_rated_and_view_hides_condition():
    items, failed = br.build_items(ROWS)
    assert len(items) == 8 and failed == [{"run_id": "rf", "condition": "C", "question": "Q9"}]
    view = br.rater_view(items, "u1", "s1")
    assert all(set(v) == {"item_id", "question", "answer", "key_points"} for v in view)
    assert [v["item_id"] for v in view] == [v["item_id"] for v in br.rater_view(items, "u1", "s1")]  # ổn định
    assert [v["item_id"] for v in view] != [v["item_id"] for v in br.rater_view(items, "u2", "s1")] or len(items) < 3


def test_validate_score():
    ok = br.validate_score({"key_points": [True, False], "correct": 4, "complete": 3, "grounded": 5, "useful": 4}, 2)
    assert ok["fabricated"] is False and ok["correct"] == 4
    with pytest.raises(ValueError):
        br.validate_score({"key_points": [True], "correct": 4, "complete": 3, "grounded": 5, "useful": 4}, 2)
    with pytest.raises(ValueError):
        br.validate_score({"key_points": [True, True], "correct": 6, "complete": 3, "grounded": 5, "useful": 4}, 2)


def test_krippendorff_alpha():
    assert br.krippendorff_interval([[1, 1], [3, 3], [5, 5]]) == 1.0
    assert br.krippendorff_interval([[1, 5], [5, 1], [3, 3]]) < 0
    assert br.krippendorff_interval([[2]]) is None


def test_aggregate_counts_failed_as_worst_and_compares_by_question():
    items, failed = br.build_items(ROWS)
    ratings = []
    for it in items:
        good = it["condition"] == "C"
        for rater in ("u1", "u2"):
            ratings.append({"item_id": it["item_id"], "rater": rater, "scores": {
                "key_points": [True, good], "correct": 5 if good else 3, "complete": 5 if good else 2,
                "grounded": 4, "useful": 4, "fabricated": False}})
    out = br.aggregate(items, failed, ratings)
    assert out["conditions"]["C"]["failed_runs"] == 1 and out["conditions"]["C"]["kp_coverage"]["mean"] == 1.0
    cmp = out["comparisons"]["C_vs_A_kp_coverage"]
    assert cmp["pairs"] == 4 and cmp["mean_diff"] == 0.5  # Q9 chỉ có C (thất bại) nên không thành cặp
    assert out["agreement_alpha"]["correct"] == 1.0 and out["auto_vs_human_agreement"] == 0.75


def test_api_requires_postgres_and_validates():
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda u, *a: None, session_factory=lambda: None))
    c = TestClient(app)
    assert c.get("/api/studio/rating/join/ABCDEF").status_code == 503
    assert c.post("/api/studio/rating/studies", json={"title": "x", "items": []}).status_code == 422
