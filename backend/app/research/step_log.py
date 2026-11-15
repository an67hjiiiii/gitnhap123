"""Per-step measurement of a research run (opt-in: set STEP_LOG_DIR). Writes one JSON file per run; read-only."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_COUNTERS = ("input_tokens", "output_tokens", "llm_calls", "failed_llm_attempts", "retrieved_chunks", "selected_chunks")


def steps_from_marks(marks: list[dict]) -> list[dict]:
    """Each mark is taken when a stage event is emitted, so a step is the delta since the previous mark."""
    steps, prev = [], {"t": 0.0, **{k: 0 for k in _COUNTERS}}
    for mark in marks:
        step = {"stage": mark["stage"], "seconds": round(mark["t"] - prev["t"], 3)}
        for key in _COUNTERS:
            step[key] = mark[key] - prev[key]
        step["retry_or_degrade"] = step["failed_llm_attempts"] > 0 or "degrad" in mark["stage"] or "retry" in mark["stage"]
        steps.append(step)
        prev = mark
    return steps


def write_step_log(run_id: str, condition: str, query: str, status: str | None, marks: list[dict], metrics) -> None:
    directory = os.getenv("STEP_LOG_DIR", "").strip()
    if not directory:
        return
    try:
        Path(directory).mkdir(parents=True, exist_ok=True)
        payload = {"run_id": run_id, "condition": condition, "query": query, "status": status,
                   "totals": {k: getattr(metrics, k, None) for k in _COUNTERS}, "steps": steps_from_marks(marks)}
        (Path(directory) / f"{run_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # measurement must never affect a run
        logging.getLogger(__name__).exception("could not write step log")
