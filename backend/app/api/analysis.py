"""API cho chức năng phân tích của Studio: truy vết yêu cầu, gói thiết kế kỹ thuật và báo cáo đã lưu.

Tách khỏi /api/chat và các điều kiện nghiên cứu A/B/C; chỉ dùng lại truy xuất và mô hình cục bộ.
"""

from __future__ import annotations

import json
from collections import Counter
import secrets
from typing import Any, Callable, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.analysis import blind_rating, consistency, design, evaluation, grounding, insights, reading, req_quality, security_review
from app.analysis.traceability import (Requirement, assign_agent, check_requirement, extract_requirements,
                                       evidence_for, requirement_query)
from app.core.config import RuntimeConfig
from app.core.types import SourceChunk
from app.providers.factory import get_provider

ReportKind = Literal["traceability", "design", "security_review", "evaluation", "eval_set", "consistency", "doc_profile", "doc_compare", "mindmap", "req_quality"]
Domain = Literal["database", "api_architecture", "security"]
MAX_PAYLOAD_BYTES = 2_000_000
OVERVIEW_CITE_WINDOW = 120


class ExtractBody(BaseModel):
    source_id: str = Field(min_length=1, max_length=160)


class RewriteBody(BaseModel):
    req_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=4000)
    issues: list[str] = Field(default_factory=list, max_length=20)


class RequirementIn(BaseModel):
    req_id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=600)
    body: str = Field(default="", max_length=2000)


class CheckBody(BaseModel):
    requirement: RequirementIn
    source_ids: list[str] = Field(min_length=1, max_length=50)
    top_k: int = Field(default=4, ge=1, le=8)
    agent: Domain | None = None  # bỏ trống: tự chọn theo chuyên môn của yêu cầu


class DesignPoint(BaseModel):
    id: str = Field(min_length=1, max_length=8)
    text: str = Field(min_length=1, max_length=400)
    domain: Domain


class DesignRequest(BaseModel):
    request: str = Field(min_length=10, max_length=4000)


class SectionBody(DesignRequest):
    domain: Domain
    points: list[DesignPoint] = Field(min_length=1, max_length=design.MAX_POINTS)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    avoid_chunk_ids: list[str] = Field(default_factory=list, max_length=60)
    top_k: int = Field(default=4, ge=1, le=6)


class CoverageBody(DesignRequest):
    points: list[DesignPoint] = Field(min_length=1, max_length=design.MAX_POINTS)
    sections: dict[Domain, dict[str, Any]]


class EvalRunBody(BaseModel):
    question: str = Field(min_length=5, max_length=2000)
    condition: Literal["A", "B", "C", "C-P", "C-N", "C-O"]
    source_ids: list[str] | None = Field(default=None, max_length=50)
    key_points: list[str] = Field(default_factory=list, max_length=12)


class EvalStatsBody(BaseModel):
    # điểm theo điều kiện, cùng thứ tự câu hỏi; None = chưa có điểm cho câu đó
    scores: dict[str, list[float | None]] = Field(min_length=1, max_length=6)
    pairs: list[tuple[str, str]] = Field(default_factory=list, max_length=15)


class CandidatesBody(BaseModel):
    source_ids: list[str] = Field(min_length=2, max_length=50)
    max_pairs: int = Field(default=15, ge=1, le=40)


class StatementIn(BaseModel):
    source_name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=400)


class JudgeBody(BaseModel):
    a: StatementIn
    b: StatementIn


class RunRef(BaseModel):
    run_id: str = Field(min_length=1, max_length=80)


class SourceRef(BaseModel):
    source_id: str = Field(min_length=1, max_length=160)


class CompareDocsBody(BaseModel):
    old_source_id: str = Field(min_length=1, max_length=160)
    new_source_id: str = Field(min_length=1, max_length=160)
    summarize: bool = True


class FeedbackBody(BaseModel):
    run_id: str = Field(min_length=1, max_length=80)
    rating: Literal[-1, 0, 1]  # 0 = bỏ đánh giá
    note: str = Field(default="", max_length=500)


class MindmapBody(BaseModel):
    source_id: str = Field(min_length=1, max_length=160)
    mode: Literal["outline", "ai"] = "outline"


class ExplainBody(BaseModel):
    source_name: str = Field(default="", max_length=200)
    selection: str = Field(min_length=2, max_length=1500)
    context: str = Field(default="", max_length=4000)


class DocxBody(BaseModel):
    markdown: str = Field(min_length=1, max_length=400_000)


class RatingItemRef(BaseModel):
    run_id: str = Field(min_length=1, max_length=80)
    key_points: list[str] = Field(default_factory=list, max_length=12)


class StudyBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    items: list[RatingItemRef] = Field(min_length=1, max_length=600)


class ScoreBody(BaseModel):
    key_points: list[bool] = Field(default_factory=list, max_length=12)
    correct: int
    complete: int
    grounded: int
    useful: int
    fabricated: bool = False
    note: str = Field(default="", max_length=1000)


class ReportUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    payload: dict[str, Any]


class ReportBody(BaseModel):
    kind: ReportKind
    title: str = Field(min_length=1, max_length=200)
    workspace_id: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any]


def build_router(
    *,
    current_user: Callable[[Request], dict],
    owner_pipeline: Callable[..., Any],
    session_factory: Callable[[], Any],
    provider_factory: Callable[[], Any] = get_provider,
) -> APIRouter:
    router = APIRouter(prefix="/api/studio", tags=["studio-analysis"])

    def _db():
        factory = session_factory()
        if factory is None:
            raise HTTPException(503, "Chức năng này cần APP_STORAGE_BACKEND=postgres.")
        return factory()

    @router.post("/traceability/extract")
    def extract(body: ExtractBody, request: Request) -> dict:
        user = current_user(request)
        chunks = sorted(owner_pipeline(user).source_store.chunks([body.source_id]), key=lambda c: c.index)
        if not chunks:
            raise HTTPException(404, "Không tìm thấy tài liệu.")
        requirements = extract_requirements("\n\n".join(c.text for c in chunks))
        return {"source_id": body.source_id, "source_name": chunks[0].source_name,
                "requirements": [r.to_dict() for r in requirements]}

    # ---------------- Soát chất lượng yêu cầu (ISO/IEC/IEEE 29148): luật xác định, không gọi mô hình
    @router.post("/req-quality")
    def requirement_quality(body: ExtractBody, request: Request) -> dict:
        user = current_user(request)
        chunks = sorted(owner_pipeline(user).source_store.chunks([body.source_id]), key=lambda c: c.index)
        if not chunks:
            raise HTTPException(404, "Không tìm thấy tài liệu.")
        request.state.audit_target = chunks[0].source_name
        return {"source_id": body.source_id, "source_name": chunks[0].source_name,
                **req_quality.review_text("\n\n".join(c.text for c in chunks))}

    @router.post("/req-quality/rewrite")
    async def requirement_rewrite(body: RewriteBody, request: Request) -> dict:
        current_user(request)
        try:
            return await _llm(req_quality.suggest_rewrite(provider_factory(), body.req_id, body.text, body.issues))
        except ValueError as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.post("/traceability/check")
    async def check(body: CheckBody, request: Request) -> dict:
        user = current_user(request)
        pipeline = owner_pipeline(user)
        chunks = pipeline.source_store.chunks(body.source_ids)
        if not chunks:
            raise HTTPException(404, "Không tìm thấy tài liệu thiết kế đã chọn.")
        item = body.requirement
        domains, agent = assign_agent(f"{item.title}\n{item.body}")
        requirement = Requirement(item.req_id.strip(), item.title.strip(), item.body.strip(), domains, body.agent or agent)
        evidence = evidence_for(pipeline, requirement_query(requirement), chunks, top_k=body.top_k,
                                min_score=RuntimeConfig.from_env().retrieval_min_score, source_ids=body.source_ids)
        terms = security_review.EVIDENCE_TERMS.get(requirement.req_id) if requirement.agent == "security" and body.agent else None
        return await _llm(check_requirement(provider_factory(), requirement, evidence, required_terms=terms))

    async def _llm(call):
        try:
            return await call
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            raise HTTPException(503, "Không gọi được mô hình ngôn ngữ cục bộ (Ollama).") from exc

    # ---------------- Rà soát bảo mật: danh mục tiêu chí; từng tiêu chí kiểm tra qua /traceability/check với agent=security
    @router.get("/security/controls")
    def security_controls(request: Request) -> dict:
        current_user(request)
        return {"standard": security_review.ASVS_VERSION, "controls": security_review.asvs_controls()}

    # ---------------- Gói thiết kế kỹ thuật
    @router.post("/design/points")
    async def design_points(body: DesignRequest, request: Request) -> dict:
        current_user(request)
        return await _llm(design.key_points(provider_factory(), body.request.strip()))

    @router.post("/design/section")
    async def design_section(body: SectionBody, request: Request) -> dict:
        user = current_user(request)
        pipeline = owner_pipeline(user)
        points = [p.model_dump() for p in body.points]
        evidence, shared = [], 0
        if body.source_ids:
            chunks = pipeline.source_store.chunks(body.source_ids)
            if not chunks:
                raise HTTPException(404, "Không tìm thấy tài liệu tham chiếu đã chọn.")
            ranked = evidence_for(pipeline, design.section_query(body.request, body.domain, points), chunks,
                                  top_k=body.top_k * 3, min_score=RuntimeConfig.from_env().retrieval_min_score, source_ids=body.source_ids)
            evidence, shared = design.allocate_evidence(ranked, body.top_k, set(body.avoid_chunk_ids))
        result = await _llm(design.design_section(provider_factory(), body.request.strip(), body.domain, points, evidence))
        return {**result, "shared_chunks": shared}

    @router.post("/design/coverage")
    async def design_coverage(body: CoverageBody, request: Request) -> dict:
        current_user(request)
        return await _llm(design.coverage(provider_factory(), body.request.strip(), [p.model_dump() for p in body.points], body.sections))

    # ---------------- Kiểm tra mâu thuẫn giữa tài liệu
    @router.post("/consistency/candidates")
    def consistency_candidates(body: CandidatesBody, request: Request) -> dict:
        user = current_user(request)
        chunks = sorted(owner_pipeline(user).source_store.chunks(body.source_ids), key=lambda c: (c.source_id, c.index))
        if len({c.source_id for c in chunks}) < 2:
            raise HTTPException(404, "Cần ít nhất hai tài liệu có nội dung để so sánh.")
        statements = consistency.extract_statements(chunks)
        return {"statements": len(statements), "pairs": consistency.candidate_pairs(statements, max_pairs=body.max_pairs)}

    @router.post("/consistency/judge")
    async def consistency_judge(body: JudgeBody, request: Request) -> dict:
        current_user(request)
        return await _llm(consistency.judge_pair(provider_factory(), body.a.model_dump(), body.b.model_dump()))

    # ---------------- Phòng đánh giá thực nghiệm
    @router.post("/eval/run")
    async def eval_run(body: EvalRunBody, request: Request) -> dict:
        """Một lượt chạy nghiên cứu (lưu vết như /api/chat nhưng không tạo cuộc trò chuyện).

        Mọi điều kiện cùng bật nhắc trả lời theo ngôn ngữ câu hỏi để so sánh công bằng; thiết lập này nằm trong
        sự kiện run_started (answer_language) của từng lượt.
        """
        user = current_user(request)
        try:
            RuntimeConfig.from_env().assert_condition(body.condition)
        except ValueError as exc:
            raise HTTPException(400, f"Điều kiện {body.condition} chưa bật trong cấu hình hiện tại.") from exc
        try:
            run = await owner_pipeline(user).run(body.question.strip(), body.condition, source_ids=body.source_ids,
                                                 reply_in_query_language=True)
        except LookupError as exc:
            raise HTTPException(404, "Không tìm thấy tài liệu đã chọn.") from exc
        answer = evaluation.readable_answer(run.get("answer"))
        hits = evaluation.keypoint_hits(answer, body.key_points) if run.get("status") != "FAILED" else [False] * len(body.key_points)
        metrics = run.get("metrics") or {}
        return {
            "run_id": run.get("run_id"), "condition": body.condition, "status": run.get("status"), "answer": answer,
            "key_point_hits": hits, "key_point_coverage": (sum(hits) / len(hits)) if hits else None,
            "metrics": {k: metrics.get(k) for k in evaluation.METRIC_KEYS},
            "tasks": len(run.get("tasks") or []), "model": run.get("model"), "config_hash": run.get("config_hash"),
        }

    @router.post("/eval/stats")
    def eval_stats(body: EvalStatsBody, request: Request) -> dict:
        current_user(request)
        lengths = {len(v) for v in body.scores.values()}
        if len(lengths) != 1 or max(lengths) > 1000:
            raise HTTPException(422, "Các điều kiện phải có cùng số câu hỏi (tối đa 1000).")
        missing = [c for pair in body.pairs for c in pair if c not in body.scores]
        if missing:
            raise HTTPException(422, f"Không có điểm của điều kiện: {', '.join(sorted(set(missing)))}")
        return {
            "conditions": {c: evaluation.describe([v for v in vals if v is not None]) for c, vals in body.scores.items()},
            "comparisons": [{"a": a, "b": b, **evaluation.compare_paired(body.scores[a], body.scores[b])} for a, b in body.pairs],
        }

    # ---------------- Đèn báo độ tin cậy, hồ sơ tài liệu, so sánh phiên bản
    def _chunks_of(user, source_id: str):
        chunks = sorted(owner_pipeline(user).source_store.chunks([source_id]), key=lambda c: c.index)
        if not chunks:
            raise HTTPException(404, "Không tìm thấy tài liệu.")
        return chunks

    @router.post("/grounding")
    def grounding_check(body: RunRef, request: Request) -> dict:
        user = current_user(request)
        pipeline = owner_pipeline(user)
        run = pipeline.run_store.get(body.run_id)
        if not run:
            raise HTTPException(404, "Không tìm thấy lượt chạy.")
        chunks = [SourceChunk(**item) for cid in grounding.run_evidence_ids(run)[:40] if (item := pipeline.source_store.chunk(cid))]
        return grounding.ground_answer(evaluation.readable_answer(run.get("answer")), chunks)

    @router.post("/profile/local")
    def profile_local(body: SourceRef, request: Request) -> dict:
        """Phần chạy tại máy: chất lượng, thông tin nhạy cảm (đã che), thuật ngữ định nghĩa sẵn, tài liệu liên quan."""
        user = current_user(request)
        chunks = _chunks_of(user, body.source_id)
        everything = owner_pipeline(user).source_store.chunks(None)
        by_source: dict[str, list] = {}
        for c in everything:
            by_source.setdefault(c.source_id, []).append(c)
        names = {c.source_id: c.source_name for c in everything}
        request.state.audit_target = chunks[0].source_name
        doc = "\n\n".join(c.text for c in chunks)
        defined, pending = insights.glossary_candidates(doc)
        pii = insights.pii_scan(doc)
        return {"source_id": body.source_id, "source_name": chunks[0].source_name,
                "quality": insights.quality_report(chunks, [c for c in everything if c.source_id != body.source_id]),
                "pii": {"findings": pii["findings"], "counts": pii["counts"]},
                "glossary_defined": defined, "glossary_pending": len(pending),
                "related": insights.related_documents(body.source_id, by_source, names)}

    @router.post("/profile/masked")
    def profile_masked(body: SourceRef, request: Request) -> dict:
        chunks = _chunks_of(current_user(request), body.source_id)
        return {"source_name": chunks[0].source_name, "masked_text": insights.pii_scan("\n\n".join(c.text for c in chunks))["masked_text"]}

    @router.post("/profile/summary")
    async def profile_summary(body: SourceRef, request: Request) -> dict:
        chunks = _chunks_of(current_user(request), body.source_id)
        return await _llm(insights.summarize(provider_factory(), chunks[0].source_name, chunks))

    @router.post("/profile/questions")
    async def profile_questions(body: SourceRef, request: Request) -> dict:
        chunks = _chunks_of(current_user(request), body.source_id)
        return await _llm(insights.suggest_questions(provider_factory(), chunks[0].source_name, chunks))

    @router.post("/profile/glossary")
    async def profile_glossary(body: SourceRef, request: Request) -> dict:
        chunks = _chunks_of(current_user(request), body.source_id)
        defined, pending = insights.glossary_candidates("\n\n".join(c.text for c in chunks))
        model = await _llm(insights.define_terms(provider_factory(), pending))
        return {**model, "terms": defined + model["terms"]}

    @router.post("/compare-docs")
    async def compare_docs(body: CompareDocsBody, request: Request) -> dict:
        user = current_user(request)
        old, new = _chunks_of(user, body.old_source_id), _chunks_of(user, body.new_source_id)
        request.state.audit_target = f"{old[0].source_name} → {new[0].source_name}"
        diff = insights.compare_versions("\n\n".join(c.text for c in old), "\n\n".join(c.text for c in new))
        summary = await _llm(insights.summarize_changes(provider_factory(), diff["changes"])) if body.summarize else None
        return {**diff, "old_name": old[0].source_name, "new_name": new[0].source_name, "summary": summary}

    # ---------------- Sơ đồ tư duy, bôi đen để hỏi, báo cáo từ câu trả lời, xuất Word, kiểm tra kho
    @router.post("/mindmap")
    async def mindmap(body: MindmapBody, request: Request) -> dict:
        chunks = _chunks_of(current_user(request), body.source_id)
        request.state.audit_target = chunks[0].source_name
        if body.mode == "outline":
            return {**reading.mindmap_outline(chunks[0].source_name, chunks), "source_id": body.source_id, "source_name": chunks[0].source_name}
        result = await _llm(reading.mindmap_ai(provider_factory(), chunks[0].source_name, chunks))
        if len(result["root"]["children"]) < 2:
            raise HTTPException(502, "Mô hình chưa lập được sơ đồ đủ nhánh; hãy thử lại hoặc dùng sơ đồ theo cấu trúc.")
        return {**result, "source_id": body.source_id, "source_name": chunks[0].source_name}

    @router.post("/related")
    def related(body: SourceRef, request: Request) -> dict:
        """Tài liệu cùng chủ đề (tại máy) cho trình đọc tài liệu."""
        everything = owner_pipeline(current_user(request)).source_store.chunks(None)
        by_source: dict[str, list] = {}
        for c in everything:
            by_source.setdefault(c.source_id, []).append(c)
        if body.source_id not in by_source:
            raise HTTPException(404, "Không tìm thấy tài liệu.")
        return {"related": insights.related_documents(body.source_id, by_source, {c.source_id: c.source_name for c in everything}, limit=6)}

    @router.post("/explain")
    async def explain(body: ExplainBody, request: Request) -> dict:
        current_user(request)
        try:
            return await _llm(reading.explain_selection(provider_factory(), body.source_name, body.selection.strip(), body.context))
        except ValueError as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.post("/answer-report")
    async def answer_report(body: RunRef, request: Request) -> dict:
        user = current_user(request)
        pipeline = owner_pipeline(user)
        run = pipeline.run_store.get(body.run_id)
        if not run:
            raise HTTPException(404, "Không tìm thấy lượt chạy.")
        answer = evaluation.readable_answer(run.get("answer"))
        if not answer.strip() or run.get("status") in {"FAILED", "NO_EVIDENCE"}:
            raise HTTPException(422, "Lượt chạy này không có câu trả lời dựa trên tài liệu để viết báo cáo.")
        evidence = [SourceChunk(**item) for cid in grounding.run_evidence_ids(run)[:8] if (item := pipeline.source_store.chunk(cid))]
        question = str(run.get("query") or "")
        # Câu hỏi tiếp nối ("Mất bao lâu?") cần kèm câu hỏi trước để báo cáo tự đủ nghĩa.
        prev = next((e.get("previous_request") for e in run.get("events") or [] if e.get("stage") == "follow_up_resolved"), None)
        if prev:
            question = f"{question} (tiếp theo câu hỏi: {prev})"
        request.state.audit_target = question[:120]
        try:
            return await _llm(reading.answer_report(provider_factory(), question, answer, evidence))
        except ValueError as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.post("/export/docx")
    def export_docx(body: DocxBody, request: Request) -> Response:
        current_user(request)
        return Response(reading.markdown_to_docx(body.markdown),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": 'attachment; filename="bao-cao.docx"'})

    @router.get("/library-quality")
    def library_quality(request: Request) -> dict:
        user = current_user(request)
        store = owner_pipeline(user).source_store
        by_source: dict[str, list] = {}
        for c in store.chunks(None):
            by_source.setdefault(c.source_id, []).append(c)
        return reading.library_quality(store.list_sources(), by_source)

    @router.get("/admin/feedback")
    def admin_feedback(request: Request, limit: int = 200) -> dict:
        user = current_user(request)
        if str(user.get("role", "")).upper() != "ADMIN":
            raise HTTPException(403, "Chức năng này dành cho quản trị hệ thống.")
        with _db() as db:
            rows = db.execute(text(
                "SELECT f.run_id, f.rating, f.note, f.created_at, COALESCE(u.email, u.username) AS user_label, "
                "r.query, r.answer, r.status, r.condition FROM studio_feedback f "
                "LEFT JOIN users u ON u.user_id = f.owner_user_id LEFT JOIN runs r ON r.run_id = f.run_id "
                "ORDER BY f.created_at DESC LIMIT :l"), {"l": max(1, min(limit, 1000))}).mappings().all()
            totals = {int(k): int(v) for k, v in db.execute(text("SELECT rating, COUNT(*) FROM studio_feedback GROUP BY rating")).all()}
        items = [{"run_id": r["run_id"], "rating": r["rating"], "note": r["note"], "created_at": r["created_at"].isoformat(),
                  "user": r["user_label"] or "", "query": r["query"] or "", "status": r["status"] or "", "condition": r["condition"] or "",
                  "answer": evaluation.readable_answer(r["answer"])[:600]} for r in rows]
        return {"up": totals.get(1, 0), "down": totals.get(-1, 0), "items": items}

    # ---------------- Chấm mù nhiều người
    def _study(db, *, study_id: str | None = None, code: str | None = None):
        row = db.execute(text("SELECT study_id, owner_user_id, title, code, items, failed, created_at FROM studio_rating_studies WHERE "
                              + ("study_id = :v" if study_id else "code = :v")), {"v": study_id or (code or "").strip().upper()}).mappings().first()
        if not row:
            raise HTTPException(404, "Không tìm thấy đợt chấm. Kiểm tra lại mã.")
        return row

    @router.post("/rating/studies")
    def create_study(body: StudyBody, request: Request) -> dict:
        user = current_user(request)
        store = owner_pipeline(user).run_store
        rows = []
        for ref in body.items:
            run = store.get(ref.run_id)
            if not run:
                raise HTTPException(404, f"Không tìm thấy lượt chạy {ref.run_id}.")
            answer = evaluation.readable_answer(run.get("answer"))
            rows.append({"run_id": ref.run_id, "condition": run.get("condition") or "?", "question": str(run.get("query") or ""),
                         "answer": answer, "status": run.get("status"), "key_points": ref.key_points,
                         "auto_hits": evaluation.keypoint_hits(answer, ref.key_points) if ref.key_points else None})
        items, failed = blind_rating.build_items(rows)
        if not items:
            raise HTTPException(422, "Không có câu trả lời nào để chấm (mọi lượt đều thất bại).")
        study_id = "rs_" + secrets.token_hex(8)
        with _db() as db:
            for _ in range(5):
                code = blind_rating.new_code()
                if not db.execute(text("SELECT 1 FROM studio_rating_studies WHERE code = :c"), {"c": code}).first():
                    break
            db.execute(text("INSERT INTO studio_rating_studies (study_id, owner_user_id, title, code, items, failed) "
                            "VALUES (:i, :o, :t, :c, CAST(:it AS jsonb), CAST(:f AS jsonb))"),
                       {"i": study_id, "o": str(user["user_id"]), "t": body.title.strip(), "c": code,
                        "it": json.dumps(items, ensure_ascii=False), "f": json.dumps(failed, ensure_ascii=False)})
            db.commit()
        request.state.audit_target = body.title.strip()
        return {"study_id": study_id, "code": code, "items": len(items), "failed_runs": len(failed)}

    @router.get("/rating/studies")
    def list_studies(request: Request) -> list[dict]:
        owner = str(current_user(request)["user_id"])
        with _db() as db:
            rows = db.execute(text(
                "SELECT s.study_id, s.title, s.code, s.created_at, jsonb_array_length(s.items) AS items, jsonb_array_length(s.failed) AS failed, "
                "COUNT(r.item_id) AS ratings, COUNT(DISTINCT r.rater_user_id) AS raters FROM studio_rating_studies s "
                "LEFT JOIN studio_ratings r ON r.study_id = s.study_id WHERE s.owner_user_id = :o "
                "GROUP BY s.study_id ORDER BY s.created_at DESC"), {"o": owner}).mappings().all()
        return [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]

    @router.get("/rating/studies/{study_id}/results")
    def study_results(study_id: str, request: Request) -> dict:
        owner = str(current_user(request)["user_id"])
        with _db() as db:
            st = _study(db, study_id=study_id)
            if st["owner_user_id"] != owner:
                raise HTTPException(404, "Không tìm thấy đợt chấm.")
            rows = db.execute(text("SELECT r.item_id, r.scores, r.note, COALESCE(u.email, u.username, r.rater_user_id) AS rater "
                                   "FROM studio_ratings r LEFT JOIN users u ON u.user_id = r.rater_user_id WHERE r.study_id = :s"),
                              {"s": study_id}).mappings().all()
        ratings = [{"item_id": r["item_id"], "rater": r["rater"], "scores": r["scores"], "note": r["note"]} for r in rows]
        result = blind_rating.aggregate(st["items"], st["failed"], ratings)
        cond = {it["item_id"]: it["condition"] for it in st["items"]}
        result["notes"] = [{"condition": cond.get(r["item_id"]), "note": r["note"]} for r in ratings if r["note"]]
        return {"study_id": study_id, "title": st["title"], "code": st["code"], **result}

    @router.delete("/rating/studies/{study_id}")
    def delete_study(study_id: str, request: Request) -> dict:
        owner = str(current_user(request)["user_id"])
        with _db() as db:
            n = db.execute(text("DELETE FROM studio_rating_studies WHERE study_id = :s AND owner_user_id = :o"), {"s": study_id, "o": owner}).rowcount
            db.commit()
        if not n:
            raise HTTPException(404, "Không tìm thấy đợt chấm.")
        return {"deleted": study_id}

    @router.get("/rating/join/{code}")
    def join_study(code: str, request: Request) -> dict:
        user = current_user(request)
        rater = str(user["user_id"])
        with _db() as db:
            st = _study(db, code=code)
            if st["owner_user_id"] == rater:
                raise HTTPException(403, "Người tạo đợt chấm không tự chấm để giữ tính mù. Hãy đăng nhập bằng tài khoản của người chấm.")
            mine = db.execute(text("SELECT item_id, scores, note FROM studio_ratings WHERE study_id = :s AND rater_user_id = :r"),
                              {"s": st["study_id"], "r": rater}).mappings().all()
        return {"title": st["title"], "code": st["code"], "items": blind_rating.rater_view(st["items"], rater, st["study_id"]),
                "mine": {m["item_id"]: {**m["scores"], "note": m["note"]} for m in mine}}

    @router.put("/rating/join/{code}/{item_id}")
    def save_score(code: str, item_id: str, body: ScoreBody, request: Request) -> dict:
        user = current_user(request)
        rater = str(user["user_id"])
        with _db() as db:
            st = _study(db, code=code)
            if st["owner_user_id"] == rater:
                raise HTTPException(403, "Người tạo đợt chấm không tự chấm để giữ tính mù.")
            item = next((it for it in st["items"] if it["item_id"] == item_id), None)
            if not item:
                raise HTTPException(404, "Không tìm thấy mục chấm.")
            try:
                scores = blind_rating.validate_score(body.model_dump(exclude={"note"}), len(item["key_points"]))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            db.execute(text("INSERT INTO studio_ratings (study_id, rater_user_id, item_id, scores, note) VALUES (:s, :r, :i, CAST(:sc AS jsonb), :n) "
                            "ON CONFLICT (study_id, rater_user_id, item_id) DO UPDATE SET scores = EXCLUDED.scores, note = EXCLUDED.note, updated_at = now()"),
                       {"s": st["study_id"], "r": rater, "i": item_id, "sc": json.dumps(scores), "n": body.note.strip()})
            db.commit()
        return {"item_id": item_id, "saved": True}

    # ---------------- Phản hồi, nhật ký hoạt động, tổng quan
    @router.post("/feedback")
    def save_feedback(body: FeedbackBody, request: Request) -> dict:
        user = current_user(request)
        owner = str(user["user_id"])
        if not owner_pipeline(user).run_store.get(body.run_id):
            raise HTTPException(404, "Không tìm thấy lượt chạy.")
        with _db() as db:
            if body.rating == 0:
                db.execute(text("DELETE FROM studio_feedback WHERE owner_user_id = :o AND run_id = :r"), {"o": owner, "r": body.run_id})
            else:
                db.execute(text("INSERT INTO studio_feedback (owner_user_id, run_id, rating, note) VALUES (:o, :r, :g, :n) "
                                "ON CONFLICT (owner_user_id, run_id) DO UPDATE SET rating = EXCLUDED.rating, note = EXCLUDED.note, created_at = now()"),
                           {"o": owner, "r": body.run_id, "g": body.rating, "n": body.note.strip()})
            db.commit()
        return {"run_id": body.run_id, "rating": body.rating}

    @router.get("/feedback")
    def list_feedback(request: Request) -> dict:
        owner = str(current_user(request)["user_id"])
        with _db() as db:
            rows = db.execute(text("SELECT run_id, rating, note FROM studio_feedback WHERE owner_user_id = :o ORDER BY created_at DESC LIMIT 1000"),
                              {"o": owner}).mappings().all()
        return {r["run_id"]: {"rating": r["rating"], "note": r["note"]} for r in rows}

    @router.get("/activity/page")
    def activity_page(request: Request, page: int = 1, size: int = 20, q: str = "") -> dict:
        """Nhật ký hoạt động theo trang (mới nhất trước); q lọc theo thao tác hoặc đối tượng."""
        owner = str(current_user(request)["user_id"])
        size = max(5, min(size, 100))
        page = max(1, page)
        where = "owner_user_id = :o" + (" AND (action ILIKE :q OR target ILIKE :q)" if q.strip() else "")
        args = {"o": owner, "q": f"%{q.strip()}%", "l": size, "off": (page - 1) * size}
        with _db() as db:
            total = int(db.execute(text(f"SELECT COUNT(*) FROM studio_activity WHERE {where}"), args).scalar() or 0)
            rows = db.execute(text(f"SELECT action, target, status, created_at FROM studio_activity WHERE {where} "
                                   "ORDER BY created_at DESC, activity_id DESC LIMIT :l OFFSET :off"), args).mappings().all()
        return {"rows": [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows],
                "total": total, "page": page, "size": size, "pages": max(1, -(-total // size))}

    @router.get("/activity")
    def list_activity(request: Request, limit: int = 100) -> list[dict]:
        owner = str(current_user(request)["user_id"])
        with _db() as db:
            rows = db.execute(text("SELECT action, target, status, created_at FROM studio_activity WHERE owner_user_id = :o "
                                   "ORDER BY created_at DESC, activity_id DESC LIMIT :l"), {"o": owner, "l": max(1, min(limit, 5000))}).mappings().all()
        return [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]

    @router.get("/overview")
    def overview(request: Request) -> dict:
        """Số liệu sử dụng thật của tài khoản: tài liệu, lượt chạy theo điều kiện và trạng thái, token, phản hồi, báo cáo."""
        user = current_user(request)
        owner = str(user["user_id"])
        pipeline = owner_pipeline(user)
        sources = pipeline.source_store.list_sources()
        store = pipeline.run_store
        # kho PostgreSQL có truy vấn gọn (không tải cột JSON lớn, gom trích dẫn trong một truy vấn); kho tệp dùng cách cũ
        runs = store.list_light(limit=500) if hasattr(store, "list_light") else store.list(limit=500)
        names = {s["source_id"]: s["source_name"] for s in sources}
        cited: Counter = Counter()
        # shortcut: đọc toàn bộ đoạn của tài khoản để tách từ ghép; kho rất lớn thì cần lưu sẵn từ vựng
        topics = reading.question_topics(runs, reading.bigram_vocabulary(c.text for c in pipeline.source_store.chunks(None)))
        window = runs[:OVERVIEW_CITE_WINDOW]  # 120 lượt gần nhất; cần cột citations riêng nếu muốn đếm toàn bộ
        if hasattr(store, "recent_citations"):
            citations = store.recent_citations(len(window))
        else:
            citations = [cid for r in window for res in (store.get(r["run_id"]) or {}).get("task_results") or [] for cid in res.get("citations") or []]
        for cid in citations:
            cited[str(cid).rsplit("_c", 1)[0]] += 1
        measured = [r.get("metrics") or {} for r in runs if r.get("metrics")]
        tokens = [int(m.get("input_tokens") or 0) + int(m.get("output_tokens") or 0) for m in measured if m.get("input_tokens") is not None]
        latency = [int(m["latency_ms"]) for m in measured if m.get("latency_ms")]
        with _db() as db:
            fb = {int(k): int(v) for k, v in db.execute(text("SELECT rating, COUNT(*) FROM studio_feedback WHERE owner_user_id = :o GROUP BY rating"), {"o": owner}).all()}
            reports = {k: int(v) for k, v in db.execute(text("SELECT kind, COUNT(*) FROM studio_reports WHERE owner_user_id = :o GROUP BY kind"), {"o": owner}).all()}
        return {
            "sources": len(sources), "chunks": sum(int(s.get("chunk_count") or 0) for s in sources), "runs": len(runs),
            "runs_by_condition": dict(Counter(r.get("condition") or "?" for r in runs)),
            "runs_by_status": dict(Counter(r.get("status") or "?" for r in runs)),
            "tokens_total": sum(tokens) if tokens else None, "tokens_avg": round(sum(tokens) / len(tokens)) if tokens else None,
            "latency_avg_ms": round(sum(latency) / len(latency)) if latency else None,
            "feedback": {"up": fb.get(1, 0), "down": fb.get(-1, 0)}, "reports": reports,
            "top_documents": [{"source_id": sid, "source_name": names[sid], "citations": n} for sid, n in cited.most_common(8) if sid in names][:5],
            "cite_window": len(window),
            "unused_documents": [{"source_id": s["source_id"], "source_name": s["source_name"]} for s in sources if s["source_id"] not in cited] if window else [],
            **topics,
            **reading.usage_patterns(runs),
        }

    # ---------------- Báo cáo đã lưu
    @router.get("/reports")
    def list_reports(request: Request, kind: str | None = None) -> list[dict]:
        owner = str(current_user(request)["user_id"])
        with _db() as db:
            rows = db.execute(text(
                "SELECT report_id, workspace_id, kind, title, created_at, updated_at FROM studio_reports "
                "WHERE owner_user_id = :o AND (CAST(:k AS TEXT) IS NULL OR kind = :k) ORDER BY created_at DESC LIMIT 100"),
                {"o": owner, "k": kind}).mappings().all()
        return [{**dict(r), "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()} for r in rows]

    @router.post("/reports")
    def save_report(body: ReportBody, request: Request) -> dict:
        owner = str(current_user(request)["user_id"])
        payload = json.dumps(body.payload, ensure_ascii=False)
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise HTTPException(413, "Báo cáo quá lớn để lưu.")
        report_id = "rpt_" + secrets.token_hex(8)
        request.state.audit_target = body.title.strip()
        with _db() as db:
            if body.workspace_id and db.execute(text("SELECT 1 FROM studio_workspaces WHERE workspace_id = :w AND owner_user_id = :o"),
                                                {"w": body.workspace_id, "o": owner}).scalar() is None:
                raise HTTPException(404, "Không tìm thấy không gian làm việc.")
            db.execute(text("INSERT INTO studio_reports (report_id, owner_user_id, workspace_id, kind, title, payload) "
                            "VALUES (:r, :o, :w, :k, :t, CAST(:p AS JSONB))"),
                       {"r": report_id, "o": owner, "w": body.workspace_id, "k": body.kind, "t": body.title.strip(), "p": payload})
            db.commit()
        return {"report_id": report_id}

    @router.get("/reports/{report_id}")
    def get_report(report_id: str, request: Request) -> dict:
        owner = str(current_user(request)["user_id"])
        with _db() as db:
            row = db.execute(text("SELECT report_id, workspace_id, kind, title, payload, created_at FROM studio_reports "
                                  "WHERE report_id = :r AND owner_user_id = :o"), {"r": report_id, "o": owner}).mappings().first()
        if row is None:
            raise HTTPException(404, "Không tìm thấy báo cáo.")
        return {**dict(row), "created_at": row["created_at"].isoformat()}

    @router.patch("/reports/{report_id}")
    def update_report(report_id: str, body: ReportUpdate, request: Request) -> dict:
        owner = str(current_user(request)["user_id"])
        payload = json.dumps(body.payload, ensure_ascii=False)
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise HTTPException(413, "Báo cáo quá lớn để lưu.")
        with _db() as db:
            updated = db.execute(text("UPDATE studio_reports SET payload = CAST(:p AS JSONB), title = COALESCE(:t, title), updated_at = now() "
                                      "WHERE report_id = :r AND owner_user_id = :o"),
                                 {"p": payload, "t": body.title.strip() if body.title else None, "r": report_id, "o": owner}).rowcount
            db.commit()
        if not updated:
            raise HTTPException(404, "Không tìm thấy báo cáo.")
        return {"report_id": report_id}

    @router.delete("/reports/{report_id}")
    def delete_report(report_id: str, request: Request) -> dict:
        owner = str(current_user(request)["user_id"])
        with _db() as db:
            deleted = db.execute(text("DELETE FROM studio_reports WHERE report_id = :r AND owner_user_id = :o"),
                                 {"r": report_id, "o": owner}).rowcount
            db.commit()
        if not deleted:
            raise HTTPException(404, "Không tìm thấy báo cáo.")
        return {"deleted": report_id}

    return router
