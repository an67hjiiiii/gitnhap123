"""Thread-safe, conservative accounting with an injectable monotonic clock."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import math
from threading import RLock
import time
from typing import Any


def _count(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("Counts must be nonnegative integers")


def _seconds(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("Seconds must be finite and nonnegative")


@dataclass(frozen=True)
class BudgetCost:
    tokens: int = 0
    seconds: float = 0
    model_calls: int = 1

    def __post_init__(self):
        _count(self.tokens)
        _seconds(self.seconds)
        _count(self.model_calls)


@dataclass(frozen=True)
class SkipDecision:
    skip: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkippedRequirement:
    requirement: Any
    index: int
    reason: str = "BUDGET"


class BudgetManager:
    """Account for token commitments, model calls and elapsed/charged time.

    Each reserve commits tokens and one call for a nonempty kind. charge records
    actual usage for one call of that kind. Per-kind committed usage is the
    maximum of cumulative reserved and charged usage: charges consume reservations
    without double counting, and unused reservations are never refunded. Kinds
    must therefore identify the same stream of work for reserve and charge.
    Time usage is max(elapsed wall time, sum of charged seconds), avoiding double
    counting. Rejected operations leave counters unchanged. All limits are hard;
    over-limit actual usage raises ValueError rather than silently overflowing.
    """

    def __init__(self, max_tokens: int, max_seconds: float, max_model_calls: int,
                 clock: Callable[[], float] = time.monotonic):
        BudgetCost(max_tokens, max_seconds, max_model_calls)
        self._limits = {"tokens": max_tokens, "seconds": max_seconds, "model_calls": max_model_calls}
        self._clock = clock
        self._lock = RLock()
        self._started = clock()
        _seconds(self._started)
        self._elapsed = 0.0
        self._kinds: dict[str, dict[str, int | float]] = {}

    def _used(self) -> dict:
        now = self._clock()
        _seconds(now)
        self._elapsed = max(self._elapsed, now - self._started)
        return {
            "tokens": sum(max(v["reserved_tokens"], v["charged_tokens"]) for v in self._kinds.values()),
            "model_calls": sum(max(v["reserved_calls"], v["charged_calls"]) for v in self._kinds.values()),
            "seconds": max(self._elapsed, sum(v["seconds"] for v in self._kinds.values())),
        }

    def remaining(self) -> dict:
        with self._lock:
            used = self._used()
            return {key: max(0, limit - used[key]) for key, limit in self._limits.items()}

    def snapshot(self) -> dict:
        """Return detached, trace-ready counters; no timestamps or mutable aliases."""
        with self._lock:
            used = self._used()
            return {"limits": dict(self._limits), "used": used,
                    "remaining": {k: max(0, v - used[k]) for k, v in self._limits.items()},
                    "kinds": {k: dict(v) for k, v in sorted(self._kinds.items())}}

    def should_skip(self, next_cost: BudgetCost | Mapping) -> SkipDecision:
        """Check additional committed cost; this query does not reserve capacity."""
        cost = next_cost if isinstance(next_cost, BudgetCost) else BudgetCost(**next_cost)
        with self._lock:
            remaining = self.remaining()
            reasons = tuple(f"BUDGET: {key}" for key in self._limits
                            if getattr(cost, key) > remaining[key])
            return SkipDecision(bool(reasons), reasons)

    def _record(self, kind: str, tokens: int, seconds: float, reserve: bool) -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("kind must be a nonempty string")
        BudgetCost(tokens, seconds)
        with self._lock:
            used = self._used()
            old = self._kinds.get(kind, dict(reserved_tokens=0, charged_tokens=0,
                                             reserved_calls=0, charged_calls=0, seconds=0))
            new = dict(old)
            prefix = "reserved" if reserve else "charged"
            new[f"{prefix}_tokens"] += tokens
            new[f"{prefix}_calls"] += 1
            new["seconds"] += seconds
            for key in ("tokens", "calls"):
                delta = max(new[f"reserved_{key}"], new[f"charged_{key}"]) - max(old[f"reserved_{key}"], old[f"charged_{key}"])
                limit_key = "model_calls" if key == "calls" else key
                if used[limit_key] + delta > self._limits[limit_key]:
                    raise ValueError(f"BUDGET: {limit_key}")
            charged_seconds = sum(v["seconds"] for v in self._kinds.values()) + seconds
            if max(self._elapsed, charged_seconds) > self._limits["seconds"]:
                raise ValueError("BUDGET: seconds")
            self._kinds[kind] = new

    def reserve(self, kind: str, tokens: int) -> None:
        self._record(kind, tokens, 0, True)

    def charge(self, kind: str, tokens: int, seconds: float) -> None:
        self._record(kind, tokens, seconds, False)

    def degrade_plan(self, requirements: Iterable) -> tuple[list, list[SkippedRequirement]]:
        """Preview a plan without accounting mutations, preserving relative order.

        Each requirement is a mapping with an optional `cost` (BudgetCost or
        mapping). Other objects default to zero tokens/time and one model call.
        Keep affordable items greedily in input order. Every rejection retains
        its original object and position, including duplicates. The two outputs
        preserve their respective input order; indices permit full reconstruction.
        """
        with self._lock:
            available = self.remaining()
            kept, skipped = [], []
            for index, requirement in enumerate(requirements):
                raw = requirement.get("cost", BudgetCost()) if isinstance(requirement, Mapping) else BudgetCost()
                cost = raw if isinstance(raw, BudgetCost) else BudgetCost(**raw)
                if any(getattr(cost, key) > available[key] for key in available):
                    skipped.append(SkippedRequirement(requirement, index))
                else:
                    kept.append(requirement)
                    for key in available:
                        available[key] -= getattr(cost, key)
            return kept, skipped
