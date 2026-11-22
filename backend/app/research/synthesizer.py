from __future__ import annotations
from app.core.answer_checks import IMG_MARK, apply_calc, clean, finish, unsupported_articles, unsupported_quantities
from app.core.citations import strip_unauthorized_citations
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


async def synthesize(provider, query: str, results: list[TaskResult], metrics: RunMetrics, reply_language: str | None = None, max_output_tokens: int | None = None,
                     evidence_text: str | None = None, guard_report: dict | None = None) -> str:
    if guard_report is not None:
        guard_report.update(partial=False, no_evidence=False)
    if max_output_tokens is not None and (not results or all(r.status == "NO_EVIDENCE" for r in results)):
        if guard_report is not None:
            guard_report["no_evidence"] = True
        return "Kh\u00f4ng t\u00ecm th\u1ea5y b\u1eb1ng ch\u1ee9ng ph\u00f9 h\u1ee3p trong ngu\u1ed3n \u0111\u00e3 ch\u1ecdn."
    compact = []
    all_citations: list[str] = []
    for r in results:
        all_citations.extend(cid for cid in r.citations if cid in set(r.evidence_ids))
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
    if max_output_tokens is not None and IMG_MARK in query:
        user += ("\n\nCASE FROM IMAGE: the text after \"" + IMG_MARK + "\" is the user's case data. Compare each fact with the thresholds "
                 "and conditions in the task results, state each comparison explicitly (e.g. 0,72 < 1,0) and give a clear conclusion.")
    structured = getattr(provider, "generate_structured", None)
    if max_output_tokens is not None and callable(structured) and getattr(provider, "supports_per_call_output_tokens", False):
        # Ô chat sản phẩm: khuôn {"answer"} + giới hạn riêng. Không khuôn thì qwen3 viết suy nghĩ ra câu trả lời;
        # prompt cũ lại khớp nhầm "WORKER" nên bị ép JSON tự do và cắt ở 700 token. Thực nghiệm giữ nhánh dưới như cũ.
        result = await structured(
            system=system.replace(" Do not return JSON.", "")
            + " FORMAT: open with 1-2 sentences answering directly; for multi-part content use short '### ' headings, bullets with **bold keywords**, "
            "numbered steps for procedures, and a Markdown table (header row, citation IDs in a column named Nguồn/Source) when comparing or listing items with shared attributes. "
            "Keep simple answers short. Never mention internal task IDs (T1, T2) or the word 'task' to the user; check every item the user asked about. "
            "If the user asks for a table, you MUST answer with a filled Markdown table. Copy every number, year and rate verbatim from the task results. "
            "Never do arithmetic yourself: write each calculation as [[= expression ]] using only digits, + - * / and parentheses (150% as 1.5); "
            "the system replaces it with the result."
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
    if max_output_tokens is not None:
        known = {cid for result in results for cid in (*result.evidence_ids, *result.citations, *result.invalid_citations)}
        cleaned = strip_unauthorized_citations(text, set(unique), known)
        removed = cleaned != text
        text = cleaned
        if evidence_text:
            sources = evidence_text + "\n" + query
            articles = unsupported_articles(text, sources)
            quantities = unsupported_quantities(text, evidence_text)
            text, bad = finish(text, sources)
            if bad or articles or quantities:
                text = "Kh\u00f4ng \u0111\u1ee7 c\u0103n c\u1ee9 \u0111\u1ec3 x\u00e1c nh\u1eadn s\u1ed1 li\u1ec7u ho\u1eb7c \u0111i\u1ec1u kho\u1ea3n trong k\u1ebft qu\u1ea3 t\u1ed5ng h\u1ee3p."
                if guard_report is not None:
                    guard_report["partial"] = True
        else:
            text = apply_calc(clean(text))
        if removed and guard_report is not None:
            guard_report["partial"] = True
    # The worker citations are already validated; append them if the synthesis model dropped locators.
    if unique and not any(cid in text for cid in unique):
        text += "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in unique)
    return text
