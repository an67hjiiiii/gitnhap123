"""Deterministic, read-only inspection of OpenAPI and Swagger documents."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


class OpenApiParseError(ValueError):
    """Raised when an input is too large, malformed, or not an API document."""


class Parameter(BaseModel):
    name: str
    in_: str = Field(alias="in")
    required: bool = False
    schema_type: str | None = None


class RequestBody(BaseModel):
    required: bool = False
    content_types: list[str] = Field(default_factory=list)
    schema_ref: str | None = None
    schema_type: str | None = None


class Response(BaseModel):
    description: str = ""
    schema_type: str | None = None


class Operation(BaseModel):
    method: str
    path: str
    operation_id: str | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    request_body: RequestBody | None = None
    responses: dict[str, Response] = Field(default_factory=dict)
    security: list[dict[str, list[str]]] = Field(default_factory=list)


class SchemaSummary(BaseModel):
    properties: dict[str, str | None] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    enum_values: dict[str, list[Any]] = Field(default_factory=dict)


class OpenApiSummary(BaseModel):
    version: str
    title: str
    api_version: str = ""
    servers: list[str] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    schemas: dict[str, SchemaSummary] = Field(default_factory=dict)
    resolved_refs: list[str] = Field(default_factory=list)
    unresolved_refs: list[str] = Field(default_factory=list)


def _type(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    if "$ref" in schema:
        return str(schema["$ref"])
    value = schema.get("type")
    if isinstance(value, list):
        return "|".join(sorted(str(v) for v in value))
    if value == "array" and isinstance(schema.get("items"), dict):
        inner = _type(schema["items"])
        return f"array[{inner}]" if inner else "array"
    return str(value) if value is not None else None


def _resolve(doc: dict[str, Any], value: Any, depth: int = 0, seen: set[str] | None = None,
             refs: set[str] | None = None, unresolved: set[str] | None = None) -> Any:
    if not isinstance(value, dict):
        return value
    seen = set() if seen is None else seen
    refs = set() if refs is None else refs
    unresolved = set() if unresolved is None else unresolved
    ref = value.get("$ref")
    if not isinstance(ref, str):
        return {k: _resolve(doc, v, depth, seen, refs, unresolved) for k, v in value.items()}
    if not ref.startswith("#/"):
        unresolved.add(ref)
        return value
    if depth >= 10:
        unresolved.add(ref)
        return value
    if ref in seen:
        refs.add(ref)
        return value
    target: Any = doc
    try:
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError):
        unresolved.add(ref)
        return value
    refs.add(ref)
    if not isinstance(target, dict):
        return target
    merged = {k: v for k, v in value.items() if k != "$ref"}
    merged.update(target)
    return _resolve(doc, merged, depth + 1, seen | {ref}, refs, unresolved)


def _parse(doc: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(doc, str):
        if len(doc.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise OpenApiParseError("OpenAPI document exceeds the 2 MB size limit")
        try:
            parsed = json.loads(doc)
        except (json.JSONDecodeError, UnicodeError):
            try:
                import yaml
                parsed = yaml.safe_load(doc)
            except ImportError as exc:
                raise OpenApiParseError("YAML input is unavailable because PyYAML is not installed") from exc
            except Exception as exc:
                raise OpenApiParseError(f"Invalid JSON or YAML document: {exc}") from exc
    elif isinstance(doc, dict):
        try:
            if len(json.dumps(doc, ensure_ascii=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
                raise OpenApiParseError("OpenAPI document exceeds the 2 MB size limit")
        except (TypeError, ValueError) as exc:
            raise OpenApiParseError("Document must contain JSON-compatible values") from exc
        parsed = doc
    else:
        raise OpenApiParseError("Document must be a JSON/YAML string or a dictionary")
    if not isinstance(parsed, dict):
        raise OpenApiParseError("Document root must be an object")
    version = parsed.get("openapi")
    swagger = parsed.get("swagger")
    if not (isinstance(version, str) and version.startswith(("3.0", "3.1"))) and swagger != "2.0":
        raise OpenApiParseError("Document must declare OpenAPI 3.0/3.1 or Swagger 2.0")
    if not isinstance(parsed.get("info"), dict) or not isinstance(parsed.get("paths"), dict):
        raise OpenApiParseError("OpenAPI document must contain info and paths objects")
    return parsed


def inspect(doc: str | dict[str, Any]) -> OpenApiSummary:
    """Return a stable summary; remote references are recorded but never fetched."""
    raw = _parse(doc)
    swagger = raw.get("swagger") == "2.0"
    refs: set[str] = set()
    unresolved: set[str] = set()
    operations: list[Operation] = []
    consumes = raw.get("consumes", []) if swagger else []
    produces = raw.get("produces", []) if swagger else []
    for path in sorted(raw["paths"]):
        path_item = raw["paths"][path]
        if not isinstance(path_item, dict):
            continue
        path_params = path_item.get("parameters", [])
        for method in sorted(HTTP_METHODS & set(path_item)):
            op = path_item[method]
            if not isinstance(op, dict):
                continue
            params: dict[tuple[str, str], dict[str, Any]] = {}
            for p in list(path_params if isinstance(path_params, list) else []) + list(op.get("parameters", [])):
                p = _resolve(raw, p, refs=refs, unresolved=unresolved)
                if isinstance(p, dict) and isinstance(p.get("name"), str):
                    params[(p.get("in", ""), p["name"])] = p
            request_body = None
            if swagger:
                body_params = [p for p in params.values() if p.get("in") in ("body", "formData")]
                normal_params = [p for p in params.values() if p.get("in") not in ("body", "formData")]
                params = {(p.get("in", ""), p["name"]): p for p in normal_params}
                if body_params:
                    bp = next((p for p in body_params if p.get("in") == "body"), body_params[0])
                    schema = bp.get("schema", bp)
                    request_body = RequestBody(required=bool(bp.get("required")), content_types=sorted(consumes),
                                               schema_ref=schema.get("$ref") if isinstance(schema, dict) else None,
                                               schema_type=_type(schema))
                elif any(p.get("in") == "formData" for p in body_params):
                    request_body = RequestBody(content_types=sorted(consumes))
            else:
                rb = _resolve(raw, op.get("requestBody"), refs=refs, unresolved=unresolved)
                if isinstance(rb, dict):
                    content = rb.get("content", {})
                    media = sorted(content) if isinstance(content, dict) else []
                    schemas = [content[m].get("schema", {}) for m in media if isinstance(content.get(m), dict)]
                    schema = schemas[0] if schemas else {}
                    request_body = RequestBody(required=bool(rb.get("required")), content_types=media,
                                               schema_ref=schema.get("$ref") if isinstance(schema, dict) else None,
                                               schema_type=_type(schema))
            response_data: dict[str, Response] = {}
            raw_responses = op.get("responses", {})
            if isinstance(raw_responses, dict):
                for status, response in sorted(raw_responses.items(), key=lambda x: str(x[0])):
                    response = _resolve(raw, response, refs=refs, unresolved=unresolved)
                    if not isinstance(response, dict):
                        continue
                    schema = response.get("schema") if swagger else None
                    if not swagger:
                        content = response.get("content", {})
                        if isinstance(content, dict) and content:
                            media = sorted(content)
                            schema = content[media[0]].get("schema", {}) if isinstance(content[media[0]], dict) else {}
                    response_data[str(status)] = Response(description=str(response.get("description", "")), schema_type=_type(schema))
            operations.append(Operation(method=method, path=path, operation_id=op.get("operationId"),
                                        summary=op.get("summary"), tags=sorted(op.get("tags", [])),
                                        parameters=[Parameter(name=p["name"], **{"in": p.get("in", "")},
                                                              required=bool(p.get("required")),
                                                              schema_type=_type(p.get("schema", p)))
                                                    for _, p in sorted(params.items())],
                                        request_body=request_body, responses=response_data,
                                        security=op.get("security", raw.get("security", []))))
    schemas_raw = (raw.get("definitions", {}) if swagger else raw.get("components", {}).get("schemas", {}))
    schemas: dict[str, SchemaSummary] = {}
    if isinstance(schemas_raw, dict):
        for name, schema0 in sorted(schemas_raw.items()):
            schema = schema0 if isinstance(schema0, dict) else {}
            props = schema.get("properties", {})
            if isinstance(props, dict):
                for prop_schema in props.values():
                    _resolve(raw, prop_schema, refs=refs, unresolved=unresolved)
            schemas[name] = SchemaSummary(properties={k: _type(v) for k, v in sorted(props.items())} if isinstance(props, dict) else {},
                                          required=sorted(schema.get("required", [])) if isinstance(schema, dict) else [],
                                          enum_values={k: sorted(v["enum"], key=str) for k, v in sorted(props.items()) if isinstance(v, dict) and isinstance(v.get("enum"), list)} if isinstance(props, dict) else {})
    servers = [str(s.get("url", "")) for s in raw.get("servers", []) if isinstance(s, dict)] if not swagger else [str(raw.get("host", ""))]
    if swagger and raw.get("basePath"):
        servers = [servers[0] + str(raw["basePath"])]
    return OpenApiSummary(version=str(raw.get("openapi", raw.get("swagger"))), title=str(raw["info"].get("title", "")),
                          api_version=str(raw["info"].get("version", "")), servers=servers,
                          operations=operations, schemas=schemas, resolved_refs=sorted(refs),
                          unresolved_refs=sorted(unresolved))
