from __future__ import annotations
from app.core.types import SourceChunk
from app.retrieval.text import make_chunks, retrieve, terms

from app.research.registry import _SOFTWARE_ANCHORS, _SOFTWARE_PATTERNS, active_pack, active_pack_name

# Tên cũ = bộ Phần mềm; mẫu của bộ đang dùng đọc qua active_pack().
DEFAULT_PATTERNS = _SOFTWARE_PATTERNS
PLANNING_ANCHORS = _SOFTWARE_ANCHORS
PLANNING_SCORER_VERSION = "planning-lexical-intent-v2"

class PlanningRetriever:
    def __init__(self, min_score: float = 0.0):
        self.min_score = max(0.0, float(min_score))
        self._chunks: dict[str, list[SourceChunk]] = {}

    @property
    def chunks(self) -> list[SourceChunk]:
        name = active_pack_name()
        if name not in self._chunks:
            self._chunks[name] = [c for pattern, text in active_pack()["patterns"]
                                  for c in make_chunks(pattern, text, max_chars=1000)]
        return self._chunks[name]

    def search(
        self,
        query: str,
        top_k: int = 3,
        *,
        min_score: float | None = None,
    ) -> list[SourceChunk]:
        """Return ranked planning patterns with pattern-specific relevance."""

        query_terms = terms(query)
        anchors = active_pack()["anchors"]
        keywords = active_pack().get("pattern_keywords", {})  # bộ Phần mềm không có: chấm điểm như cũ
        eligible_names = {
            name for name, values in anchors.items() if query_terms & values
        }
        intent_terms = query_terms & set().union(*(
            terms(" ".join(anchors[name])) for name in eligible_names
        ))
        candidates = [
            SourceChunk(**{
                **chunk.__dict__, "text": f"{chunk.source_name}\n{chunk.text}\n{keywords.get(chunk.source_name, '')}".rstrip()
            })
            for chunk in self.chunks
            if chunk.source_name in eligible_names
        ]
        score_floor = self.min_score if min_score is None else max(0.0, float(min_score))

        found = retrieve(
            " ".join(sorted(intent_terms)),
            candidates,
            top_k=top_k,
            min_score=score_floor,
        )
        originals = {chunk.chunk_id: chunk for chunk in self.chunks}
        return [
            SourceChunk(**{**originals[hit.chunk_id].__dict__, "score": hit.score})
            for hit in found
        ]
