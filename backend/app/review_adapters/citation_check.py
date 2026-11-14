"""Pure citation integrity checks; numeric diagnostics do not assign verdicts."""

import unicodedata
from collections.abc import Iterable

from app.review_adapters.slot_check import Slot, _numbers, _quantity_keys


def excerpt_in_chunk(excerpt: str, chunk_text: str) -> bool:
    def normalized(text: str) -> str:
        return " ".join(unicodedata.normalize("NFC", text).split())

    return normalized(excerpt) in normalized(chunk_text)


def numbers_in_answer_supported(answer: str, evidence_texts: Iterable[str]) -> tuple[Slot, ...]:
    """Return distinct answer quantities lacking support in any single excerpt."""
    supported = {key for text in evidence_texts for slot in _numbers(text)
                 for key in _quantity_keys(slot)}
    return tuple(dict.fromkeys(slot for slot in _numbers(answer)
                               if not _quantity_keys(slot) & supported))


def citations_in_retrieved(citations: Iterable[str], retrieved_ids: Iterable[str]) -> list[str]:
    allowed = set(retrieved_ids)
    return list(dict.fromkeys(citation for citation in citations if citation not in allowed))
