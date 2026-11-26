from __future__ import annotations
import asyncio
import threading
import os
from contextvars import ContextVar
import unicodedata
import re
import time
import uuid
import httpx
from dataclasses import asdict
from datetime import datetime, timezone
from app.core.config import RuntimeConfig
from app.core.graph import topological_order, validate_tasks
from app.core.telemetry import cpu_busy_percent, cpu_times, model_rss_mb, process_rss_mb, gpu_memory_mb
from app.core.types import SourceChunk, Task, TaskPlan, TaskResult, RunMetrics
from app.providers.factory import get_provider
from app.research.context_controller import ContextController
from app.research.provenance import build_provenance
from app.research.token_budget import resolve_product_num_ctx
from app.research.token_context import TokenContextController, context_policy, plan_task_budgets
from app.research.conversation_context import ConversationContext, resolve_follow_up
from app.research.plan_anchoring import anchor_and_verify
from app.research.decomposer import (
    canonicalize_task_plan,
    PLANNER_SEMANTICS_VERSION,
    TASK_PLAN_PROMPT_VERSION,
    _safe_warning,
    build_semantic_task_plan_repair_prompt,
    decompose_plan,
    generate_task_plan,
    parse_task_plan_output,
    understand_request,
)
from app.research.normalizer import normalize_tasks
from app.research.obligation_concern_extraction import extract_obligations_and_concerns
from app.research.product_intents import (
    is_library_question,
    is_simple_project_question,
    library_answer,
    product_help_response,
)
from app.ingestion.doc_type import DOC_TYPES
from app.research.plan_verification import (
    decide_repair,
    validate_repaired_plan,
    verify_task_plan,
)
from app.research.planning_retrieval import PlanningRetriever, PLANNING_SCORER_VERSION
from app.research.agent_selection import PACK_DESCRIPTIONS, forced_selection, select_agents
from app.research.reviewer import annotate, review_answer, reviewer_enabled, reviewer_revise_enabled, revision_note
from app.research.agent_tools import TOOL_SEARCH_CHUNKS, agent_tools_enabled, status_rank, tool_query
from app.research.knowledge_source import BOTH, BOTH_HINT, GENERAL, answer_general, choose_source, doc_bound, label as knowledge_label
from app.research.registry import OFFICE_PACK, SELECTION_PACKS, active_pack, active_pack_name, profile, use_pack, use_work_context
from app.research.worker import execute_task
from app.research.progress import emit, emit_validated_answer
from app.research.synthesizer import synthesize
from app.research.vanilla import answer_vanilla
from app.retrieval.text import retrieve, apply_token_budget, estimate_tokens, terms
from app.retrieval.source_focus import focus_sources
from app.retrieval.hybrid import POOL as HYBRID_POOL, bm25_scores, continue_articles, fuse as hybrid_fuse
from app.retrieval.multilingual import build_query_variants, detect_language
from app.storage.source_store import SourceStore
from app.storage.run_store import RunStore

CONDITIONS = {"A", "B", "C", "C-P", "C-N", "C-O"}
# truy xuất (nhúng câu hỏi qua HTTP đồng bộ, chỉ mục vector nhúng) chạy ở luồng phụ trong ô chat sản phẩm để không giữ vòng lặp
# sự kiện (đo 23/11: sự kiện tới trình duyệt muộn tới 5 s); khóa để hai việc con song song không gọi chỉ mục cùng lúc
_RETRIEVE_LOCK = threading.Lock()
_LEXICAL_FALLBACK_FILLERS = frozenset(
    {"what", "which", "who", "where", "when", "why", "how", "doe", "do", "did", "use", "used", "dùng", "gì"}
)


def resolve_product_simple_max_output_tokens(synth_limit: int) -> int:
    """Calibrated output limit for single-pass product answers (avoids 1800-token tail stalls)."""
    upper = max(256, int(synth_limit))
    try:
        val = int(os.getenv("PRODUCT_SIMPLE_MAX_OUTPUT_TOKENS", "1200") or 1200)
    except ValueError:
        val = 1200
    return max(256, min(val, upper))


def resolve_product_llm_timeout_seconds(provider: object) -> float | None:
    """Calibrated HTTP timeout for product-mode requests when not explicitly overridden by LOCAL_LLM_TIMEOUT_SECONDS."""
    if os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "").strip():
        return None
    if getattr(provider, "_explicit_timeout", False):
        return None
    try:
        val = float(os.getenv("PRODUCT_LLM_TIMEOUT_SECONDS", "240") or 240.0)
    except ValueError:
        val = 240.0
    return max(10.0, min(val, 600.0))


def classify_run_error(exc: Exception) -> tuple[str, int | None]:
    """Distinguish request timeout vs provider HTTP/connection/stream errors cleanly."""
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "request_timeout", None
    if isinstance(exc, httpx.ConnectError):
        return "provider_connection_error", None
    if isinstance(exc, httpx.HTTPStatusError):
        code = getattr(getattr(exc, "response", None), "status_code", None)
        return "provider_http_error", int(code) if code is not None else None
    if isinstance(exc, RuntimeError) and "ollama stream" in str(exc).lower():
        return "provider_stream_error", None
    return "pipeline_error", None


def reply_language_of(query: str) -> str:
    """Có dấu tiếng Việt thì trả lời tiếng Việt (detect_language bỏ sót chữ như "ệ", "ề")."""
    has_vi_marks = any(unicodedata.combining(ch) for ch in unicodedata.normalize("NFD", query)) or "đ" in query.lower()
    return "vi" if has_vi_marks or detect_language(query) != "en" else "en"


class ResearchPipeline:
    def __init__(
        self,
        source_store: SourceStore,
        run_store: RunStore,
        candidate_index=None,
        retrieval_backend: str = "lexical",
    ):
        self.source_store = source_store
        self.run_store = run_store
        self.candidate_index = candidate_index
        self.retrieval_backend = retrieval_backend if candidate_index else "lexical"
        self.planning = PlanningRetriever()

    def _retrieve_candidates(
        self,
        query: str,
        chunks: list[SourceChunk],
        *,
        top_k: int,
        min_score: float,
        source_ids: list[str] | None,
        fallback_trace: dict | None = None,
        hybrid: bool = False,
    ) -> list[SourceChunk]:
        if source_ids is not None:
            allowed_sids = set(source_ids)
            chunks = [c for c in chunks if c.source_id in allowed_sids]
        variants = build_query_variants(query)
        if hybrid and active_pack_name() == OFFICE_PACK:
            # Đợt 8: câu nêu tên tài liệu ("theo nội quy", "quy chế 2026") chỉ tìm trong tài liệu đó
            focused = focus_sources(query, chunks, source_ids)
            if focused:
                source_ids = focused
                chunks = [c for c in chunks if c.source_id in focused]  # BM25 chạy trên danh sách đoạn: lọc luôn
                if fallback_trace is not None:
                    fallback_trace["source_focus"] = focused
            else:
                # câu nhiều vế chỉ nêu một tài liệu (vòng khóa 1: "theo nội quy, tạm ứng 6 triệu…" lấy nhầm PayNhanh):
                # không lọc hẳn (vế kia có thể ở tài liệu khác) nhưng đưa đoạn của tài liệu được nêu lên trước
                preferred = focus_sources(query, chunks, source_ids, allow_multi_part=True) or _DOC_HINT.get()
                if preferred and source_ids is not None:
                    preferred = [p for p in preferred if p in source_ids]
                if preferred:
                    first = self._retrieve_hybrid(query, variants, [c for c in chunks if c.source_id in preferred], top_k=top_k,
                                                  min_score=min_score, source_ids=preferred, trace=None)
                    rest = self._retrieve_hybrid(query, variants, chunks, top_k=top_k, min_score=min_score, source_ids=source_ids,
                                                 trace=fallback_trace)
                    seen = {c.chunk_id for c in first}
                    half = max(1, top_k // 2)
                    merged = first[:half] + [c for c in rest if c.chunk_id not in seen]
                    if fallback_trace is not None:
                        fallback_trace["source_prefer"] = preferred
                    return continue_articles(merged[:top_k], chunks)
        if hybrid:
            # chỉ chế độ sản phẩm (Đợt 3): vector + BM25 + tiêu đề mục; A/B/C không đi nhánh này
            found = self._retrieve_hybrid(query, variants, chunks, top_k=top_k, min_score=min_score, source_ids=source_ids, trace=fallback_trace)
            return continue_articles(found, chunks)
        if self.candidate_index is None:
            merged: dict[str, SourceChunk] = {}
            for variant in variants:
                for chunk in retrieve(variant.text, chunks, top_k=top_k, min_score=min_score):
                    current = merged.get(chunk.chunk_id)
                    if current is None or (chunk.score or 0.0) > (current.score or 0.0):
                        merged[chunk.chunk_id] = chunk
            return sorted(merged.values(), key=lambda c: c.score or 0.0, reverse=True)[:top_k]

        # CandidateIndex applies owner/source filters in the vector query before top-k.
        # Hydrate only canonical chunks already scoped by the owner source store.
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        matches_by_id = {}
        for variant in variants:
            for match in self.candidate_index.candidates(variant.text, limit=top_k, source_ids=source_ids):
                existing = matches_by_id.get(str(match.payload.get("chunk_id") or ""))
                if existing is None or match.score > existing.score:
                    matches_by_id[str(match.payload.get("chunk_id") or "")] = match
        matches = sorted(matches_by_id.values(), key=lambda match: match.score, reverse=True)[:top_k]
        candidates: list[SourceChunk] = []
        for match in matches:
            chunk_id = str(match.payload.get("chunk_id") or "")
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None or match.score < min_score:
                continue
            candidates.append(SourceChunk(**{**chunk.__dict__, "score": match.score}))
        if candidates:
            return candidates

        # The index is derived and can miss paraphrases. Fall back only over the
        # already owner-scoped canonical chunks supplied by the source store.
        # Keep the same top-k and score gate; normalize only generic query fillers.
        fallback_map: dict[str, SourceChunk] = {}
        for variant in variants:
            lexical_query = " ".join(sorted(terms(variant.text) - _LEXICAL_FALLBACK_FILLERS)) or variant.text
            for chunk in retrieve(lexical_query, chunks, top_k=top_k, min_score=min_score):
                current = fallback_map.get(chunk.chunk_id)
                if current is None or (chunk.score or 0.0) > (current.score or 0.0):
                    fallback_map[chunk.chunk_id] = chunk
        fallback = sorted(fallback_map.values(), key=lambda c: c.score or 0.0, reverse=True)[:top_k]
        if fallback_trace is not None:
            fallback_trace.update(
                backend="lexical",
                reason="no_vector_candidate_met_min_score",
                candidate_count=len(fallback),
            )
        return fallback

    async def _retrieve_async(self, product: bool, *args, **kwargs):
        """Như _retrieve_candidates; ô chat sản phẩm chạy ở luồng phụ (thực nghiệm giữ nguyên chạy thẳng)."""
        if not product:
            return self._retrieve_candidates(*args, **kwargs)

        def run():
            with _RETRIEVE_LOCK:
                return self._retrieve_candidates(*args, **kwargs)
        return await asyncio.to_thread(run)

    def _split_subqueries(self, query: str) -> list[str]:
        head = query.split("[Ảnh đính kèm, chữ nhận dạng được]:", 1)[0].strip()
        parts = [
            p.strip(" ?.,;")
            for p in re.split(r"[?;]|\s+(?:và|đồng thời|còn)\s+", head, flags=re.I)
            if len(p.strip().split()) >= 2
        ]
        # Giữ tối đa 3 vế độc lập nếu câu thực sự nhiều ý
        return parts[:3] if len(parts) >= 2 else []

    def _retrieve_hybrid(self, query, variants, chunks, *, top_k, min_score, source_ids, trace):
        scope_set = None if source_ids is None else set(source_ids)
        scope_chunks = [c for c in chunks if scope_set is None or c.source_id in scope_set]
        vector_ranked: list[str] = []
        if self.candidate_index is not None:
            best: dict[str, float] = {}
            for variant in variants:
                for match in self.candidate_index.candidates(variant.text, limit=top_k * HYBRID_POOL, source_ids=source_ids):
                    cid = str(match.payload.get("chunk_id") or "")
                    if match.score >= min_score and match.score > best.get(cid, -1.0):
                        best[cid] = match.score
            vector_ranked = sorted(best, key=lambda cid: (-best[cid], cid))
        fused, info = hybrid_fuse(query, scope_chunks, vector_ranked, top_k)

        # Workstream A: kiểm tra từng vế độc lập + bao phủ nhiều nguồn được chọn bằng BM25 thuần Python (0 tốn Ollama embed)
        subqueries = self._split_subqueries(query)
        distinct_scope_sids = list(dict.fromkeys(c.source_id for c in scope_chunks))
        if scope_chunks and (subqueries or len(distinct_scope_sids) >= 2):
            fused_ids = {c.chunk_id for c in fused}
            by_cid = {c.chunk_id: c for c in scope_chunks}
            rrf_ceiling = (fused[-1].score or (1.0 / 61.0)) * 0.98 if fused else (1.0 / 61.0)

            def _scaled_rescue_score(raw_bm25: float, existing: float | None) -> float:
                # Quy đổi điểm BM25 thô về thang RRF bị chặn trên để không bóp méo thứ tự xếp hạng chính
                scaled = rrf_ceiling * (raw_bm25 / (raw_bm25 + 2.0)) if raw_bm25 > 0 else 0.0
                return round(max(float(existing or 0.0), scaled), 6)

            rescue: list[SourceChunk] = []
            subq_anchor_ids: set[str] = set()
            # 1) Bổ sung đoạn khớp nhất cho từng vế chưa có mặt trong fused
            for sub_q in subqueries:
                sub_scores = bm25_scores(sub_q, scope_chunks)
                ranked_sub = sorted((cid for cid, sc in sub_scores.items() if sc > 0.0), key=lambda cid: (-sub_scores[cid], cid))
                if not ranked_sub:
                    continue
                top_cid = ranked_sub[0]
                subq_anchor_ids.add(top_cid)
                if top_cid not in fused_ids:
                    c = by_cid[top_cid]
                    rescue.append(SourceChunk(**{**c.__dict__, "score": _scaled_rescue_score(float(sub_scores[top_cid]), c.score)}))
                    fused_ids.add(top_cid)
            # 2) Nếu có >=2 nguồn khác nhau trong scope và có nguồn liên quan chưa có đoạn nào trong fused, lấy top BM25 nếu thật sự khớp (score > 0.5)
            covered_sids = {c.source_id for c in fused} | {c.source_id for c in rescue}
            if len(distinct_scope_sids) >= 2:
                full_scores = bm25_scores(query, scope_chunks)
                for sid in distinct_scope_sids:
                    if sid in covered_sids:
                        continue
                    src_cids = [c.chunk_id for c in scope_chunks if c.source_id == sid and full_scores.get(c.chunk_id, 0.0) > 0.5]
                    if src_cids:
                        best_cid = max(src_cids, key=lambda cid: full_scores[cid])
                        if best_cid not in fused_ids:
                            c = by_cid[best_cid]
                            rescue.append(SourceChunk(**{**c.__dict__, "score": _scaled_rescue_score(float(full_scores[best_cid]), c.score)}))
                            fused_ids.add(best_cid)
                            covered_sids.add(sid)
            if rescue:
                # Bảo toàn đoạn #1 chính, các neo vế (subquery) đã có và đoạn from_bm25_only trước khi loại bớt phần đuôi
                bm25_only_ids = set(info.get("from_bm25_only") or ())
                merged: list[SourceChunk] = []
                seen_merged: set[str] = set()

                def _push(chunk: SourceChunk) -> None:
                    if len(merged) < top_k and chunk.chunk_id not in seen_merged:
                        merged.append(chunk)
                        seen_merged.add(chunk.chunk_id)

                if fused:
                    _push(fused[0])
                for c in fused[1:]:
                    if c.chunk_id in subq_anchor_ids:
                        _push(c)
                for r in rescue:
                    _push(r)
                for c in fused[1:]:
                    if c.chunk_id in bm25_only_ids:
                        _push(c)
                for c in fused[1:]:
                    _push(c)
                fused = merged
                info = {**info, "subquery_rescue": [c.chunk_id for c in rescue]}

        if trace is not None:
            trace.update(backend="hybrid", **info)
        return fused

    async def run(self, query: str, condition: str = "A", provider_name: str | None = None, *,
                  domain_pack: str | None = None, **kwargs) -> dict:
        """Chạy một lượt với bộ lĩnh vực của không gian; None = Phần mềm (hành vi và prompt như cũ)."""
        with use_pack(domain_pack):
            examples = kwargs.pop("routing_examples", None)  # Đợt 8: chỉ bộ "work" (ô chat sản phẩm) dùng
            pack = active_pack_name()
            if pack not in SELECTION_PACKS:
                kwargs.pop("forced_agent", None)
                return await self._run(query, condition, provider_name, **kwargs)
            # Bộ "work" (đợt 5): chọn tác tử theo ý nghĩa + nạp kiến thức ngành theo loại tài liệu trong phạm vi hỏi
            doc_types = self._doc_types(kwargs.get("source_ids"))
            embedder = getattr(self.candidate_index, "embedder", None)
            forced = kwargs.pop("forced_agent", None)
            if forced and forced not in PACK_DESCRIPTIONS[pack]:
                forced = None  # nút hỏi lại của bộ khác (đổi PRODUCT_AGENT_PACK giữa chừng): chọn lại theo ý nghĩa, không báo lỗi
            try:
                selection = (forced_selection(forced, pack) if forced
                             else await asyncio.to_thread(select_agents, query, getattr(embedder, "embed", None), examples, pack))
            except ValueError:
                raise
            except Exception as exc:  # mô hình nhúng lỗi: chọn theo từ khóa, ghi lại lý do
                selection = {**select_agents(query, None, pack=pack), "embed_error": type(exc).__name__}
            selection["doc_types"] = sorted(doc_types)
            hint_token = None
            if pack == OFFICE_PACK:
                try:
                    sids = kwargs.get("source_ids")
                    hint_token = _DOC_HINT.set(focus_sources(query, self.source_store.chunks(sids) if sids else self.source_store.chunks(
                        [x["source_id"] for x in self.source_store.list_sources()]), sids, allow_multi_part=True))
                except Exception:  # gợi ý chỉ để ưu tiên; lỗi thì bỏ qua
                    hint_token = None
            try:
                with use_work_context(doc_types, selection["agents"]):
                    return await self._run(query, condition, provider_name, agent_selection=selection, **kwargs)
            finally:
                if hint_token is not None:
                    _DOC_HINT.reset(hint_token)

    def _doc_types(self, source_ids: list[str] | None) -> set[str]:
        lister = getattr(self.source_store, "list_sources", None)
        if not callable(lister):
            return set()
        wanted = set(source_ids) if source_ids is not None else None
        return {s.get("doc_type") for s in lister() if s.get("doc_type") and (wanted is None or s["source_id"] in wanted)}

    async def _run(
        self,
        query: str,
        condition: str = "A",
        provider_name: str | None = None,
        *,
        source_ids: list[str] | None = None,
        conversation_context: ConversationContext | str | None = None,
        conversation_id: str | None = None,
        product_mode: bool = False,
        reply_in_query_language: bool = False,
        agent_selection: dict | None = None,
    ) -> dict:
        condition = condition.upper()
        answer_language = reply_language_of(query) if (product_mode or reply_in_query_language) else None
        if condition not in CONDITIONS:
            raise ValueError(f"Unknown condition {condition}")
        if isinstance(conversation_context, str):
            conversation_context = ConversationContext(text=conversation_context)
        elif not isinstance(conversation_context, ConversationContext):
            conversation_context = ConversationContext()
        if source_ids is not None:
            source_ids = [str(source_id) for source_id in source_ids]
            validator = getattr(self.source_store, "validate_source_selection", None)
            if callable(validator):
                validator(source_ids)
        cfg = RuntimeConfig.from_env()
        cfg.assert_condition(condition)
        # AI-GUARD-01: trần lượt gọi LLM thực tế (pre-flight) & giới hạn thời gian chạy toàn phiên từ trước bước extract/plan.
        try:
            max_llm_calls = max(1, int(os.getenv("MAX_RUN_LLM_CALLS", "24") or 24))
        except ValueError:
            max_llm_calls = 24
        try:
            dag_wall_seconds = float(os.getenv("MAX_DAG_WALL_SECONDS", "300") or 300.0)
        except ValueError:
            dag_wall_seconds = 300.0
        if dag_wall_seconds <= 0:
            dag_wall_seconds = 300.0
        dag_deadline = time.monotonic() + dag_wall_seconds
        guarded = _GuardedProvider(get_provider(provider_name), max_calls=max_llm_calls, deadline=dag_deadline)
        provider = guarded
        started = time.perf_counter()
        metrics = RunMetrics(peak_rss_mb=process_rss_mb(), gpu_memory_mb=gpu_memory_mb())
        cpu_start = cpu_times()
        events: list[dict] = []
        run_id = "run_" + uuid.uuid4().hex[:12]
        created_at = datetime.now(timezone.utc).isoformat()
        flags = self._flags(condition)
        source_snapshot = self.source_store.snapshot_id()
        lifecycle_status = "PENDING"
        effective = {
            "condition": condition,
            "implementation_profile": cfg.implementation_profile,
            "flags": flags,
            "task_top_k": cfg.task_top_k,
            "planning_top_k": cfg.planning_top_k,
            "max_context_tokens": cfg.max_context_tokens,
            "max_output_tokens": cfg.max_output_tokens,
            "task_plan_max_output_tokens": cfg.task_plan_max_output_tokens,
            "max_run_tokens": cfg.max_run_tokens,
            "retry_limit": cfg.retry_limit,
            "retrieval_min_score": cfg.retrieval_min_score,
            "retrieval_backend": self.retrieval_backend,
            "planning_scorer_version": PLANNING_SCORER_VERSION,
            "domain_pack": active_pack_name(),
            "task_plan_prompt_version": TASK_PLAN_PROMPT_VERSION,
            "task_plan_schema_version": "canonical-task-plan-explicit-coverage-v2",
            "conversation_id": conversation_id,
            "conversation_context": conversation_context.to_trace(),
        }
        policy = context_policy()
        effective["context_policy"] = policy
        product_num_ctx: int | None = None
        product_timeout: float | None = None
        simple_output_limit = cfg.synthesis_max_output_tokens
        if product_mode:
            product_num_ctx = resolve_product_num_ctx()
            simple_output_limit = resolve_product_simple_max_output_tokens(cfg.synthesis_max_output_tokens)
            product_timeout = resolve_product_llm_timeout_seconds(guarded._inner)
            effective["synthesis_max_output_tokens"] = cfg.synthesis_max_output_tokens
            effective["product_simple_max_output_tokens"] = simple_output_limit
            effective["product_num_ctx"] = product_num_ctx
            if product_timeout is not None:
                effective["product_llm_timeout_seconds"] = product_timeout
        embedder = getattr(self.candidate_index, "embedder", None)
        provenance = build_provenance(
            provider_name=provider.name,
            model=provider.model,
            embedding_version=getattr(embedder, "version", None) if embedder else "lexical",
            context_policy=policy,
        )

        def event(stage: str, **data):
            events.append({"stage": stage, "ts": datetime.now(timezone.utc).isoformat(), **data})
            # ô chat sản phẩm (stream): báo bước đang làm; chỉ gửi tên bước và mã nhiệm vụ, không gửi nội dung
            # thêm cờ trạng thái để văn phòng 3D Trực tiếp diễn giống Xem lại (23/11); không gửi nội dung trả lời/tài liệu
            brief = {k: data[k] for k in ("task_id", "domain", "classification", "agents", "has_documents", "document_bound",
                                          "source", "review_status", "waves", "limit",
                                          # công cụ của chuyên gia, Reviewer trả bài (23/11): chỉ tên công cụ, số lượng, trạng thái
                                          "tool", "added", "before", "after", "revision") if k in data}
            if isinstance(data.get("unsupported"), list):
                brief["unsupported"] = len(data["unsupported"])  # chỉ số lượng: danh sách chứa câu trích từ câu trả lời
            elif isinstance(data.get("unsupported"), int):
                brief["unsupported"] = data["unsupported"]
            # chỉ số lượng (23/11): văn phòng biết RAG có tìm thấy đoạn nào không, kế hoạch có mấy việc con
            if isinstance(data.get("selected"), list):
                brief["selected_count"] = len(data["selected"])
            if isinstance(data.get("tasks"), list):
                brief["task_count"] = len(data["tasks"])
            elif isinstance(data.get("task_count"), int):
                brief["task_count"] = data["task_count"]
            if isinstance(data.get("result"), dict) and data["result"].get("task_id"):
                brief["task_id"] = data["result"]["task_id"]
                brief["result"] = {k: data["result"][k] for k in ("task_id", "domain", "status") if data["result"].get(k)}
                if data["result"].get("domain"):
                    brief["domain"] = data["result"]["domain"]  # tác tử làm việc này (văn phòng 3D biết ai vừa xong)
            emit({"type": "progress", "stage": stage, **brief})

        def make_run(status: str | None, answer: str, tasks: list[Task], task_results: list[TaskResult]) -> dict:
            top_citations = list(dict.fromkeys(
                cid for r in task_results
                if (not product_mode or r.status != "NO_EVIDENCE")
                for cid in (r.citations or []) if cid
            ))
            return {
                "run_id": run_id,
                "created_at": created_at,
                "condition": condition,
                "implementation_profile": cfg.implementation_profile,
                "provider": provider.name,
                "model": provider.model,
                "query": query,
                "conversation_id": conversation_id,
                "conversation_context": conversation_context.to_trace(),
                "lifecycle_status": lifecycle_status,
                "status": status,
                "answer": answer,
                "citations": top_citations,
                "source_snapshot_id": source_snapshot,
                "config_hash": cfg.config_hash(),
                "tasks": [asdict(t) for t in tasks],
                "task_results": [asdict(r) for r in task_results],
                "metrics": metrics.to_dict(),
                "events": events,
                "effective_config": effective,
                "provenance": provenance,
            }

        def persist_lifecycle(status: str) -> None:
            nonlocal lifecycle_status
            lifecycle_status = status
            self.run_store.save(make_run(None, "", [], []))

        def finalize(status: str, answer: str, tasks: list[Task], task_results: list[TaskResult]) -> dict:
            nonlocal lifecycle_status
            metrics.latency_ms = int((time.perf_counter() - started) * 1000)
            metrics.peak_rss_mb = max(filter(lambda x: x is not None, [metrics.peak_rss_mb, process_rss_mb()]), default=None)
            metrics.gpu_memory_mb = gpu_memory_mb()
            metrics.cpu_percent = cpu_busy_percent(cpu_start)
            metrics.model_rss_mb = model_rss_mb()
            lifecycle_status = "FAILED" if status == "FAILED" else "COMPLETED"
            run = make_run(status, answer, tasks, task_results)
            self.run_store.save(run)
            return run

        if agent_selection is not None:
            effective["agent_selection"] = agent_selection
        persist_lifecycle("PENDING")
        if agent_selection is not None:
            event("agent_selection", **agent_selection)
        event(
            "run_started",
            lifecycle_status=lifecycle_status,
            answer_language=answer_language,
            condition=condition,
            provider=provider.name,
            model=provider.model,
            implementation_profile=cfg.implementation_profile,
            source_snapshot_id=source_snapshot,
            config_hash=cfg.config_hash(),
            flags=flags,
        )
        event("conversation_context", **conversation_context.to_trace())
        persist_lifecycle("RUNNING")
        event("lifecycle_transition", from_status="PENDING", to_status="RUNNING")
        tasks: list[Task] = []
        task_results: list[TaskResult] = []
        synth_meta: dict = {}
        budget_stopped = False
        budget_event_emitted = False

        def budget_exceeded_reason() -> str | None:
            if guarded.exceeded_reason is not None:
                return guarded.exceeded_reason
            if metrics.input_tokens + metrics.output_tokens > cfg.max_run_tokens:
                return "token_budget"
            if guarded.attempted_calls >= max_llm_calls or metrics.llm_calls >= max_llm_calls:
                return "max_llm_calls"
            if time.monotonic() >= dag_deadline:
                return "wall_timeout"
            return None

        def emit_budget_stopped(reason: str) -> None:
            nonlocal budget_stopped, budget_event_emitted
            budget_stopped = True
            if not budget_event_emitted:
                budget_event_emitted = True
                event(
                    "run_budget_exceeded",
                    reason=reason,
                    total_tokens=metrics.input_tokens + metrics.output_tokens,
                    llm_calls=metrics.llm_calls,
                    attempted_llm_calls=guarded.attempted_calls,
                    limit=max_llm_calls,
                )

        try:
            product_help = product_help_response(query) if product_mode else None
            if product_mode and product_help is None and is_library_question(query):
                # câu hỏi về chính kho ("kho có những tài liệu gì"): trả lời từ danh sách tài liệu thật, không tìm đoạn gần nghĩa
                rows = [s for s in self.source_store.list_sources() if source_ids is None or s["source_id"] in source_ids]
                product_help = ("library", library_answer(rows, DOC_TYPES))
            if product_help is not None:
                intent, answer = product_help
                task = Task(task_id="T1", goal=query, domain="general")
                result = TaskResult(
                    task_id=task.task_id,
                    domain=task.domain,
                    status="COMPLETE",
                    answer=answer,
                )
                event(
                    "product_help_response",
                    intent=intent,
                    source_grounding_required=False,
                )
                event("task_completed", result=asdict(result))
                event("run_finished", status="COMPLETE", lifecycle_status="COMPLETED")
                return finalize("COMPLETE", answer, [task], [result])

            understanding = understand_request(query) if product_mode else None
            # Chỉ ở chế độ sản phẩm: câu hỏi tiếp nối ngắn được hiểu theo câu hỏi trước (không phải bằng chứng).
            follow_up = resolve_follow_up(query, conversation_context) if product_mode else None
            if follow_up:
                event("follow_up_resolved", previous_request=follow_up, is_rag_evidence=False)
            simple_retrieval_query = (
                "\n".join((query, follow_up)) if follow_up
                else _retrieval_query_with_conversation_context(query, conversation_context)
            )
            simple_product_request = bool(
                product_mode
                and condition != "A"
                and understanding is not None
                and is_simple_project_question(query, [d for d in understanding.domains
                                                       if not (active_pack_name() == OFFICE_PACK and d in ("analyst", "general"))])
            )
            if product_mode and condition != "A":
                route = (
                    "SIMPLE_PROJECT_QUESTION"
                    if simple_product_request
                    else "COMPLEX_PROJECT_REQUEST"
                )
                effective["request_route"] = route
                event(
                    "product_request_routing",
                    classification=route,
                    path=("simple_grounded_rag" if simple_product_request else "s3_planning"),
                    planner_required=not simple_product_request,
                    condition=condition,
                    detected_domains=list(understanding.domains),
                )
                event("request_understanding", **understanding.to_dict())

            all_chunks = self.source_store.chunks(source_ids)
            # Bước điều phối "chọn nguồn tri thức" (23/11): chỉ ô chat sản phẩm; điều kiện A và thực nghiệm giữ nguyên.
            knowledge_on = bool(product_mode and condition != "A")
            has_docs = bool(all_chunks)
            bound = knowledge_on and doc_bound(query, _DOC_HINT.get() if has_docs else None)
            if knowledge_on:
                effective["knowledge_source"] = {"has_documents": has_docs, "document_bound": bound}
                event("knowledge_source_policy", has_documents=has_docs, document_bound=bound)

            async def by_source(task_id, domain, question, evidence, run_docs, *, stream=False, search=None):
                """Chọn nguồn cho một việc: tài liệu (run_docs như cũ), kiến thức chung, hoặc cả hai.
                Câu gắn với tài liệu không bao giờ chuyển sang kiến thức chung."""
                if not knowledge_on:
                    return await run_docs(None, evidence)
                source = choose_source(question, len(evidence), bound=bound, evidence=evidence)
                try:
                    role = profile(domain)["name"]
                except Exception:
                    role = "General Assistant"

                async def general(had_docs):
                    return await answer_general(provider, question, metrics, task_id=task_id, domain=domain, role=role,
                                                reply_language=answer_language, had_documents=had_docs,
                                                max_output_tokens=cfg.synthesis_max_output_tokens,
                                                user_request=query, stream=stream)

                if source == GENERAL:
                    result = await general(has_docs)
                    if has_docs and result.status == "COMPLETE":
                        result.status = "PARTIAL"
                else:
                    hint = BOTH_HINT if source == BOTH else None
                    result = await run_docs(hint, evidence)
                    if search is not None and result.status != "COMPLETE" and agent_tools_enabled():
                        # công cụ của tác tử (23/11): thiếu thông tin thì tự tìm thêm tài liệu theo điều còn thiếu, làm lại một lần
                        extra = await search(tool_query(question, result.missing_information))
                        event("agent_tool", task_id=task_id, domain=domain, tool="search", added=len(extra))
                        if extra:
                            evidence = [*evidence, *extra]
                            again = await run_docs(hint, evidence)
                            event("agent_tool_result", task_id=task_id, domain=domain, tool="search", before=result.status, after=again.status)
                            if status_rank(again.status) > status_rank(result.status):
                                result = again
                    if result.status == "NO_EVIDENCE" and not stream:
                        # việc con có đoạn tài liệu mà tác tử vẫn báo không có (đo 23/11, K29: mục tiêu việc viết tiếng Anh,
                        # tác tử bỏ sót bảng số): hỏi lại một lần trên chính các đoạn đó bằng câu hỏi gốc, rồi mới xét kiến thức chung
                        retry = await answer_vanilla(provider, f"{query}\n\n(Phần cần trả lời: {question})", evidence, metrics,
                                                     reply_language=answer_language, product=True,
                                                     max_output_tokens=simple_output_limit,
                                                     num_ctx=product_num_ctx,
                                                     request_timeout=product_timeout)
                        event("knowledge_source_retry", task_id=task_id, status=retry.status)
                        if retry.status != "NO_EVIDENCE":
                            retry.task_id, retry.domain = task_id, domain
                            result = retry
                    if result.status == "NO_EVIDENCE" and not bound:
                        result = await general(True)  # tài liệu có nhưng không nói tới: trả lời phổ thông, giữ trạng thái PARTIAL (không gán COMPLETE)
                        if result.status == "COMPLETE":
                            result.status = "PARTIAL"
                    elif source == BOTH and "Kiến thức chung:" in result.answer:
                        result.source = BOTH
                event("knowledge_source", task_id=task_id, domain=domain, source=result.source, evidence_chunks=len(evidence))
                return result

            if condition == "A" or simple_product_request:
                r0 = time.perf_counter()
                retrieval_trace: dict = {}
                candidates = await self._retrieve_async(
                    product_mode,
                    simple_retrieval_query,
                    all_chunks,
                    top_k=cfg.task_top_k,
                    min_score=cfg.retrieval_min_score,
                    source_ids=source_ids,
                    fallback_trace=retrieval_trace,
                    hybrid=product_mode,
                )
                metrics.retrieval_latency_ms += int((time.perf_counter() - r0) * 1000)
                metrics.retrieved_chunks += len(candidates)
                if product_mode:
                    try:
                        product_ctx_cap = max(cfg.max_context_tokens, int(os.getenv("PRODUCT_MAX_CONTEXT_TOKENS", "4000") or 4000))
                    except ValueError:
                        product_ctx_cap = max(cfg.max_context_tokens, 4000)
                else:
                    product_ctx_cap = cfg.max_context_tokens
                selected, budget_dropped = apply_token_budget(candidates, product_ctx_cap, query=query if product_mode else None)
                metrics.selected_chunks += len(selected)
                metrics.dropped_chunks += len(budget_dropped)
                metrics.context_chars += sum(len(c.text) for c in selected)
                metrics.context_tokens_est += sum(estimate_tokens(c.text) for c in selected)
                event(
                    "vanilla_retrieval",
                    retrieval_backend=self.retrieval_backend,
                    retrieval_fallback=retrieval_trace or None,
                    candidates=[c.chunk_id for c in candidates],
                    selected=[c.chunk_id for c in selected],
                    dropped=budget_dropped,
                    query_variants=[{"label": v.label, "language": v.language} for v in build_query_variants(simple_retrieval_query)],
                )
                # 23/11 (chủ dự án duyệt): ô chat sản phẩm, câu đơn giản do đúng chuyên gia ngành đã chọn trả lời (vẫn một lần gọi
                # mô hình); không có đúng một chuyên gia ngành thì Chuyên viên tổng hợp trả lời như cũ. Điều kiện A/thực nghiệm không đổi.
                answerer = simple_answerer(agent_selection) if product_mode and condition != "A" else "general"
                task = Task(task_id="T1", goal=query, domain=answerer)
                tasks = [task]
                if answerer != "general":
                    event("task_started", task_id="T1", domain=answerer)
                g0 = time.perf_counter()
                answer_query = (
                    "\n\n".join((query, f"(Câu hỏi tiếp nối. Câu hỏi trước của người dùng: {follow_up})"))
                    if follow_up else query
                )
                role = profile(answerer) if answerer != "general" else None
                result = await by_source(
                    "T1", answerer, answer_query, selected,
                    lambda hint, ev: answer_vanilla(provider, answer_query, ev, metrics, reply_language=answer_language, product=product_mode,
                                                max_output_tokens=simple_output_limit if product_mode else None, extra_hint=hint,
                                                role=role,
                                                num_ctx=product_num_ctx if product_mode else None,
                                                request_timeout=product_timeout if product_mode else None),
                    stream=True)
                result.domain = answerer
                task_results = [result]
                # 23/11: Reviewer soát cả câu đơn giản (đo: mô hình bịa "PostgreSQL", "mở cửa 3 giờ chiều" khi tài liệu không có);
                # ý không thấy trong tài liệu thì người trả lời làm lại một lần với góp ý. Chỉ phần trả lời từ tài liệu.
                if product_mode and condition != "A" and reviewer_enabled() and result.source == "documents" \
                        and result.status != "NO_EVIDENCE" and selected and result.answer.strip():
                    event("review_started", task_id="T1")
                    r0 = time.perf_counter()
                    review = await review_answer(provider, result.answer, "\n".join(c.text for c in selected), metrics)
                    if guarded.exceeded_reason is not None:
                        raise RunBudgetExceeded(guarded.exceeded_reason)
                    event("review_finished", task_id="T1", review_status=review["status"], checked=review["checked"],
                          unsupported=review["unsupported"], error=review.get("error"), latency_ms=int((time.perf_counter() - r0) * 1000))
                    if review["status"] == "ok" and review["unsupported"] and reviewer_revise_enabled():
                        event("review_revision", task_id="T1", unsupported=len(review["unsupported"]))
                        redo = await answer_vanilla(provider, answer_query, selected, metrics, reply_language=answer_language, product=True,
                                                    max_output_tokens=simple_output_limit, role=role,
                                                    extra_hint=revision_note(review["unsupported"]),
                                                    num_ctx=product_num_ctx,
                                                    request_timeout=product_timeout)
                        if redo.answer.strip():
                            redo.task_id, redo.domain = "T1", answerer
                            result = redo
                            task_results = [result]
                if answerer != "general":
                    event("task_completed", result=asdict(result))
                metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                answer = result.answer
            else:
                planning_request = (
                    "\n\n".join((f"CURRENT USER REQUEST:\n{query}",
                                 f"PREVIOUS USER REQUEST (reference only; not source evidence):\n{follow_up}"))
                    if follow_up else _planning_request_with_conversation_context(query, conversation_context)
                )
                if understanding is None:
                    understanding = understand_request(query)
                    event("request_understanding", **understanding.to_dict())
                extraction_started = time.perf_counter()
                try:
                    extraction = await extract_obligations_and_concerns(
                        provider, query, metrics
                    )
                except RunBudgetExceeded:
                    raise
                except Exception as exc:
                    metrics.generation_latency_ms += int(
                        (time.perf_counter() - extraction_started) * 1000
                    )
                    event(
                        "obligation_concern_extraction",
                        status="FAILED",
                        error_type=type(exc).__name__,
                        error=_safe_warning(exc),
                    )
                    raise ValueError(
                        "Obligation and concern extraction failed: "
                        f"{type(exc).__name__}"
                    ) from exc
                metrics.generation_latency_ms += int(
                    (time.perf_counter() - extraction_started) * 1000
                )
                event(
                    "obligation_concern_extraction",
                    status="COMPLETE",
                    obligations=[asdict(item) for item in extraction.obligations],
                    concerns=[asdict(item) for item in extraction.concerns],
                )

                planning_context = ""
                planning_hits = []
                fallback_reason = "planning_retrieval_disabled_by_condition"
                if flags["P"]:
                    retrieval_started = time.perf_counter()
                    planning_hits = (await asyncio.to_thread(self.planning.search, query, top_k=cfg.planning_top_k,
                                                             min_score=cfg.retrieval_min_score)
                                     if product_mode else
                                     self.planning.search(query, top_k=cfg.planning_top_k, min_score=cfg.retrieval_min_score))
                    metrics.retrieval_latency_ms += int(
                        (time.perf_counter() - retrieval_started) * 1000
                    )
                    planning_context = "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in planning_hits)
                    fallback_reason = (
                        None
                        if planning_hits
                        else "no_planning_evidence_selected; continuing without retrieved planning context"
                    )
                event(
                    "planning_retrieval",
                    enabled=flags["P"],
                    scorer_version=PLANNING_SCORER_VERSION,
                    min_score=cfg.retrieval_min_score,
                    selected=[c.chunk_id for c in planning_hits],
                    selected_evidence=[
                        {"evidence_id": c.chunk_id, "score": c.score}
                        for c in planning_hits
                    ],
                    fallback_reason=fallback_reason,
                )

                g0 = time.perf_counter()
                planning_result = await decompose_plan(
                    provider,
                    planning_request,
                    planning_context,
                    metrics,
                    extraction=extraction,
                    max_repairs=1,
                    max_output_tokens=cfg.task_plan_max_output_tokens,
                )
                metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                if guarded.exceeded_reason is not None:
                    raise RunBudgetExceeded(guarded.exceeded_reason)
                plan = planning_result.plan
                event(
                    "planning_generation",
                    semantic_preservation_version=PLANNER_SEMANTICS_VERSION,
                    status=planning_result.status,
                    task_ids=[] if plan is None else [task.task_id for task in plan.tasks],
                    repair_attempted=planning_result.repair_attempted,
                    warnings=list(planning_result.warnings),
                )
                if planning_result.repair_attempted:
                    event(
                        "planning_repair",
                        phase="parse",
                        attempt=1,
                        accepted=plan is not None,
                        errors=list(planning_result.warnings),
                    )
                if plan is None:
                    failure_details = planning_result.warnings or [
                        "TaskPlan generation did not produce a plan"
                    ]
                    event(
                        "plan_verification",
                        phase="initial",
                        valid=False,
                        skipped=True,
                        errors=failure_details,
                        repair_attempted=planning_result.repair_attempted,
                    )
                    event("planning_rejected", reason="task_plan_generation_failed")
                    raise ValueError("TaskPlan generation failed")

                verification = verify_task_plan(plan)
                repair_decision = decide_repair(
                    verification,
                    repair_attempted=planning_result.repair_attempted,
                )
                event(
                    "plan_verification",
                    phase="initial",
                    valid=verification.valid,
                    action=repair_decision.action,
                    errors=list(verification.errors),
                    covered_obligations=list(verification.covered_obligations),
                    missing_required_obligations=list(
                        verification.missing_required_obligations
                    ),
                    covered_concerns=list(verification.covered_concerns),
                    missing_concerns=list(verification.missing_concerns),
                    misrouted_concerns=list(verification.misrouted_concerns),
                    task_coverage=verification.task_coverage,
                    repair_attempted=planning_result.repair_attempted,
                )

                if repair_decision.action == "REPAIR":
                    repair_prompt = build_semantic_task_plan_repair_prompt(
                        plan,
                        verification.errors,
                        missing_concern_ids=tuple(dict.fromkeys(
                            (*verification.missing_concerns, *verification.misrouted_concerns)
                        )),
                        missing_obligation_ids=verification.missing_required_obligations,
                    )
                    repaired_plan = None
                    repaired_verification = None
                    repair_error_type = None
                    repair_error_message = None
                    repair_started = time.perf_counter()
                    try:
                        repaired_output = await generate_task_plan(
                            provider,
                            user=repair_prompt,
                            extraction=extraction,
                            max_output_tokens=cfg.task_plan_max_output_tokens,
                        )
                        metrics.add_usage(repaired_output.usage)
                        repaired_plan = parse_task_plan_output(
                            repaired_output.text,
                            plan.request,
                            extraction,
                        )
                        repaired_plan = canonicalize_task_plan(repaired_plan)
                        repaired_verification = validate_repaired_plan(
                            plan, repaired_plan
                        )
                    except RunBudgetExceeded:
                        raise
                    except Exception as exc:
                        repair_error_type = type(exc).__name__
                        repair_error_message = str(exc)
                    finally:
                        metrics.generation_latency_ms += int(
                            (time.perf_counter() - repair_started) * 1000
                        )

                    repair_accepted = bool(
                        repaired_verification is not None
                        and repaired_verification.valid
                    )
                    event(
                        "planning_repair",
                        phase="semantic_verification",
                        attempt=1,
                        accepted=repair_accepted,
                        errors=(
                            []
                            if repaired_verification is None
                            else list(repaired_verification.errors)
                        ),
                        error_type=repair_error_type,
                    )
                    event(
                        "plan_verification",
                        phase="post_repair",
                        valid=repair_accepted,
                        task_coverage={} if repaired_verification is None else repaired_verification.task_coverage,
                        errors=(
                            [repair_error_message]
                            if repaired_verification is None
                            and repair_error_message
                            else []
                            if repaired_verification is None
                            else list(repaired_verification.errors)
                        ),
                    )
                    if not repair_accepted:
                        # Bước sửa tất định: chép nguyên văn nghĩa vụ vào nhiệm vụ rồi kiểm tra lại bằng đúng bộ kiểm tra cũ.
                        anchored, anchored_verification, anchor_changes = anchor_and_verify(repaired_plan or plan)
                        event("plan_anchoring", source=("repaired" if repaired_plan else "initial"), accepted=anchored_verification.valid,
                              changes=anchor_changes, errors=list(anchored_verification.errors), task_coverage=anchored_verification.task_coverage,
                              tasks=[asdict(t) for t in anchored.tasks])
                        if not anchored_verification.valid:
                            event(
                                "planning_rejected",
                                reason="task_plan_failed_verification_after_repair",
                            )
                            raise ValueError(
                                "TaskPlan failed verification after one bounded repair"
                            )
                        repaired_plan, repaired_verification = anchored, anchored_verification
                    plan = repaired_plan
                    verification = repaired_verification
                elif repair_decision.action == "REJECT":
                    anchored, anchored_verification, anchor_changes = anchor_and_verify(plan)
                    event("plan_anchoring", source="initial", accepted=anchored_verification.valid,
                          changes=anchor_changes, errors=list(anchored_verification.errors), task_coverage=anchored_verification.task_coverage)
                    if not anchored_verification.valid:
                        event(
                            "planning_rejected",
                            reason="task_plan_verification_failed",
                            errors=list(verification.errors),
                        )
                        raise ValueError("TaskPlan verification failed")
                    plan, verification = anchored, anchored_verification

                tasks = list(plan.tasks)
                event("decomposition", tasks=[asdict(t) for t in tasks])
                if flags["N"]:
                    tasks, removed = normalize_tasks(tasks)
                    metrics.duplicate_tasks_removed += removed
                    event("normalization", removed=removed, tasks=[asdict(t) for t in tasks])
                    normalized_plan = TaskPlan(
                        request=plan.request,
                        obligations=list(plan.obligations),
                        concerns=list(plan.concerns),
                        tasks=tasks,
                    )
                    verification = verify_task_plan(normalized_plan)
                    event(
                        "plan_verification",
                        phase="post_normalization",
                        valid=verification.valid,
                        errors=list(verification.errors),
                        covered_obligations=list(verification.covered_obligations),
                        missing_required_obligations=list(
                            verification.missing_required_obligations
                        ),
                        covered_concerns=list(verification.covered_concerns),
                        missing_concerns=list(verification.missing_concerns),
                        misrouted_concerns=list(verification.misrouted_concerns),
                    )
                    if not verification.valid:
                        event(
                            "planning_rejected",
                            reason="normalization_invalidated_task_plan",
                            errors=list(verification.errors),
                        )
                        raise ValueError(
                            "Task normalization invalidated the verified TaskPlan"
                        )
                validate_tasks(tasks)
                ordered = topological_order(tasks)
                event(
                    "validated_plan_handoff",
                    request=plan.request,
                    obligations=[asdict(item) for item in plan.obligations],
                    concerns=[asdict(item) for item in plan.concerns],
                    verification_valid=verification.valid,
                    task_coverage=verification.task_coverage,
                    tasks=[asdict(task) for task in tasks],
                    execution_order=[task.task_id for task in ordered],
                )
                task_results = []
                completed: dict[str, TaskResult] = {}
                product_evidence: list[str] = []  # đoạn đã đưa cho tác tử: để hậu kiểm con số ở bước tổng hợp (chỉ sản phẩm)
                product_evidence_chunks: list[SourceChunk] = []
                per_task_budget = max(256, cfg.max_context_tokens // max(1, len(tasks)))
                controller = ContextController(max_chars=per_task_budget * 3)
                budget_plan = None
                if flags["O"] and policy == "adaptive_qwen":
                    # Nhu cầu ước từ lượt truy xuất sơ bộ (chưa có ngữ cảnh phụ thuộc); trần áp vào lượt truy xuất thật bên dưới.
                    preview = {}
                    for task in ordered:
                        preview[task.task_id] = await self._retrieve_async(
                            product_mode,
                            _task_query(task, query),
                            all_chunks,
                            top_k=cfg.task_top_k,
                            min_score=cfg.retrieval_min_score,
                            source_ids=source_ids,
                            fallback_trace={},
                            hybrid=product_mode,
                        )
                    budget_plan = plan_task_budgets(preview, cfg.max_context_tokens)
                    event("adaptive_budget_plan", **budget_plan)
                else:
                    preview = {}

                async def run_one(task):
                    """Một việc con: tìm đoạn tài liệu, chọn theo ngân sách, giao tác tử. Không ghi vào kết quả chung."""
                    event("task_started", task_id=task.task_id, domain=task.domain)  # Đợt 4 văn phòng 3D: mốc bắt đầu từng việc
                    dependency_context = " ".join(completed[d].answer for d in task.depends_on if d in completed)
                    task_q = _task_query(task, query)
                    retrieval_query = f"{task_q} {dependency_context}".strip()
                    r0 = time.perf_counter()
                    retrieval_trace: dict = {}
                    # MA-03: tái sử dụng ứng viên đã truy xuất ở bước ước lượng adaptive_qwen khi truy vấn không đổi.
                    if preview and not dependency_context and task.task_id in preview:
                        candidates = list(preview[task.task_id])
                        retrieval_trace["reused_preview"] = True
                    else:
                        candidates = await self._retrieve_async(
                            product_mode,
                            retrieval_query,
                            all_chunks,
                            top_k=cfg.task_top_k,
                            min_score=cfg.retrieval_min_score,
                            source_ids=source_ids,
                            fallback_trace=retrieval_trace,
                            hybrid=product_mode,
                        )
                    metrics.retrieval_latency_ms += int((time.perf_counter() - r0) * 1000)
                    metrics.retrieved_chunks += len(candidates)
                    if budget_plan is not None:
                        selected, dropped = TokenContextController(budget_plan["limits"][task.task_id]).select(
                            candidates, query=retrieval_query if product_mode else None
                        )
                    elif flags["O"]:
                        selected, dropped = controller.select(candidates, query=retrieval_query if product_mode else None)
                    else:
                        selected, dropped = candidates, []
                    if budget_plan is None:
                        selected, hard_dropped = apply_token_budget(selected, per_task_budget, query=retrieval_query if product_mode else None)
                        dropped = [*dropped, *hard_dropped]
                    metrics.selected_chunks += len(selected)
                    metrics.dropped_chunks += len(dropped)
                    metrics.context_chars += sum(len(c.text) for c in selected)
                    metrics.context_tokens_est += sum(estimate_tokens(c.text) for c in selected)
                    event(
                        "task_retrieval",
                        task_id=task.task_id,
                        domain=task.domain,
                        retrieval_backend=self.retrieval_backend,
                        retrieval_fallback=retrieval_trace or None,
                        candidates=[c.chunk_id for c in candidates],
                        selected=[c.chunk_id for c in selected],
                        dropped=dropped,
                    )
                    g0 = time.perf_counter()
                    upstream = [completed[d] for d in task.depends_on if d in completed]
                    found_more: list[SourceChunk] = []

                    async def search_more(tool_q: str) -> list[SourceChunk]:
                        seen = {c.chunk_id for c in selected} | {c.chunk_id for c in found_more}
                        r1 = time.perf_counter()
                        more = await self._retrieve_async(product_mode, tool_q, all_chunks, top_k=cfg.task_top_k, min_score=cfg.retrieval_min_score,
                                                         source_ids=source_ids, fallback_trace={}, hybrid=product_mode)
                        metrics.retrieval_latency_ms += int((time.perf_counter() - r1) * 1000)
                        new = [c for c in more if c.chunk_id not in seen][:TOOL_SEARCH_CHUNKS]
                        found_more.extend(new)
                        return new

                    async def run_worker_attempt(hint, ev) -> TaskResult:
                        max_attempts = 1 + max(0, cfg.retry_limit)
                        last_exc: Exception | None = None
                        for attempt in range(max_attempts):
                            if attempt > 0:
                                reason = budget_exceeded_reason()
                                if reason is not None:
                                    raise RuntimeError(f"retry stopped by {reason}")
                            try:
                                remaining = max(0.01, dag_deadline - time.monotonic())
                                return await asyncio.wait_for(
                                    execute_task(
                                        provider,
                                        task,
                                        ev,
                                        metrics,
                                        reply_language=answer_language,
                                        upstream=upstream,
                                        product=product_mode,
                                        user_request=query if product_mode else None,
                                        extra_hint=hint,
                                        num_ctx=product_num_ctx if product_mode else None,
                                        request_timeout=product_timeout if product_mode else None,
                                    ),
                                    timeout=remaining,
                                )
                            except RunBudgetExceeded:
                                raise
                            except (TimeoutError, httpx.TimeoutException) as exc:
                                if isinstance(exc, TimeoutError) and time.monotonic() >= dag_deadline:
                                    raise
                                last_exc = exc
                                # In product mode, never double a long HTTP read timeout; preserve bounded retry in research mode.
                                if (product_mode and isinstance(exc, httpx.TimeoutException)) or attempt + 1 >= max_attempts or budget_exceeded_reason() is not None:
                                    break
                            except (httpx.HTTPError, OSError, ValueError) as exc:
                                last_exc = exc
                                if attempt + 1 >= max_attempts or budget_exceeded_reason() is not None:
                                    break
                        return TaskResult(
                            task_id=task.task_id,
                            domain=task.domain,
                            status="FAILED",
                            answer="",
                            evidence_ids=[c.chunk_id for c in ev],
                            citations=[],
                            missing_information=[f"task execution error: {type(last_exc).__name__}" if last_exc else "task execution failed"],
                        )

                    try:
                        result = await by_source(
                            task.task_id,
                            task.domain,
                            task.goal,
                            selected,
                            run_worker_attempt,
                            search=search_more if product_mode else None,
                        )
                    except (asyncio.TimeoutError, RunBudgetExceeded):
                        raise
                    except Exception as exc:
                        result = TaskResult(
                            task_id=task.task_id,
                            domain=task.domain,
                            status="FAILED",
                            answer="",
                            evidence_ids=[c.chunk_id for c in selected],
                            citations=[],
                            missing_information=[f"task execution error: {type(exc).__name__}"],
                        )
                    metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                    return result, [*selected, *found_more]

                def record(task, result, selected) -> bool:
                    """Ghi kết quả theo thứ tự kế hoạch; trả True khi vượt ngân sách token/lượt gọi/thời gian."""
                    product_evidence.extend(c.text for c in selected)
                    product_evidence_chunks.extend(selected)
                    completed[task.task_id] = result
                    task_results.append(result)
                    event("task_completed", result=asdict(result))
                    reason = budget_exceeded_reason()
                    if reason is not None:
                        emit_budget_stopped(reason)
                        return True
                    return False

                parallel = task_parallel_limit() if product_mode else 1
                if parallel <= 1:
                    for task in ordered:
                        if reason := budget_exceeded_reason():
                            emit_budget_stopped(reason)
                            break
                        try:
                            task_res, task_sel = await run_one(task)
                        except RunBudgetExceeded as exc:
                            emit_budget_stopped(exc.reason)
                            break
                        except asyncio.TimeoutError:
                            emit_budget_stopped("wall_timeout")
                            break
                        if record(task, task_res, task_sel):
                            break
                else:
                    # Đợt 7: các việc không phụ thuộc nhau chạy cùng lúc, tối đa `parallel` việc; việc phụ thuộc chờ đợt trước.
                    waves = dependency_waves(ordered)
                    effective["task_parallel"] = parallel
                    event("parallel_execution", limit=parallel, waves=[[t.task_id for t in w] for w in waves])
                    gate = asyncio.Semaphore(parallel)

                    async def gated(task):
                        async with gate:
                            return await run_one(task)

                    for wave in waves:
                        if reason := budget_exceeded_reason():
                            emit_budget_stopped(reason)
                            break
                        outcomes = await asyncio.gather(*(gated(t) for t in wave), return_exceptions=True)
                        wave_stop_reason: str | None = None
                        unexpected_exc: BaseException | None = None
                        stop_after_wave = False
                        for t, outcome in zip(wave, outcomes):
                            if isinstance(outcome, BaseException):
                                if isinstance(outcome, RunBudgetExceeded):
                                    wave_stop_reason = wave_stop_reason or outcome.reason
                                elif isinstance(outcome, asyncio.TimeoutError):
                                    wave_stop_reason = wave_stop_reason or "wall_timeout"
                                elif unexpected_exc is None:
                                    unexpected_exc = outcome
                                continue
                            if record(t, *outcome):
                                stop_after_wave = True
                        if unexpected_exc is not None and wave_stop_reason is None:
                            raise unexpected_exc
                        if wave_stop_reason is not None:
                            emit_budget_stopped(wave_stop_reason)
                            break
                        if stop_after_wave:
                            break
                stop_synth_reason = budget_exceeded_reason()
                synth_meta: dict = {}
                if stop_synth_reason in {"max_llm_calls", "wall_timeout"} or not task_results:
                    if stop_synth_reason is not None:
                        emit_budget_stopped(stop_synth_reason)
                    parts = [r.answer.strip() for r in task_results if r.answer and r.answer.strip()]
                    answer = "\n\n".join(parts) if parts else "Lượt chạy dừng do vượt giới hạn an toàn trước khi tổng hợp."
                elif product_mode and task_results and all(r.status == "NO_EVIDENCE" for r in task_results):
                    # Toàn bộ tác tử không tìm thấy bằng chứng: trả lời NO_EVIDENCE trực tiếp, không gọi Synthesizer tránh bịa chi tiết/citation.
                    parts = [r.answer.strip() for r in task_results if r.answer and r.answer.strip()]
                    answer = parts[0] if parts else "Không tìm thấy bằng chứng phù hợp trong tài liệu đã nạp để trả lời yêu cầu này."
                    emit_validated_answer(answer)
                else:
                    event("synthesis_started", task_count=len(task_results))
                    g0 = time.perf_counter()
                    # Ô chat sản phẩm: nới giới hạn để câu trả lời nhiều ý không bị cắt; thực nghiệm giữ nguyên.
                    synth_limit = cfg.synthesis_max_output_tokens if product_mode else None
                    remaining = max(0.01, dag_deadline - time.monotonic())
                    answer = await asyncio.wait_for(
                        synthesize(provider, query, task_results, metrics, reply_language=answer_language, max_output_tokens=synth_limit,
                                   evidence_text="\n".join(product_evidence) if product_mode else None,
                                   evidence_chunks=product_evidence_chunks if product_mode else None,
                                   num_ctx=product_num_ctx if product_mode else None,
                                   request_timeout=product_timeout if product_mode else None,
                                   synth_meta=synth_meta if product_mode else None),
                        timeout=remaining,
                    )
                    metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                if knowledge_on and task_results and all(r.source == GENERAL for r in task_results) \
                        and not any(m in answer for m in ("iến thức chung", "eneral knowledge")):
                    answer = f"{knowledge_label(answer_language, has_docs)}\n\n{answer}"  # bước tổng hợp bỏ nhãn: mã gắn lại
                # Reviewer đối chiếu từng ý với đoạn tài liệu đã dùng; phần kiến thức chung không có trong tài liệu nên không soát
                if not budget_stopped and product_mode and reviewer_enabled() and all(r.source == "documents" for r in task_results):
                    event("review_started")
                    g0 = time.perf_counter()
                    review = await review_answer(provider, answer, "\n".join(product_evidence), metrics)
                    if guarded.exceeded_reason is not None:
                        raise RunBudgetExceeded(guarded.exceeded_reason)
                    review_ms = int((time.perf_counter() - g0) * 1000)
                    metrics.generation_latency_ms += review_ms
                    event("review_finished", review_status=review["status"], checked=review["checked"],
                          unsupported=review["unsupported"], error=review.get("error"), latency_ms=review_ms)
                    if review["status"] == "ok" and review["unsupported"] and reviewer_revise_enabled():
                        # 23/11: Reviewer trả bài, Integrator viết lại một lần chỉ dựa trên kết quả các tác tử
                        event("review_revision", unsupported=len(review["unsupported"]))
                        event("synthesis_started", task_count=len(task_results), revision=True)
                        g0 = time.perf_counter()
                        rev_meta: dict = {}
                        revised = await synthesize(provider, query, task_results, metrics, reply_language=answer_language,
                                                   max_output_tokens=synth_limit, evidence_text="\n".join(product_evidence),
                                                   evidence_chunks=product_evidence_chunks,
                                                   revision_note=revision_note(review["unsupported"]),
                                                   num_ctx=product_num_ctx if product_mode else None,
                                                   request_timeout=product_timeout if product_mode else None,
                                                   synth_meta=rev_meta if product_mode else None)
                        metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                        if revised.strip():
                            answer = revised
                            synth_meta = rev_meta
                    else:
                        if review.get("status") == "ok" and review.get("unsupported"):
                            synth_meta["reviewer_unsupported"] = True
                        answer = annotate(answer, review, answer_language)

            if budget_stopped or (tasks and len(task_results) < len(tasks)) or any(r.status == "FAILED" for r in task_results):
                status = "PARTIAL" if any(r.status in ("COMPLETE", "PARTIAL", "NO_EVIDENCE") for r in task_results) else "FAILED"
            elif task_results and all(r.status == "NO_EVIDENCE" for r in task_results):
                status = "NO_EVIDENCE"
            elif task_results and all(r.status == "COMPLETE" for r in task_results):
                status = "PARTIAL" if (product_mode and any(synth_meta.get(k) for k in ("truncated", "context_trimmed", "unsupported_numbers", "unsupported_articles", "invalid_inline_citations", "reviewer_unsupported", "post_synth_validation_partial"))) else "COMPLETE"
            else:
                status = "PARTIAL"
            lifecycle_status = "COMPLETED"
            event(
                "run_finished",
                status=status,
                lifecycle_status=lifecycle_status,
            )
            if product_mode:
                # đo đạc tài nguyên (nvidia-smi, tiến trình) và ghi lượt chạy vào CSDL là việc đồng bộ: chạy ở luồng phụ để sự kiện
                # run_finished tới trình duyệt ngay (đo 23/11: muộn 0,6–3,6 s và câu trả lời cuối tới chậm theo)
                return await asyncio.to_thread(finalize, status, answer, tasks, task_results)
            return finalize(status, answer, tasks, task_results)
        except RunBudgetExceeded as exc:
            emit_budget_stopped(exc.reason)
            parts = [r.answer.strip() for r in task_results if r.answer and r.answer.strip()]
            answer = "\n\n".join(parts) if parts else "Lượt chạy dừng do vượt giới hạn an toàn trước khi tổng hợp."
            status = "PARTIAL" if any(r.status in ("COMPLETE", "PARTIAL", "NO_EVIDENCE") for r in task_results) else "FAILED"
            lifecycle_status = "COMPLETED"
            event(
                "run_finished",
                status=status,
                lifecycle_status=lifecycle_status,
            )
            if product_mode:
                return await asyncio.to_thread(finalize, status, answer, tasks, task_results)
            return finalize(status, answer, tasks, task_results)
        except Exception as exc:
            error_category, http_status = classify_run_error(exc)
            lifecycle_status = "FAILED"
            failed_payload = {
                "lifecycle_status": lifecycle_status,
                "error_category": error_category,
                "error_type": type(exc).__name__,
                "error": type(exc).__name__,
            }
            if http_status is not None:
                failed_payload["http_status"] = http_status
            event("run_failed", **failed_payload)
            return finalize("FAILED", f"Pipeline failed: {type(exc).__name__}", tasks, task_results)

    @staticmethod
    def _flags(condition: str) -> dict[str, bool]:
        if condition in {"A", "B"}:
            return {"P": False, "N": False, "O": False}
        if condition == "C":
            return {"P": True, "N": True, "O": True}
        return {"P": condition != "C-P", "N": condition != "C-N", "O": condition != "C-O"}


class RunBudgetExceeded(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _GuardedProvider:
    """Enforces pre-flight LLM call count and wall-clock deadline across all pipeline phases."""

    def __init__(self, inner: Any, *, max_calls: int, deadline: float) -> None:
        self._inner = inner
        self.max_calls = max_calls
        self.deadline = deadline
        self.attempted_calls = 0
        self.exceeded_reason: str | None = None
        self.name = getattr(inner, "name", "unknown")
        self.model = getattr(inner, "model", "unknown")
        if callable(getattr(inner, "generate_structured", None)):
            self.generate_structured = self._generate_structured
        if callable(getattr(inner, "generate_grounded", None)):
            self.generate_grounded = self._generate_grounded

    def _reserve(self) -> float:
        if self.attempted_calls >= self.max_calls:
            self.exceeded_reason = "max_llm_calls"
            raise RunBudgetExceeded("max_llm_calls")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.exceeded_reason = "wall_timeout"
            raise RunBudgetExceeded("wall_timeout")
        self.attempted_calls += 1
        return remaining

    async def _call(self, fn, **kwargs):
        remaining = self._reserve()
        try:
            return await asyncio.wait_for(fn(**kwargs), timeout=remaining)
        except TimeoutError as exc:
            if time.monotonic() + 0.02 >= self.deadline:
                self.exceeded_reason = "wall_timeout"
                raise RunBudgetExceeded("wall_timeout") from exc
            raise

    async def generate(self, **kwargs):
        return await self._call(self._inner.generate, **kwargs)

    async def _generate_structured(self, **kwargs):
        return await self._call(self._inner.generate_structured, **kwargs)

    async def _generate_grounded(self, **kwargs):
        return await self._call(self._inner.generate_grounded, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)


# tài liệu được nêu tên trong câu hỏi của người dùng (một lượt chạy): việc con không nhắc lại tên vẫn ưu tiên tài liệu đó
_DOC_HINT: ContextVar[list[str] | None] = ContextVar("doc_hint", default=None)


# tác tử chung, không phải chuyên gia ngành: Tổng hợp, Số liệu (bộ office), Số liệu (bộ work)
_NOT_FIELD_EXPERTS = frozenset({"general", "analyst", "figures"})


def simple_answerer(selection: dict | None) -> str:
    """Người trả lời câu đơn giản: đúng một chuyên gia ngành được chọn (không mơ hồ) thì là người đó, còn lại là general."""
    if not selection or selection.get("ambiguous"):
        return "general"
    experts = [a for a in selection.get("agents") or [] if a not in _NOT_FIELD_EXPERTS]
    return experts[0] if len(experts) == 1 else "general"


def task_parallel_limit() -> int:
    """Số việc con chạy cùng lúc ở ô chat sản phẩm (PRODUCT_TASK_PARALLEL, mặc định 1 = lần lượt như cũ, tối đa 4)."""
    try:
        return max(1, min(4, int(os.getenv("PRODUCT_TASK_PARALLEL", "1"))))
    except ValueError:
        return 1


def dependency_waves(tasks: list) -> list[list]:
    """Chia việc đã sắp theo thứ tự phụ thuộc thành từng đợt: mỗi việc chỉ chờ các việc nó phụ thuộc ở đợt trước."""
    ids = {t.task_id for t in tasks}
    done: set[str] = set()
    remaining = list(tasks)
    waves: list[list] = []
    while remaining:
        wave = [t for t in remaining if all(d in done or d not in ids for d in t.depends_on)] or [remaining[0]]
        waves.append(wave)
        done.update(t.task_id for t in wave)
        remaining = [t for t in remaining if t not in wave]
    return waves


def _task_query(task, query: str) -> str:
    """Truy vấn tìm bằng chứng của một nhiệm vụ.

    Ngành ngoài Phần mềm: mô hình nhỏ đôi khi viết nhiệm vụ bằng ngôn ngữ khác câu hỏi (dù prompt đã dặn),
    khi đó ghép câu hỏi gốc để vẫn khớp tài liệu. Bộ Phần mềm giữ nguyên truy vấn cũ.
    """
    text = f"{task.goal} {' '.join(task.evidence_needs)}".strip()
    if active_pack()["plan_rules"] and reply_language_of(text) != reply_language_of(query):
        return f"{text} {query}"
    return text


def _retrieval_query_with_conversation_context(
    query: str, conversation_context: ConversationContext
) -> str:
    """Keep a new question primary; resolve references from the last user turn."""

    if not conversation_context.last_user_request or not re.search(
        r"\b(it|its|they|their|them|follow-up)\b|"
        r"\b(this|that|those|same|previous|earlier)\s+(one|approach|design|system|topic|question|request)\b|"
        r"\b(nó|đó|trước)\b",
        query, re.IGNORECASE,
    ):
        return query
    return f"{query}\n{conversation_context.last_user_request}"


def _planning_request_with_conversation_context(
    query: str, conversation_context: ConversationContext
) -> str:
    """Use bounded history only for query disambiguation, never as evidence."""

    # "Identify requirements and determine their domains" resolves within the
    # current request. It is not a reference to an earlier chat question.
    reference_probe = re.sub(
        r"\b(?:obligations?|concerns?|requirements?|tasks?)\b[^.!?\n]{0,160}\btheir\b",
        lambda match: re.sub(r"\btheir\b", "these", match.group(0), flags=re.IGNORECASE),
        query, flags=re.IGNORECASE,
    )
    if re.search(r"\b(?:previous|earlier|prior|above|last|those|these|same)\b", query, re.IGNORECASE):
        reference_probe = query
    if (
        not conversation_context.text
        or _retrieval_query_with_conversation_context(reference_probe, conversation_context) == reference_probe
    ):
        return query
    return (
        "CURRENT USER REQUEST:\n"
        f"{query}\n\n"
        "RECENT CONVERSATION CONTEXT (reference only; not source evidence):\n"
        f"{conversation_context.text}"
    )
