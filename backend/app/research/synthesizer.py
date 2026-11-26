from __future__ import annotations
from app.core.answer_checks import IMG_MARK, apply_calc, check_product_evidence_claims, clean, strip_invalid_inline_citations
from app.core.structured_output import parse_answer_json
from app.core.types import TaskResult, RunMetrics
from app.research.progress import answer_streamer, emit_validated_answer
from app.research.token_budget import count_prompt_tokens, resolve_product_num_ctx

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
                     evidence_text: str | None = None, revision_note: str | None = None,
                     num_ctx: int | None = None, request_timeout: float | None = None,
                     synth_meta: dict | None = None, evidence_chunks: list | None = None) -> str:
    compact = []
    for r in results:
        # nguồn tri thức chỉ ghi khi khác tài liệu (chỉ ô chat sản phẩm tạo ra), prompt thực nghiệm giữ nguyên
        source = f" source={r.source}" if r.source != "documents" else ""
        compact.append(
            f"TASK {r.task_id} [{r.domain}] status={r.status}{source}\n"
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
    def _build_user(joined_compact: str) -> str:
        body = f"USER REQUEST:\n{query}\n\nTASK RESULTS:\n{joined_compact}"
        if revision_note:  # Reviewer trả bài (chỉ ô chat sản phẩm)
            body += "\n\n" + revision_note
        if any(r.source != "documents" for r in results):
            body += ("\n\nKNOWLEDGE SOURCES: tasks marked source=general (and the 'Kiến thức chung:' part of source=both) come from general knowledge, "
                     "not from the user's documents. You MAY use that content (it is not invented by you), but keep it in a clearly labelled part "
                     "(a '### Kiến thức chung' heading, or '### General knowledge' in English), never attach document citations to it, "
                     "and keep document-based parts with their citations.")
        if reply_language in SYNTH_LANGUAGE_HINT:
            body += "\n\n" + SYNTH_LANGUAGE_HINT[reply_language]
        if max_output_tokens is not None and IMG_MARK in query:
            body += ("\n\nCASE FROM IMAGE: the text after \"" + IMG_MARK + "\" is the user's case data. Compare each fact with the thresholds "
                     "and conditions in the task results, state each comparison explicitly (e.g. 0,72 < 1,0) and give a clear conclusion.")
        return body

    joined_compact = "\n\n".join(compact)
    kept_results = list(results)
    context_trimmed = False
    effective_num_ctx: int | None = None
    if max_output_tokens is not None or num_ctx is not None:
        effective_num_ctx = num_ctx if num_ctx is not None else resolve_product_num_ctx()
        available = effective_num_ctx - max(64, int(max_output_tokens or 700)) - 256 - count_prompt_tokens(system) - count_prompt_tokens(_build_user(""))
        if available > 128 and count_prompt_tokens(joined_compact) > available and compact:
            kept_compact: list[str] = []
            kept_subset: list[TaskResult] = []
            used = 0
            for r_item, item in zip(results, compact):
                cost = count_prompt_tokens(("\n\n" if kept_compact else "") + item)
                if used + cost <= available:
                    kept_compact.append(item)
                    kept_subset.append(r_item)
                    used += cost
                else:
                    context_trimmed = True
                    break
            if len(kept_compact) < len(compact):
                context_trimmed = True
            kept_results = kept_subset if kept_subset else [results[0]]
            joined_compact = "\n\n".join(kept_compact) if kept_compact else compact[0][: max(256, available * 2)]
    if synth_meta is not None and context_trimmed:
        synth_meta["context_trimmed"] = True
        dropped_ids = [r.task_id for r in results if r not in kept_results]
        if dropped_ids:
            synth_meta["dropped_tasks"] = dropped_ids
    user = _build_user(joined_compact)
    extra_opts: dict = {}
    if (max_output_tokens is not None or num_ctx is not None) and effective_num_ctx is not None and getattr(provider, "supports_num_ctx", False):
        extra_opts["num_ctx"] = effective_num_ctx
    if request_timeout is not None and getattr(provider, "supports_per_call_timeout", False):
        extra_opts["timeout"] = request_timeout
    structured = getattr(provider, "generate_structured", None)
    output_truncated = False
    if max_output_tokens is not None and callable(structured) and getattr(provider, "supports_per_call_output_tokens", False):
        # Ô chat sản phẩm: khuôn {"answer"} + giới hạn riêng. Không khuôn thì qwen3 viết suy nghĩ ra câu trả lời;
        # prompt cũ lại khớp nhầm "WORKER" nên bị ép JSON tự do và cắt ở 700 token. Thực nghiệm giữ nhánh dưới như cũ.
        result = await structured(
            system=system.replace(" Do not return JSON.", "")
            + " FORMAT: open with 1-2 sentences answering directly; for multi-part content use short '### ' headings, bullets with **bold keywords**, "
            "numbered steps for procedures, and a Markdown table (header row, citation IDs in a column named Nguồn/Source) when comparing or listing items with shared attributes. "
            "Keep simple answers short. Never mention internal task IDs (T1, T2) or the word 'task' to the user; check every item the user asked about. "
            "If the user asks for a table, you MUST answer with a filled Markdown table. Copy every number, year and rate verbatim from the task results. "
            "Never do arithmetic yourself: write each calculation as [[= expression ]] using only digits, + - * / // and parentheses (150% as 1.5; use // for \"every full N\" rules, e.g. 12 + 6//5); "
            "the system replaces it with the result."
            + ' Return JSON {"answer": "<the final answer for the user as Markdown prose>"}.',
            user=user,
            response_schema=SYNTH_SCHEMA,
            max_output_tokens=max_output_tokens,
            **extra_opts,
            **answer_streamer(provider, buffered=True),
        )
        metrics.add_usage(result.usage)
        parsed = parse_answer_json(result.text)
        output_truncated = bool(parsed.get("truncated"))
        text = str(parsed.get("answer") or "").strip() or result.text.strip()
    else:
        result = await provider.generate(system=system, user=user)
        metrics.add_usage(result.usage)
        text = result.text.strip()
    if max_output_tokens is not None:  # ô chat sản phẩm: chỉ giữ citation của task được nạp vào prompt và có status != NO_EVIDENCE
        kept_used = [r for r in kept_results if r.status != "NO_EVIDENCE"]
        all_citations = [cid for r in kept_used for cid in (r.citations or []) if cid]
        allowed_cids = set(all_citations)
        text, bad_inline = strip_invalid_inline_citations(text, allowed_cids)
        if synth_meta is not None and bad_inline:
            synth_meta["invalid_inline_citations"] = bad_inline
        if evidence_text:
            post_status, text, bad_nums, bad_arts = check_product_evidence_claims(
                "COMPLETE", text, evidence_text, query, [], evidence_chunks=evidence_chunks
            )
            if synth_meta is not None:
                if bad_nums:
                    synth_meta["unsupported_numbers"] = bad_nums
                if bad_arts:
                    synth_meta["unsupported_articles"] = bad_arts
                if post_status != "COMPLETE":
                    synth_meta["post_synth_validation_partial"] = True
        else:
            text = apply_calc(clean(text))
        if output_truncated:
            if synth_meta is not None:
                synth_meta["truncated"] = True
            text += ("\n\n> **Note:** response output was truncated at the length limit; content may be incomplete."
                     if reply_language == "en"
                     else "\n\n> **Lưu ý:** câu trả lời bị cắt ngắn do chạm giới hạn độ dài; nội dung có thể chưa đầy đủ.")
        if context_trimmed:
            text += ("\n\n> **Note:** some task results were trimmed to fit the context window; answer covers only part of the evidence."
                     if reply_language == "en"
                     else "\n\n> **Lưu ý:** một phần kết quả bị cắt bớt để vừa cửa sổ ngữ cảnh; câu trả lời có thể chưa đầy đủ.")
        unique = list(dict.fromkeys(all_citations))
        missing_cits = [cid for cid in unique if cid not in text]
        if missing_cits:
            if synth_meta is not None:
                synth_meta["unmapped_worker_citations"] = missing_cits
                synth_meta["grounding_scope"] = "chunk_id_presence_only_not_claim_verified"
            text += (
                "\n\n> **Citation notice:** worker-referenced chunks not mapped sentence-by-sentence (not claim-verified): "
                + ", ".join(f"[{cid}]" for cid in missing_cits)
                if reply_language == "en"
                else "\n\n> **Lưu ý trích dẫn:** các mã nguồn sau do bước xử lý sử dụng nhưng chưa đối chiếu ở cấp từng nhận định (not claim-verified): "
                + ", ".join(f"[{cid}]" for cid in missing_cits)
            )
        emit_validated_answer(text)
    else:
        # Thực nghiệm A/B/C: bảo toàn y nguyên quy tắc nối citation trước B137
        all_citations = [cid for r in results for cid in (r.citations or []) if cid]
        unique = list(dict.fromkeys(all_citations))
        if unique and not any(cid in text for cid in unique):
            text += "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in unique)
    return text
