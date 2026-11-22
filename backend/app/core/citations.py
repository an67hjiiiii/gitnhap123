from __future__ import annotations
import re
from app.core.types import SourceChunk


def validate_citations(citation_ids: list[str], available: list[SourceChunk]) -> tuple[list[str], list[str]]:
    allowed = {c.chunk_id for c in available}
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for cid in citation_ids:
        cid = str(cid).strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        if cid in allowed:
            valid.append(cid)
        else:
            invalid.append(cid)
    return valid, invalid


_BRACKETED = re.compile(r"\[([^\[\]\n]+)\]")
_CHUNK_ID = re.compile(r"src_[0-9a-f]{16}_c\d{4,}")


def strip_unauthorized_citations(text: str, allowed: set[str], known: set[str]) -> str:
    """Filter recognized locators only; preserve unrelated bracketed text."""
    def replace(match):
        original = match.group(1)
        content = _CHUNK_ID.sub(lambda found: found.group(0) if found.group(0) in allowed else "", original)
        if content != original:
            content = content.strip(" ,;")
            return "[" + content + "]" if content else ""
        parts = [part.strip() for part in content.split(",")]
        if not any(_CHUNK_ID.fullmatch(cid) or cid in known for cid in parts):
            return match.group(0)
        kept = [cid for cid in parts if cid in allowed or not (_CHUNK_ID.fullmatch(cid) or cid in known)]
        return "[" + ", ".join(kept) + "]" if kept else ""
    return _BRACKETED.sub(replace, text)
