from __future__ import annotations

import re

from app.core.types import RunMetrics, TaskResult


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
        "SYNTHESIZER. Tổng hợp kết quả bằng tiếng Việt tự nhiên, không thêm sự kiện hay bằng chứng mới. "
        "Mỗi câu trả lời thành một đoạn ngắn theo đúng thứ tự TASK RESULTS; cuối cùng thêm một câu kết luận chung. "
        "Tối đa 4 câu, khoảng 100 từ khi đủ trình bày các phần; chỉ dài hơn khi cần liệt kê đủ các phần theo yêu cầu. "
        "Giữ nguyên citation ID đã được xác thực và dòng 'Nguồn: [chunk_id]' nếu có. "
        "Dẫn nguồn trong câu bằng 'theo tài liệu <source name>', giữ tên nguồn từ câu trả lời; "
        "nếu chỉ có ID thì dùng ID, không tự đặt tên. Không chép nguyên bằng chứng. "
        "Với PARTIAL/NO_EVIDENCE, nói rõ phần chưa tìm thấy và đề xuất đúng một bước tiếp theo cụ thể để bổ sung thông tin thiếu. "
        "Giữ nguyên tên kỹ thuật, mã và giá trị.\n"
        "Ví dụ 1 — T1 đã xác nhận thời hạn khóa trong API.md [c1]:\n"
        "Khóa được giữ 24 giờ, theo tài liệu API.md [c1].\n\n"
        "Như vậy, thời hạn khóa là 24 giờ.\n"
        "Ví dụ 2 — T1 xác nhận thời hạn khóa, T2 chưa tìm thấy giới hạn tải tệp:\n"
        "Khóa được giữ 24 giờ, theo tài liệu API.md [c1].\n\n"
        "Mình chưa tìm thấy giới hạn tải tệp. Bạn hãy tải lên tài liệu quy định dung lượng tệp.\n\n"
        "Như vậy, đã xác nhận thời hạn khóa nhưng còn thiếu giới hạn tải tệp."
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
