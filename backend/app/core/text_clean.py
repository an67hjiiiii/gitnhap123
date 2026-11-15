"""Small output cleanups shared by answer paths."""
from __future__ import annotations

import re

_SOURCE_NAME_TAG = re.compile(r"</?\s*source[ _]?name\s*>", re.IGNORECASE)
_DUP_FILE_NAME = re.compile(
    r"(\b[\w\-]+\.(?:txt|md|pdf|docx|json|csv))(?:[ \t]*[.,]?[ \t]*)\1(?![\w])", re.IGNORECASE)
_CHUNK_ID_TAG = re.compile(r"[ 	]*<(src_[A-Za-z0-9_]+)>")


def strip_placeholder_tags(text: str) -> str:
    """Remove prompt-placeholder tags a small model sometimes echoes (<source name>x</source name> -> x)."""
    if not text:
        return text
    cleaned = _DUP_FILE_NAME.sub(r"\1", _CHUNK_ID_TAG.sub("", _SOURCE_NAME_TAG.sub("", text)))
    return re.sub(r"[ \t]{2,}", " ", cleaned) if cleaned != text else text
