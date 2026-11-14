from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "golden_s4"
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("golden_s4_regen", FIXTURES / "_regen.py")
assert SPEC is not None and SPEC.loader is not None
REGEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGEN)


def read_doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_expected(path: Path):
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    canonical = json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert raw == canonical, f"{path.relative_to(FIXTURES)} is not sorted, canonical JSON"
    return parsed


def scenario_actual(name: str, old: str, new: str):
    return {
        "diff.json": REGEN.normalized_diff(old, new),
        "checks.json": REGEN.normalized_checks(new),
        "spec_change.json": REGEN.normalized_spec_change(name, old, new),
    }


@pytest.mark.parametrize(
    "scenario_dir",
    sorted(p for p in FIXTURES.iterdir() if p.is_dir() and (p / "old.json").is_file()),
)
def test_golden_scenario_outputs_are_exact_and_deterministic(scenario_dir: Path):
    name = scenario_dir.name
    old, new = read_doc(scenario_dir / "old.json"), read_doc(scenario_dir / "new.json")
    first = scenario_actual(name, old, new)
    second = scenario_actual(name, old, new)
    assert first == second, f"{name}: recomputation changed between identical runs"

    for filename, actual in first.items():
        expected = read_expected(scenario_dir / "expected" / filename)
        assert actual == expected, (
            f"Golden mismatch for {name}/{filename}\n"
            f"expected:\n{json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True)}\n"
            f"actual:\n{json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True)}"
        )


@pytest.mark.xfail(
    strict=False,
    reason="SUSPECTED DEFECT: request body media type changes are absent from OpenAPI diff output",
)
def test_content_type_change_is_reported_by_diff():
    old = read_doc(FIXTURES / "content_type_change" / "old.json")
    new = read_doc(FIXTURES / "content_type_change" / "new.json")
    changes = REGEN.normalized_diff(old, new)["changes"]
    assert any(change["kind"] == "REQUEST_BODY_CONTENT_TYPE_CHANGED" for change in changes)
