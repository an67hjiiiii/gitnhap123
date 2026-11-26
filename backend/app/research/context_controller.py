from __future__ import annotations

from app.core.types import SourceChunk
from app.retrieval.text import select_budgeted_chunks


class ContextController:
    def __init__(self, max_chars: int = 5000):
        self.max_chars = max_chars

    def select(self, candidates: list[SourceChunk], *, query: str | None = None) -> tuple[list[SourceChunk], list[dict]]:
        ordered = sorted(candidates, key=lambda c: (-c.score, c.chunk_id))
        return select_budgeted_chunks(
            ordered,
            cost_fn=len,
            budget=self.max_chars,
            query=query,
            truncate_first=False,
            budget_reason="token_budget_proxy",
        )
