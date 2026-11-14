import math
import os
from time import sleep
from typing import Callable, Protocol

from .schemas import Confidence, Evidence, Finding, Requirement, ReviewCase, Verdict


class ReviewEngine(Protocol):
    def propose_requirements(self, case: ReviewCase) -> list[Requirement]: ...

    def run(
        self,
        case: ReviewCase,
        requirements: list[Requirement],
        budget: dict | None,
        emit: Callable[[Finding], None],
    ) -> list[Finding]: ...


class FakeReviewEngine:
    def __init__(
        self,
        skip_budget: bool = False,
        foreign_evidence_id: str | None = None,
        evidence: list[Evidence] | None = None,
        delay_ms: float | None = None,
    ) -> None:
        self.skip_budget = skip_budget
        self.foreign_evidence_id = foreign_evidence_id
        self.evidence = evidence or []
        if delay_ms is None:
            try:
                delay_ms = float(os.getenv("REVIEW_FAKE_DELAY_MS", "0"))
            except ValueError:
                delay_ms = 0
            if not math.isfinite(delay_ms) or delay_ms < 0:
                delay_ms = 0
        if not math.isfinite(delay_ms) or delay_ms < 0:
            raise ValueError("delay_ms must be finite and nonnegative")
        self.delay_ms = delay_ms

    def propose_requirements(self, case: ReviewCase) -> list[Requirement]:
        lines = [
            part.strip()
            for line in case.request_text.splitlines()
            for part in line.split(".")
            if part.strip()
        ]
        return [
            Requirement(
                id=f"{case.id}:req-{index + 1}",
                case_id=case.id,
                text=text.rstrip(".!?"),
                origin="AI_PROPOSED",
                confirmed=False,
                order=index,
            )
            for index, text in enumerate(lines)
        ]

    def run(
        self,
        case: ReviewCase,
        requirements: list[Requirement],
        budget: dict | None,
        emit: Callable[[Finding], None],
    ) -> list[Finding]:
        findings = []
        for index, requirement in enumerate(requirements):
            if self.delay_ms:
                sleep(self.delay_ms / 1000)
            cited = list(self.evidence[:1])
            if self.foreign_evidence_id:
                cited.append(
                    Evidence(
                        evidence_id=self.foreign_evidence_id,
                        source_id="foreign",
                        locator="",
                        excerpt="",
                    )
                )
            finding = Finding(
                id=f"finding-{index + 1}",
                case_id=case.id,
                requirement_id=requirement.id,
                verdict=Verdict.SKIPPED_BUDGET if self.skip_budget else Verdict.SATISFIED,
                evidence=cited,
                confidence=Confidence.L0,
            )
            emit(finding)
            findings.append(finding)
        return findings
