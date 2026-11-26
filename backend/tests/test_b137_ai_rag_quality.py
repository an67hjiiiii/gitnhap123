"""Batch 137 AI/RAG Quality Closure Tests (AI-T01 .. AI-T20, Zero Ollama, FakeProvider).

Covers:
- AI-T01..AI-T07: Focus 1 (AI-05 Unbound NO_EVIDENCE & statutory/regulatory guard vs valid general fallback & Research Mode A/B/C)
- AI-T08..AI-T13: Focus 2 (Answer completeness, split list/table/article chunk continuation, silent truncation visibility)
- AI-T14..AI-T20: Focus 3 (Worker NO_EVIDENCE citation cleanup, finish_checked on worker/synthesizer, missing/fabricated citation handling, status normalization, Research A/B/C parity)
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.core.types import ProviderResult, RunMetrics, SourceChunk, Task, TaskResult, Usage
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


def _chunk(i: int, text: str, src: str = "src_doc", name: str = "doc.md") -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{src}_c{i:04d}",
        source_id=src,
        source_name=name,
        text=text,
        index=i,
        provenance={},
    )


def _pipe(tmp_path, monkeypatch, docs=()):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    store = SourceStore(str(tmp_path / "src"))
    for name, text in docs:
        store.import_text(name, text)
    return ResearchPipeline(store, RunStore(str(tmp_path / "runs")))


# ==============================================================================
# Focus 1: AI-05 Unbound NO_EVIDENCE & Statutory/Regulatory Guard
# ==============================================================================


def test_ai_t01_statutory_and_regulatory_queries_are_doc_bound():
    assert doc_bound("Nghị định 99/2026 quy định mức phạt hành chính về dữ liệu là bao nhiêu?")
    assert doc_bound("Theo Nghị định 13/2023/NĐ-CP và Thông tư 80, thời hạn nộp báo cáo là bao lâu?")
    assert doc_bound("Điều 15 Luật Giao dịch điện tử 2023 quy định những điều kiện nào?")
    # Valid non-statutory general knowledge remains unbound:
    assert not doc_bound("Thủ đô của Úc là thành phố nào?")
    assert not doc_bound("Giải thích khái niệm ROI trong tài chính?")


class _OfficePlannedBase(FakeProvider):
    """FakeProvider that outputs OFFICE_PACK valid task domains + supports structured synthesis."""

    supports_per_call_output_tokens = True

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        marker = system.upper()
        if "TASK_PLAN_BUILDER" in marker:
            req = self._current_request(user)
            return ProviderResult(
                f'{{"tasks":[{{"task_id":"T1","goal":"{req[:80]}","domain":"general","depends_on":[],"evidence_needs":["quy định"]}},{{"task_id":"T2","goal":"{req[:80]}","domain":"general","depends_on":[],"evidence_needs":["chi tiết"]}}]}}',
                Usage(5, 5),
                model="fake",
            )
        return await super().generate(system=system, user=user)

    async def generate_structured(self, *, system: str, user: str, response_schema, **kw):
        return await self.generate(system=system, user=user)


def test_ai_t02_unbound_statutory_query_returns_no_evidence_without_general_fallback(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch, docs=[("noi_quy.md", "Nhân viên thử việc tối đa 60 ngày.")])
    general_called = False

    class _SpyFake(_OfficePlannedBase):
        async def generate_grounded(self, *, system, user, evidence_ids, **kw):
            return ProviderResult('{"status":"NO_EVIDENCE","answer":"Không có trong tài liệu.","citations":[],"missing_information":["nđ 99"]}', Usage(5, 5))

        async def generate_structured(self, *, system, user, response_schema, **kw):
            nonlocal general_called
            if "GENERAL_KNOWLEDGE_ANSWERER" in system:
                general_called = True
                return ProviderResult('{"answer":"Theo Nghị định 99/2026 mức phạt là 50 triệu đồng."}', Usage(5, 5))
            return await super().generate_structured(system=system, user=user, response_schema=response_schema, **kw)

    with patch("app.research.pipeline.get_provider", return_value=_SpyFake()):
        run = asyncio.run(
            pipe.run(
                "Nghị định 99/2026 quy định mức phạt vi phạm bảo vệ dữ liệu là bao nhiêu?",
                "C",
                provider_name="fake",
                product_mode=True,
                domain_pack=OFFICE_PACK,
            )
        )

    assert general_called is False
    assert run["status"] == "NO_EVIDENCE"
    assert run["citations"] == []


def test_ai_t03_general_branch_with_uploaded_docs_never_marks_complete(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch, docs=[("noi_quy.md", "Nhân viên gửi đơn nghỉ phép trước 03 ngày.")])

    class _GeneralFake(_OfficePlannedBase):
        async def generate_structured(self, *, system, user, response_schema, **kw):
            if "GENERAL_KNOWLEDGE_ANSWERER" in system:
                return ProviderResult('{"answer":"Thủ đô của Brazil là Brasília."}', Usage(5, 5))
            return await super().generate_structured(system=system, user=user, response_schema=response_schema, **kw)

    with patch("app.research.pipeline.get_provider", return_value=_GeneralFake()):
        run = asyncio.run(
            pipe.run(
                "Thủ đô của Brazil là thành phố nào?",
                "C",
                provider_name="fake",
                product_mode=True,
                domain_pack=OFFICE_PACK,
            )
        )

    assert run["status"] == "PARTIAL"
    assert run["citations"] == []
    assert "Tài liệu bạn gửi không có thông tin này" in run["answer"]


def test_ai_t04_planned_multi_agent_all_no_evidence_never_calls_synthesizer_or_marks_complete(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch, docs=[("noi_quy.md", "Nhân viên làm việc từ 8h30 đến 17h30.")])
    synth_calls = 0

    class _PlannedNoEvFake(_OfficePlannedBase):
        async def generate_structured(self, *, system, user, response_schema, **kw):
            nonlocal synth_calls
            if "SYNTHESIZER" in system:
                synth_calls += 1
                return ProviderResult('{"answer":"Bịa thông tin [fake_c1]."}', Usage(5, 5))
            return await super().generate_structured(system=system, user=user, response_schema=response_schema, **kw)

        async def generate_grounded(self, *, system, user, evidence_ids, **kw):
            return ProviderResult('{"status":"NO_EVIDENCE","answer":"Tài liệu không nêu quy định này.","citations":[],"missing_information":["ngoài phạm vi"]}', Usage(5, 5))

    with patch("app.research.pipeline.get_provider", return_value=_PlannedNoEvFake()):
        run = asyncio.run(
            pipe.run(
                "Theo tài liệu, so sánh quy định trợ cấp thai sản ở hợp đồng A và kiểm tra mức thưởng cổ phần ở phụ lục B.",
                "C",
                provider_name="fake",
                product_mode=True,
                domain_pack=OFFICE_PACK,
            )
        )

    assert run["status"] == "NO_EVIDENCE"
    assert run["citations"] == []
    assert synth_calls == 0


def test_ai_t05_general_knowledge_without_docs_stays_complete_and_labelled(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch)

    class _GeneralFake(_OfficePlannedBase):
        async def generate_structured(self, *, system, user, response_schema, **kw):
            if "GENERAL_KNOWLEDGE_ANSWERER" in system:
                return ProviderResult('{"answer":"Canberra là thủ đô của Úc."}', Usage(5, 5))
            return await super().generate_structured(system=system, user=user, response_schema=response_schema, **kw)

    with patch("app.research.pipeline.get_provider", return_value=_GeneralFake()):
        run = asyncio.run(
            pipe.run("Thủ đô của Úc là thành phố nào?", "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK, source_ids=[])
        )

    assert run["status"] == "COMPLETE"
    assert "Kiến thức chung" in run["answer"]
    assert run["citations"] == []


def test_ai_t06_both_knowledge_source_keeps_doc_citations(tmp_path, monkeypatch):
    assert choose_source("Phụ cấp ăn trưa bao nhiêu và giải thích vì sao cần chứng từ?", 2, bound=False) == BOTH
    pipe = _pipe(tmp_path, monkeypatch, docs=[("che_do.md", "Điều 4. Phụ cấp ăn trưa 500.000 đồng/tháng cho nhân viên chính thức.")])
    cid = pipe.source_store.chunks()[0].chunk_id

    class _BothFake(FakeProvider):
        async def generate_grounded(self, *, system, user, evidence_ids, **kw):
            return ProviderResult(
                f'{{"status":"COMPLETE","answer":"Phụ cấp ăn trưa là 500.000 đồng/tháng [{cid}].\\n\\nKiến thức chung: Chứng từ giúp hạch toán chi phí hợp lệ.","citations":["{cid}"],"missing_information":[]}}',
                Usage(5, 5),
            )

    with patch("app.research.pipeline.get_provider", return_value=_BothFake()):
        run = asyncio.run(
            pipe.run("Phụ cấp ăn trưa bao nhiêu và giải thích vì sao cần chứng từ?", "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK)
        )

    assert run["status"] == "COMPLETE"
    assert cid in run["citations"]
    assert "Kiến thức chung:" in run["answer"]


def test_ai_t07_research_mode_abc_never_uses_general_fallback(tmp_path, monkeypatch):
    for cond in ("A", "B", "C"):
        pipe = _pipe(tmp_path / cond, monkeypatch)
        run = asyncio.run(pipe.run("Thủ đô của Úc là thành phố nào?", cond, provider_name="fake", source_ids=[]))
        assert run["status"] == "NO_EVIDENCE"
        assert not any(e["stage"].startswith("knowledge_source") for e in run["events"])


# ==============================================================================
# Focus 2: Answer Completeness, Chunk Continuation & Truncation Visibility
# ==============================================================================


def test_ai_t08_continue_articles_pulls_split_enumerated_list_chunk():
    c0 = _chunk(0, "Điều 5. Hình thức kỷ luật\nNgười vi phạm chịu các hình thức kỷ luật sau đây:")
    c1 = _chunk(1, "a) Khiển trách bằng văn bản;\nb) Kéo dài thời hạn nâng lương không quá 06 tháng;\nc) Sa thải.")
    c2 = _chunk(2, "Điều 6. Thời hiệu xử lý kỷ luật là 06 tháng.")
    out = continue_articles([c0], [c0, c1, c2])
    assert [c.chunk_id for c in out] == [c0.chunk_id, c1.chunk_id]


def test_ai_t09_continue_articles_pulls_split_markdown_table_chunk():
    c0 = _chunk(0, "## 3. Bảng phụ cấp công tác\n| Cấp bậc | Mức phụ cấp |\n|---|---|\n| Nhân viên | 300.000 |")
    c1 = _chunk(1, "| Trưởng nhóm | 500.000 |\n| Quản lý | 800.000 |")
    out = continue_articles([c0], [c0, c1])
    assert [c.chunk_id for c in out] == [c0.chunk_id, c1.chunk_id]


def test_ai_t10_continue_articles_pulls_long_article_continuation_past_400_chars():
    body_pad = "Nội dung chi tiết quy trình xét duyệt từng học kỳ và đối chiếu tín chỉ tích lũy theo quy chế đào tạo đại học. " * 5
    c0 = _chunk(0, f"Điều 14. Công nhận tốt nghiệp\n{body_pad}\nSinh viên phải đáp ứng đủ:")
    c1 = _chunk(1, "c) Hoàn thành học phần giáo dục quốc phòng;\nd) Đạt chuẩn đầu ra ngoại ngữ.")
    assert len(c0.text) > 400
    out = continue_articles([c0], [c0, c1])
    assert [c.chunk_id for c in out] == [c0.chunk_id, c1.chunk_id]


def test_ai_t11_truncated_synthesizer_output_downgrades_complete_to_partial(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch, docs=[("nq.md", "Điều 1. Thử việc 60 ngày.\nĐiều 2. Nghỉ phép 12 ngày.")])
    cid = pipe.source_store.chunks()[0].chunk_id

    class _TruncSynthFake(_OfficePlannedBase):
        async def generate_grounded(self, *, system, user, evidence_ids, **kw):
            return ProviderResult(f'{{"status":"COMPLETE","answer":"Đáp án [{cid}].","citations":["{cid}"],"missing_information":[]}}', Usage(5, 5))

        async def generate_structured(self, *, system, user, response_schema, **kw):
            if "SYNTHESIZER" in system:
                return ProviderResult('{"answer":"1. Thử việc 60 ngày.\\n2. Nghỉ phép bị cắt dở', Usage(5, 5))
            return await super().generate_structured(system=system, user=user, response_schema=response_schema, **kw)

    with patch("app.research.pipeline.get_provider", return_value=_TruncSynthFake()):
        run = asyncio.run(
            pipe.run(
                "So sánh quy định thử việc và lập bảng tổng hợp chính sách nghỉ phép theo tài liệu.",
                "C",
                provider_name="fake",
                product_mode=True,
                domain_pack=OFFICE_PACK,
            )
        )

    assert run["status"] == "PARTIAL"
    assert "cắt" in run["answer"].lower() or "chưa đầy đủ" in run["answer"].lower()


def test_ai_t12_synthesizer_compact_task_drop_never_reports_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCT_NUM_CTX", "1024")
    monkeypatch.setenv("OLLAMA_MAX_NUM_CTX", "4096")

    class _CompactProvider:
        supports_per_call_output_tokens = True
        supports_num_ctx = True

        async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None, num_ctx=None, **kw):
            return ProviderResult('{"answer":"Tổng hợp ngắn [c1]."}', Usage(10, 10), model="m")

    long_a = "Nội dung rất chi tiết về điều khoản hợp đồng và mức phạt chậm tiến độ. " * 25
    results = [
        TaskResult("T1", "general", "COMPLETE", long_a, ["c1"], ["c1"], []),
        TaskResult("T2", "general", "COMPLETE", long_a, ["c2"], ["c2"], []),
    ]
    meta: dict = {}
    text = asyncio.run(synthesize(_CompactProvider(), "Tổng hợp A và B", results, RunMetrics(), max_output_tokens=200, num_ctx=1024, synth_meta=meta))
    assert meta.get("context_trimmed") is True
    assert "Tóm tắt" in text or "cắt" in text.lower() or "Nguồn:" in text


def test_ai_t13_vanilla_truncated_json_sets_partial_and_notice():
    ev = [_chunk(0, "Điều 1. Quy định thử việc tối đa 60 ngày.")]

    class _TruncVanilla:
        async def generate(self, *, system, user):
            return ProviderResult('{"status":"COMPLETE","answer":"Thử việc tối đa 60 ngày và các quyền lợi sau đây', Usage(5, 5))

    res = asyncio.run(answer_vanilla(_TruncVanilla(), "Thử việc bao lâu?", ev, RunMetrics(), product=True))
    assert res.status == "PARTIAL"
    assert any("truncated" in m for m in res.missing_information)


# ==============================================================================
# Focus 3: Citation Accuracy & Evidence Sufficiency
# ==============================================================================


def test_ai_t14_worker_no_evidence_clears_citations_and_strips_prompt_echo():
    ev = [_chunk(0, "Khoản 3. Phụ cấp ăn trưa 500.000 đồng.", "src_1111111111111111")]
    task = Task("T1", "Mức phạt trễ hạn?", "general")

    class _BadNoEvWorker:
        async def generate(self, *, system, user):
            return ProviderResult(
                '{"status":"NO_EVIDENCE","answer":"USER REQUEST: Mức phạt?\\nEVIDENCE: [src_1111111111111111_c0000]","citations":["src_1111111111111111_c0000"],"missing_information":[]}',
                Usage(5, 5),
            )

    with use_pack(OFFICE_PACK):
        res = asyncio.run(execute_task(_BadNoEvWorker(), task, ev, RunMetrics(), product=True, user_request="Mức phạt trễ hạn?"))
    assert res.status == "NO_EVIDENCE"
    assert res.citations == []
    assert "USER REQUEST:" not in res.answer and "EVIDENCE:" not in res.answer


def test_ai_t15_worker_unsupported_article_or_number_downgrades_complete_to_partial():
    ev = [_chunk(0, "Khoản 2 quy định phụ cấp xăng xe 400.000 đồng/tháng.", "src_2222222222222222")]
    task = Task("T1", "Phụ cấp xăng xe?", "general")

    class _HallucinatingWorker:
        async def generate(self, *, system, user):
            return ProviderResult(
                '{"status":"COMPLETE","answer":"Theo Điều 9, phụ cấp xăng xe là 400.000 đồng và thưởng thêm 999.000 đồng.","citations":["src_2222222222222222_c0000"],"missing_information":[]}',
                Usage(5, 5),
            )

    with use_pack(OFFICE_PACK):
        res = asyncio.run(execute_task(_HallucinatingWorker(), task, ev, RunMetrics(), product=True, user_request="Phụ cấp xăng xe?"))
    assert res.status == "PARTIAL"
    assert "Lưu ý căn cứ" in res.answer
    assert "Cần kiểm tra lại" in res.answer
    assert any("articles not found" in m for m in res.missing_information)
    assert any("numbers not found" in m for m in res.missing_information)


def test_ai_t16_synthesizer_preserves_all_missing_valid_citations():
    class _PartialCiteSynth:
        supports_per_call_output_tokens = True

        async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None, **kw):
            return ProviderResult('{"answer":"Ý 1 [src_a_c0000]. Ý 2 không ghi mã."}', Usage(5, 5), model="m")

    results = [
        TaskResult("T1", "general", "COMPLETE", "Ý 1", ["src_a_c0000"], ["src_a_c0000"], []),
        TaskResult("T2", "general", "COMPLETE", "Ý 2", ["src_b_c0001"], ["src_b_c0001"], []),
    ]
    out = asyncio.run(synthesize(_PartialCiteSynth(), "So sánh A và B", results, RunMetrics(), max_output_tokens=1800))
    assert "src_a_c0000" in out
    assert "src_b_c0001" in out


def test_ai_t17_synthesizer_strips_fabricated_inline_citations():
    class _FakeCiteSynth:
        supports_per_call_output_tokens = True

        async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None, **kw):
            return ProviderResult('{"answer":"Ý đúng [src_aaaa1111aaaa1111_c0000] và ý bịa [src_deadbeefdeadbeef_c9999]."}', Usage(5, 5), model="m")

    results = [
        TaskResult("T1", "legal", "COMPLETE", "Ý đúng", ["src_aaaa1111aaaa1111_c0000"], ["src_aaaa1111aaaa1111_c0000"], []),
    ]
    meta: dict = {}
    out = asyncio.run(
        synthesize(_FakeCiteSynth(), "Hỏi về quy định", results, RunMetrics(), max_output_tokens=1800, synth_meta=meta)
    )
    assert "src_aaaa1111aaaa1111_c0000" in out
    assert "src_deadbeefdeadbeef_c9999" not in out
    assert meta.get("invalid_inline_citations") == ["src_deadbeefdeadbeef_c9999"]


def test_ai_t18_synthesizer_unsupported_article_downgrades_pipeline_run_to_partial(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, monkeypatch, docs=[("nq.md", "Khoản 2. Phụ cấp đi lại 300.000 đồng.")])
    cid = pipe.source_store.chunks()[0].chunk_id

    class _BadArtSynthFake(_OfficePlannedBase):
        async def generate_grounded(self, *, system, user, evidence_ids, **kw):
            return ProviderResult(f'{{"status":"COMPLETE","answer":"Phụ cấp đi lại 300.000 đồng [{cid}].","citations":["{cid}"],"missing_information":[]}}', Usage(5, 5))

        async def generate_structured(self, *, system, user, response_schema, **kw):
            if "SYNTHESIZER" in system:
                return ProviderResult(f'{{"answer":"Theo Điều 88, phụ cấp đi lại 300.000 đồng [{cid}]."}}', Usage(5, 5))
            return await super().generate_structured(system=system, user=user, response_schema=response_schema, **kw)

    with patch("app.research.pipeline.get_provider", return_value=_BadArtSynthFake()):
        run = asyncio.run(
            pipe.run(
                "So sánh phụ cấp đi lại và kiểm tra điều khoản áp dụng theo tài liệu.",
                "C",
                provider_name="fake",
                product_mode=True,
                domain_pack=OFFICE_PACK,
            )
        )

    assert run["status"] == "PARTIAL"
    assert "Lưu ý căn cứ" in run["answer"]


def test_ai_t19_noncanonical_llm_status_normalized():
    ev = [_chunk(0, "Điều 1. Nội dung hợp đồng.")]
    task = Task("T1", "Nội dung?", "general")

    class _BadStatus:
        async def generate(self, *, system, user):
            return ProviderResult('{"status":"DONE","answer":"Nội dung hợp đồng.","citations":["src_doc_c0000"],"missing_information":[]}', Usage(5, 5))

    with use_pack(OFFICE_PACK):
        res_v = asyncio.run(answer_vanilla(_BadStatus(), "Nội dung?", ev, RunMetrics(), product=True))
        res_w = asyncio.run(execute_task(_BadStatus(), task, ev, RunMetrics(), product=True, user_request="Nội dung?"))
    assert res_v.status == "PARTIAL"
    assert res_w.status == "PARTIAL"


def test_ai_t20_research_mode_abc_preserves_retrieval_status_and_non_product_behavior(tmp_path, monkeypatch):
    for cond in ("A", "B", "C"):
        pipe = _pipe(tmp_path / cond, monkeypatch, docs=[("spec.md", "Authentication requires signed JWT tokens and authorization permissions.")])
        run = asyncio.run(pipe.run("Review authentication JWT authorization permissions", cond, provider_name="fake"))
        assert run["status"] in {"COMPLETE", "PARTIAL"}
        assert "product_request_routing" not in [e["stage"] for e in run["events"]]
        assert "agent_selection" not in run["effective_config"]
        assert "knowledge_source" not in run["effective_config"]
