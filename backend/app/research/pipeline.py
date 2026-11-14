from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone

from app.core.config import RuntimeConfig
from app.core.graph import topological_order, validate_tasks
from app.core.telemetry import gpu_memory_mb, process_rss_mb
from app.core.types import RunMetrics, SourceChunk, Task, TaskPlan, TaskResult
from app.providers.factory import get_provider
from app.research.context_controller import ContextController
from app.research.conversation_context import ConversationContext
from app.research.decomposer import (
    PLANNER_SEMANTICS_VERSION,
    TASK_PLAN_PROMPT_VERSION,
    _safe_warning,
    build_semantic_task_plan_repair_prompt,
    canonicalize_task_plan,
    decompose_plan,
    generate_task_plan,
    parse_task_plan_output,
    understand_request,
)
from app.research.normalizer import normalize_tasks
from app.research.obligation_concern_extraction import extract_obligations_and_concerns
from app.research.plan_verification import (
    decide_repair,
    validate_repaired_plan,
    verify_task_plan,
)
from app.research.planning_retrieval import PLANNING_SCORER_VERSION, PlanningRetriever
from app.research.product_intents import (
    is_simple_project_question,
    product_help_response,
)
from app.research.provenance import build_provenance
from app.research.synthesizer import synthesize
from app.research.token_context import POLICIES, TokenContextController, plan_task_budgets
from app.research.token_context import context_policy as env_context_policy
from app.research.product_retrieval import product_retrieve, run_budget_exceeded
from app.research.vanilla import answer_vanilla
from app.research.worker import execute_task
from app.retrieval.index_identity import IndexingError
from app.retrieval.multilingual import build_query_variants, detect_language
from app.retrieval.text import apply_token_budget, estimate_tokens, retrieve, terms
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore

CONDITIONS = {"A", "B", "C", "C-P", "C-N", "C-O"}
_LEXICAL_FALLBACK_FILLERS = frozenset(
    {"what", "which", "who", "where", "when", "why", "how", "doe", "do", "did", "use", "used", "dùng", "gì"}
)

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
    ) -> list[SourceChunk]:
        variants = build_query_variants(query)
        if self.candidate_index is None:
            if chunks is None:
                chunks = self.source_store.chunks(source_ids)
            merged: dict[str, SourceChunk] = {}
            for variant in variants:
                for chunk in retrieve(variant.text, chunks, top_k=top_k, min_score=min_score):
                    current = merged.get(chunk.chunk_id)
                    if current is None or (chunk.score or 0.0) > (current.score or 0.0):
                        merged[chunk.chunk_id] = chunk
            return sorted(merged.values(), key=lambda c: c.score or 0.0, reverse=True)[:top_k]

        # CandidateIndex applies owner/source filters in the vector query before top-k.
        # Hydrate only canonical chunks already scoped by the owner source store.
        matches_by_id = {}
        for variant in variants:
            for match in self.candidate_index.candidates(variant.text, limit=top_k, source_ids=source_ids):
                existing = matches_by_id.get(str(match.payload.get("chunk_id") or ""))
                if existing is None or match.score > existing.score:
                    matches_by_id[str(match.payload.get("chunk_id") or "")] = match
        matches = sorted(matches_by_id.values(), key=lambda match: match.score, reverse=True)[:top_k]
        hydrate = getattr(self.source_store, "chunks_by_ids", None)
        if callable(hydrate):
            matched_chunks = hydrate([str(m.payload.get("chunk_id") or "") for m in matches], source_ids=source_ids)
        elif chunks is not None:
            matched_chunks = chunks
        else:
            raise TypeError("source store must implement chunks_by_ids for lazy hydration")
        chunks_by_id = {chunk.chunk_id: chunk for chunk in matched_chunks
                        if source_ids is None or chunk.source_id in source_ids}
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
        if chunks is None:
            chunks = self.source_store.chunks(source_ids)
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

    async def run(
        self,
        query: str,
        condition: str = "A",
        provider_name: str | None = None,
        *,
        source_ids: list[str] | None = None,
        conversation_context: ConversationContext | str | None = None,
        conversation_id: str | None = None,
        product_mode: bool = False,
        context_policy: str | None = None,
        on_event: Callable[[dict], None] | None = None,
        force_plan: bool = False,
        reply_language_hint: str | None = None,
        multi_retrieval: bool = False,
        answer_checker=None,
    ) -> dict:
        condition = condition.upper()
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
        provider = get_provider(provider_name)
        started = time.perf_counter()
        metrics = RunMetrics(peak_rss_mb=process_rss_mb(), gpu_memory_mb=gpu_memory_mb())
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
            "task_plan_prompt_version": TASK_PLAN_PROMPT_VERSION,
            "task_plan_schema_version": "canonical-task-plan-explicit-coverage-v2",
            "conversation_id": conversation_id,
            "conversation_context": conversation_context.to_trace(),
        }
        policy = env_context_policy() if context_policy is None else context_policy
        if policy not in POLICIES:
            raise ValueError(f"Unsupported context_policy={policy!r}; expected one of {sorted(POLICIES)}")
        effective["context_policy"] = policy
        embedder = getattr(self.candidate_index, "embedder", None)
        provenance = build_provenance(
            provider_name=provider.name,
            model=provider.model,
            embedding_version=getattr(embedder, "version", None) if embedder else "lexical",
            context_policy=policy,
        )

        def event(stage: str, **data):
            if stage in {"vanilla_retrieval", "task_retrieval"}:
                search_info = getattr(self.candidate_index, "last_search_info", None) or {}
                data.update({key: search_info.get(key) for key in (
                    "index_state", "index_embedding_version",
                    "retrieval_backend_used", "fallback_reason",
                )})
            item = {"stage": stage, "ts": datetime.now(timezone.utc).isoformat(), **data}
            events.append(item)
            if on_event is not None:
                try:
                    on_event(item.copy())
                except Exception:
                    logging.getLogger(__name__).exception("Research pipeline event callback failed")

        def make_run(status: str | None, answer: str, tasks: list[Task], task_results: list[TaskResult]) -> dict:
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
            lifecycle_status = "FAILED" if status == "FAILED" else "COMPLETED"
            run = make_run(status, answer, tasks, task_results)
            self.run_store.save(run)
            return run

        persist_lifecycle("PENDING")
        event(
            "run_started",
            lifecycle_status=lifecycle_status,
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
        try:
            product_help = product_help_response(query) if product_mode else None
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
            simple_product_request = bool(
                product_mode
                and condition != "A"
                and not force_plan
                and understanding is not None
                and (multi_retrieval or is_simple_project_question(query, understanding.domains))
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
            budget_cut = False
            if condition == "A" or simple_product_request:
                r0 = time.perf_counter()
                retrieval_trace: dict = {}
                retrieval_query_text = _retrieval_query_with_conversation_context(query, conversation_context)
                if product_mode:
                    candidates = await product_retrieve(
                        self, provider, metrics, query=query, retrieval_query=retrieval_query_text,
                        chunks=all_chunks, cfg=cfg, source_ids=source_ids, trace=retrieval_trace, event=event,
                        multi=multi_retrieval, retry=True,
                    )
                else:
                    candidates = await asyncio.to_thread(self._retrieve_candidates,
                        retrieval_query_text,
                        all_chunks,
                        top_k=cfg.task_top_k,
                        min_score=cfg.retrieval_min_score,
                        source_ids=source_ids,
                        fallback_trace=retrieval_trace,
                    )
                metrics.retrieval_latency_ms += int((time.perf_counter() - r0) * 1000)
                metrics.retrieved_chunks += len(candidates)
                selected, budget_dropped = apply_token_budget(candidates, cfg.max_context_tokens)
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
                    query_variants=[{"label": v.label, "language": v.language} for v in build_query_variants(_retrieval_query_with_conversation_context(query, conversation_context))],
                )
                task = Task(task_id="T1", goal=query, domain="general")
                g0 = time.perf_counter()
                reply_language = None
                if product_mode:
                    # Có dấu tiếng Việt thì trả lời tiếng Việt (detect_language bỏ sót chữ như "ệ", "ề").
                    has_vi_marks = any(unicodedata.combining(ch) for ch in unicodedata.normalize("NFD", query)) or "đ" in query.lower()
                    reply_language = reply_language_hint or (
                        "vi" if has_vi_marks or detect_language(query) != "en" else "en")
                if product_mode and run_budget_exceeded(metrics, cfg, event, "answer"):
                    result = TaskResult(
                        task_id="T1", domain="general", status="NO_EVIDENCE",
                        answer="RUN_BUDGET_EXCEEDED: Token budget exhausted before answer generation.",
                        missing_information=["answer generation skipped: run token budget exhausted"],
                    )
                else:
                    checked_provider = _AttemptCountingProvider(provider, metrics) if product_mode else provider
                    checker = (
                        _BudgetedChecker(answer_checker, metrics, cfg, event)
                        if product_mode and answer_checker is not None else None
                    )
                    try:
                        result = await answer_vanilla(
                            checked_provider, query, selected, metrics, reply_language=reply_language,
                            **({"checker": checker} if checker is not None else {}))
                    except Exception:
                        if not product_mode:
                            raise
                        result = TaskResult(
                            task_id="T1", domain="general", status="PARTIAL" if selected else "NO_EVIDENCE",
                            answer="Answer generation failed. Relevant evidence: " + " ".join(c.text for c in selected)[:500],
                            evidence_ids=[c.chunk_id for c in selected],
                            missing_information=["answer generation failed"],
                        )
                    if checker is not None and checker.budget_cut:
                        budget_cut = True
                if result.guard_notes:
                    event("answer_guard", notes=list(result.guard_notes))
                if result.status == "NO_EVIDENCE":
                    event(
                        "no_evidence",
                        reason="MODEL_REFUSED" if selected else "NO_CHUNKS",
                        retrieved=[c.chunk_id for c in candidates],
                        selected=[c.chunk_id for c in selected],
                    )
                metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                tasks, task_results = [task], [result]
                answer = result.answer
            else:
                planning_request = _planning_request_with_conversation_context(
                    query, conversation_context
                )
                if understanding is None:
                    understanding = understand_request(query)
                    event("request_understanding", **understanding.to_dict())
                extraction_started = time.perf_counter()
                try:
                    extraction = await extract_obligations_and_concerns(
                        provider, query, metrics
                    )
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
                    planning_hits = self.planning.search(
                        query,
                        top_k=cfg.planning_top_k,
                        min_score=cfg.retrieval_min_score,
                    )
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
                        event(
                            "planning_rejected",
                            reason="task_plan_failed_verification_after_repair",
                        )
                        raise ValueError(
                            "TaskPlan failed verification after one bounded repair"
                        )
                    plan = repaired_plan
                    verification = repaired_verification
                elif repair_decision.action == "REJECT":
                    event(
                        "planning_rejected",
                        reason="task_plan_verification_failed",
                        errors=list(verification.errors),
                    )
                    raise ValueError("TaskPlan verification failed")

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
                per_task_budget = max(256, cfg.max_context_tokens // max(1, len(tasks)))
                controller = ContextController(max_chars=per_task_budget * 3)
                budget_plan = None
                if flags["O"] and policy == "adaptive_qwen":
                    # Nhu cầu ước từ lượt truy xuất sơ bộ (chưa có ngữ cảnh phụ thuộc); trần áp vào lượt truy xuất thật bên dưới.
                    preview = {
                        task.task_id: await asyncio.to_thread(self._retrieve_candidates,
                            f"{task.goal} {' '.join(task.evidence_needs)}".strip(),
                            all_chunks,
                            top_k=cfg.task_top_k,
                            min_score=cfg.retrieval_min_score,
                            source_ids=source_ids,
                            fallback_trace={},
                        )
                        for task in ordered
                    }
                    budget_plan = plan_task_budgets(preview, cfg.max_context_tokens)
                    event("adaptive_budget_plan", **budget_plan)
                for task in ordered:
                    dependency_context = " ".join(completed[d].answer for d in task.depends_on if d in completed)
                    retrieval_query = f"{task.goal} {' '.join(task.evidence_needs)} {dependency_context}".strip()
                    r0 = time.perf_counter()
                    retrieval_trace: dict = {}
                    candidates = await asyncio.to_thread(self._retrieve_candidates,
                        retrieval_query,
                        all_chunks,
                        top_k=cfg.task_top_k,
                        min_score=cfg.retrieval_min_score,
                        source_ids=source_ids,
                        fallback_trace=retrieval_trace,
                    )
                    metrics.retrieval_latency_ms += int((time.perf_counter() - r0) * 1000)
                    metrics.retrieved_chunks += len(candidates)
                    if budget_plan is not None:
                        selected, dropped = TokenContextController(budget_plan["limits"][task.task_id]).select(candidates)
                    elif flags["O"]:
                        selected, dropped = controller.select(candidates)
                    else:
                        selected, dropped = candidates, []
                    if budget_plan is None:
                        selected, hard_dropped = apply_token_budget(selected, per_task_budget)
                        dropped = [*dropped, *hard_dropped]
                    metrics.selected_chunks += len(selected)
                    metrics.dropped_chunks += len(dropped)
                    metrics.context_chars += sum(len(c.text) for c in selected)
                    metrics.context_tokens_est += sum(estimate_tokens(c.text) for c in selected)
                    event(
                        "task_retrieval",
                        task_id=task.task_id,
                        retrieval_backend=self.retrieval_backend,
                        retrieval_fallback=retrieval_trace or None,
                        candidates=[c.chunk_id for c in candidates],
                        selected=[c.chunk_id for c in selected],
                        dropped=dropped,
                    )
                    g0 = time.perf_counter()
                    result = await execute_task(provider, task, selected, metrics)
                    metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)
                    completed[task.task_id] = result
                    task_results.append(result)
                    event("task_completed", result=asdict(result))
                    if metrics.input_tokens + metrics.output_tokens > cfg.max_run_tokens:
                        event("run_budget_exceeded", total_tokens=metrics.input_tokens + metrics.output_tokens)
                        budget_cut = len(task_results) < len(ordered)
                        break
                g0 = time.perf_counter()
                answer = await synthesize(provider, query, task_results, metrics)
                metrics.generation_latency_ms += int((time.perf_counter() - g0) * 1000)

            status = "COMPLETE" if task_results and all(r.status == "COMPLETE" for r in task_results) else "PARTIAL"
            if task_results and all(r.status == "NO_EVIDENCE" for r in task_results):
                status = "NO_EVIDENCE"
            if budget_cut:  # run stopped by max_run_tokens with unexecuted tasks
                status = "PARTIAL"
            lifecycle_status = "COMPLETED"
            event(
                "run_finished",
                status=status,
                lifecycle_status=lifecycle_status,
            )
            return finalize(status, answer, tasks, task_results)
        except asyncio.CancelledError:
            event("run_failed", lifecycle_status="FAILED", error="CLIENT_CANCELLED",
                  error_type="CancelledError")
            finalize("FAILED", "CLIENT_CANCELLED", [], [])
            raise
        except Exception as exc:
            lifecycle_status = "FAILED"
            event(
                "run_failed",
                lifecycle_status=lifecycle_status,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            run = finalize("FAILED", f"Pipeline failed: {type(exc).__name__}: {exc}", [], [])
            if isinstance(exc, IndexingError) and getattr(exc, "code", None):
                raise
            return run

    @staticmethod
    def _flags(condition: str) -> dict[str, bool]:
        if condition in {"A", "B"}:
            return {"P": False, "N": False, "O": False}
        if condition == "C":
            return {"P": True, "N": True, "O": True}
        return {"P": condition != "C-P", "N": condition != "C-N", "O": condition != "C-O"}


class _AttemptCountingProvider:
    """Count provider failures even when a downstream verifier swallows them."""

    def __init__(self, provider, metrics):
        self.provider = provider
        self.metrics = metrics

    def __getattr__(self, name):
        value = getattr(self.provider, name)
        if name not in {"generate", "generate_grounded"} or not callable(value):
            return value

        async def generate(**kwargs):
            try:
                return await value(**kwargs)
            except Exception:
                self.metrics.failed_llm_attempts += 1
                raise

        return generate


class _BudgetedChecker:
    """Keep the answer when the optional verification call exceeds the budget."""

    def __init__(self, checker, metrics, cfg, event):
        self.checker, self.metrics, self.cfg, self.event = checker, metrics, cfg, event
        self.budget_cut = False

    def guard(self, *args, **kwargs):
        return self.checker.guard(*args, **kwargs)

    def needs_verification(self, query, answer):
        if not self.checker.needs_verification(query, answer):
            return False
        self.budget_cut = run_budget_exceeded(self.metrics, self.cfg, self.event, "verifier")
        return not self.budget_cut

    async def verify(self, provider, answer, evidence_texts, metrics):
        return await self.checker.verify(provider, answer, evidence_texts, metrics)


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
