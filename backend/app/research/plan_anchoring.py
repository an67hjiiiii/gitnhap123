"""Neo nghĩa vụ vào nhiệm vụ: bước sửa tất định sau khi lần sửa bằng mô hình vẫn bị bộ kiểm tra kế hoạch từ chối.

Bộ kiểm tra (`plan_verification.verify_task_plan`) đòi mục tiêu nhiệm vụ giữ lại câu chữ của từng nghĩa vụ/mối quan
tâm. Mô hình nhỏ hay diễn đạt lại nên kế hoạch đúng ý vẫn bị từ chối. Bước này chỉ CHÉP NGUYÊN VĂN nghĩa vụ vào mục tiêu
của nhiệm vụ đã nhận nó (hoặc nhiệm vụ cùng mảng khi chưa nhiệm vụ nào nhận); không thêm, bớt hay diễn giải yêu cầu,
không đổi số nhiệm vụ, mảng hay phụ thuộc. Kết quả vẫn phải qua đúng bộ kiểm tra cũ; không qua thì vẫn từ chối.
"""

from __future__ import annotations

from dataclasses import replace

from app.core.types import TaskPlan
from app.research.decomposer import detect_domains
from app.research.plan_verification import (
    PlanVerification,
    _concern_text_for_coverage,
    _meaningful_evidence_needs,
    _requests_supporting_evidence,
    _retains_text,
    _source_text,
    _task_text,
    verify_task_plan,
)

GENERAL = "general"


def _clean(text: str) -> str:
    # bộ kiểm tra tách mệnh đề theo ";" và ". ", nên bản chép phải nằm gọn trong một mệnh đề
    return " ".join(text.replace(";", ",").replace(". ", ", ").split()).rstrip(".")


def anchor_plan(plan: TaskPlan) -> tuple[TaskPlan, list[dict]]:
    """Trả về kế hoạch đã neo và danh sách thay đổi (để ghi sự kiện); không sửa kế hoạch gốc."""
    tasks = [replace(t, covers_obligations=list(t.covers_obligations) if t.covers_obligations is not None else None,
                     covers_concerns=list(t.covers_concerns) if t.covers_concerns is not None else None) for t in plan.tasks]
    changes: list[dict] = []

    def pick(item_id: str, field: str, domain: str | None):
        claimed = [t for t in tasks if item_id in (getattr(t, field) or [])]
        same_domain = [t for t in tasks if domain and t.domain == domain]
        if domain:
            return next((t for t in claimed if t.domain == domain), None) or (same_domain[0] if same_domain else None)
        return claimed[0] if claimed else (tasks[0] if tasks else None)

    def attach(task, field: str, item_id: str, text: str, kind: str) -> None:
        idx = tasks.index(task)
        goal = task.goal if _retains_text(_task_text(task), text) else f"{task.goal.rstrip(' .;')}; {kind}: {_clean(text)}"
        ids = getattr(task, field)
        ids = (ids or []) if ids is not None else None
        if ids is not None and item_id not in ids:
            ids = [*ids, item_id]
        tasks[idx] = replace(task, goal=goal, **({field: ids} if ids is not None else {}))
        if goal != task.goal or ids != getattr(task, field):
            changes.append({"task_id": task.task_id, "kind": kind, "id": item_id})

    for ob in plan.obligations:
        text = _source_text(ob)
        domains = detect_domains(ob.description)
        domain = domains[0] if len(domains) == 1 else None
        holders = [t for t in tasks if ob.obligation_id in (t.covers_obligations or [])]
        if holders and all(_retains_text(_task_text(t), text) and (not domain or t.domain == domain) for t in holders):
            continue
        if not ob.required and not holders:
            continue
        if domain and holders and not any(t.domain == domain for t in holders):
            right = next((t for t in tasks if t.domain == domain), None)
            if right is None:
                # chưa có nhiệm vụ nào thuộc mảng mà luật định tuyến của bộ kiểm tra yêu cầu: chuyển nhiệm vụ đang nhận sang tác tử đó
                h = holders[0]
                tasks[tasks.index(h)] = replace(h, domain=domain)
                changes.append({"task_id": h.task_id, "kind": "Định tuyến lại tác tử", "id": ob.obligation_id, "from": h.domain, "to": domain})
            # bỏ mã nghĩa vụ khỏi nhiệm vụ sai mảng; nhiệm vụ đúng mảng sẽ nhận bên dưới
            for t in holders:
                cur = next(x for x in tasks if x.task_id == t.task_id)
                if cur.domain != domain:
                    tasks[tasks.index(cur)] = replace(cur, covers_obligations=[i for i in (cur.covers_obligations or []) if i != ob.obligation_id])
            holders = [t for t in tasks if ob.obligation_id in (t.covers_obligations or [])]
        # nhiệm vụ đã nhận mà chưa giữ chữ: neo vào chính nhiệm vụ đó (nếu đúng mảng)
        for t in holders:
            if not domain or t.domain == domain:
                attach(t, "covers_obligations", ob.obligation_id, text, "Nghĩa vụ")
        if not holders:
            target = pick(ob.obligation_id, "covers_obligations", domain)
            if target is not None:
                attach(target, "covers_obligations", ob.obligation_id, text, "Nghĩa vụ")

    for concern in plan.concerns:
        text = _concern_text_for_coverage(concern)
        domain = None if concern.domain == GENERAL else concern.domain
        holders = [t for t in tasks if concern.concern_id in (t.covers_concerns or [])]
        good = [t for t in holders if (not domain or t.domain == domain) and _retains_text(_task_text(t), text)]
        if good and len(good) == len(holders):
            continue
        targets = [t for t in holders if not domain or t.domain == domain] or [x for x in [pick(concern.concern_id, "covers_concerns", domain)] if x]
        for t in targets:
            attach(t, "covers_concerns", concern.concern_id, text, "Mối quan tâm")
        # nhiệm vụ nhận mối quan tâm nhưng sai mảng: bỏ mã khỏi danh sách nhận (không đổi mục tiêu)
        for t in holders:
            if domain and t.domain != domain:
                idx = tasks.index(next(x for x in tasks if x.task_id == t.task_id))
                cur = tasks[idx]
                tasks[idx] = replace(cur, covers_concerns=[c for c in (cur.covers_concerns or []) if c != concern.concern_id])
                changes.append({"task_id": t.task_id, "kind": "Bỏ mối quan tâm sai mảng", "id": concern.concern_id})

    # Chỉ bổ sung evidence_needs khi yêu cầu có đòi hỏi bằng chứng hoặc danh sách đang rỗng (không đụng kế hoạch đã hợp lệ)
    if _requests_supporting_evidence(plan):
        for idx, cur in enumerate(tasks):
            if not _meaningful_evidence_needs(cur.evidence_needs):
                phrase = _clean(cur.goal)[:120]
                if phrase:
                    tasks[idx] = replace(cur, evidence_needs=[phrase])
                    changes.append({"task_id": cur.task_id, "kind": "Bổ sung cụm tìm kiếm", "id": cur.task_id})

    return replace(plan, tasks=tasks), changes


def anchor_and_verify(plan: TaskPlan) -> tuple[TaskPlan, PlanVerification, list[dict]]:
    anchored, changes = anchor_plan(plan)
    return anchored, verify_task_plan(anchored), changes
