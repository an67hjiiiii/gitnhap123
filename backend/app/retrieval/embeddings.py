from __future__ import annotations

import hashlib
import math
import os
import threading
from dataclasses import dataclass
from typing import Protocol

from app.retrieval.text import normalize_text, terms


EMBEDDING_VERSION = "local-hash-embedding-v1"


class TextEmbedder(Protocol):
    dimension: int
    version: str

    def embed(self, text: str) -> tuple[float, ...]: ...


@dataclass(frozen=True)
class LocalHashEmbedder:
    """Deterministic local vectorizer for the optional derived index.

    This is a lexical/hash embedding, not a research model.  It keeps local
    index tests deterministic and records a version so it cannot be confused
    with semantic-model evidence.
    """

    dimension: int = 768
    version: str = EMBEDDING_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int):
            raise TypeError("embedding dimension must be an integer")
        if self.dimension < 1:
            raise ValueError("embedding dimension must be positive")

    def embed(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        clean = normalize_text(text)
        values = [0.0] * self.dimension
        tokens = sorted(terms(clean))
        if not tokens and clean:
            tokens = [clean.casefold()]
        for token in tokens:
            digest = hashlib.sha256(
                f"{self.version}\0{token}".encode("utf-8")
            ).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            values[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            return tuple(values)
        return tuple(round(value / norm, 8) for value in values)

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self.embed(t) for t in texts]


_CLIENTS_LOCK = threading.Lock()
_CLIENTS: dict[tuple[str, float], object] = {}


def _client(base_url: str, timeout: float):
    """Một kết nối HTTP dùng lại cho mỗi địa chỉ Ollama: httpx.post() mỗi lần tạo client và nạp chứng chỉ (~0,3 giây
    trên Windows), làm câu có nhiều câu ví dụ chậm hẳn (20/11)."""
    import httpx

    key = (base_url.rstrip("/"), float(timeout))
    with _CLIENTS_LOCK:
        if key not in _CLIENTS:
            _CLIENTS[key] = httpx.Client(timeout=timeout)
        return _CLIENTS[key]


@dataclass(frozen=True)
class OllamaEmbedder:
    """Embedding ngữ nghĩa qua Ollama (mặc định nomic-embed-text, 768 chiều), chạy cục bộ.

    Chuyển từ C1SE.27. Bật bằng EMBEDDING_BACKEND=ollama. Đổi embedder thì phải dùng
    VECTOR_COLLECTION mới (hoặc index lại), không trộn vector hash với vector ngữ nghĩa.
    """

    dimension: int = 768
    model: str = "nomic-embed-text"
    base_url: str = "http://127.0.0.1:11434"
    timeout: float = 60.0

    @property
    def version(self) -> str:
        return f"ollama:{self.model}:{self.dimension}"

    def embed(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        response = _client(self.base_url, self.timeout).post(
            f"{self.base_url.rstrip('/')}/api/embed",
            json={"model": self.model, "input": text or " "},
            timeout=self.timeout,
        )
        response.raise_for_status()
        vectors = response.json().get("embeddings") or []
        if not vectors or len(vectors[0]) != self.dimension:
            raise ValueError(
                f"Ollama embedding {self.model} returned dimension "
                f"{len(vectors[0]) if vectors else 0}, expected {self.dimension}"
            )
        return tuple(float(v) for v in vectors[0])

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        payload_inputs: list[str] = []
        for t in texts:
            if not isinstance(t, str):
                raise TypeError("texts must be strings")
            payload_inputs.append(t or " ")
        response = _client(self.base_url, self.timeout).post(
            f"{self.base_url.rstrip('/')}/api/embed",
            json={"model": self.model, "input": payload_inputs},
            timeout=self.timeout,
        )
        response.raise_for_status()
        vectors = response.json().get("embeddings") or []
        if len(vectors) != len(payload_inputs) or any(len(v) != self.dimension for v in vectors):
            raise ValueError(
                f"Ollama batch embedding {self.model} returned {len(vectors)} vectors "
                f"for {len(payload_inputs)} inputs (expected dimension {self.dimension})"
            )
        return [tuple(float(x) for x in v) for v in vectors]


_EMBEDDER_CACHE_LOCK = threading.Lock()
_EMBEDDER_CACHE: dict[tuple[str, int, str, str, float], TextEmbedder] = {}


def clear_embedder_cache() -> None:
    with _EMBEDDER_CACHE_LOCK:
        _EMBEDDER_CACHE.clear()


def make_embedder(dimension: int = 768) -> TextEmbedder:
    """Chọn và tái sử dụng embedder an toàn theo cấu hình (EMBEDDING_BACKEND | model | endpoint | dimension)."""
    backend = os.getenv("EMBEDDING_BACKEND", "hash").strip().lower()
    dim = int(dimension)
    if backend == "hash":
        key = ("hash", dim, EMBEDDING_VERSION, "", 0.0)
        with _EMBEDDER_CACHE_LOCK:
            hit = _EMBEDDER_CACHE.get(key)
            if hit is None:
                hit = _EMBEDDER_CACHE[key] = LocalHashEmbedder(dimension=dim)
            return hit
    if backend == "ollama":
        model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip()
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
        key = ("ollama", dim, model, base_url, 60.0)
        with _EMBEDDER_CACHE_LOCK:
            hit = _EMBEDDER_CACHE.get(key)
            if hit is None:
                hit = _EMBEDDER_CACHE[key] = OllamaEmbedder(
                    dimension=dim,
                    model=model,
                    base_url=base_url,
                )
            return hit
    raise ValueError(f"Unsupported EMBEDDING_BACKEND={backend}")


__all__ = [
    "EMBEDDING_VERSION",
    "LocalHashEmbedder",
    "OllamaEmbedder",
    "TextEmbedder",
    "clear_embedder_cache",
    "make_embedder",
]
