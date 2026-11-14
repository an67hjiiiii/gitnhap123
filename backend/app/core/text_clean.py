"""Small output cleanups shared by answer paths."""
from __future__ import annotations

import re

_SOURCE_NAME_TAG = re.compile(r"</?\s*source[ _]?name\s*>", re.IGNORECASE)


def strip_placeholder_tags(text: str) -> str:
    """Remove prompt-placeholder tags a small model sometimes echoes (<source name>x</source name> -> x)."""
    if not text:
        return text
    cleaned = _SOURCE_NAME_TAG.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned) if cleaned != text else text
