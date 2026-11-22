"""Tiến trình gửi dần cho ô chat sản phẩm (/api/chat/stream).

Chỉ endpoint stream đặt `progress_sink`; thực nghiệm và /api/chat thường để None nên pipeline chạy y như cũ.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from typing import Any, AsyncIterator, Awaitable, Callable

progress_sink: ContextVar[Callable[[dict], None] | None] = ContextVar("progress_sink", default=None)


def emit(item: dict) -> None:
    sink = progress_sink.get()
    if sink is not None:
        sink(item)


def bound_emit() -> Callable[[dict], None]:
    """emit gắn với người nghe hiện tại: dùng cho lời báo gọi từ tác vụ khác (hàng đợi báo thứ tự khi người trước xong)."""
    sink = progress_sink.get()
    return sink if sink is not None else (lambda item: None)


def answer_streamer(provider) -> dict:
    """Không phát draft answer chưa kiểm chứng; chỉ stream progress, trả lời bằng done.run."""
    return {}


_running: set[asyncio.Task] = set()  # giữ tham chiếu: người dùng đóng trang thì lượt chạy vẫn chạy xong và được lưu


async def ndjson_run(run_factory: Callable[[], Awaitable[Any]]) -> AsyncIterator[str]:
    """Chỉ gửi tiến độ; chặn mọi draft answer trước final validation."""
    queue: asyncio.Queue = asyncio.Queue()

    def safe_emit(item: dict) -> None:
        # Defense in depth: some provider/caller may emit answer directly.
        if item.get("type") != "answer":
            queue.put_nowait(item)

    async def work() -> None:
        progress_sink.set(safe_emit)
        try:
            queue.put_nowait({"type": "done", "run": await run_factory()})
        except Exception as exc:  # HTTPException mang status_code/detail; lỗi khác báo 500 thay vì cắt luồng im lặng
            status = int(getattr(exc, "status_code", 500))
            if status >= 500:
                logging.getLogger(__name__).exception("chat stream failed")
            queue.put_nowait({"type": "error", "status": status, "detail": getattr(exc, "detail", None) or type(exc).__name__})
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(work())
    _running.add(task)
    task.add_done_callback(_running.discard)
    while (item := await queue.get()) is not None:
        yield json.dumps(item, ensure_ascii=False, default=str) + "\n"
