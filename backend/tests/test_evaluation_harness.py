"""Offline evaluation math, repeatability, ablations and CLI contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import random
import subprocess
import sys

import pytest

from app.evaluation.harness import Condition, default_conditions, load_corpus, run
from app.evaluation.metrics import LABELS, NOTE, score
from app.evaluation.report import markdown, write_report
from app.review.engine import FakeReviewEngine

CORPUS = Path(__file__).parent / "fixtures" / "eval"
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch, sf1_vector_store):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


def row(expected, predicted, expected_locators=None, cited_locators=None):
    return dict(expected=expected, predicted=predicted, expected_locators=expected_locators or [],
                cited_locators=cited_locators or [])


def test_hand_computed_metrics_and_confusion():
    rows = [row("SATISFIED", "SATISFIED", ["p1", "alternate"], ["alternate"]),
            row("SATISFIED", "DEVIATES", ["p2"], ["p20"]),
            row("PARTIAL", "SATISFIED", ["p3"], []),
            row("DEVIATES", "DEVIATES", ["p4"], ["p4"]),
            row("NOT_FOUND", "NOT_FOUND"), row("NOT_FOUND", "PARTIAL")]
    m = score(rows)
    assert m["n"] == 6
    assert m["exact_match_accuracy"] == {"numerator": 3, "denominator": 6, "rate": .5}
    assert m["evidence_hit_rate"] == {"numerator": 2, "denominator": 4, "rate": .5}
    assert m["false_deviates_rate"] == {"numerator": 1, "denominator": 5, "rate": .2}
    expected = {"SATISFIED": (1, 1, 1, .5, .5, .5),
                "PARTIAL": (0, 1, 1, 0, 0, 0),
                "DEVIATES": (1, 1, 0, .5, 1, 2/3),
                "NOT_FOUND": (1, 0, 1, 1, .5, 2/3)}
    for label, (tp, fp, fn, precision, recall, f1) in expected.items():
        v = m["per_verdict"][label]
        assert (v["tp"], v["fp"], v["fn"], v["support"]) == (tp, fp, fn, tp + fn)
        for name, value in (("precision", precision), ("recall", recall), ("f1", f1)):
            assert v[name]["rate"] == pytest.approx(value)
            assert "numerator" in v[name] and "denominator" in v[name]
    assert m["macro_f1"]["rate"] == pytest.approx(11/24)
    assert m["confusion_matrix"] == {
        "SATISFIED": dict(zip(LABELS, [1, 0, 1, 0])),
        "PARTIAL": dict(zip(LABELS, [1, 0, 0, 0])),
        "DEVIATES": dict(zip(LABELS, [0, 0, 1, 0])),
        "NOT_FOUND": dict(zip(LABELS, [0, 1, 0, 1])),
    }
    assert m["note"] == NOTE


def test_empty_and_abstained_predictions_are_counted():
    empty = score([])
    assert empty["n"] == 0
    assert empty["macro_f1"]["rate"] == 0
    assert empty["evidence_hit_rate"] == {"numerator": 0, "denominator": 0, "rate": 0}
    abstained = score([row("SATISFIED", "UNDETERMINED"), row("PARTIAL", "SKIPPED_BUDGET")])
    assert abstained["per_verdict"]["SATISFIED"]["fn"] == 1
    assert abstained["confusion_matrix"]["PARTIAL"]["SKIPPED_BUDGET"] == 1
    assert abstained["exact_match_accuracy"]["denominator"] == 2
    with pytest.raises(ValueError):
        score([row("UNKNOWN", "SATISFIED")])
    with pytest.raises(ValueError):
        score([row("SATISFIED", "TYPO")])


def test_corpus_coverage_and_gt1_provenance():
    corpus = load_corpus(CORPUS)
    bilingual = [c for c in corpus if c.kind == "requirement_review"]
    assert len(bilingual) >= 12
    assert {r.expected for c in bilingual for r in c.requirements} == set(LABELS)
    assert any("Mật khẩu" in r.text for c in bilingual for r in c.requirements)
    specs = [c for c in corpus if c.kind == "spec_change"]
    assert len(specs) == 3
    for item in specs:
        scenario = item.id.removeprefix("spec_")
        golden = CORPUS.parent / "golden_s4" / scenario
        assert item.sources["old"] == (golden / "old.json").read_text(encoding="utf-8")
        assert item.sources["new"] == (golden / "new.json").read_text(encoding="utf-8")
        label = json.loads((golden / "expected" / "spec_change.json").read_text(encoding="utf-8"))["findings"][0]
        assert item.requirements[0].expected == label["verdict"]
        assert item.requirements[0].text == label["requirement_text"]
        assert len(item.requirements[0].expected_locators) == len(label["evidence_ids"])


def test_repeats_are_deterministic_with_separate_latency():
    corpus = load_corpus(CORPUS)
    before = [item.model_dump() for item in corpus]
    first = run(default_conditions(), corpus, repeats=3, seed=41)
    second = run(default_conditions(), corpus, repeats=3, seed=41)
    assert first == second
    assert first.results == second.results
    assert len(first.latencies) == 5 * 3 * len(corpus)
    assert all(t["seconds"] >= 0 for t in first.latencies)
    second.latencies.clear()
    assert first == second
    assert "seconds" not in json.dumps(first.results)
    for condition in first.results["conditions"]:
        assert condition["consistent"]
        assert all(r["metrics"]["n"] == 15 for r in condition["runs"])
    assert before == [item.model_dump() for item in corpus]


def test_factory_seed_and_isolation():
    corpus = load_corpus(CORPUS)[:2]
    seeds = []

    def factory(item, seed):
        seeds.append(seed)
        item.sources.clear()
        return FakeReviewEngine(skip_budget=random.Random(seed).choice([True, False]), delay_ms=0)

    result = run([Condition("seeded", factory)], corpus, repeats=3, seed=9)
    assert seeds == [9, 10] * 3
    assert result.results["conditions"][0]["consistent"]
    assert all(item.sources for item in corpus)


@pytest.mark.parametrize("status,expected", [("COMPLETE", "UNDETERMINED"),
                                           ("PARTIAL", "PARTIAL"), ("NO_EVIDENCE", "NOT_FOUND")])
def test_legacy_mapping_without_evidence(status, expected):
    item = load_corpus(CORPUS)[0].model_copy(deep=True)
    item.requirements[0].evidence = []
    item.requirements[0].status = status
    condition = next(c for c in default_conditions() if c.name == "C_minus_rules")
    result = run([condition], [item], repeats=1)
    assert result.results["conditions"][0]["runs"][0]["rows"][0]["predicted"] == expected


def test_rules_ablation_and_naive_safety():
    result = run(default_conditions(), load_corpus(CORPUS), repeats=1)
    by_name = {c["name"]: c["runs"][0] for c in result.results["conditions"]}
    rules = by_name["C_verdict_rules"]["metrics"]["false_deviates_rate"]
    naive = by_name["naive_overlap"]["metrics"]["false_deviates_rate"]
    assert rules["rate"] <= naive["rate"]
    assert rules["numerator"] == 0
    assert naive["numerator"] > 0
    assert by_name["C_minus_rules"]["metrics"]["per_verdict"]["DEVIATES"]["tp"] == 0
    assert by_name["C_verdict_rules"]["metrics"]["per_verdict"]["DEVIATES"]["tp"] == 3
    spec_rows = [r for r in by_name["D_spec_change"]["rows"] if r["case_id"].startswith("spec_")]
    assert all(r["expected"] == r["predicted"] for r in spec_rows)
    assert all(not r["expected_locators"] or r["expected_locators"] == r["cited_locators"] for r in spec_rows)


@pytest.mark.parametrize("repeats", [0, -1])
def test_invalid_repeat_count(repeats):
    with pytest.raises(ValueError):
        run(default_conditions(), load_corpus(CORPUS), repeats=repeats)


def test_invalid_corpus_and_conditions(tmp_path):
    with pytest.raises(ValueError):
        load_corpus(tmp_path)
    item = load_corpus(CORPUS)[0]
    (tmp_path / "cases.json").write_text(json.dumps([item.model_dump(), item.model_dump()]), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_corpus(tmp_path)
    conditions = default_conditions()
    with pytest.raises(ValueError, match="Duplicate condition"):
        run([conditions[0], conditions[0]], [item])


def test_missing_findings_fail_loudly():
    class EmptyEngine(FakeReviewEngine):
        def run(self, case, requirements, budget, emit):
            return []
    with pytest.raises(ValueError, match="exactly one"):
        run([Condition("empty", lambda item, seed: EmptyEngine(delay_ms=0))], load_corpus(CORPUS))


def test_reports_and_cli_smoke(tmp_path):
    command = [sys.executable, str(BACKEND / "scripts" / "run_eval.py"),
               "--conditions", "C_verdict_rules,C_minus_rules", "--repeats", "2", "--seed", "7",
               "--out", str(tmp_path / "report")]
    completed = subprocess.run(command, cwd=BACKEND, env=os.environ.copy(), capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    output = tmp_path / "report"
    payload = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    assert payload["seed"] == 7 and payload["repeats"] == 2
    assert [c["name"] for c in payload["conditions"]] == ["C_verdict_rules", "C_minus_rules"]
    assert len(json.loads((output / "latencies.json").read_text())) == 2 * 2 * 15
    text = (output / "evaluation.md").read_text(encoding="utf-8")
    assert "False-DEVIATES" in text and NOTE in text and "| 15 |" in text
    result = run(default_conditions()[:1], load_corpus(CORPUS), repeats=1)
    write_report(result, tmp_path / "direct")
    assert (tmp_path / "direct" / "evaluation.md").read_text(encoding="utf-8") == markdown(result)


@pytest.mark.parametrize("relative", ["data", "data/nested", "backend/data", "backend/data/nested"])
def test_report_refuses_repository_data(relative):
    result = run(default_conditions()[:1], load_corpus(CORPUS), repeats=1)
    with pytest.raises(ValueError, match="Refusing"):
        write_report(result, BACKEND.parent / relative)


@pytest.mark.parametrize("arguments", [["--conditions", "unknown"], ["--repeats", "0"]])
def test_cli_rejects_invalid_arguments(arguments, tmp_path):
    completed = subprocess.run([sys.executable, str(BACKEND / "scripts" / "run_eval.py"),
                                *arguments, "--out", str(tmp_path / "unused")],
                               cwd=BACKEND, env=os.environ.copy(), capture_output=True, text=True)
    assert completed.returncode == 2
    assert not (tmp_path / "unused").exists()
