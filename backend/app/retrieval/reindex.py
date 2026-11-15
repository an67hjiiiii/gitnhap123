"""Background, per-source re-indexing when the embedder identity (embedding_version) changed.

The old collection is never deleted: vectors are re-embedded in place (same record ids) by the incremental
`CandidateIndex.index_source`, one source at a time. While it runs, document questions get a friendly
"index is updating (done/total)" answer instead of INDEX_INCOMPATIBLE.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Iterable

from app.retrieval.index_identity import IndexState, compute_state

logger = logging.getLogger(__name__)


def index_state(index) -> IndexState:
    """Identity state of the collection behind `index` (cheap: reads the manifest only)."""
    return compute_state(index._read_manifest(), index.identity)


class ReindexManager:
    """One rebuild at a time per process; progress is readable from any request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "failed": 0,
                                       "started_at": None, "finished_at": None, "duration_s": None}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    @property
    def running(self) -> bool:
        return self.status()["status"] == "running"

    def start(self, make_index: Callable[[str], Any], items: Iterable[tuple[str, str]], *,
              prepare: Callable[[], None] | None = None) -> bool:
        """Start a rebuild of (owner_id, source_id) items in the background. False if one is already running."""
        items = list(items)
        with self._lock:
            if self._state["status"] == "running":
                return False
            self._state.update(status="running", done=0, total=len(items), failed=0,
                               started_at=time.time(), finished_at=None, duration_s=None)
            self._thread = threading.Thread(target=self._run, args=(make_index, items, prepare),
                                            name="reindex", daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self, make_index, items, prepare) -> None:
        try:
            if prepare is not None:
                prepare()
            for owner, source_id in items:
                try:
                    make_index(owner).index_source(source_id)
                except Exception:  # one broken source must not stop the others
                    logger.exception("reindex failed for source %s", source_id)
                    with self._lock:
                        self._state["failed"] += 1
                with self._lock:
                    self._state["done"] += 1
        except Exception:
            logger.exception("reindex aborted")
            with self._lock:
                self._state["failed"] += 1
        finally:
            with self._lock:
                now = time.time()
                self._state.update(status="failed" if self._state["failed"] else "done", finished_at=now,
                                   duration_s=round(now - (self._state["started_at"] or now), 1))
