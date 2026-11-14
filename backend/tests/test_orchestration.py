"""Offline contract tests for the standalone orchestration policies."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.orchestration import BudgetCost, BudgetManager, Route, RouteRequest, route_request


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")


def request(**changes):
    values = dict(text="What is the API version?", mode="grounded", has_sources=True,
                  requirement_count=1, has_structured_artifacts=False, estimated_tokens=12)
    return RouteRequest(**(values | changes))


@pytest.mark.parametrize("changes,expected", [
    ({}, Route.SINGLE_LLM),
    ({"text": "Validate only the OpenAPI schema", "has_structured_artifacts": True}, Route.DETERMINISTIC),
    ({"requirement_count": 2}, Route.MULTI_AGENT),
    ({"text": "Check authentication; then review authorization"}, Route.MULTI_AGENT),
    ({"text": "What is the API version? What is the database?"}, Route.MULTI_AGENT),
    ({"text": "Review the design"}, Route.MULTI_AGENT),
    ({"estimated_tokens": 129}, Route.MULTI_AGENT),
    ({"text": "Validate only the schema"}, Route.MULTI_AGENT),
    ({"text": "Validate only the schema and explain risks", "has_structured_artifacts": True}, Route.MULTI_AGENT),
    ({"mode": "general", "requirement_count": 5}, Route.SINGLE_LLM),
    ({"mode": "case"}, Route.MULTI_AGENT),
    ({"mode": "case", "text": "Validate only the schema", "has_structured_artifacts": True}, Route.MULTI_AGENT),
    ({"has_sources": False}, Route.SINGLE_LLM),
])
def test_routes(changes, expected):
    decision = route_request(request(**changes))
    assert decision.route == expected
    assert decision.reasons and all(decision.reasons)
    assert decision == route_request(request(**changes))
    assert decision.budget_hint["model_calls"] == (0 if expected == Route.DETERMINISTIC else
                                                   1 if expected == Route.SINGLE_LLM else
                                                   max(1, changes.get("requirement_count", 1)) + 2)


@pytest.mark.parametrize("route", list(Route))
def test_force_route_wins_over_mode(route):
    decision = route_request(request(mode="case", force_route=route))
    assert decision.route == route
    assert {"code": "ROUTE_FORCED", "params": {"route": route.value}} in decision.reasons


@pytest.mark.parametrize("changes", [
    {"mode": "unknown"}, {"estimated_tokens": -1}, {"requirement_count": True},
    {"force_route": "unknown"}, {"has_sources": 1},
])
def test_invalid_route_inputs(changes):
    with pytest.raises(ValueError):
        request(**changes)


def test_reservation_charge_and_exhaustion():
    manager = BudgetManager(20, 10, 2, clock=lambda: 0)
    manager.reserve("answer", 8)
    assert manager.remaining() == {"tokens": 12, "seconds": 10, "model_calls": 1}
    manager.charge("answer", 5, 2)
    assert manager.remaining() == {"tokens": 12, "seconds": 8, "model_calls": 1}
    manager.charge("answer", 15, 8)
    assert manager.remaining() == {"tokens": 0, "seconds": 0, "model_calls": 0}
    assert not manager.should_skip(BudgetCost(0, 0, 0)).skip
    decision = manager.should_skip(BudgetCost(1, 1, 1))
    assert decision.skip
    assert set(decision.reasons) == {"BUDGET: tokens", "BUDGET: seconds", "BUDGET: model_calls"}


@pytest.mark.parametrize("operation", [
    lambda m: m.reserve("x", -1), lambda m: m.reserve("", 0),
    lambda m: m.reserve("x", 11), lambda m: m.reserve("x", True),
    lambda m: m.charge("x", 0, -1), lambda m: m.charge("x", 0, float("nan")),
    lambda m: m.charge("x", 0, float("inf")), lambda m: m.charge("x", 0, 11),
    lambda m: m.charge("x", 11, 0),
])
def test_invalid_or_overflow_operations_are_atomic(operation):
    manager = BudgetManager(10, 10, 1, clock=lambda: 0)
    before = manager.snapshot()
    with pytest.raises(ValueError):
        operation(manager)
    assert manager.snapshot() == before


@pytest.mark.parametrize("limits", [(-1, 1, 1), (1, -1, 1), (1, 1, -1),
                                    (1.5, 1, 1), (1, float("inf"), 1)])
def test_invalid_limits(limits):
    with pytest.raises(ValueError):
        BudgetManager(*limits, clock=lambda: 0)


def test_calls_exhaust_independently_and_kinds_do_not_share_reservations():
    manager = BudgetManager(100, 100, 1, clock=lambda: 0)
    manager.reserve("first", 1)
    before = manager.snapshot()
    with pytest.raises(ValueError, match="model_calls"):
        manager.charge("second", 1, 0)
    assert manager.snapshot() == before
    assert manager.should_skip({"tokens": 0}).skip


def test_snapshot_injected_clock_and_monotonic_accounting():
    now = [100.0]
    manager = BudgetManager(10, 10, 2, clock=lambda: now[0])
    manager.reserve("worker", 4)
    manager.charge("worker", 2, 3)
    now[0] = 105.0
    snapshot = manager.snapshot()
    assert snapshot == {
        "limits": {"tokens": 10, "seconds": 10, "model_calls": 2},
        "used": {"tokens": 4, "seconds": 5, "model_calls": 1},
        "remaining": {"tokens": 6, "seconds": 5, "model_calls": 1},
        "kinds": {"worker": {"reserved_tokens": 4, "charged_tokens": 2,
                               "reserved_calls": 1, "charged_calls": 1, "seconds": 3}},
    }
    snapshot["kinds"]["worker"]["seconds"] = 999
    snapshot["limits"]["tokens"] = 999
    now[0] = 102.0
    assert manager.remaining()["seconds"] == 5
    assert manager.snapshot()["limits"]["tokens"] == 10
    now[0] = 111.0
    assert manager.remaining()["seconds"] == 0
    with pytest.raises(ValueError, match="seconds"):
        manager.reserve("worker", 0)


def test_degrade_plan_preserves_items_duplicates_and_order():
    manager = BudgetManager(6, 10, 3, clock=lambda: 0)
    duplicate = {"id": "same", "cost": {"tokens": 3}}
    requirements = [duplicate, {"id": "large", "cost": {"tokens": 10}},
                    duplicate, {"id": "late", "cost": {"tokens": 1}}]
    before = manager.snapshot()
    kept, skipped = manager.degrade_plan(iter(requirements))
    assert kept == [duplicate, duplicate]
    assert [item.index for item in skipped] == [1, 3]
    assert all(item.reason == "BUDGET" for item in skipped)
    kept_iter = iter(kept)
    rejected = {item.index: item.requirement for item in skipped}
    reconstructed = [rejected[i] if i in rejected else next(kept_iter)
                     for i in range(len(requirements))]
    assert all(actual is original for actual, original in zip(reconstructed, requirements))
    assert len(kept) + len(skipped) == len(requirements)
    assert manager.snapshot() == before


@pytest.mark.parametrize("cost", [BudgetCost(0, 11, 0), BudgetCost(0, 0, 2)])
def test_degrade_plan_checks_time_and_calls(cost):
    manager = BudgetManager(10, 10, 1, clock=lambda: 0)
    requirements = [{"cost": cost}, "small"]
    kept, skipped = manager.degrade_plan(requirements)
    assert kept == ["small"]
    assert skipped[0].requirement is requirements[0]
    assert skipped[0].reason == "BUDGET"
    assert manager.degrade_plan([]) == ([], [])


def test_concurrent_reservations_and_charges_obey_limits():
    manager = BudgetManager(20, 100, 20, clock=lambda: 0)

    def work(index):
        try:
            manager.reserve(str(index), 1)
        except ValueError:
            return False
        manager.charge(str(index), 1, 1)
        return True

    with ThreadPoolExecutor(max_workers=4) as pool:
        accepted = list(pool.map(work, range(40)))
    assert sum(accepted) == 20
    assert manager.snapshot()["used"] == {"tokens": 20, "seconds": 20, "model_calls": 20}
