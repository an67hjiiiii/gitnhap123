"""Pilot runner for Review Case requirements (conditions A, B0/B, C).

One run per (condition, requirement), fixed order, one inference at a time. It reads ONLY
case_id/title/document/requirements from the pilot file and never opens label files.
Experiment A = source-free direct judgement; B0/B = grounded condition-A pipeline (B0 legacy
verdict, B through the review engine's rules); C = pipeline condition C through the same engine.
Results: one JSON per run plus summary.csv under out_dir. Real providers need
REVIEW_EXPERIMENT_ALLOW_REAL=1; condition C needs the dev profile, set only inside this process.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.evaluation.real_runner import BASELINE_SYSTEM, CountingProvider, parse_baseline

ORDER = ("A", "B", "C")
TOKEN_CAP = 700
CSV_FIELDS = ["condition", "case_id", "requirement_id", "verdict", "b0_verdict", "evidence_ids",
              "citation_valid", "citations_total", "model_calls", "seconds", "output_truncated",
              "output_cap_reached", "task_failed", "failed_code", "status"]
_VERSION_FILES = ("research/worker.py", "research/decomposer.py", "research/obligation_concern_extraction.py",
                  "research/synthesizer.py", "research/vanilla.py", "review_adapters/verdict_rules.py",
                  "review_adapters/slot_check.py", "review_adapters/pipeline_engine.py")


def prompt_rule_version() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256(BASELINE_SYSTEM.encode())
    for name in _VERSION_FILES:
        digest.update((root / name).read_bytes())
    return digest.hexdigest()[:12]


def load_cases(path) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return [{"case_id": c["case_id"], "title": c["title"], "document": c["document"],
             "requirements": [{"id": r["id"], "text": r["text"]} for r in c["requirements"]]}
            for c in raw]


def _git_commit(subpath: str) -> str:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h", "--", subpath], capture_output=True,
                             text=True, cwd=Path(__file__).resolve().parents[3], check=True)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _model_digest(provider) -> str | None:
    if getattr(provider, "name", "") != "ollama":
        return None
    try:
        import urllib.request
        base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as response:
            for item in json.load(response).get("models", []):
                if item.get("name") == provider.model:
                    return str(item.get("digest", ""))[:12]
    except Exception:
        return None
    return None


def citation_stats(pipeline, raw: dict, source_ids: list[str]) -> tuple[int, int]:
    """(valid, total) over distinct citations: retrieved by the task, existing, excerpt inside chunk."""
    from app.review_adapters.citation_check import excerpt_in_chunk
    chunks = {c.chunk_id: c for c in pipeline.source_store.chunks(source_ids)}
    valid = total = 0
    seen = set()
    for task in raw.get("task_results", []):
        retrieved = set(task.get("evidence_ids", []))
        for cid in task.get("citations", []):
            if cid in seen:
                continue
            seen.add(cid)
            total += 1
            chunk = chunks.get(str(cid))
            if cid in retrieved and chunk is not None and excerpt_in_chunk(chunk.text, chunk.text):
                valid += 1
    total += sum(len(t.get("invalid_citations", [])) for t in raw.get("task_results", []))
    return valid, total


def _legacy(raw: dict, evidence) -> str:
    return {"COMPLETE": "SATISFIED" if evidence else "UNDETERMINED", "PARTIAL": "PARTIAL",
            "NO_EVIDENCE": "NOT_FOUND"}.get(raw.get("status"), "UNDETERMINED")


async def run_pilot(*, cases_path, out_dir, conditions=("A",), max_calls=30, max_minutes=10,
                    limit=None, provider=None, c_abort_after=3) -> dict:
    from app.providers.factory import get_provider
    from app.research import pipeline as pm
    from app.retrieval.candidate_index import CandidateIndex
    from app.retrieval.embeddings import make_embedder
    from app.review.schemas import Requirement, ReviewCase
    from app.review_adapters.pipeline_engine import PipelineReviewEngine
    from app.storage.run_store import RunStore
    from app.storage.source_store import SourceStore
    from app.storage.vector_store import InMemoryVectorStore

    conditions = tuple(c for c in ORDER if c in conditions)
    if "C" in conditions:
        os.environ["IMPLEMENTATION_PROFILE"] = "dev"  # this process only; default profile m0 is unchanged
    provider = provider or get_provider(None)
    if provider.name != "fake" and os.getenv("REVIEW_EXPERIMENT_ALLOW_REAL") != "1":
        raise PermissionError("Real provider requires REVIEW_EXPERIMENT_ALLOW_REAL=1")
    cap = getattr(provider, "max_output_tokens", None)
    if provider.name != "fake" and cap != TOKEN_CAP:
        raise ValueError(f"Shared output token cap must be {TOKEN_CAP}, provider has {cap}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases = load_cases(cases_path)
    if limit:
        cases = cases[:limit]
    counter = CountingProvider(provider, max_calls, max_minutes * 60)
    meta = {"model": getattr(provider, "model", None), "provider": provider.name,
            "model_digest": _model_digest(provider), "token_cap": TOKEN_CAP if cap else None,
            "prompt_rule_version": prompt_rule_version(),
            "g_freeze_commit": _git_commit("docs/engineering/g-freeze.md"),
            "code_commit": _git_commit("."), "profile": os.getenv("IMPLEMENTATION_PROFILE")}
    rows, stop_reason = [], None
    started_all = time.monotonic()
    now = datetime.now(timezone.utc)
    c_failed_streak = 0
    c_seen = 0
    for condition in conditions:
        if stop_reason:
            break
        for case in cases:
            if stop_reason:
                break
            with tempfile.TemporaryDirectory(prefix="pilot-") as scratch:
                pipeline = engine = review_case = None
                source_ids: list[str] = []
                if condition != "A":
                    sources = SourceStore(str(Path(scratch) / "sources"))
                    imported = sources.import_text(case["title"], case["document"],
                                                   provenance={"locator": case["case_id"]})
                    source_ids = [imported["source_id"]]
                    dim = int(os.getenv("VECTOR_SIZE", "768"))
                    index = CandidateIndex(sources, InMemoryVectorStore(vector_size=dim),
                                           owner_user_id="pilot", embedder=make_embedder(dim))
                    index.index_source(imported["source_id"])
                    pipeline = pm.ResearchPipeline(sources, RunStore(str(Path(scratch) / "out")),
                                                   candidate_index=index, retrieval_backend="memory")
                    engine = PipelineReviewEngine(pipeline, condition="A" if condition == "B" else "C")
                    review_case = ReviewCase(id=case["case_id"], owner_user_id="pilot", title=case["title"],
                                             request_text=case["document"], source_ids=source_ids,
                                             created_at=now, updated_at=now)
                    raw_holder: dict = {}
                    original_run = pipeline.run

                    async def wrapped(*a, _orig=original_run, _h=raw_holder, **k):
                        _h["raw"] = await _orig(*a, **k)
                        return _h["raw"]

                    pipeline.run = wrapped  # type: ignore[method-assign]  # capture the raw run for B0 and citation stats
                for req in case["requirements"]:
                    if counter.failure or counter.count >= max_calls:
                        stop_reason = counter.failure or f"Call cap {max_calls} reached"
                        break
                    row = await _one(condition, case, req, counter, pipeline, engine, review_case,
                                     source_ids, pm, Requirement, meta, out, raw_holder if engine else None)
                    rows.append(row)
                    if condition == "C":
                        c_seen += 1
                        c_failed_streak = c_failed_streak + 1 if row["task_failed"] else 0
                        if c_seen <= c_abort_after and c_failed_streak >= c_abort_after:
                            stop_reason = f"First {c_abort_after} C requirements all failed"
                            break
    summary = {"meta": meta, "rows": len(rows), "stop_reason": stop_reason, "total_model_calls": counter.count,
               "wall_seconds": round(time.monotonic() - started_all, 1), "conditions": list(conditions)}
    with (out / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


async def _one(condition, case, req, counter, pipeline, engine, review_case, source_ids, pm, Requirement,
               meta, out, raw_holder) -> dict:
    counter.context = {"condition": condition, "requirement_id": req["id"]}
    before = len(counter.calls)
    started = time.monotonic()
    events: list[dict] = []
    verdict, b0, evidence_ids, valid, total = "UNDETERMINED", None, [], None, 0
    status, answer = "COMPLETED", None
    if condition == "A":
        try:
            result = await counter.generate(system=BASELINE_SYSTEM, user=req["text"])
            verdict, answer = parse_baseline(result.text), result.text
        except Exception as exc:
            status = f"ERROR:{type(exc).__name__}"
            events.append({"name": "task.failed", "error_type": type(exc).__name__})
    else:
        requirement = Requirement(id=f"{case['case_id']}:{req['id']}", case_id=case["case_id"], text=req["text"],
                                  origin="USER", confirmed=True, order=0)

        def emit(name, payload=None):
            events.append({"name": name, **(payload or {})})

        with patch.object(pm, "get_provider", return_value=counter):
            findings = await engine.run_async(review_case, [requirement], None, emit)
        finding = findings[0]
        verdict = finding.verdict.value
        evidence_ids = [e.evidence_id for e in finding.evidence]
        raw = (raw_holder or {}).get("raw") or {}
        status = raw.get("status", "NO_RAW")
        if condition == "B":
            b0 = _legacy(raw, finding.evidence if status in {"COMPLETE", "PARTIAL"} else [])
        v, total = citation_stats(pipeline, raw, source_ids)
        valid = round(v / total, 3) if total else None
    calls = [c for c in counter.calls[before:]]
    truncated = sum("OutputTruncatedError" in str(c.get("error")) for c in calls)
    capped = sum(1 for c in calls if (c.get("completion_tokens") or 0) >= TOKEN_CAP)
    failed = [e for e in events if e["name"] == "task.failed"]
    row = {"condition": condition, "case_id": case["case_id"], "requirement_id": req["id"], "verdict": verdict,
           "b0_verdict": b0, "evidence_ids": ";".join(evidence_ids), "citation_valid": valid,
           "citations_total": total, "model_calls": len(calls), "seconds": round(time.monotonic() - started, 2),
           "output_truncated": truncated, "output_cap_reached": capped, "task_failed": bool(failed),
           "failed_code": failed[0].get("error_type") if failed else None, "status": status}
    detail = {**row, "meta": meta, "answer": answer, "events": events,
              "calls": [{k: c.get(k) for k in ("method", "latency_seconds", "prompt_tokens",
                                                "completion_tokens", "error")} for c in calls]}
    (out / f"{condition}_{req['id']}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    return row


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--cases", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--conditions", default="A")
    p.add_argument("--max-calls", type=int, default=30)
    p.add_argument("--max-minutes", type=int, default=10)
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args(argv)
    summary = asyncio.run(run_pilot(cases_path=a.cases, out_dir=a.out, conditions=tuple(a.conditions.split(",")),
                                    max_calls=a.max_calls, max_minutes=a.max_minutes, limit=a.limit))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
