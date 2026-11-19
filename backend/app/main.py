from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from app.api.auth import router as auth_router
from app.api.auth import get_session_token
from app.auth.store import AuthStore, InvalidSessionError
from app.core.access import require_active_member
from app.core.config import RuntimeConfig
from app.ingestion.documents import (
    DOCUMENT_INGESTION_VERSION,
    DocumentTypeError,
    extract_document,
)
from app.providers.ollama import OllamaProvider
from app.retrieval.candidate_index import CandidateIndex, IndexingError
from app.retrieval.embeddings import make_embedder
from typing import Literal

from app.research.pipeline import ResearchPipeline
from app.research.registry import PACKS
from app.research.conversation_context import build_conversation_context
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore
from app.storage.conversation_store import ConversationStore
from app.storage.vector_store import InMemoryVectorStore, QdrantVectorStore
from app.storage.postgres import create_postgres_engine, create_session_factory
from app.storage.postgres.config import PostgresConfigurationError
from app.storage.postgres.runtime import (
    PostgresAuthStore,
    PostgresConversationStore,
    PostgresRunStore,
    PostgresSourceStore,
)

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env", override=False)
DATA_DIR = os.getenv("APP_DATA_DIR", str(BASE / "data"))
RUNS_DIR = os.getenv("RUNS_DIR", str(BASE / "runs"))
STORAGE_BACKEND = os.getenv("APP_STORAGE_BACKEND", "postgres").strip().lower()
VECTOR_BACKEND = os.getenv(
    "VECTOR_BACKEND", os.getenv("VECTOR_INDEX_BACKEND", "disabled")
).strip().lower()
VECTOR_INDEX_PATH = os.getenv("VECTOR_INDEX_PATH", str(BASE / "storage" / "qdrant"))
VECTOR_COLLECTION = os.getenv("VECTOR_COLLECTION", "domain")
VECTOR_SIZE = os.getenv("VECTOR_SIZE", "768")
_derived_vector_store = None
_derived_vector_store_backend = None


def _configured_stores(storage_backend: str | None = None):
    backend = (storage_backend or os.getenv("APP_STORAGE_BACKEND", "postgres")).strip().lower()
    if backend == "file":
        return AuthStore(DATA_DIR), SourceStore(DATA_DIR), RunStore(RUNS_DIR), None
    if backend != "postgres":
        raise PostgresConfigurationError("APP_STORAGE_BACKEND must be postgres or file")
    engine = create_postgres_engine()
    session_factory = create_session_factory(engine)
    return PostgresAuthStore(session_factory), None, None, (engine, session_factory)

app = FastAPI(title="Local Multi-Agent RAG", version="0.2.0-m0")
app.mount("/static", StaticFiles(directory=BASE / "app" / "static"), name="static")
app.include_router(auth_router)
auth_store, source_store, run_store, postgres_runtime = _configured_stores()
app.state.storage_backend = STORAGE_BACKEND
app.state.auth_store = auth_store
app.state.session_factory = None if postgres_runtime is None else postgres_runtime[1]
pipeline = None if STORAGE_BACKEND == "postgres" else ResearchPipeline(source_store, run_store)

def current_user(request: Request) -> dict:
    try:
        return request.app.state.auth_store.resolve(get_session_token(request))
    except InvalidSessionError as exc:
        raise HTTPException(status_code=401, detail="Authentication is required") from exc


def current_principal(request: Request) -> dict:
    """Người dùng kèm phạm vi của yêu cầu (?space_id=...). Không có = cá nhân, hành vi như cũ.

    Mọi kho (tài liệu, lượt chạy, hội thoại) đọc phạm vi từ đây nên không route nào quên lọc được.
    Có space_id thì phải là thành viên đang hoạt động của không gian đó, nếu không 403.
    """
    user = current_user(request)
    space_id = (request.query_params.get("space_id") or "").strip() or None
    if space_id is not None:
        if STORAGE_BACKEND != "postgres":
            raise HTTPException(400, "Không gian tổ chức cần APP_STORAGE_BACKEND=postgres.")
        try:
            with app.state.session_factory() as db:
                require_active_member(db, str(user["user_id"]), space_id)
        except PermissionError as exc:
            raise HTTPException(403, "Bạn không thuộc không gian tổ chức này.") from exc
    return {**user, "space_id": space_id}


def _space(user: dict) -> str | None:
    return user.get("space_id")


def owner_source_store(user: dict):
    """Phạm vi lấy từ current_principal: cá nhân như trước, hoặc chỉ tài liệu app.core.access cho phép."""
    if STORAGE_BACKEND == "postgres":
        return PostgresSourceStore(app.state.session_factory, str(user["user_id"]), _space(user))
    root = Path(DATA_DIR) / "owners" / str(user["user_id"]) / "sources"
    return SourceStore(str(root))

def owner_run_store(user: dict, conversation_id: str | None = None):
    if STORAGE_BACKEND == "postgres":
        return PostgresRunStore(
            app.state.session_factory, str(user["user_id"]), conversation_id, _space(user)
        )
    root = Path(RUNS_DIR) / "owners" / str(user["user_id"])
    return RunStore(str(root))

def owner_pipeline(user: dict, conversation_id: str | None = None) -> ResearchPipeline:
    sources = owner_source_store(user)
    candidate_index = None
    if VECTOR_BACKEND not in {"", "disabled", "off", "none"}:
        vector_store = _configured_vector_store()
        if vector_store is not None:
            candidate_index = CandidateIndex(
                sources,
                vector_store,
                owner_user_id=str(user["user_id"]),
                embedder=make_embedder(
                    int(getattr(vector_store, "vector_size", 768) or 768)
                ),
            )
    return ResearchPipeline(
        sources,
        owner_run_store(user, conversation_id),
        candidate_index=candidate_index,
        retrieval_backend=VECTOR_BACKEND if candidate_index is not None else "lexical",
    )


def _configured_vector_store():
    """Create the explicitly selected derived-index backend lazily."""

    global _derived_vector_store, _derived_vector_store_backend
    backend = VECTOR_BACKEND
    if backend in {"", "disabled", "off", "none"}:
        return None
    if backend not in {"memory", "qdrant"}:
        raise IndexingError(f"Unsupported VECTOR_BACKEND={backend}")
    if _derived_vector_store is not None and _derived_vector_store_backend == backend:
        return _derived_vector_store
    try:
        vector_size = int(VECTOR_SIZE)
    except (TypeError, ValueError) as exc:
        raise IndexingError("VECTOR_SIZE must be a positive integer") from exc
    if vector_size < 1:
        raise IndexingError("VECTOR_SIZE must be a positive integer")
    if backend == "memory":
        store = InMemoryVectorStore(vector_size=vector_size)
    else:
        store = QdrantVectorStore(
            path=VECTOR_INDEX_PATH,
            collection=VECTOR_COLLECTION,
            vector_size=vector_size,
        )
    _derived_vector_store = store
    _derived_vector_store_backend = backend
    return store


def _index_imported_source(user: dict, source_store, imported: dict) -> dict:
    """Index a READY source only when an explicit derived backend is enabled."""

    if VECTOR_BACKEND in {"", "disabled", "off", "none"}:
        return imported
    source_id = str(imported.get("source_id") or "")
    try:
        vector_store = _configured_vector_store()
        if vector_store is None:
            return imported
        index = CandidateIndex(
            source_store,
            vector_store,
            owner_user_id=str(user["user_id"]),
            embedder=make_embedder(
                int(getattr(vector_store, "vector_size", 768) or 768)
            ),
        )
        result = index.index_source(source_id)
    except Exception as exc:
        marker = getattr(source_store, "mark_failed", None)
        if callable(marker):
            marker(source_id, exc)
        if isinstance(exc, IndexingError):
            raise
        raise IndexingError("derived index failed") from exc
    return {**imported, "derived_index": {"backend": VECTOR_BACKEND, **result}}


def owner_conversation_store(user: dict):
    if STORAGE_BACKEND == "postgres":
        return PostgresConversationStore(app.state.session_factory, str(user["user_id"]), _space(user))
    root = Path(DATA_DIR) / "owners" / str(user["user_id"]) / "conversations"
    return ConversationStore(root)

class ChatRequest(BaseModel):
    message: str
    condition: str | None = None
    provider: str | None = None
    conversation_id: str | None = None
    source_ids: list[str] | None = None
    product_mode: bool = False
    # Studio: trả lời theo ngôn ngữ câu hỏi ở lượt phân tích; trang Thực nghiệm không bật để giữ prompt nghiên cứu.
    reply_in_query_language: bool = False
    # lĩnh vực của không gian đang mở; bỏ trống = Phần mềm (prompt nghiên cứu như cũ, dùng cho script thực nghiệm)
    domain_pack: Literal[tuple(PACKS)] | None = None  # type: ignore[valid-type]

class SourceTextRequest(BaseModel):
    source_name: str
    text: str

@app.get("/")
def index():
    return FileResponse(BASE / "app" / "static" / "index.html")

@app.get("/api/health")
def health():
    cfg = RuntimeConfig.from_env()
    return {
        "ok": True,
        "app": "local-multi-agent-rag",
        "version": "0.2.0-m0",
        "implementation_profile": cfg.implementation_profile,
        "allowed_conditions": cfg.allowed_conditions(),
        "default_provider": os.getenv("PROVIDER", "fake"),
        "source_snapshot_id": None if source_store is None else source_store.snapshot_id(),
        "storage_backend": STORAGE_BACKEND,
        "config_hash": cfg.config_hash(),
    }

@app.get("/api/config")
def config():
    cfg = RuntimeConfig.from_env()
    return {**cfg.public_dict(), "allowed_conditions": cfg.allowed_conditions(), "config_hash": cfg.config_hash()}

@app.get("/api/local-model/health")
async def local_model_health():
    try:
        return await OllamaProvider().health()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "configured_model": os.getenv("LOCAL_LLM_MODEL", "qwen3:4b")}

@app.get("/api/sources")
def list_sources(request: Request):
    user = current_principal(request)
    store = owner_source_store(user)
    return {"snapshot_id": store.snapshot_id(), "sources": store.list_sources()}

@app.get("/api/sources/{source_id}")
def get_source(source_id: str, request: Request):
    item = owner_source_store(current_principal(request)).source(source_id)
    if not item:
        raise HTTPException(404, "source not found")
    return item

@app.get("/api/chunks/{chunk_id}")
def get_chunk(chunk_id: str, request: Request):
    item = owner_source_store(current_principal(request)).chunk(chunk_id)
    if not item:
        raise HTTPException(404, "chunk not found")
    return item

@app.post("/api/sources/text")
def import_text(body: SourceTextRequest, request: Request):
    if not body.text.strip():
        raise HTTPException(400, "text is empty")
    user = current_user(request)
    if request.query_params.get("space_id"):  # nộp tài liệu vào tổ chức (kèm mức mật) làm ở đợt sau
        raise HTTPException(400, "Chưa hỗ trợ tải tài liệu trực tiếp vào không gian tổ chức.")
    request.state.audit_target = body.source_name
    store = owner_source_store(user)
    try:
        imported = store.import_text(
            body.source_name,
            body.text,
            provenance={
                "ingestion_version": DOCUMENT_INGESTION_VERSION,
                "source_type": "text/plain",
                "source_format": "text",
                "origin": "text_api",
            },
        )
        return _index_imported_source(user, store, imported)
    except IndexingError as exc:
        raise HTTPException(503, "DERIVED_INDEX_FAILED") from exc

@app.post("/api/sources/file")
async def import_file(request: Request, file: UploadFile = File(...)):
    user = current_user(request)
    if request.query_params.get("space_id"):  # nộp tài liệu vào tổ chức (kèm mức mật) làm ở đợt sau
        raise HTTPException(400, "Chưa hỗ trợ tải tài liệu trực tiếp vào không gian tổ chức.")
    data = await file.read()
    if len(data) > 2_000_000:
        raise HTTPException(413, "Files must be no larger than 2 MB")

    source_name = file.filename or "upload.txt"
    request.state.audit_target = source_name
    try:
        document = extract_document(
            data,
            source_name,
            origin="upload",
            content_type=file.content_type,
        )
    except DocumentTypeError as exc:
        detail = (
            "PDF_NO_TEXT"
            if "no extractable text" in str(exc)
            else "PDF_EXTRACTION_UNAVAILABLE"
        )
        if source_name.lower().endswith((".docx", ".xlsx")):
            detail = "OFFICE_EXTRACTION_FAILED"
        elif not source_name.lower().endswith(".pdf"):
            detail = "UNSUPPORTED_DOCUMENT_TYPE"
        raise HTTPException(415 if detail != "PDF_NO_TEXT" else 422, detail) from exc
    except UnicodeError as exc:
        raise HTTPException(415, "UTF8_TEXT_REQUIRED") from exc
    except ValueError as exc:
        if "must not be empty" in str(exc):
            raise HTTPException(400, "file is empty") from exc
        raise HTTPException(415, "DOCUMENT_EXTRACTION_FAILED") from exc
    store = owner_source_store(user)
    try:
        imported = store.import_text(
            document.source_name,
            document.text,
            provenance=document.provenance,
        )
        return _index_imported_source(user, store, imported)
    except IndexingError as exc:
        raise HTTPException(503, "DERIVED_INDEX_FAILED") from exc

@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    if not body.message.strip():
        raise HTTPException(400, "message is required")
    try:
        user = current_principal(request)
        runtime_config = RuntimeConfig.from_env()
        if body.product_mode:
            if body.condition is not None or body.provider is not None:
                raise HTTPException(
                    400,
                    "RESEARCH_CONTROLS_NOT_AVAILABLE_IN_PRODUCT_MODE",
                )
            configured_provider = runtime_config.provider
            test_mode = os.getenv("APP_ENV", "development").strip().lower() == "test"
            if configured_provider == "fake" and test_mode:
                provider_name = configured_provider
            elif configured_provider == "ollama":
                provider_name = configured_provider
            else:
                raise HTTPException(
                    503,
                    "PRODUCT_PROVIDER_NOT_CONFIGURED: set PROVIDER=ollama",
                )
            configured_product_condition = os.getenv("PRODUCT_CONDITION", "").strip().upper()
            condition = configured_product_condition or (
                "C" if runtime_config.implementation_profile in {"m1", "m2", "dev"} else "A"
            )
        elif body.condition is not None:
            condition = body.condition.upper()
            provider_name = body.provider
        else:
            condition = "A"
            provider_name = body.provider
        runtime_config.assert_condition(condition)
        conversations = owner_conversation_store(user)
        if body.conversation_id:
            if conversations.get(body.conversation_id) is None:
                raise HTTPException(404, "conversation not found")
            conversation_id = body.conversation_id
        else:
            conversation_id = conversations.create(body.message.strip()[:120])["conversation_id"]
        conversation_context = build_conversation_context(conversations.get(conversation_id))
        selected_source_ids = None if body.source_ids is None else [str(source_id) for source_id in body.source_ids]
        validator = getattr(owner_source_store(user), "validate_source_selection", None)
        if callable(validator) and selected_source_ids is not None:
            validator(selected_source_ids)
        conversations.add_message(conversation_id, "USER", body.message.strip())
        run = await owner_pipeline(user, conversation_id).run(
            body.message.strip(),
            condition,
            provider_name,
            source_ids=selected_source_ids,
            conversation_context=conversation_context,
            conversation_id=conversation_id,
            product_mode=body.product_mode,
            reply_in_query_language=body.reply_in_query_language,
            domain_pack=body.domain_pack,
        )
        conversations.add_message(
            conversation_id,
            "ASSISTANT",
            str(run.get("answer") or run.get("status") or "Run completed"),
            run_id=run["run_id"],
        )
        run = {**run, "conversation_id": conversation_id}
        if run["status"] == "FAILED":
            return run
        return run
    except LookupError as exc:
        raise HTTPException(404, "source not found") from exc
    except IndexingError as exc:
        raise HTTPException(503, "DERIVED_INDEX_UNAVAILABLE") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.get("/api/runs")
def list_runs(request: Request):
    return owner_run_store(current_principal(request)).list()

@app.get("/api/runs/{run_id}")
def get_run(run_id: str, request: Request):
    run = owner_run_store(current_principal(request)).get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


@app.get("/api/conversations")
def list_conversations(request: Request):
    return owner_conversation_store(current_principal(request)).list()


class ConversationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None
    hidden: bool | None = None


@app.patch("/api/conversations/{conversation_id}")
def patch_conversation(conversation_id: str, body: ConversationPatch, request: Request):
    """Đổi tên / ghim / xóa (ẩn, hoàn tác được) cuộc trò chuyện của chính mình; tin nhắn và lượt chạy không bị xóa."""
    store = owner_conversation_store(current_principal(request))
    if not hasattr(store, "update"):
        raise HTTPException(501, "Kho dữ liệu này không hỗ trợ sửa cuộc trò chuyện")
    try:
        return store.update(conversation_id, title=body.title, pinned=body.pinned, hidden=body.hidden)
    except LookupError as exc:
        raise HTTPException(404, "conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request):
    conversation = owner_conversation_store(current_principal(request)).get(conversation_id)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    return conversation


# API bổ sung cho giao diện Studio (C1SE.27): thử truy xuất, so sánh điều kiện, trang quản trị.
from app.api.studio import build_router as _build_studio_router

app.include_router(_build_studio_router(
    current_user=current_principal,
    owner_pipeline=owner_pipeline,
    session_factory=lambda: app.state.session_factory,
    owner_source_store=owner_source_store,
    vector_store=_configured_vector_store,
))

# Chức năng phân tích của Studio (truy vết yêu cầu, báo cáo); không đi qua /api/chat hay điều kiện A/B/C.
from app.api.analysis import build_router as _build_analysis_router

app.include_router(_build_analysis_router(
    current_user=current_principal,
    owner_pipeline=owner_pipeline,
    session_factory=lambda: app.state.session_factory,
))

# Không gian tổ chức: phòng ban, thành viên, lời mời, tài liệu tổ chức, thông báo (luật ở app/core/access.py).
from app.api.org import build_router as _build_org_router

app.include_router(_build_org_router(current_user=current_user, session_factory=lambda: app.state.session_factory,
                                     vector_store=_configured_vector_store))

# Quản lý người dùng cho ADMIN (tạo tài khoản, vai trò, khóa/mở khóa, đặt lại mật khẩu, thu hồi phiên).
from app.api.users import build_router as _build_users_router

app.include_router(_build_users_router(current_user=current_user))

# Bảng điều khiển quản trị: số đo thật của máy chủ, Ollama, PostgreSQL, Qdrant; nhật ký kiểm toán mọi tài khoản.
from app.api.admin_system import build_router as _build_admin_system_router

app.include_router(_build_admin_system_router(current_user=current_user, session_factory=lambda: app.state.session_factory,
                                              vector_path=VECTOR_INDEX_PATH))

# Nhật ký hoạt động: ghi các thao tác có ý nghĩa (không ghi nội dung câu hỏi hay tài liệu). Ghi lỗi không làm hỏng yêu cầu.
import logging as _logging
import re as _re

from sqlalchemy import text as _sql
from starlette.concurrency import run_in_threadpool as _in_thread

_ORG_AUDIT_MASK = "(không gian tổ chức)"
_AUDITED = [(m, _re.compile(p), label) for m, p, label in (
    ("POST", r"^/api/sources/(text|file)$", "Nạp tài liệu"),
    ("DELETE", r"^/api/studio/sources/(?P<t>[^/]+)$", "Xóa tài liệu"),
    ("POST", r"^/api/chat$", "Đặt câu hỏi"),
    ("PATCH", r"^/api/conversations/(?P<t>[^/]+)$", "Sửa cuộc trò chuyện"),
    ("POST", r"^/api/studio/workspaces$", "Tạo không gian làm việc"),
    ("DELETE", r"^/api/studio/workspaces/(?P<t>[^/]+)$", "Xóa không gian làm việc"),
    ("POST", r"^/api/studio/reports$", "Lưu báo cáo"),
    ("DELETE", r"^/api/studio/reports/(?P<t>[^/]+)$", "Xóa báo cáo"),
    ("POST", r"^/api/studio/compare$", "So sánh điều kiện"),
    ("POST", r"^/api/studio/eval/run$", "Chạy đánh giá"),
    ("POST", r"^/api/studio/traceability/extract$", "Truy vết yêu cầu"),
    ("POST", r"^/api/studio/req-quality$", "Soát chất lượng yêu cầu"),
    ("POST", r"^/api/studio/design/points$", "Lập gói thiết kế"),
    ("POST", r"^/api/studio/consistency/candidates$", "Kiểm tra mâu thuẫn"),
    ("POST", r"^/api/studio/profile/local$", "Lập hồ sơ tài liệu"),
    ("POST", r"^/api/studio/compare-docs$", "So sánh phiên bản tài liệu"),
    ("POST", r"^/api/studio/feedback$", "Đánh giá câu trả lời"),
    ("POST", r"^/api/studio/mindmap$", "Lập sơ đồ tư duy"),
    ("POST", r"^/api/studio/answer-report$", "Viết báo cáo từ câu trả lời"),
    ("GET", r"^/api/studio/library-quality$", "Kiểm tra kho tài liệu"),
    ("POST", r"^/api/studio/rating/studies$", "Tạo đợt chấm mù"),
    ("DELETE", r"^/api/studio/rating/studies/(?P<t>[^/]+)$", "Xóa đợt chấm mù"),
    # không gian tổ chức: chỉ ghi mã (không gian, thành viên, tài liệu), không ghi tên hay nội dung
    ("POST", r"^/api/org/spaces$", "Tạo không gian tổ chức"),
    ("POST", r"^/api/org/spaces/(?P<t>[^/]+)/invites$", "Tạo lời mời vào tổ chức"),
    ("POST", r"^/api/org/join$", "Xin vào tổ chức bằng link/mã"),
    ("POST", r"^/api/org/invites/(?P<t>[^/]+)/(accept|decline)$", "Trả lời lời mời vào tổ chức"),
    ("POST", r"^/api/org/spaces/[^/]+/members/(?P<t>[^/]+)/approve$", "Duyệt thành viên tổ chức"),
    ("PATCH", r"^/api/org/spaces/[^/]+/members/(?P<t>[^/]+)$", "Đổi cấp bậc / đơn vị thành viên"),
    ("DELETE", r"^/api/org/spaces/[^/]+/members/(?P<t>[^/]+)$", "Gỡ thành viên tổ chức"),
    ("POST", r"^/api/org/spaces/(?P<t>[^/]+)/leave$", "Rời không gian tổ chức"),
    ("DELETE", r"^/api/org/spaces/(?P<t>[^/]+)$", "Xóa tổ chức"),
    ("POST", r"^/api/org/spaces/[^/]+/sources/(?P<t>[^/]+)/publish$", "Nộp tài liệu vào tổ chức"),
    ("PATCH", r"^/api/org/spaces/[^/]+/sources/(?P<t>[^/]+)$", "Đổi mức mật tài liệu"),
    ("POST", r"^/api/org/spaces/[^/]+/sources/(?P<t>[^/]+)/shares$", "Chia sẻ tài liệu tổ chức"),
    ("DELETE", r"^/api/org/spaces/[^/]+/shares/(?P<t>[^/]+)$", "Gỡ chia sẻ tài liệu"),
    ("POST", r"^/api/admin/users$", "Tạo tài khoản"),
    ("PATCH", r"^/api/admin/users/[^/]+$", "Đổi vai trò / trạng thái tài khoản"),
    ("POST", r"^/api/admin/users/[^/]+/reset-password$", "Đặt lại mật khẩu"),
    ("POST", r"^/api/admin/users/[^/]+/revoke-sessions$", "Đăng xuất mọi phiên của tài khoản"),
)]


def _audit_write(owner: str, action: str, target: str, status: int) -> None:
    with app.state.session_factory() as db:
        db.execute(_sql("INSERT INTO studio_activity (owner_user_id, action, target, status) VALUES (:o, :a, :t, :s)"),
                   {"o": owner, "a": action, "t": target[:200], "s": status})
        db.commit()


@app.middleware("http")
async def _activity_log(request: Request, call_next):
    hit = None
    if request.method != "GET" and app.state.session_factory is not None:
        hit = next(((label, m) for method, pattern, label in _AUDITED
                    if method == request.method and (m := pattern.match(request.url.path))), None)
    if hit is None:
        return await call_next(request)
    try:
        owner = str((await _in_thread(current_user, request))["user_id"])
    except Exception:  # chưa đăng nhập: để route tự trả 401, không ghi nhật ký
        return await call_next(request)
    response = await call_next(request)
    label, match = hit
    try:
        target = getattr(request.state, "audit_target", None) or match.groupdict().get("t") or ""
        if request.query_params.get("space_id"):
            target = _ORG_AUDIT_MASK  # ADMIN xem nhật ký: không lộ tên tài liệu hay câu hỏi của tổ chức
        await _in_thread(_audit_write, owner, label, target, response.status_code)
    except Exception:
        _logging.getLogger(__name__).warning("Không ghi được nhật ký hoạt động", exc_info=True)
    return response
