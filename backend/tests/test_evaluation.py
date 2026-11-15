"""Phòng đánh giá: độ phủ ý chính và thống kê, đối chiếu với giá trị chuẩn đã biết."""
import math

from app.analysis.evaluation import (compare_paired, cohens_dz, describe, keypoint_hits, t_critical,
                                     wilcoxon_signed_rank)


def test_keypoint_hits_ignore_accents_case_and_function_words():
    answer = "Webhook duoc gui lai TOI DA 8 LAN, lịch 1 phút, 5 phút. Merchant phải trả 2xx trong 10 giây."
    assert keypoint_hits(answer, ["Gửi lại tối đa 8 lần", "Trả mã 2xx trong 10 giây", "Ký bằng HMAC-SHA256"]) == [True, True, False]
    assert keypoint_hits("bất kỳ", ["và của là"]) == [False]  # ý toàn hư từ không tính là có


def test_t_critical_table_and_large_df():
    assert t_critical(1) == 12.706 and t_critical(9) == 2.262 and t_critical(30) == 2.042
    assert 2.000 <= t_critical(50) <= 2.021 and abs(t_critical(10_000) - 1.960) < 0.01


def test_describe_mean_sd_ci():
    d = describe([2, 4, 4, 4, 5, 5, 7, 9])
    assert d["n"] == 8 and d["mean"] == 5 and abs(d["sd"] - 2.138) < 0.001
    half = 2.365 * d["sd"] / math.sqrt(8)
    assert abs(d["ci95"][0] - (5 - half)) < 1e-9
    assert describe([]) == {"n": 0, "mean": None, "sd": None, "ci95": None}


def test_wilcoxon_matches_r_reference_example():
    # R: wilcox.test(x, y, paired = TRUE) -> V = 40, p-value = 0.03906
    x = [1.83, 0.50, 1.62, 2.48, 1.68, 1.88, 1.55, 3.06, 1.30]
    y = [0.878, 0.647, 0.598, 2.05, 1.06, 1.29, 1.06, 3.14, 1.29]
    r = wilcoxon_signed_rank(x, y)
    assert r["w_plus"] == 40 and r["method"] == "chính xác"
    assert abs(r["p_value"] - 0.03906) < 1e-4


def test_wilcoxon_with_ties_zero_diffs_and_normal_approximation():
    r = wilcoxon_signed_rank([3, 4, 5, 5, 2], [3, 3, 4, 4, 3])  # một cặp bằng nhau bị bỏ, ba hạng bằng nhau
    assert r["n"] == 4 and r["w_plus"] == 7.5 and r["w_minus"] == 2.5 and 0 < r["p_value"] <= 1
    big = wilcoxon_signed_rank([i + 0.5 for i in range(40)], list(range(40)))
    assert big["method"] == "xấp xỉ chuẩn" and big["p_value"] < 1e-6 and big["rank_biserial"] == 1
    assert wilcoxon_signed_rank([1, 2], [1, 2])["p_value"] is None


def test_cohens_dz_and_compare_paired_skip_missing():
    assert abs(cohens_dz([3, 4, 5], [1, 1, 1]) - 3.0) < 1e-9
    out = compare_paired([4, 5, None, 3], [3, 3, 2, 3])
    assert out["pairs"] == 3 and abs(out["mean_diff"] - 1.0) < 1e-9 and out["wilcoxon"]["n"] == 2


def test_readable_answer_unwraps_json_shapes():
    from app.analysis.evaluation import readable_answer
    assert readable_answer("Văn bản thường") == "Văn bản thường"
    assert readable_answer('{"answer": "8 lần"}') == "8 lần"
    assert readable_answer('{"task": "x", "task_results": [{"answer": "Một"}, {"answer": "Hai"}]}') == "Một\n\nHai"


def _eval_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.analysis import build_router

    class Pipeline:
        calls = []

        async def run(self, query, condition, *, source_ids=None, reply_in_query_language=False):
            Pipeline.calls.append((condition, source_ids, reply_in_query_language))
            return {"run_id": "run_1", "status": "COMPLETE", "answer": '{"answer": "Gửi lại tối đa 8 lần"}', "tasks": [{}, {}],
                    "metrics": {"latency_ms": 900, "input_tokens": 100, "output_tokens": 20, "llm_calls": 3}, "model": "m", "config_hash": "h"}

    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: Pipeline(),
                                    session_factory=lambda: None, provider_factory=lambda: None))
    return TestClient(app), Pipeline


def test_eval_run_returns_measured_metrics_and_keypoints(monkeypatch):
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    c, pipe = _eval_client()
    r = c.post("/api/studio/eval/run", json={"question": "Webhook gửi lại mấy lần?", "condition": "C", "source_ids": ["s1"],
                                             "key_points": ["gửi lại tối đa 8 lần", "lịch 24 giờ"]}).json()
    assert r["answer"] == "Gửi lại tối đa 8 lần" and r["key_point_hits"] == [True, False] and r["key_point_coverage"] == 0.5
    assert r["metrics"]["latency_ms"] == 900 and r["metrics"]["citations_valid"] is None and r["tasks"] == 2
    assert pipe.calls[-1] == ("C", ["s1"], True)  # mọi điều kiện cùng thiết lập ngôn ngữ
    assert c.post("/api/studio/eval/run", json={"question": "Webhook?", "condition": "Z"}).status_code == 422
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m0")
    assert c.post("/api/studio/eval/run", json={"question": "Webhook gửi lại?", "condition": "C"}).status_code == 400


def test_eval_stats_endpoint_and_validation():
    c, _ = _eval_client()
    body = {"scores": {"A": [3, 3, 4, None], "C": [4, 5, 4, 5]}, "pairs": [["C", "A"]]}
    r = c.post("/api/studio/eval/stats", json=body).json()
    assert r["conditions"]["A"]["n"] == 3 and r["comparisons"][0]["pairs"] == 3 and r["comparisons"][0]["wilcoxon"]["n"] == 2
    assert c.post("/api/studio/eval/stats", json={"scores": {"A": [1], "C": [1, 2]}}).status_code == 422
    assert c.post("/api/studio/eval/stats", json={"scores": {"A": [1]}, "pairs": [["A", "B"]]}).status_code == 422
