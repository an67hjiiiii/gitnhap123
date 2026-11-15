"""Đo tài nguyên: % CPU toàn máy trong lượt chạy và RAM tiến trình mô hình; thiếu số đo thì trả None, không đoán."""
from app.core import telemetry
from app.core.types import RunMetrics


def test_cpu_percent_is_bounded_or_none():
    start = telemetry.cpu_times()
    sum(i * i for i in range(200_000))
    value = telemetry.cpu_busy_percent(start)
    assert value is None or 0.0 <= value <= 100.0
    assert telemetry.cpu_busy_percent(None) is None


def test_new_metrics_default_to_not_measured():
    d = RunMetrics().to_dict()
    assert d["cpu_percent"] is None and d["model_rss_mb"] is None
