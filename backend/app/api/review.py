"""Owner-scoped review HTTP API with selectable durable persistence."""

import os
from datetime import datetime, timezone
from threading import RLock
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from app.jobs import EventLog, JobRunner, format_sse
from app.review.engine import FakeReviewEngine
from app.review.repository import InMemoryCaseRepository
from app.review.schemas import CaseStatus, Decision, Evidence, Finding, JobState, Requirement, RequirementOrigin
from app.review_adapters import PipelineReviewEngine
from app.review_adapters.durable_jobs import DurableJobRunner
from app.review_adapters.pg_repository import PostgresCaseRepository
from app.review.service import (
    CaseNotFound, InvalidDecision, RequirementsUnconfirmed, ReviewCaseService, RunCancelled,
)
from app.retrieval.index_identity import IndexingError


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | None = None


def error_responses(*statuses):
    return {
        status: {"model": ErrorBody, "description": "Review API error"}
        for status in statuses
    }


def get_review_engine():
    """Allow explicit fake selection and dependency overrides; otherwise use runtime wiring."""
    return FakeReviewEngine() if os.getenv("REVIEW_ENGINE", "pipeline").lower() == "fake" else None


class ReviewRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                return JSONResponse(status_code=422, content={
                    "code": "VALIDATION_ERROR", "message": "Invalid request",
                    "details": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
                })
            except CaseNotFound:
                return JSONResponse(status_code=404, content={
                    "code": "CASE_NOT_FOUND", "message": "Case not found",
                })
            except RequirementsUnconfirmed:
                return JSONResponse(status_code=409, content={
                    "code": "REQUIREMENTS_UNCONFIRMED", "message": "Confirm all requirements first",
                })
            except InvalidDecision as exc:
                return JSONResponse(status_code=422, content={
                    "code": "VALIDATION_ERROR", "message": str(exc),
                })
            except HTTPException as exc:
                content = exc.detail if isinstance(exc.detail, dict) else {
                    "code": "AUTHENTICATION_REQUIRED" if exc.status_code == 401 else "VALIDATION_ERROR",
                    "message": str(exc.detail),
                }
                return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)

        return wrapped


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CaseInput(Input):
    title: str = Field(min_length=1, max_length=500)
    source_ids: list[str] = Field(default_factory=list)
    request_text: str = Field(min_length=1)


class RequirementInput(Input):
    id: str | None = None
    text: str = Field(min_length=1)
    confirmed: bool = False


class RequirementsInput(Input):
    requirements: list[RequirementInput]


class RunInput(Input):
    budget: dict | None = None


class DecisionInput(Input):
    review: Literal["ACCEPT", "REJECT", "EDIT"]
    edited_text: str | None = None


class _RunEngine:
    """Give engine-local finding IDs a unique HTTP identity for each run."""

    def __init__(self, engine, job_id, event_emit):
        self.engine, self.job_id, self.event_emit = engine, job_id, event_emit

    def run(self, case, requirements, budget, emit):
        def scoped(finding):
            identity = str(uuid5(NAMESPACE_URL, f"{self.job_id}:{finding.requirement_id}:{finding.id}"))
            return finding.model_copy(update={"id": identity})

        def forward(*args):
            if len(args) == 1:
                emit(scoped(args[0]))
            elif args[0] == "finding.created":
                emit(scoped(Finding.model_validate(args[1])))
            else:
                self.event_emit(*args)

        return [scoped(finding) for finding in self.engine.run(
            case, requirements, budget, forward,
        )]


class ReviewRuntime:
    """One repository and one single-worker runner per application instance."""

    def __init__(self, *, pipeline_factory=None, source_store_factory=None,
                 session_factory=None, storage_backend=None):
        self.pipeline_factory = pipeline_factory
        self.source_store_factory = source_store_factory
        backend = (storage_backend or os.getenv("APP_STORAGE_BACKEND", "file")).strip().lower()
        self.durable = backend == "postgres" and session_factory is not None
        self.repository = (PostgresCaseRepository(session_factory) if self.durable
                           else InMemoryCaseRepository())
        self.events = EventLog()
        self.runs = {}
        self.lock = RLock()
        if self.durable:
            self.runner = DurableJobRunner(self.repository, self._work, str(uuid4()), 30, self.now)
            self.events = self.runner
        else:
            self.runner = JobRunner(self._work, self.events, self.now,
                                    lambda: str(uuid4()), max_concurrent=1)

    def startup(self):
        if self.durable:
            self.runner.recover(self.now())
            self.runner.start()

    @staticmethod
    def now():
        return datetime.now(timezone.utc)

    def service(self, engine, evidence=()):
        return ReviewCaseService(self.repository, engine, evidence=evidence)

    def selected_sources(self, owner, source_ids):
        if self.source_store_factory is None:
            return list(source_ids)
        store = self.source_store_factory(owner)
        return [sid for sid in source_ids if store.source(sid) is not None]

    def engine(self):
        if self.pipeline_factory is None or self.source_store_factory is None:
            raise HTTPException(503, {"code": "REVIEW_ENGINE_UNAVAILABLE",
                                      "message": "Review pipeline is not configured"})
        return PipelineReviewEngine(
            pipeline_factory=self.pipeline_factory,
            source_ids_getter=lambda case: self.selected_sources(case.owner_user_id, case.source_ids),
        )

    def mutable(self, owner, case_id):
        self.service(None)._case(case_id, owner)
        if self.durable:
            active = any(job.state in {JobState.QUEUED, JobState.RUNNING}
                         for job in self.repository.get_jobs(owner, case_id))
            if active:
                raise HTTPException(409, {"code": "CASE_RUNNING", "message": "Case has an active run"})
            return
        if any(run["owner"] == owner and run["case_id"] == case_id
               and self.runner.status(job_id).value in {"QUEUED", "RUNNING"}
               for job_id, run in self.runs.items()):
            raise HTTPException(409, {"code": "CASE_RUNNING", "message": "Case has an active run"})

    def _work(self, job_id, run, emit, cancelled):
        owner, case_id = run["owner"], run["case_id"]
        run["started_at"] = self.now()
        case = self.service(None)._case(case_id, owner)
        evidence = []
        if self.source_store_factory is not None:
            source_ids = self.selected_sources(owner, case.source_ids)
            evidence = [Evidence(evidence_id=chunk.chunk_id, source_id=chunk.source_id,
                                 locator=chunk.chunk_id, excerpt=chunk.text)
                        for chunk in self.source_store_factory(owner).chunks(source_ids)]
        selected_engine = run.get("engine")
        if selected_engine is None:
            selected_engine = get_review_engine()
            if selected_engine is None:
                selected_engine = self.engine()
        service = self.service(_RunEngine(selected_engine, job_id, emit), evidence)
        pipeline_events = isinstance(selected_engine, PipelineReviewEngine)

        def check():
            if cancelled():
                raise RunCancelled()

        def finding_created(finding):
            check()
            if not self.durable:
                emit("finding.created", finding.model_dump(mode="json"))
            if finding.verdict.value == "SKIPPED_BUDGET" and not pipeline_events:
                emit("budget.skipped", {"requirement_id": finding.requirement_id})
            emit("task.done", {"requirement_id": finding.requirement_id})

        try:
            check()
            if not pipeline_events:
                emit("task.started", {"case_id": case_id})
            try:
                service.start_run(
                    case_id, owner, run["budget"], emit=finding_created, cancelled=cancelled,
                    job_id=job_id if self.durable else None, attempt=run.get("attempt", 1),
                    checkpoint=(lambda finding: self.runner.checkpoint(job_id, finding)) if self.durable else None,
                )
            except IndexingError as exc:
                code = getattr(exc, "code", None) or "DERIVED_INDEX_UNAVAILABLE"
                emit("error", {"code": code, "message": str(exc)})
                raise
            check()
            complete = service.is_complete(self.repository.get_requirements(owner, case_id),
                                           self.repository.get_findings(owner, case_id))
            run["partial"] = not complete
            return JobState.SUCCEEDED if complete else JobState.PARTIAL
        except RunCancelled:
            if not self.durable:
                case = service._case(case_id, owner)
                case.status = CaseStatus.PARTIAL
                case.updated_at = self.now()
                self.repository.save_case(owner, case)
        finally:
            run["finished_at"] = self.now()

    def owned_run(self, owner, job_id):
        if self.durable:
            job = self.repository.get_job(owner, job_id)
            if job is None:
                raise CaseNotFound(job_id)
            self.service(None)._case(job.case_id, owner)
            return {"owner": owner, "case_id": job.case_id, "budget": job.budget,
                    "started_at": job.started_at, "finished_at": job.finished_at}
        run = self.runs.get(job_id)
        if run is None or run["owner"] != owner:
            raise CaseNotFound(job_id)
        self.service(None)._case(run["case_id"], owner)
        return run

    def case_runs(self, owner, case_id):
        if self.durable:
            return [job.id for job in self.repository.get_jobs(owner, case_id)]
        return [job_id for job_id, value in self.runs.items()
                if value["owner"] == owner and value["case_id"] == case_id]

    def status(self, owner, job_id):
        run = self.owned_run(owner, job_id)
        state = self.runner.status(job_id).value
        events = self.events.read_since(job_id, 0)
        return {
            "id": job_id, "case_id": run["case_id"],
            "state": "PARTIAL" if state == "SUCCEEDED" and run.get("partial") else state,
            "seq": events[-1].seq if events else 0, "budget": run["budget"],
            "started_at": run.get("started_at"), "finished_at": run.get("finished_at"),
        }


def build_router(*, current_user, runtime: ReviewRuntime):
    router = APIRouter(prefix="/api/review", tags=["review"], route_class=ReviewRoute)
    repo = runtime.repository

    def owner(request: Request):
        return str(current_user(request)["user_id"])

    def engine(selected=Depends(get_review_engine)):
        return selected if selected is not None else runtime.engine()

    @router.post("/cases", status_code=201, responses=error_responses(404, 422))
    def create_case(body: CaseInput, user=Depends(owner)):
        if len(runtime.selected_sources(user, body.source_ids)) != len(body.source_ids):
            raise HTTPException(404, {"code": "SOURCE_NOT_FOUND", "message": "Source not found"})
        return runtime.service(None).create_case(user, body.title, body.request_text, body.source_ids)

    @router.get("/cases", responses=error_responses(422))
    def list_cases(user=Depends(owner)):
        return repo.list_cases(user)

    @router.get("/cases/{case_id}", responses=error_responses(404, 422))
    def get_case(case_id: str, user=Depends(owner)):
        case = runtime.service(None)._case(case_id, user)
        return {**case.model_dump(), "requirements": repo.get_requirements(user, case_id),
                "findings": repo.get_findings(user, case_id)}

    @router.get("/cases/{case_id}/inspector", responses=error_responses(404, 422))
    def inspector(case_id: str, run: str | None = Query(default=None), user=Depends(owner)):
        case = runtime.service(None)._case(case_id, user)
        selected = run
        if selected is None:
            matching = runtime.case_runs(user, case_id)
            selected = matching[-1] if matching else None
        run_data = None
        events = []
        if selected is not None:
            try:
                value = runtime.owned_run(user, selected)
            except CaseNotFound:
                value = None
            if value is None or value["owner"] != user or value["case_id"] != case_id:
                return JSONResponse(status_code=404, content={
                    "code": "RUN_NOT_FOUND", "message": "Run not found",
                })
            events = runtime.events.read_since(selected, 0)
            state = runtime.runner.status(selected).value
            if state == "SUCCEEDED" and value.get("partial"):
                state = "PARTIAL"
            run_data = {
                "id": selected, "state": state,
                "seq": {"last": events[-1].seq if events else 0, "count": len(events)},
                "started_at": value.get("started_at"),
                "finished_at": value.get("finished_at"),
            }
        event_findings = {event.data.get("requirement_id"): event.data
                          for event in events if event.type == "finding.created"}
        saved_findings = {finding.requirement_id: finding
                          for finding in repo.get_findings(user, case_id)}
        requirements = []
        skipped = []
        for event in events:
            if event.type == "budget.skipped":
                requirement_id = event.data.get("requirement_id")
                if requirement_id is not None and requirement_id not in skipped:
                    skipped.append(requirement_id)
        for requirement in sorted(repo.get_requirements(user, case_id), key=lambda item: (item.order, item.id)):
            raw = event_findings.get(requirement.id)
            finding = saved_findings.get(requirement.id)
            if raw is not None:
                verdict = raw.get("verdict")
                confidence = raw.get("confidence")
                review = raw.get("review", "NONE")
                edited_text = raw.get("edited_text")
                evidence = raw.get("evidence", [])
            elif finding is not None and selected is None:
                verdict, confidence = finding.verdict.value, finding.confidence.value
                review, edited_text = finding.review.value, finding.edited_text
                evidence = [item.model_dump(mode="json") for item in finding.evidence]
            else:
                verdict = confidence = review = edited_text = None
                evidence = []
            requirements.append({
                "id": requirement.id, "text": requirement.text,
                "confirmed": requirement.confirmed, "origin": requirement.origin.value,
                "finding": ({"verdict": verdict, "confidence": confidence,
                             "review": review, "edited_text": edited_text}
                            if verdict is not None else None),
                "evidence": [{"source_id": item.get("source_id"),
                              "locator": item.get("locator"), "excerpt": item.get("excerpt")}
                             for item in evidence],
            })
        return {
            "case": {"id": case.id, "title": case.title, "status": case.status.value,
                     "source_ids": list(case.source_ids), "created_at": case.created_at,
                     "updated_at": case.updated_at},
            "requirements": requirements,
            "run": run_data,
            "events": [{"seq": event.seq, "type": event.type, "ts": event.ts,
                        "data": event.data} for event in events],
            "budget": {"given": value["budget"] if selected else None,
                       "skipped_requirement_ids": skipped},
        }

    @router.post("/cases/{case_id}/requirements:propose",
                 responses=error_responses(404, 409, 422, 503))
    def propose(case_id: str, user=Depends(owner), engine=Depends(engine)):
        with runtime.lock:
            runtime.mutable(user, case_id)
            return runtime.service(engine).propose_requirements(case_id, user)

    @router.put("/cases/{case_id}/requirements", responses=error_responses(404, 409, 422))
    def replace_requirements(case_id: str, body: RequirementsInput, user=Depends(owner)):
        with runtime.lock:
            runtime.mutable(user, case_id)
            existing = {item.id: item for item in repo.get_requirements(user, case_id)}
            values, seen = [], set()
            for index, item in enumerate(body.requirements):
                if item.id is not None and (item.id not in existing or item.id in seen):
                    raise HTTPException(422, "Unknown or duplicate requirement ID")
                requirement_id = item.id or str(uuid4())
                seen.add(requirement_id)
                values.append(Requirement(
                    id=requirement_id, case_id=case_id, text=item.text,
                    confirmed=item.confirmed, order=index,
                    origin=existing[item.id].origin if item.id else RequirementOrigin.USER,
                ))
            repo.save_requirements(user, case_id, values)
            case = runtime.service(None)._case(case_id, user)
            case.status = CaseStatus.READY if values and all(r.confirmed for r in values) else CaseStatus.CONFIRMING
            case.updated_at = runtime.now()
            repo.save_case(user, case)
            return values

    @router.post("/cases/{case_id}/runs", status_code=202,
                 responses=error_responses(404, 409, 422, 503))
    def start_run(case_id: str, body: RunInput = RunInput(), user=Depends(owner),
                  engine=Depends(engine)):
        with runtime.lock:
            runtime.mutable(user, case_id)
            requirements = repo.get_requirements(user, case_id)
            if not requirements or not all(item.confirmed for item in requirements):
                raise RequirementsUnconfirmed(case_id)
            budget = body.budget or {}
            if any(isinstance(budget.get(key), (int, float)) and budget[key] <= 0
                   for key in ("max_requirements", "max_seconds")):
                raise HTTPException(409, {
                    "code": "RUN_BUDGET_EXCEEDED",
                    "message": "Run budget cannot cover one requirement",
                })
            run = {"owner": user, "case_id": case_id, "budget": body.budget, "engine": engine}
            try:
                job_id = runtime.runner.submit(run)
            except ValueError as exc:
                if str(exc) != "case has an active run":
                    raise
                raise HTTPException(409, {"code": "CASE_RUNNING", "message": "Case has an active run"}) from exc
            if not runtime.durable:
                runtime.runs[job_id] = run
            return runtime.status(user, job_id)

    @router.get("/runs/{job_id}", responses=error_responses(404, 422))
    def get_run(job_id: str, user=Depends(owner)):
        return runtime.status(user, job_id)

    @router.get("/runs/{job_id}/events", responses=error_responses(404, 422))
    def events(job_id: str, user=Depends(owner),
               last_event_id: int = Header(default=0, ge=0)):
        runtime.owned_run(user, job_id)

        async def stream():
            async for event in runtime.runner.iter_events(job_id, last_seq=last_event_id):
                yield format_sse(event)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @router.post("/runs/{job_id}:cancel", responses=error_responses(404, 422))
    def cancel(job_id: str, user=Depends(owner)):
        runtime.owned_run(user, job_id)
        runtime.runner.cancel(job_id)
        return runtime.status(user, job_id)

    @router.put("/findings/{finding_id}/decision", responses=error_responses(404, 409, 422))
    def decide(finding_id: str, body: DecisionInput, user=Depends(owner)):
        with runtime.lock:
            for case in repo.list_cases(user):
                if any(f.id == finding_id for f in repo.get_findings(user, case.id)):
                    runtime.mutable(user, case.id)
                    return runtime.service(None).decide_finding(
                        case.id, user, finding_id, Decision(body.review), body.edited_text,
                    )
            raise CaseNotFound(finding_id)

    @router.get("/cases/{case_id}/export", responses=error_responses(404, 422))
    def export(case_id: str, format: Literal["md"] = Query(default="md"), user=Depends(owner)):
        return Response(runtime.service(None).export_markdown(case_id, user), media_type="text/markdown")

    return router
