from datetime import datetime, timezone
from uuid import uuid4

from .schemas import (CaseStatus, Decision, Finding, JobState, Requirement, RequirementOrigin,
                      ReviewCase, RunJob, Verdict)


class CaseNotFound(LookupError): pass
class RequirementsUnconfirmed(ValueError): pass


class ReviewCaseService:
    def __init__(self, repository, engine, clock=lambda: datetime.now(timezone.utc), id_factory=lambda: str(uuid4()), evidence=()):
        self.repository, self.engine, self.clock, self.id_factory = repository, engine, clock, id_factory
        self.evidence = list(evidence)

    def _case(self, case_id, owner):
        case = self.repository.get_case(owner, case_id)
        if case is None: raise CaseNotFound(case_id)
        return case

    def create_case(self, owner_user_id, title, request_text, source_ids=None):
        now = self.clock(); case = ReviewCase(id=self.id_factory(), owner_user_id=owner_user_id, title=title,
            request_text=request_text, source_ids=list(source_ids or []), created_at=now, updated_at=now)
        self.repository.save_case(owner_user_id, case); return case

    def propose_requirements(self, case_id, owner_user_id):
        case = self._case(case_id, owner_user_id)
        proposed = self.engine.propose_requirements(case)
        safe = [r.model_copy(update={"confirmed": False, "origin": RequirementOrigin.AI_PROPOSED}) for r in proposed]
        self.repository.save_requirements(owner_user_id, case_id, safe)
        case.status = CaseStatus.CONFIRMING; case.updated_at = self.clock(); self.repository.save_case(owner_user_id, case)
        return safe

    def confirm_requirements(self, case_id, owner_user_id, requirement_ids=None):
        case = self._case(case_id, owner_user_id); requirements = self.repository.get_requirements(owner_user_id, case_id)
        wanted = set(requirement_ids or [r.id for r in requirements])
        for req in requirements:
            if req.id in wanted: req.confirmed = True
        self.repository.save_requirements(owner_user_id, case_id, requirements)
        case.status = CaseStatus.READY if requirements and all(r.confirmed for r in requirements) else CaseStatus.CONFIRMING
        case.updated_at = self.clock(); self.repository.save_case(owner_user_id, case); return requirements

    def add_requirement(self, case_id, owner_user_id, text):
        self._case(case_id, owner_user_id); reqs = self.repository.get_requirements(owner_user_id, case_id)
        req = Requirement(id=self.id_factory(), case_id=case_id, text=text, origin=RequirementOrigin.USER, confirmed=False, order=len(reqs))
        reqs.append(req); self.repository.save_requirements(owner_user_id, case_id, reqs); return req

    def start_run(self, case_id, owner_user_id, budget=None):
        case = self._case(case_id, owner_user_id); reqs = self.repository.get_requirements(owner_user_id, case_id)
        if not reqs or not all(r.confirmed for r in reqs): raise RequirementsUnconfirmed(case_id)
        now = self.clock(); case.status = CaseStatus.RUNNING; case.updated_at = now; self.repository.save_case(owner_user_id, case)
        job = RunJob(id=self.id_factory(), case_id=case_id, state=JobState.RUNNING, seq=len(self.repository.get_jobs(owner_user_id, case_id))+1, budget=budget, started_at=now)
        self.repository.save_job(owner_user_id, job)
        allowed = {e.evidence_id: e for e in self.evidence}
        produced = self.engine.run(case, reqs, budget, lambda _: None)
        sanitized = []
        for f in produced:
            safe = f.model_copy(update={"review": Decision.NONE, "evidence": [e for e in f.evidence if e.evidence_id in allowed]})
            sanitized.append(safe)
        self.repository.save_findings(owner_user_id, case_id, sanitized)
        complete = len(sanitized) == len(reqs) and all(f.verdict not in (Verdict.SKIPPED_BUDGET, Verdict.UNDETERMINED) for f in sanitized)
        case.status = CaseStatus.COMPLETE if complete else CaseStatus.PARTIAL; case.updated_at = self.clock(); self.repository.save_case(owner_user_id, case)
        job.state = JobState.SUCCEEDED if complete else JobState.PARTIAL; job.finished_at = self.clock(); self.repository.save_job(owner_user_id, job)
        return sanitized

    def decide_finding(self, case_id, owner_user_id, finding_id, decision, edited_text=None):
        self._case(case_id, owner_user_id); findings = self.repository.get_findings(owner_user_id, case_id)
        for f in findings:
            if f.id == finding_id:
                decision = Decision(decision)
                if decision == Decision.EDIT and not edited_text: raise ValueError("edited_text required")
                f.review = decision; f.edited_text = edited_text if decision == Decision.EDIT else None
                self.repository.save_findings(owner_user_id, case_id, findings); return f
        raise KeyError(finding_id)

    def export_markdown(self, case_id, owner_user_id):
        case = self._case(case_id, owner_user_id); reqs = self.repository.get_requirements(owner_user_id, case_id)
        findings = {f.requirement_id: f for f in self.repository.get_findings(owner_user_id, case_id)}
        rows = [f"# {case.title}", "", f"Status: {case.status.value}", "", "## Requirements"]
        for r in reqs:
            rows += [f"{r.order + 1}. {r.text} (confirmed: {str(r.confirmed).lower()})"]
            f = findings.get(r.id)
            if f:
                rows += [f"   - Verdict: {f.verdict.value}", f"   - Decision: {f.review.value}"]
                rows += [f"   - Evidence: {e.evidence_id} ({e.source_id}, {e.locator}): {e.excerpt}" for e in f.evidence]
        return "\n".join(rows) + "\n"
