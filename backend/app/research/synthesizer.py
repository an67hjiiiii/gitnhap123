from __future__ import annotations
import re
from app.core.answer_checks import IMG_MARK, apply_calc, clean, finish, numbers
from app.core.structured_output import parse_answer_json
from app.core.types import TaskResult, RunMetrics
from app.research.progress import answer_streamer

_EN_META_LEAK = re.compile(
    r"^\s*(?:the user asked|based on the task results|the task results show|the response should be in vietnamese|"
    r"here is the synthesized|in summary,\s+the user)",
    re.I,
)

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
                     evidence_text: str | None = None, revision_note: str | None = None) -> str:
    compact = []
    all_citations: list[str] = []
    for r in results:
        all_citations.extend(r.citations)
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
    user = f"USER REQUEST:\n{query}\n\nTASK RESULTS:\n" + "\n\n".join(compact)
    if revision_note:  # Reviewer trả bài (chỉ ô chat sản phẩm)
        user += "\n\n" + revision_note
    if any(r.source != "documents" for r in results):
        user += ("\n\nKNOWLEDGE SOURCES: tasks marked source=general (and the 'Kiến thức chung:' part of source=both) come from general knowledge, "
                 "not from the user's documents. You MAY use that content (it is not invented by you), but keep it in a clearly labelled part "
                 "(a '### Kiến thức chung' heading, or '### General knowledge' in English), never attach document citations to it, "
                 "and keep document-based parts with their citations.")
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
            "Keep simple answers short. Never mention internal task IDs (T1, T2) or '[TASK]' or the word 'task' to the user. "
            "CRITICAL COMPLETENESS: you MUST cover EVERY SINGLE part/pillar (e.g. (1), (2), (3), (4)) asked in USER REQUEST by integrating ALL task results — NEVER copy or summarize only one task while dropping the other tasks! "
            "If the user asks for a table, you MUST answer with a filled Markdown table. Copy every number, year and rate verbatim from the task results. "
            "Do NOT invent sub-allocations or split numbers that are not in the task results (e.g. if evidence only states 75% combined for two channels, report the combined 75% = [[= total*0.75 ]] without inventing per-channel splits). "
            "Never substitute one allowance/benefit/metric for a different one that was not in the documents (if an asked item is absent, state clearly it is not in the documents). "
            "Never do arithmetic yourself: write each calculation as [[= expression ]] keeping literal % signs (e.g. 0.5% * 10 * 240000000, 120% * 15 * 950000, 12 * 2800000 * (1 - 15%); use // for \"every full N\" rules, e.g. 12 + 8//4; divide excess by step size for \"per 0.5 kg\" rules); "
            "when converting monthly salary to hourly pay, divide by BOTH working days per month AND working hours per day stated in the evidence (e.g. monthly/22/8); "
            "the system replaces it with the result. Write directly for the user, never narrate 'The user asked...' or 'The task results show...'."
            + ' Return JSON {"answer": "<the final answer for the user as Markdown prose>"}.',
            user=user,
            response_schema=SYNTH_SCHEMA,
            max_output_tokens=max_output_tokens,
            **answer_streamer(provider),
        )
        metrics.add_usage(result.usage)
        text = str(parse_answer_json(result.text).get("answer") or "").strip() or result.text.strip()
        if reply_language == "vi" and _EN_META_LEAK.search(text):
            # Hậu kiểm 25/11: qwen3:4b đôi khi xuất tường thuật nội bộ tiếng Anh ("The user asked...") ở bước tổng hợp → sinh lại trực tiếp bằng tiếng Việt
            repair = await structured(
                system=(
                    "Viết lại câu trả lời trực tiếp cho người dùng HOÀN TOÀN bằng tiếng Việt (Markdown). "
                    "Không tường thuật lại 'The user asked...' hay 'The task results show...'. Giữ đúng số liệu và trích dẫn hiện có. "
                    'Trả về JSON {"answer": "..."}.'
                ),
                user=f"YÊU CẦU NGƯỜI DÙNG:\n{query}\n\nBẢN NHÁP CẦN VIẾT LẠI BẰNG TIẾNG VIỆT:\n{text}",
                response_schema=SYNTH_SCHEMA,
                max_output_tokens=max_output_tokens,
            )
            metrics.add_usage(repair.usage)
            fixed = str(parse_answer_json(repair.text).get("answer") or "").strip()
            if fixed and not _EN_META_LEAK.search(fixed):
                text = fixed
        if text.rstrip().endswith(":"):
            # Chống câu trả lời cụt đuôi ngay sau dấu ':' (vd. "Dưới đây là chi tiết theo tài liệu đã xác minh:" mà quên viết nội dung)
            details = [
                f"- {r.answer.strip()}"
                for r in results
                if str(r.answer or "").strip() and r.status != "NO_EVIDENCE"
            ]
            if details:
                text = text.rstrip() + "\n\n" + "\n".join(details)
        # V9: Multi-Task Completeness Guard — chống recency bias trên mô hình nhỏ (4B) khi tổng hợp >= 3 tác tử
        # mà câu trả lời cuối bỏ sót phần lớn kết quả của các tác tử đầu (chỉ tóm tắt 1 task cuối hoặc rò "[TASK]").
        valid_results = [r for r in results if str(r.answer or "").strip() and r.status != "NO_EVIDENCE"]
        if len(valid_results) >= 3:
            text_nums = numbers(text)
            text_words = set(re.findall(r"[a-zà-ỹđ0-9]{3,}", text.casefold()))
            dropped_tasks: list[tuple[int, TaskResult]] = []
            for idx, r in enumerate(valid_results, 1):
                r_nums = {n for n in numbers(r.answer) if len(n.replace(".", "")) >= 2}
                r_words = set(re.findall(r"[a-zà-ỹđ0-9]{4,}", r.answer.casefold()))
                num_cov = (len(r_nums & text_nums) / len(r_nums)) if r_nums else 1.0
                word_cov = (len(r_words & text_words) / max(1, len(r_words))) if r_words else 1.0
                if (r_nums and num_cov < 0.25) or word_cov < 0.18:
                    dropped_tasks.append((idx, r))
            if re.search(r"^\s*Đối với\s+\[TASK\]", text, re.I) or len(dropped_tasks) >= max(2, len(valid_results) // 2):
                domain_titles = {
                    "finance": "Tài chính & Ngân sách",
                    "software": "Hạ tầng CNTT, Kiến trúc & SLA",
                    "hr": "Nhân sự, Chế độ & Đào tạo",
                    "marketing": "Marketing & Tăng trưởng",
                    "business": "Kinh doanh & Chiến lược",
                    "education": "Đào tạo & Năng lực",
                    "analyst": "Phân tích & Đối chiếu Số liệu",
                    "general": "Tổng hợp & Khuyến nghị",
                }
                seen_domains: dict[str, int] = {}
                sections: list[str] = []
                for idx, r in enumerate(valid_results, 1):
                    base_title = domain_titles.get(r.domain, f"Nội dung {idx}")
                    seen_domains[base_title] = seen_domains.get(base_title, 0) + 1
                    title = base_title if seen_domains[base_title] == 1 else f"{base_title} (tiếp)"
                    body_clean = clean(r.answer.strip())
                    sections.append(f"### {idx}. {title}\n\n{body_clean}")
                text = "\n\n".join(sections)
    else:
        result = await provider.generate(system=system, user=user)
        metrics.add_usage(result.usage)
        text = result.text.strip()
    if max_output_tokens is not None:  # ô chat sản phẩm: dọn rác, cảnh báo số không có trong nguồn, máy tính thay phép tính
        worker_computed: set[str] = set()
        for r in results:
            worker_computed.update(getattr(r, "computed_numbers", None) or ())
        text = finish(text, evidence_text + "\n" + query, extra_known=worker_computed)[0] if evidence_text else apply_calc(clean(text))
    unique = list(dict.fromkeys(all_citations))
    # The worker citations are already validated; append them if the synthesis model dropped locators.
    if unique and not any(cid in text for cid in unique):
        text += "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in unique)
    return text
