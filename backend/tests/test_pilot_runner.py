import asyncio
import csv
import json

from app.evaluation import pilot_runner

CASES = [{
    "case_id": "T1", "title": "Policy", "label": "SECRET",
    "document": "Passwords must have at least 12 characters. Sessions expire after 30 minutes.",
    "requirements": [{"id": "T1-R1", "text": "Passwords must have at least 12 characters.", "expected": "SATISFIED"},
                     {"id": "T1-R2", "text": "Sessions expire after 30 minutes."}],
}]


def test_runner_fake_provider_runs_a_and_b_and_writes_results(tmp_path, sf1_fake_provider_env, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(CASES), encoding="utf-8")
    out = tmp_path / "res"
    summary = asyncio.run(pilot_runner.run_pilot(cases_path=cases, out_dir=out, conditions=("B", "A"),
                                                 max_calls=10, max_minutes=1))
    assert summary["rows"] == 4 and summary["stop_reason"] is None
    rows = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert [r["condition"] for r in rows] == ["A", "A", "B", "B"]  # fixed order regardless of argument order
    assert all(int(r["model_calls"]) >= 1 for r in rows)
    detail = json.loads((out / "B_T1-R1.json").read_text(encoding="utf-8"))
    assert detail["meta"]["prompt_rule_version"] and "b0_verdict" in detail
    assert "SECRET" not in (out / "B_T1-R1.json").read_text(encoding="utf-8")  # labels never read


def test_runner_stops_at_call_cap(tmp_path, sf1_fake_provider_env, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(CASES), encoding="utf-8")
    summary = asyncio.run(pilot_runner.run_pilot(cases_path=cases, out_dir=tmp_path / "r", conditions=("A",),
                                                 max_calls=1, max_minutes=1))
    assert summary["rows"] == 1 and "cap" in summary["stop_reason"]
