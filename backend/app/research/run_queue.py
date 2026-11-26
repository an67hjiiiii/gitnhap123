"""Hàng đợi lượt chạy của ô chat sản phẩm (đợt 9, 19/11).

Máy chủ cục bộ thường chỉ có một GPU: cả tổ chức hỏi cùng lúc thì các lời gọi Ollama tranh nhau và quá thời gian chờ.
Giới hạn số lượt chạy đồng thời (PRODUCT_MAX_CONCURRENT_RUNS, mặc định 1), người đến sau xếp hàng theo thứ tự
và được báo thứ tự chờ. Hàng đợi ở cấp lượt chạy, không ở từng lời gọi mô hình, nên thời gian đo của một lượt
không lẫn thời gian chờ người khác. Thực nghiệm A/B/C không đi qua hàng đợi này.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

PositionCallback = Callable[[int], None] | None


class QueueFullError(RuntimeError):
    """Hàng đợi đã đạt số người chờ tối đa cho phép."""


def _env_int(name: str, default: int | None) -> int | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float | None) -> float | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        return val if val > 0 else default
    except ValueError:
        return default


class FairQueue:
    def __init__(
        self,
        limit: int | Callable[[], int],
        *,
        max_waiters: int | Callable[[], int | None] | None = None,
        wait_timeout: float | Callable[[], float | None] | None = None,
    ):
        self._limit = limit
        self._max_waiters = max_waiters
        self._wait_timeout = wait_timeout
        self._lock = threading.RLock()
        self._active_tokens: set[int] = set()
        self._next_token = 0
        self._waiters: list[tuple[asyncio.Future, PositionCallback, asyncio.AbstractEventLoop]] = []

    @property
    def limit(self) -> int:
        val = self._limit() if callable(self._limit) else self._limit
        return max(1, int(val))

    @property
    def max_waiters(self) -> int | None:
        val = self._max_waiters() if callable(self._max_waiters) else self._max_waiters
        return None if val is None else max(0, int(val))

    @property
    def wait_timeout(self) -> float | None:
        val = self._wait_timeout() if callable(self._wait_timeout) else self._wait_timeout
        return None if val is None else max(0.001, float(val))

    @property
    def active(self) -> int:
        with self._lock:
            return len(self._active_tokens)

    @property
    def waiting(self) -> int:
        with self._lock:
            self._prune()
            return len(self._waiters)

    def _issue_token(self) -> int:
        self._next_token += 1
        self._active_tokens.add(self._next_token)
        return self._next_token

    def _prune(self) -> None:
        if self._waiters:
            self._waiters = [(f, cb, lp) for f, cb, lp in self._waiters if not f.done() and not lp.is_closed()]

    @staticmethod
    def _running_loop() -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    def _notify(self) -> None:
        with self._lock:
            self._prune()
            snapshot = list(self._waiters)
        running = self._running_loop()
        for i, (_, cb, lp) in enumerate(snapshot):
            if cb is None:
                continue
            pos = i + 1
            if running is lp:
                try:
                    cb(pos)
                except Exception:
                    logging.getLogger(__name__).exception("FairQueue position callback failed")
            elif not lp.is_closed():
                def _safe_cb(fn=cb, p=pos):
                    try:
                        fn(p)
                    except Exception:
                        logging.getLogger(__name__).exception("FairQueue position callback failed")
                lp.call_soon_threadsafe(_safe_cb)

    async def acquire(self, on_position: PositionCallback = None) -> int:
        loop = asyncio.get_running_loop()
        with self._lock:
            self._prune()
            if len(self._active_tokens) < self.limit and not self._waiters:
                return self._issue_token()
            cap = self.max_waiters
            if cap is not None and len(self._waiters) >= cap:
                raise QueueFullError("Hệ thống đang bận, vui lòng thử lại sau.")
            fut = loop.create_future()
            entry = (fut, on_position, loop)
            self._waiters.append(entry)
        try:
            self._notify()
            timeout = self.wait_timeout
            if timeout is not None:
                return await asyncio.wait_for(fut, timeout=timeout)
            return await fut  # release() chuyển thẳng chỗ cho người đầu hàng (tập active giữ nguyên số lượng)
        except BaseException:
            removed = False
            with self._lock:
                if entry in self._waiters:  # bỏ đi / quá thời gian khi đang chờ: rời hàng, người sau lên một bậc
                    self._waiters.remove(entry)
                    removed = True
            if removed:
                self._notify()
            elif fut.done() and not fut.cancelled():  # vừa được chỗ thì bị hủy hoặc hết giờ: trả đúng token đã nhận
                self.release(fut.result())
            raise

    def release(self, token: int | None = None) -> None:
        handoff: tuple[asyncio.Future, asyncio.AbstractEventLoop, int] | None = None
        with self._lock:
            if token is not None:
                if token not in self._active_tokens:
                    return
                self._active_tokens.discard(token)
            elif self._active_tokens:
                self._active_tokens.pop()
            else:
                return
            while self._waiters and len(self._active_tokens) < self.limit:
                fut, _, lp = self._waiters.pop(0)
                if not fut.done() and not lp.is_closed():
                    tok = self._issue_token()
                    handoff = (fut, lp, tok)
                    break
        if handoff is not None:
            fut, lp, tok = handoff
            running = self._running_loop()
            if running is lp:
                if not fut.done():
                    fut.set_result(tok)
                else:
                    self.release(tok)
            else:
                def _deliver(f=fut, t=tok):
                    if not f.done():
                        f.set_result(t)
                    else:
                        self.release(t)
                try:
                    lp.call_soon_threadsafe(_deliver)
                except RuntimeError:
                    self.release(tok)
        self._notify()

    @asynccontextmanager
    async def slot(self, on_position: PositionCallback = None) -> AsyncIterator[None]:
        token = await self.acquire(on_position)
        try:
            yield
        finally:
            self.release(token)


product_runs = FairQueue(
    lambda: _env_int("PRODUCT_MAX_CONCURRENT_RUNS", 1) or 1,
    max_waiters=lambda: _env_int("PRODUCT_MAX_WAITERS", None),
    wait_timeout=lambda: _env_float("PRODUCT_QUEUE_WAIT_TIMEOUT", None),
)

__all__ = ["FairQueue", "QueueFullError", "product_runs"]
