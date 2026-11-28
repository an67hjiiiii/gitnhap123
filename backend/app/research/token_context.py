"""Chọn evidence theo ngân sách token Qwen3 thật và chia ngân sách thích ứng giữa các task (R2 của C1SE.27).

Bật bằng CONTEXT_POLICY=adaptive_qwen. Mặc định (char_proxy) pipeline giữ nguyên ContextController cũ.
"""
from __future__ import annotations

import hashlib
import os

from app.core.types import SourceChunk
from app.research.adaptive_budget import allocate_task_budgets
from app.research.token_budget import count_qwen_tokens

POLICIES = {"char_proxy", "adaptive_qwen"}


def context_policy() -> str:
    policy = os.getenv("CONTEXT_POLICY", "char_proxy").strip().lower()
    if policy not in POLICIES:
        raise ValueError(f"Unsupported CONTEXT_POLICY={policy}")
    return policy


class TokenContextController:
    """Cùng giao diện ContextController.select(); trần tính bằng token thật, không cắt giữa chunk."""

    def __init__(self, max_tokens: int):
        self.max_tokens = max(0, int(max_tokens))

    def select(self, candidates: list[SourceChunk], *, query: str | None = None) -> tuple[list[SourceChunk], list[dict]]:
        from app.retrieval.text import select_budgeted_chunks

        ordered = sorted(candidates, key=lambda c: (-c.score, c.chunk_id))
        return select_budgeted_chunks(
            ordered,
            cost_fn=count_qwen_tokens,
            budget=self.max_tokens,
            query=query,
            truncate_first=False,
            budget_reason="qwen_token_budget",
        )


def plan_task_budgets(candidates_by_task: dict[str, list[SourceChunk]], total_tokens: int) -> dict:
    """Nhu cầu của mỗi task = tổng token các chunk ứng viên khác nhau; chia tổng ngân sách theo tỉ lệ nhu cầu."""
    needs: dict[str, int] = {}
    for task_id, chunks in candidates_by_task.items():
        unique = {hashlib.sha256(c.text.strip().encode()).hexdigest(): c.text for c in chunks}
        needs[task_id] = sum(count_qwen_tokens(text) for text in unique.values())
    zeros = {t: 0 for t in needs}
    limits = allocate_task_budgets(needs, zeros, dict(needs), int(total_tokens))
    return {"policy": "adaptive_qwen", "total_tokens": int(total_tokens), "needs": needs, "limits": limits}
