"""API bổ sung cho giao diện Studio của C1SE.27 (tích hợp vào CAP1).

- POST /api/studio/retrieval-test: thử truy xuất trong kho của người dùng, không gọi LLM.
- POST /api/studio/compare: chạy cùng một yêu cầu dưới nhiều điều kiện (A, B, C, C-P, C-N, C-O).
- GET  /api/studio/admin/*: tổng quan bảng, xem bảng (đã ẩn cột bí mật), tự kiểm tra cấu hình, chẩn đoán CSDL. Chỉ ADMIN.

Router được dựng bằng các hàm phụ thuộc của main.py để không nhân đôi logic xác thực và phân quyền.
"""
from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from app.core.access import Source, can_delete, load_member
from app.core.secret_audit import log_secret_access
from app.research.decomposer import detect_domains
from app.research.registry import OFFICE_PACK, PACKS, use_pack
from app.storage.postgres.models import KnowledgeSourceRecord

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
# Cột nội dung bị che với hàng thuộc không gian tổ chức: ADMIN hệ thống không đọc nội dung của tổ chức.
ORG_REDACTED: dict[str, tuple[str, ...]] = {
    "knowledge_sources": ("source_name",),
    "conversations": ("title",),
    "runs": ("query",),
}
ORG_MASK = "(không gian tổ chức)"


class RetrievalTestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=20)
    source_ids: list[str] | None = None
    domain: Literal[
        "software", "business", "marketing", "hr", "finance", "education", "analyst",
        "database", "api_architecture", "security",
    ] | None = None


class WorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default="", max_length=500)
    domain_pack: Literal[tuple(PACKS)] | None = None  # type: ignore[valid-type]  # None: tạo mới = office (11 Agent), sửa = giữ nguyên

    @field_validator("name")
    @classmethod
    def _non_blank_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tên không gian làm việc không được để trống.")
        return v


class WorkspaceItemBody(BaseModel):
    item_type: Literal["source", "conversation"]
    item_id: str = Field(min_length=1, max_length=160)


class CompareRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conditions: list[str] = Field(default_factory=lambda: ["A", "B", "C"], min_length=1, max_length=6)
    source_ids: list[str] | None = None  # tài liệu của không gian đang mở, như ô hỏi đáp
    domain_pack: Literal[tuple(PACKS)] | None = None  # type: ignore[valid-type]  # mặc định office (11 Agent 3D)


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
    owner_source_store: Callable[[dict], Any] | None = None,
    vector_store: Callable[[], Any] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/studio", tags=["studio"])

    def require_admin(request: Request) -> dict:
        user = current_user(request)
        if str(user.get("role", "")).upper() != "ADMIN":
            raise HTTPException(403, "Chức năng này dành cho quản trị hệ thống.")
        if session_factory() is None:
            raise HTTPException(503, "Trang quản trị cần APP_STORAGE_BACKEND=postgres.")
        return user

    def _personal_only(user: dict) -> None:
        if user.get("space_id"):
            raise HTTPException(400, "Chức năng này chỉ dùng trong không gian cá nhân.")

    @router.post("/retrieval-test")
    def retrieval_test(body: RetrievalTestRequest, request: Request) -> dict:
        user = current_user(request)
        pipeline = owner_pipeline(user)
        started = time.perf_counter()
        chunks = pipeline.source_store.chunks(body.source_ids)
        trace: dict = {}
        # Lọc chuyên môn: lấy rộng hơn rồi giữ đoạn mà bộ nhận diện miền của planner gắn đúng chuyên môn.
        hits = pipeline._retrieve_candidates(  # dùng đúng đường truy xuất của pipeline
            body.query, chunks, top_k=min(body.top_k * 5, 50) if body.domain else body.top_k,
            min_score=0.0, source_ids=body.source_ids, fallback_trace=trace,
        )
        detect_pack = "software" if body.domain in {"database", "api_architecture", "security"} else OFFICE_PACK
        with use_pack(detect_pack):
            domains = {c.chunk_id: detect_domains(c.text) if c.text.strip() else [] for c in hits}
        if body.domain:
            hits = [c for c in hits if body.domain in domains[c.chunk_id]][: body.top_k]
        if hits:
            log_secret_access(session_factory(), str(user["user_id"]), {c.source_id for c in hits}, "ASK")
        return {
            "query": body.query,
            "top_k": body.top_k,
            "retrieval_backend": pipeline.retrieval_backend,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "total_chunks": len(chunks),
            "fallback": trace or None,
            "results": [
                {"chunk_id": c.chunk_id, "source_id": c.source_id, "source_name": c.source_name,
                 "score": round(float(c.score), 4), "text": c.text, "domains": domains[c.chunk_id]}
                for c in hits
            ],
        }

    def _require_postgres() -> None:
        if owner_source_store is None or session_factory() is None:
            raise HTTPException(503, "Chức năng này cần APP_STORAGE_BACKEND=postgres.")

    def _delete_source(user: dict, source_id: str) -> int:
        """Xóa nguồn người dùng có quyền xóa (app.core.access): vector dẫn xuất, bản ghi nguồn, các đoạn (CASCADE)."""
        item = owner_source_store(user).source(source_id)  # kho theo phạm vi: không thấy thì như không tồn tại
        if not item:
            raise HTTPException(404, "Không tìm thấy tài liệu.")
        uid = str(user["user_id"])
        with session_factory()() as db:
            row = db.get(KnowledgeSourceRecord, source_id)
            if row is None:
                raise HTTPException(404, "Không tìm thấy tài liệu.")
            member = None if row.space_id is None else load_member(db, uid, row.space_id)
            source = Source(row.source_id, row.owner_user_id, row.space_id, row.department_id, row.classification)
            owner = row.owner_user_id
        if not can_delete(uid, member, source):
            raise HTTPException(403, "Bạn không có quyền xóa tài liệu này.")
        chunk_ids = [c["chunk_id"] for c in item.get("chunks", [])]
        try:
            store = vector_store() if vector_store else None
        except Exception:
            store = None  # chỉ mục dẫn xuất không mở được: vẫn xóa nguồn có thẩm quyền.
        if store is not None and chunk_ids:
            store.delete([f"{owner}:{cid}" for cid in chunk_ids])  # mã vector mang tên người tải lên
        with session_factory()() as db:
            db.execute(text("DELETE FROM knowledge_sources WHERE source_id = :s"), {"s": source_id})
            db.execute(text("DELETE FROM studio_workspace_items WHERE item_type = 'source' AND item_id = :s"), {"s": source_id})
            db.commit()
        return len(chunk_ids)

    @router.delete("/sources/{source_id}")
    def delete_source(source_id: str, request: Request) -> dict:
        """Xóa một tài liệu của chính người dùng."""
        user = current_user(request)
        _require_postgres()
        return {"deleted": source_id, "chunks_removed": _delete_source(user, source_id)}

    # ---------------- Không gian làm việc: nhóm tài liệu và cuộc trò chuyện của một người dùng
    def _sync_workspaces(db, owner: str) -> None:
        """Bảo đảm có ít nhất một không gian; gán mục chưa thuộc không gian nào vào không gian cũ nhất."""
        first = db.execute(text("SELECT workspace_id FROM studio_workspaces WHERE owner_user_id = :o ORDER BY created_at, workspace_id LIMIT 1"), {"o": owner}).scalar()
        if first is None:
            first = "ws_" + secrets.token_hex(8)
            db.execute(text("INSERT INTO studio_workspaces (workspace_id, owner_user_id, name, description) VALUES (:w, :o, 'Kho chính', '')"), {"w": first, "o": owner})
        db.execute(text("""INSERT INTO studio_workspace_items (workspace_id, item_type, item_id)
            SELECT :w, 'source', s.source_id FROM knowledge_sources s
            WHERE s.owner_user_id = :o AND s.space_id IS NULL AND NOT EXISTS (SELECT 1 FROM studio_workspace_items i WHERE i.item_type = 'source' AND i.item_id = s.source_id)
            ON CONFLICT (item_type, item_id) DO NOTHING"""), {"w": first, "o": owner})  # gán song song từ yêu cầu khác: giữ bản đã có
        db.execute(text("""INSERT INTO studio_workspace_items (workspace_id, item_type, item_id)
            SELECT :w, 'conversation', c.conversation_id FROM conversations c
            WHERE c.owner_user_id = :o AND c.space_id IS NULL AND NOT EXISTS (SELECT 1 FROM studio_workspace_items i WHERE i.item_type = 'conversation' AND i.item_id = c.conversation_id)
            ON CONFLICT (item_type, item_id) DO NOTHING"""), {"w": first, "o": owner})  # gán song song từ yêu cầu khác: giữ bản đã có

    def _owned_workspace(db, owner: str, workspace_id: str) -> None:
        if db.execute(text("SELECT 1 FROM studio_workspaces WHERE workspace_id = :w AND owner_user_id = :o"), {"w": workspace_id, "o": owner}).scalar() is None:
            raise HTTPException(404, "Không tìm thấy không gian làm việc.")

    @router.get("/workspaces")
    def list_workspaces(request: Request) -> list[dict]:
        user = current_user(request); _require_postgres(); _personal_only(user); owner = str(user["user_id"])
        with session_factory()() as db:
            _sync_workspaces(db, owner)
            db.commit()
            rows = db.execute(text("""SELECT w.workspace_id, w.name, w.description, w.domain_pack, w.created_at,
                    COUNT(*) FILTER (WHERE i.item_type = 'source') AS source_count,
                    COUNT(*) FILTER (WHERE i.item_type = 'conversation' AND NOT EXISTS (SELECT 1 FROM conversations hc WHERE hc.conversation_id = i.item_id AND hc.hidden_at IS NOT NULL)) AS conversation_count
                FROM studio_workspaces w LEFT JOIN studio_workspace_items i ON i.workspace_id = w.workspace_id
                WHERE w.owner_user_id = :o GROUP BY w.workspace_id ORDER BY w.created_at, w.workspace_id"""), {"o": owner}).mappings().all()
        return [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]

    @router.post("/workspaces")
    def create_workspace(body: WorkspaceBody, request: Request) -> dict:
        user = current_user(request); _require_postgres(); _personal_only(user)
        wid = "ws_" + secrets.token_hex(8)
        with session_factory()() as db:
            db.execute(text("INSERT INTO studio_workspaces (workspace_id, owner_user_id, name, description, domain_pack) VALUES (:w, :o, :n, :d, :p)"),
                       {"w": wid, "o": str(user["user_id"]), "n": body.name.strip(), "d": (body.description or "").strip(), "p": body.domain_pack or OFFICE_PACK})
            db.commit()
        return {"workspace_id": wid, "name": body.name.strip(), "description": (body.description or "").strip(),
                "domain_pack": body.domain_pack or OFFICE_PACK, "source_count": 0, "conversation_count": 0}

    @router.patch("/workspaces/{workspace_id}")
    def rename_workspace(workspace_id: str, body: WorkspaceBody, request: Request) -> dict:
        user = current_user(request); _require_postgres(); _personal_only(user); owner = str(user["user_id"])
        with session_factory()() as db:
            _owned_workspace(db, owner, workspace_id)
            db.execute(text("UPDATE studio_workspaces SET name = :n, description = :d, domain_pack = COALESCE(:p, domain_pack) WHERE workspace_id = :w"),
                       {"n": body.name.strip(), "d": (body.description or "").strip(), "p": body.domain_pack, "w": workspace_id})
            db.commit()
        return {"workspace_id": workspace_id, "name": body.name.strip(), "domain_pack": body.domain_pack}

    @router.get("/workspaces/{workspace_id}/items")
    def workspace_items(workspace_id: str, request: Request) -> dict:
        user = current_user(request); _require_postgres(); _personal_only(user); owner = str(user["user_id"])
        with session_factory()() as db:
            _owned_workspace(db, owner, workspace_id)
            rows = db.execute(text("SELECT item_type, item_id FROM studio_workspace_items WHERE workspace_id = :w"), {"w": workspace_id}).all()
        return {"source_ids": [r[1] for r in rows if r[0] == "source"], "conversation_ids": [r[1] for r in rows if r[0] == "conversation"]}

    @router.post("/workspaces/{workspace_id}/items")
    def assign_item(workspace_id: str, body: WorkspaceItemBody, request: Request) -> dict:
        user = current_user(request); _require_postgres(); _personal_only(user); owner = str(user["user_id"])
        table, key = {"source": ("knowledge_sources", "source_id"), "conversation": ("conversations", "conversation_id")}[body.item_type]
        with session_factory()() as db:
            _owned_workspace(db, owner, workspace_id)
            if db.execute(text(f"SELECT 1 FROM {table} WHERE {key} = :i AND owner_user_id = :o AND space_id IS NULL"), {"i": body.item_id, "o": owner}).scalar() is None:
                raise HTTPException(404, "Không tìm thấy mục cần gán.")
            db.execute(text("""INSERT INTO studio_workspace_items (workspace_id, item_type, item_id) VALUES (:w, :t, :i)
                ON CONFLICT (item_type, item_id) DO UPDATE SET workspace_id = EXCLUDED.workspace_id"""), {"w": workspace_id, "t": body.item_type, "i": body.item_id})
            db.commit()
        return {"workspace_id": workspace_id, "item_type": body.item_type, "item_id": body.item_id}

    @router.delete("/workspaces/{workspace_id}")
    def delete_workspace(workspace_id: str, request: Request, delete_sources: bool = False) -> dict:
        """Xóa không gian. Cuộc trò chuyện (có lượt chạy gắn kèm) chuyển sang không gian còn lại;
        tài liệu bị xóa hẳn nếu delete_sources=true, nếu không thì cũng chuyển sang."""
        user = current_user(request); _require_postgres(); _personal_only(user); owner = str(user["user_id"])
        with session_factory()() as db:
            _owned_workspace(db, owner, workspace_id)
            fallback = db.execute(text("""SELECT workspace_id FROM studio_workspaces WHERE owner_user_id = :o AND workspace_id <> :w
                ORDER BY created_at, workspace_id LIMIT 1"""), {"o": owner, "w": workspace_id}).scalar()
            if fallback is None:
                raise HTTPException(409, "Cần giữ lại ít nhất một không gian làm việc.")
            sources = [r[0] for r in db.execute(text("SELECT item_id FROM studio_workspace_items WHERE workspace_id = :w AND item_type = 'source'"), {"w": workspace_id})]
        removed = 0
        if delete_sources:
            for sid in sources:
                try:
                    _delete_source(user, sid); removed += 1
                except HTTPException:
                    pass  # tài liệu đã mất trước đó
        with session_factory()() as db:
            db.execute(text("UPDATE studio_workspace_items SET workspace_id = :f WHERE workspace_id = :w"), {"f": fallback, "w": workspace_id})
            db.execute(text("DELETE FROM studio_workspaces WHERE workspace_id = :w AND owner_user_id = :o"), {"w": workspace_id, "o": owner})
            db.commit()
        return {"deleted": workspace_id, "moved_to": fallback, "sources_deleted": removed}

    @router.post("/compare")
    async def compare(body: CompareRequest, request: Request) -> dict:
        user = current_user(request)
        conditions = [c.strip().upper() for c in body.conditions]
        runs = []
        for condition in conditions:
            try:
                run = await owner_pipeline(user).run(
                    body.message.strip(),
                    condition,
                    source_ids=body.source_ids,
                    domain_pack=body.domain_pack or OFFICE_PACK,
                )
            except LookupError as exc:
                raise HTTPException(404, "Không tìm thấy tài liệu đã chọn.") from exc
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
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
    def admin_table(name: str, request: Request, limit: int = 50, offset: int = 0, q: str = "") -> dict:
        require_admin(request)
        if name not in ADMIN_TABLES:
            raise HTTPException(404, "Bảng không có trong danh sách được xem.")
        cols = ADMIN_TABLES[name]
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        order = "created_at DESC" if "created_at" in cols else f'"{cols[0]}"'
        masked = ORG_REDACTED.get(name, ())

        def expr(c: str) -> str:  # cột nội dung của hàng tổ chức thay bằng nhãn, kể cả khi tìm kiếm (không dò được)
            return f"""(CASE WHEN space_id IS NULL THEN CAST("{c}" AS TEXT) ELSE '{ORG_MASK}' END)""" if c in masked else f'"{c}"'
        # Tìm trong các cột đã cho phép xem; từ khóa đi qua tham số, tên cột lấy từ danh sách cố định.
        where = (" WHERE " + " OR ".join(f"CAST({expr(c)} AS TEXT) ILIKE :q" for c in cols)) if q.strip() else ""
        params = {"l": limit, "o": offset, "q": f"%{q.strip()}%"}
        sql = text(f'SELECT {", ".join(expr(c) + " AS " + chr(34) + c + chr(34) for c in cols)} FROM "{name}"{where} ORDER BY {order} LIMIT :l OFFSET :o')
        with session_factory()() as db:
            rows = db.execute(sql, params).mappings().all()
            total = int(db.execute(text(f'SELECT COUNT(*) FROM "{name}"{where}'), params).scalar() or 0)
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
            "vector_index": os.getenv("VECTOR_INDEX_BACKEND") or os.getenv("VECTOR_BACKEND", "disabled"),
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
