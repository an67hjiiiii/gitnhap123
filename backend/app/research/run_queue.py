"""Hàng đợi lượt chạy của ô chat sản phẩm (đợt 9, 19/11).

Máy chủ cục bộ thường chỉ có một GPU: cả tổ chức hỏi cùng lúc thì các lời gọi Ollama tranh nhau và quá thời gian chờ.
Giới hạn số lượt chạy đồng thời (PRODUCT_MAX_CONCURRENT_RUNS, mặc định 1), người đến sau xếp hàng theo thứ tự
và được báo thứ tự chờ. Hàng đợi ở cấp lượt chạy, không ở từng lời gọi mô hình, nên thời gian đo của một lượt
không lẫn thời gian chờ người khác. Thực nghiệm A/B/C không đi qua hàng đợi này.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

PositionCallback = Callable[[int], None] | None


class FairQueue:
    def __init__(self, limit: int):
        self.limit = max(1, int(limit))
        self.active = 0
        self._waiters: list[tuple[asyncio.Future, PositionCallback]] = []
        self._tokens: set[object] = set()

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    def _notify(self) -> None:
        for i, (_, cb) in enumerate(list(self._waiters)):
            if cb is not None:
                try:
                    cb(i + 1)
                except Exception:
                    # Callback phía client ngắt kết nối hoặc lỗi không được làm treo hàng đợi (FQ-02)
                    pass

    async def acquire(self, on_position: PositionCallback = None) -> object:
        token = object()
        if self.active < self.limit and not self._waiters:
            self.active += 1
            self._tokens.add(token)
            return token
        fut = asyncio.get_running_loop().create_future()
        entry = (fut, on_position)
        self._waiters.append(entry)
        try:
            self._notify()
            await fut  # release() chuyển thẳng chỗ cho người đầu hàng (active giữ nguyên)
        except BaseException:
            if entry in self._waiters:  # bỏ đi khi đang chờ: rời hàng, người sau lên một bậc
                self._waiters.remove(entry)
                self._notify()
            elif fut.done() and not fut.cancelled():  # vừa được chỗ thì bị hủy: trả chỗ lại
                self._release_slot()
            raise
        self._tokens.add(token)
        return token

    def _release_slot(self) -> None:
        while self._waiters:
            fut, _ = self._waiters.pop(0)
            if not fut.done():
                fut.set_result(None)
                self._notify()
                return
        self.active = max(0, self.active - 1)

    def release(self, token: object | None = None) -> None:
        if token is not None:
            if token not in self._tokens:
                return  # đã trả chỗ rồi: chống double-release (FQ-01)
            self._tokens.discard(token)
        elif self._tokens:
            # giữ tương thích ngược cho caller cũ không truyền token, chỉ giảm nếu còn slot đang hoạt động
            if self.active <= 0:
                return
        self._release_slot()

    @asynccontextmanager
    async def slot(self, on_position: PositionCallback = None) -> AsyncIterator[None]:
        token = await self.acquire(on_position)
        try:
            yield
        finally:
            self.release(token)


product_runs = FairQueue(int(os.getenv("PRODUCT_MAX_CONCURRENT_RUNS", "1") or 1))

__all__ = ["FairQueue", "product_runs"]
