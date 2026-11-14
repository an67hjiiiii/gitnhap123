"""Run confirmed review requirements through an injected research pipeline."""

from __future__ import annotations

import asyncio
import inspect
import re
import time
from collections.abc import Callable

from app.research.pipeline import ResearchPipeline
from app.review.schemas import Confidence, Evidence, Finding, Requirement, ReviewCase, Verdict
from app.review_adapters.verdict_rules import assess, check_answer


class PipelineReviewEngine:
    """A factory receives an owner ID and must return an owner-scoped pipeline.

    A supplied pipeline must already be scoped to the resolved owner. The owner
    defaults to the case owner; an explicit ID or case resolver can override it,
    but must match the case. source_ids_getter(case) may narrow case.source_ids.
    The seconds budget is checked between calls, never interrupts an active call.
    Named event callbacks receive (name, payload). The ReviewEngine protocol's
    legacy one-argument callbacks receive only Finding objects.
    """

    def __init__(
        self,
        pipeline: ResearchPipeline | None = None,
        *,
        pipeline_factory: Callable[[str], ResearchPipeline] | None = None,
        owner_user_id: str | Callable[[ReviewCase], str] | None = None,
        source_ids_getter: Callable[[ReviewCase], list[str]] | None = None,
    ) -> None:
        if (pipeline is None) == (pipeline_factory is None):
            raise ValueError("Supply exactly one pipeline or pipeline_factory")
        self.pipeline = pipeline
        self.pipeline_factory = pipeline_factory
        self.owner_user_id = owner_user_id
        self.source_ids_getter = source_ids_getter

    def propose_requirements(self, case: ReviewCase) -> list[Requirement]:
        texts: list[str] = []
        seen: set[str] = set()
        for line in case.request_text.splitlines():
            line = re.sub(r"^\s*(?:[-*•]+\s*|\d+[.)]\s+)", "", line)
            for part in re.split(r"[.!?]+(?:\s+|$)", line):
                text = " ".join(part.split()).strip(".!? ")
                key = text.casefold()
                if text and key not in seen:
                    texts.append(text)
                    seen.add(key)
                if len(texts) == 12:
                    break
            if len(texts) == 12:
                break
        return [
            Requirement(
                id=f"{case.id}:req-{index + 1}", case_id=case.id, text=text,
                origin="AI_PROPOSED", confirmed=False, order=index,
            )
            for index, text in enumerate(texts)
        ]

    def run(self, case, requirements, budget, emit) -> list[Finding]:
        """Sync ReviewEngine entry point; use await run_async in an event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(case, requirements, budget, emit))
        raise RuntimeError("Use await PipelineReviewEngine.run_async inside an event loop")

    @staticmethod
    def _emit(emit, name: str, payload: dict, finding: Finding | None = None) -> None:
        try:
            inspect.signature(emit).bind(name, payload)
        except TypeError:
            if finding is not None:
                emit(finding)
        except ValueError:
            emit(name, payload)
        else:
            emit(name, payload)

    @staticmethod
    def _evidence(pipeline, result: dict, source_ids: list[str]) -> list[Evidence]:
        tasks = result.get("task_results", [])
        citations = list(dict.fromkeys(cid for task in tasks for cid in task.get("citations", [])))
        retrieved = {cid for task in tasks for cid in task.get("evidence_ids", [])}
        chunks = {chunk.chunk_id: chunk for chunk in pipeline.source_store.chunks(source_ids)}
        evidence = []
        for citation in citations:
            chunk = chunks.get(citation)
            # Do not turn uncited retrieved chunks or out-of-scope IDs into evidence.
            if chunk is None or citation not in retrieved or chunk.source_id not in source_ids:
                continue
            evidence.append(Evidence(
                evidence_id=citation, source_id=chunk.source_id,
                locator=str(chunk.provenance.get("locator") or citation), excerpt=chunk.text,
            ))
        return evidence

    async def run_async(
        self, case: ReviewCase, requirements: list[Requirement],
        budget: dict | None, emit: Callable,
    ) -> list[Finding]:
        """Execute confirmed requirements in list order, with no parallel calls."""
        budget = budget or {}
        started = time.monotonic()
        attempts = 0
        findings = []
        for requirement in requirements:
            if not requirement.confirmed:
                continue
            payload = {"case_id": case.id, "requirement_id": requirement.id}
            skipped = (
                budget.get("max_requirements") is not None
                and attempts >= budget["max_requirements"]
            ) or (
                budget.get("max_seconds") is not None
                and time.monotonic() - started >= budget["max_seconds"]
            )
            verdict = Verdict.SKIPPED_BUDGET if skipped else Verdict.UNDETERMINED
            evidence = []
            if skipped:
                self._emit(emit, "budget.skipped", payload)
            else:
                attempts += 1
                self._emit(emit, "task.started", payload)
                try:
                    owner = self.owner_user_id
                    owner = owner(case) if callable(owner) else owner
                    owner = case.owner_user_id if owner is None else owner
                    if owner != case.owner_user_id or requirement.case_id != case.id:
                        raise ValueError("Review owner or requirement case mismatch")
                    selected = (
                        self.source_ids_getter(case)
                        if self.source_ids_getter else case.source_ids
                    )
                    source_ids = [sid for sid in case.source_ids if sid in selected]
                    pipeline = self.pipeline_factory(owner) if self.pipeline_factory else self.pipeline
                    result = await pipeline.run(requirement.text, source_ids=source_ids)
                    evidence = self._evidence(pipeline, result, source_ids)
                    status = result.get("status")
                    if status == "COMPLETE" and evidence:
                        verdict = Verdict.SATISFIED
                    elif status == "PARTIAL":
                        verdict = Verdict.PARTIAL
                    elif status == "NO_EVIDENCE":
                        verdict = Verdict.NOT_FOUND
                    if status in {"COMPLETE", "PARTIAL"} and any(e.excerpt for e in evidence):
                        assessment = assess(requirement.text, evidence)
                        if assessment.conflicting:
                            verdict = Verdict.DEVIATES
                            evidence = list(assessment.conflicting)
                            evidence.extend(e for e in assessment.supporting if e not in evidence)
                            self._emit(emit, "verdict.conflict", {
                                **payload, "detail": " ".join(assessment.notes),
                                "conflicting_evidence_ids": [
                                    e.evidence_id for e in assessment.conflicting
                                ],
                            })
                    if status == "COMPLETE" and verdict == Verdict.SATISFIED:
                        checks = [check_answer(requirement.text, task.get("answer"), evidence)
                                  for task in result.get("task_results", [])]
                        notes = [note for check in checks if check.status == "UNSUPPORTED_CLAIM"
                                 for note in check.notes]
                        if notes:
                            verdict = Verdict.PARTIAL
                            self._emit(emit, "verdict.answer_inconsistent", {
                                **payload, "detail": " ".join(notes),
                                "evidence_ids": [e.evidence_id for e in evidence],
                            })
                except Exception as exc:
                    verdict = Verdict.UNDETERMINED
                    evidence = []
                    self._emit(emit, "task.failed", {
                        **payload, "error_type": type(exc).__name__, "error": str(exc),
                    })
            finding = Finding(
                id=f"{case.id}:finding:{requirement.id}", case_id=case.id,
                requirement_id=requirement.id, verdict=verdict,
                evidence=evidence, confidence=Confidence.L1,
            )
            findings.append(finding)
            self._emit(emit, "finding.created", finding.model_dump(mode="json"), finding)
        return findings
