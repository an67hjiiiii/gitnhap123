from datetime import datetime, timezone

import pytest

from app.review.engine import FakeReviewEngine
from app.review.repository import InMemoryCaseRepository
from app.review.schemas import (
    CaseStatus,
    Decision,
    Evidence,
    Finding,
    JobState,
    Requirement,
    RequirementOrigin,
    Verdict,
)
from app.review.service import (
    CaseNotFound,
    FindingNotFound,
    InvalidDecision,
    RequirementsUnconfirmed,
    ReviewCaseService,
)


class AdversarialEngine:
    def propose_requirements(self, case):
        return [
            Requirement(
                id="proposal",
                case_id=case.id,
                text="Check policy",
                origin=RequirementOrigin.USER,
                confirmed=True,
                order=0,
            )
        ]

    def run(self, case, requirements, budget, emit):
        return [
            Finding(
                id="finding",
                case_id=case.id,
                requirement_id=requirements[0].id,
                verdict=Verdict.SATISFIED,
                review=Decision.ACCEPT,
                confidence="L1",
            )
        ]


class RaisingEngine(FakeReviewEngine):
    def run(self, case, requirements, budget, emit):
        raise RuntimeError("engine failed")


class UndeterminedEngine(FakeReviewEngine):
    def run(self, case, requirements, budget, emit):
        return [
            Finding(
                id="finding-1",
                case_id=case.id,
                requirement_id=requirements[0].id,
                verdict=Verdict.UNDETERMINED,
                confidence="L0",
            )
        ]


def setup_service(engine=None):
    ticks = iter([datetime(2025, 1, 1, tzinfo=timezone.utc)] * 50)
    ids = iter(f"id-{number}" for number in range(50))
    evidence = [Evidence(evidence_id="e1", source_id="s1", locator="p1", excerpt="text")]
    return ReviewCaseService(
        InMemoryCaseRepository(),
        engine or FakeReviewEngine(evidence=evidence),
        lambda: next(ticks),
        lambda: next(ids),
        evidence,
    )


def ready_case(service, owner="owner", request="Check policy."):
    case = service.create_case(owner, "Audit", request)
    service.propose_requirements(case.id, owner)
    service.confirm_requirements(case.id, owner)
    return case


def test_owner_isolation_on_case_lookup():
    service = setup_service()
    case = service.create_case("owner", "Audit", "Check policy.")
    with pytest.raises(CaseNotFound):
        service._case(case.id, "other")


def test_owner_isolation_on_propose_requirements():
    service = setup_service()
    case = service.create_case("owner", "Audit", "Check policy.")
    with pytest.raises(CaseNotFound):
        service.propose_requirements(case.id, "other")


def test_owner_isolation_on_confirm_requirements():
    service = setup_service()
    case = ready_case(service)
    with pytest.raises(CaseNotFound):
        service.confirm_requirements(case.id, "other")


def test_owner_isolation_on_add_requirement():
    service = setup_service()
    case = service.create_case("owner", "Audit", "Check policy.")
    with pytest.raises(CaseNotFound):
        service.add_requirement(case.id, "other", "More")


def test_owner_isolation_on_start_run():
    service = setup_service()
    case = ready_case(service)
    with pytest.raises(CaseNotFound):
        service.start_run(case.id, "other")


def test_owner_isolation_on_decide_finding():
    service = setup_service()
    case = ready_case(service)
    finding = service.start_run(case.id, "owner")[0]
    with pytest.raises(CaseNotFound):
        service.decide_finding(case.id, "other", finding.id, Decision.ACCEPT)


def test_owner_isolation_on_export():
    service = setup_service()
    case = service.create_case("owner", "Audit", "Check policy.")
    with pytest.raises(CaseNotFound):
        service.export_markdown(case.id, "other")


def test_ai_requirements_are_forced_unconfirmed_and_ai_proposed():
    service = setup_service(AdversarialEngine())
    case = service.create_case("owner", "Audit", "Check policy")
    requirements = service.propose_requirements(case.id, "owner")
    assert requirements[0].confirmed is False
    assert requirements[0].origin == RequirementOrigin.AI_PROPOSED


def test_engine_decision_is_forced_to_none():
    service = setup_service(AdversarialEngine())
    case = ready_case(service)
    finding = service.start_run(case.id, "owner")[0]
    assert finding.review == Decision.NONE


def test_start_run_refuses_zero_requirements():
    service = setup_service()
    case = service.create_case("owner", "Audit", "")
    with pytest.raises(RequirementsUnconfirmed):
        service.start_run(case.id, "owner")


def test_complete_run_sets_complete_status():
    service = setup_service()
    case = ready_case(service)
    service.start_run(case.id, "owner")
    assert service._case(case.id, "owner").status == CaseStatus.COMPLETE


def test_budget_skip_run_is_partial():
    service = setup_service(FakeReviewEngine(skip_budget=True))
    case = ready_case(service)
    finding = service.start_run(case.id, "owner")[0]
    assert finding.verdict == Verdict.SKIPPED_BUDGET
    assert service._case(case.id, "owner").status == CaseStatus.PARTIAL


def test_undetermined_run_is_partial():
    service = setup_service(UndeterminedEngine())
    case = ready_case(service)
    finding = service.start_run(case.id, "owner")[0]
    assert finding.verdict == Verdict.UNDETERMINED
    assert service._case(case.id, "owner").status == CaseStatus.PARTIAL


def test_engine_failure_marks_case_and_job_failed_and_reraises():
    service = setup_service(RaisingEngine())
    case = ready_case(service)
    with pytest.raises(RuntimeError, match="engine failed"):
        service.start_run(case.id, "owner")
    assert service._case(case.id, "owner").status == CaseStatus.FAILED
    assert service.repository.get_jobs("owner", case.id)[-1].state == JobState.FAILED


def test_edit_requires_edited_text():
    service = setup_service()
    case = ready_case(service)
    finding = service.start_run(case.id, "owner")[0]
    with pytest.raises(InvalidDecision):
        service.decide_finding(case.id, "owner", finding.id, Decision.EDIT)


def test_decision_never_changes_verdict():
    service = setup_service()
    case = ready_case(service)
    finding = service.start_run(case.id, "owner")[0]
    verdict = finding.verdict
    decided = service.decide_finding(case.id, "owner", finding.id, Decision.REJECT)
    assert decided.review == Decision.REJECT
    assert decided.verdict == verdict


def test_missing_finding_uses_named_key_error_subclass():
    service = setup_service()
    case = ready_case(service)
    service.start_run(case.id, "owner")
    with pytest.raises(FindingNotFound):
        service.decide_finding(case.id, "owner", "missing", Decision.ACCEPT)


def test_export_markdown_matches_golden_string_deterministically():
    service = setup_service()
    case = ready_case(service)
    finding = service.start_run(case.id, "owner")[0]
    service.decide_finding(case.id, "owner", finding.id, Decision.EDIT, "Updated wording")
    expected = (
        "# Audit\n\nStatus: COMPLETE\n\n## Requirements\n"
        "1. Check policy (confirmed: true)\n"
        "   - Verdict: SATISFIED\n"
        "   - Decision: EDIT\n"
        "   - Evidence: e1 (s1, p1): text\n"
    )
    assert service.export_markdown(case.id, "owner") == expected
    assert service.export_markdown(case.id, "owner") == expected


def test_evidence_ids_outside_allowed_set_are_dropped():
    service = setup_service(
        FakeReviewEngine(
            foreign_evidence_id="intruder",
            evidence=[Evidence(evidence_id="e1", source_id="s1", locator="p1", excerpt="text")],
        )
    )
    case = ready_case(service)
    finding = service.start_run(case.id, "owner")[0]
    assert [item.evidence_id for item in finding.evidence] == ["e1"]


def test_clock_and_id_factories_make_output_deterministic():
    service = setup_service()
    case = service.create_case("owner", "Audit", "Check policy.", ["s1"])
    requirement = service.propose_requirements(case.id, "owner")[0]
    service.confirm_requirements(case.id, "owner")
    finding = service.start_run(case.id, "owner")[0]
    assert case.id == "id-0"
    assert case.created_at == case.updated_at == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert requirement.id == "id-0:req-1"
    assert finding.id == "finding-1"
    assert service.repository.get_jobs("owner", case.id)[0].id == "id-1"
