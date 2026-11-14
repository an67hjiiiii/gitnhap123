from pathlib import Path

import pytest

from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import make_embedder
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore


DOCS = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_docs"
CASES = [
    ("readme.md", "14 days"),
    ("requirements.md", "31 days"),
    ("public_api.md", "9 hours"),
    ("policy.txt", "45 minutes"),
    ("table.md", "cobalt | archive | 23"),
    ("vietnamese.md", "28 ngày"),
]


@pytest.mark.parametrize(("filename", "sentence"), CASES)
def test_synthetic_document_import_chunk_and_retrieval(tmp_path, sf1_fake_provider_env, filename, sentence):
    store = SourceStore(str(tmp_path / "sources"))
    imported = store.import_text(filename, (DOCS / filename).read_text(encoding="utf-8"))
    chunks = store.chunks([imported["source_id"]])
    assert chunks
    vector_store = InMemoryVectorStore()
    index = CandidateIndex(store, vector_store, owner_user_id="acceptance", embedder=make_embedder(768))
    index.index_source(imported["source_id"])
    found = index.candidates(sentence, limit=4)
    assert found
    assert any(sentence.casefold() in c.text.casefold() for c in chunks)
