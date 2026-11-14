"""Deterministic parameterized checks for OpenAPI documents."""

from __future__ import annotations

import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .openapi_inspect import OpenApiSummary, inspect


class CheckError(ValueError):
    """An unknown check or invalid check parameters."""


class Violation(BaseModel):
    path: str
    method: str
    location: str
    message: str


class CheckResult(BaseModel):
    name: str
    params: dict[str, Any]
    passed: bool
    violations: list[Violation] = Field(default_factory=list)


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecurityParams(_Params):
    allow_public_paths: list[str] = Field(default_factory=list)


class ErrorResponsesParams(_Params):
    required_status_codes: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=lambda: ["get", "put", "post", "delete", "patch"])


class NamingParams(_Params):
    style: Literal["kebab", "snake", "camel"]
    ignore: list[str] = Field(default_factory=list)


class PaginationParams(_Params):
    param_names: list[str] = Field(default_factory=lambda: ["page", "limit", "cursor"])


class EmptyParams(_Params):
    pass


class RequiredFieldsParams(_Params):
    require: Literal["description", "example"]


class ContentTypesParams(_Params):
    allowed: list[str]


def _raw(doc: Any) -> tuple[OpenApiSummary, dict[str, Any]]:
    summary = inspect(doc)
    if isinstance(doc, str):
        import json
        try:
            raw = json.loads(doc)
        except json.JSONDecodeError:
            import yaml
            raw = yaml.safe_load(doc)
        if not isinstance(raw, dict):
            raw = {}
    elif isinstance(doc, dict):
        raw = doc
    else:
        raw = {}
    return summary, raw


def _ops(summary: OpenApiSummary):
    return sorted(summary.operations, key=lambda op: (op.path, op.method))


def _violation(path: str, method: str, location: str, message: str) -> Violation:
    return Violation(path=path, method=method, location=location, message=message)


def _finish(name: str, params: BaseModel, violations: list[Violation]) -> CheckResult:
    violations.sort(key=lambda v: (v.path, v.method, v.location))
    return CheckResult(name=name, params=params.model_dump(), passed=not violations, violations=violations)


def _security(s: OpenApiSummary, raw: dict, p: SecurityParams) -> list[Violation]:
    return [_violation(o.path, o.method, "security", "Operation has no security requirement")
            for o in _ops(s) if not o.security and o.path not in p.allow_public_paths]


def _errors(s: OpenApiSummary, raw: dict, p: ErrorResponsesParams) -> list[Violation]:
    statuses = set(p.required_status_codes)
    methods = {m.lower() for m in p.methods}
    return [_violation(o.path, o.method, f"responses:{status}", f"Required error response {status} is undocumented")
            for o in _ops(s) if o.method in methods
            for status in sorted(statuses - set(o.responses))]


def _naming(s: OpenApiSummary, raw: dict, p: NamingParams) -> list[Violation]:
    patterns = {"kebab": r"^[a-z0-9]+(?:-[a-z0-9]+)*$", "snake": r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
                "camel": r"^[a-z][A-Za-z0-9]*$"}
    return [_violation(o.path, o.method, "path", f"Path does not follow {p.style} naming convention")
            for o in _ops(s) if o.path not in p.ignore
            if any(not re.fullmatch(patterns[p.style], seg) for seg in o.path.strip("/").split("/")
                   if seg and not (seg.startswith("{") and seg.endswith("}")))]


def _is_array_response(op: Any, raw: dict) -> bool:
    response = op.responses.get("200")
    if not response:
        return False
    if response.schema_type == "array" or (response.schema_type or "").startswith("array["):
        return True
    raw_op = raw.get("paths", {}).get(op.path, {}).get(op.method, {})
    schema = raw_op.get("responses", {}).get("200", {}).get("content", {})
    for media in schema.values() if isinstance(schema, dict) else []:
        sch = media.get("schema", {}) if isinstance(media, dict) else {}
        if isinstance(sch, dict) and (sch.get("type") == "array" or "items" in sch):
            return True
        props = sch.get("properties", {}) if isinstance(sch, dict) else {}
        if isinstance(props, dict):
            items = props.get("items")
            if isinstance(items, dict) and (items.get("type") == "array" or "items" in items):
                return True
    return False


def _pagination(s: OpenApiSummary, raw: dict, p: PaginationParams) -> list[Violation]:
    return [_violation(o.path, o.method, "parameters", "List endpoint lacks a pagination parameter")
            for o in _ops(s) if o.method == "get" and _is_array_response(o, raw)
            if not ({x.name for x in o.parameters} & set(p.param_names))]


def _ids(s: OpenApiSummary, raw: dict, p: EmptyParams) -> list[Violation]:
    counts: dict[str, int] = {}
    for op in s.operations:
        if op.operation_id:
            counts[op.operation_id] = counts.get(op.operation_id, 0) + 1
    out = []
    for op in _ops(s):
        if not op.operation_id:
            out.append(_violation(op.path, op.method, "operationId", "Operation ID is missing"))
        elif counts[op.operation_id] > 1:
            out.append(_violation(op.path, op.method, "operationId", f"Operation ID '{op.operation_id}' is duplicated"))
    return out


def _required(s: OpenApiSummary, raw: dict, p: RequiredFieldsParams) -> list[Violation]:
    roots = raw.get("components", {}).get("schemas", {})
    if raw.get("swagger") == "2.0":
        roots = raw.get("definitions", {})
    out = []
    for name, schema in sorted(roots.items()) if isinstance(roots, dict) else []:
        if not isinstance(schema, dict):
            continue
        props = schema.get("properties", {})
        for field in sorted(schema.get("required", [])):
            prop = props.get(field, {}) if isinstance(props, dict) else {}
            key = "description" if p.require == "description" else "example"
            if not isinstance(prop, dict) or not prop.get(key):
                out.append(_violation("", "", f"schema:{name}.{field}", f"Required field lacks {p.require}"))
    return out


def _deprecated(s: OpenApiSummary, raw: dict, p: EmptyParams) -> list[Violation]:
    out = []
    for op in _ops(s):
        data = raw.get("paths", {}).get(op.path, {}).get(op.method, {})
        description = data.get("description", "")
        replacement_text = isinstance(description, str) and re.search(
            r"\b(replac(?:ed|ement)|supersed(?:ed|es)|migrat(?:e|ion)|use\b.+\binstead)\b",
            description, re.IGNORECASE,
        )
        if data.get("deprecated") and not (data.get("x-replaced-by") or data.get("x-replacement") or replacement_text):
            out.append(_violation(op.path, op.method, "deprecated", "Deprecated operation has no documented replacement"))
    return out


def _content(s: OpenApiSummary, raw: dict, p: ContentTypesParams) -> list[Violation]:
    allowed = {x.lower() for x in p.allowed}
    return [_violation(o.path, o.method, f"requestBody:{media}", f"Request body content type '{media}' is not allowed")
            for o in _ops(s) if o.request_body
            for media in o.request_body.content_types if media.lower() not in allowed]


CHECKS: dict[str, tuple[str, type[BaseModel], Callable]] = {
    "all_operations_have_security": ("Every operation has security unless its path is allow-listed.", SecurityParams, _security),
    "error_responses_documented": ("Selected methods document each required error status.", ErrorResponsesParams, _errors),
    "path_naming_convention": ("Path segments follow the selected naming style.", NamingParams, _naming),
    "list_endpoints_paginated": ("GET operations returning arrays define a pagination parameter.", PaginationParams, _pagination),
    "operation_ids_unique_and_present": ("Every operation ID is present and unique.", EmptyParams, _ids),
    "required_fields_have_examples_or_descriptions": ("Required schema fields include the selected metadata.", RequiredFieldsParams, _required),
    "deprecated_operations_documented_replacement": ("Deprecated operations describe a replacement.", EmptyParams, _deprecated),
    "request_body_content_types": ("Request body media types belong to the allowed list.", ContentTypesParams, _content),
}


def _parse_params(model: type[BaseModel], params: dict[str, Any]) -> BaseModel:
    try:
        return model.model_validate(params)
    except (ValidationError, ValueError, TypeError) as exc:
        raise CheckError(str(exc)) from exc


def run_check(name: str, doc: Any, params: dict[str, Any]) -> CheckResult:
    if name not in CHECKS:
        raise CheckError(f"Unknown check: {name}")
    _, model, check = CHECKS[name]
    parsed = _parse_params(model, params)
    try:
        summary, raw = _raw(doc)
        return _finish(name, parsed, check(summary, raw, parsed))
    except CheckError:
        raise
    except Exception as exc:
        raise CheckError(str(exc)) from exc


def list_checks() -> list[dict[str, Any]]:
    return [{"name": name, "description": description, "params_schema": model.model_json_schema()}
            for name, (description, model, _) in CHECKS.items()]


def run_checks(doc: Any, specs: list[dict[str, Any]]) -> list[CheckResult]:
    results = []
    for spec in specs:
        if not isinstance(spec, dict) or not isinstance(spec.get("name"), str):
            raise CheckError("Each check spec must contain a string name")
        params = spec.get("params", {})
        if not isinstance(params, dict):
            raise CheckError("Check params must be an object")
        results.append(run_check(spec["name"], doc, params))
    return results
