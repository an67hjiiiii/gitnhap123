from datetime import datetime, timezone
import inspect

from app.review.memory import InMemoryMemoryStore, Suggestion, recall
from app.review.schemas import Decision, Finding, Requirement, Verdict


def requirement(text):
    return Requirement(
        id="req", case_id="case", text=text, origin="USER", order=0
    )


def finding(review=Decision.ACCEPT, edited_text=None):
    return Finding(
        id="finding",
        case_id="case",
        requirement_id="req",
        verdict=Verdict.SATISFIED,
        review=review,
        edited_text=edited_text,
        confidence="L1",
    )


def store_with_clock(ids, ticks=None, cap=500):
    ticks = iter(ticks or [datetime(2025, 1, 1, tzinfo=timezone.utc)] * 20)
    ids = iter(ids)
    return InMemoryMemoryStore(
        cap, clock=lambda: next(ticks), id_factory=lambda: next(ids)
    )


def test_entries_are_isolated_by_owner_and_project():
    store = store_with_clock(["one", "two"])
    store.record_from_finding("alice", "project", requirement("Password length"), finding())
    store.record_from_finding("bob", "project", requirement("Password length"), finding())

    assert [entry.id for entry in store.list_entries("alice")] == ["one"]
    assert [entry.id for entry in store.list_entries("alice", "elsewhere")] == []
    assert store.delete("alice", "two") is False
    assert [entry.id for entry in store.list_entries("bob")] == ["two"]


def test_only_human_decisions_are_recorded():
    store = store_with_clock(["decided"])
    assert store.record_from_finding(
        "alice", "project", requirement("Password"), finding(Decision.NONE)
    ) is None
    assert store.list_entries("alice") == []
    assert store.record_from_finding(
        "alice", "project", requirement("Password"), finding(Decision.ACCEPT)
    ).id == "decided"


def test_reject_is_returned_as_a_negative_signal():
    store = store_with_clock(["reject"])
    store.record_from_finding(
        "alice", "project", requirement("Password length minimum"), finding(Decision.REJECT)
    )

    result = recall(store, "alice", "project", "Password length minimum", threshold=1)
    assert result[0].prior_decision == "REJECT"
    assert "rejected" in result[0].note


def test_edit_recall_surfaces_edited_text():
    store = store_with_clock(["edit"])
    store.record_from_finding(
        "alice", "project", requirement("Password length"),
        finding(Decision.EDIT, "Password must contain 12 characters"),
    )

    result = recall(store, "alice", "project", "Password length", threshold=1)
    assert result[0].edited_text == "Password must contain 12 characters"


def test_bilingual_phrases_are_lexical_not_translated_matches():
    store = store_with_clock(["vietnamese"])
    store.record_from_finding(
        "alice", "project", requirement("Mật khẩu tối thiểu 12 ký tự"), finding()
    )

    # This lexical matcher does not translate Vietnamese to English. Equivalent
    # meanings in different languages therefore need not match.
    assert recall(
        store, "alice", "project", "password at least 12 characters"
    ) == []


def test_eviction_is_oldest_first_with_id_tie_break():
    moment = datetime(2025, 1, 1, tzinfo=timezone.utc)
    store = store_with_clock(["b", "a", "c"], [moment, moment, moment], cap=2)
    for text in ("one", "two", "three"):
        store.record_from_finding("alice", "project", requirement(text), finding())

    assert [entry.id for entry in store.list_entries("alice", "project")] == ["b", "c"]


def test_threshold_and_ranking_are_deterministic():
    moment = datetime(2025, 1, 1, tzinfo=timezone.utc)
    store = store_with_clock(["z", "a", "low"], [moment, moment, moment])
    for text in ("password length", "password length", "password"):
        store.record_from_finding("alice", "project", requirement(text), finding())

    assert recall(store, "alice", "project", "password length extra", threshold=0.8) == []
    results = recall(store, "alice", "project", "password length", threshold=0.5)
    assert [item.entry_id for item in results] == ["a", "z", "low"]
    assert [item.entry_id for item in recall(store, "alice", "project", "password length")] == [
        "a", "z", "low"
    ]


def test_public_recall_api_only_returns_suggestions_and_cannot_confirm():
    assert set(inspect.signature(recall).parameters) == {
        "store", "owner_user_id", "project_key", "requirement_text", "k", "threshold"
    }
    assert not hasattr(Suggestion, "confirmed")
    assert not hasattr(Suggestion, "review")
    assert "decide" not in vars(__import__("app.review.memory", fromlist=["*" ]))
    assert "confirm" not in vars(__import__("app.review.memory", fromlist=["*" ]))
