"""Isolated bilingual adversarial corpus; no providers, sockets or file stores."""

import json
from pathlib import Path

import pytest

from app.review_adapters.verdict_rules import CONFLICTS, UNRELATED, assess, extract_claims


PAIRS = json.loads((Path(__file__).parent / "fixtures/eval_fp/pairs.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")


def prediction(pair):
    hint = assess(pair["requirement"], [pair["evidence"]]).verdict_hint
    return CONFLICTS if hint == "DEVIATES" else hint


def pair_parameter(pair):
    marks = []
    if pair.get("known_limitation"):
        marks.append(pytest.mark.xfail(strict=False, reason=pair["known_limitation"]))
    return pytest.param(pair, id=pair["id"], marks=marks)


@pytest.mark.parametrize("pair", [pair_parameter(pair) for pair in PAIRS])
def test_adversarial_pair(pair):
    actual = prediction(pair)
    if pair["expected"] != CONFLICTS:
        assert actual != CONFLICTS, "False DEVIATES"
    assert actual == pair["expected"]


@pytest.mark.parametrize("pair", PAIRS, ids=lambda pair: pair["id"])
def test_pair_is_deterministic(pair):
    assert assess(pair["requirement"], [pair["evidence"]]) == assess(
        pair["requirement"], [pair["evidence"]]
    )


def test_corpus_coverage():
    assert len({pair["id"] for pair in PAIRS}) == len(PAIRS)
    assert sum(pair["expected"] != CONFLICTS for pair in PAIRS) >= 40
    assert sum(pair["expected"] == CONFLICTS for pair in PAIRS) >= 15
    assert {pair["expected"] for pair in PAIRS} == {"SATISFIES", CONFLICTS, UNRELATED}


@pytest.mark.parametrize("text", [None, "", "🛡️ 日本語 tiếng Việt", "x" * 100_000, 42, {}, []],
                         ids=["none", "empty", "unicode", "long", "integer", "mapping", "list"])
def test_empty_and_odd_text_is_unknown(text):
    assert extract_claims(text) == []
    assert assess(text, [None, "", {"excerpt": text}]).verdict_hint == UNRELATED
    assert assess("logs 180 days", [text]).verdict_hint == UNRELATED


def test_missing_evidence_collection_is_unknown():
    assert assess("logs 180 days", None).verdict_hint == UNRELATED
