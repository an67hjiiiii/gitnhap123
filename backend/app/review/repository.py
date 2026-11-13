from typing import Protocol

from .schemas import Finding, Requirement, ReviewCase, RunJob


class CaseRepository(Protocol):
    def save_case(self, owner_user_id: str, case: ReviewCase) -> None: ...
    def get_case(self, owner_user_id: str, case_id: str) -> ReviewCase | None: ...
    def save_requirements(self, owner_user_id: str, case_id: str, values: list[Requirement]) -> None: ...
    def get_requirements(self, owner_user_id: str, case_id: str) -> list[Requirement]: ...
    def save_findings(self, owner_user_id: str, case_id: str, values: list[Finding]) -> None: ...
    def get_findings(self, owner_user_id: str, case_id: str) -> list[Finding]: ...
    def save_job(self, owner_user_id: str, job: RunJob) -> None: ...
    def get_jobs(self, owner_user_id: str, case_id: str) -> list[RunJob]: ...


class InMemoryCaseRepository:
    def __init__(self):
        self._cases = {}; self._requirements = {}; self._findings = {}; self._jobs = {}

    def save_case(self, owner_user_id, case):
        if owner_user_id != case.owner_user_id: raise ValueError("owner mismatch")
        self._cases[case.id] = case.model_copy(deep=True)
    def get_case(self, owner_user_id, case_id):
        item = self._cases.get(case_id)
        return item.model_copy(deep=True) if item and item.owner_user_id == owner_user_id else None
    def save_requirements(self, owner_user_id, case_id, values):
        if self.get_case(owner_user_id, case_id) is None: raise KeyError(case_id)
        self._requirements[case_id] = [x.model_copy(deep=True) for x in values]
    def get_requirements(self, owner_user_id, case_id):
        if self.get_case(owner_user_id, case_id) is None: return []
        return [x.model_copy(deep=True) for x in self._requirements.get(case_id, [])]
    def save_findings(self, owner_user_id, case_id, values):
        if self.get_case(owner_user_id, case_id) is None: raise KeyError(case_id)
        self._findings[case_id] = [x.model_copy(deep=True) for x in values]
    def get_findings(self, owner_user_id, case_id):
        if self.get_case(owner_user_id, case_id) is None: return []
        return [x.model_copy(deep=True) for x in self._findings.get(case_id, [])]
    def save_job(self, owner_user_id, job):
        case = self.get_case(owner_user_id, job.case_id)
        if case is None: raise KeyError(job.case_id)
        self._jobs.setdefault(job.case_id, []).append(job.model_copy(deep=True))
    def get_jobs(self, owner_user_id, case_id):
        if self.get_case(owner_user_id, case_id) is None: return []
        return [x.model_copy(deep=True) for x in self._jobs.get(case_id, [])]
