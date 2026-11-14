import json
import time
from pathlib import Path

import pytest

from app.review.tools.openapi_checks import CheckError, run_check, run_checks, list_checks


FIXTURES = Path(__file__).parent / "fixtures" / "openapi_checks"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,params", [
    ("all_operations_have_security", {"allow_public_paths": []}),
    ("error_responses_documented", {"required_status_codes": ["400", "401"], "methods": ["get", "post"]}),
    ("path_naming_convention", {"style": "kebab"}),
    ("list_endpoints_paginated", {"param_names": ["page"]}),
    ("operation_ids_unique_and_present", {}),
    ("required_fields_have_examples_or_descriptions", {"require": "description"}),
    ("deprecated_operations_documented_replacement", {}),
    ("request_body_content_types", {"allowed": ["application/json"]}),
])
def test_each_check_accepts_good_fixture(name, params):
    result = run_check(name, fixture("good"), params)
    assert result.passed
    assert result.violations == []


@pytest.mark.parametrize("name,params", [
    ("all_operations_have_security", {}),
    ("error_responses_documented", {"required_status_codes": ["404"], "methods": ["get"]}),
    ("path_naming_convention", {"style": "kebab"}),
    ("list_endpoints_paginated", {"param_names": ["offset"]}),
    ("operation_ids_unique_and_present", {}),
    ("required_fields_have_examples_or_descriptions", {"require": "example"}),
    ("deprecated_operations_documented_replacement", {}),
    ("request_body_content_types", {"allowed": ["application/json"]}),
])
def test_each_check_finds_bad_fixture(name, params):
    result = run_check(name, fixture("bad"), params)
    assert not result.passed
    assert result.violations
    assert [(v.path, v.method, v.location) for v in result.violations] == sorted(
        (v.path, v.method, v.location) for v in result.violations)


def test_parameter_variations_and_result_order():
    doc = fixture("bad")
    assert run_check("all_operations_have_security", doc, {"allow_public_paths": ["/bad_path", "/bad_path/{id}", "/missing"]}).passed
    assert run_check("path_naming_convention", doc, {"style": "snake", "ignore": ["/bad_path/{id}", "/missing"]}).passed
    assert run_check("error_responses_documented", doc, {"required_status_codes": ["200"], "methods": ["post"]}).passed
    doc["paths"]["/bad_path"]["get"]["description"] = "This old endpoint remains available."
    assert not run_check("deprecated_operations_documented_replacement", doc, {}).passed
    doc["paths"]["/bad_path"]["get"]["x-replaced-by"] = "/items"
    assert run_check("deprecated_operations_documented_replacement", doc, {}).passed
    specs = [{"name": "operation_ids_unique_and_present", "params": {}}, {"name": "request_body_content_types", "params": {"allowed": ["text/plain"]}}]
    assert [x.name for x in run_checks(doc, specs)] == [x["name"] for x in specs]


def test_unknown_and_invalid_params_are_typed_errors():
    with pytest.raises(CheckError, match="Unknown check"):
        run_check("not_a_check", fixture("good"), {})
    with pytest.raises(CheckError, match="style"):
        run_check("path_naming_convention", fixture("good"), {"style": "bad"})
    with pytest.raises(CheckError, match="unknown"):
        run_check("error_responses_documented", fixture("good"), {"unknown": []})


def test_list_checks_and_determinism():
    assert len(list_checks()) == 8
    doc = fixture("bad")
    first = run_check("operation_ids_unique_and_present", doc, {}).model_dump()
    assert first == run_check("operation_ids_unique_and_present", doc, {}).model_dump()


def test_large_document_smoke_under_two_seconds():
    paths = {f"/resource-{i}": {"get": {"operationId": f"get{i}", "security": [{"key": []}],
              "parameters": [{"name": "page", "in": "query"}], "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "array", "items": {"type": "string"}}}}}}}}
             for i in range(500)}
    doc = {"openapi": "3.0.3", "info": {"title": "Large", "version": "1"}, "paths": paths}
    start = time.perf_counter()
    result = run_check("list_endpoints_paginated", doc, {"param_names": ["page"]})
    elapsed = time.perf_counter() - start
    assert result.passed
    assert elapsed < 2
