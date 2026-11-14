from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[2]))
BASE = {
    "openapi": "3.0.3", "info": {"title": "Widgets", "version": "1"},
    "paths": {
        "/widgets": {"get": {
            "operationId": "listWidgets", "security": [{"apiKey": []}],
            "parameters": [{"name": "page", "in": "query", "required": False, "schema": {"type": "integer"}}],
            "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Widget"}}}}}, "400": {"description": "bad request"}},
        }},
        "/widgets/{widgetId}": {"get": {
            "operationId": "getWidget", "security": [{"apiKey": []}],
            "parameters": [{"name": "widgetId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Widget"}}}}},
        }},
    },
    "components": {"schemas": {"Widget": {"type": "object", "required": ["id", "state"], "properties": {
        "id": {"type": "string", "description": "Identifier"},
        "state": {"type": "string", "description": "Current state", "enum": ["active", "paused", "retired"]},
        "label": {"type": "string", "description": "Display label"},
    }}}},
}


def clone():
    return copy.deepcopy(BASE)


def make_scenarios():
    scenarios = {}
    old, new = clone(), clone()
    new["paths"]["/widgets/search"] = {"post": {"operationId": "searchWidgets", "security": [{"apiKey": []}], "responses": {"200": {"description": "ok"}}}}
    scenarios["endpoint_added"] = (old, new)

    old, new = clone(), clone()
    del new["paths"]["/widgets/{widgetId}"]
    scenarios["endpoint_removed"] = (old, new)

    old, new = clone(), clone()
    new["paths"]["/widgets/{id}"] = new["paths"].pop("/widgets/{widgetId}")
    old["paths"]["/widgets/{widgetId}"]["get"]["parameters"][0]["name"] = "widgetId"
    new["paths"]["/widgets/{id}"]["get"]["parameters"][0]["name"] = "id"
    scenarios["parameter_renamed"] = (old, new)

    old, new = clone(), clone()
    old["paths"]["/widgets/{widgetId}"]["get"]["parameters"][0]["required"] = True
    new["paths"]["/widgets/{widgetId}"]["get"]["parameters"][0]["required"] = False
    scenarios["required_to_optional"] = (old, new)

    old, new = clone(), clone()
    new["components"]["schemas"]["Widget"]["properties"]["state"]["enum"] = ["active"]
    scenarios["enum_narrowing"] = (old, new)

    old, new = clone(), clone()
    del new["components"]["schemas"]["Widget"]["properties"]["label"]
    scenarios["response_schema_property_removed"] = (old, new)

    old, new = clone(), clone()
    del old["paths"]["/widgets"]["get"]["security"]
    scenarios["auth_added"] = (old, new)

    old, new = clone(), clone()
    del new["paths"]["/widgets"]["get"]["security"]
    scenarios["auth_removed"] = (old, new)

    old, new = clone(), clone()
    new["paths"]["/widgets/{widgetId}"]["get"].update({"deprecated": True, "description": "Use GET /widgets instead.", "x-replaced-by": "GET /widgets"})
    scenarios["deprecation"] = (old, new)

    old, new = clone(), clone()
    old["paths"]["/widgets/{widgetId}"]["get"]["requestBody"] = {
        "required": False, "content": {"application/json": {"schema": {"type": "string"}}}}
    new["paths"]["/widgets/{widgetId}"]["get"]["requestBody"] = {
        "required": False, "content": {"text/plain": {"schema": {"type": "string"}}}}
    scenarios["content_type_change"] = (old, new)

    old, new = clone(), clone()
    old["components"]["schemas"]["Widget"]["properties"]["label"] = {"$ref": "#/components/schemas/Label"}
    old["components"]["schemas"]["Label"] = {"$ref": "#/components/schemas/LabelValue"}
    old["components"]["schemas"]["LabelValue"] = {"type": "string"}
    new = copy.deepcopy(old)
    scenarios["ref_chain"] = (old, new)

    old = {
        "swagger": "2.0", "info": {"title": "Widgets", "version": "1"},
        "host": "api.example.test", "basePath": "/v1", "schemes": ["https"],
        "paths": {"/widgets": {"get": {
            "operationId": "listWidgets", "security": [{"apiKey": []}],
            "responses": {"200": {"description": "ok", "schema": {
                "type": "array", "items": {"type": "string"}}}},
        }}},
        "securityDefinitions": {"apiKey": {"type": "apiKey", "name": "key", "in": "header"}},
    }
    new = {
        "openapi": "3.0.3", "info": {"title": "Widgets", "version": "2"},
        "servers": [{"url": "https://api.example.test/v1"}],
        "paths": {"/widgets": {"get": {
            "operationId": "listWidgets", "security": [{"apiKey": []}],
            "responses": {"200": {"description": "ok", "content": {
                "application/json": {"schema": {"type": "array", "items": {"type": "string"}}}}}},
        }}},
        "components": {"securitySchemes": {"apiKey": {"type": "apiKey", "name": "key", "in": "header"}}},
    }
    scenarios["swagger_2_to_3"] = (old, new)

    old, new = clone(), clone()
    yaml_text = '''openapi: 3.0.3\ninfo:\n  title: Widgets YAML\n  version: "2"\npaths:\n  /widgets:\n    get:\n      operationId: listWidgets\n      security:\n        - apiKey: []\n      responses:\n        "200":\n          description: ok\n          content:\n            application/json:\n              schema:\n                type: array\n                items:\n                  type: string\n        "400":\n          description: bad request\ncomponents:\n  securitySchemes:\n    apiKey:\n      type: apiKey\n      name: key\n      in: header\n'''
    scenarios["yaml_variant"] = (old, yaml_text)

    old, new = clone(), clone()
    scenarios["identical"] = (old, new)

    scenarios["invalid_document"] = ('{"info":{"title":"Not an API"}}', '{"info":{"title":"Still not an API"}}')
    return scenarios


def _json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(type(value).__name__)


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalized_diff(old, new):
    from app.review.tools.openapi_diff import diff
    try:
        return diff(old, new).model_dump(mode="json")
    except Exception as exc:
        return {"error_type": type(exc).__name__, "message": str(exc)}


CHECK_SPECS = [
    {"name": "all_operations_have_security", "params": {"allow_public_paths": []}},
    {"name": "error_responses_documented", "params": {"required_status_codes": ["400", "401"], "methods": ["get", "post"]}},
    {"name": "path_naming_convention", "params": {"style": "kebab", "ignore": []}},
    {"name": "operation_ids_unique_and_present", "params": {}},
]


def normalized_checks(doc):
    from app.review.tools.openapi_checks import run_checks
    try:
        return [item.model_dump(mode="json") for item in run_checks(doc, CHECK_SPECS)]
    except Exception as exc:
        return {"error_type": type(exc).__name__, "message": str(exc)}


def normalized_spec_change(scenario: str, old, new):
    from datetime import datetime, timezone
    from app.review.schemas import Requirement, ReviewCase
    from app.review_adapters.spec_change_engine import SpecChangeEngine

    case = ReviewCase(id=f"golden-{scenario}", owner_user_id="fixture-user", title=scenario,
                      request_text="Golden corpus characterization", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    engine = SpecChangeEngine(lambda _: old, lambda _: new)
    proposed = engine.propose_requirements(case)
    requirements = [Requirement(id=req.id, case_id=req.case_id, text=req.text, origin=req.origin,
                                confirmed=True, order=req.order) for req in proposed]
    requirements.append(Requirement(id=f"{case.id}:unrelated", case_id=case.id,
                                    text="Verify an unrelated billing concern", origin="USER", confirmed=True,
                                    order=len(requirements)))
    if scenario == "invalid_document":
        requirements = [Requirement(id=f"{case.id}:invalid", case_id=case.id, text="GET /widgets",
                                    origin="USER", confirmed=True, order=0)]
    findings = engine.run(case, requirements, None, lambda *_: None)
    return {
        "proposed_requirements": [r.text for r in proposed],
        "findings": [{"requirement_text": next((r.text for r in requirements if r.id == f.requirement_id), ""),
                      "verdict": f.verdict.value,
                      "evidence_ids": [e.evidence_id for e in f.evidence]} for f in findings],
    }


def main() -> None:
    for name, (old, new) in make_scenarios().items():
        directory = ROOT / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "expected").mkdir(parents=True, exist_ok=True)
        # Keep the required filenames; a YAML scenario intentionally stores YAML text in new.json.
        old_text = old if isinstance(old, str) else json.dumps(old, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        new_text = new if isinstance(new, str) else json.dumps(new, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        (directory / "old.json").write_text(old_text, encoding="utf-8")
        (directory / "new.json").write_text(new_text, encoding="utf-8")
        write_json(directory / "expected" / "diff.json", normalized_diff(old_text, new_text))
        write_json(directory / "expected" / "checks.json", normalized_checks(new_text))
        write_json(directory / "expected" / "spec_change.json", normalized_spec_change(name, old_text, new_text))


if __name__ == "__main__":
    main()
