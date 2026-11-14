"""Stable JSON and Markdown reports, with timing in a separate artifact."""

import json
from pathlib import Path

from .harness import EvaluationResult
from .metrics import NOTE


def markdown(result: EvaluationResult) -> str:
    lines = ["# Review evaluation", "", NOTE, "", result.results["limitations"], "",
             "Rates include numerator/denominator; macro-F1 averages the four labelled verdicts.", "",
             "| Condition | Run | n | Accuracy | Macro-F1 (4 labels) | Evidence hit | False-DEVIATES | Consistent |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]

    def rate(value):
        return f'{value["rate"]:.4f} ({value["numerator"]}/{value["denominator"]})'

    for condition in result.results["conditions"]:
        name = condition["name"].replace("|", "\\|").replace("\n", " ")
        for run in condition["runs"]:
            m = run["metrics"]
            lines.append(f'| {name} | {run["repeat"]} | {m["n"]} | '
                         f'{rate(m["exact_match_accuracy"])} | {m["macro_f1"]["rate"]:.4f} | '
                         f'{rate(m["evidence_hit_rate"])} | {rate(m["false_deviates_rate"])} | '
                         f'{condition["consistent"]} |')
    return "\n".join(lines) + "\n"


def write_report(result: EvaluationResult, out: str | Path) -> None:
    out = Path(out).resolve()
    repo = Path(__file__).resolve().parents[3]
    for forbidden in (repo / "data", repo / "backend" / "data"):
        if out == forbidden or forbidden in out.parents:
            raise ValueError("Refusing to write inside repository data/ directory")
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in (("evaluation.json", result.results), ("latencies.json", result.latencies)):
        (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "evaluation.md").write_text(markdown(result), encoding="utf-8")
