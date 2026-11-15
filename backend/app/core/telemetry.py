from __future__ import annotations
import os
import subprocess


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


def model_rss_mb() -> float | None:
    """RAM của tiến trình mô hình cục bộ (mọi tiến trình tên bắt đầu bằng "ollama"); None nếu không thấy."""
    try:
        import psutil  # type: ignore
        total = 0
        for proc in psutil.process_iter(["name", "memory_info"]):
            name = (proc.info.get("name") or "").lower()
            if name.startswith("ollama") and proc.info.get("memory_info"):
                total += proc.info["memory_info"].rss
        return round(total / (1024 * 1024), 2) if total else None
    except Exception:
        return None


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
