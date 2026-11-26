"""Batch 137.1 Independent Review Hardening Tests (Test-First RED -> GREEN, Zero Ollama).

Covers:
- FIX-01: NO_EVIDENCE output safety (affirmative claim suppression, inline citation removal,
          invalid/truncated status lock on NO_EVIDENCE, GENERAL/BOTH preservation, streaming + persistence).
- FIX-02: Statutory routing precision (Groups A/B/C in VI accented, VI unaccented, EN).
- FIX-03: Citation integrity (dropped-task citation exclusion, NO_EVIDENCE evidence_ids exclusion,
          inline forged/unauthorized citation stripping, question-number/article leak prevention,
          honest unmapped-citation disclosure without fake claim-level grounding claim).
- FIX-04: Research Mode A/B/C exact parity vs pre-B137 behavior (`product_mode=False`).
- FIX-05: Chunk continuation boundary (3-4 chunk chain, out-of-order retrieval fix, stop at new article,
          cross-source/ACL isolation, token budget compliance).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.types import ProviderResult, RunMetrics, SourceChunk, Task, TaskResult, Usage
from app.main import app
from app.providers.fake import FakeProvider
from app.research.knowledge_source import BOTH, DOCUMENTS, GENERAL, choose_source, doc_bound
from app.research.pipeline import ResearchPipeline
from app.research.registry import OFFICE_PACK, use_pack
from app.research.synthesizer import synthesize
from app.research.vanilla import answer_vanilla
from app.research.worker import execute_task
from app.retrieval.hybrid import continue_articles
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _c(i: int, text: str, src: str = "src_1111111111111111", name: str = "doc.md") -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{src}_c{i:04d}",
        source_id=src,
        source_name=name,
        text=text,
        index=i,
        provenance={},
    )


# ==============================================================================
# FIX-01: NO_EVIDENCE OUTPUT SAFETY
# ==============================================================================


def test_fix01_vanilla_no_evidence_strips_affirmative_claims_inline_cites_and_locks_status():
    ev = [_c(0, "Điều 1. Quy định chung về nghỉ phép.", "src_aaaa1111aaaa1111")]

    class _UnsafeNoEv:
        async def generate(self, *, system, user):
            return ProviderResult(
                '{"status":"NO_EVIDENCE","answer":"Mức phạt chậm báo cáo là 50.000.000 đồng [src_aaaa1111aaaa1111_c0000].","citations":["src_deadbeefdeadbeef_c0009"],"missing_information":[]}',
                Usage(5, 5),
            )

    res = asyncio.run(answer_vanilla(_UnsafeNoEv(), "Mức phạt chậm báo cáo là bao nhiêu?", ev, RunMetrics(), product=True))
    assert res.status == "NO_EVIDENCE"
    assert res.citations == []
    assert "50.000.000" not in res.answer
    assert "src_aaaa1111aaaa1111_c0000" not in res.answer
    assert "src_deadbeefdeadbeef_c0009" not in res.answer


def test_fix01_worker_no_evidence_strips_affirmative_claims_and_locks_status_with_invalid_cites():
    ev = [_c(0, "Khoản 2. Thời hạn lưu trữ hồ sơ.", "src_bbbb2222bbbb2222")]
    task = Task("T1", "Mức phạt vi phạm?", "general")

    class _UnsafeWorker:
        async def generate(self, *, system, user):
            return ProviderResult(
                '{"status":"NO_EVIDENCE","answer":"Doanh nghiệp bị phạt 100.000.000 đồng theo [src_bbbb2222bbbb2222_c0000].","citations":["fake_bad_cid"],"missing_information":[]}',
                Usage(5, 5),
            )

    with use_pack(OFFICE_PACK):
        res = asyncio.run(execute_task(_UnsafeWorker(), task, ev, RunMetrics(), product=True, user_request="Mức phạt vi phạm?"))
    assert res.status == "NO_EVIDENCE"
    assert res.citations == []
    assert "100.000.000" not in res.answer
    assert "src_bbbb2222bbbb2222_c0000" not in res.answer


def test_fix01_stream_and_persisted_conversation_contain_safe_no_evidence_output(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("ALLOW_HEADER_AUTH", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    # Use direct FastAPI TestClient on file backend after setting up an owner doc
    from app import main as app_main

    store = SourceStore(str(tmp_path / "src"))
    imp = store.import_text("nq.md", "Điều 1. Thời gian làm việc 8 giờ/ngày.")
    sid = imp["source_id"]

    class _StreamUnsafeFake(FakeProvider):
        supports_streaming = True

        async def generate_grounded(self, *, system, user, evidence_ids, on_text=None, **kw):
            if on_text:
                on_text('{"status":"NO_EVIDENCE","answer":"Bịa 99 triệu [')
            return ProviderResult(
                f'{{"status":"NO_EVIDENCE","answer":"Theo tài liệu, phạt 99 triệu [{sid}_c0000].","citations":["fake_bad"],"missing_information":[]}}',
                Usage(5, 5),
            )

    conv_store_path = tmp_path / "convs"
    from app.storage.conversation_store import ConversationStore
    cstore = ConversationStore(str(conv_store_path))
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))

    monkeypatch.setattr(app_main, "current_principal", lambda req: {"user_id": "u_stream_qa", "role": "staff"})
    monkeypatch.setattr(app_main, "owner_source_store", lambda u: store)
    monkeypatch.setattr(app_main, "owner_conversation_store", lambda u: cstore)
    monkeypatch.setattr(app_main, "owner_pipeline", lambda u, cid=None: pipe)
    monkeypatch.setattr(app_main, "log_secret_access", lambda *a, **k: None)

    client = TestClient(app)
    with patch("app.research.pipeline.get_provider", return_value=_StreamUnsafeFake()):
        resp = client.post(
            "/api/chat/stream",
            json={"message": "Theo nội quy, mức phạt là bao nhiêu?", "product_mode": True, "source_ids": [sid]},
        )
    assert resp.status_code == 200
    import json as _json
    lines = [_json.loads(line) for line in resp.text.splitlines() if line.strip()]
    answer_frames = [x["text"] for x in lines if x.get("type") == "answer"]
    done_frame = next(x["run"] for x in lines if x.get("type") == "done")
    assert done_frame["status"] == "NO_EVIDENCE"
    assert done_frame["citations"] == []
    assert "99 triệu" not in done_frame["answer"]
    assert f"{sid}_c0000" not in done_frame["answer"]
    assert answer_frames and "99 triệu" not in answer_frames[-1]
    saved_conv = cstore.get(done_frame["conversation_id"])
    assistant_msgs = [m for m in saved_conv["messages"] if m["role"] == "ASSISTANT"]
    assert assistant_msgs and "99 triệu" not in assistant_msgs[-1]["content"]


# ==============================================================================
# FIX-02: STATUTORY ROUTING PRECISION (A vs B vs C; VI accented, unaccented, EN)
# ==============================================================================


def test_fix02_statutory_precision_separates_a_b_c_multilingual():
    # Group A (concrete statutory/doc-bound queries -> MUST be True):
    group_a = [
        "Nghị định 99/2026 quy định mức phạt hành chính về dữ liệu là bao nhiêu?",
        "Nghi dinh 13/2023 quy dinh thoi han thong bao vi pham bao nhieu gio?",
        "Theo Thông tư 08/2021/TT-BGDĐT, điều kiện xét tốt nghiệp là gì?",
        "Theo Thong tu 08, sinh vien bi canh bao hoc tap khi nao?",
        "Luật Giao dịch điện tử 2023 quy định chữ ký điện tử gồm mấy loại?",
        "Điều 14 Luật Giao dịch điện tử quy định gì về thông điệp dữ liệu?",
        "Theo Quyết định số 12/2025, ai có thẩm quyền phê duyệt?",
        "According to Decree 13/2023, what is sensitive personal data?",
        "In Article 22 of Law 20/2023, how are digital signatures classified?",
    ]
    for q in group_a:
        assert doc_bound(q) is True, f"Expected Group A statutory query to be doc_bound: {q}"

    # Group B (general legal concepts -> MUST be False):
    group_b = [
        "Thông tư là gì?",
        "Thong tu la gi?",
        "Nghị định là gì và do ai ban hành?",
        "Nghi dinh la gi?",
        "What is a decree or circular?",
        "Giải thích khái niệm hợp đồng thương mại?",
    ]
    for q in group_b:
        assert doc_bound(q) is False, f"Expected Group B general legal concept NOT doc_bound: {q}"

    # Group C (business/technical overlap phrasing -> MUST be False):
    group_c = [
        "Làm sao để ra quyết định mua máy chủ?",
        "Lam sao de ra quyet dinh mua may chu?",
        "Giải thích quyết định thiết kế hệ thống?",
        "Giai thich quyet dinh thiet ke he thong?",
        "How should our team make a database architecture decision?",
        "Cách đưa ra quyết định chọn công nghệ cho startup?",
    ]
    for q in group_c:
        assert doc_bound(q) is False, f"Expected Group C technical/business overlap NOT doc_bound: {q}"


# ==============================================================================
# FIX-03: CITATION INTEGRITY & CLAIM-GROUNDING BOUNDARY
# ==============================================================================


def test_fix03_synthesizer_excludes_dropped_task_and_no_evidence_allowed_cids(monkeypatch):
    monkeypatch.setenv("PRODUCT_NUM_CTX", "1024")
    monkeypatch.setenv("OLLAMA_MAX_NUM_CTX", "4096")
    c_kept = "src_aaaa1111aaaa1111_c0000"
    c_dropped = "src_bbbb2222bbbb2222_c0001"
    c_noev_only = "src_cccc3333cccc3333_c0002"

    class _LeakProbeSynth:
        supports_per_call_output_tokens = True
        supports_num_ctx = True

        async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None, num_ctx=None, **kw):
            # Model tries to inline-cite a NO_EVIDENCE task's evidence_id and a dropped task's chunk
            return ProviderResult(
                f'{{"answer":"Phần giữ lại [{c_kept}]. Rò rỉ từ NO_EVIDENCE [{c_noev_only}] và task bị cắt [{c_dropped}]."}}',
                Usage(10, 10),
                model="m",
            )

    long_a = "Nội dung chi tiết quy trình nghiệm thu thiết bị và kiểm tra chất lượng phần mềm. " * 25
    results = [
        TaskResult("T1", "general", "COMPLETE", "Tóm tắt ngắn gọn phần 1.", [c_kept], [c_kept], []),
        TaskResult("T_NOEV", "general", "NO_EVIDENCE", "Không thấy bằng chứng.", [c_noev_only], [], []),
        TaskResult("T2_DROP", "general", "COMPLETE", long_a, [c_dropped], [c_dropped], []),
    ]
    meta: dict = {}
    out = asyncio.run(
        synthesize(_LeakProbeSynth(), "Tổng hợp", results, RunMetrics(), max_output_tokens=200, num_ctx=1024, synth_meta=meta)
    )
    assert c_kept in out
    assert c_noev_only not in out, "NO_EVIDENCE evidence_ids must never survive as citations in final output"
    assert c_dropped not in out, "Dropped task citations must not be appended when task content was trimmed"
    assert c_noev_only in (meta.get("invalid_inline_citations") or [])
    assert c_dropped in (meta.get("invalid_inline_citations") or [])


def test_fix03_vanilla_and_worker_strip_unauthorized_inline_citations_and_flag_query_numbers():
    ev = [_c(0, "Khoản 2 quy định phụ cấp đi lại 300.000 đồng.", "src_1111111111111111")]
    unauth_cid = "src_9999999999999999_c0004"

    class _InlineLeakProv:
        async def generate(self, *, system, user):
            return ProviderResult(
                f'{{"status":"COMPLETE","answer":"Theo Điều 9 từ câu hỏi, phụ cấp 300.000 đồng và thưởng 888.000 đồng [{unauth_cid}].","citations":["src_1111111111111111_c0000"],"missing_information":[]}}',
                Usage(5, 5),
            )

    res_v = asyncio.run(
        answer_vanilla(
            _InlineLeakProv(),
            "Theo Điều 9, thưởng 888.000 đồng đúng không?",
            ev,
            RunMetrics(),
            product=True,
        )
    )
    assert unauth_cid not in res_v.answer
    assert res_v.status == "PARTIAL"
    assert "Lưu ý căn cứ" in res_v.answer
    assert "Cần kiểm tra lại" in res_v.answer
    assert any("unauthorized or unprompted inline" in m for m in res_v.missing_information)

    task = Task("T1", "Theo Điều 9, thưởng 888.000 đồng?", "general")
    with use_pack(OFFICE_PACK):
        res_w = asyncio.run(
            execute_task(
                _InlineLeakProv(),
                task,
                ev,
                RunMetrics(),
                product=True,
                user_request="Theo Điều 9, thưởng 888.000 đồng đúng không?",
            )
        )
    assert unauth_cid not in res_w.answer
    assert res_w.status == "PARTIAL"
    assert "Lưu ý căn cứ" in res_w.answer
    assert "Cần kiểm tra lại" in res_w.answer


def test_fix03_synthesizer_marks_unmapped_worker_citations_honestly():
    class _PartialCiteSynth:
        supports_per_call_output_tokens = True

        async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None, **kw):
            return ProviderResult('{"answer":"Ý 1 [src_aaaa1111aaaa1111_c0000]. Ý 2 tổng hợp chung."}', Usage(5, 5), model="m")

    results = [
        TaskResult("T1", "general", "COMPLETE", "Ý 1", ["src_aaaa1111aaaa1111_c0000"], ["src_aaaa1111aaaa1111_c0000"], []),
        TaskResult("T2", "general", "COMPLETE", "Ý 2", ["src_bbbb2222bbbb2222_c0001"], ["src_bbbb2222bbbb2222_c0001"], []),
    ]
    meta: dict = {}
    out = asyncio.run(
        synthesize(_PartialCiteSynth(), "So sánh", results, RunMetrics(), max_output_tokens=1800, synth_meta=meta)
    )
    assert "src_bbbb2222bbbb2222_c0001" in out
    assert meta.get("unmapped_worker_citations") == ["src_bbbb2222bbbb2222_c0001"]
    assert "chưa đối chiếu" in out.lower() or "not claim-verified" in out.lower()


# ==============================================================================
# FIX-04: RESEARCH A/B/C EXACT PARITY (product_mode=False)
# ==============================================================================


def test_fix04_research_abc_parity_for_noncanonical_status_worker_guard_and_synthesizer():
    ev = [_c(0, "Authentication uses signed JWT.", "src_aaaa1111aaaa1111")]

    class _WeirdResearchWorker:
        async def generate(self, *, system, user):
            return ProviderResult(
                '{"status":"DONE","answer":"RAW_NO_STRIP   ","citations":["src_aaaa1111aaaa1111_c0000"],"missing_information":[]}',
                Usage(5, 5),
            )

    # Pre-B137 Research Mode (`product=False`) did NOT normalize "DONE" -> "PARTIAL" or strip worker answers or append extra warnings
    res_w = asyncio.run(execute_task(_WeirdResearchWorker(), Task("T1", "Auth?", "security"), ev, RunMetrics(), product=False))
    assert res_w.status == "DONE"
    assert res_w.answer == "RAW_NO_STRIP   "

    res_v = asyncio.run(answer_vanilla(_WeirdResearchWorker(), "Auth?", ev, RunMetrics(), product=False))
    assert res_v.status == "DONE"

    # Pre-B137 Research Mode synthesizer (`max_output_tokens=None`): skips append if ANY citation already present
    class _ResearchSynth:
        async def generate(self, *, system, user):
            return ProviderResult("Summary using [src_aaaa1111aaaa1111_c0000] only.", Usage(5, 5), model="m")

    synth_res = asyncio.run(
        synthesize(
            _ResearchSynth(),
            "Compare",
            [
                TaskResult("T1", "security", "COMPLETE", "a", ["src_aaaa1111aaaa1111_c0000"], ["src_aaaa1111aaaa1111_c0000"], []),
                TaskResult("T2", "database", "COMPLETE", "b", ["src_bbbb2222bbbb2222_c0001"], ["src_bbbb2222bbbb2222_c0001"], []),
            ],
            RunMetrics(),
        )
    )
    assert synth_res == "Summary using [src_aaaa1111aaaa1111_c0000] only."


# ==============================================================================
# FIX-05: CHUNK CONTINUATION BOUNDARY
# ==============================================================================


def test_fix05_continue_articles_multi_chunk_3_4_out_of_order_and_boundary_safety():
    # 4-chunk Markdown table split across c0..c3, retrieved out of order [c2, c0]
    src_a = "src_aaaa1111aaaa1111"
    c0 = _c(0, "## 2. Bảng mức chi\n| Mục | Số tiền |\n|---|---|\n| A | 100 |", src_a)
    c1 = _c(1, "| B | 200 |\n| C | 300 |", src_a)
    c2 = _c(2, "| D | 400 |\n| E | 500 |", src_a)
    c3 = _c(3, "| F | 600 |", src_a)
    c4_new = _c(4, "Điều 9. Quy định riêng khác hoàn toàn.", src_a)
    other_src = _c(1, "| X | 999 |", "src_bbbb2222bbbb2222")

    out_multi = continue_articles([c0], [c0, c1, c2, c3, c4_new, other_src])
    assert [c.chunk_id for c in out_multi] == [c0.chunk_id, c1.chunk_id, c2.chunk_id, c3.chunk_id]
    assert other_src.chunk_id not in [c.chunk_id for c in out_multi]

    # Out-of-order retrieved [c1, c0] must reorder contiguous chain c0 -> c1 -> c2 -> c3 cleanly
    out_ooo = continue_articles([c1, c0], [c0, c1, c2, c3, c4_new])
    assert [c.chunk_id for c in out_ooo] == [c0.chunk_id, c1.chunk_id, c2.chunk_id, c3.chunk_id]

    # New article boundary: Điều 14 with complete body MUST NOT pull Điều 15 just because < 400 chars
    d14 = _c(10, "Điều 14. Thời gian nghỉ trưa\nNhân viên nghỉ trưa từ 12h00 đến 13h30 hằng ngày.", src_a)
    d15 = _c(11, "Điều 15. Quy định về trang phục công sở.", src_a)
    out_art = continue_articles([d14], [d14, d15])
    assert [c.chunk_id for c in out_art] == [d14.chunk_id]

    # Bare heading at chunk end ("Chương I") STILL pulls Điều 1 chunk (B129 Case-2 regression preserved!)
    ch1 = _c(0, "Lời nói đầu.\nChương I", "src_cccc3333cccc3333")
    d1 = _c(1, "NHỮNG QUY ĐỊNH CHUNG\nĐiều 1. Phạm vi điều chỉnh.", "src_cccc3333cccc3333")
    assert [c.chunk_id for c in continue_articles([ch1], [ch1, d1])] == [ch1.chunk_id, d1.chunk_id]
