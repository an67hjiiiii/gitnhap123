"""Explainable routing without providers, retrieval, or pipeline dependencies."""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Literal


class Route(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    SINGLE_LLM = "SINGLE_LLM"
    MULTI_AGENT = "MULTI_AGENT"


@dataclass(frozen=True)
class RouteRequest:
    text: str
    mode: Literal["general", "grounded", "case"]
    has_sources: bool
    requirement_count: int
    has_structured_artifacts: bool
    estimated_tokens: int
    force_route: Route | None = None

    def __post_init__(self):
        if self.mode not in {"general", "grounded", "case"}:
            raise ValueError("Unknown mode")
        for value in (self.requirement_count, self.estimated_tokens):
            if type(value) is not int or value < 0:
                raise ValueError("Counts must be nonnegative integers")
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")
        if type(self.has_sources) is not bool or type(self.has_structured_artifacts) is not bool:
            raise ValueError("Source and artifact flags must be booleans")
        if self.force_route is not None:
            Route(self.force_route)


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    reasons: list[str]
    budget_hint: dict[str, int]


def route_request(request: RouteRequest) -> RouteDecision:
    """Apply these rules in order, with no external state.

    An explicit force_route overrides everything. General mode selects a single
    answer; case mode selects multi-agent analysis. Grounded mode permits an
    artifacts-only check when text explicitly asks only for validation/checking
    (not explanation, analysis, or recommendations). Otherwise multiple declared
    requirements, or multiple clauses with sources, select MULTI_AGENT. A short
    single question (<=128 estimated tokens and <=500 characters) selects
    SINGLE_LLM; remaining grounded requests conservatively select MULTI_AGENT.
    Thus user-selected modes take precedence over text heuristics. Budget hints
    are advisory input-token estimates and call counts, not execution limits.
    """
    reasons = [f"Selected mode: {request.mode}"]
    text = request.text.strip().casefold()
    clauses = [part.strip() for part in re.split(r"[;?\n]+|\b(?:and|then|also)\b", text) if part.strip()]
    artifacts_only = (
        request.has_structured_artifacts
        and bool(re.search(r"\b(?:check|validate|lint)\b", text))
        and bool(re.search(r"\b(?:only|syntax|schema|validity)\b", text))
        and not re.search(r"\b(?:explain|analy[sz]e|recommend|design|compare)\b", text)
    )
    if request.force_route is not None:
        route = Route(request.force_route)
        reasons.append(f"force_route override: {route.value}")
    elif request.mode == "general":
        route = Route.SINGLE_LLM
        reasons.append("General mode requests a single answer")
    elif request.mode == "case":
        route = Route.MULTI_AGENT
        reasons.append("Case mode requests planned analysis")
    elif artifacts_only:
        route = Route.DETERMINISTIC
        reasons.append("Artifacts-only validation can use deterministic checks")
    elif request.requirement_count > 1 or (request.has_sources and len(clauses) > 1):
        route = Route.MULTI_AGENT
        reasons.append("Multiple requirements or multiple clauses with sources")
    elif request.estimated_tokens <= 128 and len(text) <= 500 and (
        text.endswith("?") or re.match(r"^(what|which|who|where|when|why|how|is|are|can|does|do)\b", text)
    ):
        route = Route.SINGLE_LLM
        reasons.append("Short single question")
    else:
        route = Route.MULTI_AGENT
        reasons.append("Grounded request needs planning beyond a short single question")
    calls = {Route.DETERMINISTIC: 0, Route.SINGLE_LLM: 1,
             Route.MULTI_AGENT: max(1, request.requirement_count) + 2}[route]
    return RouteDecision(route, reasons, {
        "tokens": 0 if route == Route.DETERMINISTIC else request.estimated_tokens,
        "model_calls": calls,
    })
