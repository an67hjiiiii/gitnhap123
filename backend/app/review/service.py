from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.orchestration.budget import BudgetCost, BudgetManager
from app.orchestration.router import Route, RouteRequest, route_request

from .engine import ReviewEngine
from .repository import CaseRepository
from .schemas import (
    CaseStatus,
    Confidence,
    Decision,
    Finding,
    JobState,
    Requirement,
    RequirementOrigin,
    ReviewCase,
    RunJob,
    Verdict,
)


def review_route_decision(case: ReviewCase, requirement_count: int) -> dict:
    """Use the shared router while retaining the configured requirement engine."""
    decision = route_request(RouteRequest(
        text=case.request_text, mode="case", has_sources=bool(case.source_ids or case.old_source_id),
        requirement_count=requirement_count, has_structured_artifacts=case.kind == "spec_change",
        estimated_tokens=(len(case.request_text) + 2) // 3,
        force_route=Route.DETERMINISTIC if case.kind == "spec_change" else None,
    ))
    return {"route": decision.route.value, "reasons": decision.reasons,
            "budget_hint": decision.budget_hint}


class CaseNotFound(LookupError):
    """Raised when a case is absent or belongs to another owner."""


class RequirementsUnconfirmed(ValueError):
    """Raised when a run is requested without confirmed requirements."""


class FindingNotFound(KeyError):
    """Raised when a finding is absent from the case."""


class InvalidDecision(ValueError):
    """Raised when a decision value is invalid or incomplete."""


class RunCancelled(Exception):
    """Cooperative cancellation between requirement checkpoints."""


class ReviewCaseService:
    def __init__(
        self,
        repository: CaseRepository,
        engine: ReviewEngine,
        clock=lambda: datetime.now(timezone.utc),
        id_factory=lambda: str(uuid4()),
        evidence=(),
        memory_store=None,
    ) -> None:
        self.repository = repository
        self.engine = engine
        self.clock = clock
        self.id_factory = id_factory
        self.evidence = list(evidence)
        self.memory_store = memory_store

    def _case(self, case_id: str, owner: str) -> ReviewCase:
        case = self.repository.get_case(owner, case_id)
        if case is None:
            raise CaseNotFound(case_id)
        return case

    def create_case(
        self,
        owner_user_id: str,
        title: str,
        request_text: str,
        source_ids: list[str] | None = None,
        *, kind: str = "requirement_review", old_source_id: str | None = None,
        new_source_id: str | None = None,
    ) -> ReviewCase:
        """Create and store a review case for its owner."""
        now = self.clock()
        case = ReviewCase(
            id=self.id_factory(),
            owner_user_id=owner_user_id,
            title=title,
            request_text=request_text,
            source_ids=list(source_ids or []),
            kind=kind,
            old_source_id=old_source_id if kind == "spec_change" else None,
            new_source_id=new_source_id if kind == "spec_change" else None,
            created_at=now,
            updated_at=now,
        )
        self.repository.save_case(owner_user_id, case)
        return case

    def propose_requirements(self, case_id: str, owner_user_id: str) -> list[Requirement]:
        """Ask the engine for requirements and store them as unconfirmed proposals."""
        case = self._case(case_id, owner_user_id)
        proposed = self.engine.propose_requirements(case)
        safe = [
            requirement.model_copy(
                update={"confirmed": False, "origin": RequirementOrigin.AI_PROPOSED}
            )
            for requirement in proposed
        ]
        self.repository.save_requirements(owner_user_id, case_id, safe)
        case.status = CaseStatus.CONFIRMING
        case.updated_at = self.clock()
        self.repository.save_case(owner_user_id, case)
        return safe

    def confirm_requirements(
        self,
        case_id: str,
        owner_user_id: str,
        requirement_ids: list[str] | None = None,
    ) -> list[Requirement]:
        """Confirm selected requirements and update the case readiness."""
        case = self._case(case_id, owner_user_id)
        requirements = self.repository.get_requirements(owner_user_id, case_id)
        wanted = set(requirement_ids or [item.id for item in requirements])
        for requirement in requirements:
            if requirement.id in wanted:
                requirement.confirmed = True
        self.repository.save_requirements(owner_user_id, case_id, requirements)
        case.status = (
            CaseStatus.READY
            if requirements and all(item.confirmed for item in requirements)
            else CaseStatus.CONFIRMING
        )
        case.updated_at = self.clock()
        self.repository.save_case(owner_user_id, case)
        return requirements

    def add_requirement(
        self, case_id: str, owner_user_id: str, text: str
    ) -> Requirement:
        """Add an unconfirmed user requirement to a case."""
        self._case(case_id, owner_user_id)
        requirements = self.repository.get_requirements(owner_user_id, case_id)
        requirement = Requirement(
            id=self.id_factory(),
            case_id=case_id,
            text=text,
            origin=RequirementOrigin.USER,
            confirmed=False,
            order=len(requirements),
        )
        requirements.append(requirement)
        self.repository.save_requirements(owner_user_id, case_id, requirements)
        return requirement

    def start_run(
        self, case_id: str, owner_user_id: str, budget: dict | None = None, emit=None,
        *, job_id: str | None = None, attempt: int = 1, cancelled=None, checkpoint=None,
    ) -> list[Finding]:
        """Checkpoint each requirement; a leased runner owns managed job state."""
        case = self._case(case_id, owner_user_id)
        requirements = self.repository.get_requirements(owner_user_id, case_id)
        if not requirements or not all(item.confirmed for item in requirements):
            raise RequirementsUnconfirmed(case_id)
        managed = job_id is not None
        job = None
        if not managed:
            case.status, case.updated_at = CaseStatus.RUNNING, self.clock()
            self.repository.save_case(owner_user_id, case)
            job = RunJob(
                id=self.id_factory(), case_id=case_id, state=JobState.RUNNING,
                seq=len(self.repository.get_jobs(owner_user_id, case_id)) + 1,
                budget=budget, started_at=self.clock(),
            )
            self.repository.save_job(owner_user_id, job)
        findings = (self.repository.get_findings(owner_user_id, case_id)
                    if attempt > 1 else [])
        if not managed:
            self.repository.save_findings(owner_user_id, case_id, findings)
        completed = {item.requirement_id for item in findings}
        allowed = {item.evidence_id for item in self.evidence}
        remaining = dict(budget or {})
        if remaining.get("max_requirements") is not None:
            used = sum(item.verdict != Verdict.SKIPPED_BUDGET for item in findings)
            remaining["max_requirements"] = max(0, remaining["max_requirements"] - used)
        started = self.clock()
        manager = None
        if budget is not None:
            manager = BudgetManager(
                max_tokens=budget["max_tokens"] if budget.get("max_tokens") is not None else 2**63 - 1,
                max_seconds=budget["max_seconds"] if budget.get("max_seconds") is not None else 10**12,
                max_model_calls=budget["max_model_calls"] if budget.get("max_model_calls") is not None else 2**63 - 1,
                clock=lambda: max(0, (self.clock() - started).total_seconds()),
            )
            # Replayed checkpoints still consume the original run's allowance.
            if case.kind != "spec_change":
                for item in requirements:
                    if any(f.requirement_id == item.id and f.verdict != Verdict.SKIPPED_BUDGET
                           for f in findings):
                        cost = max(1, (len(item.text) + 2) // 3)
                        if not manager.should_skip(BudgetCost(tokens=cost)).skip:
                            manager.reserve("requirements", cost)

        def publish(finding):
            if cancelled is not None and cancelled():
                raise RunCancelled()
            safe = finding.model_copy(update={
                "review": Decision.NONE, "edited_text": None,
                "evidence": [item for item in finding.evidence if item.evidence_id in allowed],
            })
            if any(item.id == safe.id and item.requirement_id != safe.requirement_id
                   for item in findings):
                safe.id = str(uuid5(NAMESPACE_URL, f"{case_id}:{safe.requirement_id}:{safe.id}"))
            if checkpoint is not None:
                checkpoint(safe)
            else:
                self.repository.save_finding(owner_user_id, case_id, safe)
            findings[:] = [item for item in findings if item.requirement_id != safe.requirement_id]
            findings.append(safe)
            if emit is not None:
                emit(safe)

        try:
            for requirement in requirements:
                if requirement.id in completed:
                    continue
                if cancelled is not None and cancelled():
                    raise RunCancelled()
                call_budget = dict(remaining) if budget is not None else None
                if call_budget is not None and call_budget.get("max_seconds") is not None:
                    elapsed = (self.clock() - started).total_seconds()
                    call_budget["max_seconds"] = max(0, call_budget["max_seconds"] - elapsed)
                published = set()

                def step(finding):
                    if legacy_exhausted:
                        finding = finding.model_copy(update={"verdict": Verdict.SKIPPED_BUDGET, "evidence": []})
                    publish(finding)
                    published.add(finding.requirement_id)

                cost = BudgetCost(
                    tokens=0 if case.kind == "spec_change" else max(1, (len(requirement.text) + 2) // 3),
                    model_calls=0 if case.kind == "spec_change" else 1,
                )
                skipped = []
                if manager is not None:
                    _, skipped = manager.degrade_plan([{"requirement": requirement, "cost": cost}])
                legacy_exhausted = call_budget is not None and (
                    (call_budget.get("max_requirements") is not None and call_budget["max_requirements"] <= 0)
                    or (call_budget.get("max_seconds") is not None and call_budget["max_seconds"] <= 0)
                )
                if skipped:
                    produced = []
                else:
                    if manager is not None and cost.model_calls and not legacy_exhausted:
                        manager.reserve("requirements", cost.tokens)
                    # Preserve legacy engine budget callbacks and checkpoint behavior.
                    produced = self.engine.run(case, [requirement], call_budget, step)
                if (skipped or legacy_exhausted) and requirement.id not in published:
                    produced = [Finding(
                        id=str(uuid5(NAMESPACE_URL, f"{job_id or case_id}:budget:{requirement.id}")),
                        case_id=case_id, requirement_id=requirement.id,
                        verdict=Verdict.SKIPPED_BUDGET, confidence=Confidence.L0,
                    )]
                for finding in produced:
                    if finding.requirement_id not in published:
                        step(finding)
                if remaining.get("max_requirements") is not None:
                    used = sum(item.verdict != Verdict.SKIPPED_BUDGET for item in produced)
                    remaining["max_requirements"] = max(0, remaining["max_requirements"] - used)
        except Exception:
            if not managed:
                case.status, case.updated_at = CaseStatus.FAILED, self.clock()
                self.repository.save_case(owner_user_id, case)
                job.state, job.finished_at = JobState.FAILED, self.clock()
                self.repository.save_job(owner_user_id, job)
            raise
        complete = self.is_complete(requirements, findings)
        if not managed:
            case.status = CaseStatus.COMPLETE if complete else CaseStatus.PARTIAL
            case.updated_at = self.clock()
            self.repository.save_case(owner_user_id, case)
            job.state = JobState.SUCCEEDED if complete else JobState.PARTIAL
            job.finished_at = self.clock()
            self.repository.save_job(owner_user_id, job)
        return findings

    @staticmethod
    def is_complete(requirements, findings):
        by_requirement = {finding.requirement_id: finding for finding in findings}
        return bool(requirements) and all(
            requirement.id in by_requirement and by_requirement[requirement.id].verdict
            not in (Verdict.SKIPPED_BUDGET, Verdict.UNDETERMINED)
            for requirement in requirements
        )

    def decide_finding(
        self,
        case_id: str,
        owner_user_id: str,
        finding_id: str,
        decision: Decision,
        edited_text: str | None = None,
    ) -> Finding:
        """Store a user decision without changing the engine verdict."""
        self._case(case_id, owner_user_id)
        findings = self.repository.get_findings(owner_user_id, case_id)
        try:
            normalized = Decision(decision)
        except (TypeError, ValueError) as error:
            raise InvalidDecision(decision) from error
        if normalized == Decision.NONE:
            raise InvalidDecision(decision)
        for finding in findings:
            if finding.id == finding_id:
                if normalized == Decision.EDIT and not edited_text:
                    raise InvalidDecision("edited_text required")
                finding.review = normalized
                finding.edited_text = edited_text if normalized == Decision.EDIT else None
                self.repository.save_findings(owner_user_id, case_id, findings)
                if self.memory_store is not None:
                    case = self._case(case_id, owner_user_id)
                    requirement = next((item for item in self.repository.get_requirements(
                        owner_user_id, case_id
                    ) if item.id == finding.requirement_id), None)
                    if requirement is not None:
                        project_key = case.source_ids[0] if case.source_ids else "default"
                        self.memory_store.record_from_finding(
                            owner_user_id, project_key, requirement, finding,
                        )
                return finding
        raise FindingNotFound(finding_id)

    def export_markdown(self, case_id: str, owner_user_id: str) -> str:
        """Export the case, requirements, findings, and decisions as Markdown."""
        case = self._case(case_id, owner_user_id)
        requirements = self.repository.get_requirements(owner_user_id, case_id)
        findings = {
            finding.requirement_id: finding
            for finding in self.repository.get_findings(owner_user_id, case_id)
        }
        rows = [f"# {case.title}", "", f"Status: {case.status.value}", "", "## Requirements"]
        for requirement in requirements:
            rows.append(
                f"{requirement.order + 1}. {requirement.text} "
                f"(confirmed: {str(requirement.confirmed).lower()})"
            )
            finding = findings.get(requirement.id)
            if finding is None:
                continue
            rows.extend(
                [
                    f"   - Verdict: {finding.verdict.value}",
                    f"   - Decision: {finding.review.value}",
                ]
            )
            rows.extend(
                f"   - Evidence: {item.evidence_id} ({item.source_id}, "
                f"{item.locator}): {item.excerpt}"
                for item in finding.evidence
            )
        return "\n".join(rows) + "\n"
