from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from app.retrieval.embeddings import LocalHashEmbedder, OllamaEmbedder, TextEmbedder


class IndexingError(RuntimeError):
    """A derived-index write failed; the authoritative source remains separate."""


class IndexIncompatibleError(IndexingError):
    code = "INDEX_INCOMPATIBLE"


class IndexLegacyUnverifiedError(IndexingError):
    code = "INDEX_LEGACY_UNVERIFIED"


class IndexState(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    EMPTY = "EMPTY"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
    INCOMPATIBLE = "INCOMPATIBLE"


@dataclass(frozen=True)
class IndexIdentity:
    backend: str
    model_name: str
    dimension: int
    embedding_version: str
    normalization_version: str
    digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("backend", "model_name", "embedding_version", "normalization_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if type(self.dimension) is not int or self.dimension < 1:
            raise ValueError("dimension must be a positive integer")
        if self.digest is not None and (not isinstance(self.digest, str) or not self.digest.strip()):
            raise ValueError("digest must be non-empty when supplied")

    @classmethod
    def from_embedder(cls, embedder: TextEmbedder) -> IndexIdentity:
        """Describe the configured embedder without invoking it or fetching a digest."""
        if isinstance(embedder, LocalHashEmbedder):
            backend, model, normalization = "hash", "local-hash", "text-nfc-terms-l2-v1"
        elif isinstance(embedder, OllamaEmbedder):
            backend, model, normalization = "ollama", embedder.model, "ollama-raw-v1"
        else:
            backend = f"{type(embedder).__module__}.{type(embedder).__qualname__}"
            model, normalization = type(embedder).__name__, "embedder-default-v1"
        return cls(
            backend=getattr(embedder, "backend", backend),
            model_name=getattr(embedder, "model_name", getattr(embedder, "model", model)),
            digest=getattr(embedder, "digest", None),
            dimension=embedder.dimension,
            embedding_version=embedder.version if embedder.version.endswith("+hdr1") else embedder.version + "+hdr1",
            normalization_version=getattr(embedder, "normalization_version", normalization),
        )


@dataclass(frozen=True)
class IndexManifest:
    identity: IndexIdentity
    empty: bool = False
    payload_complete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.identity, IndexIdentity):
            raise ValueError("identity must be an IndexIdentity")
        if type(self.empty) is not bool or type(self.payload_complete) is not bool:
            raise ValueError("manifest flags must be booleans")


def manifest_path(index_path: str | Path, collection: str) -> Path:
    """Keep the collection sidecar next to, never inside, the Qdrant directory."""
    if not collection or collection in {".", ".."} or any(c in collection for c in "/\\:"):
        raise ValueError("collection must be a single filename component")
    return Path(index_path).parent / f"{collection}.manifest.json"


def read_manifest(path: str | Path) -> IndexManifest | None:
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("unsupported manifest schema")
        return IndexManifest(
            identity=IndexIdentity(**raw["identity"]),
            empty=raw.get("empty", False),
            payload_complete=raw.get("payload_complete", False),
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise IndexIncompatibleError(f"Cannot verify index manifest: {path}") from exc


def write_manifest(path: str | Path, manifest: IndexManifest) -> None:
    """Replace the sidecar atomically so readers never observe partial JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps({"schema_version": 1, **asdict(manifest)}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def compute_state(manifest: IndexManifest | None, current: IndexIdentity) -> IndexState:
    """Use metadata only; absent metadata is conservatively unverified, never empty."""
    if manifest is None:
        return IndexState.LEGACY_UNVERIFIED
    if manifest.identity != current:
        return IndexState.INCOMPATIBLE
    return IndexState.EMPTY if manifest.empty else IndexState.COMPATIBLE
