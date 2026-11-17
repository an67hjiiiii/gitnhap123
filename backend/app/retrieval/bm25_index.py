"""Bounded corpus cache for deterministic, owner-scoped BM25 statistics."""
from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass

from app.retrieval.text import content_hash, contextual_text


@dataclass(frozen=True)
class Bm25Index:
    postings: dict[str, dict[str, int]]
    lengths: dict[str, int]
    df: Counter
    avg_length: float
    size: int
    headers: tuple


_CACHE: OrderedDict = OrderedDict()


def get_index(chunks) -> Bm25Index:
    # Recompute hashes: callers can supply mutable or legacy provenance.
    key = tuple(sorted((c.chunk_id, content_hash(c.text)) for c in chunks))
    headers = tuple(sorted((c.chunk_id, c.provenance.get("context_header", "")) for c in chunks))
    cached = _CACHE.get(key)
    if cached is not None and cached.headers == headers:
        _CACHE.move_to_end(key)
        return cached
    from app.retrieval.hybrid import tokens

    postings: dict[str, dict[str, int]] = {}
    lengths: dict[str, int] = {}
    df: Counter = Counter()
    for chunk in chunks:
        corpus_tokens = tokens(contextual_text(chunk))
        lengths[chunk.chunk_id] = len(corpus_tokens)
        counts = Counter(corpus_tokens)
        df.update(counts.keys())
        for term, count in counts.items():
            postings.setdefault(term, {})[chunk.chunk_id] = count
    size = len(chunks)
    index = Bm25Index(postings, lengths, df,
                      (sum(lengths.values()) / size or 1.0) if size else 1.0,
                      size, headers)
    _CACHE[key] = index
    _CACHE.move_to_end(key)
    if len(_CACHE) > 32:
        _CACHE.popitem(last=False)
    return index


# Persistent indexes deliberately use a separate tokenizer and cache so the
# default (legacy) ranking above remains byte-for-byte compatible.
import gzip
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import replace
from pathlib import Path

FOLDED_FIELD_WEIGHT = 0.5
_PERSISTED = OrderedDict()
_LOCK = threading.RLock()
_WORD = re.compile(r"[^\W_]+(?:_[^\W_]+)*", re.UNICODE)

try:
    from underthesea import word_tokenize as _segment
    TOKENIZER = "underthesea"
except ImportError:
    try:
        from pyvi import ViTokenizer
        _segment = ViTokenizer.tokenize
        TOKENIZER = "pyvi"
    except ImportError:
        _segment = None
        TOKENIZER = "syllable_unigram_bigram"


def enabled():
    return os.getenv("BM25_INDEX", "").strip().lower() == "persist"


def fold_text(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower().replace("đ", "d").replace("Đ", "d"))
                   if unicodedata.category(c) != "Mn")


def tokenize(text):
    """One tokenizer for both fields and queries; fallback keeps adjacent syllables."""
    text = unicodedata.normalize("NFC", text).lower()
    if _segment is not None:
        segmented = _segment(text, format="text") if TOKENIZER == "underthesea" else _segment(text)
        return _WORD.findall(segmented)
    # Do not form bigrams across punctuation/sentence boundaries.
    result = []
    for phrase in re.split(r"[^\w\s]+|[\r\n]+", text):
        words = _WORD.findall(phrase)
        result.extend(words)
        result.extend(a + "_" + b for a, b in zip(words, words[1:]))
    return result


def signature(store):
    reader = getattr(store, "retrieval_signature", None)
    if not callable(reader) and hasattr(store, "path"):
        return repr((len(store._chunks), store.path.stat().st_mtime_ns if store.path.exists() else None))
    return repr(reader() if callable(reader) else store.snapshot_id())


def index_path(store, directory=None):
    """Hash scope components (including database) to avoid path traversal/collisions."""
    factory = getattr(store, "session_factory", None)
    bind = factory.kw.get("bind") if factory is not None else None
    database = str(bind.url.render_as_string(hide_password=True)) if bind is not None else str(store.root.resolve())
    scope = [database, getattr(store, "owner_user_id", None), getattr(store, "space_id", None)]
    root = directory or os.getenv("BM25_INDEX_DIR")
    if root is None:
        root = getattr(store, "root", None)
    if root is None:
        root = Path(os.getenv("APP_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))) / "bm25"
    digest = hashlib.sha256(json.dumps(scope).encode("utf-8")).hexdigest()
    return Path(root) / ("bm25-" + digest + ".json.gz")


class PersistentIndex:
    def __init__(self, documents=None):
        self.documents = documents or {}
        self.postings = [{}, {}]
        self.lengths = [{}, {}]
        for cid, doc in self.documents.items():
            self._add_postings(cid, doc)

    def _add_postings(self, cid, doc):
        for field in range(2):
            counts = doc["fields"][field]
            self.lengths[field][cid] = sum(counts.values())
            for term, count in counts.items():
                self.postings[field].setdefault(term, {})[cid] = count

    def replace_sources(self, source_ids, chunks):
        for cid in list(self.documents):
            if self.documents[cid]["source"] in source_ids:
                doc = self.documents.pop(cid)
                for field in range(2):
                    self.lengths[field].pop(cid)
                    for term in doc["fields"][field]:
                        posting = self.postings[field][term]
                        posting.pop(cid)
                        if not posting:
                            del self.postings[field][term]
        from app.retrieval.text import terms
        for chunk in chunks:
            text = contextual_text(chunk)
            doc = {"source": chunk.source_id,
                   "fields": [dict(Counter(tokenize(text))), dict(Counter(tokenize(fold_text(text))))],
                   "lexical": sorted(terms(chunk.text))}
            self.documents[chunk.chunk_id] = doc
            self._add_postings(chunk.chunk_id, doc)

    def rank(self, query, source_ids, top_k, min_score=0.0, bm25=True):
        allowed = None if source_ids is None else set(source_ids)
        ids = {cid for cid, doc in self.documents.items() if allowed is None or doc["source"] in allowed}
        if not ids:
            return []
        scores = {}
        if not bm25:
            from app.retrieval.text import terms
            q = terms(query)
            for cid in ids:
                c = set(self.documents[cid]["lexical"])
                overlap = len(q & c)
                score = round(0.8 * overlap / max(1, len(q)) + 0.2 * overlap / max(1, len(c)), 8)
                if score > 0 and score >= min_score:
                    scores[cid] = score
        else:
            for field, text, weight in ((0, query, 1.0), (1, fold_text(query), FOLDED_FIELD_WEIGHT)):
                avg = sum(self.lengths[field][cid] for cid in ids) / len(ids) or 1.0
                for term in set(tokenize(text)):
                    posting = self.postings[field].get(term, {})
                    matching = ids.intersection(posting)
                    df = len(matching)
                    idf = math.log(1 + (len(ids) - df + 0.5) / (df + 0.5))
                    for cid in matching:
                        freq = posting[cid]
                        scores[cid] = scores.get(cid, 0.0) + weight * idf * freq * 2.5 / (
                            freq + 1.5 * (0.25 + 0.75 * self.lengths[field][cid] / avg))
            scores = {cid: round(score, 6) for cid, score in scores.items() if score > 0}
        ranked = sorted(scores.items(), key=lambda row: (-row[1], row[0]))
        if bm25 and ranked:
            ranked = [row for row in ranked if row[1] >= 0.4 * ranked[0][1]]
        return ranked[:top_k]


def _load(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            data = json.load(stream)
        if data["version"] != 2 or data["tokenizer"] != TOKENIZER or not isinstance(data["documents"], dict):
            return None
        index = PersistentIndex()
        index.documents = data["documents"]
        index.postings = data["postings"]
        index.lengths = data["lengths"]
        if len(index.postings) != 2 or len(index.lengths) != 2:
            return None
        return data["signature"], index
    except (OSError, EOFError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _save(path, revision, index):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(descriptor)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", newline="\r\n") as stream:
            json.dump({"version": 2, "tokenizer": TOKENIZER, "signature": revision,
                       "documents": index.documents, "postings": index.postings,
                       "lengths": index.lengths}, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    _PERSISTED[path] = (revision, index, path.stat().st_mtime_ns)
    _PERSISTED.move_to_end(path)
    while len(_PERSISTED) > 16:
        _PERSISTED.popitem(last=False)


def _cached(path):
    cached = _PERSISTED.get(path)
    if cached is not None and path.exists() and cached[2] == path.stat().st_mtime_ns:
        _PERSISTED.move_to_end(path)
        return cached[:2]
    return _load(path)


def rebuild(store, directory=None):
    """Explicit full rebuild, also used once to repair missing/stale/corrupt files."""
    with _LOCK:
        revision = signature(store)
        index = PersistentIndex()
        index.replace_sources(set(), store.chunks())
        _save(index_path(store, directory), revision, index)
        return index


def update_source(store, source_id, previous_signature, removed_source_ids=()):
    """After a committed ingestion, update only that source and removed versions."""
    if not enabled():
        return
    with _LOCK:
        path = index_path(store)
        cached = _cached(path)
        if cached is None or cached[0] != previous_signature:
            rebuild(store)
            return
        index = cached[1]
        index.replace_sources({source_id, *removed_source_ids}, store.chunks([source_id]))
        _save(path, signature(store), index)


def persistent_rank(store, query, source_ids, top_k, min_score=0.0, *, bm25=True):
    if not enabled():
        return None
    scope = getattr(store, "scope_source_ids", None)
    if callable(scope):
        # Preserve the caller's original version intent (rewrites may differ).
        visible = scope()
        source_ids = sorted(visible if source_ids is None else visible & set(source_ids))
    else:
        scope = getattr(store, "effective_source_ids", None)
        if callable(scope):
            source_ids = sorted(scope(query, source_ids))
    if source_ids == []:
        return []
    with _LOCK:
        path = index_path(store)
        revision = signature(store)
        cached = _cached(path)
        if cached is None or cached[0] != revision:
            index = rebuild(store)
        else:
            index = cached[1]
            _PERSISTED[path] = (revision, index, path.stat().st_mtime_ns)
        ranked = index.rank(query, source_ids, top_k, min_score, bm25)
    chunks = {c.chunk_id: c for c in store.chunks_by_ids([cid for cid, _ in ranked], source_ids=source_ids)}
    return [replace(chunks[cid], score=score) for cid, score in ranked if cid in chunks]
