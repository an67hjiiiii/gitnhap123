"""Offline experiment contracts; no provider or storage connections."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier

import pytest

from app.evaluation.experiment import (
    EngineRegistration, build_conditions, config_hash, fake_registry, load_config,
    load_experiment_corpus, run_experiment,
)
from app.evaluation.guard import (
    InferenceLimitReached, RealEngineRefused, ResourceGuard, RunTimeout,
)


BACKEND = Path(__file__).resolve().parents[1]
CONFIG = BACKEND / "tests" / "fixtures" / "experiment" / "experiment.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.delenv("REVIEW_EXPERIMENT_ALLOW_REAL", raising=False)


class EchoEngine:
    def run(self, case, requirements, budget, emit):
        return [case]


class PidEngine:
    def run(self, case, requirements, budget, emit):
        return [os.getpid()]


class BlockedEngine:
    def run(self, case, requirements, budget, emit):
        from threading import Event
        Event().wait()


@pytest.mark.parametrize("real,opt_in,allowed", [(False, False, False), (True, False, False),
                                                (False, True, False), (True, True, True)])
def test_real_requires_both_opt_ins(monkeypatch, real, opt_in, allowed):
    if opt_in:
        monkeypatch.setenv("REVIEW_EXPERIMENT_ALLOW_REAL", "1")
    with ResourceGuard(real=real) as guard:
        if allowed:
            guard.authorize(is_fake=False)
        else:
            with pytest.raises(RealEngineRefused):
                guard.wrap(EchoEngine(), is_fake=False)
        assert guard.inferences == 0


def test_dry_run_refuses_before_factory(monkeypatch):
    config = load_config(CONFIG)
    monkeypatch.setenv("REVIEW_EXPERIMENT_ALLOW_REAL", "1")
    def forbidden(*args):
        pytest.fail("Factory must not run before authorization")
    with ResourceGuard(real=True) as guard:
        with pytest.raises(RealEngineRefused, match="Dry-run"):
            build_conditions(config, {"fake": EngineRegistration(forbidden)}, guard)


def test_concurrency_uses_one_worker_and_counts_exactly():
    barrier = Barrier(4)
    with ResourceGuard(max_inferences=3) as guard:
        engine = guard.wrap(PidEngine(), is_fake=True)
        def call():
            barrier.wait(timeout=10)
            return engine.run(None, [], None, lambda *_: None)[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(call) for _ in range(4)]
            pids, rejected = [], 0
            for future in futures:
                try:
                    pids.append(future.result(timeout=40))
                except InferenceLimitReached:
                    rejected += 1
        assert len(set(pids)) == 1
        assert len(pids) == guard.inferences == 3
        assert rejected == 1


def test_timeout_terminates_worker():
    with ResourceGuard(per_run_timeout=0.2) as guard:
        with pytest.raises(RunTimeout):
            guard.wrap(BlockedEngine(), is_fake=True).run(None, [], None, lambda *_: None)
        assert guard.inferences == 1
        assert guard._process is None


@pytest.mark.parametrize("kwargs", [{"max_inferences": -1}, {"max_inferences": True},
                                   {"per_run_timeout": 0}, {"per_run_timeout": float("nan")}])
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        ResourceGuard(**kwargs)


def test_hash_and_ablations():
    config = load_config(CONFIG)
    reordered = json.loads(json.dumps(config, sort_keys=True))
    assert config_hash(config) == config_hash(reordered)
    changed = deepcopy(config)
    changed["seeds"][0] += 1
    assert config_hash(config) != config_hash(changed)
    assert len(config_hash(config)) == 64
    conditions = {c["name"]: c for c in config["conditions"]}
    for name, flag in (("H-noMemory", "project_memory_suggestions"), ("H-noRules", "verdict_rules"),
                       ("H-noRouter", "router_budget")):
        assert [key for key, value in conditions[name]["components"].items()
                if value != conditions["C"]["components"][key]] == [flag]
        assert conditions[name]["components"][flag] is False


def test_partial_results_and_metadata():
    config = load_config(CONFIG)
    corpus = load_experiment_corpus(config, CONFIG.parent)
    with ResourceGuard(max_inferences=1) as guard:
        result = run_experiment(config, corpus, fake_registry(), guard)
    payload = result.results
    assert payload["partial"] and payload["inferences"] == 1
    assert "InferenceLimitReached" in payload["stop_reason"]
    assert len(payload["conditions"]) == 7
    rows = payload["conditions"][0]["runs"][0]["rows"]
    assert len(rows) == len(corpus[0].requirements)
    for row in rows:
        assert row["condition"] == "A" and row["repeat"] == 0
        assert row["engine_id"] == "fake"
        assert row["components"] == config["conditions"][0]["components"]
        assert row["config_hash"] == config_hash(payload["config"])
    assert all(run["partial"] for c in payload["conditions"] for run in c["runs"])


def test_injected_factory_receives_flags_and_repeat_seeds():
    config = load_config(CONFIG)
    corpus = load_experiment_corpus(config, CONFIG.parent)[:1]
    received = []
    default = fake_registry()["fake"].factory
    def factory(item, seed, components):
        received.append((seed, deepcopy(components)))
        return default(item, seed, components)
    registry = {"fake": EngineRegistration(factory, is_fake=True)}
    with ResourceGuard() as guard:
        result = run_experiment(config, corpus, registry, guard)
    assert received == [(seed, spec["components"]) for spec in config["conditions"]
                        for seed in config["seeds"]]
    assert not result.results["partial"]
    assert all(c["consistent"] for c in result.results["conditions"])
    assert result.results["inferences"] == 21


def test_dry_run_end_to_end(tmp_path):
    out = tmp_path / "report"
    completed = subprocess.run([sys.executable, str(BACKEND / "scripts" / "run_experiment.py"),
                                "--dry-run", "--out", str(out)], cwd=BACKEND,
                               env=os.environ.copy(), capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads((out / "evaluation.json").read_text(encoding="utf-8"))
    assert not payload["partial"] and payload["dry_run"]
    assert payload["inferences"] == 7 * 3 * 15
    assert len(payload["conditions"]) == 7
    assert all(len(c["runs"]) == 3 and c["consistent"] for c in payload["conditions"])
    assert "Accuracy" in completed.stdout and "False-DEVIATES" in completed.stdout
    assert "(0/" in completed.stdout
    assert "raw counts" in (out / "evaluation.md").read_text(encoding="utf-8")
    assert len(json.loads((out / "latencies.json").read_text())) == 315


@pytest.mark.parametrize("arguments", [["--real"], ["--max-inferences", "-1"]])
def test_cli_refusal(arguments, tmp_path):
    completed = subprocess.run([sys.executable, str(BACKEND / "scripts" / "run_experiment.py"),
                                *arguments, "--out", str(tmp_path / "unused")], cwd=BACKEND,
                               env=os.environ.copy(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 2
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("relative", ["data", "data/nested", "backend/data"])
def test_cli_refuses_repo_data_without_writing(relative, capsys):
    spec = importlib.util.spec_from_file_location("experiment_cli", BACKEND / "scripts" / "run_experiment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit) as error:
        module.main(["--out", str(BACKEND.parent / relative)])
    assert error.value.code == 2
    assert "Refusing" in capsys.readouterr().err
