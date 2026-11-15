"""Số liệu biểu đồ Tổng quan: tính đúng từ lượt chạy, lượt không có số đo không bị đếm vào trung bình."""
from datetime import datetime, timedelta, timezone

from app.analysis.reading import usage_patterns

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _run(cond, status, hours_ago, latency=None, tokens=None):
    m = {}
    if latency is not None:
        m["latency_ms"] = latency
    if tokens is not None:
        m["input_tokens"], m["output_tokens"] = tokens - 10, 10
    return {"condition": cond, "status": status, "created_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "metrics": m}


def test_usage_patterns_counts_and_averages():
    runs = [_run("C", "COMPLETE", 1, 10_000, 4000), _run("C", "FAILED", 2, 30_000, 6000), _run("C", "COMPLETE", 26),
            _run("A", "PARTIAL", 3, 2_000, 1000), _run("A", "COMPLETE", 24 * 20, 4_000, 1200)]  # lượt cuối ngoài 14 ngày
    out = usage_patterns(runs, now=NOW)
    assert len(out["daily_status"]) == 14 and out["daily_status"][-1]["date"] == "2026-11-14"
    today = out["daily_status"][-1]
    assert (today["COMPLETE"], today["FAILED"], today["PARTIAL"]) == (1, 1, 1)
    assert sum(d["COMPLETE"] for d in out["daily_status"]) == 2  # lượt 20 ngày trước không nằm trong 14 ngày
    assert sum(map(sum, out["heatmap"])) == 5 and len(out["heatmap"]) == 7 and len(out["heatmap"][0]) == 24
    c = next(x for x in out["by_condition"] if x["condition"] == "C")
    assert (c["runs"], c["complete"], c["latency_avg_ms"], c["tokens_avg"]) == (3, 2, 20_000, 5000)  # lượt không số đo không tính
    assert out["latency_p50_ms"] == 4_000 and out["latency_p95_ms"] == 30_000


def test_usage_patterns_empty_is_null_not_zero():
    out = usage_patterns([], now=NOW)
    assert out["by_condition"] == [] and out["latency_p50_ms"] is None and out["latency_p95_ms"] is None
