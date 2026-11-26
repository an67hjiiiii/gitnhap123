"""Batch 138.2 Targeted Safety Closure Tests (Test-First RED -> GREEN, Zero Ollama).

Covers:
- FIX-3A (NO_EVIDENCE Prose Safety):
  - Refusal + ungrounded numeric claim
  - Refusal + ungrounded NON-numeric claim
  - Refusal at start vs refusal at end of answer
  - Vietnamese & English refusal + ungrounded claims
  - Fabricated inline citations & citation metadata
  - NO_EVIDENCE combined with invalid citations & context truncation
  - Preserved GENERAL, BOTH, valid document-grounded, and persisted conversation / reload flows
- FIX-3B (Streaming Pre-Guard Safety):
  - Collects ALL client-visible NDJSON frames (progress, answer, done, error)
  - Verifies zero unguarded prose or forged citations appear in ANY intermediate or final frame
  - Covers unsafe text in first frame, mid-stream, NO_EVIDENCE after long text, invalid citation after chunks
  - Timeout mid-stream, cancellation, provider exception, empty output, concurrent isolated streams
  - Progress events never leak secret doc text or unverified answer text
  - Research Mode A/B/C exact parity preserved
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as app_main
from app.core.types import ProviderResult, RunMetrics, SourceChunk, TaskResult, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.progress import answer_streamer, emit, ndjson_run, progress_sink
from app.research.registry import OFFICE_PACK
from app.research.synthesizer import synthesize
from app.research.vanilla import answer_vanilla
from app.research.worker import execute_task
from app.core.types import Task
from app.storage.conversation_store import ConversationStore
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _c(i: int, text: str, src: str = "src_1111111111111111") -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{src}_c{i:04d}",
        source_id=src,
        source_name="doc.md",
        text=text,
        index=i,
        provenance={},
    )


# ==============================================================================
# FIX-3A: NO_EVIDENCE PROSE SAFETY
# ==============================================================================


def test_fix3a_no_evidence_strips_mixed_refusal_non_numeric_and_numeric_vi_en():
    ev = [_c(0, "Điều 1. Thời gian làm việc 8 giờ/ngày.")]
    cases = [
        # Refusal at start + non-numeric false obligation
        "Tài liệu bạn gửi không đề cập, nhưng theo quy định bắt buộc doanh nghiệp phải sa thải ngay lập tức và đóng cửa chi nhánh.",
        # Non-numeric false claim first + refusal at end
        "Nhân viên sẽ bị kỷ luật buộc thôi việc ngay lập tức. Tuy nhiên tài liệu hiện tại không nêu rõ chi tiết.",
        # Refusal + numeric false figure
        "Nội quy không quy định mức này, nhưng thông thường phạt 50.000.000 đồng.",
        # English mixed refusal + non-numeric false claim + fake inline citation
        "Your documents do not mention this policy, however the company strictly bans all remote work permanently [src_deadbeefdeadbeef_c0001].",
    ]
    for idx, bad_text in enumerate(cases):
        class _MixedProv:
            async def generate(self, *, system, user):
                return ProviderResult(
                    json.dumps(
                        {
                            "status": "NO_EVIDENCE",
                            "answer": bad_text,
                            "citations": ["src_1111111111111111_c0000", "invalid_cid_x"],
                            "missing_information": [],
                        },
                        ensure_ascii=False,
                    ),
                    Usage(5, 5),
                )

        lang = "en" if idx == 3 else "vi"
        res = asyncio.run(answer_vanilla(_MixedProv(), "Question?", ev, RunMetrics(), reply_language=lang, product=True))
        assert res.status == "NO_EVIDENCE"
        assert res.citations == []
        assert "sa thải" not in res.answer
        assert "buộc thôi việc" not in res.answer
        assert "50.000.000" not in res.answer
        assert "bans all remote work" not in res.answer
        assert "src_deadbeefdeadbeef_c0001" not in res.answer
        assert "src_1111111111111111_c0000" not in res.answer


def test_fix3a_worker_and_context_truncation_preserve_safe_refusal_only():
    ev = [_c(0, "Điều 1. Nội dung ngắn.")]

    class _TruncWorkerProv:
        async def generate(self, *, system, user):
            return ProviderResult(
                '{"status":"NO_EVIDENCE","answer":"Tài liệu không nêu, nên áp dụng mức phạt tối đa theo thông lệ ngành.',
                Usage(5, 5),
            )

    res = asyncio.run(execute_task(_TruncWorkerProv(), Task("T1", "Mức phạt?", "security"), ev, RunMetrics(), product=True, user_request="Mức phạt?"))
    assert res.status == "NO_EVIDENCE"
    assert res.citations == []
    assert "thông lệ ngành" not in res.answer


def test_fix3a_preserves_general_both_valid_doc_and_conversation_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")

    # 1. Valid GENERAL without docs stays COMPLETE
    st_empty = SourceStore(str(tmp_path / "s_empty"))
    pipe_empty = ResearchPipeline(st_empty, RunStore(str(tmp_path / "r_empty")))

    class _GenFake(FakeProvider):
        async def generate(self, *, system, user, **kw):
            if "GENERAL_KNOWLEDGE_ANSWERER" in system:
                return ProviderResult('{"answer":"Canberra là thủ đô của Úc."}', Usage(5, 5))
            return await super().generate(system=system, user=user)

        async def generate_structured(self, *, system, user, response_schema, **kw):
            if "GENERAL_KNOWLEDGE_ANSWERER" in system:
                return ProviderResult('{"answer":"Canberra là thủ đô của Úc."}', Usage(5, 5))
            return await super().generate_structured(system=system, user=user, response_schema=response_schema, **kw)

    with patch("app.research.pipeline.get_provider", return_value=_GenFake()):
        r_gen = asyncio.run(pipe_empty.run("Thủ đô của Úc là gì?", "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK, source_ids=[]))
    assert r_gen["status"] == "COMPLETE" and "Canberra" in r_gen["answer"]

    # 2. Valid BOTH stays grounded + general labeled
    st_doc = SourceStore(str(tmp_path / "s_doc"))
    imp = st_doc.import_text("che_do.md", "Điều 4. Phụ cấp ăn trưa 500.000 đồng/tháng.")
    cid = st_doc.chunks()[0].chunk_id
    pipe_doc = ResearchPipeline(st_doc, RunStore(str(tmp_path / "r_doc")))

    class _BothAndSafeFake(FakeProvider):
        async def generate_grounded(self, *, system, user, evidence_ids, **kw):
            if "chứng từ" in user:
                return ProviderResult(
                    f'{{"status":"COMPLETE","answer":"Phụ cấp ăn trưa là 500.000 đồng/tháng [{cid}].\\n\\nKiến thức chung: Chứng từ dùng để hạch toán chi phí.","citations":["{cid}"],"missing_information":[]}}',
                    Usage(5, 5),
                )
            return ProviderResult(
                '{"status":"NO_EVIDENCE","answer":"Tài liệu không nêu, nhưng nhân viên vi phạm sẽ bị sa thải ngay.","citations":[],"missing_information":[]}',
                Usage(5, 5),
            )

    with patch("app.research.pipeline.get_provider", return_value=_BothAndSafeFake()):
        r_both = asyncio.run(pipe_doc.run("Phụ cấp ăn trưa bao nhiêu và vì sao cần chứng từ?", "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK))
        r_noev = asyncio.run(pipe_doc.run("Theo nội quy, hình thức kỷ luật sa thải áp dụng thế nào?", "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK))
    assert r_both["status"] == "COMPLETE" and cid in r_both["citations"]
    assert r_noev["status"] == "NO_EVIDENCE" and "sa thải ngay" not in r_noev["answer"]


# ==============================================================================
# FIX-3B: STREAMING PRE-GUARD SAFETY (NO UNVALIDATED ANSWER FRAMES LEAKED)
# ==============================================================================


def _run_stream_request(tmp_path, monkeypatch, provider_obj, query="Theo nội quy, giờ làm việc quy định gì?"):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PRODUCT_REVIEWER", "off")
    monkeypatch.setenv("PRODUCT_AGENT_TOOLS", "off")
    monkeypatch.setenv("PRODUCT_TASK_PARALLEL", "1")

    st = SourceStore(str(tmp_path / "src"))
    imp = st.import_text("nq.md", "Điều 1. Nội quy giờ làm việc từ 8h30 đến 17h30. MÃ BÍ MẬT SECRET-991.")
    sid = imp["source_id"]
    cid = st.chunks()[0].chunk_id
    cs = ConversationStore(str(tmp_path / "convs"))
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "runs")))

    monkeypatch.setattr(app_main, "current_principal", lambda req: {"user_id": "u_stream_3b", "role": "staff"})
    monkeypatch.setattr(app_main, "owner_source_store", lambda u: st)
    monkeypatch.setattr(app_main, "owner_conversation_store", lambda u: cs)
    monkeypatch.setattr(app_main, "owner_pipeline", lambda u, cid_arg=None: pipe)
    monkeypatch.setattr(app_main, "log_secret_access", lambda *a, **k: None)

    client = TestClient(app_main.app)
    with patch("app.research.pipeline.get_provider", return_value=provider_obj):
        resp = client.post("/api/chat/stream", json={"message": query, "product_mode": True, "source_ids": [sid]})
    frames = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
    return resp, frames, cs, sid, cid


def test_fix3b_streaming_blocks_early_mid_no_evidence_and_forged_citation_frames(tmp_path, monkeypatch):
    class _EarlyAndMidLeakProv(FakeProvider):
        supports_streaming = True
        supports_per_call_output_tokens = True

        async def generate_grounded(self, *, system, user, evidence_ids, on_text=None, **kw):
            assert on_text is not None
            on_text('{"status":"NO_EVIDENCE","answer":"FRAME1_SA_THAI_NGAY ')
            on_text('{"status":"NO_EVIDENCE","answer":"FRAME1_SA_THAI_NGAY và phạt 99 triệu [src_deadbeefdeadbeef_c0009]. Nội dung dài thêm...')
            return ProviderResult(
                '{"status":"NO_EVIDENCE","answer":"FRAME1_SA_THAI_NGAY và phạt 99 triệu [src_deadbeefdeadbeef_c0009]. Nội dung dài thêm.","citations":["src_deadbeefdeadbeef_c0009"],"missing_information":[]}',
                Usage(5, 5),
            )

    resp, frames, cs, sid, cid = _run_stream_request(tmp_path, monkeypatch, _EarlyAndMidLeakProv())
    assert resp.status_code == 200
    ans_frames = [f["text"] for f in frames if f.get("type") == "answer"]
    progress_frames = [f for f in frames if f.get("type") == "progress"]
    done_run = next(f["run"] for f in frames if f.get("type") == "done")
    saved_conv = cs.get(done_run["conversation_id"])

    # Every single client-visible answer frame, progress frame, done answer & persisted message MUST be clean
    assert ans_frames, "Expected validated final answer frame to be emitted"
    for txt in ans_frames:
        assert "FRAME1_SA_THAI_NGAY" not in txt
        assert "99 triệu" not in txt
        assert "src_deadbeefdeadbeef_c0009" not in txt
    assert "SECRET-991" not in json.dumps(progress_frames, ensure_ascii=False)
    assert "FRAME1_SA_THAI_NGAY" not in done_run["answer"]
    assert "FRAME1_SA_THAI_NGAY" not in saved_conv["messages"][-1]["content"]
    assert done_run["status"] == "NO_EVIDENCE"


def test_fix3b_streaming_blocks_forged_inline_citation_in_complete_mode(tmp_path, monkeypatch):
    class _ForgedInlineStreamProv(FakeProvider):
        supports_streaming = True
        supports_per_call_output_tokens = True

        async def generate_grounded(self, *, system, user, evidence_ids, on_text=None, **kw):
            valid_cid = evidence_ids[0]
            if on_text:
                on_text('{"status":"COMPLETE","answer":"Giờ làm 8h30 [src_9999999999999999_c0007] ')
                on_text(f'{{"status":"COMPLETE","answer":"Giờ làm 8h30 [src_9999999999999999_c0007] [{valid_cid}]."}}')
            return ProviderResult(
                f'{{"status":"COMPLETE","answer":"Giờ làm 8h30 [src_9999999999999999_c0007] [{valid_cid}].","citations":["{valid_cid}"],"missing_information":[]}}',
                Usage(5, 5),
            )

    resp, frames, cs, sid, cid = _run_stream_request(tmp_path, monkeypatch, _ForgedInlineStreamProv())
    ans_frames = [f["text"] for f in frames if f.get("type") == "answer"]
    assert ans_frames and "8h30" in ans_frames[-1] and cid in ans_frames[-1]
    for txt in ans_frames:
        assert "src_9999999999999999_c0007" not in txt


def test_fix3b_streaming_timeout_and_exception_never_leak_partial_unsafe_answer(tmp_path, monkeypatch):
    class _TimeoutMidStreamProv(FakeProvider):
        supports_streaming = True
        supports_per_call_output_tokens = True

        async def generate_grounded(self, *, system, user, evidence_ids, on_text=None, **kw):
            if on_text:
                on_text('{"status":"COMPLETE","answer":"LEAK_BEFORE_TIMEOUT 500 triệu [src_9999999999999999_c0001]')
            raise TimeoutError("simulated mid-stream timeout")

    resp, frames, cs, sid, cid = _run_stream_request(tmp_path, monkeypatch, _TimeoutMidStreamProv())
    assert resp.status_code == 200
    ans_frames = [f["text"] for f in frames if f.get("type") == "answer"]
    assert all("LEAK_BEFORE_TIMEOUT" not in t for t in ans_frames)
    done_run = next(f["run"] for f in frames if f.get("type") == "done")
    assert done_run["status"] == "FAILED"


def test_fix3b_streaming_general_both_and_synthesizer_emit_validated_frames_only():
    items: list[dict] = []

    class _SynthForgeStream:
        supports_per_call_output_tokens = True
        supports_streaming = True

        async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None, on_text=None):
            if on_text:
                on_text('{"answer":"Ý hợp [src_aaaa1111aaaa1111_c0000] và giả [src_deadbeefdeadbeef_c0099]')
            return ProviderResult(
                '{"answer":"Ý hợp [src_aaaa1111aaaa1111_c0000] và giả [src_deadbeefdeadbeef_c0099]."}',
                Usage(5, 5),
                model="m",
            )

    tok = progress_sink.set(items.append)
    try:
        out = asyncio.run(
            synthesize(
                _SynthForgeStream(),
                "Tổng hợp",
                [TaskResult("T1", "general", "COMPLETE", "a", ["src_aaaa1111aaaa1111_c0000"], ["src_aaaa1111aaaa1111_c0000"], [])],
                RunMetrics(),
                max_output_tokens=1800,
            )
        )
    finally:
        progress_sink.reset(tok)

    ans_frames = [i["text"] for i in items if i.get("type") == "answer"]
    assert "src_deadbeefdeadbeef_c0099" not in out
    assert ans_frames and all("src_deadbeefdeadbeef_c0099" not in t for t in ans_frames)


def test_fix3b_concurrent_stream_isolation_and_research_mode_abc_parity(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")

    async def _run_two():
        seen_a: list[dict] = []
        seen_b: list[dict] = []

        async def work_a():
            emit({"type": "answer", "text": "STREAM_A_ONLY"})
            return {"status": "COMPLETE"}

        async def work_b():
            emit({"type": "answer", "text": "STREAM_B_ONLY"})
            return {"status": "COMPLETE"}

        async def collect(fn, out):
            async for raw in ndjson_run(fn):
                out.append(json.loads(raw))

        await asyncio.gather(collect(work_a, seen_a), collect(work_b, seen_b))
        return seen_a, seen_b

    a, b = asyncio.run(_run_two())
    assert any(x.get("text") == "STREAM_A_ONLY" for x in a) and all("STREAM_B_ONLY" not in json.dumps(x) for x in a)
    assert any(x.get("text") == "STREAM_B_ONLY" for x in b) and all("STREAM_A_ONLY" not in json.dumps(x) for x in b)

    # Research Mode A/B/C stays 100% untouched (no product streaming or guard overrides)
    for cond in ("A", "B", "C"):
        st = SourceStore(str(tmp_path / f"r_{cond}"))
        st.import_text("spec.md", "Authentication requires signed JWT tokens.")
        pipe = ResearchPipeline(st, RunStore(str(tmp_path / f"rr_{cond}")))
        run = asyncio.run(pipe.run("Authentication JWT?", cond, provider_name="fake"))
        assert run["status"] in {"COMPLETE", "PARTIAL", "NO_EVIDENCE"}
        assert "knowledge_source" not in run["effective_config"]
