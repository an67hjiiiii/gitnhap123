"""Đếm token bằng tokenizer Qwen3 offline (đã pin SHA-256), không ước lượng bằng số ký tự.

Chuyển từ C1SE.27 (context_budget). Tokenizer: backend/app/assets/qwen3/tokenizer.json.
"""
from __future__ import annotations

import hashlib
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.types import SourceChunk

TOKENIZER_PATH = Path(__file__).resolve().parents[1] / "assets" / "qwen3" / "tokenizer.json"
TOKENIZER_SHA256 = "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"


class TokenBudgetError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _tokenizer():
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:  # pragma: no cover - phụ thuộc bắt buộc trong requirements
        raise TokenBudgetError("Thiếu thư viện tokenizers.") from exc
    try:
        digest = hashlib.sha256(TOKENIZER_PATH.read_bytes()).hexdigest()
    except OSError as exc:
        raise TokenBudgetError("Thiếu tokenizer offline Qwen3.") from exc
    if digest != TOKENIZER_SHA256:
        raise TokenBudgetError("Tokenizer Qwen3 không khớp SHA-256 đã kiểm chứng.")
    tokenizer = Tokenizer.from_file(str(TOKENIZER_PATH))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def count_qwen_tokens(text: str) -> int:
    return len(_tokenizer().encode(text, add_special_tokens=False).ids)


def count_prompt_tokens(text: str) -> int:
    """Count prompt tokens accurately with offline Qwen3 tokenizer and conservative fallback."""
    clean = str(text or "")
    if not clean:
        return 0
    try:
        return count_qwen_tokens(clean)
    except TokenBudgetError:
        return max(1, (len(clean) + 1) // 2)


def _system_total_ram_mb() -> int | None:
    """Best-effort physical RAM detection for num_ctx guardrails without external deps."""
    try:
        if os.name == "nt":
            import ctypes

            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys // (1024 * 1024))
        elif hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if pages > 0 and page_size > 0:
                return int((pages * page_size) // (1024 * 1024))
    except Exception:
        return None
    return None


def resolve_max_safe_num_ctx() -> int:
    """Upper safe bound for Ollama num_ctx constrained by explicit cap and host RAM."""
    try:
        cap = int(os.getenv("OLLAMA_MAX_NUM_CTX", "16384") or 16384)
    except ValueError:
        cap = 16384
    cap = max(2048, min(cap, 32768))
    ram_mb = _system_total_ram_mb()
    if ram_mb is not None:
        # Windows/Linux physical memory reports slightly below nominal (e.g. ~7886 MB on an 8 GB host).
        if ram_mb < 6144:
            cap = min(cap, 4096)
        elif ram_mb < 14336:
            cap = min(cap, 8192)
    return max(2048, cap)


def resolve_product_num_ctx() -> int:
    """Configured num_ctx for Product Mode, clamped safely against hardware limits.

    Precedence: PRODUCT_NUM_CTX > OLLAMA_NUM_CTX > default 8192, bounded by host RAM cap.
    """
    safe_cap = resolve_max_safe_num_ctx()
    raw = os.getenv("PRODUCT_NUM_CTX", "").strip() or os.getenv("OLLAMA_NUM_CTX", "").strip() or "8192"
    try:
        requested = int(raw or "8192")
    except ValueError:
        requested = 8192
    return max(2048, min(requested, safe_cap))


def fit_evidence_to_prompt_budget(
    evidence: list[SourceChunk],
    *,
    system: str,
    prompt_without_evidence: str,
    num_ctx: int,
    output_reserve: int,
    overhead_tokens: int = 256,
) -> tuple[list[SourceChunk], dict[str, Any]]:
    """Keep query + #1 ranked chunks intact inside total num_ctx budget by trimming trailing evidence cleanly."""
    fixed_tokens = (
        count_prompt_tokens(system)
        + count_prompt_tokens(prompt_without_evidence)
        + max(0, int(overhead_tokens))
    )
    reserved = max(64, int(output_reserve))
    available = int(num_ctx) - reserved - fixed_tokens
    if available < 96:
        return [], {
            "overflow": True,
            "trimmed_trailing": False,
            "trimmed_top": False,
            "available_evidence_tokens": available,
            "fixed_tokens": fixed_tokens,
            "kept": 0,
            "dropped": len(evidence),
        }

    kept: list[SourceChunk] = []
    used = 0
    for idx, chunk in enumerate(evidence):
        prefix = f"[{chunk.chunk_id}] "
        sep = "\n\n" if kept else ""
        piece = f"{sep}{prefix}{chunk.text}"
        cost = count_prompt_tokens(piece)
        if used + cost <= available:
            kept.append(chunk)
            used += cost
            continue
        if not kept:
            # First ranked chunk alone exceeds available budget: trim only its tail safely.
            lo, hi = 0, len(chunk.text)
            best = ""
            while lo <= hi:
                mid = (lo + hi) // 2
                candidate = f"{prefix}{chunk.text[:mid].rstrip()}"
                if count_prompt_tokens(candidate) <= available:
                    best = chunk.text[:mid].rstrip()
                    lo = mid + 1
                else:
                    hi = mid - 1
            if len(best) >= 32:
                kept.append(SourceChunk(**{**chunk.__dict__, "text": best}))
                return kept, {
                    "overflow": False,
                    "trimmed_trailing": len(evidence) > 1,
                    "trimmed_top": True,
                    "available_evidence_tokens": available,
                    "fixed_tokens": fixed_tokens,
                    "kept": 1,
                    "dropped": len(evidence) - 1,
                }
            return [], {
                "overflow": True,
                "trimmed_trailing": False,
                "trimmed_top": False,
                "available_evidence_tokens": available,
                "fixed_tokens": fixed_tokens,
                "kept": 0,
                "dropped": len(evidence),
            }
        # Preserve rank ordering without skipping higher chunks to backfill trailing noise.
        return kept, {
            "overflow": False,
            "trimmed_trailing": idx < len(evidence),
            "trimmed_top": False,
            "available_evidence_tokens": available,
            "fixed_tokens": fixed_tokens,
            "kept": len(kept),
            "dropped": len(evidence) - len(kept),
        }

    return kept, {
        "overflow": False,
        "trimmed_trailing": False,
        "trimmed_top": False,
        "available_evidence_tokens": available,
        "fixed_tokens": fixed_tokens,
        "kept": len(kept),
        "dropped": 0,
    }


def tokenizer_identity() -> dict:
    return {"tokenizer": "Qwen/Qwen3-4B", "tokenizer_sha256": TOKENIZER_SHA256}


__all__ = [
    "TokenBudgetError",
    "count_prompt_tokens",
    "count_qwen_tokens",
    "fit_evidence_to_prompt_budget",
    "resolve_max_safe_num_ctx",
    "resolve_product_num_ctx",
    "tokenizer_identity",
]
