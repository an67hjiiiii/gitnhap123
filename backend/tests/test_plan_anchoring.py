"""Neo nghĩa vụ: chỉ chép nguyên văn vào nhiệm vụ phù hợp, kế hoạch vẫn phải qua bộ kiểm tra (bộ 11 Agent thật)."""
from app.core.types import Concern, Obligation, Task, TaskPlan
from app.research.plan_anchoring import anchor_and_verify
from app.research.plan_verification import verify_task_plan

OB = Obligation("O1", "Analyze and design a payment order creation flow that prevents double payment")


def plan(*tasks, concerns=()):
    return TaskPlan(request="r", obligations=[OB], concerns=list(concerns), tasks=list(tasks))


def test_paraphrased_claim_is_anchored_verbatim_and_passes():
    p = plan(Task("t1", "Design idempotent payment API endpoints", "software", [], ["API spec"], ["O1"], []))
    assert not verify_task_plan(p).valid
    anchored, v, changes = anchor_and_verify(p)
    assert v.valid and changes == [{"task_id": "t1", "kind": "Nghĩa vụ", "id": "O1"}]
    assert OB.description in anchored.tasks[0].goal and anchored.tasks[0].goal.startswith("Design idempotent")
    assert p.tasks[0].goal == "Design idempotent payment API endpoints"  # kế hoạch gốc không bị sửa


def test_task_count_domains_and_dependencies_unchanged():
    p = plan(Task("t1", "Design payment API", "software", [], ["x"], ["O1"], []),
             Task("t2", "Review budget impact", "finance", ["t1"], ["y"], [], []))
    anchored, _, _ = anchor_and_verify(p)
    assert [(t.task_id, t.domain, t.depends_on) for t in anchored.tasks] == [("t1", "software", []), ("t2", "finance", ["t1"])]


def test_concern_goes_to_its_canonical_domain():
    c = Concern("C1", "Employee annual leave and payroll rules must be verified", "hr")
    p = plan(Task("t1", "Analyze and design a payment order creation flow that prevents double payment", "software", [], ["x"], ["O1"], ["C1"]),
             Task("t2", "Review HR leave policy", "hr", [], ["y"], [], []), concerns=[c])
    anchored, v, _ = anchor_and_verify(p)
    assert v.valid and "annual leave" in anchored.tasks[1].goal and "C1" not in (anchored.tasks[0].covers_concerns or [])


def test_valid_plan_is_left_alone():
    p = plan(Task("t1", "Analyze and design a payment order creation flow that prevents double payment", "software", [], ["x"], ["O1"], []))
    anchored, v, changes = anchor_and_verify(p)
    assert v.valid and changes == [] and anchored.tasks[0].goal == p.tasks[0].goal


def test_claim_in_wrong_domain_is_routed_to_the_domain_the_verifier_requires():
    ob = Obligation("O1", "Design a secure and trustworthy webhook mechanism for merchants, including signature, response, logging, and attack prevention")
    p = TaskPlan(request="r", obligations=[ob], concerns=[], tasks=[
        Task("T1", "Design a secure webhook mechanism for merchants with signature verification, response handling, logging, and attack prevention",
             "hr", [], ["x"], ["O1"], [])])
    assert not verify_task_plan(p).valid
    anchored, v, changes = anchor_and_verify(p)
    assert v.valid and anchored.tasks[0].domain == "software"
    assert changes[0]["kind"] == "Định tuyến lại tác tử"
