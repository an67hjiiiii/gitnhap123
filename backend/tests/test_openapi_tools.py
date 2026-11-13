import json
from pathlib import Path

import pytest

from app.review.tools.openapi_diff import diff
from app.review.tools.openapi_inspect import OpenApiParseError, inspect

FIXTURES = Path(__file__).parent / "fixtures" / "openapi"


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_inspect_json_and_local_refs_are_deterministic():
    first = inspect(read("petstore_v1.json"))
    second = inspect(read("petstore_v1.json"))
    assert first.model_dump() == second.model_dump()
    assert [(op.path, op.method) for op in first.operations] == [
        ("/gone", "get"), ("/pets", "get"), ("/pets", "post")
    ]
    assert "#/components/schemas/Node" in first.resolved_refs
    assert first.schemas["Node"].properties["next"] == "#/components/schemas/Node"


def test_yaml_inspection():
    summary = inspect(read("petstore.yaml"))
    assert summary.title == "YAML Pets"
    assert summary.operations[0].path == "/pets"


def test_remote_references_are_reported_unresolved():
    doc = {"openapi": "3.0.0", "info": {"title": "x", "version": "1"}, "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok", "content": {
            "application/json": {"schema": {"$ref": "https://example.test/schema.json"}}
        }}}}}
    }}
    summary = inspect(doc)
    assert summary.resolved_refs == []
    assert summary.unresolved_refs == ["https://example.test/schema.json"]


def test_swagger_20_body_and_form_data_normalization():
    doc = {
        "swagger": "2.0", "info": {"title": "Legacy", "version": "1"}, "paths": {
            "/pets": {"post": {"consumes": ["application/json"], "parameters": [
                {"name": "body", "in": "body", "required": True, "schema": {"type": "object"}},
                {"name": "tag", "in": "formData", "type": "string"},
                {"name": "token", "in": "header", "type": "string"}],
                "responses": {"200": {"description": "ok"}}}}
        }
    }
    op = inspect(doc).operations[0]
    assert op.request_body.required is True
    assert op.request_body.schema_type == "object"
    assert [p.name for p in op.parameters] == ["token"]


def test_diff_emits_each_change_kind_and_is_stable():
    first = diff(read("petstore_v1.json"), read("petstore_v2.json"))
    second = diff(read("petstore_v1.json"), read("petstore_v2.json"))
    assert first.model_dump() == second.model_dump()
    kinds = {change.kind for change in first.changes}
    assert kinds == {
        "ENDPOINT_ADDED", "ENDPOINT_REMOVED", "METHOD_ADDED", "METHOD_REMOVED",
        "PARAM_ADDED", "PARAM_REMOVED", "PARAM_REQUIRED_CHANGED", "PARAM_TYPE_CHANGED",
        "REQUEST_BODY_REQUIRED_CHANGED", "RESPONSE_ADDED", "RESPONSE_REMOVED",
        "RESPONSE_SCHEMA_CHANGED", "SCHEMA_PROPERTY_ADDED", "SCHEMA_PROPERTY_REMOVED",
        "SCHEMA_PROPERTY_TYPE_CHANGED", "SCHEMA_PROPERTY_REQUIRED_CHANGED", "SECURITY_CHANGED",
        "ENUM_VALUE_REMOVED",
    }
    md = first.to_markdown()
    assert md.startswith("# OpenAPI changes")
    assert "BREAKING" in md and "NON_BREAKING" in md


def test_enum_addition_is_reported():
    old = {"openapi": "3.0.0", "info": {"title": "x", "version": "1"}, "paths": {}, "components": {"schemas": {"S": {"properties": {"state": {"type": "string", "enum": ["a"]}}}}}}
    new = json.loads(json.dumps(old))
    new["components"]["schemas"]["S"]["properties"]["state"]["enum"].append("b")
    assert "ENUM_VALUE_ADDED" in {c.kind for c in diff(old, new).changes}


@pytest.mark.parametrize("doc, message", [(read("invalid.json"), "declare OpenAPI"), ("[broken", "Invalid JSON or YAML")])
def test_invalid_documents_raise_typed_error(doc, message):
    with pytest.raises(OpenApiParseError, match=message):
        inspect(doc)


def test_oversize_document_is_rejected():
    with pytest.raises(OpenApiParseError, match="2 MB"):
        inspect(" " * (2 * 1024 * 1024 + 1))
