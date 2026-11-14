"""Run the in-memory Review API mock for the frontend integration."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.review.schemas import CaseStatus, Confidence, Finding, Verdict

DEV_TOKEN = "review-mock-token"
DEV_USER = {"user_id": "review-mock-user", "role": "USER"}


class AllVerdictsEngine:
    verdicts = list(Verdict)

    def propose_requirements(self, case):
        from app.review.engine import FakeReviewEngine
        return FakeReviewEngine().propose_requirements(case)

    def run(self, case, requirements, budget, emit):
        finding = Finding(id=f"mock-{requirements[0].order}", case_id=case.id,
                          requirement_id=requirements[0].id,
                          verdict=self.verdicts[requirements[0].order % len(self.verdicts)],
                          confidence=Confidence.L0)
        emit(finding)
        return [finding]


def create_mock_app():
    runtime = ReviewRuntime(storage_backend="memory")
    app = FastAPI(title="Review API local mock")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    def current_user(request: Request):
        if request.headers.get("authorization") != f"Bearer {DEV_TOKEN}":
            raise HTTPException(401, "Authentication is required")
        return DEV_USER

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = AllVerdictsEngine
    app.state.review_runtime = runtime
    return app


def seed_complete_case(app):
    """Seed a completed case with one finding for every verdict."""
    runtime = app.state.review_runtime
    service = runtime.service(AllVerdictsEngine())
    verdicts = list(Verdict)
    case = service.create_case(DEV_USER["user_id"], "Review mock demo",
                               ". ".join(f"Check sample requirement {i}" for i in range(len(verdicts))))
    requirements = service.propose_requirements(case.id, DEV_USER["user_id"])
    service.confirm_requirements(case.id, DEV_USER["user_id"])
    service.start_run(case.id, DEV_USER["user_id"])
    # The contract fixture intentionally displays all verdicts together, including the
    # two incomplete verdicts that ordinary service completion classifies as PARTIAL.
    case.status = CaseStatus.COMPLETE
    runtime.repository.save_case(DEV_USER["user_id"], case)
    return case.id


def main():
    import uvicorn

    app = create_mock_app()
    seed_complete_case(app)
    print(f"Review mock token: {DEV_TOKEN}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8020)


if __name__ == "__main__":
    main()
