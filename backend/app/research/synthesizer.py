from __future__ import annotations

import os
import re

from app.core.config import RuntimeConfig
from app.core.text_clean import strip_placeholder_tags
from app.core.types import RunMetrics, TaskResult


_MIN_BODY_FOR_SUMMARY = 600
DOMAIN_LABELS = {
    "security": "Bảo mật",
    "database": "Cơ sở dữ liệu",
    "api_architecture": "API / Kiến trúc",
    "general": "Tổng quan",
}


def _mostly_in(summary: str, body: str) -> bool:
    words = [w for w in re.findall(r"\w+", summary.casefold()) if len(w) > 2]
    if not words:
        return True
    pool = set(re.findall(r"\w+", body.casefold()))
    return sum(w in pool for w in words) / len(words) >= 0.85


SYNTH_LANGUAGE_HINT = {
    "vi": "NGÔN NGỮ: Viết bản tóm tắt bằng tiếng Việt, kể cả khi kết quả tác tử là tiếng Anh.",
    "en": "LANGUAGE: Write the summary in English.",
}


async def synthesize(provider, query: str, results: list[TaskResult], metrics: RunMetrics, reply_language: str | None = None) -> str:
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
    body = strip_placeholder_tags(body)
    min_body = int(os.getenv("SYNTH_MIN_BODY_CHARS", str(_MIN_BODY_FOR_SUMMARY)))
    if min_body > 0 and (len(grouped) < 2 or len(body) < min_body):  # a summary of a short answer only repeats it
        return body
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
    if reply_language in SYNTH_LANGUAGE_HINT:
        user += "\n\n" + SYNTH_LANGUAGE_HINT[reply_language]
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
    text = strip_placeholder_tags(text)
    if not text or _mostly_in(text, body):
        return body
    return body + "\n\n**Tóm tắt**\n" + text
