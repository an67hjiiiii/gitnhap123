"""GIT-01 Targeted Fixes — Test-First RED -> GREEN Verification (Zero Ollama).

Covers:
- FIX-01 (R-05 Retrieval Regression): Preserve from_bm25_only / subquestion anchors when subquery_rescue
  inserts another subquestion's chunk under tight top_k, across single-source and multi-source ACL scope.
- FIX-02 (R-08A Synthesizer Guardrail Bypass): Run check_product_evidence_claims after synthesis in Product Mode
  so unverified external law compliance verdicts (including **bold** Markdown) or rule contradictions are
  never re-emitted in streamed frames or persisted answers, while preserving Research Mode A/B/C & NO_EVIDENCE.
- FIX-03 (R-02 Markdown Rule Conclusion): Normalize Markdown emphasis (* / ** / _) in _reconcile_rule_conclusions
  and handle Vietnamese internal-rule verdicts like '**có đúng nội quy và quy định ...**' for MET / NOT_MET / UNKNOWN.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from app.core.answer_checks import (
    IMG_MARK,
    check_product_evidence_claims,
)
from app.core.types import ProviderResult, RunMetrics, SourceChunk, TaskResult, Usage
from app.providers.fake import FakeProvider
from app.research.pipeline import ResearchPipeline
from app.research.registry import OFFICE_PACK, use_pack
from app.research.synthesizer import synthesize
from app.storage.conversation_store import ConversationStore
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _chunk(src: str, name: str, idx: int, text: str, *, score: float = 0.5, doc_type: str = "other") -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{src}_c{idx:04d}",
        source_id=src,
        source_name=name,
        text=text,
        index=idx,
        score=score,
        provenance={"doc_type": doc_type},
    )


# ==============================================================================
# FIX-01 — R-05 RETRIEVAL EVIDENCE REGRESSION
# ==============================================================================


class _MockVectorIndex:
    """Deterministic vector candidate index returning fixed top chunks (simulating R-05 vector miss)."""

    def __init__(self, ranked_cids: list[str], score: float = 0.85):
        self._ranked = ranked_cids
        self._score = score

    def candidates(self, query: str, limit: int = 10, source_ids=None):
        return [
            SimpleNamespace(payload={"chunk_id": cid}, score=max(0.1, self._score - i * 0.01))
            for i, cid in enumerate(self._ranked[:limit])
        ]


def test_fix01_subquery_rescue_does_not_evict_bm25_only_or_first_subquestion_anchor(tmp_path):
    st = SourceStore(str(tmp_path / "r05_src"))
    # Construct 10 distinct chunks in 1 legal document:
    # - chunk 1 holds "72 giờ" (missed by vector, rescued via from_bm25_only)
    # - chunks 2..8 match vector + "bộ công an / xử phạt / báo cáo" filler
    # - chunk 9 holds effective date "01 tháng 7 năm 2023" (missed by fused, rescued via subquery_rescue)
    filler_common = "Thông báo vi phạm dữ liệu cá nhân gửi Bộ Công an Nghị định bảo vệ dữ liệu cá nhân 60 ngày xử phạt báo cáo. "
    pad = filler_common * 11  # >1100 chars so each Điều stays in its own chunk
    blocks = [
        f"# Thông báo vi phạm Bộ Công an\n{pad}",
        "Khoản 1. Tổ chức, cá nhân phải thông báo cho Bộ Công an trong thời hạn 72 giờ kể từ khi phát hiện hành vi vi phạm dữ liệu cá nhân.\n" + ("Quy định thông báo chậm nhất 72 giờ kể từ khi phát hiện vi phạm dữ liệu cá nhân. " * 14),
        f"# Thông báo vi phạm Bộ Công an 30\n{pad}",
        f"# Thông báo vi phạm Bộ Công an 31\n{pad}",
        f"# Thông báo vi phạm Bộ Công an 32\n{pad}",
        f"# Thông báo vi phạm Bộ Công an 40\n{pad}",
        f"# Thông báo vi phạm Bộ Công an 41\n{pad}",
        f"# Thông báo vi phạm Bộ Công an 42\n{pad}",
        f"# Thông báo vi phạm Bộ Công an 42b\n{pad}",
        "Điều 43. Hiệu lực thi hành: Văn bản này có hiệu lực thi hành từ ngày 01 tháng 7 năm 2023.",
    ]
    s_dec = st.import_text("LD_Nghi_dinh_13_2023.pdf", "\n\n".join(blocks))
    chunks = st.chunks([s_dec["source_id"]])
    assert len(chunks) >= 10
    cid_72h = next(c.chunk_id for c in chunks if "72 giờ" in c.text)
    cid_eff = next(c.chunk_id for c in chunks if "01 tháng 7 năm 2023" in c.text)

    # Vector returns the 8 filler chunks (NOT cid_72h and NOT cid_eff)
    vec_cids = [c.chunk_id for c in chunks if c.chunk_id not in {cid_72h, cid_eff}][:8]
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "r05_runs")), candidate_index=_MockVectorIndex(vec_cids))

    q = "Khi phát hiện vi phạm dữ liệu cá nhân phải thông báo cho Bộ Công an trong thời hạn bao nhiêu giờ và Nghị định có hiệu lực từ ngày nào?"
    trace: dict = {}
    with use_pack(OFFICE_PACK):
        got = pipe._retrieve_hybrid(
            q, [SimpleNamespace(text=q)], chunks, top_k=8, min_score=0.01, source_ids=[s_dec["source_id"]], trace=trace
        )
    got_ids = [c.chunk_id for c in got]
    # Hard budget preserved, AND BOTH 72h (from_bm25_only/subq1) and effective date (subq2 rescue) MUST survive!
    assert len(got_ids) <= 8
    assert cid_72h in got_ids, f"from_bm25_only / subq1 chunk {cid_72h} evicted from {got_ids}; trace={trace}"
    assert cid_eff in got_ids, f"subquery_rescue effective-date chunk {cid_eff} missing from {got_ids}; trace={trace}"


def test_fix01_multi_source_subquery_rescue_preserves_acl_scope_and_budget(tmp_path):
    st = SourceStore(str(tmp_path / "r05_multi"))
    s_hr = st.import_text("Chinh_sach_nghi.md", "Điều 5. Nhân viên nghỉ trên 3 ngày phải báo trước 5 ngày làm việc.")
    s_pay = st.import_text("Bang_luong.md", "Lương cơ bản tháng của Trần An là 20.000.000 đồng, chia 26 ngày công.")
    s_secret = st.import_text("Mat_Kinh_doanh.md", "MẬT: Thưởng giám đốc 999.000.000 đồng.")
    all_chunks = st.chunks()
    cid_hr = st.chunks([s_hr["source_id"]])[0].chunk_id
    cid_pay = st.chunks([s_pay["source_id"]])[0].chunk_id
    cid_secret = st.chunks([s_secret["source_id"]])[0].chunk_id

    # Vector index falsely suggests secret chunk (outside source_ids) plus pay chunk
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "r05_multi_runs")), candidate_index=_MockVectorIndex([cid_secret, cid_pay]))
    with use_pack(OFFICE_PACK):
        got = pipe._retrieve_hybrid(
            "Nghỉ trên 3 ngày báo trước mấy ngày và lương cơ bản Trần An bao nhiêu?",
            [], all_chunks, top_k=2, min_score=0.01,
            source_ids=[s_hr["source_id"], s_pay["source_id"]], trace={},
        )
    got_ids = {c.chunk_id for c in got}
    assert len(got) <= 2
    assert cid_secret not in got_ids
    assert {cid_hr, cid_pay} == got_ids


# ==============================================================================
# FIX-02 — R-08A SYNTHESIZER GUARDRAIL BYPASS (HIGHEST PRIORITY)
# ==============================================================================


def test_fix02_synthesizer_blocks_unverified_external_law_and_rule_contradictions_with_streaming(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PRODUCT_REVIEWER", "off")
    monkeypatch.setenv("PRODUCT_AGENT_TOOLS", "off")
    monkeypatch.setenv("PRODUCT_TASK_PARALLEL", "1")

    from fastapi.testclient import TestClient
    from app import main as app_main

    st = SourceStore(str(tmp_path / "r08a_src"))
    imp = st.import_text(
        "HD_03_Phan_mem.docx",
        "HỢP ĐỒNG CUNG CẤP PHẦN MỀM (tham chiếu Luật Thương mại số 36/2005/QH11).\n"
        "Điều 9.1: Phạt 30% tổng giá trị hợp đồng đối với Bên A.\n"
        "Điều 9.2: Tổng bồi thường của Bên B tối đa 5.000.000 đồng.",
    )
    sid = imp["source_id"]
    cid = st.chunks()[0].chunk_id
    cs = ConversationStore(str(tmp_path / "r08a_convs"))
    pipe = ResearchPipeline(st, RunStore(str(tmp_path / "r08a_runs")))

    class _SynthBypassProv(FakeProvider):
        supports_per_call_output_tokens = True
        supports_num_ctx = True

        async def _reply(self, system: str):
            if "OBLIGATION" in system or "CONCERN" in system:
                return ProviderResult(json.dumps({
                    "obligations": [
                        {"obligation_id": "O1", "description": "Kiểm tra vi phạm Luật Thương mại / Bộ luật Dân sự", "required": True},
                        {"obligation_id": "O2", "description": "Nêu rủi ro cho Bên A", "required": True},
                    ],
                    "concerns": [],
                }, ensure_ascii=False), Usage(5, 5))
            if "TASK_PLAN_BUILDER" in system:
                return ProviderResult(json.dumps({
                    "tasks": [
                        {"task_id": "T1", "goal": "Đối chiếu Luật Thương mại / Bộ luật Dân sự", "domain": "business", "depends_on": [], "evidence_needs": ["Điều 9"], "covers_obligations": ["O1"], "covers_concerns": []},
                        {"task_id": "T2", "goal": "Liệt kê rủi ro Bên A tại Điều 9", "domain": "business", "depends_on": [], "evidence_needs": ["phạt 30%"], "covers_obligations": ["O2"], "covers_concerns": []},
                    ]
                }, ensure_ascii=False), Usage(5, 5))
            if "WORKER" in system:
                return ProviderResult(json.dumps({
                    "status": "COMPLETE",
                    "answer": f"Điều 9 quy định phạt 30% và giới hạn bồi thường 5.000.000 đồng [{cid}].",
                    "citations": [cid],
                    "missing_information": [],
                }, ensure_ascii=False), Usage(5, 5))
            if "SYNTHESIZER" in system:
                # Reproduces exact B138.4B R-08A bypass: bold **không vi phạm** Luật Thương mại hoặc Bộ luật Dân sự
                return ProviderResult(json.dumps({
                    "answer": (
                        f"Điều 9.1 phạt 30% giá trị hợp đồng [{cid}]. "
                        "Điều khoản này **không vi phạm** Luật Thương mại hoặc Bộ luật Dân sự theo quy định hiện có."
                    ),
                }, ensure_ascii=False), Usage(5, 5))
            return ProviderResult("{}", Usage(2, 2))

        async def generate(self, *, system, user, **kw):
            return await self._reply(system)

        async def generate_structured(self, *, system, user, response_schema, **kw):
            return await self._reply(system)

    monkeypatch.setattr(app_main, "current_principal", lambda req: {"user_id": "u_r08a", "role": "staff"})
    monkeypatch.setattr(app_main, "owner_source_store", lambda u: st)
    monkeypatch.setattr(app_main, "owner_conversation_store", lambda u: cs)
    monkeypatch.setattr(app_main, "owner_pipeline", lambda u, cid_arg=None: pipe)
    monkeypatch.setattr(app_main, "log_secret_access", lambda *a, **k: None)

    q = f"Điều khoản Điều 9 có vi phạm Luật Thương mại / Bộ luật Dân sự không và rủi ro cho bên A là gì?\n\n{IMG_MARK}\nĐiều 9 phạt 30%."
    client = TestClient(app_main.app)
    with patch("app.research.pipeline.get_provider", return_value=_SynthBypassProv()):
        resp = client.post("/api/chat/stream", json={"message": q, "product_mode": True, "source_ids": [sid]})

    assert resp.status_code == 200
    frames = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
    answer_frames = [f for f in frames if f.get("type") == "answer"]
    done_frame = next(f for f in frames if f.get("type") == "done")
    assert len(answer_frames) == 1, f"Expected single buffered answer frame, got {answer_frames}"
    streamed_text = answer_frames[0].get("answer") or answer_frames[0].get("text") or ""
    persisted_text = done_frame["run"]["answer"]

    # 1. Both streamed frame and persisted run MUST strip the false external-law claim & emit scoped notice
    for text in (streamed_text, persisted_text):
        assert "không vi phạm** Luật Thương mại" not in text
        assert "không vi phạm Luật Thương mại" not in text
        assert "chưa đủ căn cứ" in text.lower()
        assert "chưa được nạp" in text.lower()

    # 2. Status MUST NOT remain COMPLETE when out-of-corpus law compliance claim was emitted
    assert done_frame["run"]["status"] == "PARTIAL"

    # 3. Conversation persistence matches the sanitized answer
    conv_id = done_frame.get("conversation_id") or done_frame["run"]["conversation_id"]
    conv = cs.get(conv_id)
    msgs = conv["messages"] if isinstance(conv, dict) else conv.messages
    assistant_msgs = [m["content"] for m in msgs if str(m.get("role", "")).upper() == "ASSISTANT"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0] == persisted_text

    # 4. Research Mode (max_output_tokens=None) stays completely untouched by Product synthesizer validation
    research_text = asyncio.run(synthesize(
        _SynthBypassProv(),
        q,
        [TaskResult("T1", "business", "COMPLETE", "T1 ans", [cid], [cid], [])],
        RunMetrics(),
        max_output_tokens=None,
    ))
    assert "**không vi phạm** Luật Thương mại" in research_text


# ==============================================================================
# FIX-03 — R-02 MARKDOWN RULE CONCLUSION
# ==============================================================================


def test_fix03_markdown_rule_conclusion_reconciles_not_met_without_breaking_met_or_mixed_tables():
    ev = "Nội quy: Nghỉ trên 3 ngày phải báo trước 5 ngày làm việc và có người nhận bàn giao khách hàng."
    q = "Đơn nghỉ phép của Phạm Minh Hải có đúng nội quy và quy định phòng Kinh doanh không?"

    # 1. Exact R-02 NOT_MET failure: **có đúng nội quy và quy định phòng Kinh doanh** in conclusion
    r02_bad = (
        "Đơn nghỉ phép yêu cầu nghỉ 5 ngày làm việc nhưng ngày gửi đơn cách ngày nghỉ ít hơn 5 ngày và chưa có người nhận bàn giao.\n\n"
        "### Kết luận\n\n"
        "Đơn nghỉ phép của Phạm Minh Hải **có đúng nội quy và quy định phòng Kinh doanh**."
    )
    st1, out1, _, _ = check_product_evidence_claims("COMPLETE", r02_bad, ev, q, [])
    assert st1 == "PARTIAL"
    assert "có đúng nội quy" not in out1
    assert "chưa đủ điều kiện kết luận đạt" in out1
    assert "Cảnh báo nhất quán" in out1

    # 2. Other Markdown wrappers: *hợp lệ*, _đạt yêu cầu_, **đủ điều kiện**
    other_bad = (
        "Nhân sự vi phạm thời hạn báo trước (2 ngày < 5 ngày).\n\n"
        "Tóm lại hồ sơ *hợp lệ* và _đạt yêu cầu_, tức là **đủ điều kiện**."
    )
    st2, out2, _, _ = check_product_evidence_claims("COMPLETE", other_bad, ev, q, [])
    assert st2 == "PARTIAL"
    assert "*hợp lệ*" not in out2 and "_đạt yêu cầu_" not in out2 and "**đủ điều kiện**" not in out2

    # 3. MET case (all conditions satisfied, NO violation / unmet negative signals): stays COMPLETE untouched
    met_ans = (
        "Đơn gửi đúng thời hạn quy định và đã bàn giao đầy đủ công việc.\n\n"
        "### Kết luận\n\n"
        "Đơn nghỉ phép của Phạm Minh Hải **có đúng nội quy và quy định phòng Kinh doanh** và **hợp lệ**."
    )
    st3, out3, _, _ = check_product_evidence_claims("COMPLETE", met_ans, ev, q, [])
    assert st3 == "COMPLETE"
    assert "**có đúng nội quy và quy định phòng Kinh doanh**" in out3
    assert "Cảnh báo nhất quán" not in out3

    # 4. UNKNOWN / mixed-condition comparison table & bullets without contradictory affirmative verdict
    mixed_table = (
        "### Đối chiếu điều kiện\n\n"
        "| Tiêu chí | Tình trạng |\n"
        "|---|---|\n"
        "| Thời gian làm việc | Hợp lệ |\n"
        "| Bàn giao khách hàng | Chưa đáp ứng |\n\n"
        "- Mục 1: đạt yêu cầu.\n"
        "- Mục 2: chưa có người nhận bàn giao nên không đủ điều kiện."
    )
    st4, out4, _, _ = check_product_evidence_claims("COMPLETE", mixed_table, ev, q, [])
    assert st4 == "COMPLETE"
    assert "Cảnh báo nhất quán" not in out4
