from __future__ import annotations
import json
import re
from copy import deepcopy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from app.core.graph import validate_tasks
from app.core.structured_output import decode_structured_json
from app.core.types import (
    ObligationConcernExtraction,
    RunMetrics,
    Task,
    TaskPlan,
)
from app.research.registry import REGISTRY, _SOFTWARE_HINTS, active_domains, active_pack, validate_domain
from app.retrieval.text import terms


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("Planner did not return JSON")
        return json.loads(m.group(0))

async def decompose(
    provider,
    query: str,
    planning_context: str,
    metrics: RunMetrics,
    *,
    num_ctx: int | None = None,
    request_timeout: float | None = None,
    keep_alive: str | int | float | None = None,
) -> list[Task]:
    system = "TASK_DECOMPOSER. Return JSON only. Preserve atomic obligations and dependencies. Do not invent requirements."
    user = f"USER REQUEST:\n{query}\n\nPLANNING CONTEXT:\n{planning_context}\n\nSchema: {{\"tasks\":[{{\"id\":\"T1\",\"goal\":\"...\",\"domain\":\"{"|".join(active_domains())}\",\"depends_on\":[],\"evidence_needs\":[]}}]}}"
    extra: dict[str, Any] = {}
    if num_ctx is not None and getattr(provider, "supports_num_ctx", False):
        extra["num_ctx"] = num_ctx
    if request_timeout is not None and getattr(provider, "supports_per_call_timeout", False):
        extra["timeout"] = request_timeout
    if keep_alive is not None and getattr(provider, "supports_keep_alive", False):
        extra["keep_alive"] = keep_alive
    result = await provider.generate(system=system, user=user, **extra)
    metrics.add_usage(result.usage)
    obj = _extract_json(result.text)
    tasks = []
    for i, raw in enumerate(obj.get("tasks") or []):
        tasks.append(Task(
            task_id=str(raw.get("id") or f"T{i+1}"),
            goal=str(raw.get("goal") or query),
            domain=str(raw.get("domain") or active_pack()["default_domain"]),
            depends_on=[str(x) for x in raw.get("depends_on") or []],
            evidence_needs=[str(x) for x in raw.get("evidence_needs") or []],
        ))
    return tasks or [Task(task_id="T1", goal=query)]


# Group A planning contracts.  The legacy ``decompose`` function above remains
# list[Task]-compatible for the existing execution pipeline.  These bounded
# helpers provide the structured Sprint 3 planning seam without moving plan
# verification, normalization, workers, dispatch, or execution into this file.
CANONICAL_TASK_DOMAINS = tuple(REGISTRY)
_DOMAIN_HINTS = _SOFTWARE_HINTS  # bộ Phần mềm; bộ đang dùng đọc qua active_pack()
TASK_PLAN_SCHEMA = (
    '{"tasks":[{"task_id":"T1","goal":"...",'
    f'"domain":"{"|".join(CANONICAL_TASK_DOMAINS)}",'
    '"depends_on":[],"evidence_needs":["subject-specific search phrase"],'
    '"covers_obligations":[],"covers_concerns":[]}]}'
)
# Stable public alias for callers that used the schema-oriented name.
TASK_PLAN_JSON_SCHEMA = TASK_PLAN_SCHEMA
TASK_PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "minLength": 1},
                    "goal": {"type": "string", "minLength": 1},
                    "domain": {"type": "string", "enum": list(CANONICAL_TASK_DOMAINS)},
                    "depends_on": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    "evidence_needs": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    "covers_obligations": {"type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
                    "covers_concerns": {"type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
                },
                "required": ["task_id", "goal", "domain", "depends_on", "evidence_needs", "covers_obligations", "covers_concerns"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tasks"],
    "additionalProperties": False,
}
PLANNER_SYSTEM_PROMPT = (
    "TASK_PLAN_BUILDER. Return exactly one compact JSON object matching the "
    "task-plan schema. Preserve explicit obligations and dependencies; keep "
    "goals concise and evidence_needs as short subject-specific search phrases, "
    "not explanations. Do not omit subjects or constraints. Do not add "
    "verification, repair, worker, dispatch, or execution fields."
)
TASK_PLAN_PROMPT_VERSION = "task-plan-required-process-contract-v10"
_TASK_ROOT_FIELDS = frozenset({"tasks"})
_TASK_FIELDS = frozenset(
    {"task_id", "id", "goal", "domain", "depends_on", "evidence_needs", "covers_obligations", "covers_concerns"}
)


def task_plan_response_schema(extraction: ObligationConcernExtraction | None = None) -> dict:
    schema = deepcopy(TASK_PLAN_RESPONSE_SCHEMA)
    schema["properties"]["tasks"]["items"]["properties"]["domain"]["enum"] = list(active_domains())
    if extraction is not None:
        fields = schema["properties"]["tasks"]["items"]["properties"]
        for name, ids in (
            ("covers_obligations", [item.obligation_id for item in extraction.obligations]),
            ("covers_concerns", [item.concern_id for item in extraction.concerns]),
        ):
            if ids:
                fields[name]["items"]["enum"] = ids
            else:
                fields[name]["maxItems"] = 0
    return schema


@dataclass(frozen=True)
class RequestUnderstanding:
    """Bounded request understanding used to seed planning and routing."""

    request: str
    normalized_request: str
    domains: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "normalized_request": self.normalized_request,
            "domains": list(self.domains),
        }


@dataclass
class PlanningResult:
    """Outcome of one plan generation plus at most one bounded repair."""

    request: str
    plan: TaskPlan | None = None
    status: str = "FAILED"
    warnings: list[str] = field(default_factory=list)
    repair_attempted: bool = False

    @property
    def tasks(self) -> list[Task]:
        """Expose the plan tasks without making execution part of planning."""

        return list(self.plan.tasks) if self.plan is not None else []


# Compatibility name for clients that use the decomposition-result wording.
DecompositionResult = PlanningResult


def _non_empty_request(request: str) -> str:
    if not isinstance(request, str) or not request.strip():
        raise ValueError("request must be a non-empty string")
    return request.strip()


def _contains_hint(text: str, hint: str) -> bool:
    if " " in hint:
        return hint in text
    return re.search(rf"(?<![\w]){re.escape(hint)}(?![\w])", text) is not None


def detect_domains(request: str) -> list[str]:
    """Return canonical domains explicitly signalled by the current request."""

    text = _non_empty_request(request).casefold()
    return [
        domain
        for domain in active_domains()
        if any(_contains_hint(text, hint) for hint in active_pack()["hints"][domain])
    ]


def understand_request(request: str) -> RequestUnderstanding:
    """Normalize the request and detect only domains named by its text."""

    normalized = " ".join(_non_empty_request(request).split())
    return RequestUnderstanding(
        request=request,
        normalized_request=normalized,
        domains=tuple(detect_domains(normalized)),
    )


def _format_requirements(
    extraction: ObligationConcernExtraction | None,
) -> tuple[str, str]:
    if extraction is None:
        return "none", "none"
    obligations = "\n".join(
        f"- {item.obligation_id}: {item.description} (required={item.required})"
        for item in extraction.obligations
    ) or "none"
    concerns = "\n".join(
        f"- {item.concern_id}: {item.description} (domain={item.domain})"
        for item in extraction.concerns
    ) or "none"
    return obligations, concerns


def domain_rules() -> str:
    """Dòng giới hạn miền cho prompt; bộ Phần mềm ra đúng câu cũ, bộ khác thêm phạm vi và quy tắc ngôn ngữ."""
    domains = active_domains()
    listed = domains[0] if len(domains) == 1 else ", ".join(domains[:-1]) + ", or " + domains[-1]
    line = f"- Use only {listed} task domains.\n"
    pack = active_pack()
    if not pack["plan_rules"]:
        return line
    scopes = "; ".join(f"{d} = {a['scope']}" for d, a in pack["agents"].items())
    return line + f"- Domain scopes: {scopes}.\n" + pack["plan_rules"]


def build_task_plan_prompt(
    request: str,
    planning_context: str = "",
    extraction: ObligationConcernExtraction | None = None,
) -> str:
    """Build the bounded task-plan prompt from request-owned inputs."""

    understanding = understand_request(request)
    obligations, concerns = _format_requirements(extraction)
    return (
        "OUTPUT PROTOCOL:\n"
        "Return exactly one JSON object and no markdown or explanation. Use root key tasks; "
        "each task must include task_id, goal, domain, depends_on, evidence_needs, "
        "covers_obligations, and covers_concerns.\n\n"
        "RULES:\n"
        "- Keep obligations and concerns distinct from tasks.\n"
        "- Return covers_obligations and covers_concerns on every task. The "
        "covers_obligations union must include every ID marked required=true "
        "under EXPLICIT OBLIGATIONS; the covers_concerns union must include "
        "every ID under EXPLICIT CONCERNS. IDs in both coverage arrays must "
        "come from those sections; never invent IDs, repeat an ID within "
        "one coverage array, or omit a required ID from the plan union. "
        "A domainless obligation is not optional: required=true still applies. "
        "Group related obligations where valid, including process/output work, "
        "but retain each claimed subject and constraint in the task goal.\n"
        "- Retain every required obligation, including process/output and "
        "negative preservation constraints, in a specific actionable goal. "
        "Do not claim coverage with IDs alone. Keep independent technical "
        "subjects in tasks of their matching canonical domain, not one vague "
        "cross-domain summary. Related obligations may share a task; there is "
        "no fixed task count. Preserve required/optional meaning and polarity.\n"
        "- For each required process/output obligation, copy its complete extracted "
        "definition as a clause in the assigned goal. Do not replace its object "
        "or qualifiers with a related technical subject. Grouping does not "
        "remove that clause or make its required ID optional.\n"
        "- Every explicit concern must be retained in at least one task.goal. "
        "Use its full subject text, not only its ID or evidence_needs; keep its "
        "domain when it is not general.\n"
        "- Keep goal wording concise while retaining all required subjects and "
        "constraints. Keep evidence_needs to short, subject-specific search "
        "phrases, not explanations. Prefer compact JSON.\n"
        "- Preserve request-stated dependency direction in depends_on.\n"
        "- depends_on entries must be exact IDs of tasks in this plan, never "
        "names or descriptions. Do not invent ordering when none is required.\n"
        "- When supporting evidence is explicitly requested, technical tasks "
        "must provide evidence_needs as subject-specific search phrases. "
        "Derive them from the task goal, related obligations/concerns and "
        "available planning context; describe needed evidence, not guessed chunks. "
        "Do not use empty arrays, placeholder words or Planning KB locator IDs "
        "as substitutes. Do not invent facts or pretend retrieval occurred.\n"
        f"{domain_rules()}"
        "- Emit no plan-verification, repair, worker, dispatch, or execution fields.\n"
        "Return JSON only.\n\n"
        "CURRENT REQUEST:\n"
        f"{understanding.normalized_request}\n\n"
        "REQUEST DOMAINS (routing hints only):\n"
        f"{', '.join(understanding.domains) or 'none'}\n\n"
        "EXPLICIT OBLIGATIONS:\n"
        f"{obligations}\n\n"
        "EXPLICIT CONCERNS:\n"
        f"{concerns}\n\n"
        "PLANNING EVIDENCE (guidance only; never a new requirement):\n"
        f"{planning_context.strip() or 'none'}"
    )


def _decode_task_plan_payload(payload: Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError("task plan output must be a JSON object")
    text = payload.strip()
    try:
        decoded = decode_structured_json(text)
    except json.JSONDecodeError:
        raise ValueError("task plan output must be exactly one JSON object") from None
    if not isinstance(decoded, Mapping):
        raise ValueError("task plan output must be a JSON object")
    return decoded


def _validate_task_item_fields(raw: Mapping[str, Any], index: int) -> None:
    unsupported = [str(key) for key in raw if key not in _TASK_FIELDS]
    if unsupported:
        raise ValueError(
            f"task {index} contains unsupported fields: "
            + ", ".join(sorted(unsupported))
        )


def _required_string(raw: Mapping[str, Any], key: str, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"task {index}.{key} must be a non-empty string")
    return value


def _string_list(raw: Mapping[str, Any], key: str, index: int) -> list[str]:
    if key not in raw:
        raise ValueError(f"task {index} must include {key} as a list")
    value = raw[key]
    if not isinstance(value, list):
        raise ValueError(f"task {index}.{key} must be a list")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"task {index}.{key} must contain non-empty strings")
        values.append(item)
    if len(values) != len(set(values)):
        raise ValueError(f"task {index}.{key} contains duplicate entries")
    return values


def parse_task_plan_output(
    payload: Mapping[str, Any] | str,
    request: str = "",
    extraction: ObligationConcernExtraction | None = None,
) -> TaskPlan:
    """Parse a strict task-only envelope into the existing ``TaskPlan`` contract."""

    obj = _decode_task_plan_payload(payload)
    unsupported = [str(key) for key in obj if key not in _TASK_ROOT_FIELDS]
    if unsupported:
        raise ValueError(
            "task plan contains unsupported root fields: "
            + ", ".join(sorted(unsupported))
        )
    if "tasks" not in obj:
        raise ValueError("task plan must contain a tasks list")
    raw_tasks = obj["tasks"]
    if not isinstance(raw_tasks, list):
        raise ValueError("task plan tasks must be a list")
    if not raw_tasks:
        raise ValueError("task plan tasks must contain at least one task")

    tasks: list[Task] = []
    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, Mapping):
            raise ValueError(f"task {index} must be an object")
        _validate_task_item_fields(raw, index)
        if "id" in raw and "task_id" in raw:
            raise ValueError(f"task {index} must use only one task ID field")
        id_key = "task_id" if "task_id" in raw else "id"
        identifier = _required_string(raw, id_key, index)
        goal = _required_string(raw, "goal", index)
        domain = _required_string(raw, "domain", index)
        try:
            validate_domain(domain)
        except ValueError as exc:
            raise ValueError(f"task {index}.domain: {exc}") from exc
        tasks.append(
            Task(
                task_id=identifier,
                goal=goal,
                domain=domain,
                depends_on=_string_list(raw, "depends_on", index),
                evidence_needs=_string_list(raw, "evidence_needs", index),
                covers_obligations=(
                    _string_list(raw, "covers_obligations", index) if "covers_obligations" in raw
                    else [] if extraction is not None else None
                ),
                covers_concerns=(
                    _string_list(raw, "covers_concerns", index) if "covers_concerns" in raw
                    else [] if extraction is not None else None
                ),
            )
        )
    if extraction is not None:
        allowed = {
            "covers_obligations": {item.obligation_id for item in extraction.obligations},
            "covers_concerns": {item.concern_id for item in extraction.concerns},
        }
        for task in tasks:
            for name, ids in allowed.items():
                if set(getattr(task, name) or []) - ids:
                    raise ValueError(f"task {task.task_id}.{name} contains unknown IDs")
    validate_tasks(tasks)
    return TaskPlan(
        request=request,
        obligations=list(extraction.obligations) if extraction else [],
        concerns=list(extraction.concerns) if extraction else [],
        tasks=tasks,
    )


parse_task_plan = parse_task_plan_output


PLANNER_SEMANTICS_VERSION = "claimed-record-goals-v3-global-output-constraint-retention"
_GOAL_SCAFFOLD = terms(
    "extract identify report determine review check verify verification perform "
    "requested requirement obligation concern task information field data value "
    "exact exactly whether has been only uploaded supplied file document source "
    "content against from according current provided mechanism can mentioned"
)


def _global_evidence_constraint(text: str) -> bool:
    words = terms(text)
    # Subject-qualified restrictions remain local to their original claims.
    if detect_domains(text) or re.search(r"\b(?:for|about|regarding|to)\s+", text, re.IGNORECASE):
        return False
    return bool(words & terms("source evidence document file")) and bool(
        re.search(r"\b(?:use|using)\s+only\b|\b(?:do not|never)\s+infer\b|\bno inference\b|\bwithout inference\b", text, re.IGNORECASE)
    )


def _global_output_constraint(text: str) -> bool:
    """Recognize only source bounds or universal preservation of plan scope."""
    if _global_evidence_constraint(text):
        return True
    from app.research.plan_verification import _coverage_clause

    # Reuse the verifier's bounded polarity normalization. Domain-specific or
    # qualified objects do not match and remain obligations of their own task.
    return bool(re.fullmatch(
        r"preserve all (?:(?:identified|required|requested) )?"
        r"(?:requirements?|obligations?|concerns?|constraints?)",
        _coverage_clause(text),
    ))


def _contradicts_scope_preservation(goal: str, constraint: str) -> bool:
    from app.research.plan_verification import _coverage_clause

    source = _coverage_clause(constraint)
    if not source.startswith("preserve all "):
        return False
    objects = terms(source) & terms("requirements obligations concerns constraints")
    return any(
        _coverage_clause(clause).startswith("not preserve ")
        and bool(terms(clause) & objects)
        for clause in re.split(r"[;.\n]+", goal)
    )


def _request_requires_order(request: str) -> bool:
    """Only explicit ordering language authorizes model-proposed graph edges.

    Numbered analytical obligations and task-list position are not dependencies.
    Structural graph validation remains mandatory before this boundary.
    """
    return bool(re.search(
        r"\b(?:after|before|then|depends on|dependent on|prerequisite)\b"
        r"|(?:sau khi|trước khi|sau đó|tiếp theo|phụ thuộc vào)",
        request.casefold(),
    ))


def canonicalize_task_plan(plan: TaskPlan) -> TaskPlan:
    """Render only explicitly claimed semantics; never repair routing or evidence.

    Specific off-topic claims and contradictory goals remain invalid. A generic
    goal can delegate its meaning to its explicit records, but IDs never bypass
    reference, domain, graph, evidence or final semantic verification.
    """
    # Reuse the accepted predicate without changing or bypassing the verifier.
    # Local import avoids the verifier's detect_domains import cycle.
    from app.research.plan_verification import _retains_text

    # Reject malformed references/cycles before removing unsupported ordering.
    try:
        validate_tasks(plan.tasks)
    except ValueError:
        return plan  # Preserve the invalid graph for the common verifier to reject.
    if not _request_requires_order(plan.request):
        plan = replace(plan, tasks=[replace(task, depends_on=[]) for task in plan.tasks])
    obligations = {item.obligation_id: item.description for item in plan.obligations}
    concerns = {item.concern_id: item.description for item in plan.concerns}
    global_ids = {item.obligation_id for item in plan.obligations if item.required and _global_output_constraint(item.description)}
    referenced = {identifier for task in plan.tasks for identifier in task.depends_on}
    constraint_only = {task.task_id for task in plan.tasks
                       if task.covers_obligations and set(task.covers_obligations) <= global_ids and not task.covers_concerns}
    technical = any(
        set(task.covers_concerns or []) & concerns.keys()
        or any(identifier not in global_ids and detect_domains(obligations[identifier])
               for identifier in task.covers_obligations or [] if identifier in obligations)
        for task in plan.tasks if task.task_id not in constraint_only
    )
    removable = constraint_only - referenced if technical else set()
    tasks = []
    for task in plan.tasks:
        if task.task_id in removable:
            continue
        # Global constraints are explicit extracted requirements, not inferred
        # task subjects. Apply them to outputs and transfer their coverage from
        # removable constraint-only nodes; other assignments stay untouched.
        claims = list(task.covers_obligations or [])
        for identifier in obligations:
            if identifier in global_ids and identifier not in claims:
                claims.append(identifier)
        task = replace(task, covers_obligations=claims if global_ids else task.covers_obligations)
        # A global claim and its actual restriction must travel together, even
        # when this task's specific subject needs a separate semantic repair.
        if any(_contradicts_scope_preservation(task.goal, obligations[key]) for key in global_ids):
            tasks.append(task)  # Keep explicit opposite actions invalid for the verifier.
            continue
        subject_goal = task.goal
        restrictions = [obligations[key] for key in obligations if key in global_ids
                        and not _retains_text(task.goal, obligations[key])]
        if restrictions:
            task = replace(task, goal=task.goal + "; " + "; ".join(restrictions))
        definitions = []
        for claims, records in ((task.covers_obligations, obligations), (task.covers_concerns, concerns)):
            for identifier in claims or []:
                if identifier not in records:
                    raise ValueError(f"task {task.task_id} claims unknown requirement {identifier}")
                if records[identifier] not in definitions:
                    definitions.append(records[identifier])
        if not definitions or all(_retains_text(task.goal, text) for text in definitions):
            tasks.append(task)
            continue
        # Inflection of approval is the same property, unlike auth/authz.
        def subject(text: str) -> set[str]:
            return {"approval" if word == "approved" else word
                    for word in terms(text) - _GOAL_SCAFFOLD}

        goal_subject = subject(subject_goal)
        compatible = all(
            not goal_subject or subject(text).issubset(goal_subject)
            for text in definitions if not _global_output_constraint(text)
        )
        augmented = task.goal + "; " + "; ".join(definitions)
        # This also prevents an explicit opposite command being laundered by
        # simply appending the correct definition after it.
        noncontradictory = all(_retains_text(augmented, text) for text in definitions)
        goal = "; ".join(definitions) if compatible and noncontradictory else task.goal
        tasks.append(replace(task, goal=goal))
    if not _request_requires_order(plan.request):
        tasks = [replace(task, depends_on=[]) for task in tasks]
    return replace(plan, tasks=tasks)


def build_task_plan_repair_prompt(
    request: str,
    previous_output: str,
    error: str,
    planning_context: str = "",
    extraction: ObligationConcernExtraction | None = None,
    *,
    missing_concern_ids: tuple[str, ...] = (),
    missing_obligation_ids: tuple[str, ...] = (),
    preservation: dict | None = None,
) -> str:
    """Request one bounded correction without widening the planning scope."""

    base = build_task_plan_prompt(request, planning_context, extraction)
    static_rules, dynamic_inputs = base.split("CURRENT REQUEST:\n", 1)
    bounded_output = previous_output
    concerns = [
        item for item in (extraction.concerns if extraction else [])
        if item.concern_id in missing_concern_ids
    ]
    concern_feedback = ""
    obligation_feedback = ""
    obligations = [
        item for item in (extraction.obligations if extraction else [])
        if item.obligation_id in missing_obligation_ids
    ]
    if obligations:
        obligation_feedback = (
            "REQUIRED OBLIGATION COVERAGE:\n"
            + "\n".join(
                f"- {item.obligation_id}: task.goal must retain {item.description} "
                f"(required={item.required})." for item in obligations
            ) + "\n\n"
        )
    if concerns:
        concern_feedback = (
            "REQUIRED CONCERN COVERAGE:\n"
            + "\n".join(
                f"- {item.concern_id}: task.goal must retain the full subject: "
                f"{item.description} (domain={item.domain})."
                for item in concerns
            )
            + "\nDo not substitute concern IDs or evidence_needs for goal coverage. "
            "Coverage IDs and retained goal text must both be correct.\n\n"
        )
    return (
        f"{static_rules}"
        "BOUNDED REPAIR RULES:\n"
        "Return one corrected JSON object only. Preserve all valid IDs and "
        "request-stated dependency direction. Return the complete plan, not a "
        "replacement design: KEEP fields locked by PRESERVATION JSON exactly. "
        "Keep already-verified coverage for each task; append missing coverage "
        "only when the updated goal actually satisfies it. Add missing process "
        "obligations and subject-specific evidence queries; do not drop good "
        "tasks to fix another. Change only fields identified by diagnostics.\n\n"
        f"CURRENT REQUEST:\n{dynamic_inputs}\n\n"
        f"{obligation_feedback}"
        f"{concern_feedback}"
        "PRESERVATION JSON:\n"
        f"{json.dumps(preservation or {}, ensure_ascii=False)}\n\n"
        "PREVIOUS INVALID TASK PLAN:\n"
        f"{bounded_output}\n\n"
        "VALIDATION ERROR:\n"
        f"{error}"
    )


def build_semantic_task_plan_repair_prompt(
    plan: TaskPlan,
    verifier_diagnostics: Sequence[str],
    *,
    missing_obligation_ids: Sequence[str] = (),
    missing_concern_ids: Sequence[str] = (),
) -> str:
    """Build a compact, evidence-bounded repair for a parsed TaskPlan.

    The canonical JSON Schema is sent separately through the provider's
    structured ``format`` field.  Only the parsed plan, exact verifier errors,
    and definitions for requirements that need repair belong in this prompt.
    """

    task_plan = {
        "tasks": [
            {
                "task_id": task.task_id,
                "goal": task.goal,
                "domain": task.domain,
                "depends_on": list(task.depends_on),
                "evidence_needs": list(task.evidence_needs),
                "covers_obligations": list(task.covers_obligations or []),
                "covers_concerns": list(task.covers_concerns or []),
            }
            for task in plan.tasks
        ]
    }
    from app.research.plan_verification import repair_preservation_contract, verify_task_plan

    report = verify_task_plan(plan)
    missing_obligations = set(missing_obligation_ids)
    missing_concerns = set(missing_concern_ids)
    # A requirement may be covered globally but still be falsely claimed by a
    # specific task. Send its definition for that diagnostic too.
    for task in plan.tasks:
        valid = report.task_coverage.get(task.task_id, {})
        missing_obligations.update(set(task.covers_obligations or []) - set(valid.get("obligation_ids", [])))
        missing_concerns.update(set(task.covers_concerns or []) - set(valid.get("concern_ids", [])))
    preservation = repair_preservation_contract(plan, report)
    required_contract = [
        {"id": item.obligation_id, "definition": item.description,
         "claimed_by": [task.task_id for task in plan.tasks
                        if item.obligation_id in (task.covers_obligations or [])]}
        for item in plan.obligations if item.required
    ]
    definitions = []
    for obligation in plan.obligations:
        if obligation.obligation_id in missing_obligations:
            definitions.append(
                f"{obligation.obligation_id} (required={str(obligation.required).lower()}): "
                f"{obligation.description}"
            )
    for concern in plan.concerns:
        if concern.concern_id in missing_concerns:
            definitions.append(
                f"{concern.concern_id} (domain={concern.domain}): "
                f"{concern.description}"
            )

    diagnostics = "\n".join(f"- {item}" for item in verifier_diagnostics) or "- none"
    definition_block = "\n".join(definitions) or "none"
    return (
        "Fix only the listed verification issues. Return the complete corrected "
        "TaskPlan JSON using the supplied structured schema. Preserve unaffected "
        "tasks, IDs, domains, dependencies, evidence_needs, coverage, and the "
        "subject and polarity of each required definition. Do not invent requirements, "
        "evidence, task IDs, or dependency edges. "
        "A does-not-retain diagnostic requires editing that task.goal, not just "
        "its coverage IDs. State every requested action/result and qualifier, "
        "including exactness, source restrictions and negative constraints. "
        "Use the supplied canonical subject/action terminology so the correction "
        "is explicit, without repeating unrelated definitions. "
        "Extraction alone does not promise the requested reporting or verification. "
        "For a failed concern, address its actual check/property in a matching-domain "
        "goal; remove an invalid claim only if that concern remains covered elsewhere. "
        "Do not return unchanged invalid goals. Obey the PRESERVATION JSON locks: "
        "keep those tasks and their verified fields; extend a goal to add missing "
        "coverage without rewriting its valid content. For a does-not-retain "
        "obligation, KEEP its claim and append the exact missing definition to "
        "that task.goal; removing the claim is not a repair. Every entry in the "
        "REQUIRED OBLIGATION CONTRACT must still be semantically covered. "
        "Do not discard a process task merely because it has no technical domain. "
        "Keep the corrected JSON compact.\n\n"
        "REQUIRED OBLIGATION CONTRACT:\n"
        f"{json.dumps(required_contract, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "CURRENT TASK PLAN:\n"
        f"{json.dumps(task_plan, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "VERIFIER DIAGNOSTICS:\n"
        f"{diagnostics}\n\n"
        "PRESERVATION JSON:\n"
        f"{json.dumps(preservation, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "REQUIRED DEFINITIONS:\n"
        f"{definition_block}"
    )


def _safe_warning(error: BaseException) -> str:
    message = str(error).strip() or type(error).__name__
    message = re.sub(
        r"(?i)(token|password|secret|api[_ -]?key)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        message,
    )
    return f"{type(error).__name__}: {message[:300]}"


async def generate_task_plan(
    provider: Any,
    *,
    user: str,
    extraction: ObligationConcernExtraction | None = None,
    max_output_tokens: int | None = None,
    num_ctx: int | None = None,
    request_timeout: float | None = None,
    keep_alive: str | int | float | None = None,
):
    extra: dict[str, Any] = {}
    if num_ctx is not None and getattr(provider, "supports_num_ctx", False):
        extra["num_ctx"] = num_ctx
    if request_timeout is not None and getattr(provider, "supports_per_call_timeout", False):
        extra["timeout"] = request_timeout
    if keep_alive is not None and getattr(provider, "supports_keep_alive", False):
        extra["keep_alive"] = keep_alive
    structured = getattr(provider, "generate_structured", None)
    if callable(structured):
        kwargs = {
            "system": PLANNER_SYSTEM_PROMPT,
            "user": user,
            "response_schema": task_plan_response_schema(extraction),
            **extra,
        }
        if (
            max_output_tokens is not None
            and getattr(provider, "supports_per_call_output_tokens", False)
        ):
            kwargs["max_output_tokens"] = max_output_tokens
        return await structured(**kwargs)
    # Keep scripted test providers compatible; live Ollama uses structured output.
    return await provider.generate(system=PLANNER_SYSTEM_PROMPT, user=user, **extra)


async def decompose_plan(
    provider: Any,
    request: str,
    planning_context: str = "",
    metrics: RunMetrics | None = None,
    *,
    extraction: ObligationConcernExtraction | None = None,
    max_repairs: int = 1,
    max_output_tokens: int | None = None,
    num_ctx: int | None = None,
    request_timeout: float | None = None,
    keep_alive: str | int | float | None = None,
) -> PlanningResult:
    """Build a TaskPlan with one bounded invalid-output repair at most."""

    if max_repairs not in (0, 1):
        raise ValueError("max_repairs must be 0 or 1")
    metrics = metrics or RunMetrics()
    try:
        understanding = understand_request(request)
    except ValueError as error:
        return PlanningResult(request=str(request), warnings=[_safe_warning(error)])

    prompt = build_task_plan_prompt(
        understanding.normalized_request, planning_context, extraction
    )
    try:
        result = await generate_task_plan(
            provider,
            user=prompt,
            extraction=extraction,
            max_output_tokens=max_output_tokens,
            num_ctx=num_ctx,
            request_timeout=request_timeout,
            keep_alive=keep_alive,
        )
        metrics.add_usage(result.usage)
    except Exception as error:
        return PlanningResult(
            request=understanding.normalized_request,
            warnings=[_safe_warning(error)],
        )

    try:
        plan = parse_task_plan_output(
            result.text, understanding.normalized_request, extraction
        )
        plan = canonicalize_task_plan(plan)
        return PlanningResult(
            request=understanding.normalized_request,
            plan=plan,
            status="COMPLETE",
        )
    except (TypeError, ValueError) as first_error:
        if max_repairs == 0:
            return PlanningResult(
                request=understanding.normalized_request,
                warnings=[_safe_warning(first_error)],
            )
        repair_prompt = build_task_plan_repair_prompt(
            understanding.normalized_request,
            str(getattr(result, "text", "")),
            str(first_error),
            planning_context,
            extraction,
        )
        try:
            repaired = await generate_task_plan(
                provider,
                user=repair_prompt,
                extraction=extraction,
                max_output_tokens=max_output_tokens,
                num_ctx=num_ctx,
                request_timeout=request_timeout,
                keep_alive=keep_alive,
            )
            metrics.add_usage(repaired.usage)
            plan = parse_task_plan_output(
                repaired.text, understanding.normalized_request, extraction
            )
            plan = canonicalize_task_plan(plan)
        except Exception as second_error:
            return PlanningResult(
                request=understanding.normalized_request,
                warnings=[_safe_warning(first_error), _safe_warning(second_error)],
                repair_attempted=True,
            )
        return PlanningResult(
            request=understanding.normalized_request,
            plan=plan,
            status="COMPLETE",
            repair_attempted=True,
        )


# Descriptive alias for callers that use the planning rather than decomposition
# vocabulary.  It remains bounded by ``decompose_plan``'s single repair.
build_task_plan = decompose_plan
