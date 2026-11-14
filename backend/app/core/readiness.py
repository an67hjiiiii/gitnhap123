from __future__ import annotations

import os

import httpx
from sqlalchemy import text


def check_postgres(session_factory) -> str:
    if os.getenv("APP_STORAGE_BACKEND", "postgres").strip().lower() != "postgres":
        return "skipped"
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "fail"


def check_vector(store) -> str:
    backend = os.getenv("VECTOR_BACKEND", os.getenv("VECTOR_INDEX_BACKEND", "disabled")).strip().lower()
    if backend in {"", "disabled", "off", "none"}:
        return "skipped"
    if store is None:
        return "skipped"
    try:
        if hasattr(store, "count"):
            store.count()
        return "ok"
    except Exception:
        return "fail"


async def check_ollama() -> str:
    configured = (os.getenv("PROVIDER", "fake").strip().lower() == "ollama" or
                  os.getenv("EMBEDDING_BACKEND", "").strip().lower() in {"ollama", "ollama-embeddings"})
    if not configured:
        return "skipped"
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(base + "/api/tags")
            response.raise_for_status()
        return "ok"
    except Exception:
        return "fail"
