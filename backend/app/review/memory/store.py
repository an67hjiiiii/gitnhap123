"""Owner-scoped, in-memory storage for human review decisions."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import uuid4

from app.review.schemas import Decision, Finding, Requirement


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    owner_user_id: str
    project_key: str
    requirement_text: str
    normalized_key: str
    verdict: str
    decision: Decision
    edited_text: str | None
    evidence_refs: list[str]
    created_at: datetime


class MemoryStore(Protocol):
    def record_from_finding(
        self,
        owner_user_id: str,
        project_key: str,
        requirement: Requirement | str,
        finding: Finding,
    ) -> MemoryEntry | None: ...

    def list_entries(
        self, owner_user_id: str, project_key: str | None = None
    ) -> list[MemoryEntry]: ...

    def delete(self, owner_user_id: str, entry_id: str) -> bool: ...


# Common English and Vietnamese function words carry little signal for a
# requirement-level lexical similarity measure.
_STOPWORDS = frozenset((
    "a an the and or but if then of to in on at by for from with as is are be "
    "must should shall can may do does have has that this these those it its "
    "requirement requirements check ensure verify user system "
    "va và vào cuả của cho là là duoc được bị bị trong tren trên duoi dưới "
    "voi với mot một cac các nhung những nay này do de để khi neu nếu thi thì "
    "can cần phai phải khong không toi tối thieu thiểu ve về"
).split())


def normalize_requirement(text: str) -> str:
    """Return folded, stopword-free tokens in their original order."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", folded)
    return " ".join(token for token in tokens if token not in _STOPWORDS)


class InMemoryMemoryStore:
    def __init__(
        self,
        max_entries_per_project: int = 500,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        if max_entries_per_project < 1:
            raise ValueError("max_entries_per_project must be at least 1")
        self.max_entries_per_project = max_entries_per_project
        self._clock = clock
        self._id_factory = id_factory
        self._entries: dict[str, MemoryEntry] = {}

    def record_from_finding(
        self,
        owner_user_id: str,
        project_key: str,
        requirement: Requirement | str,
        finding: Finding,
    ) -> MemoryEntry | None:
        decision = Decision(finding.review)
        if decision == Decision.NONE:
            return None
        if isinstance(requirement, Requirement):
            requirement_text = requirement.text
        else:
            requirement_text = requirement
        entry = MemoryEntry(
            id=self._id_factory(),
            owner_user_id=owner_user_id,
            project_key=project_key,
            requirement_text=requirement_text,
            normalized_key=normalize_requirement(requirement_text),
            verdict=str(finding.verdict.value if hasattr(finding.verdict, "value") else finding.verdict),
            decision=decision,
            edited_text=finding.edited_text if decision == Decision.EDIT else None,
            evidence_refs=[evidence.evidence_id for evidence in finding.evidence],
            created_at=self._clock(),
        )
        self._entries[entry.id] = entry
        scoped = sorted(
            (
                item
                for item in self._entries.values()
                if item.owner_user_id == owner_user_id and item.project_key == project_key
            ),
            key=lambda item: (item.created_at, item.id),
        )
        for evicted in scoped[: max(0, len(scoped) - self.max_entries_per_project)]:
            del self._entries[evicted.id]
        return entry

    def list_entries(
        self, owner_user_id: str, project_key: str | None = None
    ) -> list[MemoryEntry]:
        return sorted(
            (
                item
                for item in self._entries.values()
                if item.owner_user_id == owner_user_id
                and (project_key is None or item.project_key == project_key)
            ),
            key=lambda item: (item.created_at, item.id),
        )

    def delete(self, owner_user_id: str, entry_id: str) -> bool:
        entry = self._entries.get(entry_id)
        if entry is None or entry.owner_user_id != owner_user_id:
            return False
        del self._entries[entry_id]
        return True
