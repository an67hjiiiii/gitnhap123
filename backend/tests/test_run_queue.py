"""Đợt 9: nhiều người hỏi cùng lúc thì xếp hàng theo thứ tự, có báo thứ tự chờ, không ai bị kẹt khi có lỗi hoặc bỏ đi."""
import asyncio

import pytest

from app.research.run_queue import FairQueue


def test_fifo_order_and_positions_reported():
    async def go():
        q = FairQueue(1)
        order: list[str] = []
        positions: dict[str, list[int]] = {"b": [], "c": []}
        gate = asyncio.Event()

        async def user(name, hold=None):
            async with q.slot(positions[name].append if name in positions else None):
                order.append(name)
                if hold:
                    await hold.wait()

        a = asyncio.create_task(user("a", gate))
        await asyncio.sleep(0)
        b = asyncio.create_task(user("b"))
        await asyncio.sleep(0)
        c = asyncio.create_task(user("c"))
        await asyncio.sleep(0)
        assert q.active == 1 and q.waiting == 2
        gate.set()
        await asyncio.gather(a, b, c)
        return order, positions, q

    order, positions, q = asyncio.run(go())
    assert order == ["a", "b", "c"]
    assert positions["b"][0] == 1 and positions["c"][:2] == [2, 1]  # c lên thứ 1 khi b vào chạy
    assert q.active == 0 and q.waiting == 0


def test_error_inside_slot_releases_it():
    async def go():
        q = FairQueue(1)

        async def boom():
            async with q.slot():
                raise RuntimeError("model down")

        with pytest.raises(RuntimeError):
            await boom()
        async with q.slot():
            return q.active

    assert asyncio.run(go()) == 1


def test_leaving_the_queue_moves_others_up():
    async def go():
        q = FairQueue(1)
        gate = asyncio.Event()
        seen: list[int] = []

        async def hold():
            async with q.slot():
                await gate.wait()

        async def wait(cb=None):
            async with q.slot(cb):
                pass

        a = asyncio.create_task(hold())
        await asyncio.sleep(0)
        b = asyncio.create_task(wait())
        await asyncio.sleep(0)
        c = asyncio.create_task(wait(seen.append))
        await asyncio.sleep(0)
        b.cancel()  # người dùng đóng trang khi đang chờ
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(a, c, return_exceptions=True)
        return seen, q

    seen, q = asyncio.run(go())
    assert seen == [2, 1] and q.active == 0 and q.waiting == 0


def test_limit_allows_parallel_runs():
    async def go():
        q = FairQueue(2)
        await q.acquire()
        await q.acquire()
        return q.active, q.waiting

    assert asyncio.run(go()) == (2, 0)


def test_queue_positions_go_to_the_waiting_users_own_stream():
    """Chạy thật 19/11: lời báo thứ tự lọt vào luồng của người vừa chạy xong (emit đọc ngữ cảnh của bên gọi)."""
    from app.research.progress import bound_emit, progress_sink

    async def go():
        q = FairQueue(1)
        gate = asyncio.Event()
        got = {"a": [], "b": [], "c": []}

        async def user(name, hold=None):
            progress_sink.set(got[name].append)
            say = bound_emit()
            async with q.slot(lambda n: say({"type": "queue", "position": n})):
                if hold:
                    await hold.wait()

        a = asyncio.create_task(user("a", gate))
        await asyncio.sleep(0)
        b = asyncio.create_task(user("b"))
        await asyncio.sleep(0)
        c = asyncio.create_task(user("c"))
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(a, b, c)
        return got

    got = asyncio.run(go())
    assert got["a"] == []  # người đầu không phải chờ, không nhận lời báo của ai
    assert [x["position"] for x in got["b"]] == [1, 1]  # lúc vào hàng, và lúc c vào hàng sau (vẫn thứ 1)
    assert [x["position"] for x in got["c"]] == [2, 1]  # lên thứ 1 khi a xong, lời báo vào luồng của c
