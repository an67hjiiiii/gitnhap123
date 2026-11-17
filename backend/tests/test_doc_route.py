"""Document-first routing, offline embeddings, and S4 authorization boundaries."""
from types import SimpleNamespace

import pytest

from app.ingestion.documents import extract_document
from app.research.pipeline import ResearchPipeline
from app.research.product_retrieval import _lists_for
from app.retrieval.doc_route import build_doc_card, route_source_ids, rebuild_doc_cards
from app.retrieval.embeddings import LocalHashEmbedder
from app.storage.source_store import SourceStore
from test_s4_leak_matrix import matrix_db


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC_ROUTE", "on")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    store = SourceStore(str(tmp_path / "sources"))
    ids = {}
    for number, year, heading in [(34, 2026, "Bảo vệ dữ liệu"), (53, 2025, "Điều kiện tuyển dụng"),
                                  (8, 2022, "Thời hạn lưu trữ"), (34, 2024, "Thanh toán công tác phí"),
                                  (91, 2026, "An toàn phòng cháy")]:
        name = f"policy-{number}-{year}.txt"
        text = (f"BỘ NỘI VỤ\nSố: {number:02}/{year}/TT-BNV\nngày 12 tháng 3 năm {year}\n"
                f"THÔNG TƯ\nQuy định chính sách {number}\nĐiều 1. {heading}\nNội dung thi hành.")
        ids[number, year] = store.import_text(name, text)["source_id"]
    return store, ids


def test_card_is_deterministic_and_not_a_regular_chunk(corpus):
    store, _ = corpus
    text = "Số: 08/2022/TT-BNV\nngày 1 tháng 2 năm 2022\nThông tư\nVề việc lưu trữ\nĐiều 3. Thời hạn"
    card = build_doc_card("a.txt", text)
    assert card == build_doc_card("a.txt", text)
    assert "tt:8" in card["number_keys"]
    assert card["article_headings"] == ["Điều 3. Thời hạn"]
    assert card["title"] == "Về việc lưu trữ"
    assert card["dates"] == ["ngày 1 tháng 2 năm 2022"]
    assert len(card["opening_lines"]) == 5
    assert extract_document(text, "a.txt").provenance["doc_card"] == card
    document = extract_document(text, "a.txt")
    new_id = store.import_text(document.source_name, document.text, provenance=document.provenance)["source_id"]
    assert store.doc_cards([new_id])[0].text == card["text"]
    assert len(store.doc_cards()) == 6
    assert all(c.provenance.get("chunk_kind") != "doc_card" for c in store.chunks())
    assert all("doc_card" not in c.provenance for c in store.chunks())


@pytest.mark.parametrize("query,key", [("34/2026 quy định gì?", (34, 2026)),
    ("Thông tư 53 quy định gì?", (53, 2025)), ("TT 08/2022 có gì?", (8, 2022))])
def test_explicit_numbers_are_prioritized(corpus, query, key):
    store, ids = corpus
    pipeline = ResearchPipeline(store, None)
    routed = route_source_ids(pipeline, query)
    assert len(routed) == 3
    assert routed[0] == ids[key]
    cfg = SimpleNamespace(retrieval_min_score=-1)
    groups = _lists_for(pipeline, query, store.chunks(), cfg, None, 100, "hybrid")
    assert all(c.source_id in routed for group in groups for c in group)


def test_short_number_beats_irrelevant_ranking(corpus, monkeypatch):
    store, ids = corpus
    import app.retrieval.doc_route as module
    def adversarial_merge(rankings, top_k):
        return sorted(store.doc_cards(), key=lambda c: c.source_id == ids[53, 2025])
    monkeypatch.setattr(module, "rrf_merge", adversarial_merge)
    assert route_source_ids(ResearchPipeline(store, None), "Thông tư 53")[0] == ids[53, 2025]


def test_article_heading_and_same_embedder(corpus):
    store, ids = corpus
    class SpyEmbedder(LocalHashEmbedder):
        def embed(self, text):
            calls.append(text)
            return super().embed(text)
    calls = []
    pipeline = ResearchPipeline(store, None)
    pipeline.candidate_index = SimpleNamespace(embedder=SpyEmbedder())
    assert route_source_ids(pipeline, "Thời hạn lưu trữ")[0] == ids[8, 2022]
    assert len(calls) == 6


def test_empty_scope_and_missing_cards_fail_closed(corpus, tmp_path):
    store, _ = corpus
    pipeline = ResearchPipeline(store, None)
    assert route_source_ids(pipeline, "TT 53", []) == []
    assert pipeline._retrieve_candidates("TT 53", store.chunks(), top_k=100, min_score=-1, source_ids=[]) == []
    empty = ResearchPipeline(SourceStore(str(tmp_path / "empty")), None)
    assert route_source_ids(empty, "TT 53") == []
    # An old corpus without cards must never fall back to every source.
    for row in store._sources.values():
        row["provenance"].pop("doc_card")
    assert pipeline._retrieve_candidates("thi hành", store.chunks(), top_k=100, min_score=-1, source_ids=None) == []


def test_disabled_preserves_legacy(tmp_path, monkeypatch):
    monkeypatch.delenv("DOC_ROUTE", raising=False)
    store = SourceStore(str(tmp_path / "legacy"))
    for i in range(5):
        store.import_text(f"{i}.txt", "access policy")
    pipeline = ResearchPipeline(store, None)
    assert route_source_ids(pipeline, "access") is None
    assert len(pipeline._retrieve_candidates("access", None, top_k=100, min_score=-1, source_ids=None)) == 5
    assert not store.doc_cards()
    assert "doc_card" not in extract_document("access", "x.txt").provenance


def test_s4_cards_and_fusion_do_not_leak(matrix_db, monkeypatch):
    from app.storage.postgres.runtime import PostgresSourceStore
    from app.storage.postgres.models import KnowledgeSourceRecord
    _, factory, users, space, _, ids, _ = matrix_db
    monkeypatch.setenv("DOC_ROUTE", "on")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    # Rebuild only this fixture's sources, without touching unrelated scratch data.
    assert rebuild_doc_cards(factory, source_ids=list(ids.values())) == len(ids)
    assert rebuild_doc_cards(factory, source_ids=list(ids.values())) == len(ids)
    with factory() as db:
        assert all((db.get(KnowledgeSourceRecord, sid).display_metadata or {}).get("doc_card") for sid in ids.values())
    for user in users.values():
        store = PostgresSourceStore(factory, user, space_id=space)
        pipeline = ResearchPipeline(store, None)
        for version in ("off", "on"):
            monkeypatch.setenv("VERSION_FILTER", version)
            for query in ("hiện hành", "bản cũ", "Thông tư 53", "34/2026"):
                for selected in (None, [], list(ids.values())):
                    allowed = store.effective_source_ids(query, selected)
                    routed = route_source_ids(pipeline, query, selected)
                    assert set(routed) <= allowed
                    assert len(routed) <= 3
                    assert {c.source_id for c in store.doc_cards(selected)} <= store.scope_source_ids()
                    groups = _lists_for(pipeline, query, None, SimpleNamespace(retrieval_min_score=-1),
                                        selected, 100, "hybrid")
                    assert all(c.source_id in routed for group in groups for c in group)
