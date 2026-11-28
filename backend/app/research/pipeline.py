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
from app.core.config import RuntimeConfig, resolve_ollama_keep_alive
from app.core.graph import topological_order, validate_tasks
from app.core.telemetry import cpu_busy_percent, cpu_times, model_rss_mb, process_rss_mb, gpu_memory_mb
from app.core.types import SourceChunk, Task, TaskPlan, TaskResult, RunMetrics
from app.providers.factory import get_provider
from app.providers.ollama import generation_stage
from app.research.context_controller import ContextController
from app.research.provenance import build_provenance
from app.research.token_budget import resolve_product_num_ctx
from app.research.token_context import TokenContextController, context_policy, plan_task_budgets
from app.research.conversation_context import ConversationContext, resolve_follow_up
from app.research.plan_anchoring import anchor_and_verify
from app.research.decomposer import (
    canonicalize_task_plan,
    detect_domains,
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
from app.research.registry import OFFICE_PACK, SELECTION_PACKS, active_domains, active_pack, active_pack_name, profile, use_pack, use_work_context
from app.research.worker import execute_task
from app.research.progress import emit, emit_validated_answer
from app.research.structured_evidence_hook import (
    advanced_reasoning_enabled,
    build_grounding_snapshot,
    structured_evidence_enabled,
)
from app.research.verified_reasoning import verify_and_reconcile_answer
from app.research.synthesizer import synthesize
from app.research.vanilla import answer_vanilla
from app.retrieval.candidate_index import embed_with_run_cache, scoped_embed_cache
from app.retrieval.evidence_completeness import complete_missing_evidence
from app.retrieval.text import retrieve, apply_token_budget, estimate_tokens, terms
from app.retrieval.source_focus import focus_sources, has_same_family_for_years
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


class RunBudgetExceeded(RuntimeError):
    """Vượt trần số lượt gọi LLM hoặc thời gian chạy tối đa trong một lượt chạy (AI-GUARD-01)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


LLMBudgetExceededError = RunBudgetExceeded


class _GuardedProvider:
    """Bọc provider thống nhất: giới hạn số lần gọi LLM và thời hạn thực thi toàn phiên across all pipeline phases."""

    def __init__(
        self,
        inner: Any,
        max_calls: int = 24,
        *,
        deadline: float | None = None,
        metrics: RunMetrics | None = None,
    ) -> None:
        self._inner = inner
        self.max_calls = max(1, int(max_calls))
        self.deadline = deadline
        self.metrics = metrics
        self.attempted_calls = 0
        self.exceeded_reason: str | None = None
        self.name = getattr(inner, "name", "unknown")
        self.model = getattr(inner, "model", "unknown")
        if callable(getattr(inner, "generate_structured", None)):
            self.generate_structured = self._generate_structured
        if callable(getattr(inner, "generate_grounded", None)):
            self.generate_grounded = self._generate_grounded

    @property
    def calls(self) -> int:
        return self.attempted_calls

    def _reserve(self) -> float | None:
        if self.attempted_calls >= self.max_calls:
            self.exceeded_reason = "max_llm_calls"
            raise RunBudgetExceeded("max_llm_calls")
        remaining: float | None = None
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self.exceeded_reason = "wall_timeout"
                raise RunBudgetExceeded("wall_timeout")
        self.attempted_calls += 1
        return remaining

    async def _call(self, fn, *args, **kwargs):
        from app.providers.ollama import _GENERATION_STAGE

        remaining = self._reserve()
        t0 = time.perf_counter()
        try:
            coro = fn(*args, **kwargs)
            res = await (asyncio.wait_for(coro, timeout=remaining) if remaining is not None else coro)
            if self.metrics is not None and hasattr(self.metrics, "add_provider_call"):
                wall_ms = (time.perf_counter() - t0) * 1000.0
                self.metrics.add_provider_call(
                    _GENERATION_STAGE.get(),
                    wall_ms,
                    getattr(res, "metrics", None),
                )
            return res
        except TimeoutError as exc:
            if self.deadline is not None and time.monotonic() + 0.02 >= self.deadline:
                self.exceeded_reason = "wall_timeout"
                raise RunBudgetExceeded("wall_timeout") from exc
            raise

    async def generate(self, *args, **kwargs):
        return await self._call(self._inner.generate, *args, **kwargs)

    async def _generate_structured(self, *args, **kwargs):
        return await self._call(self._inner.generate_structured, *args, **kwargs)

    async def _generate_grounded(self, *args, **kwargs):
        return await self._call(self._inner.generate_grounded, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


_BudgetedProvider = _GuardedProvider


def _max_llm_calls_per_run() -> int:
    raw = os.getenv("MAX_RUN_LLM_CALLS", "").strip() or os.getenv("MAX_LLM_CALLS_PER_RUN", "24")
    try:
        return max(1, int(raw or 24))
    except ValueError:
        return 24


def _run_wall_timeout_s() -> float:
    raw = os.getenv("MAX_DAG_WALL_SECONDS", "").strip() or os.getenv("RUN_WALL_TIMEOUT_S", "300")
    try:
        val = float(raw or 300.0)
        return val if val > 0 else 300.0
    except ValueError:
        return 300.0


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
    """Distinguish request timeout vs proxy budget 429 vs provider rate limit vs HTTP/connection errors cleanly."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, (TimeoutError, httpx.TimeoutException)):
            return "request_timeout", None
        if isinstance(cur, httpx.ConnectError):
            return "provider_connection_error", None
        if isinstance(cur, httpx.HTTPStatusError):
            resp = getattr(cur, "response", None)
            code = getattr(resp, "status_code", None)
            if code == 429:
                body_text = ""
                try:
                    body_text = getattr(resp, "text", "") or ""
                except Exception:
                    try:
                        raw = getattr(resp, "content", b"") or b""
                        body_text = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    except Exception:
                        body_text = str(cur)
                proxy_markers = (
                    "HARD_BUDGET_EXCEEDED",
                    "BLOCKED_GEN_USED",
                    "BLOCKED_QUERY_EMBED_USED",
                    "BLOCKED_INGEST_EMBED_USED",
                    "BUDGET_NOT_APPROVED",
                    "RUN_SESSION_MISMATCH",
                )
                if any(m in body_text for m in proxy_markers):
                    return "proxy_budget_exceeded", 429
                return "provider_rate_limit", 429
            return "provider_http_error", int(code) if code is not None else None
        if isinstance(cur, RuntimeError) and "ollama stream" in str(cur).lower():
            return "provider_stream_error", None
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return "pipeline_error", None


def _doc_names_of(chunks: list[SourceChunk], limit: int = 4) -> list[str]:
    """Tên tệp tài liệu duy nhất (chỉ tên file sạch, không chứa nội dung đoạn) để hiển thị trong Văn phòng 3D."""
    names: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        name = str(c.source_name or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
            if len(names) >= limit:
                break
    return names


def _product_fallback_plan(query: str, extraction, candidate: TaskPlan | None) -> TaskPlan:
    """Kế hoạch dự phòng an toàn CHỈ cho chế độ sản phẩm khi bộ kiểm tra hình thức vẫn từ chối sau sửa & neo.
    Giữ lại các nhiệm vụ có nghĩa từ planner hoặc tách tối đa 4 nhiệm vụ theo obligations để câu hỏi khó không bị crash."""
    allowed = list(active_domains())
    default_dom = active_pack()["default_domain"]
    tasks: list[Task] = []
    if candidate is not None and candidate.tasks:
        valid_ids = {t.task_id for t in candidate.tasks if t.task_id}
        seen_ids: set[str] = set()
        for idx, t in enumerate(candidate.tasks[:6], 1):
            tid = t.task_id if (t.task_id and t.task_id not in seen_ids) else f"T{idx}"
            seen_ids.add(tid)
            dom = t.domain if t.domain in allowed else default_dom
            deps = [d for d in (t.depends_on or []) if d in valid_ids and d != tid and d in seen_ids]
            goal = str(t.goal or "").strip() or query[:200]
            needs = [str(n).strip() for n in (t.evidence_needs or []) if str(n).strip()] or [goal[:120]]
            tasks.append(Task(task_id=tid, goal=goal, domain=dom, depends_on=deps, evidence_needs=needs))
    elif extraction is not None and getattr(extraction, "obligations", None):
        for idx, ob in enumerate(extraction.obligations[:4], 1):
            desc = str(ob.description or "").strip() or query[:200]
            doms = detect_domains(desc)
            dom = doms[0] if doms and doms[0] in allowed else default_dom
            tasks.append(Task(task_id=f"T{idx}", goal=desc, domain=dom, depends_on=[], evidence_needs=[desc[:120]]))
    if not tasks:
        tasks = [Task(task_id="T1", goal=query, domain=default_dom, depends_on=[], evidence_needs=[query[:120]])]
    return TaskPlan(
        request=query,
        obligations=list(getattr(extraction, "obligations", ()) or ()),
        concerns=list(getattr(extraction, "concerns", ()) or ()),
        tasks=tasks,
    )


def _partial_failure_answer(task_results: list[TaskResult], *, timed_out: bool = False, budget_exceeded: bool = False) -> str:
    """Thông báo thân thiện khi lượt chạy lỗi giữa chừng (OBS-W3-P82-01): không rò exception thô, giữ phần đã xong."""
    reason = (
        "quá thời gian xử lý cho phép"
        if timed_out
        else ("đạt giới hạn số lượt gọi mô hình cho phép" if budget_exceeded else "gặp sự cố tạm thời khi xử lý tác vụ tiếp theo")
    )
    completed_parts = [
        str(r.answer).strip()
        for r in task_results
        if str(r.answer or "").strip() and r.status != "FAILED"
    ]
    if completed_parts:
        joined = "\n\n".join(completed_parts)
        return (
            f"{joined}\n\n"
            f"> **Lưu ý:** Phiên xử lý {reason}; các kết quả đã hoàn tất ở trên vẫn được giữ lại để bạn tham khảo."
        )
    return f"Hệ thống chưa thể hoàn tất câu trả lời do {reason}. Vui lòng thử lại hoặc chia nhỏ câu hỏi."


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
        variants = build_query_variants(query)
        if hybrid and active_pack_name() == OFFICE_PACK:
            # Đợt 8 + sửa 25/11: câu nêu tên tài liệu ("theo nội quy", "quy chế 2026") ưu tiên tìm trong tài liệu đó trước.
            # Tránh "làm mù" tài liệu thứ hai khi hỏi chéo (vd. chính sách + bảng Excel, SRS + Kiến trúc): giữ tối đa nửa
            # ngân sách top_k (hoặc toàn bộ đoạn khớp mạnh) từ tài liệu được nêu, đồng thời bổ sung chỗ trống từ các tài liệu
            # khác cùng phạm vi (vẫn loại văn bản mang năm khác nếu câu hỏi chỉ rõ năm).
            focused = focus_sources(query, chunks, source_ids)
            if focused:
                focused_set = set(focused)
                first = self._retrieve_hybrid(
                    query, variants, [c for c in chunks if c.source_id in focused_set],
                    top_k=top_k, min_score=min_score, source_ids=focused, trace=fallback_trace,
                )
                q_years = {m.group(0) for m in re.finditer(r"\b(19|20)\d{2}\b", query)}
                other_chunks = [c for c in chunks if c.source_id not in focused_set]
                if q_years and other_chunks:
                    # V9: chỉ loại bản cũ CÙNG HỌ (vd. Quy chế 2024 khi đã có Quy chế 2026), KHÔNG loại báo cáo năm trước khác chủ đề (vd. Excel Q4/2025 chứa Sheet ngân sách 2026)
                    all_titles = {c.source_id: c.source_name for c in chunks}
                    other_chunks = [
                        c for c in other_chunks
                        if not (
                            ({m.group(0) for m in re.finditer(r"\b(19|20)\d{2}\b", re.sub(r"[_\-.]", " ", c.source_name))} - q_years)
                            and has_same_family_for_years(c.source_name, all_titles, q_years, exclude_sid=c.source_id)
                        )
                    ]
                other_ids = list(dict.fromkeys(c.source_id for c in other_chunks))
                rest = (
                    self._retrieve_hybrid(
                        query, variants, other_chunks,
                        top_k=max(2, top_k - min(len(first), max(1, top_k - 2))),
                        min_score=min_score, source_ids=other_ids, trace=None,
                    )
                    if other_chunks else []
                )
                seen = {c.chunk_id for c in first}
                keep_first = max(1, top_k - min(2, len(rest))) if rest else top_k
                merged = first[:keep_first] + [c for c in rest if c.chunk_id not in seen]
                if fallback_trace is not None:
                    fallback_trace["source_focus"] = focused
                return continue_articles(merged[:top_k], chunks)
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
        return parts[:3] if len(parts) >= 2 else []

    def _retrieve_hybrid(self, query, variants, chunks, *, top_k, min_score, source_ids, trace):
        scope_set = None if source_ids is None else set(source_ids)
        scope_chunks = [c for c in chunks if scope_set is None or c.source_id in scope_set]
        vector_ranked: list[str] = []
        last_stats: dict[str, Any] = {}
        if self.candidate_index is not None:
            best: dict[str, float] = {}
            for variant in variants:
                for match in self.candidate_index.candidates(variant.text, limit=top_k * HYBRID_POOL, source_ids=source_ids):
                    cid = str(match.payload.get("chunk_id") or "")
                    if match.score >= min_score and match.score > best.get(cid, -1.0):
                        best[cid] = match.score
                if hasattr(self.candidate_index, "last_search_stats") and self.candidate_index.last_search_stats:
                    last_stats = dict(self.candidate_index.last_search_stats)
            vector_ranked = sorted(best, key=lambda cid: (-best[cid], cid))
        fused, info = hybrid_fuse(query, scope_chunks, vector_ranked, top_k)
        if isinstance(trace, dict):
            trace["vector_candidates"] = len(vector_ranked)
            trace["retrieval_mode"] = "hybrid_vector_plus_bm25" if vector_ranked else "bm25_fallback"
            trace["embedding_version"] = (
                getattr(getattr(self.candidate_index, "embedder", None), "version", "lexical")
                if self.candidate_index is not None
                else "lexical"
            )
            if last_stats:
                trace["vector_version_alias_matched"] = int(last_stats.get("alias_matched", 0))
                trace["vector_version_mismatch_skipped"] = int(last_stats.get("skipped_mismatch", 0))

        # Workstream A: kiểm tra từng vế độc lập + bao phủ nhiều nguồn được chọn bằng BM25 thuần Python
        subqueries = self._split_subqueries(query)
        distinct_scope_sids = list(dict.fromkeys(c.source_id for c in scope_chunks))
        if scope_chunks and (subqueries or len(distinct_scope_sids) >= 2):
            fused_ids = {c.chunk_id for c in fused}
            by_cid = {c.chunk_id: c for c in scope_chunks}
            rrf_ceiling = (fused[-1].score or (1.0 / 61.0)) * 0.98 if fused else (1.0 / 61.0)

            def _scaled_rescue_score(raw_bm25: float, existing: float | None) -> float:
                scaled = rrf_ceiling * (raw_bm25 / (raw_bm25 + 2.0)) if raw_bm25 > 0 else 0.0
                return round(max(float(existing or 0.0), scaled), 6)

            rescue: list[SourceChunk] = []
            subq_anchor_ids: set[str] = set()
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

    async def _run_with_timeout(self, query: str, condition: str, provider_name: str | None, **kwargs) -> dict:
        run_wall_timeout = _run_wall_timeout_s()
        run_state: dict = {
            "tasks": [],
            "task_results": [],
            "finalize": None,
            "verify_gate": None,
            "event": None,
            "provenance": None,
        }
        try:
            return await asyncio.wait_for(
                self._run(query, condition, provider_name, run_state=run_state, **kwargs),
                timeout=run_wall_timeout + 0.5,
            )
        except asyncio.TimeoutError:
            fin = run_state.get("finalize")
            gate = run_state.get("verify_gate")
            ev = run_state.get("event")
            prov = run_state.get("provenance")
            if isinstance(prov, dict):
                prov["error_type"] = "TimeoutError"
            if callable(ev):
                ev("run_failed", lifecycle_status="FAILED", error_type="TimeoutError", error="run_wall_timeout")
            if callable(fin):
                kept_tasks: list[Task] = list(run_state["tasks"])
                kept_results: list[TaskResult] = list(run_state["task_results"])
                partial_answer = _partial_failure_answer(kept_results, timed_out=True)
                status = "PARTIAL" if kept_results else "FAILED"
                if callable(gate):
                    partial_answer, status = gate(status, partial_answer, kept_results)
                return fin(status, partial_answer, kept_tasks, kept_results)
            raise
        except asyncio.CancelledError:
            fin = run_state.get("finalize")
            gate = run_state.get("verify_gate")
            ev = run_state.get("event")
            prov = run_state.get("provenance")
            if isinstance(prov, dict):
                prov["error_type"] = "CancelledError"
            if callable(ev):
                ev("run_failed", lifecycle_status="FAILED", error_type="CancelledError", error="run_cancelled")
            if callable(fin):
                kept_tasks: list[Task] = list(run_state["tasks"])
                kept_results: list[TaskResult] = list(run_state["task_results"])
                safe_answer = _partial_failure_answer(kept_results, timed_out=False, budget_exceeded=False) if kept_results else "Phiên xử lý đã bị hủy trước khi hoàn tất."
                if callable(gate):
                    safe_answer, _ = gate("FAILED", safe_answer, kept_results, emit_stream_if_needed=False)
                fin("FAILED", safe_answer, kept_tasks, kept_results)
            raise

    async def run(self, query: str, condition: str = "A", provider_name: str | None = None, *,
                  domain_pack: str | None = None, **kwargs) -> dict:
        """Chạy một lượt: product_mode=True mặc định office (11 Agent); Research B/C mặc định software khi domain_pack bỏ trống."""
        is_product = bool(kwargs.get("product_mode", False))
        cond_u = str(condition or "A").strip().upper()
        effective_pack_arg = domain_pack if domain_pack is not None else (None if (is_product or cond_u == "A") else "software")
        with use_pack(effective_pack_arg), scoped_embed_cache():
            examples = kwargs.pop("routing_examples", None)
            pack = active_pack_name()
            if pack not in SELECTION_PACKS or not is_product:
                kwargs.pop("forced_agent", None)
                return await self._run_with_timeout(query, condition, provider_name, **kwargs)
            doc_types = self._doc_types(kwargs.get("source_ids"))
            embedder = getattr(self.candidate_index, "embedder", None)
            embed_fn = None
            if embedder is not None and callable(getattr(embedder, "embed", None)):
                class _ScopedEmbedProxy:
                    def __init__(self, target):
                        self.__self__ = target

                    def __call__(self, text: str):
                        return embed_with_run_cache(self.__self__, text)

                embed_fn = _ScopedEmbedProxy(embedder)
            forced = kwargs.pop("forced_agent", None)
            if forced and forced not in PACK_DESCRIPTIONS[pack]:
                forced = None
            try:
                selection = (forced_selection(forced, pack) if forced
                             else await asyncio.to_thread(select_agents, query, embed_fn, examples, pack))
            except ValueError:
                raise
            except Exception as exc:
                selection = {**select_agents(query, None, pack=pack), "embed_error": type(exc).__name__}
            selection["doc_types"] = sorted(doc_types)
            hint_token = None
            if pack == OFFICE_PACK:
                try:
                    sids = kwargs.get("source_ids")
                    hint_token = _DOC_HINT.set(focus_sources(query, self.source_store.chunks(sids) if sids else self.source_store.chunks(
                        [x["source_id"] for x in self.source_store.list_sources()]), sids, allow_multi_part=True))
                except Exception:
                    hint_token = None
            try:
                with use_work_context(doc_types, selection["agents"]):
                    return await self._run_with_timeout(query, condition, provider_name, agent_selection=selection, **kwargs)
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
        run_state: dict | None = None,
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
        max_llm_calls = _max_llm_calls_per_run()
        run_wall_timeout = _run_wall_timeout_s()
        dag_deadline = time.monotonic() + run_wall_timeout
        started = time.perf_counter()
        metrics = RunMetrics(peak_rss_mb=process_rss_mb(), gpu_memory_mb=gpu_memory_mb())
        guarded = _GuardedProvider(get_provider(provider_name), max_calls=max_llm_calls, deadline=dag_deadline, metrics=metrics)
        provider = guarded
        product_num_ctx = resolve_product_num_ctx() if product_mode else None
        product_timeout = resolve_product_llm_timeout_seconds(guarded._inner) if product_mode else None
        product_keep_alive = resolve_ollama_keep_alive(product=True, embed=False) if product_mode else None
        simple_output_limit = resolve_product_simple_max_output_tokens(cfg.synthesis_max_output_tokens)
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
        if product_mode:
            effective["synthesis_max_output_tokens"] = cfg.synthesis_max_output_tokens
            effective["product_num_ctx"] = product_num_ctx
            effective["product_keep_alive"] = product_keep_alive
        embedder = getattr(self.candidate_index, "embedder", None)
        provenance = build_provenance(
            provider_name=provider.name,
            model=provider.model,
            embedding_version=getattr(embedder, "version", None) if embedder else "lexical",
            context_policy=policy,
        )

        def event(stage: str, **data):
            events.append({"stage": stage, "ts": datetime.now(timezone.utc).isoformat(), **data})
            brief = {k: data[k] for k in ("task_id", "domain", "classification", "agents", "has_documents", "document_bound",
                                          "source", "review_status", "waves", "limit",
                                          "tool", "added", "before", "after", "revision",
                                          "doc_names", "task_goal") if k in data}
            if isinstance(data.get("unsupported"), list):
                brief["unsupported"] = len(data["unsupported"])
            elif isinstance(data.get("unsupported"), int):
                brief["unsupported"] = data["unsupported"]
            if isinstance(data.get("selected"), list):
                brief["selected_count"] = len(data["selected"])
            if isinstance(data.get("tasks"), list):
                brief["task_count"] = len(data["tasks"])
            elif isinstance(data.get("task_count"), int):
                brief["task_count"] = data["task_count"]
            if isinstance(data.get("candidates"), list):
                brief["candidate_count"] = len(data["candidates"])
            if isinstance(data.get("dropped"), list):
                brief["dropped_count"] = len(data["dropped"])
            for k in ("removed", "checked", "total_tokens"):
                if isinstance(data.get(k), int) and not isinstance(data.get(k), bool):
                    brief[k] = data[k]
            if isinstance(data.get("limits"), dict):
                brief["budget_tasks"] = len(data["limits"])
            if isinstance(data.get("result"), dict) and data["result"].get("task_id"):
                brief["task_id"] = data["result"]["task_id"]
                brief["result"] = {k: data["result"][k] for k in ("task_id", "domain", "status") if data["result"].get(k)}
                if data["result"].get("domain"):
                    brief["domain"] = data["result"]["domain"]
            if stage == "run_finished" and isinstance(data.get("status"), str):
                brief["status"] = data["status"]
            emit({"type": "progress", "stage": stage, **brief})

        def make_run(status: str | None, answer: str, tasks: list[Task], task_results: list[TaskResult]) -> dict:
            if product_mode and status not in {"NO_EVIDENCE", "FAILED", None} and answer:
                auth_cids = {c.chunk_id for c in grounded_chunks_snapshot}
                if auth_cids:
                    answer = re.sub(
                        r"\s*\[(src_[0-9a-f]+_c\d{4}|[A-Za-z0-9_]+_c\d{4})\]",
                        lambda m: m.group(0) if m.group(1) in auth_cids else "",
                        answer,
                    )
            top_citations = list(dict.fromkeys(
                cid for r in task_results
                if (not product_mode or r.status not in {"NO_EVIDENCE", "FAILED"})
                for cid in (r.citations or []) if cid
            ))
            if product_mode and status not in {"NO_EVIDENCE", "FAILED", None} and answer:
                auth_cids = {c.chunk_id for c in grounded_chunks_snapshot}
                for inline_cid in re.findall(r"\[(src_[0-9a-f]+_c\d{4}|[A-Za-z0-9_]+_c\d{4})\]", answer):
                    if inline_cid in auth_cids and inline_cid not in top_citations:
                        top_citations.append(inline_cid)
            if status in {"NO_EVIDENCE", "FAILED"}:
                top_citations = []
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
            if product_mode and status != "FAILED" and not str(answer or "").strip():
                answer = (
                    "Không thể trả lời yêu cầu này hoặc chưa tìm thấy thông tin phù hợp trong tài liệu hiện có. "
                    "Vui lòng diễn đạt lại câu hỏi cụ thể hơn về tài liệu cần tra cứu."
                )
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
        effective["max_llm_calls"] = max_llm_calls
        effective["run_wall_timeout_s"] = run_wall_timeout
        tasks: list[Task] = run_state["tasks"] if run_state is not None else []
        task_results: list[TaskResult] = run_state["task_results"] if run_state is not None else []
        synth_meta: dict = {}
        budget_stopped = False
        budget_event_emitted = False
        stream_emitted = False
        grounded_chunks_snapshot: list[SourceChunk] = []
        run_token_cap = max(20000, cfg.max_run_tokens) if product_mode else cfg.max_run_tokens

        def budget_exceeded_reason() -> str | None:
            if guarded.exceeded_reason is not None:
                return guarded.exceeded_reason
            if metrics.input_tokens + metrics.output_tokens > run_token_cap:
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

        def apply_verified_output_gate(
            gate_status: str,
            raw_answer: str,
            kept_results: list[TaskResult] | None = None,
            *,
            emit_stream_if_needed: bool = True,
            already_verified: bool = False,
        ) -> tuple[str, str]:
            """Single verified output gate applied across ALL completion & failure exit paths."""
            nonlocal stream_emitted
            chunks_for_gate = list(grounded_chunks_snapshot)
            if not chunks_for_gate and kept_results:
                wanted_cids = {
                    cid
                    for r in kept_results
                    for cid in (*(r.citations or ()), *(r.evidence_ids or ()))
                    if cid
                }
                if wanted_cids:
                    all_avail = self.source_store.chunks(source_ids)
                    chunks_for_gate = [c for c in all_avail if c.chunk_id in wanted_cids]

            verified_answer = raw_answer
            verified_status = gate_status
            if product_mode and structured_evidence_enabled():
                event(
                    "structured_evidence_grounding",
                    **build_grounding_snapshot(
                        query,
                        chunks_for_gate,
                        answer=verified_answer,
                        allowed_source_ids=set(source_ids) if source_ids else None,
                    ),
                )
            if product_mode and advanced_reasoning_enabled():
                vr_snap = verify_and_reconcile_answer(
                    query=query,
                    chunks=chunks_for_gate,
                    llm_answer=verified_answer,
                    status=gate_status,
                    allowed_source_ids=set(source_ids) if source_ids else None,
                )
                if not (already_verified and gate_status != "FAILED"):
                    if vr_snap.get("applied") and isinstance(vr_snap.get("final_answer"), str):
                        verified_answer = vr_snap["final_answer"]
                    # Never promote FAILED to PARTIAL/COMPLETE via verified reasoning
                    if gate_status != "FAILED" and isinstance(vr_snap.get("status"), str) and vr_snap["status"] in {"PARTIAL", "COMPLETE"}:
                        if vr_snap["status"] == "COMPLETE" and gate_status == "COMPLETE":
                            verified_status = "COMPLETE"
                        elif vr_snap["status"] == "PARTIAL" and gate_status == "COMPLETE":
                            verified_status = "PARTIAL"
                event(
                    "verified_reasoning",
                    applied=bool(vr_snap.get("applied")),
                    mode=vr_snap.get("mode"),
                    contradicted_llm=bool(vr_snap.get("contradicted_llm")),
                    calc_status=vr_snap.get("calc_status"),
                    ignored_identifier_count=len(vr_snap.get("ignored_identifier_numbers") or []),
                )
            if product_mode and emit_stream_if_needed and not stream_emitted and verified_answer.strip():
                emit_validated_answer(verified_answer)
                stream_emitted = True
            return verified_answer, verified_status

        inner_verified = False
        if run_state is not None:
            run_state["finalize"] = finalize
            run_state["verify_gate"] = apply_verified_output_gate
            run_state["event"] = event
            run_state["provenance"] = provenance
        try:
            product_help = product_help_response(query) if product_mode else None
            if product_mode and product_help is None and is_library_question(query):
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
                if product_mode:
                    emit_validated_answer(answer)
                event("run_finished", status="COMPLETE", lifecycle_status="COMPLETED")
                return finalize("COMPLETE", answer, [task], [result])

            understanding = understand_request(query) if product_mode else None
            follow_up = resolve_follow_up(query, conversation_context) if product_mode else None
            if follow_up:
                event("follow_up_resolved", previous_request=follow_up, is_rag_evidence=False)
            simple_retrieval_query = (
                "\n".join((query, follow_up)) if follow_up
                else (query if product_mode else _retrieval_query_with_conversation_context(query, conversation_context))
            )
            _route_domains = [
                d for d in (understanding.domains if understanding is not None else ())
                if d != "general" and not (active_pack_name() == OFFICE_PACK and d == "analyst")
            ]
            simple_product_request = bool(
                product_mode
                and condition != "A"
                and understanding is not None
                and is_simple_project_question(query, _route_domains)
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
            knowledge_on = bool(product_mode and condition != "A")
            has_docs = bool(all_chunks)
            corpus_names = list(dict.fromkeys(c.source_name for c in all_chunks)) if has_docs else None
            bound = knowledge_on and doc_bound(query, _DOC_HINT.get() if has_docs else None, corpus_names=corpus_names)
            if knowledge_on:
                effective["knowledge_source"] = {"has_documents": has_docs, "document_bound": bound}
                event("knowledge_source_policy", has_documents=has_docs, document_bound=bound)

            async def by_source(task_id, domain, question, evidence, run_docs, *, stream=False, search=None):
                if not knowledge_on:
                    return await run_docs(None, evidence)
                task_bound = bool(
                    bound or doc_bound(question, _DOC_HINT.get() if has_docs else None, corpus_names=corpus_names)
                )
                source = choose_source(question, len(evidence), bound=task_bound, evidence=evidence)
                try:
                    role = profile(domain)["name"]
                except Exception:
                    role = "General Assistant"

                in_org = bool(getattr(self.source_store, "space_id", None))

                async def general(had_docs):
                    with generation_stage("general_knowledge"):
                        return await answer_general(provider, question, metrics, task_id=task_id, domain=domain, role=role,
                                                    reply_language=answer_language, had_documents=had_docs,
                                                    max_output_tokens=cfg.synthesis_max_output_tokens,
                                                    user_request=query, stream=stream, in_org=in_org,
                                                    num_ctx=product_num_ctx if product_mode else None,
                                                    request_timeout=product_timeout if product_mode else None,
                                                    keep_alive=product_keep_alive if product_mode else None)

                if source == GENERAL:
                    result = await general(has_docs)
                    if has_docs and result.status == "COMPLETE":
                        result.status = "PARTIAL"
                else:
                    hint = BOTH_HINT if source == BOTH else None
                    result = await run_docs(hint, evidence)
                    if search is not None and result.status != "COMPLETE" and agent_tools_enabled():
                        extra = await search(tool_query(question, result.missing_information))
                        event("agent_tool", task_id=task_id, domain=domain, tool="search", added=len(extra))
                        if extra:
                            evidence = [*evidence, *extra]
                            again = await run_docs(hint, evidence)
                            event("agent_tool_result", task_id=task_id, domain=domain, tool="search", before=result.status, after=again.status)
                            if status_rank(again.status) > status_rank(result.status):
                                result = again
                    if result.status == "NO_EVIDENCE" and not stream:
                        with generation_stage("knowledge_source_retry"):
                            retry = await answer_vanilla(provider, f"{query}\n\n(Phần cần trả lời: {question})", evidence, metrics,
                                                         reply_language=answer_language, product=True,
                                                         max_output_tokens=simple_output_limit,
                                                         num_ctx=product_num_ctx,
                                                         request_timeout=product_timeout,
                                                         keep_alive=product_keep_alive,
                                                         emit_stream=False)
                        event("knowledge_source_retry", task_id=task_id, status=retry.status)
                        if retry.status != "NO_EVIDENCE":
                            retry.task_id, retry.domain = task_id, domain
                            result = retry
                    if result.status == "NO_EVIDENCE" and not task_bound:
                        result = await general(True)
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
                bm25_prio = set(retrieval_trace.get("from_bm25_only") or ()) or None
                if product_mode:
                    try:
                        product_ctx_cap = max(cfg.max_context_tokens, int(os.getenv("PRODUCT_MAX_CONTEXT_TOKENS", "4000") or 4000))
                    except ValueError:
                        product_ctx_cap = max(cfg.max_context_tokens, 4000)
                else:
                    product_ctx_cap = cfg.max_context_tokens
                selected, budget_dropped = apply_token_budget(
                    candidates, product_ctx_cap, query=query if product_mode else None, priority_ids=bm25_prio
                )
                if product_mode and advanced_reasoning_enabled() and all_chunks:
                    selected, comp_trace = complete_missing_evidence(
                        query=query,
                        selected=selected,
                        all_chunks=all_chunks,
                        allowed_source_ids=set(source_ids) if source_ids else None,
                        max_tokens=product_ctx_cap,
                    )
                    if comp_trace["added_count"] > 0:
                        event("evidence_completeness", **comp_trace)
                grounded_chunks_snapshot = list(selected)
                metrics.selected_chunks += len(selected)
                metrics.dropped_chunks += len(budget_dropped)
                metrics.context_chars += sum(len(c.text) for c in selected)
                metrics.context_tokens_est += sum(estimate_tokens(c.text) for c in selected)
                answerer = simple_answerer(agent_selection) if product_mode and condition != "A" else "general"
                event(
                    "vanilla_retrieval",
                    domain=answerer,
                    retrieval_backend=self.retrieval_backend,
                    retrieval_fallback=retrieval_trace or None,
                    candidates=[c.chunk_id for c in candidates],
                    selected=[c.chunk_id for c in selected],
                    doc_names=_doc_names_of(selected),
                    dropped=budget_dropped,
                    query_variants=[{"label": v.label, "language": v.language} for v in build_query_variants(simple_retrieval_query)],
                )
                task = Task(task_id="T1", goal=query, domain=answerer)
                tasks[:] = [task]
                if answerer != "general":
                    event("task_started", task_id="T1", domain=answerer, task_goal=query[:120])
                g0 = time.perf_counter()
                answer_query = (
                    "\n\n".join((query, f"(Câu hỏi tiếp nối. Câu hỏi trước của người dùng: {follow_up})"))
                    if follow_up else query
                )
                role = profile(answerer) if answerer != "general" else None
                will_review = bool(product_mode and condition != "A" and reviewer_enabled())

                async def _run_vanilla(hint, ev):
                    with generation_stage("vanilla_rag"):
                        return await answer_vanilla(
                            provider, answer_query, ev, metrics,
                            reply_language=answer_language, product=product_mode,
                            max_output_tokens=simple_output_limit if product_mode else None, extra_hint=hint,
                            role=role,
                            num_ctx=product_num_ctx if product_mode else None,
                            request_timeout=product_timeout if product_mode else None,
                            keep_alive=product_keep_alive if product_mode else None,
                            emit_stream=bool(product_mode and not will_review),
                        )

                result = await by_source("T1", answerer, answer_query, selected, _run_vanilla, stream=False)
                result.domain = answerer
                task_results[:] = [result]
                if product_mode and condition != "A" and reviewer_enabled() and result.source == "documents" \
                        and result.status != "NO_EVIDENCE" and selected and result.answer.strip():
                    event("review_started", task_id="T1")
                    r0 = time.perf_counter()
                    with generation_stage("reviewer"):
                        review = await review_answer(
                            provider, result.answer, "\n".join(c.text for c in selected), metrics,
                            num_ctx=product_num_ctx,
                            request_timeout=product_timeout,
                            keep_alive=product_keep_alive,
                        )
                    if guarded.exceeded_reason is not None:
                        raise RunBudgetExceeded(guarded.exceeded_reason)
                    event("review_finished", task_id="T1", review_status=review["status"], checked=review["checked"],
                          unsupported=review["unsupported"], error=review.get("error"), latency_ms=int((time.perf_counter() - r0) * 1000))
                    if review["status"] == "ok" and review["unsupported"] and reviewer_revise_enabled():
                        event("review_revision", task_id="T1", unsupported=len(review["unsupported"]))
                        with generation_stage("vanilla_revision"):
                            redo = await answer_vanilla(provider, answer_query, selected, metrics, reply_language=answer_language, product=True,
                                                        max_output_tokens=simple_output_limit, role=role,
                                                        extra_hint=revision_note(review["unsupported"]),
                                                        num_ctx=product_num_ctx,
                                                        request_timeout=product_timeout,
                                                        keep_alive=product_keep_alive,
                                                        emit_stream=False)
                        if redo.answer.strip():
                            redo.task_id, redo.domain = "T1", answerer
                            result = redo
                            task_results[:] = [result]
                if not will_review and product_mode and result.source == "documents" and result.answer.strip():
                    stream_emitted = True
                if product_mode and condition != "A" and advanced_reasoning_enabled() and result.source == "documents" and selected and result.answer.strip():
                    inner_verified = True
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
                    with generation_stage("obligation_concern_extraction"):
                        extraction = await extract_obligations_and_concerns(
                            provider,
                            query,
                            metrics,
                            num_ctx=product_num_ctx if product_mode else None,
                            request_timeout=product_timeout if product_mode else None,
                            keep_alive=product_keep_alive if product_mode else None,
                        )
                except RunBudgetExceeded:
                    raise
                except TimeoutError as exc:
                    if time.monotonic() + 0.02 >= dag_deadline or guarded.exceeded_reason == "wall_timeout":
                        raise RunBudgetExceeded("wall_timeout") from exc
                    metrics.generation_latency_ms += int((time.perf_counter() - extraction_started) * 1000)
                    event("obligation_concern_extraction", status="FAILED", error_type=type(exc).__name__, error=_safe_warning(exc))
                    raise ValueError(f"Obligation and concern extraction failed: {type(exc).__name__}") from exc
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
                plan_output_cap = max(1200, cfg.task_plan_max_output_tokens) if product_mode else cfg.task_plan_max_output_tokens
                with generation_stage("planning_generation"):
                    planning_result = await decompose_plan(
                        provider,
                        planning_request,
                        planning_context,
                        metrics,
                        extraction=extraction,
                        max_repairs=1,
                        max_output_tokens=plan_output_cap,
                        num_ctx=product_num_ctx if product_mode else None,
                        request_timeout=product_timeout if product_mode else None,
                        keep_alive=product_keep_alive if product_mode else None,
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
                used_product_fallback = False
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
                    if product_mode:
                        plan = _product_fallback_plan(query, extraction, None)
                        verification = verify_task_plan(plan)
                        used_product_fallback = True
                        event("plan_fallback", reason="task_plan_generation_failed", task_count=len(plan.tasks))
                    else:
                        event("planning_rejected", reason="task_plan_generation_failed")
                        raise ValueError("TaskPlan generation failed")

                if not used_product_fallback:
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
                            with generation_stage("planning_repair"):
                                repaired_output = await generate_task_plan(
                                    provider,
                                    user=repair_prompt,
                                    extraction=extraction,
                                    max_output_tokens=plan_output_cap,
                                    num_ctx=product_num_ctx if product_mode else None,
                                    request_timeout=product_timeout if product_mode else None,
                                    keep_alive=product_keep_alive if product_mode else None,
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
                                if product_mode:
                                    repaired_plan = _product_fallback_plan(query, extraction, anchored)
                                    repaired_verification = anchored_verification
                                    used_product_fallback = True
                                    event("plan_fallback", reason="task_plan_failed_verification_after_repair", task_count=len(repaired_plan.tasks))
                                else:
                                    event(
                                        "planning_rejected",
                                        reason="task_plan_failed_verification_after_repair",
                                    )
                                    raise ValueError(
                                        "TaskPlan failed verification after one bounded repair"
                                    )
                            else:
                                repaired_plan, repaired_verification = anchored, anchored_verification
                        plan = repaired_plan
                        verification = repaired_verification
                    elif repair_decision.action == "REJECT":
                        anchored, anchored_verification, anchor_changes = anchor_and_verify(plan)
                        event("plan_anchoring", source="initial", accepted=anchored_verification.valid,
                              changes=anchor_changes, errors=list(anchored_verification.errors), task_coverage=anchored_verification.task_coverage)
                        if not anchored_verification.valid:
                            if product_mode:
                                plan = _product_fallback_plan(query, extraction, anchored)
                                verification = anchored_verification
                                used_product_fallback = True
                                event("plan_fallback", reason="task_plan_verification_failed", task_count=len(plan.tasks))
                            else:
                                event(
                                    "planning_rejected",
                                    reason="task_plan_verification_failed",
                                    errors=list(verification.errors),
                                )
                                raise ValueError("TaskPlan verification failed")
                        else:
                            plan, verification = anchored, anchored_verification

                tasks[:] = list(plan.tasks)
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
                    if not verification.valid and not used_product_fallback:
                        if product_mode:
                            event("plan_fallback", reason="normalization_invalidated_task_plan", task_count=len(tasks))
                        else:
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
                task_results.clear()
                completed: dict[str, TaskResult] = {}
                product_evidence: list[str] = []
                product_evidence_chunks: list[SourceChunk] = []
                product_evidence_seen: set[str] = set()
                if product_mode:
                    try:
                        s3_ctx_cap = max(cfg.max_context_tokens, int(os.getenv("PRODUCT_MAX_CONTEXT_TOKENS", "4000") or 4000))
                    except ValueError:
                        s3_ctx_cap = max(cfg.max_context_tokens, 4000)
                else:
                    s3_ctx_cap = cfg.max_context_tokens
                per_task_budget = (
                    max(1400, s3_ctx_cap // max(1, len(tasks)))
                    if product_mode
                    else max(256, s3_ctx_cap // max(1, len(tasks)))
                )
                controller = ContextController(max_chars=per_task_budget * 3)
                budget_plan = None
                preview: dict[str, list[SourceChunk]] = {}
                preview_traces: dict[str, dict] = {}
                if flags["O"] and policy == "adaptive_qwen":
                    for task in ordered:
                        pt: dict = {}
                        preview[task.task_id] = await self._retrieve_async(
                            product_mode,
                            _task_query(task, query),
                            all_chunks,
                            top_k=cfg.task_top_k,
                            min_score=cfg.retrieval_min_score,
                            source_ids=source_ids,
                            fallback_trace=pt,
                            hybrid=product_mode,
                        )
                        preview_traces[task.task_id] = pt
                    budget_plan = plan_task_budgets(preview, s3_ctx_cap)
                    event("adaptive_budget_plan", **budget_plan)

                async def run_one(task):
                    """Một việc con: tìm đoạn tài liệu, chọn theo ngân sách, giao tác tử."""
                    event("task_started", task_id=task.task_id, domain=task.domain, task_goal=str(task.goal or "")[:120])
                    dependency_context = " ".join(completed[d].answer for d in task.depends_on if d in completed)
                    retrieval_query = f"{_task_query(task, query)} {dependency_context}".strip()
                    r0 = time.perf_counter()
                    retrieval_trace: dict = {}
                    if not dependency_context and task.task_id in preview:
                        candidates = list(preview[task.task_id])
                        retrieval_trace.update(preview_traces.get(task.task_id) or {})
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
                    if product_mode and advanced_reasoning_enabled() and all_chunks:
                        task_lim = budget_plan["limits"][task.task_id] if budget_plan is not None else per_task_budget
                        rescue_cap = max(task_lim, min(s3_ctx_cap, task_lim + max(800, s3_ctx_cap // max(1, len(tasks)) - task_lim)))
                        comp_query = "\n".join(p for p in (query, task.goal, " ".join(task.evidence_needs)) if p).strip()
                        selected, comp_trace = complete_missing_evidence(
                            query=comp_query,
                            selected=selected,
                            all_chunks=all_chunks,
                            allowed_source_ids=set(source_ids) if source_ids else None,
                            max_tokens=rescue_cap,
                        )
                        if comp_trace["added_count"] > 0:
                            event("evidence_completeness", task_id=task.task_id, **comp_trace)
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
                        doc_names=_doc_names_of(selected),
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
                                with generation_stage("worker"):
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
                                            keep_alive=product_keep_alive if product_mode else None,
                                        ),
                                        timeout=remaining,
                                    )
                            except RunBudgetExceeded:
                                raise
                            except (TimeoutError, httpx.TimeoutException) as exc:
                                if isinstance(exc, TimeoutError) and time.monotonic() >= dag_deadline:
                                    raise
                                last_exc = exc
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
                            task.task_id, task.domain, task.goal, selected,
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
                    nonlocal grounded_chunks_snapshot
                    for c in selected:
                        if c.chunk_id not in product_evidence_seen:
                            product_evidence_seen.add(c.chunk_id)
                            product_evidence.append(c.text)
                            product_evidence_chunks.append(c)
                    grounded_chunks_snapshot = list(product_evidence_chunks)
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
                synth_limit = cfg.synthesis_max_output_tokens if product_mode else None
                if budget_stopped or stop_synth_reason in {"max_llm_calls", "wall_timeout"} or not task_results:
                    if stop_synth_reason is not None:
                        emit_budget_stopped(stop_synth_reason)
                    parts = [r.answer.strip() for r in task_results if r.answer and r.answer.strip()]
                    answer = "\n\n".join(parts) if parts else "Lượt chạy dừng sớm do chạm giới hạn an toàn trước khi tổng hợp."
                elif product_mode and task_results and all(r.status == "FAILED" for r in task_results):
                    # All workers failed (e.g. upstream 504/ReadError): do not spend extra synth call or emit ungrounded text
                    answer = _partial_failure_answer(task_results, timed_out=False, budget_exceeded=False)
                elif product_mode and task_results and all(r.status == "NO_EVIDENCE" for r in task_results):
                    parts = [r.answer.strip() for r in task_results if r.answer and r.answer.strip()]
                    answer = parts[0] if parts else "Không tìm thấy bằng chứng phù hợp trong tài liệu đã nạp để trả lời yêu cầu này."
                else:
                    event("synthesis_started", task_count=len(task_results))
                    g0 = time.perf_counter()
                    remaining = max(0.01, dag_deadline - time.monotonic())
                    with generation_stage("synthesizer"):
                        answer = await asyncio.wait_for(
                            synthesize(provider, query, task_results, metrics, reply_language=answer_language, max_output_tokens=synth_limit,
                                       evidence_text="\n".join(product_evidence) if product_mode else None,
                                       evidence_chunks=product_evidence_chunks if product_mode else None,
                                       num_ctx=product_num_ctx if product_mode else None,
                                       request_timeout=product_timeout if product_mode else None,
                                       keep_alive=product_keep_alive if product_mode else None,
                                       synth_meta=synth_meta if product_mode else None,
                                       emit_stream=not product_mode),
                            timeout=remaining,
                        )
                    metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                    if product_mode and advanced_reasoning_enabled() and product_evidence_chunks and synth_limit is not None:
                        inner_verified = True

                if knowledge_on and task_results and all(r.source == GENERAL for r in task_results) \
                        and not any(m in answer for m in ("iến thức chung", "eneral knowledge")):
                    answer = f"{knowledge_label(answer_language, has_docs)}\n\n{answer}"
                if not budget_stopped and product_mode and reviewer_enabled() and all(r.source == "documents" for r in task_results):
                    event("review_started")
                    g0 = time.perf_counter()
                    with generation_stage("reviewer"):
                        review = await review_answer(
                            provider, answer, "\n".join(product_evidence), metrics,
                            num_ctx=product_num_ctx,
                            request_timeout=product_timeout,
                            keep_alive=product_keep_alive,
                        )
                    if guarded.exceeded_reason is not None:
                        raise RunBudgetExceeded(guarded.exceeded_reason)
                    review_ms = int((time.perf_counter() - g0) * 1000)
                    metrics.generation_latency_ms += review_ms
                    event("review_finished", review_status=review["status"], checked=review["checked"],
                          unsupported=review["unsupported"], error=review.get("error"), latency_ms=review_ms)
                    if review["status"] == "ok" and review["unsupported"] and reviewer_revise_enabled():
                        event("review_revision", unsupported=len(review["unsupported"]))
                        event("synthesis_started", task_count=len(task_results), revision=True)
                        g0 = time.perf_counter()
                        rev_meta: dict = {}
                        with generation_stage("synthesizer_revision"):
                            revised = await synthesize(provider, query, task_results, metrics, reply_language=answer_language,
                                                       max_output_tokens=synth_limit, evidence_text="\n".join(product_evidence),
                                                       evidence_chunks=product_evidence_chunks,
                                                       revision_note=revision_note(review["unsupported"]),
                                                       num_ctx=product_num_ctx if product_mode else None,
                                                       request_timeout=product_timeout if product_mode else None,
                                                       keep_alive=product_keep_alive if product_mode else None,
                                                       synth_meta=rev_meta if product_mode else None,
                                                       emit_stream=False)
                        metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                    if product_mode and advanced_reasoning_enabled() and product_evidence_chunks and synth_limit is not None:
                        inner_verified = True
                        if revised.strip() and not (revised.rstrip().endswith(":") and len(revised.strip()) < len(answer.strip()) * 0.7):
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
            else:
                status = "COMPLETE" if task_results and all(r.status == "COMPLETE" for r in task_results) else "PARTIAL"
                _ans_plain = re.sub(r"[*_`]+", "", answer or "")
                _GAP_MARKERS = (
                    "không có thông tin",
                    "không tìm thấy thông tin",
                    "không được cung cấp",
                    "không được đề cập",
                    "không có dữ liệu",
                    "chưa có dữ liệu",
                    "tài liệu không đề cập",
                    "tài liệu hiện có không đề cập",
                    "tài liệu không nêu",
                    "tài liệu không quy định",
                    "chưa có thông tin",
                    "chưa được quy định",
                    "không đề cập đến",
                    "không đề cập tới",
                    "không có quy định về",
                    "không đủ căn cứ",
                    "không cung cấp dịch vụ",
                    "không có dịch vụ",
                    "không thấy đề cập",
                    "không có trong tài liệu",
                    "tài liệu không ghi",
                    "tài liệu không chứa",
                    "chưa thấy đề cập",
                    "không quy định cụ thể",
                    "không quy định mức",
                )
                _CROSS_DOC_RESOLVED = (
                    "nhưng điều",
                    "nhưng mục",
                    "nhưng hợp đồng",
                    "nhưng tài liệu",
                    "nhưng phụ lục",
                    "quy định rõ",
                    "được lấy từ",
                    "được nêu tại",
                    "được quy định tại",
                )
                _answer_declares_gap = any(
                    any(m in s for m in _GAP_MARKERS) and not any(c in s for c in _CROSS_DOC_RESOLVED)
                    for s in (seg.strip().casefold() for seg in re.split(r"(?<=[.!?])\s+|\n+", _ans_plain) if seg.strip())
                )
                _INTERNAL_MISSING = (
                    "invalid citation locator",
                    "no valid citation",
                    "empty answer",
                    "articles not found",
                    "numbers not found",
                    "reconciled no_evidence",
                )
                _has_real_missing = any(
                    any(
                        m.strip() and not any(tag in m.casefold() for tag in _INTERNAL_MISSING)
                        for m in (r.missing_information or ())
                    )
                    for r in task_results
                    if r.status == "PARTIAL"
                )
                _has_synth_downgrade = bool(
                    product_mode
                    and any(
                        synth_meta.get(k)
                        for k in (
                            "truncated",
                            "context_trimmed",
                            "unsupported_numbers",
                            "unsupported_articles",
                            "invalid_inline_citations",
                            "reviewer_unsupported",
                            "post_synth_validation_partial",
                        )
                    )
                )
                if _has_synth_downgrade and status == "COMPLETE":
                    status = "PARTIAL"
                elif (
                    product_mode
                    and status == "COMPLETE"
                    and _answer_declares_gap
                    and any(r.source == "documents" for r in task_results)
                    and not all(r.status == "NO_EVIDENCE" for r in task_results)
                    and (len(task_results) <= 2 or any(r.status != "COMPLETE" for r in task_results))
                ):
                    status = "PARTIAL"
                elif (
                    product_mode
                    and status == "PARTIAL"
                    and not _has_synth_downgrade
                    and len(task_results) > 1
                    and any(r.status == "COMPLETE" for r in task_results)
                    and not any(r.status in {"NO_EVIDENCE", "FAILED"} for r in task_results)
                    and not (_has_real_missing and len(task_results) <= 3)
                    and all(r.citations for r in task_results if r.source == "documents")
                    and not any(r.invalid_citations for r in task_results)
                    and "> **Cần kiểm tra lại:**" not in (answer or "")
                    and "> **Lưu ý căn cứ:**" not in (answer or "")
                    and "> **Reviewer:**" not in (answer or "")
                    and (not _answer_declares_gap or (len(task_results) >= 4 and sum(1 for r in task_results if r.status == "COMPLETE") >= len(task_results) - 1))
                ):
                    status = "COMPLETE"

            lifecycle_status = "FAILED" if status == "FAILED" else "COMPLETED"
            effective["attempted_llm_calls"] = guarded.attempted_calls
            answer, status = apply_verified_output_gate(
                status, answer, task_results, already_verified=inner_verified
            )
            lifecycle_status = "FAILED" if status == "FAILED" else "COMPLETED"
            event(
                "run_finished",
                status=status,
                lifecycle_status=lifecycle_status,
            )
            if product_mode:
                return await asyncio.to_thread(finalize, status, answer, tasks, task_results)
            return finalize(status, answer, tasks, task_results)
        except RunBudgetExceeded as exc:
            emit_budget_stopped(exc.reason)
            kept_results = list(task_results)
            kept_tasks = list(tasks)
            provenance["error_type"] = type(exc).__name__
            parts = [r.answer.strip() for r in kept_results if r.answer and r.answer.strip() and r.status != "FAILED"]
            answer = "\n\n".join(parts) if parts else _partial_failure_answer(kept_results, timed_out=(exc.reason == "wall_timeout"), budget_exceeded=(exc.reason != "wall_timeout"))
            status = "PARTIAL" if any(r.status in ("COMPLETE", "PARTIAL", "NO_EVIDENCE") for r in kept_results) else "FAILED"
            effective["attempted_llm_calls"] = guarded.attempted_calls
            answer, status = apply_verified_output_gate(status, answer, kept_results)
            lifecycle_status = "FAILED" if status == "FAILED" else "COMPLETED"
            event("run_finished", status=status, lifecycle_status=lifecycle_status)
            if product_mode:
                return await asyncio.to_thread(finalize, status, answer, kept_tasks, kept_results)
            return finalize(status, answer, kept_tasks, kept_results)
        except Exception as exc:
            kept_results = list(task_results)
            kept_tasks = list(tasks)
            error_category, http_status = classify_run_error(exc)
            is_timeout = isinstance(exc, (TimeoutError, asyncio.TimeoutError))
            provenance["error_type"] = type(exc).__name__
            lifecycle_status = "FAILED"
            effective["attempted_llm_calls"] = guarded.attempted_calls
            failed_payload = {
                "lifecycle_status": lifecycle_status,
                "error_category": error_category,
                "error_type": type(exc).__name__,
                "error": type(exc).__name__,
                "preserved_tasks": len(kept_results),
            }
            if http_status is not None:
                failed_payload["http_status"] = http_status
            event("run_failed", **failed_payload)
            safe_answer = _partial_failure_answer(kept_results, timed_out=is_timeout, budget_exceeded=False) if kept_results else f"Pipeline failed: {type(exc).__name__}"
            if kept_results:
                safe_answer, _ = apply_verified_output_gate("FAILED", safe_answer, kept_results, emit_stream_if_needed=False)
            if product_mode:
                return await asyncio.to_thread(finalize, "FAILED", safe_answer, kept_tasks, kept_results)
            return finalize("FAILED", safe_answer, kept_tasks, kept_results)

    @staticmethod
    def _flags(condition: str) -> dict[str, bool]:
        if condition in {"A", "B"}:
            return {"P": False, "N": False, "O": False}
        if condition == "C":
            return {"P": True, "N": True, "O": True}
        return {"P": condition != "C-P", "N": condition != "C-N", "O": condition != "C-O"}


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

    V9: nếu mô hình nhỏ viết nhiệm vụ chủ yếu bằng tiếng Anh (kể cả khi plan_anchoring gắn tiền tố 'Nghĩa vụ:')
    trong khi câu hỏi gốc là tiếng Việt, ghép câu hỏi gốc tiếng Việt để BM25 vẫn khớp bảng/mục tiếng Việt trong Excel/Word.
    """
    text = f"{task.goal} {' '.join(task.evidence_needs)}".strip()
    stripped_anchor = re.sub(r"\b(?:Nghĩa vụ|Mối quan ngại|Yêu cầu)\s*:", " ", text, flags=re.IGNORECASE)
    if reply_language_of(query) == "vi" and reply_language_of(stripped_anchor) != "vi":
        return f"{text} {query}"
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
