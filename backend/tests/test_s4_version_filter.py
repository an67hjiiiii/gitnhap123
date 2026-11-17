"""Pure version policy and post-guard notice contracts."""
import asyncio
import json
from datetime import date
import unicodedata

import pytest

from app.core.access import asks_other_versions, filter_version_ids
from app.core.types import ProviderResult, RunMetrics, SourceChunk
from app.research.vanilla import answer_vanilla
from app.storage.vector_store import InMemoryVectorStore, _require_scope


@pytest.mark.parametrize("query", ["bản cũ", "bản 1.0", "phiên bản 2.3", "dự thảo", "trước đây",
    "thay đổi", "khác nhau", "so với", "so sánh", "điểm mới", "bị bỏ", "thêm", "compare versions"])
def test_other_version_intent(query):
    assert asks_other_versions(query)
    assert asks_other_versions(unicodedata.normalize("NFD", query.upper()))


def version(source, effective, *, status="issued", confirmed=True, family="F"):
    return {"source_id": source, "family_key": family, "effective_from": effective,
            "status": status, "confirmed_at": "confirmed" if confirmed else None}


def test_current_only_within_visible_scope_and_only_confirmed():
    versions = [version("old", date(2025, 1, 1)), version("new", date(2026, 1, 1)),
                version("tie", date(2026, 1, 1)), version("draft", date(2027, 1, 1), status="draft"),
                version("proposal", date(2028, 1, 1), confirmed=False),
                version("future", date(2028, 1, 1)), version("undated", None),
                version("no_family", date(2024, 1, 1), family=None)]
    today = date(2026, 11, 17)
    visible = {v["source_id"] for v in versions}
    assert filter_version_ids(visible, versions, "hiện hành", today=today) == visible - {"old", "draft"}
    assert filter_version_ids({"old"}, versions, "hiện hành", today=today) == {"old"}
    assert filter_version_ids(visible, versions, "bản cũ", today=today) == visible
    assert filter_version_ids(set(), versions, "hiện hành", today=today) == set()
    assert filter_version_ids({"proposal"}, versions, "hiện hành", today=today) == {"proposal"}


@pytest.mark.parametrize("flag,confirmed,sources,cited,notice", [
    ("off", False, ["a", "b"], ["c0", "c1"], False),
    ("on", False, ["a", "b"], ["c0", "c1"], True),
    ("on", True, ["a", "b"], ["c0", "c1"], False),
    ("on", False, ["a", "a"], ["c0", "c1"], False),
    ("on", False, ["a", "b"], ["c0"], True),  # bản chưa xác nhận có trong bằng chứng dù không được trích
])
def test_notice_after_guard(monkeypatch, flag, confirmed, sources, cited, notice):
    monkeypatch.setenv("VERSION_FILTER", flag)
    evidence = [SourceChunk(f"c{i}", source, "policy", "Fact", i,
                provenance={"family_key": "F", "version_confirmed": confirmed and i == 0})
                for i, source in enumerate(sources)]
    class Provider:
        async def generate(self, **kwargs):
            return ProviderResult(json.dumps({"answer": "Fact", "status": "COMPLETE", "citations": cited}))
    class Checker:
        def guard(self, answer, **kwargs):
            from app.chat.answer_guard import GuardResult
            assert "Lưu ý" not in answer
            return GuardResult("Guarded fact")
        def needs_verification(self, query, answer):
            return False
    result = asyncio.run(answer_vanilla(Provider(), "hiện hành", evidence, RunMetrics(), checker=Checker()))
    assert ("Lưu ý: chưa xác nhận bản hiện hành của F." in result.answer) == notice
    assert result.answer.startswith("Guarded fact")


def test_vector_scope_is_required_and_empty_is_closed():
    with pytest.raises(ValueError):
        _require_scope(None, None)
    assert InMemoryVectorStore().search([1.0], source_ids=[]) == []
