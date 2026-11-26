"""Bộ test hồi quy Gói 1 (25/11/2026): kiểm chứng SEC-02, FQ-02/FQ-01, AI-GUARD-01,
OBS-W3-P82-01, OBS-B93-01, VAL-01..06, lời chào mở rộng.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pydantic import ValidationError

from app.api.analysis import ReportBody, ReportUpdate
from app.api.org import DepartmentBody, SpaceBody, SpaceUpdate
from app.api.studio import WorkspaceBody
from app.core.types import SourceChunk, TaskResult
from app.research.pipeline import (
    LLMBudgetExceededError,
    ResearchPipeline,
    _BudgetedProvider,
    _partial_failure_answer,
)
from app.research.product_intents import product_help_response
from app.research.run_queue import FairQueue
from app.storage.postgres.runtime import _skill_card_source_ids


def test_fq02_failing_callback_never_deadlocks_queue():
    async def _run():
        q = FairQueue(limit=1)
        tok1 = await q.acquire()

        def bad_cb(_pos: int):
            raise RuntimeError("client disconnected")

        # Người 2 xếp hàng với callback lỗi -> không được crash hay để lại ghost waiter
        t2 = asyncio.create_task(q.acquire(on_position=bad_cb))
        await asyncio.sleep(0.03)
        q.release(tok1)
        tok2 = await asyncio.wait_for(t2, timeout=0.5)
        q.release(tok2)

        # Người 3 lấy chỗ bình thường
        tok3 = await asyncio.wait_for(q.acquire(), timeout=0.5)
        assert q.active == 1
        q.release(tok3)
        assert q.active == 0

    asyncio.run(_run())


def test_fq01_double_release_token_guard():
    async def _run():
        q = FairQueue(limit=2)
        tok1 = await q.acquire()
        tok2 = await q.acquire()
        assert q.active == 2
        q.release(tok1)
        q.release(tok1)  # double release cùng token phải bị bỏ qua
        assert q.active == 1
        q.release(tok2)
        assert q.active == 0

    asyncio.run(_run())


def test_sec02_skill_card_source_id_extraction():
    card = {
        "kind": "profile",
        "source_id": "src_aabbcc1122",
        "evidence": [{"chunk_id": "src_ddeeff3344_c0003"}],
        "nested": {"old_source_id": "src_1122334455", "citations": ["src_9988776655_c0000"]},
    }
    msg = "Tóm tắt\n\n<!--skill-card:" + json.dumps(card, ensure_ascii=False) + "-->"
    refs = _skill_card_source_ids(msg)
    assert {"src_aabbcc1122", "src_ddeeff3344", "src_1122334455", "src_9988776655"} <= refs


def test_ai_guard01_budgeted_provider_caps_calls():
    class DummyProvider:
        name = "dummy"
        model = "dummy-1"

        async def generate(self, *args, **kwargs):
            return {"text": "ok"}

    async def _run():
        bp = _BudgetedProvider(DummyProvider(), max_calls=2)
        assert await bp.generate("a") == {"text": "ok"}
        assert await bp.generate("b") == {"text": "ok"}
        with pytest.raises(LLMBudgetExceededError):
            await bp.generate("c")

    asyncio.run(_run())


def test_obs_w3_p82_01_partial_failure_answer_hides_raw_exception():
    t1 = TaskResult(task_id="T1", domain="policy", status="COMPLETE", answer="Thời hạn báo cáo là 72 giờ.")
    msg = _partial_failure_answer([t1], timed_out=False)
    assert "72 giờ" in msg
    assert "RuntimeError" not in msg
    assert "Pipeline failed" not in msg

    empty_msg = _partial_failure_answer([], timed_out=True)
    assert "quá thời gian" in empty_msg
    assert "Traceback" not in empty_msg


def test_val_01_03_04_06_reject_whitespace_only():
    with pytest.raises(ValidationError):
        WorkspaceBody(name="   ")
    with pytest.raises(ValidationError):
        ReportBody(kind="doc_profile", title="   ", payload={})
    with pytest.raises(ValidationError):
        ReportUpdate(title="   ", payload={})
    with pytest.raises(ValidationError):
        SpaceBody(name="   ")
    with pytest.raises(ValidationError):
        SpaceUpdate(name="   ")
    with pytest.raises(ValidationError):
        DepartmentBody(name="   ")


def test_product_greeting_handles_combined_intro_questions():
    res = product_help_response("Xin chào, bạn là ai và giúp được gì?")
    assert res is not None
    intent, answer = res
    assert intent == "identity"
    assert "OrchestrIQ Studio" in answer
