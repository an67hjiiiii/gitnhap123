"""Explicit experiment configuration and injected, resource-guarded engines."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable

from .guard import InferenceLimitReached, ResourceGuard, RunTimeout
from .harness import Condition, CorpusCase, EvidenceEngine, EvaluationResult, run
from .metrics import score


FLAGS = {"retrieval_policy", "verdict_rules", "router_budget", "project_memory_suggestions"}


def config_hash(config: dict) -> str:
    return sha256(json.dumps(config, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_config(config)
    return config


def validate_config(config):
    if type(config["repeats"]) is not int or config["repeats"] < 1:
        raise ValueError("Positive repeats required")
    if len(config["seeds"]) != config["repeats"] or any(type(s) is not int for s in config["seeds"]):
        raise ValueError("Require one integer seed per repeat")
    conditions = config["conditions"]
    if not conditions or len({c["name"] for c in conditions}) != len(conditions):
        raise ValueError("Require unique conditions")
    if not config["corpus_refs"]:
        raise ValueError("Require corpus references")
    for condition in conditions:
        flags = condition["components"]
        if set(flags) != FLAGS or any(type(v) is not bool for v in flags.values()):
            raise ValueError("Require all four boolean component flags")
        if not condition["definition"] or not condition["engine_id"]:
            raise ValueError("Require condition definition and engine ID")
    by_name = {c["name"]: c["components"] for c in conditions}
    for name, removed in (("C-P", "project_memory_suggestions"), ("C-N", "verdict_rules"),
                          ("C-O", "router_budget")):
        if name in by_name:
            expected = {**by_name["C"], removed: False}
            if not by_name["C"][removed] or by_name[name] != expected:
                raise ValueError("Ablations must remove exactly their declared C component")


@dataclass(frozen=True)
class EngineRegistration:
    """Trusted registry metadata; factory receives case, seed and component flags.

    Returned engines must be pickleable and honor the one-inference run contract.
    Factories must not perform inference or external I/O.
    """
    factory: Callable
    is_fake: bool = False


def _fake_factory(item, seed, components):
    if not components["retrieval_policy"]:
        for requirement in item.requirements:
            requirement.evidence = []
            requirement.status = "NO_EVIDENCE"
    return EvidenceEngine(item, "rules" if components["verdict_rules"] else "legacy")


def fake_registry():
    return {"fake": EngineRegistration(_fake_factory, is_fake=True)}


def build_conditions(config: dict, registry: dict[str, EngineRegistration], guard: ResourceGuard,
                     *, dry_run=True) -> list[Condition]:
    validate_config(config)
    conditions = []
    for spec in deepcopy(config["conditions"]):
        registration = registry[spec["engine_id"]]
        if dry_run and not registration.is_fake:
            from .guard import RealEngineRefused
            raise RealEngineRefused("Dry-run permits fake registry engines only")
        guard.authorize(is_fake=registration.is_fake)

        def factory(item, seed, spec=spec, registration=registration):
            guard.authorize(is_fake=registration.is_fake)
            engine = registration.factory(item, seed, deepcopy(spec["components"]))
            return guard.wrap(engine, is_fake=registration.is_fake)

        conditions.append(Condition(spec["name"], factory))
    return conditions


def load_experiment_corpus(config, base: Path) -> list[CorpusCase]:
    cases = []
    for reference in config["corpus_refs"]:
        path = (base / reference).resolve()
        if base.resolve().parent not in path.parents:
            raise ValueError("Corpus references must remain inside the config directory's parent (fixtures root)")
        cases.extend(CorpusCase.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8")))
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("Require nonempty corpus with unique case IDs")
    return cases


def run_experiment(config, corpus, registry, guard, *, dry_run=True):
    if not corpus or len({c.id for c in corpus}) != len(corpus):
        raise ValueError("Require nonempty corpus with unique case IDs")
    config = deepcopy(config)
    config["execution"] = {"max_inferences": guard.max_inferences,
                           "max_concurrent_inferences": guard.max_concurrent_inferences,
                           "per_run_timeout": guard.per_run_timeout, "dry_run": dry_run}
    conditions = build_conditions(config, registry, guard, dry_run=dry_run)
    digest = config_hash(config)
    payload = {"config": config, "config_hash": digest, "repeats": config["repeats"],
               "limitations": config["definition"]["limitations"], "conditions": [],
               "partial": False, "stop_reason": None, "dry_run": dry_run}
    result = EvaluationResult(payload)
    stopped = False
    for condition, spec in zip(conditions, config["conditions"]):
        entry = {**deepcopy(spec), "config_hash": digest, "runs": [], "consistent": True}
        payload["conditions"].append(entry)
        for repeat, seed in enumerate(config["seeds"]):
            rows = []
            if not stopped:
                for index, item in enumerate(corpus):
                    try:
                        single = run([condition], [item], repeats=1, seed=seed + index)
                    except (InferenceLimitReached, RunTimeout) as exc:
                        payload.update(partial=True, stop_reason=f"{type(exc).__name__}: {exc}")
                        stopped = True
                        break
                    result.latencies.extend({**row, "repeat": repeat} for row in single.latencies)
                    for row in single.results["conditions"][0]["runs"][0]["rows"]:
                        rows.append({**row, "condition": condition.name, "repeat": repeat,
                                     "seed": seed + index, "components": deepcopy(spec["components"]),
                                     "engine_id": spec["engine_id"], "config_hash": digest})
            entry["runs"].append({"repeat": repeat, "rows": rows, "metrics": score(rows),
                                  "partial": len(rows) != sum(len(c.requirements) for c in corpus)})
        entry["consistent"] = all(r["rows"] and not r["partial"] for r in entry["runs"]) and all(
            [(r["case_id"], r["requirement_id"], r["predicted"], r["cited_locators"]) for r in item["rows"]]
            == [(r["case_id"], r["requirement_id"], r["predicted"], r["cited_locators"]) for r in entry["runs"][0]["rows"]]
            for item in entry["runs"])
    payload["inferences"] = guard.inferences
    if payload["partial"]:
        payload["limitations"] += f" PARTIAL RESULTS: {payload['stop_reason']}."
    return result
