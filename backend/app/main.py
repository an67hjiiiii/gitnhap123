from __future__ import annotations
import threading
import time
import json
import logging
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from app.api.auth import router as auth_router
from app.api.oidc import build_router as _build_oidc_router
from app.api.auth import get_session_token
from app.auth.store import AuthStore, InvalidSessionError
from app.core.access import referenced_source_ids, require_active_member
from app.core.config import RuntimeConfig
from app.ingestion.documents import (
    DOCUMENT_INGESTION_VERSION,
    DocumentTypeError,
    MAX_DOCUMENT_BYTES,
    extract_document,
)
from app.providers.ollama import OllamaProvider
from app.retrieval.candidate_index import CandidateIndex, IndexingError
from app.retrieval.embeddings import make_embedder
from typing import Literal

from app.research.learning import load_examples, record_example
from app.research.pipeline import ResearchPipeline
from app.research.progress import bound_emit, ndjson_run
from app.research.run_queue import product_runs
from app.core.secret_audit import log_secret_access, run_read_source_ids, source_ids_of_chunks
from app.analysis.watch import notify_findings, watch_findings
from app.ingestion.shared_folder import list_shared_files, shared_root
from app.ingestion.ocr import IMAGE_EXTENSIONS, LANGS, ocr_image, ocr_pdf, ocr_status
from app.research.registry import PACKS, product_agent_pack
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


def _warm_caches() -> None:
    """Nạp sẵn ở luồng nền những thứ lượt hỏi đầu tiên từng làm đồng bộ trong vòng lặp sự kiện (đo 23/11):
    tokenizer Qwen3 (~0,8 s), băm mã nguồn cho provenance (~0,3 s), mã phiên bản mô hình Ollama (~0,9 s)."""
    from app.research.provenance import code_manifest, ollama_model_digest
    from app.research.token_budget import _tokenizer
    for warm in (_tokenizer, code_manifest, lambda: ollama_model_digest(os.getenv("LOCAL_LLM_MODEL", "qwen3:4b"))):
        try:
            warm()
        except Exception:  # thiếu tokenizer, Ollama chưa chạy...: lượt hỏi tự xử lý như cũ
            pass


threading.Thread(target=_warm_caches, name="warm-caches", daemon=True).start()
app.mount("/static", StaticFiles(directory=BASE / "app" / "static"), name="static")
app.include_router(auth_router)
app.include_router(_build_oidc_router())  # đăng nhập tổ chức: tắt khi chưa đặt OIDC_PROVIDERS
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


_VECTOR_STORE_LOCK = threading.Lock()


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
    # Qdrant nhúng chỉ cho một client mỗi thư mục: hai yêu cầu đầu tiên chạy song song (luồng của FastAPI) từng tạo hai
    # client và yêu cầu sau lỗi 500 "already accessed" (20/11). Khóa để chỉ một luồng tạo.
    with _VECTOR_STORE_LOCK:
        if _derived_vector_store is not None and _derived_vector_store_backend == backend:
            return _derived_vector_store
        return _create_vector_store(backend)


def _create_vector_store(backend: str):
    global _derived_vector_store, _derived_vector_store_backend
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


def _watch_new_source(user: dict, source_store, imported: dict) -> dict:
    """Theo dõi tài liệu mới (đợt 10): kiểm hiệu lực và mâu thuẫn với tài liệu cũ bằng luật, báo qua chuông nếu có phát hiện."""
    source_id = str(imported.get("source_id") or "")
    try:
        findings = watch_findings(source_id, source_store.chunks())
        imported = {**imported, "watch": findings}
        notify_findings(app.state.session_factory, str(user["user_id"]), str(imported.get("source_name") or source_id), findings)
    except Exception:  # theo dõi là phụ: không làm hỏng việc tải tài liệu
        logging.getLogger(__name__).exception("doc watch failed")
    return imported


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
    # ô chat Tự động: người dùng chọn một cách hiểu khi được hỏi lại (tác tử theo loại việc)
    # (bộ work: conditions…; bộ office: hr, finance…); tên lạ bị bỏ qua trong pipeline, không báo lỗi
    agent: str | None = Field(default=None, max_length=32)

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

_MODEL_HEALTH: dict = {"at": 0.0, "value": None}


@app.get("/api/local-model/health")
async def local_model_health():
    # Ollama mất ~0,7 giây để liệt kê mô hình, giao diện hỏi lại mỗi 15 giây và mỗi lần đổi trang: nhớ kết quả TỐT trong 10 giây.
    # Kết quả lỗi không nhớ, để Ollama vừa bật lại là thấy ngay.
    if _MODEL_HEALTH["value"] is not None and time.monotonic() - _MODEL_HEALTH["at"] < 10:
        return _MODEL_HEALTH["value"]
    try:
        value = await OllamaProvider().health()
        _MODEL_HEALTH.update(at=time.monotonic(), value=value)
        return value
    except Exception as exc:
        _MODEL_HEALTH["value"] = None
        return {"ok": False, "error": str(exc), "configured_model": os.getenv("LOCAL_LLM_MODEL", "qwen3:4b")}

@app.get("/api/sources")
def list_sources(request: Request):
    user = current_principal(request)
    store = owner_source_store(user)
    return {"snapshot_id": store.snapshot_id(), "sources": store.list_sources()}

@app.get("/api/sources/{source_id}")
def get_source(source_id: str, request: Request):
    user = current_principal(request)
    item = owner_source_store(user).source(source_id)
    if not item:
        raise HTTPException(404, "source not found")
    log_secret_access(app.state.session_factory, str(user["user_id"]), [source_id], "VIEW")
    return item


class DocTypeBody(BaseModel):
    doc_type: str


@app.put("/api/sources/{source_id}/doc-type")
def set_source_doc_type(source_id: str, body: DocTypeBody, request: Request):
    """Sửa nhãn loại tài liệu hệ thống tự nhận (đợt 3). Chỉ người tải lên; nhãn sửa tay được giữ khi nạp lại."""
    setter = getattr(owner_source_store(current_principal(request)), "set_doc_type", None)
    if not callable(setter):
        raise HTTPException(501, "doc type requires PostgreSQL storage")
    try:
        return setter(source_id, body.doc_type)
    except LookupError as exc:
        raise HTTPException(404, "source not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@app.get("/api/chunks/{chunk_id}")
def get_chunk(chunk_id: str, request: Request):
    user = current_principal(request)
    item = owner_source_store(user).chunk(chunk_id)
    if not item:
        raise HTTPException(404, "chunk not found")
    log_secret_access(app.state.session_factory, str(user["user_id"]), source_ids_of_chunks([chunk_id]), "VIEW")
    return item

@app.post("/api/sources/text")
def import_text(body: SourceTextRequest, request: Request):
    if not body.source_name.strip():
        raise HTTPException(422, "source_name is empty")
    if not body.text.strip():
        raise HTTPException(400, "text is empty")
    user = current_user(request)
    if request.query_params.get("space_id"):  # nộp tài liệu vào tổ chức (kèm mức mật) làm ở đợt sau
        raise HTTPException(400, "Chưa hỗ trợ tải tài liệu trực tiếp vào không gian tổ chức.")
    clean_name = body.source_name.strip()
    request.state.audit_target = clean_name
    store = owner_source_store(user)
    try:
        imported = store.import_text(
            clean_name,
            body.text,
            provenance={
                "ingestion_version": DOCUMENT_INGESTION_VERSION,
                "source_type": "text/plain",
                "source_format": "text",
                "origin": "text_api",
            },
        )
        return _watch_new_source(user, store, _index_imported_source(user, store, imported))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except IndexingError as exc:
        raise HTTPException(503, "DERIVED_INDEX_FAILED") from exc

@app.post("/api/sources/file")
async def import_file(request: Request, file: UploadFile = File(...)):
    user = current_user(request)
    if request.query_params.get("space_id"):  # nộp tài liệu vào tổ chức (kèm mức mật) làm ở đợt sau
        raise HTTPException(400, "Chưa hỗ trợ tải tài liệu trực tiếp vào không gian tổ chức.")
    data = await file.read()
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "Files must be no larger than 20 MB")

    source_name = file.filename or "upload.txt"
    request.state.audit_target = source_name
    suffix = os.path.splitext(source_name)[1].lower()
    if suffix in IMAGE_EXTENSIONS:  # ảnh chụp văn bản: nhận dạng chữ (OCR) rồi mới đọc
        return _import_ocr(user, source_name, lambda: ocr_image(data, suffix))
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
        if detail == "PDF_NO_TEXT" and ocr_status()["available"]:  # PDF scan không có lớp chữ: thử OCR
            return _import_ocr(user, source_name, lambda: ocr_pdf(data))
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
        return _watch_new_source(user, store, _index_imported_source(user, store, imported))
    except IndexingError as exc:
        raise HTTPException(503, "DERIVED_INDEX_FAILED") from exc

def _import_ocr(user: dict, source_name: str, run_ocr) -> dict:
    """Nạp văn bản nhận dạng từ ảnh/PDF scan (đợt 10). Thiếu Tesseract thì báo rõ cần cài gì."""
    status = ocr_status()
    if not status["available"]:
        raise HTTPException(422, f"OCR_UNAVAILABLE: {status['reason']}")
    try:
        text = run_ocr()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(422, f"OCR_FAILED: {type(exc).__name__}") from exc
    if not text.strip():
        raise HTTPException(422, "OCR_NO_TEXT")
    store = owner_source_store(user)
    imported = store.import_text(source_name, text, provenance={"origin": "upload", "ocr": "tesseract", "ocr_langs": LANGS})
    return _watch_new_source(user, store, _index_imported_source(user, store, imported))


@app.get("/api/ocr-status")  # không đặt dưới /api/sources/ để khỏi trùng /api/sources/{source_id}
def ocr_status_endpoint(request: Request):
    current_user(request)
    return ocr_status()


@app.post("/api/ocr-image")  # ảnh dán vào ô chat: chỉ đọc chữ để hỏi, không lưu vào kho
async def ocr_image_endpoint(request: Request, file: UploadFile = File(...)):
    current_user(request)
    data = await file.read()
    if len(data) > 10_000_000:
        raise HTTPException(413, "Ảnh vượt quá 10 MB.")
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise HTTPException(415, "UNSUPPORTED_DOCUMENT_TYPE")
    status = ocr_status()
    if not status["available"]:
        raise HTTPException(422, f"OCR_UNAVAILABLE: {status['reason']}")
    try:
        text = ocr_image(data, suffix)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(422, f"OCR_FAILED: {type(exc).__name__}") from exc
    return {"text": text.strip()}


@app.get("/api/shared-folder")  # không đặt dưới /api/sources/ để khỏi trùng /api/sources/{source_id}
def shared_folder_status(request: Request):
    """Thư mục chung (đợt 10): đã cấu hình chưa, có bao nhiêu tệp nạp được. Không lộ đường dẫn đầy đủ trên máy chủ."""
    current_user(request)
    root = shared_root()
    if root is None:
        return {"configured": False}
    files, skipped = list_shared_files(root)
    return {"configured": True, "folder": root.name, "files": len(files), "skipped": len(skipped)}


@app.post("/api/shared-folder/sync")
def shared_folder_sync(request: Request):
    """Nạp tệp mới trong thư mục chung vào kho cá nhân; tệp đã có (cùng tên) bỏ qua."""
    user = current_user(request)
    if request.query_params.get("space_id"):
        raise HTTPException(400, "Đồng bộ thư mục chung vào kho cá nhân; nộp vào tổ chức làm ở trang Tổ chức.")
    root = shared_root()
    if root is None:
        raise HTTPException(400, "Quản trị chưa cấu hình thư mục chung (SHARED_FOLDER_PATH).")
    store = owner_source_store(user)
    have = {s["source_name"] for s in store.list_sources()}
    files, skipped = list_shared_files(root)
    imported = []
    for path in files:
        name = path.relative_to(root).as_posix()
        if name in have:
            # shortcut: so theo tên, tệp đổi nội dung mà giữ tên thì chưa nạp lại; nâng lên so mã băm khi cần
            skipped.append({"name": name, "reason": "đã có trong kho"})
            continue
        try:
            document = extract_document(path.read_bytes(), name, origin="shared_folder")
            item = store.import_text(document.source_name, document.text, provenance=document.provenance)
            _watch_new_source(user, store, _index_imported_source(user, store, item))
            imported.append(name)
        except (DocumentTypeError, UnicodeError, ValueError, IndexingError) as exc:
            skipped.append({"name": name, "reason": f"không đọc được ({type(exc).__name__})"})
    return {"imported": imported, "skipped": skipped}


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    return await _chat(body, request)


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """Như /api/chat nhưng gửi dần từng dòng JSON: {"type":"progress"|"answer"} rồi {"type":"done","run"} hoặc {"type":"error"}.

    Chỉ dành cho ô chat sản phẩm; tiến trình qua ContextVar nên pipeline và thực nghiệm không đổi.
    Người dùng đóng trang giữa chừng thì lượt chạy vẫn chạy xong và được lưu như /api/chat.
    """
    if not body.product_mode:
        raise HTTPException(400, "STREAM_ONLY_FOR_PRODUCT_MODE")
    if not body.message.strip():
        raise HTTPException(400, "message is required")
    user = current_principal(request)
    return StreamingResponse(ndjson_run(lambda: _chat(body, request, user=user)), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _chat(body: ChatRequest, request: Request, *, user: dict | None = None):
    if not body.message.strip():
        raise HTTPException(400, "message is required")
    try:
        user = user if user is not None else current_principal(request)
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
        # Đợt 8 (P1-5): học từ người dùng, chỉ ô chat sản phẩm. Người dùng bấm chọn cách hiểu → lưu làm ví dụ;
        # các ví dụ đã lưu giúp bộ chọn tác tử lần sau (thực nghiệm A/B/C không đọc, không ghi).
        examples: list[tuple[str, str]] = []
        if body.product_mode and STORAGE_BACKEND == "postgres":
            factory = app.state.session_factory
            if body.agent:
                record_example(factory, str(user["user_id"]), _space(user), body.message.strip(), body.agent, "clarify")
            examples = load_examples(factory, str(user["user_id"]), _space(user))
        run_call = lambda: owner_pipeline(user, conversation_id).run(  # chỉ tạo lượt chạy khi tới lượt
            body.message.strip(),
            condition,
            provider_name,
            source_ids=selected_source_ids,
            conversation_context=conversation_context,
            conversation_id=conversation_id,
            product_mode=body.product_mode,
            reply_in_query_language=body.reply_in_query_language,
            domain_pack=body.domain_pack or (product_agent_pack() if body.product_mode else None),  # ô chat sản phẩm: mặc định bộ office (Đợt 9)
            forced_agent=body.agent if body.product_mode else None,
            routing_examples=examples,
        )
        if body.product_mode:  # ô chat sản phẩm xếp hàng theo thứ tự; thực nghiệm không qua hàng đợi
            say = bound_emit()  # báo thứ tự vào luồng của chính người đang chờ, kể cả khi người trước gọi lúc nhường chỗ
            async with product_runs.slot(lambda n: say({"type": "queue", "position": n})):
                run = await run_call()
        else:
            run = await run_call()
        conversations.add_message(
            conversation_id,
            "ASSISTANT",
            str(run.get("answer") or run.get("status") or "Run completed"),
            run_id=run["run_id"],
        )
        # nhật ký Mật: tài liệu mức Mật có đoạn được đưa cho AI trong lượt này (chỉ thao tác, không ghi câu hỏi)
        log_secret_access(app.state.session_factory, str(user["user_id"]), run_read_source_ids(run), "ASK")
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


class SkillCardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str | None = Field(default=None, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    summary: str = Field(min_length=1, max_length=2000)
    card: dict
    source_ids: list[str] | None = Field(default=None, max_length=50)


@app.post("/api/conversations/skill-card")
def save_skill_card(body: SkillCardBody, request: Request):
    """Ô chat Tự động: lưu câu hỏi và thẻ kết quả kỹ năng vào cuộc trò chuyện (tải lại trang vẫn còn).

    Tin nhắn trợ lý = dòng tóm tắt + dữ liệu thẻ trong <!--skill-card:...-->; ngữ cảnh hội thoại chỉ lấy dòng tóm tắt.
    """
    user = current_principal(request)
    if not body.question.strip() or not body.summary.strip():
        raise HTTPException(422, "Nội dung câu hỏi và tóm tắt không được để trống.")
    card_data = dict(body.card)
    clean_ids = list(dict.fromkeys(str(s) for s in (body.source_ids or []) if str(s)))
    # Luôn kiểm tra mọi src_<16hex> nhúng trong thẻ/tóm tắt kể cả khi không truyền ?space_id= (đóng B135-SEC-01)
    embedded_refs = sorted(referenced_source_ids({"summary": body.summary, "card": card_data}))
    verify_ids = list(dict.fromkeys([*clean_ids, *embedded_refs]))
    if verify_ids:
        sources = owner_source_store(user)
        if any(sources.source(sid) is None for sid in verify_ids):
            raise HTTPException(404, "Không tìm thấy tài liệu.")
        existing_ids = [str(s) for s in (card_data.get("_source_ids") or []) if str(s)] if isinstance(card_data.get("_source_ids"), list) else []
        card_data["_source_ids"] = list(dict.fromkeys([*existing_ids, *verify_ids]))
    payload = json.dumps(card_data, ensure_ascii=False, separators=(",", ":"))
    if len(payload) > 60_000:
        raise HTTPException(413, "Thẻ kết quả quá lớn để lưu.")
    conversations = owner_conversation_store(user)
    conversation_id = body.conversation_id
    if conversation_id:
        if conversations.get(conversation_id) is None:
            raise HTTPException(404, "conversation not found")
    else:
        conversation_id = conversations.create(body.question.strip()[:120])["conversation_id"]
    conversations.add_message(conversation_id, "USER", body.question.strip())
    marked = payload.replace(">", "\u003e")  # chuỗi thoát JSON: "-->" trong dữ liệu không đóng dấu đánh dấu sớm
    conversations.add_message(conversation_id, "ASSISTANT", body.summary.strip() + "\n\n<!--skill-card:" + marked + "-->")
    return {"conversation_id": conversation_id}


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
