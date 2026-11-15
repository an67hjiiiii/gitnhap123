from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.auth import get_session_token
from app.api.auth import router as auth_router
from app.api.review import ReviewRuntime
from app.api.review import build_router as _build_review_router
from app.auth.store import AuthStore, InvalidSessionError
from app.chat.memory import SummaryCache as _SummaryCache
from app.chat.source_filter import filter_sources
from app.chat.sources import number_sources
from app.core.config import RuntimeConfig
from app.core.text_clean import strip_placeholder_tags
from app.core.observability import RequestIdMiddleware, SecurityHeadersMiddleware, TTLCache, configure_logging
from app.core.readiness import check_ollama, check_postgres, check_vector
from app.ingestion.documents import (
    DOCUMENT_INGESTION_VERSION,
    DocumentTypeError,
    extract_document,
)
from app.providers.ollama import OllamaProvider
from app.research.pipeline import EXTRA_RETRIEVAL_QUERIES, ResearchPipeline
from app.retrieval.candidate_index import CandidateIndex, IndexingError
from app.retrieval.index_identity import IndexState
from app.retrieval.reindex import ReindexManager, index_state
from app.review.labels import load_labels
from app.retrieval.embeddings import effective_dimension, make_embedder, validate_embedding_config
from app.review.memory import InMemoryMemoryStore
from app.storage.conversation_store import ConversationStore
from app.storage.postgres import create_postgres_engine, create_session_factory
from app.storage.postgres.config import PostgresConfigurationError
from app.storage.postgres.runtime import (
    PostgresAuthStore,
    PostgresConversationStore,
    PostgresRunStore,
    PostgresSourceStore,
)
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore, QdrantVectorStore

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
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
_ready_cache = TTLCache(5)
_local_health_cache = TTLCache(30)
def cors_origins_from_env() -> list[str]:
    origins = [x.strip() for x in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if x.strip()]
    return origins if origins and "*" not in origins else []


_cors_origins = cors_origins_from_env()
if _cors_origins and "*" not in _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
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

review_runtime = ReviewRuntime(
    pipeline_factory=lambda owner: owner_pipeline({"user_id": owner}),
    source_store_factory=lambda owner: owner_source_store({"user_id": owner}),
    storage_backend=STORAGE_BACKEND,
    session_factory=app.state.session_factory,
    memory_store=InMemoryMemoryStore(),
)
app.include_router(_build_review_router(current_user=current_user, runtime=review_runtime))

@app.on_event("startup")
def start_review_runtime():
    configure_logging()
    review_runtime.startup()
    if review_runtime.durable:
        review_runtime.runner.start_recovery()

@app.on_event("shutdown")
def stop_review_runtime():
    review_runtime.runner.shutdown()


@app.on_event("startup")
def mark_stale_chat_runs():
    max_age = float(os.getenv("CHAT_STALE_RUN_SECONDS", "3600"))
    if STORAGE_BACKEND == "postgres":
        from sqlalchemy import inspect, select
        from app.storage.postgres.models import RunRecord

        with app.state.session_factory() as db:
            # Review-only deployments may not have a chat runs table yet.
            if not inspect(db.get_bind()).has_table(RunRecord.__tablename__):
                return
            owners = db.scalars(select(RunRecord.owner_user_id).distinct()).all()
        for owner in owners:
            PostgresRunStore(app.state.session_factory, owner).mark_stale_running_runs(max_age)
    else:
        run_store.mark_stale_running_runs(max_age)
        for root in (Path(RUNS_DIR) / "owners").glob("*"):
            if root.is_dir():
                RunStore(str(root)).mark_stale_running_runs(max_age)

_REINDEX = ReindexManager()


def _reindex_items() -> list[tuple[str, str]]:
    """(owner_id, source_id) of every READY source, for the background rebuild."""
    if STORAGE_BACKEND == "postgres":
        from sqlalchemy import select
        from app.storage.postgres.models import KnowledgeSourceRecord

        with app.state.session_factory() as db:
            rows = db.execute(select(KnowledgeSourceRecord.owner_user_id, KnowledgeSourceRecord.source_id)
                              .where(KnowledgeSourceRecord.status == "READY")
                              .order_by(KnowledgeSourceRecord.owner_user_id, KnowledgeSourceRecord.source_id)).all()
        return [(str(o), str(s)) for o, s in rows]
    items = []
    for root in sorted((Path(DATA_DIR) / "owners").glob("*")):
        if root.is_dir():
            items += [(root.name, s["source_id"]) for s in SourceStore(str(root / "sources")).list_sources()
                      if s.get("status", "READY") == "READY"]
    return items


def maybe_start_reindex(user: dict | None = None) -> bool:
    """Start the background rebuild when the collection identity differs from the current embedder (once)."""
    if VECTOR_BACKEND in {"", "disabled", "off", "none"} or _REINDEX.running:
        return False
    index = owner_pipeline(user or {"user_id": "_reindex"}).candidate_index
    if index is None or index_state(index) != IndexState.INCOMPATIBLE:
        return False
    return _REINDEX.start(lambda owner: owner_pipeline({"user_id": owner}).candidate_index,
                          _reindex_items(), prepare=index.begin_rebuild)


def _reindex_reply(language: str) -> dict | None:
    """Friendly 'index is updating' payload while a rebuild runs (None when idle/finished)."""
    state = _REINDEX.status()
    if state["status"] != "running":
        return None
    labels = load_labels().get("reindex", {})
    text = labels.get("running", "").format(done=state["done"], total=state["total"])
    return {"text": text, "state": state}


@app.on_event("startup")
def start_background_reindex():
    try:
        maybe_start_reindex()
    except Exception:  # never block startup; document questions retry lazily
        logging.getLogger(__name__).exception("could not start background reindex")


@app.get("/api/index/status")
def index_status(request: Request):
    current_user(request)
    return _REINDEX.status()


def _corpus_overview(store, selected_source_ids, language: str) -> str:
    """Document list + section titles of the workspace, built by code (no model)."""
    labels = load_labels().get("overview", {})
    entries = [s for s in store.list_sources()
               if s.get("status", "READY") == "READY"
               and (selected_source_ids is None or s["source_id"] in selected_source_ids)]
    if not entries:
        return labels.get("empty", "")
    lines = [labels.get("header", "").format(n=len(entries))]
    for entry in entries:
        detail = store.source(entry["source_id"]) or {}
        sections = []
        for chunk in detail.get("chunks", []):
            title = (chunk.get("provenance") or {}).get("section_path")
            if title and title not in sections:
                sections.append(title)
        tail = (labels.get("sections", "") + ": " + "; ".join(sections[:8])) if sections else labels.get("no_sections", "")
        lines.append(f"- **{entry.get('source_name')}**: {tail}")
    return "\n".join(lines)


def owner_source_store(user: dict):
    if STORAGE_BACKEND == "postgres":
        return PostgresSourceStore(app.state.session_factory, str(user["user_id"]))
    root = Path(DATA_DIR) / "owners" / str(user["user_id"]) / "sources"
    return SourceStore(str(root))

def owner_run_store(user: dict, conversation_id: str | None = None):
    if STORAGE_BACKEND == "postgres":
        return PostgresRunStore(
            app.state.session_factory, str(user["user_id"]), conversation_id
        )
    root = Path(RUNS_DIR) / "owners" / str(user["user_id"])
    return RunStore(str(root))

def owner_pipeline(user: dict, conversation_id: str | None = None) -> ResearchPipeline:
    sources = owner_source_store(user)
    candidate_index = None
    if VECTOR_BACKEND not in {"", "disabled", "off", "none"}:
        vector_store = _configured_vector_store()
        if vector_store is not None:
            embedder = make_embedder(int(getattr(vector_store, "vector_size", 768) or 768))
            validate_embedding_config(embedder, int(getattr(vector_store, "vector_size", 768) or 768))
            candidate_index = CandidateIndex(
                sources,
                vector_store,
                owner_user_id=str(user["user_id"]),
                embedder=embedder,
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
        vector_size = effective_dimension(int(VECTOR_SIZE))
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
        embedder = make_embedder(int(getattr(vector_store, "vector_size", 768) or 768))
        validate_embedding_config(embedder, int(getattr(vector_store, "vector_size", 768) or 768))
        index = CandidateIndex(
            source_store,
            vector_store,
            owner_user_id=str(user["user_id"]),
            embedder=embedder,
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
        return PostgresConversationStore(app.state.session_factory, str(user["user_id"]))
    root = Path(DATA_DIR) / "owners" / str(user["user_id"]) / "conversations"
    return ConversationStore(root)


_SUMMARY_CACHE = _SummaryCache()


class ChatRequest(BaseModel):
    message: str
    condition: str | None = None
    provider: str | None = None
    conversation_id: str | None = None
    source_ids: list[str] | None = None
    product_mode: bool = False
    # Studio: trả lời theo ngôn ngữ câu hỏi ở lượt phân tích; trang Thực nghiệm không bật để giữ prompt nghiên cứu.
    reply_in_query_language: bool = False

class SourceTextRequest(BaseModel):
    source_name: str
    text: str

@app.get("/")
def index():
    return FileResponse(BASE / "app" / "static" / "index.html")

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "app": "local-multi-agent-rag",
        "version": "0.2.0-m0",
    }

@app.get("/api/config")
def config():
    cfg = RuntimeConfig.from_env()
    return {"implementation_profile": cfg.implementation_profile, "provider": cfg.provider,
            "task_top_k": cfg.task_top_k, "planning_top_k": cfg.planning_top_k,
            "max_context_tokens": cfg.max_context_tokens, "max_output_tokens": cfg.max_output_tokens,
            "max_run_tokens": cfg.max_run_tokens, "retry_limit": cfg.retry_limit,
            "retrieval_min_score": cfg.retrieval_min_score,
            "task_plan_max_output_tokens": cfg.task_plan_max_output_tokens,
            "allowed_conditions": cfg.allowed_conditions()}

@app.get("/api/ready")
async def ready():
    cached = _ready_cache.get()
    if cached is None:
        checks = {"postgres": check_postgres(app.state.session_factory), "qdrant": check_vector(_derived_vector_store)}
        checks["ollama"] = await check_ollama()
        cached = _ready_cache.set({"ready": all(v != "fail" for v in checks.values()),
                                   "checks": {k: {"status": v} for k, v in checks.items()}})
    from fastapi.responses import JSONResponse
    return JSONResponse(cached, status_code=200 if cached["ready"] else 503)

@app.get("/api/local-model/health")
async def local_model_health(request: Request):
    current_user(request)
    cached = _local_health_cache.get()
    if cached is not None:
        return cached
    try:
        return _local_health_cache.set(await OllamaProvider(timeout=2).health())
    except Exception:
        return _local_health_cache.set({"ok": False, "error": "LOCAL_MODEL_UNAVAILABLE"})

@app.get("/api/sources")
def list_sources(request: Request):
    user = current_user(request)
    store = owner_source_store(user)
    return {"snapshot_id": store.snapshot_id(), "sources": store.list_sources()}

@app.get("/api/sources/{source_id}")
def get_source(source_id: str, request: Request):
    item = owner_source_store(current_user(request)).source(source_id)
    if not item:
        raise HTTPException(404, "SOURCE_NOT_FOUND")
    return item

@app.get("/api/chunks/{chunk_id}")
def get_chunk(chunk_id: str, request: Request):
    item = owner_source_store(current_user(request)).chunk(chunk_id)
    if not item:
        raise HTTPException(404, "SOURCE_CHUNK_NOT_FOUND")
    return item

@app.post("/api/sources/text")
def import_text(body: SourceTextRequest, request: Request):
    if not body.text.strip():
        raise HTTPException(400, "EMPTY_TEXT")
    user = current_user(request)
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
        raise HTTPException(503, getattr(exc, "code", "DERIVED_INDEX_FAILED")) from exc

@app.post("/api/sources/file")
async def import_file(request: Request, file: UploadFile = File(...)):
    user = current_user(request)
    maximum_size = 2_000_000
    content_length = request.headers.get("content-length")
    # Multipart Content-Length includes its framing and file headers, so it can
    # exceed the file limit even when the uploaded file itself is exactly at it.
    if (content_length is not None and content_length.isdigit()
            and int(content_length) > maximum_size
            and not request.headers.get("content-type", "").lower().startswith("multipart/form-data")):
        raise HTTPException(413, "FILE_TOO_LARGE")
    chunks = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum_size:
            raise HTTPException(413, "FILE_TOO_LARGE")
        chunks.append(chunk)
    data = b"".join(chunks)

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
        if not source_name.lower().endswith(".pdf"):
            detail = "UNSUPPORTED_DOCUMENT_TYPE"
        raise HTTPException(415 if detail != "PDF_NO_TEXT" else 422, detail) from exc
    except UnicodeError as exc:
        raise HTTPException(415, "UTF8_TEXT_REQUIRED") from exc
    except ValueError as exc:
        if "must not be empty" in str(exc):
            raise HTTPException(400, "EMPTY_FILE") from exc
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
        raise HTTPException(503, getattr(exc, "code", "DERIVED_INDEX_FAILED")) from exc

def _chat_condition(body, runtime_config):
    """Return (condition, provider_name, fixed): same decisions as the original chat endpoint."""
    if body.product_mode:
        if body.condition is not None or body.provider is not None:
            raise HTTPException(400, "RESEARCH_CONTROLS_NOT_AVAILABLE")
        configured_provider = runtime_config.provider
        test_mode = os.getenv("APP_ENV", "development").strip().lower() == "test"
        if configured_provider == "fake" and test_mode:
            provider_name = configured_provider
        elif configured_provider == "ollama":
            provider_name = configured_provider
        else:
            raise HTTPException(503, "PRODUCT_PROVIDER_NOT_CONFIGURED")
        configured = os.getenv("PRODUCT_CONDITION", "").strip().upper()
        condition = configured or (
            "C" if runtime_config.implementation_profile in {"m1", "m2", "dev"} else "A"
        )
        return condition, provider_name, bool(configured)
    if body.condition is not None:
        return body.condition.upper(), body.provider, True
    return "A", body.provider, True


async def _chat_core(body: "ChatRequest", request: Request, on_event=None, notify=None):
    """One chat turn: intent -> memory/rewrite -> path choice -> pipeline. notify(step, text) reports progress."""
    from app.chat.answer_guard import AnswerChecker
    from app.chat.intent import (
        IntentDecision, classify_intent, classify_with_llm, definition_terms, mentions_terms,
    )
    from app.chat.language import document_language, text_language, translate_query
    from app.chat.memory import build_memory, has_reference, render_context, rewrite_follow_up
    from app.providers.factory import get_provider
    from app.review_adapters.auto_route import choose_path

    def say(step: str, text: str) -> None:
        if notify is not None:
            notify(step, text)

    message = body.message.strip()
    if not message:
        raise HTTPException(400, "MESSAGE_REQUIRED")
    try:
        user = current_user(request)
        t_start = time.perf_counter()
        runtime_config = RuntimeConfig.from_env()
        condition, provider_name, condition_fixed = _chat_condition(body, runtime_config)
        runtime_config.assert_condition(condition)
        conversations = owner_conversation_store(user)
        if body.conversation_id:
            conversation = conversations.get(body.conversation_id)
            if conversation is None:
                raise HTTPException(404, "CONVERSATION_NOT_FOUND")
            conversation_id = body.conversation_id
        else:
            conversation = None
            conversation_id = conversations.create(message[:120])["conversation_id"]
        has_history = bool(conversation and conversation.get("messages"))
        selected_source_ids = None if body.source_ids is None else [str(source_id) for source_id in body.source_ids]
        validator = getattr(owner_source_store(user), "validate_source_selection", None)
        if callable(validator) and selected_source_ids is not None:
            validator(selected_source_ids)

        provider = get_provider(provider_name)
        say("routing", "Đang xem bạn muốn hỏi gì…")
        decision = classify_intent(message, has_history=has_history)
        if decision.needs_llm:
            try:
                decision = await classify_with_llm(provider, message)
            except Exception:
                pass
        intent_info = {"intent": decision.intent, "reason": decision.reason, "language": decision.language}

        if decision.reply is not None:  # greeting/thanks/farewell/out_of_scope/about_system: no retrieval, no pipeline
            conversations.add_message(conversation_id, "USER", message)
            conversations.add_message(conversation_id, "ASSISTANT", decision.reply)
            return {
                "run_id": None, "status": "COMPLETE", "answer": decision.reply, "citations": [], "sources": [],
                "task_results": [], "events": [{"stage": "intent_routed", **intent_info, "retrieval": False}],
                "conversation_id": conversation_id, "intent": intent_info, "route": None, "rewritten_query": None,
            }

        timings = {"intent_ms": int((time.perf_counter() - t_start) * 1000)}
        store = owner_source_store(user)
        direct_path = None
        if decision.intent == "corpus_overview":  # built by code from the workspace's own document list
            overview = _corpus_overview(store, selected_source_ids, decision.language)
            conversations.add_message(conversation_id, "USER", message)
            conversations.add_message(conversation_id, "ASSISTANT", overview)
            return {
                "run_id": None, "status": "COMPLETE", "answer": overview, "citations": [], "task_results": [],
                "sources": [], "grounding": "document",
                "events": [{"stage": "intent_routed", **intent_info, "retrieval": False, "path": "OVERVIEW",
                            "grounded": True}, {"stage": "timings", **timings}],
                "conversation_id": conversation_id, "intent": intent_info, "route": None, "rewritten_query": None,
            }
        if decision.intent == "history_answer" and has_history:  # answer already in the recent conversation
            h0 = time.perf_counter()
            recent = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in (conversation.get("messages") or [])[-6:])
            result = await provider.generate(
                system=("Answer ONLY from the conversation below, in the language of the question, concisely. "
                        "If the answer is not stated in the conversation, reply exactly NOT_IN_HISTORY."),
                user=f"CONVERSATION:\n{recent}\n\nQUESTION: {message}",
            )
            timings["history_ms"] = int((time.perf_counter() - h0) * 1000)
            history_text = strip_placeholder_tags(str(getattr(result, "text", result)).strip())
            if history_text and "NOT_IN_HISTORY" not in history_text:
                direct_path, direct_text, direct_note = "HISTORY", history_text, ""
            else:
                decision = IntentDecision("follow_up", None, False, "HISTORY_MISS", decision.language)
                intent_info = {"intent": "follow_up", "reason": "HISTORY_MISS", "language": decision.language}
        elif decision.intent == "history_answer":
            decision = IntentDecision("document_question", None, False, "NO_HISTORY", decision.language)
            intent_info = {"intent": "document_question", "reason": "NO_HISTORY", "language": decision.language}
        if decision.intent == "general_knowledge" and decision.reason != "SELF_CONTAINED":
            # cheap retrieval gate: a definition-like question still goes to the documents when they clearly match
            try:
                has_docs = any(s.get("status", "READY") == "READY" for s in store.list_sources())
            except Exception:
                has_docs = True
            matched = []
            if has_docs:
                g0 = time.perf_counter()
                candidates = await asyncio.to_thread(
                    owner_pipeline(user, None)._retrieve_candidates, message, None, top_k=3,
                    min_score=runtime_config.retrieval_min_score, source_ids=selected_source_ids)
                # vector search always returns a nearest chunk, so a score alone cannot say "the documents cover
                # this": the defined term must literally occur in a retrieved chunk.
                matched = candidates if mentions_terms(definition_terms(message), [c.text for c in candidates]) else []
                timings["gate_ms"] = int((time.perf_counter() - g0) * 1000)
            if matched:
                decision = IntentDecision("document_question", None, False, "GATE_DOCUMENT_MATCH", decision.language)
                intent_info = {"intent": "document_question", "reason": "GATE_DOCUMENT_MATCH",
                               "language": decision.language}
        if direct_path is None and decision.intent == "general_knowledge":  # no retrieval, no pipeline
            say("answering", "Câu này không cần tài liệu, mình trả lời trực tiếp.")
            g0 = time.perf_counter()
            result = await provider.generate(
                system=("Answer the question directly and concisely, in the same language as the question. "
                        "Do not mention documents or sources."),
                user=message,
            )
            timings["answer_ms"] = int((time.perf_counter() - g0) * 1000)
            direct_path = "DIRECT"
            direct_text = strip_placeholder_tags(str(getattr(result, "text", result)).strip())
            direct_note = ""
        if direct_path is not None:
            answer = direct_text + direct_note
            conversations.add_message(conversation_id, "USER", message)
            conversations.add_message(conversation_id, "ASSISTANT", answer)
            return {
                "run_id": None, "status": "COMPLETE", "answer": answer, "citations": [], "task_results": [],
                "sources": [], "grounding": "none",
                "events": [{"stage": "intent_routed", **intent_info, "retrieval": False, "path": direct_path,
                            "grounded": False},
                           {"stage": "timings", **timings}],
                "conversation_id": conversation_id, "intent": intent_info, "route": None, "rewritten_query": None,
            }
        try:
            has_ready_sources = any(s.get("status", "READY") == "READY" for s in store.list_sources())
        except Exception:
            has_ready_sources = True
        if not has_ready_sources:
            reply = ("Hiện chưa có tài liệu nào trong kho nên mình chưa thể trả lời từ tài liệu. "
                     "Hãy tải tài liệu lên, hoặc hỏi một câu không cần tài liệu." if intent_info["language"] == "vi"
                     else "There are no documents yet, so I cannot answer from documents. "
                          "Upload a document, or ask a question that needs none.")
            conversations.add_message(conversation_id, "USER", message)
            conversations.add_message(conversation_id, "ASSISTANT", reply)
            return {
                "run_id": None, "status": "NO_EVIDENCE", "answer": reply, "citations": [], "task_results": [],
                "sources": [], "grounding": "none",
                "events": [{"stage": "intent_routed", **intent_info, "retrieval": False, "path": "EMPTY_STORE"},
                           {"stage": "timings", **timings}],
                "conversation_id": conversation_id, "intent": intent_info, "route": None, "rewritten_query": None,
            }
        try:
            maybe_start_reindex(user)
        except Exception:
            pass
        waiting = _reindex_reply(intent_info["language"])
        if waiting is not None:  # friendly answer instead of INDEX_INCOMPATIBLE while the index is being rebuilt
            conversations.add_message(conversation_id, "USER", message)
            conversations.add_message(conversation_id, "ASSISTANT", waiting["text"])
            return {
                "run_id": None, "status": "NO_EVIDENCE", "answer": waiting["text"], "citations": [], "task_results": [],
                "sources": [], "grounding": "document",
                "events": [{"stage": "intent_routed", **intent_info, "retrieval": False, "path": "REINDEXING"},
                           {"stage": "reindex_progress", **waiting["state"]}, {"stage": "timings", **timings}],
                "conversation_id": conversation_id, "intent": intent_info, "route": None, "rewritten_query": None,
                "index": waiting["state"],
            }
        m0 = time.perf_counter()
        memory = await build_memory(provider, str(user["user_id"]), conversation, cache=_SUMMARY_CACHE)
        timings["memory_ms"] = int((time.perf_counter() - m0) * 1000)
        query = message
        if has_history and (decision.intent == "follow_up" or has_reference(message)):
            say("rewriting", "Đang hiểu câu hỏi nối tiếp của bạn…")
            query = await rewrite_follow_up(provider, message, memory)
        context_text = render_context(memory)

        # G3: question in another language than the documents -> one model call to translate it before retrieval;
        # the answer still follows the asker's language.
        asker_language = text_language(message)
        reply_hint = None
        source_languages: set[str] = set()
        try:  # a few chunks of a few sources are enough to guess the documents' language
            sample = []
            for entry in store.list_sources()[:8]:
                if selected_source_ids is not None and entry["source_id"] not in selected_source_ids:
                    continue
                texts = [c.get("text", "") for c in (store.source(entry["source_id"]) or {}).get("chunks", [])[:6]]
                sample += texts
                if texts:
                    source_languages.add(text_language(" ".join(texts)))
        except Exception:
            sample = []
        doc_language = document_language(sample)
        other_languages = sorted(source_languages - {asker_language})
        if asker_language in source_languages:  # mixed corpus: some documents already match the question's language
            doc_language = None
        cross_language_query = None
        if asker_language in source_languages and len(other_languages) == 1 and                 os.getenv("CROSS_LANGUAGE_RETRIEVAL", "1") != "0":
            # translate once to the other language; retrieval then runs both versions and merges the results
            say("translating", "Kho có tài liệu ở ngôn ngữ khác, mình tìm cả hai cách diễn đạt…")
            t_x = time.perf_counter()
            cross_language_query = await translate_query(provider, query, other_languages[0])
            timings["cross_language_ms"] = int((time.perf_counter() - t_x) * 1000)
            if cross_language_query == query:
                cross_language_query = None
        timings["language_ms"] = int((time.perf_counter() - t_start) * 1000) - timings["intent_ms"]
        if doc_language and doc_language != asker_language:
            say("translating", "Đang chuyển câu hỏi sang ngôn ngữ của tài liệu…")
            translated = await translate_query(provider, query, doc_language)
            if translated != query:
                query = translated
                reply_hint = asker_language

        route = None
        if not condition_fixed:
            c_available = True
            try:
                runtime_config.assert_condition("C")
            except ValueError:
                c_available = False
            choice = choose_path(query, c_available=c_available)
            route = {"path": choice.path, "reason": choice.reason, "params": choice.params}
            condition = "C" if choice.path == "C" else "A"
        elif body.product_mode:
            route = {"path": "C" if condition.startswith("C") else "B", "reason": "CONFIGURED", "params": {}}
        if route is not None:
            say("route", "Câu hỏi nhiều ý, mình sẽ tìm riêng từng ý rồi gộp lại." if route["path"] == "C"
                else "Mình tra cứu trực tiếp trong tài liệu.")

        # Multi-step planning for chat is opt-in: in the local transcript it was slower (3-8x) and lost answers
        # that one grounded call found. Review runs use AUTO (route.chosen) separately.
        force_plan = bool(route and route["path"] == "C" and os.getenv("CHAT_FORCE_PLAN", "").strip() == "1")
        multi_retrieval = bool(
            route and route["path"] == "C" and not force_plan
            and os.getenv("CHAT_MULTI_RETRIEVAL", "1").strip() != "0")
        if route is not None:
            route["executed"] = "C" if force_plan else ("C_MULTI" if multi_retrieval else "B")
        conversations.add_message(conversation_id, "USER", message)
        EXTRA_RETRIEVAL_QUERIES.set((cross_language_query,) if cross_language_query else ())
        run = await owner_pipeline(user, conversation_id).run(
            query,
            condition,
            provider_name,
            source_ids=selected_source_ids,
            conversation_context=context_text,
            conversation_id=conversation_id,
            product_mode=body.product_mode,
            on_event=on_event,
            force_plan=force_plan,
            reply_language_hint=reply_hint,
            multi_retrieval=multi_retrieval,
            answer_checker=AnswerChecker(),
            reply_in_query_language=body.reply_in_query_language,
        )
        extra_ids = [c for r in (run.get("task_results") or []) for c in (r.get("citations") or [])]
        clean_answer, sources = number_sources(
            str(run.get("answer") or ""), store.chunk, extra_ids)
        if clean_answer:
            run["answer"] = strip_placeholder_tags(clean_answer)
        if sources and run.get("status") in {"COMPLETE", "PARTIAL"}:
            before = [x["doc_name"] for x in sources]
            kept_answer, sources, dropped = filter_sources(
                str(run.get("answer") or ""), sources, lambda cid: (store.chunk(cid) or {}).get("text", ""))
            if dropped:
                run["answer"] = kept_answer
                run.setdefault("events", []).append({"stage": "sources_filtered", "before": before,
                                                    "after": [x["doc_name"] for x in sources], "dropped": dropped})
        run["sources"] = sources
        run["grounding"] = "document"
        try:  # keep the numbered sources with the stored run so a reloaded conversation shows the same chips
            owner_run_store(user, conversation_id).save(run)
        except Exception:
            logging.getLogger(__name__).exception("could not store sources with the run")
        conversations.add_message(
            conversation_id,
            "ASSISTANT",
            str(run.get("answer") or run.get("status") or "Run completed"),
            run_id=run["run_id"],
        )
        timings["total_ms"] = int((time.perf_counter() - t_start) * 1000)
        events = list(run.get("events") or [])
        if route is not None:
            events.append({"stage": "route_chosen", **route})
        events.append({"stage": "timings", **timings})
        return {
            **run, "events": events, "conversation_id": conversation_id, "intent": intent_info,
            "route": route, "rewritten_query": query if query != message else None,
            "query_language": {"asker": asker_language, "documents": doc_language, "translated": bool(reply_hint)},
        }
    except LookupError as exc:
        raise HTTPException(404, "SOURCE_NOT_FOUND") from exc
    except IndexingError as exc:
        raise HTTPException(503, getattr(exc, "code", "DERIVED_INDEX_UNAVAILABLE")) from exc
    except ValueError:
        raise HTTPException(400, "VALIDATION_ERROR")


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    return await _chat_core(body, request)


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """Same turn as /api/chat as SSE: event 'status' {step,text} (many), then 'done' {chat response} or 'error'."""
    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    from app.chat.progress import friendly_error, stage_label

    queue: asyncio.Queue = asyncio.Queue()
    language = "vi" if any(ord(ch) > 127 for ch in body.message) or any(
        w in body.message.lower() for w in ("xin", "chao", "ban", "toi")) else "en"

    def on_event(event: dict) -> None:
        label = stage_label(event, language)
        if label is not None:
            queue.put_nowait(("status", label))

    def notify(step: str, text: str) -> None:
        queue.put_nowait(("status", {"step": step, "text": text}))

    async def worker() -> None:
        try:
            queue.put_nowait(("done", await _chat_core(body, request, on_event=on_event, notify=notify)))
        except HTTPException as exc:
            code = exc.detail if isinstance(exc.detail, str) else "UNKNOWN"
            queue.put_nowait(("error", {"http_status": exc.status_code, **friendly_error(code, language)}))
        except Exception:
            queue.put_nowait(("error", {"http_status": 500, **friendly_error("UNKNOWN", language)}))
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(worker())

    async def stream():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                name, data = item
                yield f"event: {name}\ndata: {_json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        finally:
            if not task.done():
                task.cancel()
            # Wait for pipeline cancellation to persist its terminal run status.
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs")
def list_runs(request: Request):
    return owner_run_store(current_user(request)).list()

@app.get("/api/runs/{run_id}")
def get_run(run_id: str, request: Request):
    run = owner_run_store(current_user(request)).get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


@app.get("/api/conversations")
def list_conversations(request: Request):
    return owner_conversation_store(current_user(request)).list()


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request):
    conversation = owner_conversation_store(current_user(request)).get(conversation_id)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    return conversation


# API bổ sung cho giao diện Studio (C1SE.27): thử truy xuất, so sánh điều kiện, trang quản trị.
from app.api.studio import build_router as _build_studio_router

app.include_router(_build_studio_router(
    current_user=current_user,
    owner_pipeline=owner_pipeline,
    session_factory=lambda: app.state.session_factory,
    owner_source_store=owner_source_store,
    vector_store=_configured_vector_store,
))


# Normalize legacy string details at non-review API boundaries.
@app.exception_handler(HTTPException)
async def structured_http_errors(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail, headers=exc.headers)
    code = str(detail).split(":", 1)[0]
    known = {"AUTHENTICATION_REQUIRED", "SOURCE_NOT_FOUND", "SOURCE_CHUNK_NOT_FOUND",
             "RUN_NOT_FOUND", "CONVERSATION_NOT_FOUND", "EMPTY_TEXT", "EMPTY_FILE", "FILE_TOO_LARGE", "MESSAGE_REQUIRED",
             "PDF_NO_TEXT", "PDF_EXTRACTION_UNAVAILABLE", "UNSUPPORTED_DOCUMENT_TYPE",
             "UTF8_TEXT_REQUIRED", "DOCUMENT_EXTRACTION_FAILED", "DERIVED_INDEX_FAILED",
             "DERIVED_INDEX_UNAVAILABLE", "RESEARCH_CONTROLS_NOT_AVAILABLE",
             "PRODUCT_PROVIDER_NOT_CONFIGURED", "VALIDATION_ERROR",
             "INDEX_INCOMPATIBLE", "INDEX_LEGACY_UNVERIFIED"}
    if code not in known:
        code = "INTERNAL_ERROR" if exc.status_code >= 500 else "VALIDATION_ERROR"
    return JSONResponse(status_code=exc.status_code,
                        content={"code": code, "message": "Request could not be completed"},
                        headers=exc.headers)
# Chức năng phân tích của Studio (truy vết yêu cầu, báo cáo); không đi qua /api/chat hay điều kiện A/B/C.
from app.api.analysis import build_router as _build_analysis_router

app.include_router(_build_analysis_router(
    current_user=current_user,
    owner_pipeline=owner_pipeline,
    session_factory=lambda: app.state.session_factory,
))

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

_AUDITED = [(m, _re.compile(p), label) for m, p, label in (
    ("POST", r"^/api/sources/(text|file)$", "Nạp tài liệu"),
    ("DELETE", r"^/api/studio/sources/(?P<t>[^/]+)$", "Xóa tài liệu"),
    ("POST", r"^/api/chat$", "Đặt câu hỏi"),
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
        await _in_thread(_audit_write, owner, label, getattr(request.state, "audit_target", None) or match.groupdict().get("t") or "", response.status_code)
    except Exception:
        _logging.getLogger(__name__).warning("Không ghi được nhật ký hoạt động", exc_info=True)
    return response
