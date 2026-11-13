import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.types import Concern, Obligation, Task, TaskPlan
from app.research.decomposer import canonicalize_task_plan, detect_domains
from app.research.plan_verification import verify_task_plan


def test_detect_domains_golden_table():
    fixture = Path(__file__).parent / "fixtures" / "sf2" / "detect_domains.golden.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(cases) >= 15
    for case in cases:
        assert detect_domains(case["request"]) == case["domains"], case["request"]


@pytest.mark.parametrize("request_text,expected", [
    ("Review API then database", ["T1"]),
    ("Review API and database", []),
])
def test_canonicalize_order_gate(request_text, expected):
    plan = TaskPlan(request_text, tasks=[
        Task("T1", "Review API", "api_architecture"),
        Task("T2", "Review database", "database", depends_on=["T1"]),
    ])
    result = canonicalize_task_plan(plan)
    assert result.tasks[1].depends_on == expected


def test_canonicalize_preserves_invalid_graph_for_common_verifier():
    plan = TaskPlan("Review API", tasks=[Task("T1", "Review API", "api_architecture", depends_on=["missing"])])
    result = canonicalize_task_plan(plan)
    assert result.tasks[0].depends_on == ["missing"]
    assert not verify_task_plan(result).valid


@pytest.mark.parametrize("first", ["decomposer", "plan_verification"])
def test_planning_module_import_orders_in_separate_processes(first):
    backend = Path(__file__).resolve().parents[1]
    second = "plan_verification" if first == "decomposer" else "decomposer"
    for order in ((first, second),):
        code = f"import app.research.{order[0]}; import app.research.{order[1]}"
        completed = subprocess.run([sys.executable, "-c", code], cwd=backend, timeout=60, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr


def test_verify_complete_lexical_coverage():
    plan = TaskPlan("Review API", obligations=[Obligation("O1", "Review API response")], tasks=[Task("T1", "Review API response", "api_architecture")])
    report = verify_task_plan(plan)
    assert report.valid
    assert report.covered_obligations == ("O1",)


def test_verify_missing_required_obligation():
    plan = TaskPlan("Review API", obligations=[Obligation("O1", "Review API response")], tasks=[Task("T1", "Review database schema", "database")])
    report = verify_task_plan(plan)
    assert not report.valid
    assert report.missing_required_obligations == ("O1",)


def test_verify_uncovered_optional_obligation_is_reported():
    plan = TaskPlan("Review API", obligations=[Obligation("O1", "Review API response", required=False)], tasks=[Task("T1", "Review database schema", "database")])
    report = verify_task_plan(plan)
    assert report.valid
    assert report.uncovered_optional_obligations == ("O1",)


def test_verify_domain_mismatch_for_explicit_coverage():
    plan = TaskPlan("Review API", obligations=[Obligation("O1", "Review API response")], tasks=[Task("T1", "Review API response", "database", covers_obligations=["O1"])])
    report = verify_task_plan(plan)
    assert not report.valid
    assert "O1" in report.missing_required_obligations


def test_verify_coverage_mapping_must_reference_known_task():
    plan = TaskPlan("Review API", tasks=[Task("T1", "Review API", "api_architecture")])
    report = verify_task_plan(plan, coverage={"unknown": []})
    assert not report.valid
    assert any("unknown task" in error for error in report.errors)


def test_verify_concern_domain_mismatch():
    plan = TaskPlan("Review API", concerns=[Concern("C1", "Review database consistency", "database")], tasks=[Task("T1", "Review database consistency", "api_architecture")])
    report = verify_task_plan(plan)
    assert not report.valid
    assert report.misrouted_concerns == ("C1",)
