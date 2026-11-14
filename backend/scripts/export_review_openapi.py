"""Export the review router's filtered OpenAPI contract snapshot."""

import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.review.engine import FakeReviewEngine


def filtered_openapi():
    os.environ["PROVIDER"] = "fake"
    app = FastAPI(title="Local Multi-Agent RAG", version="0.2.0-m0")

    def current_user(request: Request):
        if request.headers.get("x-user", "alice") == "anonymous":
            raise HTTPException(401, "Authentication is required")
        return {"user_id": request.headers.get("x-user", "alice"), "role": "USER"}

    runtime = ReviewRuntime()
    app.include_router(build_router(current_user=current_user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = FakeReviewEngine
    document = app.openapi()
    runtime.runner.shutdown()

    result = {key: value for key, value in document.items() if key != "paths" and key != "components"}
    result["paths"] = {path: value for path, value in document["paths"].items()
                        if path.startswith("/api/review")}
    components = document.get("components", {})
    selected = {}

    def collect(value):
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/"):
                _, _, category, name = ref.split("/", 3)
                selected.setdefault(category, set()).add(name)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(result["paths"])
    while True:
        before = sum(map(len, selected.values()))
        for category, names in list(selected.items()):
            for name in list(names):
                collect(components.get(category, {}).get(name, {}))
        if sum(map(len, selected.values())) == before:
            break
    result["components"] = {
        category: {name: components[category][name] for name in sorted(names)}
        for category, names in sorted(selected.items())
    }
    return result


def main():
    output = Path(__file__).resolve().parents[2] / "contracts" / "review" / "openapi.review.v0.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(filtered_openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
