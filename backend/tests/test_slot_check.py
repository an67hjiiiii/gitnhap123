"""Small value-coverage contracts using pure functions and in-memory citations."""

from datetime import datetime, timezone
from types import SimpleNamespace
import unicodedata

import pytest

from app.review.schemas import Requirement, ReviewCase, Verdict
from app.review_adapters.pipeline_engine import PipelineReviewEngine
from app.review_adapters.slot_check import check_slots, extract_slots


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")


@pytest.mark.parametrize("text,expected", [
    ("retain logs for 180 days", ["number:180 days"]),
    ("Phiên hết hạn sau 30 phút", ["number:30 minutes"]),
    ("Lưu nhật ký 2 giờ và 1 năm", ["number:2 hours", "number:1 years"]),
    ("availability 99.90%", ["number:99.9 %"]),
    ("upload limit 10 MB", ["number:10 MB"]),
    ("return `AUTH_REQUIRED`", ["literal:auth_required"]),
    ("return “Access denied”", ["literal:access denied"]),
    ("return 'pending' or ‘blocked’", ["literal:pending", "literal:blocked"]),
    ("integrate Microsoft Entra ID", ["entity:microsoft entra id"]),
    ("encrypt with AES256", ["entity:aes256"]),
    ("use /v1/invoices and ERR_AUTH_401", ["entity:/v1/invoices", "entity:err_auth_401"]),
    ("Microsoft Entra ID must authenticate users", ["entity:microsoft entra id"]),
    ("notify Nguyễn Văn An", ["entity:nguyễn văn an"]),
    ("Authentication requires a valid token.", []),
    ("Phiên đăng nhập hết hạn sau bao nhiêu phút?", []),
    ("", []),
])
def test_extract_slots(text, expected):
    assert [str(slot) for slot in extract_slots(text)] == expected
    assert extract_slots(text) == extract_slots(text)


@pytest.mark.parametrize("requirement,evidence", [
    ("retain for 180 days", "Retain for 180 ngày."),
    ("expire after 30 phút", "Expire after 0.5 hours."),
    ("retain for 2 giờ", "Retain for 120 minutes."),
    ("retain for 1 năm", "Retain for 365 days."),
    ("availability 99.9%", "Availability 99,9 percent."),
    ("upload limit 10 MB", "Upload limit 0.01 GB."),
    ("password 12 ký tự", "Password 12 characters."),
    ("limit 1,000 MB", "Limit 1000 megabytes."),
    ("return `AUTH_REQUIRED`", "Return auth_required."),
    ("integrate Microsoft Entra ID", "Integrate microsoft entra id."),
    ("use /v1/invoices", "Use /v1/invoices."),
    ("use /v1/invoices/", "Use /v1/invoices/."),
    ("encrypt with AES256", "Encrypted using AES256."),
    ("notify Nguyễn Văn An", "Notify Nguyễn Văn An."),
])
def test_normalized_values_are_covered(requirement, evidence):
    coverage = check_slots(requirement, [unicodedata.normalize("NFD", evidence)])
    assert coverage.slots
    assert coverage.any_covered
    assert coverage.missing_slots == ()


@pytest.mark.parametrize("requirement,evidence", [
    ("retain for 180 days", "Retain for 1180 days or 1800 days."),
    ("retain for 180 days", "Retain for 180 hours."),
    ("expire after 30 minutes", "Expire after 3:00 minutes."),
    ("availability 99.9%", "Availability 199.9% or 99.95%."),
    ("limit 10 MB", "Limit 110 MB or 10 GB."),
    ("return `AUTH_REQUIRED`", "Return AUTH_REQUIRED_EXTRA."),
    ("use ERR_40", "Return ERR_401."),
    ("use /v1/upload", "Use /v1/uploads or /v1/upload/archive."),
    ("use /v1/upload", "Use /v1/upload.csv."),
    ("use /v1/upload/", "Use /v1/upload/archive."),
    ("integrate Microsoft Entra ID", "Integrate Microsoft Entra Identity."),
])
def test_different_values_and_substrings_are_missing(requirement, evidence):
    coverage = check_slots(requirement, [evidence])
    assert not coverage.any_covered
    assert coverage.missing_slots == tuple(map(str, coverage.slots))


def test_union_of_chunks_covers_slots_but_never_joins_literal_fragments():
    requirement = 'retain for 180 days and return "Access denied"'
    assert check_slots(requirement, ["Retain for 180 days", "Access denied"]).missing_slots == ()
    coverage = check_slots(requirement, ["Retain for 180 days. Access", "denied"])
    assert coverage.any_covered
    assert coverage.missing_slots == ("literal:access denied",)
    assert check_slots("retain for 180 days and 180 ngày", []).missing_slots == ("number:180 days",)


def _review(requirement_text, evidence_texts, *, status="COMPLETE", answer=None,
            cited_ids=None, retrieved_ids=None):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = ReviewCase(
        id="slots-case", owner_user_id="owner", title="Slots", request_text=requirement_text,
        source_ids=["selected"], created_at=now, updated_at=now,
    )
    requirement = Requirement(id="r1", case_id=case.id, text=requirement_text,
                              origin="USER", confirmed=True, order=0)
    chunks = [SimpleNamespace(chunk_id=f"c{i}", source_id="selected", text=text, provenance={})
              for i, text in enumerate(evidence_texts)]
    ids = [chunk.chunk_id for chunk in chunks]

    async def run(query, *, source_ids, condition):
        return {"status": status, "task_results": [{
            "answer": answer, "citations": ids if cited_ids is None else cited_ids,
            "evidence_ids": ids if retrieved_ids is None else retrieved_ids,
        }]}

    pipeline = SimpleNamespace(run=run, source_store=SimpleNamespace(chunks=lambda ids: chunks))
    events = []
    finding, = PipelineReviewEngine(pipeline).run(
        case, [requirement], None, lambda *event: events.append(event),
    )
    return finding, events


@pytest.mark.parametrize("status", ["COMPLETE", "PARTIAL"])
def test_all_missing_slots_clear_evidence_and_emit_payload(status):
    finding, events = _review("retain logs for 180 days", ["Logs appear on the dashboard"], status=status)
    assert finding.verdict == Verdict.NOT_FOUND
    assert finding.evidence == []
    assert [name for name, _ in events] == [
        "task.started", "pipeline.trace", "verdict.slots_missing", "finding.created",
    ]
    assert events[2][1] == {"case_id": "slots-case", "requirement_id": "r1",
                            "missing_slots": ["number:180 days"]}


@pytest.mark.parametrize("status,diagnostic", [("COMPLETE", True), ("PARTIAL", False)])
def test_some_covered_slots_keep_evidence_and_only_downgrade_satisfied(status, diagnostic):
    finding, events = _review('retain logs for 180 days and use "immutable"',
                              ["Logs retained for 180 days"], status=status)
    assert finding.verdict == Verdict.PARTIAL
    assert [e.evidence_id for e in finding.evidence] == ["c0"]
    assert [payload for name, payload in events if name == "verdict.slots_missing"] == (
        [{"case_id": "slots-case", "requirement_id": "r1", "missing_slots": ["literal:immutable"]}]
        if diagnostic else []
    )


@pytest.mark.parametrize("status", ["COMPLETE", "PARTIAL"])
def test_different_quantity_stays_deviates(status):
    finding, events = _review("retain logs for 180 days", ["Logs retained for 90 days"], status=status)
    assert finding.verdict == Verdict.DEVIATES
    assert [e.evidence_id for e in finding.evidence] == ["c0"]
    assert [name for name, _ in events] == [
        "task.started", "pipeline.trace", "verdict.conflict", "finding.created",
    ]


def test_uncited_and_unretrieved_slots_cannot_supply_coverage():
    for cited_ids, retrieved_ids in [(["c0"], ["c0", "c1"]), (["c0", "c1"], ["c0"])]:
        finding, events = _review("retain logs for 180 days",
                                  ["Logs appear on the dashboard", "Logs retained for 180 days"],
                                  cited_ids=cited_ids, retrieved_ids=retrieved_ids)
        assert finding.verdict == Verdict.NOT_FOUND
        assert finding.evidence == []
        assert events[-2][0] == "verdict.slots_missing"


def test_full_coverage_and_no_slots_leave_findings_untouched():
    for requirement, text in [("retain logs for 180 days", "Logs retained for 180 days"),
                               ("Authentication is required", "Authentication uses tokens")]:
        finding, events = _review(requirement, [text])
        assert finding.verdict == Verdict.SATISFIED
        assert len(finding.evidence) == 1
        assert [name for name, _ in events] == ["task.started", "pipeline.trace", "finding.created"]


def test_slot_diagnostic_follows_existing_answer_diagnostic():
    finding, events = _review("Sessions expire within 30 minutes", ["Sessions have an identifier"],
                              answer="Sessions expire within 45 minutes")
    assert finding.verdict == Verdict.NOT_FOUND
    assert [name for name, _ in events] == [
        "task.started", "pipeline.trace", "verdict.answer_inconsistent",
        "verdict.slots_missing", "finding.created",
    ]


@pytest.mark.xfail(strict=False, reason="SUSPECTED DEFECT: value-only slots cannot bind quantities to subjects")
def test_same_value_for_another_subject_is_not_sufficient():
    finding, _ = _review("retain logs for 180 days", ["Invoices retained for 180 days"])
    assert finding.verdict == Verdict.NOT_FOUND


@pytest.mark.xfail(strict=False, reason="SUSPECTED DEFECT: sentence-initial single-word names are ambiguous")
def test_sentence_initial_single_word_entity_is_required():
    assert check_slots("Okta must authenticate users", ["Users authenticate with passwords"]).missing_slots
