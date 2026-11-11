"""Lưu vết nguồn gốc mỗi lượt chạy (Q0 của C1SE.27): mã nguồn, thư viện, mô hình, tokenizer, cách embed.

Chỉ ghi giá trị công khai (không đọc .env, không ghi secret). Không đo được thì để None, không điền thay.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from functools import lru_cache
from importlib import metadata
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[2]
PACKAGES = ("fastapi", "uvicorn", "pydantic", "sqlalchemy", "qdrant-client", "httpx", "tokenizers")
_SKIP_PARTS = {"__pycache__", ".venv", "node_modules", "runs", "data", "storage"}


@lru_cache(maxsize=1)
def code_manifest() -> dict:
    """SHA-256 của mã backend/app (*.py) + requirements, tính một lần mỗi tiến trình (mã đã nạp)."""
    files = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        if _SKIP_PARTS & set(path.relative_to(BACKEND).parts):
            continue
        files.append({"path": path.relative_to(BACKEND).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    req = BACKEND / "requirements.txt"
    if req.is_file():
        files.append({"path": "requirements.txt", "sha256": hashlib.sha256(req.read_bytes()).hexdigest()})
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"policy": "backend-app-py-v1", "manifest_sha256": hashlib.sha256(canonical).hexdigest(), "file_count": len(files)}


@lru_cache(maxsize=1)
def environment() -> dict:
    def ver(name: str):
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None
    return {"python": sys.version.split()[0], "platform": platform.platform(), "packages": {p: ver(p) for p in PACKAGES}}


def ollama_model_digest(model: str) -> str | None:
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        tags = httpx.get(f"{base}/api/tags", timeout=3).json().get("models", [])
    except Exception:
        return None
    hit = next((m for m in tags if model in (m.get("name"), m.get("model"))), None)
    return hit.get("digest") if hit else None


def build_provenance(*, provider_name: str, model: str, embedding_version: str | None, context_policy: str) -> dict:
    from app.research.token_budget import tokenizer_identity
    return {
        "schema_version": 1,
        "code": code_manifest(),
        "environment": environment(),
        "model": {"provider": provider_name, "name": model,
                  "digest": ollama_model_digest(model) if provider_name == "ollama" else None},
        "tokenizer": tokenizer_identity(),
        "embedding_version": embedding_version,
        "context_policy": context_policy,
        "quality_evaluation": "not_evaluated",
    }
