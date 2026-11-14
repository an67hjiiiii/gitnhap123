"""Stable semantic comparison rules for summarized OpenAPI documents.

Breaking changes include removals, newly required inputs, requiredness changes
that make a previously optional input mandatory, narrowed schema types, removed
response/schema fields or enum values, and security changes. Additions that do
not constrain existing clients are non-breaking. Description-only response
changes are informational.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .openapi_inspect import OpenApiSummary, inspect


class Change(BaseModel):
    kind: str
    severity: Literal["BREAKING", "NON_BREAKING", "INFO"]
    path: str = ""
    method: str = ""
    location: str = ""
    detail: str = ""


class OpenApiDiff(BaseModel):
    changes: list[Change] = Field(default_factory=list)

    def to_markdown(self) -> str:
        if not self.changes:
            return "# OpenAPI changes\n\nNo changes detected."
        rows = ["# OpenAPI changes", "", "| Severity | Change | Location | Detail |", "|---|---|---|---|"]
        for c in self.changes:
            loc = " ".join(x for x in (c.method.upper(), c.path, c.location) if x).replace("|", "\\|")
            detail = c.detail.replace("|", "\\|").replace("\n", " ")
            rows.append(f"| {c.severity} | {c.kind} | {loc} | {detail} |")
        return "\n".join(rows)


def _summary(doc: str | dict | OpenApiSummary) -> OpenApiSummary:
    return doc if isinstance(doc, OpenApiSummary) else inspect(doc)


def diff(old: str | dict | OpenApiSummary, new: str | dict | OpenApiSummary) -> OpenApiDiff:
    """Compare two documents and return changes in deterministic order."""
    a, b = _summary(old), _summary(new)
    changes: list[Change] = []
    old_paths = {o.path for o in a.operations}
    new_paths = {o.path for o in b.operations}
    old_ops = {(o.path, o.method): o for o in a.operations}
    new_ops = {(o.path, o.method): o for o in b.operations}
    for path in sorted(old_paths - new_paths):
        changes.append(Change(kind="ENDPOINT_REMOVED", severity="BREAKING", path=path, detail="Endpoint removed"))
    for path in sorted(new_paths - old_paths):
        changes.append(Change(kind="ENDPOINT_ADDED", severity="NON_BREAKING", path=path, detail="Endpoint added"))
    # Method-level additions/removals apply only where at least one method remains.
    for key in sorted(old_ops.keys() - new_ops.keys()):
        path, method = key
        if path in new_paths:
            changes.append(Change(kind="METHOD_REMOVED", severity="BREAKING", path=path, method=method, detail="Method removed"))
    for key in sorted(new_ops.keys() - old_ops.keys()):
        path, method = key
        if path in old_paths:
            changes.append(Change(kind="METHOD_ADDED", severity="NON_BREAKING", path=path, method=method, detail="Method added"))
    for key in sorted(old_ops.keys() & new_ops.keys()):
        path, method = key
        x, y = old_ops[key], new_ops[key]
        xp = {(p.name, p.in_): p for p in x.parameters}
        yp = {(p.name, p.in_): p for p in y.parameters}
        for pkey in sorted(xp.keys() - yp.keys()):
            p = xp[pkey]
            changes.append(Change(kind="PARAM_REMOVED", severity="NON_BREAKING" if not p.required else "BREAKING", path=path, method=method, location=f"parameter:{p.in_}:{p.name}", detail="Parameter removed"))
        for pkey in sorted(yp.keys() - xp.keys()):
            p = yp[pkey]
            changes.append(Change(kind="PARAM_ADDED", severity="BREAKING" if p.required else "NON_BREAKING", path=path, method=method, location=f"parameter:{p.in_}:{p.name}", detail="Parameter added"))
        for pkey in sorted(xp.keys() & yp.keys()):
            p, q = xp[pkey], yp[pkey]
            loc = f"parameter:{p.in_}:{p.name}"
            if p.required != q.required:
                changes.append(Change(kind="PARAM_REQUIRED_CHANGED", severity="BREAKING" if q.required else "NON_BREAKING", path=path, method=method, location=loc, detail=f"Required changed from {p.required} to {q.required}"))
            if p.schema_type != q.schema_type:
                changes.append(Change(kind="PARAM_TYPE_CHANGED", severity="BREAKING", path=path, method=method, location=loc, detail=f"Type changed from {p.schema_type} to {q.schema_type}"))
        xb, yb = x.request_body, y.request_body
        if xb and yb and xb.required != yb.required:
            changes.append(Change(kind="REQUEST_BODY_REQUIRED_CHANGED", severity="BREAKING" if yb.required else "NON_BREAKING", path=path, method=method, location="requestBody", detail=f"Required changed from {xb.required} to {yb.required}"))
        elif xb is None and yb and yb.required:
            changes.append(Change(kind="REQUEST_BODY_REQUIRED_CHANGED", severity="BREAKING", path=path, method=method, location="requestBody", detail="Required request body added"))
        if xb is not None and yb is not None:
            added_types = sorted(set(yb.content_types) - set(xb.content_types))
            removed_types = sorted(set(xb.content_types) - set(yb.content_types))
            if added_types or removed_types:
                details = []
                if added_types:
                    details.append(f"added: {', '.join(added_types)}")
                if removed_types:
                    details.append(f"removed: {', '.join(removed_types)}")
                changes.append(Change(
                    kind="REQUEST_BODY_CONTENT_TYPE_CHANGED",
                    severity="BREAKING" if removed_types else "NON_BREAKING",
                    path=path, method=method, location="requestBody:content",
                    detail="Request body media types " + "; ".join(details),
                ))
        xr, yr = x.responses, y.responses
        for status in sorted(xr.keys() - yr.keys()):
            changes.append(Change(kind="RESPONSE_REMOVED", severity="BREAKING", path=path, method=method, location=f"response:{status}", detail="Response removed"))
        for status in sorted(yr.keys() - xr.keys()):
            changes.append(Change(kind="RESPONSE_ADDED", severity="NON_BREAKING", path=path, method=method, location=f"response:{status}", detail="Response added"))
        for status in sorted(xr.keys() & yr.keys()):
            p, q = xr[status], yr[status]
            if p.schema_type != q.schema_type:
                changes.append(Change(kind="RESPONSE_SCHEMA_CHANGED", severity="BREAKING", path=path, method=method, location=f"response:{status}", detail=f"Schema changed from {p.schema_type} to {q.schema_type}"))
            elif p.description != q.description:
                changes.append(Change(kind="RESPONSE_SCHEMA_CHANGED", severity="INFO", path=path, method=method, location=f"response:{status}:description", detail="Response description changed"))
        if x.security != y.security:
            changes.append(Change(kind="SECURITY_CHANGED", severity="BREAKING", path=path, method=method, location="security", detail="Operation security requirements changed"))
    for name in sorted(a.schemas.keys() | b.schemas.keys()):
        x, y = a.schemas.get(name), b.schemas.get(name)
        xp, yp = (x.properties if x else {}), (y.properties if y else {})
        xr, yr = set(x.required if x else []), set(y.required if y else [])
        for prop in sorted(xp.keys() - yp.keys()):
            changes.append(Change(kind="SCHEMA_PROPERTY_REMOVED", severity="BREAKING", location=f"schema:{name}.{prop}", detail="Schema property removed"))
        for prop in sorted(yp.keys() - xp.keys()):
            changes.append(Change(kind="SCHEMA_PROPERTY_ADDED", severity="BREAKING" if prop in yr else "NON_BREAKING", location=f"schema:{name}.{prop}", detail="Schema property added"))
        for prop in sorted(xp.keys() & yp.keys()):
            if xp[prop] != yp[prop]:
                changes.append(Change(kind="SCHEMA_PROPERTY_TYPE_CHANGED", severity="BREAKING", location=f"schema:{name}.{prop}", detail=f"Type changed from {xp[prop]} to {yp[prop]}"))
            if (prop in xr) != (prop in yr):
                changes.append(Change(kind="SCHEMA_PROPERTY_REQUIRED_CHANGED", severity="BREAKING" if prop in yr else "NON_BREAKING", location=f"schema:{name}.{prop}", detail=f"Required changed from {prop in xr} to {prop in yr}"))
    # Canonical enum extraction from source summaries is not lossy: inspector stores values on schemas.
    for name in sorted(a.schemas.keys() & b.schemas.keys()):
        ae = getattr(a.schemas[name], "enum_values", {})
        be = getattr(b.schemas[name], "enum_values", {})
        for prop in sorted(ae.keys() | be.keys()):
            before, after = set(ae.get(prop, [])), set(be.get(prop, []))
            for value in sorted(before - after, key=str):
                changes.append(Change(kind="ENUM_VALUE_REMOVED", severity="BREAKING", location=f"schema:{name}.{prop}", detail=f"Enum value removed: {value}"))
            for value in sorted(after - before, key=str):
                changes.append(Change(kind="ENUM_VALUE_ADDED", severity="NON_BREAKING", location=f"schema:{name}.{prop}", detail=f"Enum value added: {value}"))
    order = {"ENDPOINT_REMOVED": 0, "ENDPOINT_ADDED": 1, "METHOD_REMOVED": 2, "METHOD_ADDED": 3}
    changes.sort(key=lambda c: (c.path, c.method, order.get(c.kind, 4), c.location, c.kind, c.detail))
    return OpenApiDiff(changes=changes)
