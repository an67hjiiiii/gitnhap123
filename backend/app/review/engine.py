from typing import Callable, Protocol

from .schemas import Evidence, Finding, Requirement, ReviewCase, Verdict, Confidence


class ReviewEngine(Protocol):
    def propose_requirements(self, case: ReviewCase) -> list[Requirement]: ...
    def run(self, case: ReviewCase, requirements: list[Requirement], budget: dict | None,
            emit: Callable[[Finding], None]) -> list[Finding]: ...


class FakeReviewEngine:
    def __init__(self, skip_budget: bool = False, foreign_evidence_id: str | None = None,
                 evidence: list[Evidence] | None = None):
        self.skip_budget = skip_budget
        self.foreign_evidence_id = foreign_evidence_id
        self.evidence = evidence or []

    def propose_requirements(self, case):
        lines = [part.strip() for line in case.request_text.splitlines() for part in line.split(".") if part.strip()]
        return [Requirement(id=f"req-{i+1}", case_id=case.id, text=text.rstrip(".!?"),
                            origin="AI_PROPOSED", confirmed=False, order=i) for i, text in enumerate(lines)]

    def run(self, case, requirements, budget, emit):
        out = []
        for i, req in enumerate(requirements):
            cited = list(self.evidence[:1])
            if self.foreign_evidence_id:
                cited.append(Evidence(evidence_id=self.foreign_evidence_id, source_id="foreign", locator="", excerpt=""))
            finding = Finding(id=f"finding-{i+1}", case_id=case.id, requirement_id=req.id,
                              verdict=Verdict.SKIPPED_BUDGET if self.skip_budget else Verdict.SATISFIED,
                              evidence=cited, confidence=Confidence.L0)
            emit(finding); out.append(finding)
        return out
