from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Protocol

from app.retrieval.text import normalize_text, terms


EMBEDDING_VERSION = "local-hash-embedding-v1+hdr1"


class TextEmbedder(Protocol):
    dimension: int
    version: str

    def embed(self, text: str) -> tuple[float, ...]: ...

    # Optional at runtime: callers fall back to embed for older implementations.
    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]: ...


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

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self.embed(text) for text in texts]

    def embed(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        clean = normalize_text(text)
        values = [0.0] * self.dimension
        tokens = sorted(terms(clean))
        if not tokens and clean:
            tokens = [clean.casefold()]
        for token in tokens:
            # Header versioning changes index compatibility, not hash coordinates.
            digest = hashlib.sha256(
                f"{self.version.removesuffix('+hdr1')}\0{token}".encode("utf-8")
            ).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            values[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            return tuple(values)
        return tuple(round(value / norm, 8) for value in values)


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
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        if any(not isinstance(text, str) for text in texts):
            raise TypeError("text must be a string")
        result: list[tuple[float, ...]] = []
        for start in range(0, len(texts), 16):
            batch = texts[start:start + 16]
            response = embedding_post(
                f"{self.base_url.rstrip('/')}/api/embed",
                json={"model": self.model, "input": [text or " " for text in batch]},
                timeout=self.timeout,
            )
            response.raise_for_status()
            vectors = response.json().get("embeddings") or []
            if len(vectors) != len(batch):
                raise ValueError("Ollama returned an unexpected embedding count")
            for vector in vectors:
                if len(vector) != self.dimension:
                    raise ValueError(f"Ollama embedding {self.model} returned dimension {len(vector)}, expected {self.dimension}")
                result.append(tuple(float(v) for v in vector))
        return result


def embedding_post(*args, **kwargs):
    """Module-level HTTP seam for offline tests."""
    import httpx
    return httpx.post(*args, **kwargs)


def effective_dimension(vector_size: int | None = None) -> int:
    return int(os.getenv("EMBEDDING_DIMENSION") or
               (vector_size if vector_size is not None else os.getenv("VECTOR_SIZE", "768")))


def validate_embedding_config(embedder: TextEmbedder, collection_dimension: int) -> None:
    if embedder.dimension != collection_dimension:
        raise ValueError(f"Embedding dimension {embedder.dimension} differs from collection dimension {collection_dimension}")


def make_embedder(dimension: int | None = None) -> TextEmbedder:
    """Chọn embedder theo EMBEDDING_BACKEND (hash | ollama). Mặc định hash, giữ hành vi cũ."""
    backend = os.getenv("EMBEDDING_BACKEND", "hash").strip().lower()
    dimension = effective_dimension(dimension)
    if backend == "hash":
        return LocalHashEmbedder(dimension=dimension)
    if backend == "ollama":
        return OllamaEmbedder(
            dimension=dimension,
            model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip(),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        )
    raise ValueError(f"Unsupported EMBEDDING_BACKEND={backend}")


__all__ = ["EMBEDDING_VERSION", "LocalHashEmbedder", "OllamaEmbedder", "TextEmbedder", "make_embedder", "effective_dimension", "validate_embedding_config"]
