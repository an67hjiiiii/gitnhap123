"""Phân chia ngân sách evidence (token) theo từng task, độc lập với model.

Chuyển từ C1SE.27 (R2 adaptive budget). Hàm thuần, không gọi LLM.
"""
from __future__ import annotations

from fractions import Fraction


def allocate_task_budgets(needs, required, capacities, total, *, fixed=False):
    """Ba ánh xạ cùng task ID. Kết quả là trần token, không phải số token đã gửi."""
    if not needs or needs.keys() != required.keys() or needs.keys() != capacities.keys():
        raise ValueError("Danh sách nhiệm vụ không nhất quán.")
    if any(type(value) is not int or value < 0 for value in
           (total, *needs.values(), *required.values(), *capacities.values())):
        raise ValueError("Ngân sách phải là số nguyên không âm.")
    tasks = sorted(needs)
    if any(required[t] > min(needs[t], capacities[t]) for t in tasks):
        raise ValueError("Evidence bắt buộc vượt sức chứa của nhiệm vụ.")
    if fixed:
        share, remainder = divmod(total, len(tasks))
        limits = {t: min(capacities[t], share + int(i < remainder))
                  for i, t in enumerate(tasks)}
        if any(required[t] > limits[t] for t in tasks):
            raise ValueError("Evidence bắt buộc vượt ngân sách cố định.")
        return limits
    remaining = total - sum(required.values())
    if remaining < 0:
        raise ValueError("Tổng evidence bắt buộc vượt ngân sách.")
    demand = {t: min(needs[t], capacities[t]) - required[t] for t in tasks}
    denominator = sum(demand.values())
    if denominator <= remaining:
        return {t: required[t] + demand[t] for t in tasks}
    quotas = {t: Fraction(remaining * demand[t], denominator) for t in tasks}
    extras = {t: int(quotas[t]) for t in tasks}
    order = sorted(tasks, key=lambda t: (-(quotas[t] - extras[t]), t))
    for t in order[:remaining - sum(extras.values())]:
        extras[t] += 1
    return {t: required[t] + extras[t] for t in tasks}
