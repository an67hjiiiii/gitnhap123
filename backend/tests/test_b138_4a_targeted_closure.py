"""Batch 138.4A Targeted AI Closure — Test-First RED -> GREEN Verification (Zero Ollama).

Covers:
- FIX-01 (B138-4-RET-01): PostgresSourceStore._chunk propagates display_metadata['doc_type'] to SourceChunk.provenance.
- FIX-02 (CHECK-C): Pipeline retrieval enforces scope_chunks before hybrid_fuse & bounds BM25 rescue scores on RRF scale.
- FIX-03 (B138-4-CTX-01): Pipeline worker context allocation keeps multi-version Law 2023 c0018/c0019 under char_proxy cap.
- FIX-04 (CHECK-A1/A2 + Calculator): Unpunctuated 3500/4000 qty, hypothetical premise trap '30 ngày', mixed BARE AST calc, ungrounded calc operand rejection.
- FIX-05 (CHECK-B1/B2/E1/E2): Strip/qualify contradicted affirmative verdicts, stop mixed-condition over-trigger, catch contract-only statute mention, filter off-topic quiz items.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.domain_tools import generate_items
from app.core.answer_checks import (
    IMG_MARK,
    apply_calc,
    check_product_evidence_claims,
    evidence_with_case_image_only,
)
from app.core.config import RuntimeConfig
from app.core.types import ProviderResult, RunMetrics, SourceChunk, Usage
from app.ingestion.doc_type import DOC_TYPE_VERSION
from app.research.pipeline import ResearchPipeline
from app.research.registry import OFFICE_PACK, use_pack
from app.research.worker import execute_task
from app.retrieval.hybrid import HYBRID_VERSION
from app.retrieval.source_focus import focus_sources
from app.storage.postgres.base import Base
from app.storage.postgres.models import KnowledgeChunkRecord, KnowledgeSourceRecord, UserRecord
from app.storage.postgres.runtime import PostgresSourceStore
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


@pytest.fixture()
def pg_like_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.create_function("btrim", 1, lambda v: None if v is None else v.strip()))
    Base.metadata.create_all(engine)
    f = sessionmaker(engine, expire_on_commit=False)
    with f.begin() as s:
        s.add_all([UserRecord(user_id="u1", email="u1@x.vn", display_name="u1", password_hash="x")])
    return f


def test_fix01_postgres_chunk_propagates_doc_type_for_source_focus(pg_like_factory):
    store = PostgresSourceStore(pg_like_factory, "u1")
    ts = store.import_text(
        "Bang_gio_lam_them_thang_11.xlsx",
        "## Lam_them\nHọ tên | Lương giờ | Giờ thường | Giờ lễ\nNguyễn An | 84.135 | 10 | 8",
    )
    law = store.import_text(
        "Bo_luat_Lao_dong.docx",
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nBỘ LUẬT LAO ĐỘNG\nĐiều 98. Tiền lương làm thêm giờ ngày thường ít nhất bằng 150%, ngày lễ 300%.",
    )
    other = store.import_text("Thuc_don_tuan.md", "# Thực đơn\nThứ Hai: Phở bò.")

    # Simulate pre-existing DB rows whose chunk provenance has no doc_type (exact B138.4 PG state)
    with pg_like_factory.begin() as s:
        for rec in s.query(KnowledgeChunkRecord).all():
            rec.provenance = {k: v for k, v in (rec.provenance or {}).items() if k != "doc_type"}

    chunks = store.chunks()
    by_sid = {c.source_id: c for c in chunks}
    assert by_sid[law["source_id"]].provenance.get("doc_type") == "legal_doc"

    # Cross-rule OT query mentioning "Bảng giờ làm thêm" MUST NOT lock out companion legal_doc
    q = "Tiền làm thêm tối thiểu trong Bảng giờ làm thêm tháng 11 là bao nhiêu?"
    focused = focus_sources(q, chunks, [ts["source_id"], law["source_id"], other["source_id"]])
    assert focused is None or law["source_id"] in focused

    # Single-doc direct query still focuses cleanly
    focused_menu = focus_sources("Theo Thực đơn tuần, Thứ Hai ăn gì?", chunks, None)
    assert focused_menu == [other["source_id"]]

    # User manual label override propagates to chunks(); missing metadata never overwrites real chunk doc_type with 'other'
    store.set_doc_type(ts["source_id"], "internal_policy")
    assert next(c for c in store.chunks([ts["source_id"]])).provenance.get("doc_type") == "internal_policy"

    with pg_like_factory.begin() as s:
        src = s.get(KnowledgeSourceRecord, law["source_id"])
        src.display_metadata = {}  # legacy source missing display_metadata
        chk = s.query(KnowledgeChunkRecord).filter_by(source_id=law["source_id"]).first()
        chk.provenance = {**(chk.provenance or {}), "doc_type": "legal_doc"}
    assert next(c for c in store.chunks([law["source_id"]])).provenance.get("doc_type") == "legal_doc"


def test_fix02_retrieve_hybrid_enforces_scope_and_comparable_bm25_scores(tmp_path):
    st = SourceStore(str(tmp_path / "src"))
    allowed = st.import_text("Chinh_sach.md", "# Chính sách công ty\nNhân viên làm việc từ thứ Hai đến thứ Sáu.")
    secret = st.import_text("Mat_Mua_lai_42ty.pdf", "# Kế hoạch M&A\nDự án Hải Đăng mua lại EduSoft giá chào mua 42 tỷ đồng tuyệt mật.")
    distractors = [
        st.import_text(f"Tai_lieu_{i}.md", f"# Tài liệu {i}\nNội dung tham chiếu nội bộ số {i} về quy trình hành chính.")
        for i in range(12)
    ]
    all_chunks = st.chunks()
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "runs")))

    # Caller accidentally passes full all_chunks alongside scoped source_ids (missing secret)
    q = "Dự án Hải Đăng mua lại EduSoft giá chào mua bao nhiêu và chính sách công ty thế nào?"
    scoped_ids = [allowed["source_id"], *[d["source_id"] for d in distractors[:4]]]
    trace: dict = {}
    with use_pack(OFFICE_PACK):
        got = pipe._retrieve_hybrid(
            q, [], all_chunks, top_k=6, min_score=0.01, source_ids=scoped_ids, trace=trace
        )
    assert all(c.source_id in scoped_ids for c in got)
    assert secret["source_id"] not in {c.source_id for c in got}

    # Subquery BM25 rescue score MUST NOT inject raw BM25 (>1.0) above RRF range (<0.2)
    multi_ids = [allowed["source_id"], secret["source_id"]]
    got_multi = pipe._retrieve_hybrid(
        "Chính sách công ty làm việc thứ mấy và giá chào mua EduSoft bao nhiêu?",
        [], all_chunks, top_k=4, min_score=0.01, source_ids=multi_ids, trace={},
    )
    assert {c.source_id for c in got_multi} == set(multi_ids)
    assert max(c.score or 0.0 for c in got_multi) < 0.25


def test_fix03_worker_context_allocation_keeps_law_2023_c0018_c0019(tmp_path):
    st = SourceStore(str(tmp_path / "ctx_src"))
    law2005_text = "\n\n".join(
        f"# Điều {14 + i} Luật Giao dịch điện tử 2005\n" + ("Quy định Luật Giao dịch điện tử 2005 về chứng thư và chữ ký điện tử cũ trong giao dịch điện tử năm 2005. " * 11)
        for i in range(4)
    )
    # Match real B138.4 Luật 2023 chunking where Điều 22 spans adjacent chunks c0003 & c0004 (~1150 chars each)
    law2023_blocks = [
        "# Luật Giao dịch điện tử 2023\nĐiều 1. Phạm vi điều chỉnh của Luật năm 2023.",
        "Điều 2. Đối tượng áp dụng Luật 2023.",
        "Điều 21. Chứng thư điện tử và lưu trữ.\n" + ("Hệ thống thông tin phục vụ lưu trữ chứng thư điện tử đáp ứng an toàn cấp độ 3. " * 10),
        "# Điều 22. Chữ ký điện tử\n1. Theo loại hình sử dụng, chữ ký điện tử bao gồm:\na) Chữ ký điện tử chuyên dùng;\n" + ("Quy định chi tiết điều kiện bảo đảm an toàn chữ ký điện tử chuyên dùng. " * 10),
        "b) Chữ ký số công cộng;\nc) Chữ ký số chuyên dùng công vụ.\n2. Chữ ký điện tử chuyên dùng bảo đảm an toàn phải được Bộ Thông tin và Truyền thông cấp chứng nhận.",
    ]
    s_2005 = st.import_text("CNTT_Luat_Giao_dich_dien_tu_2005.docx", law2005_text)
    s_2023 = st.import_text("CNTT_Luat_Giao_dich_dien_tu_2023.docx", "\n\n".join(law2023_blocks))
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "ctx_runs")))

    # Reconstruct exact candidate set from R-04 T2: 4 chunks of 2005 (~1000-1180 chars) scored higher than c0003/c0004 of 2023
    c2005 = [SourceChunk(**{**c.__dict__, "score": 0.90 - i * 0.01}) for i, c in enumerate(st.chunks([s_2005["source_id"]]))]
    c2023_all = st.chunks([s_2023["source_id"]])
    c2023 = [SourceChunk(**{**c.__dict__, "score": 0.82 - i * 0.01}) for i, c in enumerate(c2023_all[-2:])]
    candidates = [*c2005, *c2023]
    assert len(candidates) == 6

    captured_prompts: list[str] = []

    class _FakeMultiTaskProvider:
        supports_num_ctx = True
        supports_per_call_output_tokens = True

        async def _dispatch(self, system: str, user: str):
            captured_prompts.append(user)
            if "TASK_PLAN_BUILDER" in system:
                return ProviderResult(
                    json.dumps({
                        "tasks": [
                            {"task_id": "T1", "goal": "So sánh hiệu lực Luật 2005 và Luật 2023", "domain": "business", "depends_on": [], "evidence_needs": ["hiệu lực Luật 2005 và 2023"], "covers_obligations": ["O1"], "covers_concerns": []},
                            {"task_id": "T2", "goal": "nêu 3 loại chữ ký điện tử tại Điều 22 Luật 2023", "domain": "business", "depends_on": [], "evidence_needs": ["Điều 22 Luật 2023"], "covers_obligations": ["O2"], "covers_concerns": []},
                        ],
                    }, ensure_ascii=False),
                    Usage(10, 10),
                )
            if "WORKER" in system:
                return ProviderResult(
                    json.dumps({
                        "status": "COMPLETE",
                        "answer": f"Theo Điều 22 Luật 2023 gồm 3 loại chữ ký điện tử [{c2023[0].chunk_id}].",
                        "citations": [c2023[0].chunk_id],
                        "missing_information": [],
                    }, ensure_ascii=False),
                    Usage(10, 10),
                )
            if "SYNTHESIZER" in system:
                return ProviderResult(json.dumps({"answer": f"Tổng hợp hoàn chỉnh [{c2023[0].chunk_id}]."}, ensure_ascii=False), Usage(10, 10))
            return ProviderResult(json.dumps({
                "obligations": [
                    {"obligation_id": "O1", "description": "So sánh hiệu lực Luật 2005 và 2023", "required": True},
                    {"obligation_id": "O2", "description": "Nêu 3 loại chữ ký điện tử tại Điều 22 Luật 2023", "required": True},
                ],
                "concerns": [],
            }, ensure_ascii=False), Usage(5, 5))

        async def generate(self, *, system, user, **kw):
            return await self._dispatch(system, user)

        async def generate_structured(self, *, system, user, response_schema, **kw):
            return await self._dispatch(system, user)

    # Simulate char_proxy ContextController with R-04 per_task_budget (1400 -> max_chars=4200)
    # Monkeypatch _retrieve_async cleanly to return the exact R-04 candidate pool on T2
    orig_retrieve = pipe._retrieve_async

    async def _fake_ret(product, query, *args, **kwargs):
        if "Điều 22" in query or "3 loại" in query:
            return candidates
        return await orig_retrieve(product, query, *args, **kwargs)

    pipe._retrieve_async = _fake_ret
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("IMPLEMENTATION_PROFILE", "m2")
        mp.setenv("CONTEXT_POLICY", "char_proxy")
        mp.setenv("MAX_CONTEXT_TOKENS", "2800")
        mp.setattr("app.research.pipeline.get_provider", lambda name=None: _FakeMultiTaskProvider())
        run = asyncio.run(pipe.run(
            "So sánh tình trạng hiệu lực pháp lý của Luật Giao dịch điện tử 2005 và Luật Giao dịch điện tử 2023, đồng thời nêu 3 loại chữ ký điện tử tại Điều 22 Luật 2023.",
            condition="C",
            product_mode=True,
            domain_pack=OFFICE_PACK,
        ))

    from app.research.context_controller import ContextController

    t2_ev = next(
        (
            e for e in run["events"]
            if e.get("stage") == "task_retrieval"
            and str(e.get("task_id") or "").upper() == "T2"
            and c2023[0].chunk_id in (e.get("candidates") or [])
        ),
        None,
    )
    assert t2_ev is not None, f"Task 2 retrieval event not found; events={[(e.get('stage'), e.get('task_id')) for e in run['events']]}"
    selected_set = set(t2_ev["selected"])
    assert c2023[0].chunk_id in selected_set, f"Missing Art 22 start chunk in T2 selected: {selected_set}"
    assert c2023[1].chunk_id in selected_set, f"Missing Art 22 continuation chunk in T2 selected: {selected_set}"
    t2_prompt = next(p for p in captured_prompts if "[TASK]nêu 3 loại" in p and "[EVIDENCE]" in p)
    assert "Chữ ký điện tử chuyên dùng" in t2_prompt
    assert "Chữ ký số chuyên dùng công vụ" in t2_prompt

    # Ultra-tiny budget guard: hard cap respected & dropped chunks explicitly traced (never silent truncation)
    tiny_sel, tiny_drop = ContextController(max_chars=1500).select(candidates, query="Điều 22 Luật 2023")
    assert sum(len(c.text) for c in tiny_sel) <= 1500
    assert any(d.get("reason") == "token_budget_proxy" for d in tiny_drop)


def test_fix04_calc_unpunctuated_qty_premise_trap_and_ast_formula_safety():
    # CHECK-A1: both '3.500' and unpunctuated '3500' / '4000' recognized as user case inputs
    ev_price = "Gói HA-Edu >= 3.000 sinh viên giá 260.000.000 đồng; phí triển khai 50.000.000 đồng; công lập giảm 5%."
    st1, _, bad1, _ = check_product_evidence_claims(
        "COMPLETE",
        "Với 3500 sinh viên, tổng tiền năm đầu = [[= 260000000*0.95 + 50000000 ]] đồng.",
        ev_price,
        "Trường đại học công lập mua gói HA-Edu cho 3500 sinh viên, tổng tiền năm đầu?",
        [],
    )
    assert "3500" not in bad1 and st1 == "COMPLETE"

    # CHECK-A2: unverified policy premise ('30 ngày đúng không?') MUST NOT be whitelisted
    st2, _, bad2, _ = check_product_evidence_claims(
        "COMPLETE",
        "Theo nội quy, mỗi nhân viên được nghỉ phép năm 30 ngày.",
        "Điều 12. Nhân viên làm đủ 12 tháng được nghỉ phép năm 12 ngày.",
        "Theo nội quy, mỗi nhân viên được nghỉ 30 ngày đúng không?",
        [],
    )
    assert "30" in bad2 and st2 == "PARTIAL"

    # Mixed BARE calculation with + - and wrong model RHS gets recomputed by AST evaluator
    fixed_calc = apply_calc("Tổng = 260.000.000 * 0,95 + 50.000.000 = 310.000.000 đồng")
    assert "**297.000.000**" in fixed_calc and "310.000.000" not in fixed_calc

    # Ungrounded operand inside [[= ... ]] (e.g. hallucinated 15% = 0.85 discount) MUST be flagged
    st_bad_op, _, bad_ops, _ = check_product_evidence_claims(
        "COMPLETE",
        "Tổng = [[= 260000000*0.85 + 50000000 ]] đồng.",
        ev_price,
        "Trường đại học công lập mua gói HA-Edu cho 3.500 sinh viên?",
        [],
    )
    assert st_bad_op == "PARTIAL" and any(x in bad_ops for x in ("0.85", "85"))


def test_fix05_rule_conclusions_mixed_table_contract_law_mention_and_quiz():
    # CHECK-B1: Contradicted affirmative conclusion MUST be corrected/qualified, NOT left verbatim in body
    st_b1, ans_b1, _, _ = check_product_evidence_claims(
        "COMPLETE",
        "Đơn nghỉ phép này có thỏa mãn quy định phòng Kinh doanh.\n- Nộp trước 2 ngày (< 5 ngày): không thỏa mãn.\n- Bàn giao công việc: chưa có.",
        "Sổ tay KD: nghỉ 5 ngày phải báo trước 5 ngày và bàn giao công việc.",
        "Đơn này có đúng nội quy không?",
        [],
    )
    assert st_b1 == "PARTIAL"
    assert "này có thỏa mãn quy định" not in ans_b1.lower()

    # CHECK-B2: Valid mixed rejection table (item MET + overall NOT_MET) MUST NOT trigger contradiction banner
    valid_mixed = (
        "Đơn xin nghỉ phép **chưa đủ điều kiện** phê duyệt.\n\n"
        "| Tiêu chí | Đối chiếu |\n|---|---|\n"
        "| Thời gian báo trước 5 ngày | Đáp ứng (gửi trước 6 ngày) |\n"
        "| Bàn giao khách hàng | Không đạt (chưa bàn giao) |"
    )
    m_b2: list[str] = []
    _, ans_b2, _, _ = check_product_evidence_claims(
        "PARTIAL", valid_mixed,
        "Cần báo trước 5 ngày và bàn giao khách hàng.",
        "Đơn này có đúng quy định không?", m_b2,
    )
    assert not any("contradictory" in x for x in m_b2)
    assert "Cảnh báo nhất quán" not in ans_b2

    # CHECK-E1: Contract chunk mentioning "Luật Thương mại" by name is NOT an in-corpus statutory code
    ev_contract = [
        SourceChunk(
            chunk_id="src_hd07_c0000",
            source_id="src_hd07",
            source_name="HA_07_Hop_dong.docx",
            text="Điều 9. Phạt vi phạm 30%. Mọi tranh chấp giải quyết theo Luật Thương mại.",
            index=0,
            provenance={"doc_type": "contract"},
        )
    ]
    ans_e1 = "Điều 9 hợp đồng không vi phạm Luật Thương mại / Bộ luật Dân sự. Phạt Bên A là 30%."
    m_e1: list[str] = []
    st_e1, out_e1, _, _ = check_product_evidence_claims(
        "COMPLETE", ans_e1, ev_contract[0].text,
        "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không?",
        m_e1, evidence_chunks=ev_contract,
    )
    assert st_e1 == "PARTIAL"
    assert any("external law" in x.lower() for x in m_e1)
    assert "không vi phạm luật thương mại" not in out_e1.lower()

    # CHECK-E2: Quiz filters off-topic questions rather than keeping them alongside warning
    quiz_chunks = [
        SourceChunk("src_tt_c0002", "src_tt", "TT08.docx", "Điều 2. Thay thế Quyết định 25/2006/QĐ-BGDĐT.", 2),
        SourceChunk("src_tt_c0011", "src_tt", "TT08.docx", "Điều 11. Cảnh báo học tập dưới 0,8 và 1,0.", 11),
        SourceChunk("src_tt_c0014", "src_tt", "TT08.docx", "Điều 14. Tốt nghiệp và hạ hạng 5%.", 14),
    ]

    class _MixedQuizProv:
        async def generate_structured(self, *, system, user, response_schema, **kw):
            return ProviderResult(json.dumps({
                "items": [
                    {
                        "question": "Mức cảnh báo học tập ở học kỳ đầu là bao nhiêu?",
                        "options": ["0,8", "1,0", "1,5", "2,0"],
                        "answer": 0,
                        "explanation": "Điều 11 quy định dưới 0,8.",
                        "citation": "src_tt_c0011",
                    },
                    {
                        "question": "Quy chế thay thế quyết định nào?",
                        "options": ["25/2006", "43/2007", "10/2018", "01/2020"],
                        "answer": 0,
                        "explanation": "Điều 2.",
                        "citation": "src_tt_c0002",
                    },
                ]
            }, ensure_ascii=False), Usage(5, 5))

    q_out = asyncio.run(generate_items(_MixedQuizProv(), "quiz", quiz_chunks, 2, topic="cảnh báo học tập"))
    assert q_out["topic_mismatch_count"] == 1
    assert len(q_out["items"]) == 1
    assert "cảnh báo" in q_out["items"][0]["question"].lower()
    assert q_out.get("requested_count") == 2 and q_out.get("returned_count") == 1
