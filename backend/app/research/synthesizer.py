from __future__ import annotations
from app.core.types import TaskResult, RunMetrics

SYNTH_LANGUAGE_HINT = {
    "vi": "NGÔN NGỮ: Viết toàn bộ câu trả lời bằng tiếng Việt, kể cả khi kết quả tác tử là tiếng Anh.",
    "en": "LANGUAGE: Write the whole answer in English.",
}


async def synthesize(provider, query: str, results: list[TaskResult], metrics: RunMetrics, reply_language: str | None = None) -> str:
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
    result = await provider.generate(system=system, user=user)
    metrics.add_usage(result.usage)
    text = result.text.strip()
    unique = list(dict.fromkeys(all_citations))
    # The worker citations are already validated; append them if the synthesis model dropped locators.
    if unique and not any(cid in text for cid in unique):
        text += "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in unique)
    return text
