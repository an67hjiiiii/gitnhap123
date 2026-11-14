from typing import Protocol

from .schemas import Finding, Requirement, ReviewCase, RunJob


class CaseRepository(Protocol):
    def save_case(self, owner_user_id: str, case: ReviewCase) -> None: ...

    def get_case(self, owner_user_id: str, case_id: str) -> ReviewCase | None: ...

    def save_requirements(
        self, owner_user_id: str, case_id: str, values: list[Requirement]
    ) -> None: ...

    def get_requirements(self, owner_user_id: str, case_id: str) -> list[Requirement]: ...

    def save_findings(
        self, owner_user_id: str, case_id: str, values: list[Finding]
    ) -> None: ...

    def save_finding(self, owner_user_id: str, case_id: str, value: Finding) -> None: ...

    def get_findings(self, owner_user_id: str, case_id: str) -> list[Finding]: ...

    def save_job(self, owner_user_id: str, job: RunJob) -> None: ...

    def get_jobs(self, owner_user_id: str, case_id: str) -> list[RunJob]: ...


class InMemoryCaseRepository:
    def __init__(self) -> None:
        self._cases: dict[str, ReviewCase] = {}
        self._requirements: dict[str, list[Requirement]] = {}
        self._findings: dict[str, list[Finding]] = {}
        self._jobs: dict[str, list[RunJob]] = {}

    def list_cases(self, owner_user_id: str) -> list[ReviewCase]:
        return [case.model_copy(deep=True) for case in list(self._cases.values())
                if case.owner_user_id == owner_user_id]

    def save_case(self, owner_user_id: str, case: ReviewCase) -> None:
        if owner_user_id != case.owner_user_id:
            raise ValueError("owner mismatch")
        self._cases[case.id] = case.model_copy(deep=True)

    def get_case(self, owner_user_id: str, case_id: str) -> ReviewCase | None:
        item = self._cases.get(case_id)
        if item is None or item.owner_user_id != owner_user_id:
            return None
        return item.model_copy(deep=True)

    def save_requirements(
        self, owner_user_id: str, case_id: str, values: list[Requirement]
    ) -> None:
        if self.get_case(owner_user_id, case_id) is None:
            raise KeyError(case_id)
        self._requirements[case_id] = [value.model_copy(deep=True) for value in values]

    def get_requirements(self, owner_user_id: str, case_id: str) -> list[Requirement]:
        if self.get_case(owner_user_id, case_id) is None:
            return []
        return [value.model_copy(deep=True) for value in self._requirements.get(case_id, [])]

    def save_findings(
        self, owner_user_id: str, case_id: str, values: list[Finding]
    ) -> None:
        if self.get_case(owner_user_id, case_id) is None:
            raise KeyError(case_id)
        self._findings[case_id] = [value.model_copy(deep=True) for value in values]

    def get_findings(self, owner_user_id: str, case_id: str) -> list[Finding]:
        if self.get_case(owner_user_id, case_id) is None:
            return []
        return [value.model_copy(deep=True) for value in self._findings.get(case_id, [])]

    def save_finding(self, owner_user_id: str, case_id: str, value: Finding) -> None:
        findings = self.get_findings(owner_user_id, case_id)
        findings = [item for item in findings if item.requirement_id != value.requirement_id]
        self.save_findings(owner_user_id, case_id, [*findings, value])

    def save_job(self, owner_user_id: str, job: RunJob) -> None:
        if self.get_case(owner_user_id, job.case_id) is None:
            raise KeyError(job.case_id)
        jobs = self._jobs.setdefault(job.case_id, [])
        copy = job.model_copy(deep=True)
        for index, existing in enumerate(jobs):
            if existing.id == job.id:
                jobs[index] = copy
                break
        else:
            jobs.append(copy)

    def get_jobs(self, owner_user_id: str, case_id: str) -> list[RunJob]:
        if self.get_case(owner_user_id, case_id) is None:
            return []
        return [value.model_copy(deep=True) for value in self._jobs.get(case_id, [])]
