"""Confirmed legal-instrument edges shared by diffing and retrieval policy."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date


def relations_enabled() -> bool:
    return os.getenv("VERSION_RELATIONS", "0").strip().lower() in {"1", "on"}


def normalized_doc_number(value: str | None) -> str:
    text = unicodedata.normalize("NFC", value or "").upper()
    text = re.sub(r"\s+", "", text).translate(str.maketrans({"–": "-", "—": "-", "‑": "-"}))
    text = text.strip(".,;:").replace("BGDDT", "BGDĐT")
    match = re.fullmatch(r"(\d{1,3})/(\d{4})/([A-ZĐ]+(?:-[A-ZĐ0-9]+)+)", text)
    if not match:
        return ""
    return f"{int(match[1]):02d}/{match[2]}/{match[3]}"


@dataclass(frozen=True)
class VersionEdge:
    new_source_id: str
    old_source_id: str
    kind: str
    family_key: str


def relation_edges(versions) -> list[VersionEdge]:
    """Resolve only confirmed, issued endpoints within one owner/space.

    A component uses its oldest root document number as a stable chain key.
    Cyclic or multi-root metadata still receives a deterministic key.
    """
    nodes = {v["source_id"]: v for v in versions
             if v.get("confirmed_at") is not None and v.get("status") == "issued"
             and normalized_doc_number(v.get("doc_number"))}
    numbers = {}
    for sid, v in nodes.items():
        scope = (v.get("owner_user_id"), v.get("space_id"))
        numbers.setdefault((*scope, normalized_doc_number(v["doc_number"])), []).append(sid)
    raw = set()
    neighbors = {sid: set() for sid in nodes}
    outgoing = set()
    for sid, v in nodes.items():
        for relation in v.get("relations") or []:
            if not isinstance(relation, dict) or relation.get("type") not in {"replaces", "amends"}:
                continue
            key = (v.get("owner_user_id"), v.get("space_id"),
                   normalized_doc_number(relation.get("target_doc_number")))
            for target in numbers.get(key, []):
                label = relation.get("target_version_label")
                if target == sid or label and label != nodes[target].get("version_label"):
                    continue
                raw.add((sid, target, relation["type"]))
                outgoing.add(sid)
                neighbors[sid].add(target)
                neighbors[target].add(sid)
    families = {}
    for sid in sorted(nodes):
        if sid in families:
            continue
        component, pending = set(), [sid]
        while pending:
            current = pending.pop()
            if current not in component:
                component.add(current)
                pending.extend(neighbors[current] - component)
        roots = component - outgoing or component
        root = min(roots, key=lambda key: (
            nodes[key].get("issued_on") or nodes[key].get("effective_from") or date.max,
            normalized_doc_number(nodes[key]["doc_number"]), key))
        families.update(dict.fromkeys(component, normalized_doc_number(nodes[root]["doc_number"])))
    return [VersionEdge(new, old, kind, families[new]) for new, old, kind in sorted(raw)]


def relation_current_ids(visible_ids: set[str], versions, *, today: date) -> set[str]:
    """A live replacement retires its target and amendments depending on it."""
    nodes = {v["source_id"]: v for v in versions if v["source_id"] in visible_ids}
    edges = relation_edges(nodes.values())
    amendments = {}
    for edge in edges:
        if edge.kind == "amends":
            amendments.setdefault(edge.old_source_id, set()).add(edge.new_source_id)
    retired = set()
    for edge in edges:
        effective = nodes[edge.new_source_id].get("effective_from")
        if edge.kind != "replaces" or effective is None or effective > today:
            continue
        pending, visited = [edge.old_source_id], set()
        while pending:
            sid = pending.pop()
            if sid in visited or sid == edge.new_source_id:
                continue
            visited.add(sid)
            retired.add(sid)
            pending.extend(amendments.get(sid, ()))
    return set(visible_ids) - retired
