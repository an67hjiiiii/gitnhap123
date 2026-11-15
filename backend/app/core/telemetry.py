from __future__ import annotations
import os
import subprocess
import threading
import time


def process_rss_mb() -> float | None:
    try:
        import psutil  # type: ignore
        return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 2)
    except Exception:
        return None



def cpu_times():
    """Mốc thời gian CPU toàn máy (psutil); dùng với cpu_busy_percent để lấy % CPU trung bình trong một lượt."""
    try:
        import psutil  # type: ignore
        return psutil.cpu_times()
    except Exception:
        return None


def cpu_busy_percent(start) -> float | None:
    """% CPU toàn máy trung bình từ mốc start đến hiện tại (gồm cả tiến trình khác, kể cả Ollama)."""
    if start is None:
        return None
    try:
        import psutil  # type: ignore
        end = psutil.cpu_times()
        total = sum(end) - sum(start)
        return round(100.0 * (1.0 - (end.idle - start.idle) / total), 1) if total > 0 else None
    except Exception:
        return None


_MODEL_RSS = {"value": None, "at": 0.0, "busy": False}
_MODEL_RSS_TTL_S = 60.0


def _scan_model_rss() -> float | None:
    try:
        import psutil  # type: ignore
        # Chỉ đọc bộ nhớ của tiến trình ollama; duyệt toàn bộ tiến trình mất 1-3 giây trên Windows.
        total = 0
        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").lower().startswith("ollama"):
                try:
                    total += proc.memory_info().rss
                except Exception:
                    continue
        return round(total / (1024 * 1024), 2) if total else None
    except Exception:
        return None


def _refresh_model_rss() -> None:
    try:
        _MODEL_RSS["value"] = _scan_model_rss()
        _MODEL_RSS["at"] = time.monotonic()
    finally:
        _MODEL_RSS["busy"] = False


def model_rss_mb() -> float | None:
    """RAM của tiến trình mô hình cục bộ (mọi tiến trình tên bắt đầu bằng "ollama"); None nếu chưa đo được.
    Không chặn lượt hỏi: trả số đo gần nhất (tối đa ~60 giây trước) và làm mới ở luồng nền; lần đầu có thể là None."""
    if time.monotonic() - float(_MODEL_RSS["at"]) > _MODEL_RSS_TTL_S and not _MODEL_RSS["busy"]:
        _MODEL_RSS["busy"] = True
        threading.Thread(target=_refresh_model_rss, name="model-rss", daemon=True).start()
    value = _MODEL_RSS["value"]
    return value if isinstance(value, (int, float)) else None


def gpu_memory_mb() -> float | None:
    """Best-effort NVIDIA process/device memory snapshot; N/A is valid on CPU-only machines."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode != 0:
            return None
        vals = [float(x.strip()) for x in proc.stdout.splitlines() if x.strip()]
        return max(vals) if vals else None
    except Exception:
        return None
