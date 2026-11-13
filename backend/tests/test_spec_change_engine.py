import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.review.schemas import Requirement, ReviewCase, Verdict
from app.review_adapters.spec_change_engine import SpecChangeEngine


FIXTURES = Path(__file__).parent / "fixtures" / "spec_change"


@pytest.fixture
def docs():
    return (FIXTURES / "old.json").read_text(encoding="utf-8"), (FIXTURES / "new.json").read_text(encoding="utf-8")


@pytest.fixture
def case():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ReviewCase(id="case-1", owner_user_id="user-1", title="API", request_text="Review API",
                      created_at=now, updated_at=now)


def req(case, text, index=0, confirmed=True):
    return Requirement(id=f"req-{index}", case_id=case.id, text=text, origin="USER",
                       confirmed=confirmed, order=index)


def engine_from(docs):
    return SpecChangeEngine(lambda _: docs[0], lambda _: docs[1])


def test_proposal_and_breaking_and_nonbreaking_changes(docs, case):
    engine = engine_from(docs)
    proposed = engine.propose_requirements(case)
    assert any("DELETE /pets/{id}" in r.text and not r.confirmed for r in proposed)
    requirement_text = (FIXTURES / "requirement.txt").read_text(encoding="utf-8").strip()
    requirements = [req(case, requirement_text, 0), req(case, "GET /pets/{id}", 1)]
    findings = engine.run(case, requirements, None, lambda *_: None)
    assert [f.verdict for f in findings] == [Verdict.DEVIATES, Verdict.SATISFIED]
    assert findings[0].evidence[0].evidence_id.startswith("chg:")
    assert findings[0].evidence[0].source_id == "old"
    assert findings[1].evidence[0].source_id == "new"


def test_no_related_change_is_not_found(case, docs):
    findings = engine_from(docs).run(case, [req(case, "Check billing behavior")], None, lambda *_: None)
    assert findings[0].verdict == Verdict.NOT_FOUND
    assert findings[0].evidence == []


def test_budget_skips_after_limit(case, docs):
    events = []
    requirements = [req(case, "DELETE /pets/{id}", i) for i in range(2)]
    findings = engine_from(docs).run(case, requirements, {"max_requirements": 1}, lambda n, p: events.append(n))
    assert [f.verdict for f in findings] == [Verdict.DEVIATES, Verdict.SKIPPED_BUDGET]
    assert events == ["task.started", "finding.created", "budget.skipped", "finding.created"]


def test_invalid_document_is_undetermined(case):
    engine = SpecChangeEngine(lambda _: "bad", lambda _: "bad")
    findings = engine.run(case, [req(case, "GET /pets")], None, lambda *_: None)
    assert findings[0].verdict == Verdict.UNDETERMINED


def test_determinism(docs, case):
    engine = engine_from(docs)
    requirements = [req(case, "DELETE /pets/{id}")]
    first = [f.model_dump(mode="json") for f in engine.run(case, requirements, None, lambda *_: None)]
    second = [f.model_dump(mode="json") for f in engine.run(case, requirements, None, lambda *_: None)]
    assert first == second


def test_proposals_are_capped_at_25(case):
    paths = {f"/resource-{i}": {"get": {"responses": {"200": {"description": "ok"}}}}
             for i in range(30)}
    old = json.dumps({"openapi": "3.0.3", "info": {"title": "API", "version": "1"}, "paths": {}})
    new = json.dumps({"openapi": "3.0.3", "info": {"title": "API", "version": "2"}, "paths": paths})
    assert len(SpecChangeEngine(lambda _: old, lambda _: new).propose_requirements(case)) == 25


def test_removed_endpoint_proposals_keep_operation_identity(case):
    old = json.dumps({"openapi": "3.0.3", "info": {"title": "API", "version": "1"},
                      "paths": {"/pets/{id}": {"get": {}, "delete": {}}}})
    new = json.dumps({"openapi": "3.0.3", "info": {"title": "API", "version": "2"}, "paths": {}})
    proposals = SpecChangeEngine(lambda _: old, lambda _: new).propose_requirements(case)
    assert [r.text for r in proposals] == [
        "Verify consumers of DELETE /pets/{id} after its change",
        "Verify consumers of GET /pets/{id} after its change",
    ]
