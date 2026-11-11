"""Đếm token bằng tokenizer Qwen3 offline (đã pin SHA-256), không ước lượng bằng số ký tự.

Chuyển từ C1SE.27 (context_budget). Tokenizer: backend/app/assets/qwen3/tokenizer.json.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

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


def tokenizer_identity() -> dict:
    return {"tokenizer": "Qwen/Qwen3-4B", "tokenizer_sha256": TOKENIZER_SHA256}


__all__ = ["TokenBudgetError", "count_qwen_tokens", "tokenizer_identity"]
