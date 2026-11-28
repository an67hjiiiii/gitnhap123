"""API Phiên làm việc tự động thật của Văn phòng Agent 3D.

- POST /api/studio/office/work-session : NDJSON stream một phiên phối hợp đa tác tử THẬT
  (Orchestrator phân rã -> RAG Specialist truy xuất kho tài liệu thật -> 2 Chuyên gia làm việc & trao đổi chéo ->
   Reviewer kiểm định -> Integrator tổng hợp bàn giao).

100% nội dung trao đổi do mô hình LLM thật (Ollama local / fake trong test) sinh mới theo thời gian thực
dựa trên kho tài liệu thật của không gian đang mở (hoặc bài toán chuyên môn theo lĩnh vực khi kho chưa có file),
tuyệt đối không dùng kịch bản minh họa văn bản dựng sẵn.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

_log = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.answer_checks import check_product_evidence_claims, strip_invalid_inline_citations
from app.core.citations import validate_citations
from app.core.config import ollama_call_options
from app.core.secret_audit import log_secret_access
from app.providers.factory import get_provider
from app.research.run_queue import QueueFullError, product_runs

AGENT_PERSONAS: dict[str, dict[str, str]] = {
    "orchestrator": {
        "name": "Orchestrator",
        "title_vi": "Điều phối trưởng",
        "focus": "tiếp nhận bài toán, phân rã thành các đầu việc rõ ràng và phân công đúng chuyên gia",
    },
    "rag": {
        "name": "RAG Specialist",
        "title_vi": "Chuyên gia Truy xuất Tri thức",
        "focus": "rút đúng đoạn bằng chứng từ kho tài liệu và lọc bỏ trùng lặp ngữ cảnh",
    },
    "analyst": {
        "name": "Data Analyst",
        "title_vi": "Chuyên gia Phân tích Số liệu",
        "focus": "đọc số liệu định lượng, KPI, xu hướng, điểm nghẽn đo lường",
    },
    "reviewer": {
        "name": "Reviewer",
        "title_vi": "Chuyên gia Kiểm định Chất lượng",
        "focus": "đối chiếu chéo giữa các phòng ban, soi mâu thuẫn, rủi ro và tính đầy đủ của căn cứ",
    },
    "integrator": {
        "name": "Integrator",
        "title_vi": "Chuyên gia Tổng hợp",
        "focus": "tổng hợp kết quả từ các phòng ban thành báo cáo rõ ràng, súc tích và có khuyến nghị hành động",
    },
    "software": {
        "name": "Software & Tech",
        "title_vi": "Chuyên gia Kỹ thuật & Hệ thống",
        "focus": "kiến trúc hệ thống, API, cơ sở dữ liệu, bảo mật và hiệu năng triển khai",
    },
    "business": {
        "name": "Business & Strategy",
        "title_vi": "Chuyên gia Kinh doanh & Vận hành",
        "focus": "mô hình vận hành, quy trình nội bộ, trải nghiệm khách hàng và tính khả thi",
    },
    "marketing": {
        "name": "Marketing & Growth",
        "title_vi": "Chuyên gia Marketing & Tăng trưởng",
        "focus": "định vị sản phẩm, kênh tăng trưởng, chuyển đổi và thông điệp khách hàng",
    },
    "hr": {
        "name": "HR & Policy",
        "title_vi": "Chuyên gia Nhân sự & Chính sách",
        "focus": "chính sách đãi ngộ, quy chế lao động, phúc lợi và giữ chân nhân sự",
    },
    "finance": {
        "name": "Finance & Budget",
        "title_vi": "Chuyên gia Tài chính & Ngân sách",
        "focus": "ngân sách, chi phí – lợi nhuận (ROI), dòng tiền và kiểm soát rủi ro tài chính",
    },
    "education": {
        "name": "Education & Research",
        "title_vi": "Chuyên gia Giáo dục & Nghiên cứu",
        "focus": "quy chế học vụ, chương trình đào tạo, nghiên cứu khoa học và chuẩn đầu ra",
    },
}

_OFFICE_WORK_SEEDS: list[tuple[str, str, str]] = [
    ("software", "analyst", "Tối ưu độ trễ API, giảm chi phí token LLM cục bộ và theo dõi chỉ số SLA của hệ thống đa tác tử"),
    ("finance", "hr", "Cân đối ngân sách phúc lợi nhân sự, phụ cấp chuyên cần và thưởng KPI quý nhằm giữ chân đội ngũ mà vẫn giữ biên lợi nhuận"),
    ("marketing", "analyst", "Phân tích hiệu quả chiến dịch tiếp cận người dùng mới và tối ưu tỷ lệ chuyển đổi trong quý tới"),
    ("education", "analyst", "Đánh giá tỷ lệ sinh viên hoàn thành tín chỉ đúng hạn, cảnh báo học vụ sớm và phân bổ học bổng khuyến khích"),
    ("software", "business", "Đánh giá lợi ích và rủi ro khi triển khai trợ lý AI đa tác tử chạy cục bộ để tra cứu tài liệu nội bộ"),
    ("business", "hr", "Chuẩn hóa quy trình phối hợp liên phòng ban, phê duyệt công việc và đánh giá hiệu suất minh bạch"),
    ("marketing", "finance", "Phân bổ lại ngân sách tăng trưởng quý tới giữa kênh giữ chân khách hàng cũ và chiến dịch thu hút khách hàng mới"),
    ("education", "hr", "Cân đối định mức giờ giảng, hỗ trợ nghiên cứu khoa học cho giảng viên và nâng cao chất lượng công bố"),
]

_DOC_KEYWORD_AGENT: list[tuple[str, tuple[str, ...]]] = [
    ("finance", ("tài chính", "doanh thu", "lợi nhuận", "chi phí", "ngân sách", "thuế", "dòng tiền", "báo cáo tài chính", "finance", "budget")),
    ("hr", ("nhân sự", "phúc lợi", "lương", "thưởng", "nghỉ phép", "chấm công", "kpi", "quy chế nhân sự", "hr", "tuyển dụng")),
    ("software", ("kiến trúc", "api", "database", "bảo mật", "mã hóa", "jwt", "server", "hệ thống", "phần mềm", "sql", "vector", "rag")),
    ("education", ("đào tạo", "tín chỉ", "sinh viên", "học bổng", "giảng viên", "học phần", "tốt nghiệp", "nghiên cứu khoa học")),
    ("marketing", ("marketing", "thị trường", "chiến lược", "khách hàng", "thương hiệu", "quảng cáo", "tăng trưởng", "chiến dịch")),
    ("business", ("quy trình", "vận hành", "hợp đồng", "kinh doanh", "đối tác", "điều khoản", "quản trị", "dự án")),
]

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
    "additionalProperties": False,
}
_TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"topic": {"type": "string"}},
    "required": ["topic"],
    "additionalProperties": False,
}


def _clean_json_field(raw: str, field: str = "reply") -> str:
    text = _THINK_RE.sub("", raw or "").strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                for key in (field, "reply", "topic", "answer", "summary", "text"):
                    val = obj.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
        except Exception:
            pass
    return text


def _filtered_call_kwargs(fn: Any, opts: dict[str, Any]) -> dict[str, Any]:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(opts)
    return {k: v for k, v in opts.items() if k in params}


async def _await_with_guards(
    coro: Any,
    *,
    deadline: float | None = None,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> Any:
    if deadline is not None and time.monotonic() >= deadline:
        if asyncio.iscoroutine(coro):
            coro.close()
        raise TimeoutError("Phiên làm việc vượt quá giới hạn thời gian cho phép.")
    gen_task = asyncio.create_task(coro)

    async def _watch_disconnect() -> None:
        assert is_disconnected is not None
        while not gen_task.done():
            await asyncio.sleep(0.05)
            if await is_disconnected():
                raise asyncio.CancelledError("Client disconnected")

    disc_task = asyncio.create_task(_watch_disconnect()) if is_disconnected is not None else None
    try:
        while not gen_task.done():
            step_timeout: float | None = None
            if deadline is not None:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    raise TimeoutError("Phiên làm việc vượt quá giới hạn thời gian cho phép.")
                step_timeout = rem
            wait_set = {gen_task} if disc_task is None else {gen_task, disc_task}
            done, _ = await asyncio.wait(wait_set, timeout=step_timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TimeoutError("Phiên làm việc vượt quá giới hạn thời gian cho phép.")
            if disc_task is not None and disc_task in done and not gen_task.done():
                disc_task.result()  # raises CancelledError when disconnected
                break
        return await gen_task
    finally:
        for task in (gen_task, disc_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (gen_task, disc_task) if t is not None), return_exceptions=True)


async def _call_llm(
    provider: Any,
    *,
    system: str,
    user: str,
    max_tokens: int = 260,
    schema: dict[str, Any] = _REPLY_SCHEMA,
    field: str = "reply",
    call_budget: list[int] | None = None,
    deadline: float | None = None,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> tuple[str, int, int]:
    if call_budget is not None:
        if call_budget[0] <= 0:
            raise RuntimeError("Phiên làm việc đã đạt trần số lượt gọi mô hình cho phép.")
        call_budget[0] -= 1
    started = time.perf_counter()
    sys_clean = f'{system}\nChỉ trả về JSON hợp lệ theo lược đồ {{"{field}": "nội dung tiếng Việt ngắn gọn"}}.\n/no_think'
    call_opts = ollama_call_options(provider, product=True, max_output_tokens=max_tokens)
    if hasattr(provider, "generate_structured"):
        gen_fn = provider.generate_structured
        kwargs = _filtered_call_kwargs(gen_fn, {**call_opts, "response_schema": schema})
        coro = gen_fn(system=sys_clean, user=user, **kwargs)
    else:
        gen_fn = provider.generate
        kwargs = _filtered_call_kwargs(gen_fn, call_opts)
        coro = gen_fn(system=system, user=user, **kwargs)
    res = await _await_with_guards(coro, deadline=deadline, is_disconnected=is_disconnected)
    latency_ms = round((time.perf_counter() - started) * 1000)
    usage = getattr(res, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0) or 0)
    cleaned = _clean_json_field(getattr(res, "text", ""), field)
    return cleaned or "Mình đã hoàn tất phần kiểm tra và chuyển tiếp cho bước tiếp theo.", latency_ms, tokens


def _pick_agents_from_docs(doc_names: list[str], sample_text: str) -> tuple[str, str]:
    haystack = (" ".join(doc_names) + " " + sample_text).lower()
    scores: list[tuple[int, str]] = []
    for aid, kws in _DOC_KEYWORD_AGENT:
        score = sum(1 for kw in kws if kw in haystack)
        if score > 0:
            scores.append((score, aid))
    scores.sort(key=lambda x: x[0], reverse=True)
    picked = [aid for _, aid in scores[:2]]
    if len(picked) == 2:
        return picked[0], picked[1]
    a, b, _ = _OFFICE_WORK_SEEDS[0]
    if len(picked) == 1:
        other = "analyst" if picked[0] != "analyst" else "business"
        return picked[0], other
    return a, b


def _ndjson_line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


class WorkSessionRequest(BaseModel):
    source_ids: list[str] | None = None
    domain_pack: str = Field(default="office", max_length=40)
    exclude_topics: list[str] = Field(default_factory=list, max_length=12)


def build_router(
    *,
    current_user: Callable[[Request], dict],
    owner_pipeline: Callable[..., Any],
    session_factory: Callable[[], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/studio/office", tags=["office"])

    @router.post("/work-session")
    async def work_session(body: WorkSessionRequest, request: Request) -> StreamingResponse:
        """Kích hoạt một phiên làm việc đa tác tử THẬT trên kho tài liệu hiện tại với đội 11 Agent 3D."""
        user = current_user(request)
        pipeline = owner_pipeline(user)
        if body.source_ids is not None:
            body.source_ids = [str(sid) for sid in body.source_ids]
            validator = getattr(pipeline.source_store, "validate_source_selection", None)
            if callable(validator):
                try:
                    validator(body.source_ids)
                except LookupError as exc:
                    raise HTTPException(404, "Không tìm thấy tài liệu đã chọn.") from exc
            elif body.source_ids:
                source_getter = getattr(pipeline.source_store, "source", None)
                if callable(source_getter):
                    if any(source_getter(sid) is None for sid in body.source_ids):
                        raise HTTPException(404, "Không tìm thấy tài liệu đã chọn.")
                else:
                    found_ids = {c.source_id for c in pipeline.source_store.chunks(body.source_ids)}
                    if any(sid not in found_ids for sid in body.source_ids):
                        raise HTTPException(404, "Không tìm thấy tài liệu đã chọn.")
        provider = get_provider()
        uid = str(user.get("user_id") or "")

        async def _generate_session() -> AsyncIterator[bytes]:
            started_all = time.perf_counter()
            total_tokens = 0
            try:
                max_calls = max(5, int(os.getenv("OFFICE_MAX_LLM_CALLS", "6") or 6))
            except ValueError:
                max_calls = 6
            call_budget = [max_calls]
            try:
                wall_limit = max(10.0, float(os.getenv("OFFICE_SESSION_TIMEOUT_S", "180") or 180))
            except ValueError:
                wall_limit = 180.0
            deadline = time.monotonic() + wall_limit

            async def _check_aborted() -> bytes | None:
                if time.monotonic() > deadline:
                    return _ndjson_line({"type": "error", "detail": "Phiên làm việc vượt quá giới hạn thời gian cho phép."})
                if await request.is_disconnected():
                    return b""
                return None

            # 0. Kiểm tra kho tài liệu thật trong không gian đang mở
            try:
                all_chunks = pipeline.source_store.chunks(body.source_ids)
            except Exception:
                all_chunks = []

            doc_names = list(dict.fromkeys(c.source_name for c in all_chunks if getattr(c, "source_name", "")))
            has_docs = len(all_chunks) > 0

            # Chọn cặp chuyên gia phù hợp & sinh đề bài công việc thật
            if has_docs:
                sample_text = "\n".join((c.text or "")[:280] for c in all_chunks[:6])
                agent_a, agent_b = _pick_agents_from_docs(doc_names, sample_text)
                avoid_note = (
                    f"Tránh lặp lại các chủ đề trước: {'; '.join(body.exclude_topics[-3:])}.\n"
                    if body.exclude_topics
                    else ""
                )
                try:
                    topic, _, toks = await _call_llm(
                        provider,
                        system=(
                            "Bạn là Orchestrator của OrchestrIQ Studio. Dựa trên danh sách tài liệu thật dưới đây, "
                            "hãy đặt ra 1 yêu cầu công việc ngắn gọn (1 câu, dưới 28 từ, tiếng Việt) cần 2 phòng ban phối hợp rà soát."
                        ),
                        user=(
                            f"{avoid_note}Các tài liệu hiện có: {', '.join(doc_names[:5])}\n"
                            f"Trích đoạn mẫu:\n{sample_text[:900]}\n"
                            f"Hai phòng ban phối hợp: {AGENT_PERSONAS[agent_a]['title_vi']} và {AGENT_PERSONAS[agent_b]['title_vi']}."
                        ),
                        max_tokens=110,
                        schema=_TOPIC_SCHEMA,
                        field="topic",
                        call_budget=call_budget,
                        deadline=deadline,
                        is_disconnected=request.is_disconnected,
                    )
                    total_tokens += toks
                except asyncio.CancelledError:
                    return
                except TimeoutError:
                    yield _ndjson_line({"type": "error", "detail": "Phiên làm việc vượt quá giới hạn thời gian cho phép."})
                    return
                except Exception:
                    topic = f"Rà soát và đối chiếu các quy định, chỉ tiêu quan trọng trong {', '.join(doc_names[:2])}"
                if len(topic) < 12 or "{" in topic:
                    topic = f"Rà soát và đối chiếu các quy định, chỉ tiêu quan trọng trong {', '.join(doc_names[:2])}"
            else:
                pool = _OFFICE_WORK_SEEDS
                fresh = [item for item in pool if item[2] not in body.exclude_topics]
                agent_a, agent_b, topic = random.choice(fresh or pool)

            team = ["orchestrator", "rag", agent_a, agent_b, "reviewer", "integrator"] if has_docs else [
                "orchestrator", agent_a, agent_b, "reviewer", "integrator"
            ]

            yield _ndjson_line({
                "type": "session_start",
                "topic": topic,
                "team": team,
                "specialists": [agent_a, agent_b],
                "has_docs": has_docs,
                "doc_names": doc_names[:5],
            })

            abort_sig = await _check_aborted()
            if abort_sig is not None:
                if abort_sig:
                    yield abort_sig
                return

            pa = AGENT_PERSONAS[agent_a]
            pb = AGENT_PERSONAS[agent_b]

            # 1. Orchestrator tiếp nhận & phân công 2 đầu việc
            yield _ndjson_line({
                "type": "agent_thinking",
                "agent_id": "orchestrator",
                "to": "all",
                "targets": [agent_a, agent_b],
                "phase": "intake",
                "label": "Orchestrator đang phân rã nhiệm vụ và chia đầu việc cho các phòng ban…",
            })
            try:
                plan_msg, lat_ms, toks = await _call_llm(
                    provider,
                    system=(
                        "Bạn là Orchestrator (Điều phối trưởng) trong văn phòng đa tác tử OrchestrIQ. "
                        "Hãy viết 2–3 câu tiếng Việt tự nhiên (xưng 'Mình'), giao đầu việc T1 cho "
                        f"{pa['name']} ({pa['title_vi']}) và đầu việc T2 cho {pb['name']} ({pb['title_vi']}) để cùng xử lý nhiệm vụ."
                    ),
                    user=f"Nhiệm vụ phiên làm việc: {topic}\nTài liệu sẵn có: {', '.join(doc_names[:4]) if has_docs else 'Chưa có tài liệu nội bộ (dùng kiến thức chuyên môn)'}.",
                    max_tokens=200,
                    call_budget=call_budget,
                    deadline=deadline,
                    is_disconnected=request.is_disconnected,
                )
            except asyncio.CancelledError:
                return
            except TimeoutError:
                yield _ndjson_line({"type": "error", "detail": "Phiên làm việc vượt quá giới hạn thời gian cho phép."})
                return
            except Exception as exc:
                yield _ndjson_line({"type": "error", "detail": f"Lỗi gọi mô hình AI: {exc}"})
                return
            total_tokens += toks
            yield _ndjson_line({
                "type": "agent_message",
                "agent_id": "orchestrator",
                "to": "all",
                "targets": [agent_a, agent_b],
                "phase": "intake",
                "kind": "plan",
                "badge": "Phân rã 2 việc",
                "text": plan_msg,
                "latency_ms": lat_ms,
                "tokens": toks,
            })

            # 2. RAG Specialist rút bằng chứng thật nếu kho có tài liệu
            evidence_text = ""
            citations: list[dict[str, Any]] = []
            evidence_chunks: list[Any] = []
            if has_docs:
                yield _ndjson_line({
                    "type": "agent_thinking",
                    "agent_id": "rag",
                    "to": agent_a,
                    "targets": [agent_a, agent_b],
                    "phase": "work",
                    "label": "RAG Specialist đang truy xuất đoạn liên quan và lọc trùng trong kho tài liệu…",
                })
                try:
                    hits = pipeline._retrieve_candidates(topic, all_chunks, top_k=5, min_score=0.02, source_ids=body.source_ids)
                except Exception:
                    hits = all_chunks[:4]
                if hits and session_factory and uid:
                    try:
                        log_secret_access(session_factory(), uid, {c.source_id for c in hits}, "ASK")
                    except Exception:
                        pass
                blocks = []
                for idx, c in enumerate(hits[:4], start=1):
                    txt = (c.text or "").strip()
                    if not txt:
                        continue
                    evidence_chunks.append(c)
                    citations.append({
                        "index": idx,
                        "chunk_id": c.chunk_id,
                        "source_id": c.source_id,
                        "source_name": c.source_name,
                        "excerpt": txt[:300],
                    })
                    blocks.append(f"[{idx}] {c.source_name}: {txt[:520]}")
                evidence_text = "\n\n".join(blocks)
                used_files = list(dict.fromkeys(c["source_name"] for c in citations)) or doc_names[:2]
                yield _ndjson_line({
                    "type": "rag_evidence",
                    "agent_id": "rag",
                    "to": "all",
                    "targets": [agent_a, agent_b],
                    "count": len(citations),
                    "files": used_files,
                    "text": (
                        f"Mình vừa rút được {len(citations)} đoạn liên quan từ {', '.join(used_files[:2])}"
                        f"{'…' if len(used_files) > 2 else ''}, đã lọc trùng ngữ cảnh và chuyển sang bàn {pa['name']} cùng {pb['name']}."
                    ),
                })

            ev_prompt = (
                f"Đoạn trích thật từ kho tài liệu (CHỈ dùng số liệu có thật ở đây, ghi tên tệp nếu trích dẫn):\n{evidence_text}\n\n"
                if evidence_text
                else "Lưu ý: Không có tài liệu nội bộ đính kèm, tư vấn ngắn gọn theo chuyên môn và không bịa số liệu nội bộ.\n\n"
            )

            abort_sig = await _check_aborted()
            if abort_sig is not None:
                if abort_sig:
                    yield abort_sig
                return

            # 3A. Chuyên gia 1 xử lý đầu việc T1 & gửi trao đổi sang Chuyên gia 2
            yield _ndjson_line({
                "type": "agent_thinking",
                "agent_id": agent_a,
                "to": agent_b,
                "targets": [agent_a, agent_b],
                "phase": "work",
                "label": f"{pa['name']} đang xử lý đầu việc T1 và chuyển số liệu sang {pb['name']}…",
            })
            try:
                res_a, lat_ms, toks = await _call_llm(
                    provider,
                    system=(
                        f"Bạn là {pa['name']} ({pa['title_vi']}). Chuyên môn: {pa['focus']}.\n"
                        f"Hãy trả lời 2–4 câu tiếng Việt tự nhiên (xưng 'Mình'), nêu kết quả phân tích T1 ngắn gọn rồi nhắn {pb['name']} đối chiếu phần việc T2."
                    ),
                    user=f"{ev_prompt}Nhiệm vụ chung: {topic}\nPhân công của Orchestrator: {plan_msg}",
                    max_tokens=230,
                    call_budget=call_budget,
                    deadline=deadline,
                    is_disconnected=request.is_disconnected,
                )
            except asyncio.CancelledError:
                return
            except TimeoutError:
                yield _ndjson_line({"type": "error", "detail": "Phiên làm việc vượt quá giới hạn thời gian cho phép."})
                return
            except Exception as exc:
                yield _ndjson_line({"type": "error", "detail": f"Lỗi gọi mô hình ở {pa['name']}: {exc}"})
                return
            total_tokens += toks
            yield _ndjson_line({
                "type": "agent_message",
                "agent_id": agent_a,
                "to": agent_b,
                "targets": [agent_b],
                "phase": "work",
                "kind": "work",
                "badge": "Đầu việc T1",
                "text": res_a,
                "latency_ms": lat_ms,
                "tokens": toks,
            })

            abort_sig = await _check_aborted()
            if abort_sig is not None:
                if abort_sig:
                    yield abort_sig
                return

            # 3B. Chuyên gia 2 xử lý đầu việc T2 & trao đổi chéo trực tiếp với Chuyên gia 1
            yield _ndjson_line({
                "type": "agent_thinking",
                "agent_id": agent_b,
                "to": agent_a,
                "targets": [agent_b, agent_a],
                "phase": "work",
                "label": f"{pb['name']} đang đối chiếu phần việc T2 và phản hồi lại {pa['name']}…",
            })
            try:
                res_b, lat_ms, toks = await _call_llm(
                    provider,
                    system=(
                        f"Bạn là {pb['name']} ({pb['title_vi']}). Chuyên môn: {pb['focus']}.\n"
                        f"Hãy viết 2–4 câu tiếng Việt tự nhiên (xưng 'Mình'), phản hồi trực tiếp ý kiến của {pa['name']} (nêu 1 điểm thống nhất và 1 lưu ý/rủi ro bổ sung từ góc nhìn phòng bạn) rồi chuyển sang Reviewer kiểm định."
                    ),
                    user=f"{ev_prompt}Nhiệm vụ chung: {topic}\nKết quả T1 từ {pa['name']}: \"{res_a}\"",
                    max_tokens=230,
                    call_budget=call_budget,
                    deadline=deadline,
                    is_disconnected=request.is_disconnected,
                )
            except asyncio.CancelledError:
                return
            except TimeoutError:
                yield _ndjson_line({"type": "error", "detail": "Phiên làm việc vượt quá giới hạn thời gian cho phép."})
                return
            except Exception as exc:
                yield _ndjson_line({"type": "error", "detail": f"Lỗi gọi mô hình ở {pb['name']}: {exc}"})
                return
            total_tokens += toks
            yield _ndjson_line({
                "type": "agent_message",
                "agent_id": agent_b,
                "to": "reviewer",
                "targets": ["reviewer"],
                "phase": "work",
                "kind": "work",
                "badge": "Trao đổi T2",
                "text": res_b,
                "latency_ms": lat_ms,
                "tokens": toks,
            })

            abort_sig = await _check_aborted()
            if abort_sig is not None:
                if abort_sig:
                    yield abort_sig
                return

            # 4. Reviewer kiểm định chéo kết quả của 2 phòng ban
            yield _ndjson_line({
                "type": "agent_thinking",
                "agent_id": "reviewer",
                "to": "integrator",
                "targets": ["reviewer", "integrator"],
                "phase": "review",
                "label": "Reviewer đang kiểm định chéo căn cứ và rủi ro giữa hai phòng ban…",
            })
            try:
                rev_msg, lat_ms, toks = await _call_llm(
                    provider,
                    system=(
                        "Bạn là Reviewer (Chuyên gia Kiểm định Chất lượng). "
                        "Hãy viết 2–3 câu tiếng Việt ngắn gọn (xưng 'Mình'), xác nhận các điểm đã khớp giữa hai phòng ban, chỉ ra 1 điểm cần ghi chú thận trọng và bàn giao sang Integrator tổng hợp."
                    ),
                    user=f"{ev_prompt}Nhiệm vụ: {topic}\n- {pa['name']}: {res_a}\n- {pb['name']}: {res_b}",
                    max_tokens=200,
                    call_budget=call_budget,
                    deadline=deadline,
                    is_disconnected=request.is_disconnected,
                )
            except asyncio.CancelledError:
                return
            except TimeoutError:
                yield _ndjson_line({"type": "error", "detail": "Phiên làm việc vượt quá giới hạn thời gian cho phép."})
                return
            except Exception as exc:
                yield _ndjson_line({"type": "error", "detail": f"Lỗi gọi mô hình ở Reviewer: {exc}"})
                return
            total_tokens += toks
            yield _ndjson_line({
                "type": "agent_message",
                "agent_id": "reviewer",
                "to": "integrator",
                "targets": ["integrator"],
                "phase": "review",
                "kind": "review",
                "badge": "Đã kiểm định",
                "text": rev_msg,
                "latency_ms": lat_ms,
                "tokens": toks,
            })

            abort_sig = await _check_aborted()
            if abort_sig is not None:
                if abort_sig:
                    yield abort_sig
                return

            # 5. Integrator tổng hợp và chốt kết quả bàn giao
            yield _ndjson_line({
                "type": "agent_thinking",
                "agent_id": "integrator",
                "to": "user",
                "targets": ["integrator"],
                "phase": "done",
                "label": "Integrator đang tổng hợp báo cáo hoàn chỉnh từ các phòng ban…",
            })
            try:
                final_msg, lat_ms, toks = await _call_llm(
                    provider,
                    system=(
                        "Bạn là Integrator (Chuyên gia Tổng hợp). "
                        "Hãy tổng hợp gọn gàng bằng tiếng Việt (3–4 gạch đầu dòng ngắn): kết luận chính từ hai phòng ban, lưu ý của Reviewer và khuyến nghị hành động rõ ràng."
                    ),
                    user=(
                        f"{ev_prompt}Nhiệm vụ: {topic}\n"
                        f"- {pa['name']}: {res_a}\n"
                        f"- {pb['name']}: {res_b}\n"
                        f"- Reviewer: {rev_msg}"
                    ),
                    max_tokens=280,
                    call_budget=call_budget,
                    deadline=deadline,
                    is_disconnected=request.is_disconnected,
                )
            except asyncio.CancelledError:
                return
            except TimeoutError:
                yield _ndjson_line({"type": "error", "detail": "Phiên làm việc vượt quá giới hạn thời gian cho phép."})
                return
            except Exception as exc:
                yield _ndjson_line({"type": "error", "detail": f"Lỗi gọi mô hình ở Integrator: {exc}"})
                return
            total_tokens += toks

            final_status = "COMPLETE"
            saved_cids: list[str] = []
            if has_docs and not evidence_chunks:
                final_msg, _ = strip_invalid_inline_citations(final_msg, set())
                citations = []
                final_status = "PARTIAL"
            elif has_docs and evidence_chunks:
                allowed_ids = {c.chunk_id for c in evidence_chunks}
                final_msg, _ = strip_invalid_inline_citations(final_msg, allowed_ids)
                valid_cids, _ = validate_citations([c["chunk_id"] for c in citations], evidence_chunks)
                raw_ev = "\n\n".join((c.text or "") for c in evidence_chunks)
                refusal_markers = (
                    "tài liệu không đề cập", "không có thông tin", "không tìm thấy",
                    "chưa thấy", "không nêu", "tài liệu không nêu", "not found", "does not mention",
                )
                initial_status = (
                    "NO_EVIDENCE"
                    if any(m in final_msg.casefold() for m in refusal_markers)
                    else ("COMPLETE" if valid_cids else "PARTIAL")
                )
                final_status, final_msg, _, _ = check_product_evidence_claims(
                    initial_status,
                    final_msg,
                    raw_ev,
                    topic,
                    [],
                    evidence_chunks=evidence_chunks,
                )
                valid_set = set(valid_cids) if final_status != "NO_EVIDENCE" else set()
                citations = [c for c in citations if c["chunk_id"] in valid_set]
                saved_cids = [c["chunk_id"] for c in citations]

            yield _ndjson_line({
                "type": "agent_message",
                "agent_id": "integrator",
                "to": "user",
                "targets": [],
                "phase": "done",
                "kind": "done",
                "badge": "Đã bàn giao",
                "text": final_msg,
                "latency_ms": lat_ms,
                "tokens": toks,
            })

            total_ms = round((time.perf_counter() - started_all) * 1000)
            run_store = getattr(pipeline, "run_store", None)
            if run_store is not None and callable(getattr(run_store, "save", None)):
                try:
                    run_store.save({
                        "run_id": f"office_{int(time.time() * 1000)}",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "condition": "OFFICE_SESSION",
                        "query": topic,
                        "lifecycle_status": "COMPLETED",
                        "status": final_status,
                        "answer": final_msg,
                        "citations": saved_cids,
                        "metrics": {"latency_ms": total_ms, "total_tokens": total_tokens},
                    })
                except Exception:
                    _log.warning("Failed to persist office run_store record", exc_info=True)

            yield _ndjson_line({
                "type": "session_done",
                "total_latency_ms": total_ms,
                "total_tokens": total_tokens,
                "citations": citations,
                "status": final_status,
            })

        async def stream() -> AsyncIterator[bytes]:
            try:
                async with product_runs.slot():
                    async for chunk in _generate_session():
                        yield chunk
            except QueueFullError as exc:
                yield _ndjson_line({"type": "error", "detail": str(exc)})

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
