"""Batch 133 RAG & Answer Quality regression tests (Phase 2A — Option A NO REINDEX):
RET-01, CHUNKING_HEADING_SEPARATION, BUG-B109-01, RET-03, NEW-B116-01, NEW-B116-02,
BUG-B104-02, BUG-B109-02, OBS-B99-01, NEW-B116-03, OBS-B93-01, B131-OBS-01/02.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import app.core.answer_checks as _ac
from app.core.answer_checks import apply_calc
from app.core.structured_output import parse_answer_json
from app.core.types import ProviderResult, RunMetrics, SourceChunk, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.registry import OFFICE_PACK
from app.research.vanilla import answer_vanilla
from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import LocalHashEmbedder
from app.retrieval.hybrid import continue_articles, fuse
from app.retrieval.source_focus import focus_sources
from app.retrieval.text import chunk_text
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore, VectorRecord


def _c(i: int, text: str, src: str = "src_doc", name: str = "doc.md") -> SourceChunk:
    return SourceChunk(chunk_id=f"{src}_c{i:04d}", source_id=src, source_name=name, text=text, index=i, provenance={})


# ---------------- RET-01 & CHUNKING_HEADING_SEPARATION ----------------

def test_ret01_strong_bm25_loop_preserves_multiple_strong_hits():
    s0 = _c(0, "Quy định chung về thanh toán hợp đồng dịch vụ.", "src_s0")
    s1 = _c(0, "Mức phạt chậm nộp hồ sơ thuế theo quy định đặc biệt.", "src_s1")
    noise = [_c(i, f"Điều {i}. Nội dung chung về hành chính văn phòng mục {i}.", "src_n") for i in range(6)]
    vec = [c.chunk_id for c in noise]
    out, _ = fuse("Mức phạt chậm nộp hồ sơ thuế và thanh toán hợp đồng", noise + [s0, s1], vec, top_k=4)
    ids = {c.chunk_id for c in out}
    assert s0.chunk_id in ids and s1.chunk_id in ids and len(out) == 4


def test_chunking_heading_separation_and_continue_articles_b129_case1_and_case2():
    # Synthetic DOC-05 boundary reproducing real B128/B129: c0000 ends with "Chương I", c0001 starts with Điều 1
    doc05_c0 = _c(0, "Chính phủ ban hành Nghị định bảo vệ dữ liệu cá nhân.\nChương I", "src_doc05", "05_Nghi_dinh_13_2023.pdf")
    doc05_c1 = _c(1, "NHỮNG QUY ĐỊNH CHUNG\nĐiều 1. Phạm vi điều chỉnh và đối tượng áp dụng\n1. Nghị định này quy định về bảo vệ dữ liệu cá nhân.", "src_doc05", "05_Nghi_dinh_13_2023.pdf")
    doc05_c53 = _c(53, "Điều 42. Hiệu lực thi hành\nNghị định này có hiệu lực thi hành từ ngày 01 tháng 07 năm 2023.", "src_doc05", "05_Nghi_dinh_13_2023.pdf")
    doc02_c0 = _c(0, "# Luật số 20/2023/QH15 Giao dịch điện tử\nCó hiệu lực thi hành từ ngày 01 tháng 07 năm 2024.", "src_doc02", "02_Luat_GD_dien_tu.pdf")
    doc02_fill = [_c(i, f"Điều {i}. Quy định nội dung chi tiết số {i}.", "src_doc02", "02_Luat_GD_dien_tu.pdf") for i in range(1, 6)]
    corpus = [doc05_c0, doc05_c1, doc05_c53, doc02_c0, *doc02_fill]

    # B129 CASE-1: DOC-05 c0053 effective date reaches Top-6
    out1, _ = fuse("Nghị định bảo vệ dữ liệu cá nhân có hiệu lực từ ngày nào?", corpus, [doc02_c0.chunk_id, doc05_c0.chunk_id], top_k=6)
    assert doc05_c53.chunk_id in [c.chunk_id for c in out1]

    # B129 CASE-2: c0000 in Top-6 pulls c0001 ("Chương I" -> "Điều 1") alongside DOC-02 c0000!
    fused2, _ = fuse("Luật Giao dịch điện tử và Nghị định bảo vệ dữ liệu cá nhân", corpus, [doc02_c0.chunk_id, *[c.chunk_id for c in doc02_fill], doc05_c0.chunk_id], top_k=6)
    out2 = continue_articles(fused2, corpus)
    out2_ids = [c.chunk_id for c in out2]
    assert doc02_c0.chunk_id in out2_ids and doc05_c1.chunk_id in out2_ids

    # chunk_text keeps trailing "Chương I" heading attached to its body in next chunk when text exceeds max_chars=1200
    long_intro = ("Đoạn mở đầu dài về căn cứ pháp lý ban hành nghị định bảo vệ dữ liệu.\n\n" * 18).strip()
    parts = chunk_text(long_intro + "\n\nChương I\n\nĐiều 1. Phạm vi điều chỉnh của văn bản pháp quy này.", max_chars=1200)
    assert len(parts) >= 2
    assert not parts[0].rstrip().endswith("Chương I")
    assert "Chương I" in parts[1] and "Điều 1." in parts[1]


# ---------------- BUG-B109-01 & RET-03 ----------------

def test_bug_b109_01_product_mode_context_budget_avoids_3000_cap_drop(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("TASK_TOP_K", "8")
    monkeypatch.delenv("PRODUCT_MAX_CONTEXT_TOKENS", raising=False)
    store = SourceStore(str(tmp_path / "src"))
    # 8 chunks ~430 est tokens each (~3440 > 3000): product_mode gives headroom without changing cfg.max_context_tokens (Research A/B/C)
    text = "\n\n".join(f"Mục {i}: Quy định chính sách nhân sự thứ {i} " + ("chi tiết áp dụng " * 75) for i in range(8))
    store.import_text("long.md", text)
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    run = asyncio.run(pipe.run("Quy định chính sách nhân sự gồm những mục nào?", "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK))
    van = next(e for e in run["events"] if e["stage"] == "vanilla_retrieval")
    assert len(van["selected"]) == 8 and van["dropped"] == []
    assert run["effective_config"]["max_context_tokens"] == 3000  # Research Mode invariant preserved!


def test_ret03_candidate_index_filters_mismatched_embedding_version():
    emb = LocalHashEmbedder(dimension=8)
    vs = InMemoryVectorStore(vector_size=8)
    vs.upsert([
        VectorRecord("u1:s1_c0", emb.embed("hello"), {"owner_user_id": "u1", "source_id": "s1", "chunk_id": "s1_c0", "embedding_version": emb.version}),
        VectorRecord("u1:s2_c0", emb.embed("hello"), {"owner_user_id": "u1", "source_id": "s2", "chunk_id": "s2_c0", "embedding_version": "ollama:nomic-embed-text:8"}),
    ])

    class _DummyStore:
        def scope_source_ids(self): return {"s1", "s2"}

    idx = CandidateIndex(_DummyStore(), vs, owner_user_id="u1", embedder=emb)
    hits = idx.candidates("hello", limit=5)
    assert [m.payload["chunk_id"] for m in hits] == ["s1_c0"]


# ---------------- NEW-B116-01 & NEW-B116-02 ----------------

def test_new_b116_01_focus_sources_keeps_both_docs_in_short_comparison():
    docs = [
        _c(0, "# QUY CHẾ LÀM VIỆC 2026\nQuy định mới", "doc_2026", "Quy_che_lam_viec_2026.md"),
        _c(0, "# NỘI QUY LAO ĐỘNG\nQuy định thử việc", "doc_nq", "Noi_quy_lao_dong.md"),
        _c(0, "# QUY CHẾ 2024\nQuy định cũ", "doc_2024", "Quy_che_lam_viec_2024.md"),
    ]
    focused = focus_sources("So sánh quy chế 2026 với nội quy?", docs, None)
    assert focused is not None and set(focused) == {"doc_2026", "doc_nq"}


def test_new_b116_02_unbound_no_evidence_with_docs_never_marks_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    store = SourceStore(str(tmp_path / "src"))
    store.import_text("noi_quy.md", "Nhân viên thử việc tối đa 60 ngày.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))

    class _VanillaNoEvGeneralFake(FakeProvider):
        async def generate_grounded(self, *, system, user, evidence_ids, **kw):
            return ProviderResult('{"status":"NO_EVIDENCE","answer":"Không có trong tài liệu.","citations":[],"missing_information":["x"]}', Usage(5, 5))

        async def generate_structured(self, *, system, user, response_schema, **kw):
            return ProviderResult('{"answer":"Hà Nội là thủ đô của Việt Nam."}', Usage(5, 5))

    with patch("app.research.pipeline.get_provider", return_value=_VanillaNoEvGeneralFake()):
        run = asyncio.run(pipe.run("Thủ đô của Việt Nam là gì?", "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK))

    assert run["status"] != "COMPLETE"
    assert run["status"] == "PARTIAL"
    assert "Tài liệu bạn gửi không có thông tin này" in run["answer"]


# ---------------- BUG-B104-02, BUG-B109-02, OBS-B99-01, NEW-B116-03 ----------------

def test_vanilla_guards_prompt_echo_unsupported_articles_and_no_evidence_citations():
    ev = [_c(0, "Khoản 3 quy định phụ cấp ăn trưa 500000 đồng/tháng.", "src_1111111111111111")]

    class _EchoProv:
        async def generate(self, *, system, user):
            return ProviderResult('{"status":"NO_EVIDENCE","answer":"USER REQUEST: Mức phạt?\\nEVIDENCE: [src_1111111111111111_c0000]","citations":["src_1111111111111111_c0000"],"missing_information":[]}', Usage(5, 5))

    res_echo = asyncio.run(answer_vanilla(_EchoProv(), "Mức phạt?", ev, RunMetrics(), product=True))
    assert res_echo.status == "NO_EVIDENCE"
    assert "USER REQUEST:" not in res_echo.answer and "EVIDENCE:" not in res_echo.answer
    assert res_echo.citations == [] and "Nguồn:" not in res_echo.answer

    class _BadArtProv:
        async def generate(self, *, system, user):
            return ProviderResult('{"status":"COMPLETE","answer":"Theo Điều 3, mức phụ cấp ăn trưa là 500000 đồng/tháng.","citations":["src_1111111111111111_c0000"],"missing_information":[]}', Usage(5, 5))

    res_art = asyncio.run(answer_vanilla(_BadArtProv(), "Phụ cấp ăn trưa?", ev, RunMetrics(), product=True))
    assert res_art.status == "PARTIAL"
    assert "Lưu ý căn cứ" in res_art.answer
    finish_checked = getattr(_ac, "finish_checked", None)
    assert finish_checked is not None
    text_2, bad_2, arts_2 = finish_checked("Theo Điều 3, phụ cấp 500000.", ev[0].text)
    assert arts_2 == ["3"] and bad_2 == [] and "Lưu ý căn cứ" in text_2


def test_new_b116_03_bare_regex_ignores_dates_ratios_and_compound_expressions():
    assert apply_calc("Tỷ lệ đồng thuận = 3/4") == "Tỷ lệ đồng thuận = 3/4"
    assert apply_calc("Ngày hiệu lực = 15/12") == "Ngày hiệu lực = 15/12"
    assert apply_calc("Tổng = 10/2 + 3") == "Tổng = 10/2 + 3"
    assert apply_calc("Phạt = 0.005*10*120000000 đồng") == "Phạt = 0.005*10*120000000 = **6.000.000** đồng"
    assert apply_calc("Lương giờ = 12000000/26/8 đồng") == "Lương giờ = 12000000/26/8 = **57.692,31** đồng"


# ---------------- OBS-B93-01 & B131-OBS-01 ----------------

def test_obs_b93_01_top_level_citations_and_b131_obs_01_truncation_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    store = SourceStore(str(tmp_path / "src"))
    store.import_text("nq.md", "Nhân viên thử việc tối đa 60 ngày.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    run = asyncio.run(pipe.run("Thời gian thử việc tối đa bao lâu?", "C", provider_name="fake", product_mode=True, domain_pack=OFFICE_PACK))
    assert "citations" in run and isinstance(run["citations"], list)
    expected = [cid for tr in run["task_results"] for cid in tr.get("citations") or []]
    assert run["citations"] == list(dict.fromkeys(expected))

    # Truncated JSON before "citations" marks truncation explicitly without fabricating citations
    parsed = parse_answer_json('{"status":"COMPLETE","answer":"Theo Điều 1, thử việc 60 ngày')
    assert parsed["status"] == "PARTIAL"
    assert parsed["citations"] == []
    assert parsed.get("truncated") is True
    assert "model output truncated before citations" in parsed["missing_information"]
