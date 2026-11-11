"""API bổ sung cho giao diện Studio của C1SE.27 (tích hợp vào CAP1).

- POST /api/studio/retrieval-test: thử truy xuất trong kho của người dùng, không gọi LLM.
- POST /api/studio/compare: chạy cùng một yêu cầu dưới nhiều điều kiện (A, B, C, C-P, C-N, C-O).
- GET  /api/studio/admin/*: tổng quan bảng, xem bảng (đã ẩn cột bí mật), tự kiểm tra cấu hình, chẩn đoán CSDL. Chỉ ADMIN.

Router được dựng bằng các hàm phụ thuộc của main.py để không nhân đôi logic xác thực và phân quyền.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

# Cột được phép xem trong trang quản trị; cột bí mật (password_hash, token_hash) không bao giờ trả về.
ADMIN_TABLES: dict[str, tuple[str, ...]] = {
    "users": ("user_id", "email", "username", "display_name", "role", "status", "created_at", "last_login_at"),
    "sessions": ("session_id", "user_id", "created_at", "expires_at", "revoked_at"),
    "knowledge_sources": ("source_id", "owner_user_id", "source_name", "status", "created_at"),
    "knowledge_chunks": ("chunk_id", "source_id", "chunk_index", "indexing_version", "created_at"),
    "conversations": ("conversation_id", "owner_user_id", "title", "created_at", "updated_at"),
    "conversation_messages": ("message_id", "conversation_id", "role", "run_id", "created_at"),
    "runs": ("run_id", "owner_user_id", "condition", "status", "model", "config_hash", "query", "created_at"),
}


class RetrievalTestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=20)
    source_ids: list[str] | None = None


class CompareRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conditions: list[str] = Field(default_factory=lambda: ["A", "B", "C"], min_length=1, max_length=6)


def _loopback(url: str | None) -> bool | None:
    if not url:
        return None
    host = urlparse(url).hostname or ""
    return host in {"127.0.0.1", "localhost", "::1"}


def build_router(
    *,
    current_user: Callable[[Request], dict],
    owner_pipeline: Callable[..., Any],
    session_factory: Callable[[], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/studio", tags=["studio"])

    def require_admin(request: Request) -> dict:
        user = current_user(request)
        if str(user.get("role", "")).upper() != "ADMIN":
            raise HTTPException(403, "Chức năng này dành cho quản trị hệ thống.")
        if session_factory() is None:
            raise HTTPException(503, "Trang quản trị cần APP_STORAGE_BACKEND=postgres.")
        return user

    @router.post("/retrieval-test")
    def retrieval_test(body: RetrievalTestRequest, request: Request) -> dict:
        user = current_user(request)
        pipeline = owner_pipeline(user)
        started = time.perf_counter()
        chunks = pipeline.source_store.chunks(body.source_ids)
        trace: dict = {}
        hits = pipeline._retrieve_candidates(  # dùng đúng đường truy xuất của pipeline
            body.query, chunks, top_k=body.top_k, min_score=0.0, source_ids=body.source_ids, fallback_trace=trace,
        )
        return {
            "query": body.query,
            "top_k": body.top_k,
            "retrieval_backend": pipeline.retrieval_backend,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "total_chunks": len(chunks),
            "fallback": trace or None,
            "results": [
                {"chunk_id": c.chunk_id, "source_id": c.source_id, "source_name": c.source_name,
                 "score": round(float(c.score), 4), "text": c.text}
                for c in hits
            ],
        }

    @router.post("/compare")
    async def compare(body: CompareRequest, request: Request) -> dict:
        user = current_user(request)
        conditions = [c.strip().upper() for c in body.conditions]
        runs = []
        for condition in conditions:
            run = await owner_pipeline(user).run(body.message.strip(), condition)
            runs.append(run)
        return {"message": body.message.strip(), "conditions": conditions, "runs": runs,
                "note": "Một lượt so sánh là số mô tả kỹ thuật, không phải kết quả thực nghiệm."}

    @router.get("/admin/overview")
    def admin_overview(request: Request) -> dict:
        require_admin(request)
        with session_factory()() as db:
            counts = {t: int(db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0) for t in ADMIN_TABLES}
        return {"tables": [{"name": t, "row_count": n} for t, n in counts.items()]}

    @router.get("/admin/table/{name}")
    def admin_table(name: str, request: Request, limit: int = 50, offset: int = 0) -> dict:
        require_admin(request)
        if name not in ADMIN_TABLES:
            raise HTTPException(404, "Bảng không có trong danh sách được xem.")
        cols = ADMIN_TABLES[name]
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        order = "created_at DESC" if "created_at" in cols else f'"{cols[0]}"'
        sql = text(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{name}" ORDER BY {order} LIMIT :l OFFSET :o')
        with session_factory()() as db:
            rows = db.execute(sql, {"l": limit, "o": offset}).mappings().all()
            total = int(db.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar() or 0)
        def cell(v):
            return v.isoformat() if isinstance(v, datetime) else v
        return {"name": name, "columns": list(cols), "total": total,
                "rows": [{k: cell(v) for k, v in r.items()} for r in rows]}

    @router.get("/admin/security-audit")
    def security_audit(request: Request) -> dict:
        require_admin(request)
        ollama = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        db_url = os.getenv("DATABASE_URL", "")
        checks = {
            "llm_endpoint_loopback": _loopback(ollama),
            "database_host_loopback": _loopback(db_url.replace("+psycopg", "")) if db_url else None,
            "vector_index": os.getenv("VECTOR_INDEX_BACKEND", "disabled"),
            "provider": os.getenv("PROVIDER", "fake"),
            "app_env": os.getenv("APP_ENV", "development"),
        }
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "status": "NOT_VERIFIED",
            "note": "Tự kiểm tra cấu hình chạy cục bộ; chưa kiểm chứng egress mạng, không phải chứng nhận bảo mật.",
        }

    @router.get("/admin/db-diagnostic")
    def db_diagnostic(request: Request) -> dict:
        require_admin(request)
        with session_factory()() as db:
            version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            orphan_chunks = int(db.execute(text(
                "SELECT COUNT(*) FROM knowledge_chunks c LEFT JOIN knowledge_sources s ON s.source_id = c.source_id "
                "WHERE s.source_id IS NULL")).scalar() or 0)
            orphan_messages = int(db.execute(text(
                "SELECT COUNT(*) FROM conversation_messages m LEFT JOIN conversations c ON c.conversation_id = m.conversation_id "
                "WHERE c.conversation_id IS NULL")).scalar() or 0)
            present = {r[0] for r in db.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))}
        missing = sorted(set(ADMIN_TABLES) - present)
        return {"alembic_version": version, "tables_expected": len(ADMIN_TABLES), "tables_missing": missing,
                "orphan_chunks": orphan_chunks, "orphan_messages": orphan_messages,
                "ok": not missing and orphan_chunks == 0 and orphan_messages == 0}

    return router
