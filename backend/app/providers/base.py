from __future__ import annotations
from abc import ABC, abstractmethod
from app.core.types import ProviderResult, Usage


class OutputTruncatedError(Exception):
    """Generation reached its output cap; partial text is diagnostic only."""

    def __init__(self, partial_text: str, usage: Usage, output_limit: int,
                 done_reason: str | None = None):
        super().__init__(f"Provider output truncated at {output_limit} tokens")
        self.partial_text = partial_text
        self.usage = usage
        self.output_limit = output_limit
        self.done_reason = done_reason

class Provider(ABC):
    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    async def generate(self, *, system: str, user: str) -> ProviderResult:
        raise NotImplementedError
