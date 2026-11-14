"""Cross-language question handling for chat (one small model call only when languages differ)."""
from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable

from app.retrieval.multilingual import detect_language

_NAMES = {"vi": "Vietnamese", "en": "English"}


def text_language(text: str) -> str:
    """'vi' or 'en'; same rule the pipeline uses for the reply language."""
    has_marks = any(unicodedata.combining(ch) for ch in unicodedata.normalize("NFD", text)) or "đ" in text.lower()
    return "vi" if has_marks or detect_language(text) != "en" else "en"


def document_language(chunk_texts: Iterable[str], *, sample: int = 30, majority: float = 0.6) -> str | None:
    votes = Counter(text_language(t) for t in list(chunk_texts)[:sample] if t and t.strip())
    total = sum(votes.values())
    if not total:
        return None
    lang, count = votes.most_common(1)[0]
    return lang if count / total >= majority else None


async def translate_query(provider, query: str, target: str) -> str:
    """One generate call: standalone translation of the question. Returns the original on any problem."""
    name = _NAMES.get(target)
    if not name:
        return query
    try:
        result = await provider.generate(
            system=(f"You translate search questions into {name}. Output ONLY the translated question, "
                    "one line, no quotes, no explanation. Keep names, numbers, units and technical terms."),
            user=query,
        )
    except Exception:
        return query
    text = " ".join(str(getattr(result, "text", "") or "").split()).strip(" \"'“”")
    if not text or len(text) > 3 * len(query) + 120:
        return query
    return text
