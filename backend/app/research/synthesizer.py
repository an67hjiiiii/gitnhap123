from __future__ import annotations
import re
from app.core.types import TaskResult, RunMetrics

async def synthesize(provider, query: str, results: list[TaskResult], metrics: RunMetrics) -> str:
    compact = []
    all_citations: list[str] = []
    allowed_ids: set[str] = set()
    for r in results:
        all_citations.extend(r.citations)
        allowed_ids.update(r.citations)
        allowed_ids.update(r.evidence_ids)
        compact.append(
            f"TASK {r.task_id} [{r.domain}] status={r.status}\n"
            f"answer={r.answer}\n"
            f"citations={','.join(r.citations)}\n"
            f"available_evidence={','.join(r.evidence_ids)}\n"
            f"missing={','.join(r.missing_information)}"
        )
    system = (
        "SYNTHESIZER. Combine structured task results. Do not invent evidence or new facts. "
        "Preserve exact citation IDs already validated by workers. If a task is PARTIAL/NO_EVIDENCE, say so clearly."
    )
    user = f"USER REQUEST:\n{query}\n\nTASK RESULTS:\n" + "\n\n".join(compact)
    result = await provider.generate(system=system, user=user)
    metrics.add_usage(result.usage)
    text = result.text.strip()
    # Locators are single, non-whitespace IDs enclosed in square brackets.
    text = re.sub(
        r"\[([^\[\]\s]+)\]",
        lambda match: match.group(0) if match.group(1) in allowed_ids else "",
        text,
    )
    unique = list(dict.fromkeys(all_citations))
    # The worker citations are already validated; append them if the synthesis model dropped locators.
    if unique and not any(cid in text for cid in unique):
        text += "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in unique)
    return text
