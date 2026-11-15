"""Bảng điều khiển quản trị (/api/admin/system, /api/admin/audit), chỉ ADMIN dùng được.

/system: số đo thật tại thời điểm gọi (psutil, Ollama /api/tags và /api/ps, pg_database_size, kích thước thư mục Qdrant).
Không có số nào được ước lượng hay điền sẵn: đo không được thì trả None, giao diện hiện "Chưa đo".
/audit: nhật ký hoạt động của mọi tài khoản (thao tác, đối tượng, mã trạng thái), không chứa nội dung câu hỏi hay tài liệu.
"""
from __future__ import annotations

import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

STARTED_AT = time.time()
COUNTED = ("users", "sessions", "knowledge_sources", "knowledge_chunks", "conversations", "runs")


def dir_size(path: str | Path) -> int | None:
    """Tổng dung lượng các tệp trong thư mục (byte); None nếu thư mục không tồn tại."""
    p = Path(path)
    if not p.exists():
        return None
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue  # tệp đang bị khóa/ghi dở: bỏ qua, không làm hỏng cả số đo
    return total


def host_metrics(data_dir: str | Path) -> dict[str, Any]:
    try:
        import psutil  # type: ignore
    except ImportError:
        return {"available": False}
    vm = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage(str(Path(data_dir).resolve().anchor or data_dir))
        disk_d = {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free, "percent": disk.percent}
    except Exception:
        disk_d = None
    proc = psutil.Process(os.getpid())
    return {
        "available": True,
        "cpu_percent": psutil.cpu_percent(interval=0.25),
        "cpu_count": psutil.cpu_count(logical=True),
        "ram_total_bytes": vm.total, "ram_used_bytes": vm.total - vm.available, "ram_percent": vm.percent,
        "disk": disk_d,
        "boot_time": datetime.fromtimestamp(psutil.boot_time(), timezone.utc).isoformat(),
        "backend_rss_bytes": proc.memory_info().rss,
        "backend_uptime_s": round(time.time() - STARTED_AT),
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }


async def ollama_metrics(base_url: str, chat_model: str, embed_model: str) -> dict[str, Any]:
    out: dict[str, Any] = {"base_url": base_url, "chat_model": chat_model, "embed_model": embed_model,
                           "reachable": False, "models": [], "loaded": []}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            tags = (await client.get(f"{base_url}/api/tags")).json()
            out["reachable"] = True
            out["models"] = [{"name": m.get("name"), "size_bytes": m.get("size"), "family": (m.get("details") or {}).get("family"),
                              "parameter_size": (m.get("details") or {}).get("parameter_size"),
                              "quantization": (m.get("details") or {}).get("quantization_level")} for m in tags.get("models", [])]
            try:
                ps = (await client.get(f"{base_url}/api/ps")).json()
                out["loaded"] = [{"name": m.get("name"), "size_bytes": m.get("size"), "vram_bytes": m.get("size_vram"),
                                  "expires_at": m.get("expires_at")} for m in ps.get("models", [])]
            except Exception:
                out["loaded"] = None
    except Exception as exc:
        out["error"] = type(exc).__name__
    names = {m["name"] for m in out["models"]}
    out["chat_model_ready"] = (chat_model in names or f"{chat_model}:latest" in names) if out["reachable"] else None
    out["embed_model_ready"] = (embed_model in names or f"{embed_model}:latest" in names) if out["reachable"] else None
    try:
        from app.core.telemetry import gpu_memory_mb, model_rss_mb
        out["process_rss_mb"] = model_rss_mb()
        out["gpu_memory_mb"] = gpu_memory_mb()
    except Exception:
        out["process_rss_mb"] = out["gpu_memory_mb"] = None
    return out


def db_metrics(factory) -> dict[str, Any]:
    out: dict[str, Any] = {"reachable": False, "counts": {}, "size_bytes": None, "version": None, "connections": None}
    try:
        with factory() as db:
            out["dialect"] = db.bind.dialect.name
            for t in COUNTED:
                try:
                    out["counts"][t] = int(db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0)
                except Exception:
                    db.rollback(); out["counts"][t] = None
            try:
                out["counts"]["active_sessions"] = int(db.execute(text(
                    "SELECT COUNT(*) FROM sessions WHERE revoked_at IS NULL AND expires_at > CURRENT_TIMESTAMP")).scalar() or 0)
            except Exception:
                db.rollback(); out["counts"]["active_sessions"] = None
            if out["dialect"] == "postgresql":
                out["size_bytes"] = int(db.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
                out["version"] = str(db.execute(text("SHOW server_version")).scalar())
                out["connections"] = int(db.execute(text(
                    "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()")).scalar() or 0)
            try:
                out["alembic_version"] = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception:
                db.rollback(); out["alembic_version"] = None
            out["reachable"] = True
    except Exception as exc:
        out["error"] = type(exc).__name__
    return out


def qdrant_metrics(path: str) -> dict[str, Any]:
    p = Path(path)
    coll = p / "collection"
    return {"path": str(p), "exists": p.exists(), "size_bytes": dir_size(p),
            "collections": sorted(d.name for d in coll.iterdir() if d.is_dir()) if coll.exists() else [],
            "backend": os.getenv("VECTOR_INDEX_BACKEND", "disabled")}


def build_router(*, current_user: Callable[[Request], dict], session_factory: Callable[[], Any], vector_path: str) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin-system"])

    def admin(request: Request) -> dict:
        user = current_user(request)
        if str(user.get("role", "")).upper() != "ADMIN":
            raise HTTPException(403, "Chỉ quản trị viên được dùng chức năng này.")
        return user

    @router.get("/system")
    async def system(request: Request) -> dict:
        admin(request)
        factory = session_factory()
        host, db, qd = await run_in_threadpool(lambda: (host_metrics(vector_path), db_metrics(factory), qdrant_metrics(vector_path)))
        ollama = await ollama_metrics(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
                                      os.getenv("LOCAL_LLM_MODEL", "qwen3:4b"), os.getenv("EMBEDDING_MODEL", "nomic-embed-text"))
        return {"measured_at": datetime.now(timezone.utc).isoformat(), "host": host, "ollama": ollama, "postgres": db, "qdrant": qd,
                "provider": os.getenv("PROVIDER", "fake"), "embedding_backend": os.getenv("EMBEDDING_BACKEND", "hash")}

    @router.get("/audit")
    def audit(request: Request, page: int = 1, size: int = 20, q: str = "", errors: bool = False) -> dict:
        """Nhật ký hoạt động của mọi tài khoản, mới nhất trước; q lọc theo thao tác, đối tượng hoặc tài khoản."""
        admin(request)
        size, page = max(5, min(size, 100)), max(1, page)
        conds, args = [], {"l": size, "off": (page - 1) * size, "q": f"%{q.strip()}%"}
        if q.strip():
            conds.append("(a.action ILIKE :q OR a.target ILIKE :q OR u.email ILIKE :q OR u.display_name ILIKE :q)")
        if errors:
            conds.append("a.status >= 400")
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        base = "FROM studio_activity a LEFT JOIN users u ON u.user_id = a.owner_user_id"
        with session_factory()() as db:
            if db.bind.dialect.name != "postgresql":  # SQLite trong test không có ILIKE
                where = where.replace(" ILIKE ", " LIKE ")
            total = int(db.execute(text(f"SELECT COUNT(*) {base}{where}"), args).scalar() or 0)
            rows = db.execute(text(f"SELECT a.action, a.target, a.status, a.created_at, u.email, u.display_name, u.role {base}{where} "
                                   "ORDER BY a.created_at DESC, a.activity_id DESC LIMIT :l OFFSET :off"), args).mappings().all()
        def iso(v):
            return v.isoformat() if hasattr(v, "isoformat") else v
        return {"rows": [{**dict(r), "created_at": iso(r["created_at"])} for r in rows],
                "total": total, "page": page, "size": size, "pages": max(1, -(-total // size))}

    return router
