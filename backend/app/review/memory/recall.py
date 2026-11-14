"""Read-only suggestions from prior human decisions."""

from __future__ import annotations

from dataclasses import dataclass

from .store import MemoryStore, normalize_requirement


@dataclass(frozen=True)
class Suggestion:
    entry_id: str
    similarity: float
    prior_verdict: str
    prior_decision: str
    edited_text: str | None
    note: str


def _jaccard(left: str, right: str) -> float:
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def recall(
    store: MemoryStore,
    owner_user_id: str,
    project_key: str,
    requirement_text: str,
    k: int = 3,
    threshold: float = 0.5,
) -> list[Suggestion]:
    """Return similar prior decisions as suggestions; never mutates review data."""
    if k <= 0:
        return []
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    normalized = normalize_requirement(requirement_text)
    ranked = []
    for entry in store.list_entries(owner_user_id, project_key):
        similarity = _jaccard(normalized, entry.normalized_key)
        if similarity < threshold:
            continue
        ranked.append((entry, similarity))
    ranked.sort(key=lambda pair: (-pair[1], pair[0].created_at, pair[0].id))
    suggestions = []
    for entry, similarity in ranked[:k]:
        if entry.decision == "REJECT":
            note = "A reviewer rejected a similar requirement; treat this as a cautionary signal."
        elif entry.decision == "EDIT":
            note = "A reviewer edited a similar requirement; consider the prior wording."
        else:
            note = "A reviewer accepted a similar requirement; use this only as a suggestion."
        suggestions.append(
            Suggestion(
                entry_id=entry.id,
                similarity=similarity,
                prior_verdict=entry.verdict,
                prior_decision=entry.decision.value,
                edited_text=entry.edited_text,
                note=note,
            )
        )
    return suggestions
