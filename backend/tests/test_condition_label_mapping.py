import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.evaluation.experiment import EngineRegistration, build_conditions, fake_registry, load_config
from app.evaluation.guard import ResourceGuard
from app.evaluation.harness import CONDITION_FLAG_MAP, condition_definition, default_conditions, load_corpus, run
from app.evaluation import real_runner


BACKEND = Path(__file__).resolve().parents[1]
EXPERIMENT = BACKEND / "tests/fixtures/experiment/experiment.json"


def test_mapping_covers_all_emitted_labels_and_actual_factory_flags():
    config = load_config(EXPERIMENT)
    labels = {item.name for item in default_conditions()} | {item["name"] for item in config["conditions"]} | {"A", "B0", "B", "C"}
    assert labels <= CONDITION_FLAG_MAP.keys()
    received = []
    def factory(item, seed, flags):
        received.append(deepcopy(flags))
        return fake_registry()["fake"].factory(item, seed, flags)
    registry = {"fake": EngineRegistration(factory, is_fake=True)}
    with ResourceGuard() as guard:
        conditions = build_conditions(config, registry, guard)
        item = load_corpus(BACKEND / "tests/fixtures/eval")[0]
        for condition in conditions:
            condition.factory(item.model_copy(deep=True), 0)
    expected = {spec["name"]: spec["components"] for spec in config["conditions"]}
    assert received == [expected[c.name] for c in conditions]
    for name, flags in expected.items():
        assert CONDITION_FLAG_MAP[name]["harness_flags"] == flags
    for name in ("A", "B0", "B", "C"):
        assert CONDITION_FLAG_MAP[name]["pipeline_condition"] == (None if name == "A" else "A")


def test_mapping_rejects_unknown_and_ablation_flags_differ_once():
    with pytest.raises(ValueError, match="Unknown"):
        condition_definition("not-a-condition")
    config = load_config(EXPERIMENT)
    by_name = {condition["name"]: condition["components"] for condition in config["conditions"]}
    for name, removed in (("C-P", "project_memory_suggestions"), ("C-N", "verdict_rules"), ("C-O", "router_budget")):
        assert sum(by_name["C"][key] != by_name[name][key] for key in by_name["C"]) == 1
        assert by_name[name] == CONDITION_FLAG_MAP[name]["harness_flags"]


def test_harness_ablation_names_are_not_pipeline_ablations():
    for name in ("C-P", "C-N", "C-O"):
        entry = CONDITION_FLAG_MAP[name]
        assert entry["pipeline_condition"] is None and entry["name_collision_with_pipeline"] is True


def test_json_and_markdown_outputs_have_condition_and_hash():
    item = load_corpus(BACKEND / "tests/fixtures/eval")[0]
    harness_result = run(default_conditions()[:1], [item], repeats=1)
    assert len(harness_result.results["config_hash"]) == 64
    assert harness_result.results["conditions"][0]["condition"] == "A_baseline_fake"
    assert "Config hash:" in __import__("app.evaluation.report", fromlist=["markdown"]).markdown(harness_result)

    config = load_config(EXPERIMENT)
    with ResourceGuard() as guard:
        experiment_result = __import__("app.evaluation.experiment", fromlist=["run_experiment"]).run_experiment(
            config, [item], fake_registry(), guard)
    payload = experiment_result.results
    assert len(payload["config_hash"]) == 64
    assert all(condition["condition"] == condition["name"] for condition in payload["conditions"])
    assert all(condition["config_hash"] == payload["config_hash"] for condition in payload["conditions"])

    real_result = real_runner.empty_result(real_runner.load_corpus(), dry_run=True,
        max_invocations=24, max_minutes=60)
    assert len(real_result["config_hash"]) == 64
    assert all(entry["condition"] == name for name, entry in real_result["conditions"].items())
    for entry in real_result["conditions"].values():
        entry["metrics"] = real_runner.score(entry["rows"])
    assert "Config hash:" in real_runner.markdown(real_result)
