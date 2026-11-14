from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from .engine import ReviewEngine
from .repository import CaseRepository
from .schemas import (
    CaseStatus,
    Decision,
    Finding,
    JobState,
    Requirement,
    RequirementOrigin,
    ReviewCase,
    RunJob,
    Verdict,
)


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
    ) -> None:
        self.repository = repository
        self.engine = engine
        self.clock = clock
        self.id_factory = id_factory
        self.evidence = list(evidence)

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
    ) -> ReviewCase:
        """Create and store a review case for its owner."""
        now = self.clock()
        case = ReviewCase(
            id=self.id_factory(),
            owner_user_id=owner_user_id,
            title=title,
            request_text=request_text,
            source_ids=list(source_ids or []),
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
                    publish(finding)
                    published.add(finding.requirement_id)

                produced = self.engine.run(case, [requirement], call_budget, step)
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
