"""Nhiệm vụ phụ thuộc nhận kết quả nhiệm vụ trước trong lời nhắc; nhiệm vụ độc lập thì không."""
import asyncio
from types import SimpleNamespace

from app.core.types import RunMetrics, SourceChunk, Task, TaskResult, Usage
from app.research.worker import execute_task

EV = [SourceChunk("s_c0", "s", "a.md", "Bảng payments có cột amount BIGINT.", 0)]


class Spy:
    def __init__(self):
        self.user = ""

    async def generate(self, *, system, user):
        self.user = user
        return SimpleNamespace(text='{"status":"COMPLETE","answer":"ok","citations":["s_c0"],"missing_information":[]}', usage=Usage(1, 1))


def test_upstream_results_are_in_prompt_only_when_given():
    spy = Spy()
    up = TaskResult("t1", "database", "COMPLETE", "Bảng payments dùng BIGINT cho amount.")
    asyncio.run(execute_task(spy, Task("t2", "Thiết kế API tạo đơn", "api_architecture", ["t1"]), EV, RunMetrics(), upstream=[up]))
    assert "[UPSTREAM]" in spy.user and "Bảng payments dùng BIGINT" in spy.user and spy.user.index("[UPSTREAM]") < spy.user.index("[EVIDENCE]")
    asyncio.run(execute_task(spy, Task("t3", "Thiết kế API", "api_architecture"), EV, RunMetrics()))
    assert "[UPSTREAM]" not in spy.user
