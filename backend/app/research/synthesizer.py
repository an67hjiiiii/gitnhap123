from __future__ import annotations

import re

from app.core.config import RuntimeConfig
from app.core.types import RunMetrics, TaskResult


DOMAIN_LABELS = {
    "security": "Bảo mật",
    "database": "Cơ sở dữ liệu",
    "api_architecture": "API / Kiến trúc",
    "general": "Tổng quan",
}


async def synthesize(provider, query: str, results: list[TaskResult], metrics: RunMetrics) -> str:
    """Assemble immutable task answers; the model supplies only an optional summary."""
    grouped: dict[str, list[str]] = {}
    compact = []
    allowed_ids: set[str] = set()
    for result in results:
        parts = grouped.setdefault(result.domain, [])
        parts.append(result.answer)
        absent = [cid for cid in dict.fromkeys(result.citations) if f"[{cid}]" not in result.answer]
        if absent:
            parts.append("Nguồn: " + ", ".join(f"[{cid}]" for cid in absent))
        if result.status in {"PARTIAL", "NO_EVIDENCE"} and result.missing_information:
            parts.append(
                "Mình chưa tìm thấy " + "; ".join(result.missing_information)
                + ". Bạn hãy tải thêm tài liệu liên quan đến phần này."
            )
        allowed_ids.update(result.citations)
        allowed_ids.update(result.evidence_ids)
        compact.append(
            f"TASK {result.task_id} [{result.domain}] status={result.status}\n"
            f"answer={result.answer}\nmissing={','.join(result.missing_information)}"
        )
    body = "\n\n".join(
        f"**{DOMAIN_LABELS.get(domain, domain)}**\n" + "\n\n".join(parts)
        for domain, parts in grouped.items()
    )
    cfg = RuntimeConfig.from_env()
    remaining = cfg.max_run_tokens - metrics.input_tokens - metrics.output_tokens
    summary_budget = min(160, cfg.max_output_tokens, remaining)
    if summary_budget <= 0:
        return body
    system = (
        "SYNTHESIZER. Chỉ viết một bản tóm tắt ngắn bằng tiếng Việt: 1-3 câu, tối đa 60 từ. "
        "Không thêm sự kiện hay bằng chứng mới, không thêm citation mới. "
        "Chỉ tóm tắt TASK RESULTS; không viết lại các câu trả lời, không thêm tiêu đề."
    )
    user = f"USER REQUEST:\n{query}\n\nTASK RESULTS:\n" + "\n\n".join(compact)
    try:
        result = await provider.generate(system=system, user=user)
    except Exception as exc:
        if getattr(exc, "usage", None) is not None:
            metrics.add_usage(exc.usage)
        metrics.failed_llm_attempts += 1
        return body
    metrics.add_usage(result.usage)
    text = re.sub(
        r"\[([^\[\]\s]+)\]",
        lambda match: match.group(0) if match.group(1) in allowed_ids else "",
        result.text,
    ).strip()
    if (
        result.usage.output_tokens > summary_budget
        or metrics.input_tokens + metrics.output_tokens > cfg.max_run_tokens
        or getattr(result, "done_reason", None) in {"length", "max_tokens"}
        or len(text.split()) > 60
    ):
        return body
    return body + ("\n\n**Tóm tắt**\n" + text if text else "")
