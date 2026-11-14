"""Deterministic answer checks with no provider, database or storage access."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.review_adapters.verdict_rules import AnswerCheck, check_answer


PAIRS = json.loads((Path(__file__).parent / "fixtures/eval_fp/answer_pairs.json").read_text(
    encoding="utf-8",
))


@pytest.fixture(autouse=True)
def fake_provider(sf1_fake_provider_env):
    pass


@pytest.mark.parametrize("pair", PAIRS, ids=lambda pair: pair["id"])
def test_answer_pair(pair):
    result = check_answer(pair["requirement"], pair["answer"], pair["evidence"])
    assert isinstance(result, AnswerCheck)
    assert result.status == pair["expected"]
    assert bool(result.notes) == (result.status == "UNSUPPORTED_CLAIM")
    assert result == check_answer(pair["requirement"], pair["answer"], pair["evidence"])


@pytest.mark.parametrize("value", [None, "", 42, {}, [], "🛡 日本語", "x" * 100_000],
                         ids=["none", "empty", "integer", "mapping", "list", "unicode", "long"])
def test_empty_and_odd_inputs(value):
    requirement = "Sessions expire within 30 minutes"
    assert check_answer(value, requirement, [requirement]).status == "UNKNOWN"
    assert check_answer(requirement, value, [requirement]).status == "UNKNOWN"
    assert check_answer(requirement, requirement, [None, {"excerpt": value}, value]).status in {
        "UNKNOWN", "CONSISTENT",
    }


@pytest.mark.parametrize("number", ["3:00", "03:00", "30:00", "3:00:00", "3,0,0", "3.0.0", "-3", "+3"])
def test_malformed_and_signed_values_are_distinct(number):
    text = "Sessions expire within 30 minutes"
    result = check_answer(text, f"Sessions expire within {number} minutes", [text])
    assert result.status == "UNSUPPORTED_CLAIM"
    assert number in result.notes[0]


@pytest.mark.parametrize("wrapper", [lambda s: s, lambda s: {"excerpt": s},
                                    lambda s: SimpleNamespace(excerpt=s)])
def test_supported_evidence_item_shapes_and_one_shot_iterables(wrapper):
    text = "Sessions expire within 30 minutes"
    result = check_answer(text, "Sessions expire within 3:00 minutes", iter([wrapper(text)]))
    assert result.status == "UNSUPPORTED_CLAIM"


@pytest.mark.parametrize("evidence", [None, [], [None], [{"excerpt": None}], [SimpleNamespace()]])
def test_missing_evidence_is_unknown(evidence):
    assert check_answer("Sessions expire within 30 minutes", "Sessions expire within 3:00 minutes",
                        evidence) == AnswerCheck("UNKNOWN", [])


def test_corpus_contains_bilingual_consistent_variants_and_both_real_cases():
    assert len({pair["id"] for pair in PAIRS}) == len(PAIRS)
    assert sum(pair["expected"] == "CONSISTENT" for pair in PAIRS) >= 10
    assert {"real-session-time", "real-extra-channel"} <= {pair["id"] for pair in PAIRS}


def test_multiple_unsupported_claims_keep_stable_note_order_without_mutation():
    requirement = "Incident notifications must be sent by email within 30 minutes"
    evidence = [{"excerpt": requirement}]
    answer = "Incident notifications must be sent by email within 3:00 minutes. " \
             "Incident notifications must be sent by email and SMS."
    first = check_answer(requirement, answer, evidence)
    assert first.status == "UNSUPPORTED_CLAIM"
    assert len(first.notes) == 2
    assert "3:00" in first.notes[0] and "SMS" in first.notes[1]
    assert first == check_answer(requirement, answer, evidence)
    assert evidence == [{"excerpt": requirement}]


def test_chained_list_checks_each_extra_token():
    requirement = "Incident notifications must be sent by email"
    answer = requirement + " and Slack and SMS."
    result = check_answer(requirement, answer, [requirement + " and Slack."])
    assert result.status == "UNSUPPORTED_CLAIM"
    assert len(result.notes) == 1 and "SMS" in result.notes[0]


@pytest.mark.parametrize("excerpt", ["The manual quotes 'SMS'", "For example SMS is available"])
def test_channel_present_anywhere_in_an_excerpt_is_not_absent(excerpt):
    requirement = "Incident notifications must be sent by email"
    result = check_answer(requirement, requirement + " and SMS.", [requirement, excerpt])
    assert result.status == "CONSISTENT"
