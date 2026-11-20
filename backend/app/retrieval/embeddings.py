from __future__ import annotations

import hashlib
import math
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


_CLIENTS: dict[tuple[str, float], object] = {}


def _client(base_url: str, timeout: float):
    """Một kết nối HTTP dùng lại cho mỗi địa chỉ Ollama: httpx.post() mỗi lần tạo client và nạp chứng chỉ (~0,3 giây
    trên Windows), làm câu có nhiều câu ví dụ chậm hẳn (20/11)."""
    import httpx

    key = (base_url, timeout)
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


def make_embedder(dimension: int = 768) -> TextEmbedder:
    """Chọn embedder theo EMBEDDING_BACKEND (hash | ollama). Mặc định hash, giữ hành vi cũ."""
    import os

    backend = os.getenv("EMBEDDING_BACKEND", "hash").strip().lower()
    if backend == "hash":
        return LocalHashEmbedder(dimension=dimension)
    if backend == "ollama":
        return OllamaEmbedder(
            dimension=dimension,
            model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip(),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        )
    raise ValueError(f"Unsupported EMBEDDING_BACKEND={backend}")


__all__ = ["EMBEDDING_VERSION", "LocalHashEmbedder", "OllamaEmbedder", "TextEmbedder", "make_embedder"]
