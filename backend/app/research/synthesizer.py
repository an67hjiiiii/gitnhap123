from __future__ import annotations
from app.core.structured_output import parse_answer_json
from app.core.types import TaskResult, RunMetrics
from app.research.progress import answer_streamer

SYNTH_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

SYNTH_LANGUAGE_HINT = {
    "vi": "NGÔN NGỮ: Viết toàn bộ câu trả lời bằng tiếng Việt, kể cả khi kết quả tác tử là tiếng Anh.",
    "en": "LANGUAGE: Write the whole answer in English.",
}


async def synthesize(provider, query: str, results: list[TaskResult], metrics: RunMetrics, reply_language: str | None = None, max_output_tokens: int | None = None) -> str:
    compact = []
    all_citations: list[str] = []
    for r in results:
        all_citations.extend(r.citations)
        compact.append(
            f"TASK {r.task_id} [{r.domain}] status={r.status}\n"
            f"answer={r.answer}\n"
            f"citations={','.join(r.citations)}\n"
            f"available_evidence={','.join(r.evidence_ids)}\n"
            f"missing={','.join(r.missing_information)}"
        )
    system = (
        "SYNTHESIZER. Combine structured task results. Do not invent evidence or new facts. "
        "Preserve exact citation IDs already validated by workers. If a task is PARTIAL/NO_EVIDENCE, say so clearly. "
        "Write the final answer for the user as plain prose (Markdown allowed). Do not return JSON."
    )
    user = f"USER REQUEST:\n{query}\n\nTASK RESULTS:\n" + "\n\n".join(compact)
    if reply_language in SYNTH_LANGUAGE_HINT:
        user += "\n\n" + SYNTH_LANGUAGE_HINT[reply_language]
    structured = getattr(provider, "generate_structured", None)
    if max_output_tokens is not None and callable(structured) and getattr(provider, "supports_per_call_output_tokens", False):
        # Ô chat sản phẩm: khuôn {"answer"} + giới hạn riêng. Không khuôn thì qwen3 viết suy nghĩ ra câu trả lời;
        # prompt cũ lại khớp nhầm "WORKER" nên bị ép JSON tự do và cắt ở 700 token. Thực nghiệm giữ nhánh dưới như cũ.
        result = await structured(
            system=system.replace(" Do not return JSON.", "")
            + ' Return JSON {"answer": "<the final answer for the user as Markdown prose>"}.',
            user=user,
            response_schema=SYNTH_SCHEMA,
            max_output_tokens=max_output_tokens,
            **answer_streamer(provider),
        )
        metrics.add_usage(result.usage)
        text = str(parse_answer_json(result.text).get("answer") or "").strip() or result.text.strip()
    else:
        result = await provider.generate(system=system, user=user)
        metrics.add_usage(result.usage)
        text = result.text.strip()
    unique = list(dict.fromkeys(all_citations))
    # The worker citations are already validated; append them if the synthesis model dropped locators.
    if unique and not any(cid in text for cid in unique):
        text += "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in unique)
    return text
