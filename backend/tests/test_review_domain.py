from datetime import datetime, timezone

import pytest

from app.review.engine import FakeReviewEngine
from app.review.repository import InMemoryCaseRepository
from app.review.schemas import Decision, Evidence, Verdict
from app.review.service import CaseNotFound, RequirementsUnconfirmed, ReviewCaseService


def setup_service(engine=None):
    ticks = iter([datetime(2025, 1, 1, tzinfo=timezone.utc)] * 30)
    ids = iter(f"id-{n}" for n in range(30))
    evidence = [Evidence(evidence_id="e1", source_id="s1", locator="p1", excerpt="text")]
    svc = ReviewCaseService(InMemoryCaseRepository(), engine or FakeReviewEngine(evidence=evidence), lambda: next(ticks), lambda: next(ids), evidence)
    return svc


def test_owner_isolation_and_requirement_confirmation():
    svc = setup_service(); case = svc.create_case("owner", "Audit", "First sentence. Second sentence.")
    assert svc.repository.get_case("other", case.id) is None
    with pytest.raises(CaseNotFound): svc.propose_requirements(case.id, "other")
    requirements = svc.propose_requirements(case.id, "owner")
    assert len(requirements) == 2 and all(not r.confirmed for r in requirements)
    with pytest.raises(RequirementsUnconfirmed): svc.start_run(case.id, "owner")
    svc.confirm_requirements(case.id, "owner")
    assert all(r.confirmed for r in svc.repository.get_requirements("owner", case.id))


def test_finding_evidence_is_filtered_decisions_do_not_change_verdict():
    svc = setup_service(FakeReviewEngine(foreign_evidence_id="intruder", evidence=[Evidence(evidence_id="e1", source_id="s1", locator="p1", excerpt="text")]))
    case = svc.create_case("owner", "Audit", "Check policy.")
    requirement = svc.propose_requirements(case.id, "owner")[0]
    svc.confirm_requirements(case.id, "owner")
    finding = svc.start_run(case.id, "owner")[0]
    assert [e.evidence_id for e in finding.evidence] == ["e1"]
    assert finding.review == Decision.NONE
    verdict = finding.verdict
    with pytest.raises(ValueError): svc.decide_finding(case.id, "owner", finding.id, Decision.EDIT)
    decided = svc.decide_finding(case.id, "owner", finding.id, Decision.REJECT)
    assert decided.review == Decision.REJECT and decided.verdict == verdict
    assert "Decision: REJECT" in svc.export_markdown(case.id, "owner")


def test_partial_status_for_budget_skip_and_complete_for_normal_verdict():
    svc = setup_service(FakeReviewEngine(skip_budget=True))
    case = svc.create_case("owner", "Audit", "Check policy.")
    svc.propose_requirements(case.id, "owner"); svc.confirm_requirements(case.id, "owner")
    finding = svc.start_run(case.id, "owner")[0]
    assert finding.verdict == Verdict.SKIPPED_BUDGET
    assert svc._case(case.id, "owner").status.value == "PARTIAL"
