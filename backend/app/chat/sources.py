"""Turn raw chunk ids in an answer into numbered sources: body uses [n], the response carries `sources`."""
from __future__ import annotations

import re

_CHUNK_ID = r"src_[A-Za-z0-9]+_c\d+"
_FOOTER_LINE = re.compile(r"(?im)^[ \t]*Ngu[ồo]n[ \t]*:.*$")
_WRAPPED = re.compile(rf"[\[<(]\s*({_CHUNK_ID})\s*[\]>)]")
_BARE = re.compile(rf"(?<![\w\[<(])({_CHUNK_ID})(?![\w\]>)])")
_SNIPPET_CHARS = 200


def _snippet(text: str) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= _SNIPPET_CHARS else flat[:_SNIPPET_CHARS].rstrip() + "…"


def number_sources(answer: str, lookup, extra_ids=()) -> tuple[str, list[dict]]:
    """Return (answer with [n] markers and no raw ids/'Nguồn:' footer, sources).

    `lookup(chunk_id)` returns a chunk dict (source_name, text, provenance) or None. Ids found in the body come
    first (order of appearance), then `extra_ids` (cited by tasks but not mentioned inline).
    """
    text = answer or ""
    ids: list[str] = []
    for match in re.finditer(_CHUNK_ID, text):
        if match.group(0) not in ids:
            ids.append(match.group(0))
    for cid in extra_ids:
        if cid and cid not in ids:
            ids.append(cid)
    if not ids:
        return text, []
    numbers: dict[str, int] = {}
    sources: list[dict] = []
    for cid in ids:
        chunk = None
        try:
            chunk = lookup(cid)
        except Exception:
            chunk = None
        if not chunk:
            continue  # unknown id: never show a raw id to the user
        numbers[cid] = len(sources) + 1
        provenance = chunk.get("provenance") or {}
        sources.append({
            "n": numbers[cid], "doc_name": chunk.get("source_name") or "", "chunk_id": cid,
            "section": provenance.get("section_path") or "", "snippet": _snippet(chunk.get("text", "")),
        })
    body = _FOOTER_LINE.sub("", text)
    body = _WRAPPED.sub(lambda m: f"[{numbers[m.group(1)]}]" if m.group(1) in numbers else "", body)
    body = _BARE.sub(lambda m: f"[{numbers[m.group(1)]}]" if m.group(1) in numbers else "", body)
    body = re.sub(r"\[(\d+)\](?:\s*\[\1\])+", r"[\1]", body)  # same source twice in a row
    body = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", body)).strip()
    return body, sources
