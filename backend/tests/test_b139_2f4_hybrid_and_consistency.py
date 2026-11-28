"""B139.2F4 Test-First RED/GREEN suite: Hybrid Retrieval Recovery & Final Targeted Defect Closure.

Covers:
- FIX-01 (P0 / INFRA-02 / RET-03): Conservative Ollama `:latest` embedding alias compatibility,
  Qdrant hybrid retrieval recovery (`vector_candidates > 0`, paraphrase recall, ACL isolation),
  and strict rejection of mismatched tags/models/dimensions.
- FIX-02 (G-01): Score-prioritized evidence completeness (`HA_02_c0002`), missing discount-policy
  guardrail (no silent `310M` VERIFIED when requested customer discount rule is unretrieved),
  and stripping unsupported approver claims on UNKNOWN/CONFLICT.
- FIX-03 (R-02): Eliminating `"chưa được vi phạm"` handover contradiction, single consistency
  warning banner (`answer_checks` + `verified_reasoning`), general lookup preservation, and
  `stream == final == persisted` parity.
- FIX-04 (R-08A): Separating legal compliance review questions (containing quoted OCR numbers)
  from `_needs_calculation`, preventing double legal-scope substitution, keeping genuine
  calculation queries active, and recovering relevant contract clauses (`HA_07_c0003`).
- Independent non-Hai-Au / non-BLLD held-out domain scenarios (tracked explicitly).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.answer_checks import IMG_MARK, check_product_evidence_claims
from app.core.approval_authority import ApprovalResolution, reconcile_approval_in_answer, resolve_approval_authority
from app.core.formula_engine import CalcStatus, execute_formula, select_formula
from app.core.types import SourceChunk
from app.providers.base import ProviderResult
from app.research.pipeline import ResearchPipeline
from app.research.verified_reasoning import _needs_calculation, verify_and_reconcile_answer
from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.embeddings import OllamaEmbedder
from app.retrieval.evidence_completeness import complete_missing_evidence
from app.retrieval.text import estimate_tokens
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore
from app.storage.vector_store import QdrantVectorStore, VectorRecord


# ---------------------------------------------------------------------------
# Helpers (offline deterministic sparse-semantic embedder for Qdrant tests)
# ---------------------------------------------------------------------------

class _ConceptParaphraseEmbedder:
    """Offline 768-d embedder encoding semantic concept axes (0 keyword overlap between paraphrase & chunk)."""

    dimension: int = 768

    def __init__(self, model: str = "nomic-embed-text:latest", version_override: str | None = None) -> None:
        self.model = model
        self._version_override = version_override

    @property
    def version(self) -> str:
        return self._version_override or OllamaEmbedder(model=self.model, dimension=self.dimension).version

    def _vec(self, text: str) -> list[float]:
        cf = (text or "").casefold()
        v = [0.0] * self.dimension
        # Concept axis 0: data breach notification deadline
        if any(k in cf for k in ("rò rỉ", "sự cố an toàn thông tin", "vi phạm quy định bảo vệ dữ liệu", "báo cáo cơ quan", "thông báo cho bộ công an", "72 giờ")):
            v[0] += 1.0
        # Concept axis 1: discount & public school policy
        if any(k in cf for k in ("chiết khấu", "ưu đãi", "cơ quan nhà nước", "trường công lập", "thẩm quyền phê duyệt")):
            v[1] += 1.0
        # Concept axis 2: IT cloud uptime SLA & credit
        if any(k in cf for k in ("thời gian hoạt động", "uptime", "gián đoạn dịch vụ", "hoàn phí", "sla")):
            v[2] += 1.0
        # Small non-zero fallback norm so cosine similarity is always well-defined
        v[767] = 0.05
        return v

    def embed(self, text: str) -> list[float]:
        return self._vec(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def _make_indexed_qdrant_store(
    tmp_path: Path,
    chunks_with_versions: list[tuple[SourceChunk, str]],
) -> QdrantVectorStore:
    client = QdrantClient(path=str(tmp_path / "qdrant_scratch"))
    store = QdrantVectorStore(path=str(tmp_path / "qdrant_scratch"), collection="qa_b139_2f4_test", vector_size=768, client=client)
    emb = _ConceptParaphraseEmbedder(model="nomic-embed-text")
    records: list[VectorRecord] = []
    for ch, ver in chunks_with_versions:
        vec = emb.embed(ch.text)
        prov = ch.provenance or {}
        records.append(
            VectorRecord(
                id=f"usr_qa:{ch.chunk_id}",
                vector=vec,
                payload={
                    "chunk_id": ch.chunk_id,
                    "source_id": ch.source_id,
                    "source_name": ch.source_name,
                    "chunk_index": ch.index,
                    "embedding_version": ver,
                    "owner_user_id": prov.get("owner_user_id", "usr_qa"),
                    "visibility": prov.get("visibility", "private"),
                },
            )
        )
    store.upsert(records)
    return store


# ---------------------------------------------------------------------------
# FIX-01: Embedding identity & Qdrant hybrid retrieval recovery
# ---------------------------------------------------------------------------

def test_fix01_ollama_latest_alias_compatibility_matrix() -> None:
    from app.retrieval.embeddings import are_embedding_versions_compatible

    ok_untagged_to_latest, reason1 = are_embedding_versions_compatible(
        "ollama:nomic-embed-text:768", "ollama:nomic-embed-text:latest:768"
    )
    ok_latest_to_untagged, _ = are_embedding_versions_compatible(
        "ollama:nomic-embed-text:latest:768", "ollama:nomic-embed-text:768"
    )
    ok_exact, _ = are_embedding_versions_compatible(
        "ollama:nomic-embed-text:latest:768", "ollama:nomic-embed-text:latest:768"
    )
    assert ok_untagged_to_latest is True, reason1
    assert ok_latest_to_untagged is True
    assert ok_exact is True

    # Conservative rejections: different tag, different model, different backend, different dimension
    assert are_embedding_versions_compatible("ollama:nomic-embed-text:v1.5:768", "ollama:nomic-embed-text:latest:768")[0] is False
    assert are_embedding_versions_compatible("ollama:bge-m3:768", "ollama:nomic-embed-text:768")[0] is False
    assert are_embedding_versions_compatible("local-hash-embedding-v1", "ollama:nomic-embed-text:768")[0] is False
    assert are_embedding_versions_compatible("ollama:nomic-embed-text:768", "ollama:nomic-embed-text:latest:384")[0] is False


def test_fix01_qdrant_recovers_zero_overlap_paraphrase_and_reports_hybrid_telemetry(tmp_path: Path) -> None:
    target = SourceChunk(
        chunk_id="src_nd13_c0032",
        source_id="src_nd13",
        source_name="NĐ 13/2023/NĐ-CP",
        text="Điều 23. Bên kiểm soát dữ liệu thông báo cho Bộ Công an chậm nhất 72 giờ kể từ khi phát sinh sự cố an toàn thông tin cá nhân.",
        index=32,
        provenance={"owner_user_id": "usr_qa", "visibility": "private"},
    )
    distractor = SourceChunk(
        chunk_id="src_other_c0001",
        source_id="src_other",
        source_name="Tài liệu khác",
        text="Quy định chung về lưu trữ hồ sơ hành chính nội bộ hàng năm.",
        index=1,
        provenance={"owner_user_id": "usr_qa", "visibility": "private"},
    )
    unauth = SourceChunk(
        chunk_id="src_secret_c0001",
        source_id="src_secret",
        source_name="Bí mật không thuộc phạm vi",
        text="Sự cố an toàn thông tin mật nội bộ cần báo cáo trong 12 giờ.",
        index=1,
        provenance={"owner_user_id": "usr_other", "visibility": "private"},
    )
    store = _make_indexed_qdrant_store(
        tmp_path,
        [
            (target, "ollama:nomic-embed-text:768"),
            (distractor, "ollama:nomic-embed-text:768"),
            (unauth, "ollama:nomic-embed-text:768"),
        ],
    )
    cindex = CandidateIndex(source_store=None, vector_store=store, owner_user_id="usr_qa", embedder=_ConceptParaphraseEmbedder(model="nomic-embed-text:latest"))
    pipe = ResearchPipeline(SourceStore(str(tmp_path / "src")), RunStore(str(tmp_path / "runs")), candidate_index=cindex, retrieval_backend="qdrant")

    # Zero lexical keyword overlap ("Doanh nghiệp cần báo cáo cơ quan chức năng..." vs "Bên kiểm soát... Bộ Công an... 72 giờ")
    query = "Khi xảy ra rò rỉ dữ liệu khách hàng thì đơn vị xử lý phải trình diện cơ quan nào và trong bao lâu?"
    trace: dict[str, Any] = {}
    selected = pipe._retrieve_candidates(
        query,
        [target, distractor, unauth],
        top_k=3,
        min_score=0.0,
        source_ids=["src_nd13", "src_other"],
        fallback_trace=trace,
        hybrid=True,
    )
    ids = [c.chunk_id for c in selected]
    assert "src_nd13_c0032" in ids
    assert "src_secret_c0001" not in ids  # ACL/scope strictly respected
    assert trace["vector_candidates"] > 0
    assert trace["retrieval_mode"] == "hybrid_vector_plus_bm25"


def test_fix01_incompatible_version_falls_back_to_bm25_telemetry(tmp_path: Path) -> None:
    chunk = SourceChunk(
        chunk_id="src_sla_c0001",
        source_id="src_sla",
        source_name="SLA Policy",
        text="Mức cam kết uptime tối thiểu 99.9% hàng tháng, hoàn phí nếu dưới ngưỡng.",
        index=1,
        provenance={"owner_user_id": "usr_qa", "visibility": "private"},
    )
    store = _make_indexed_qdrant_store(tmp_path, [(chunk, "ollama:bge-m3:768")])
    cindex = CandidateIndex(source_store=None, vector_store=store, owner_user_id="usr_qa", embedder=_ConceptParaphraseEmbedder(model="nomic-embed-text:latest"))
    pipe = ResearchPipeline(SourceStore(str(tmp_path / "src")), RunStore(str(tmp_path / "runs")), candidate_index=cindex, retrieval_backend="qdrant")

    trace: dict[str, Any] = {}
    selected = pipe._retrieve_candidates(
        "Mức cam kết uptime SLA tối thiểu hàng tháng là bao nhiêu?",
        [chunk],
        top_k=2,
        min_score=0.0,
        source_ids=["src_sla"],
        fallback_trace=trace,
        hybrid=True,
    )
    assert [c.chunk_id for c in selected] == ["src_sla_c0001"]
    assert trace["vector_candidates"] == 0
    assert trace["retrieval_mode"] == "bm25_fallback"


# ---------------------------------------------------------------------------
# FIX-02: G-01 Policy Completeness, Discount-Missing Guard & Approval Authority
# ---------------------------------------------------------------------------

def _ha_g01_chunks() -> tuple[list[SourceChunk], list[SourceChunk]]:
    c_ha02_0 = SourceChunk(
        "src_79ae8c1e4c8cbd14_c0000", "src_79ae8c1e4c8cbd14", "HA_02",
        "## 1. Bảng giá niêm yết\n| Sản phẩm | Gói / Phân hạng | Đơn giá (VNĐ) | Đơn vị tính | Phí triển khai một lần |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| HA-Edu | Trường từ 3.000 sinh viên | 260.000.000 | năm | 50.000.000 |\n", 0
    )
    c_ha02_2 = SourceChunk(
        "src_79ae8c1e4c8cbd14_c0002", "src_79ae8c1e4c8cbd14", "HA_02",
        "## 4. Chính sách chiết khấu và thẩm quyền phê duyệt\n"
        "- Cơ quan nhà nước và trường công lập: giảm 5% trên giá niêm yết của gói (không giảm phí triển khai cố định).\n"
        "| Mức chiết khấu trên giá niêm yết | Cấp phê duyệt |\n"
        "| --- | --- |\n"
        "| 0% - 5% | Nhân viên Kinh doanh tự quyết |\n"
        "| Trên 5% - 15% | Trưởng phòng Kinh doanh |\n"
        "| Trên 15% - 25% | Giám đốc Kinh doanh |\n", 2
    )
    # Distractor example from HA_03 and verbose chunks from alphabetically earlier source IDs
    c_ha03_0 = SourceChunk(
        "src_3808d1e8cd06f583_c0000", "src_3808d1e8cd06f583", "HA_03",
        "Ví dụ tháng 8: KD05 Đỗ Mai Linh ký hợp đồng HA-Edu Đại học Duyên Hải chiết khấu 22% được Giám đốc Kinh doanh phê duyệt.", 0
    )
    c_ha01_0 = SourceChunk(
        "src_00d7e739cefcc3c2_c0000", "src_00d7e739cefcc3c2", "HA_01",
        "## Nội quy công ty Hải Âu\nQuy định về tác phong làm việc, giờ làm việc hành chính và thẻ nhân viên văn phòng. " + ("chi tiết quy định hành chính văn phòng " * 40), 0
    )
    c_ha05_1 = SourceChunk(
        "src_59874741237fcaf4_c0001", "src_59874741237fcaf4", "HA_05",
        "## Báo cáo công nợ khách hàng\nTổng hợp hợp đồng năm trước và công nợ thanh toán từng quý. " + ("hợp đồng thanh toán từng quý công nợ " * 40), 1
    )
    c_ha04_3 = SourceChunk(
        "src_884132b48364517c_c0003", "src_884132b48364517c", "HA_04",
        "## Mẫu biên bản nghiệm thu\nMẫu checklist bàn giao phần mềm và hướng dẫn lưu trữ chứng từ kế toán. " + ("chứng từ kế toán bàn giao phần mềm " * 40), 3
    )
    # Selected initial 7 chunks (total tokens tight below 4000 so only ~1-4 chunks fit!)
    sel_a = SourceChunk("src_884132b48364517c_c0000", "src_884132b48364517c", "HA_04", "Giới thiệu sản phẩm HA-Edu và tổng quan hợp đồng. " + ("tổng quan triển khai hợp đồng " * 80), 0)
    sel_b = SourceChunk("src_59874741237fcaf4_c0000", "src_59874741237fcaf4", "HA_05", "Quy trình xuất hóa đơn và theo dõi hợp đồng năm. " + ("quy trình theo dõi hợp đồng " * 80), 0)
    sel_c = SourceChunk("src_3808d1e8cd06f583_c0001", "src_3808d1e8cd06f583", "HA_03", "KPI kinh doanh Q3 của đội ngũ bán hàng khu vực. " + ("doanh số gói phần mềm năm " * 80), 1)
    selected = [sel_a, sel_b, sel_c, c_ha02_0]
    pool = [*selected, c_ha01_0, c_ha03_0, c_ha05_1, c_ha04_3, c_ha02_2]
    return selected, pool


def test_fix02_g01_completeness_recovers_discount_and_strips_hallucinated_approver() -> None:
    selected, pool = _ha_g01_chunks()
    q_g01 = (
        "Trường đại học Bách Khoa Miền Trung là trường công lập muốn mua gói HA-Edu cho 4.000 sinh viên và ký hợp đồng 1 năm "
        "(không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm phí triển khai là bao nhiêu và ai phê duyệt mức chiết khấu này?"
    )
    # Tight token budget allowing ~2 added chunks so alphabetically earlier HA_01/HA_03/HA_05 would starve HA_02_c0002 unless relevance-ranked
    used_now = sum(estimate_tokens(c.text) for c in selected)
    ha02_c2_cost = estimate_tokens(next(c for c in pool if c.chunk_id == "src_79ae8c1e4c8cbd14_c0002").text)
    rescued, info = complete_missing_evidence(
        query=q_g01,
        selected=selected,
        all_chunks=pool,
        allowed_source_ids={c.source_id for c in pool},
        max_tokens=used_now + ha02_c2_cost + 120,
        max_added=4,
    )
    rescued_ids = [c.chunk_id for c in rescued]
    assert "src_79ae8c1e4c8cbd14_c0002" in rescued_ids, f"HA_02_c0002 starved! info={info}"

    # Verify full calculation & approval authority once HA_02_c0002 is recovered
    vr = verify_and_reconcile_answer(
        query=q_g01,
        chunks=rescued,
        llm_answer="Tổng cộng là 310.000.000 VND. Mức chiết khấu được phê duyệt bởi Giám đốc Kinh doanh [src_3808d1e8cd06f583_c0000].",
        status="COMPLETE",
        allowed_source_ids={c.source_id for c in pool},
    )
    assert vr["verified_value"] == "297000000"
    assert "297.000.000" in vr["final_answer"]
    assert "Nhân viên Kinh doanh" in vr["final_answer"]
    assert "Giám đốc Kinh doanh" not in vr["final_answer"]


def test_fix02_missing_discount_policy_blocks_silent_zero_and_strips_wrong_approver() -> None:
    # Only tier table + distractor KPI example; NO HA_02_c0002 public-institution discount rule!
    selected, _ = _ha_g01_chunks()
    ha03_ex = SourceChunk(
        "src_3808d1e8cd06f583_c0000", "src_3808d1e8cd06f583", "HA_03",
        "Ví dụ tháng 8: KD05 Đỗ Mai Linh ký hợp đồng chiết khấu 22% được Giám đốc Kinh doanh phê duyệt.", 0
    )
    chunks_without_policy = [c for c in selected if c.chunk_id == "src_79ae8c1e4c8cbd14_c0000"] + [ha03_ex]
    q_g01 = (
        "Trường đại học Bách Khoa Miền Trung là trường công lập muốn mua gói HA-Edu cho 4.000 sinh viên và ký hợp đồng 1 năm "
        "(không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm phí triển khai là bao nhiêu và ai phê duyệt mức chiết khấu này?"
    )
    spec = select_formula(q_g01, chunks=chunks_without_policy, allowed_source_ids={c.source_id for c in chunks_without_policy})
    res = execute_formula(spec)
    assert res.status != CalcStatus.VERIFIED, "Must NOT assert 310M VERIFIED when public-institution discount policy chunk is absent"

    appr = resolve_approval_authority(q_g01, chunks_without_policy)
    assert appr.status == "UNKNOWN"
    cleaned, changed = reconcile_approval_in_answer(
        "Mức chiết khấu được phê duyệt bởi Giám đốc Kinh doanh [src_3808d1e8cd06f583_c0000].",
        appr,
    )
    assert changed is True
    assert "Giám đốc Kinh doanh" not in cleaned
    assert "UNKNOWN" in cleaned


# ---------------------------------------------------------------------------
# FIX-03: R-02 Verbatim "chưa được vi phạm" Contradiction & Single Banner
# ---------------------------------------------------------------------------

def test_fix03_r02_handover_chua_duoc_vi_pham_reconciled_and_single_banner() -> None:
    ha_01_c3 = SourceChunk(
        "src_00d7e739cefcc3c2_c0003", "src_00d7e739cefcc3c2", "HA_01",
        "Nghỉ phép từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc.", 3
    )
    ha_02_c3 = SourceChunk(
        "src_79ae8c1e4c8cbd14_c0003", "src_79ae8c1e4c8cbd14", "HA_02",
        "Nhân viên Kinh doanh phải bàn giao danh sách khách hàng đang theo dõi cho người trực thay trước khi nghỉ. "
        "Mùa cao điểm (tháng 12) hạn chế nghỉ quá 03 ngày liên tiếp.", 3
    )
    q_r02 = (
        "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        f"{IMG_MARK}\n"
        "ĐƠN XIN NGHỈ PHÉP\nPhòng: Kinh doanh\nNgày gửi đơn: 28/11/2026\n"
        "Thời gian nghỉ: từ 03/12/2026 đến 07/12/2026 (5 ngày)\n"
        "Người nhận bàn giao khách hàng: chưa có"
    )
    llm_bad = (
        "Đơn nghỉ phép đạt yêu cầu một phần.\n\n"
        "### Điều kiện nghỉ phép\n"
        "2. **Bàn giao khách hàng**: Đơn yêu cầu \"chưa có người nhận bàn giao khách hàng\". "
        "Theo quy định tại **[src_79ae8c1e4c8cbd14_c0003]**, nhân viên Kinh doanh phải **bàn giao danh sách khách hàng đang theo dõi cho người trực thay** khi nghỉ phép. "
        "Tuy nhiên, trong trường hợp này, đơn không có thông tin về người nhận bàn giao, nhưng điều kiện này **chưa được vi phạm** vì đơn chưa yêu cầu người nhận bàn giao (chỉ cần có người nhận để thực hiện bàn giao).\n\n"
        "### Kết luận\n"
    )
    vr = verify_and_reconcile_answer(
        query=q_r02,
        chunks=[ha_01_c3, ha_02_c3],
        llm_answer=llm_bad,
        status="COMPLETE",
        allowed_source_ids={"src_00d7e739cefcc3c2", "src_79ae8c1e4c8cbd14"},
    )
    ev_text = "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in [ha_01_c3, ha_02_c3])
    post_status, final_out, _, _ = check_product_evidence_claims(
        "COMPLETE",
        vr["final_answer"],
        ev_text,
        q_r02,
        [],
        evidence_chunks=[ha_01_c3, ha_02_c3],
        ignored_identifiers=set(vr.get("ignored_identifier_numbers") or []),
    )
    assert "chưa được vi phạm" not in final_out.casefold()
    assert "vì đơn chưa yêu cầu người nhận bàn giao" not in final_out.casefold()
    assert final_out.count("Cảnh báo nhất quán") == 1
    assert "src_79ae8c1e4c8cbd14_c0003" in final_out
    assert "NOT_MET" in final_out
    # Empty ### Kết luận header should not be left dangling right before ### Đối chiếu quy định
    assert "### Kết luận\n\n### Đối chiếu" not in final_out
    assert post_status in {"COMPLETE", "PARTIAL"}


# ---------------------------------------------------------------------------
# FIX-04: R-08A Legal Review vs Calculation Intent & Contract Evidence Retention
# ---------------------------------------------------------------------------

def test_fix04_r08a_legal_review_with_ocr_numbers_skips_calc_and_preserves_general_calc() -> None:
    q_r08a = (
        "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không? Rủi ro cho bên A là gì?\n\n"
        f"{IMG_MARK}\n"
        "Điều 9.1: Nếu Bên A vi phạm bất kỳ nghĩa vụ nào sẽ chịu phạt 30% tổng giá trị hợp đồng.\n"
        "Điều 9.2: Tổng trách nhiệm bồi thường của Bên B không vượt quá 5.000.000 đồng."
    )
    assert _needs_calculation(q_r08a, {}) is False

    c_contract = SourceChunk(
        "src_aadf23faaa3faec1_c0003", "src_aadf23faaa3faec1", "HA_07_Contract",
        "Điều 9.1: Phạt vi phạm 30% giá trị hợp đồng. Điều 9.2: Giới hạn bồi thường của Bên B tối đa 5.000.000 đồng.", 3
    )
    c_preamble = SourceChunk(
        "src_aadf23faaa3faec1_c0000", "src_aadf23faaa3faec1", "HA_07_Contract",
        "HỢP ĐỒNG CUNG CẤP DỊCH VỤ PHẦN MỀM giữa Bên A (Trường Học) và Bên B (Nhà Cung Cấp).", 0
    )
    c_law = SourceChunk(
        "src_fe6a508650e0d0a8_c0013", "src_fe6a508650e0d0a8", "NĐ 13/2023/NĐ-CP",
        "Điều 13: Nguyên tắc xử lý dữ liệu cá nhân theo sự đồng ý của chủ thể dữ liệu.", 13
    )
    vr = verify_and_reconcile_answer(
        query=q_r08a,
        chunks=[c_contract, c_law],
        llm_answer="Điều khoản này có vi phạm Luật Thương mại ở mức phạt 30%. Rủi ro cho Bên A gồm phạt 30% và giới hạn bồi thường 5.000.000 đồng.",
        status="COMPLETE",
        allowed_source_ids={"src_aadf23faaa3faec1", "src_fe6a508650e0d0a8"},
    )
    assert vr["mode"] in {"bypassed_general_or_lookup", "identifier_audit_only"}
    assert "Kiểm chứng tính toán" not in vr["final_answer"]

    # Calling check_product_evidence_claims twice must NOT nest "chưa đủ căn cứ kết luận..."
    ev_txt = f"[{c_contract.chunk_id}] {c_contract.text}\n[{c_law.chunk_id}] {c_law.text}"
    st1, out1, _, _ = check_product_evidence_claims("COMPLETE", vr["final_answer"], ev_txt, q_r08a, [], evidence_chunks=[c_contract, c_law])
    st2, out2, _, _ = check_product_evidence_claims(st1, out1, ev_txt, q_r08a, [], evidence_chunks=[c_contract, c_law])
    assert out1.count("chưa đủ căn cứ kết luận") == 1
    assert out2.count("chưa đủ căn cứ kết luận") == 1

    # Complete missing evidence recovers Art 9 contract chunk c0003 when preamble c0000 + unrelated statutes are present
    rescued, _ = complete_missing_evidence(
        query=q_r08a,
        selected=[c_preamble, c_law],
        all_chunks=[c_preamble, c_contract, c_law],
        allowed_source_ids={"src_aadf23faaa3faec1", "src_fe6a508650e0d0a8"},
        max_tokens=2000,
        max_added=2,
    )
    assert "src_aadf23faaa3faec1_c0003" in [c.chunk_id for c in rescued]

    # Genuine calculation queries MUST still trigger calculation
    q_calc = (
        "Bên A chậm thanh toán 10 ngày, tổng tiền phạt phải trả là bao nhiêu?\n\n"
        f"{IMG_MARK}\nGiá trị hợp đồng 120.000.000 đồng, phạt 0,5%/ngày chậm thanh toán."
    )
    assert _needs_calculation(q_calc, {}) is True


# ---------------------------------------------------------------------------
# Held-Out Non-HA Multi-Domain Scenarios (explicitly independent of Hai Au / BLLD)
# ---------------------------------------------------------------------------

def test_heldout_non_ha_cloud_sla_review_vs_credit_calc_and_release_rule() -> None:
    # Scenario IND-01 (Cloud SaaS SLA compliance review with quoted 99.9% / $5,000 cap -> NO calculation banner)
    q_sla_review = (
        "Điều khoản miễn trừ SLA này có hợp lệ không và rủi ro cho khách hàng là gì?\n\n"
        f"{IMG_MARK}\nClause 7.2: Uptime target 99.9%, service credit capped at 10% monthly fee ($5,000)."
    )
    assert _needs_calculation(q_sla_review, {}) is False

    # Scenario IND-01b (Explicit SLA credit calculation ask with quoted attachment numbers -> triggers calculation)
    q_sla_calc = (
        "Tổng tiền hoàn trả SLA tháng này là bao nhiêu?\n\n"
        f"{IMG_MARK}\nMonthly fee $50,000, service credit 10%."
    )
    assert _needs_calculation(q_sla_calc, {}) is True

    # Scenario IND-02 (Cloud SaaS release rule contradiction with "chưa được vi phạm")
    sec_policy = SourceChunk(
        "src_rel_policy_c0001", "src_rel_policy", "Cloud Release Policy",
        "Mọi deployment lên production phải nộp change ticket trước ít nhất 05 ngày làm việc và có kế hoạch rollback được phê duyệt bởi SRE Lead.", 1
    )
    q_rel = (
        "Yêu cầu deploy này có đúng quy định phát hành phần mềm không?\n\n"
        f"{IMG_MARK}\nNgày gửi đơn: 28/11/2026\nThời gian nghỉ: từ 03/12/2026 đến 04/12/2026\n"
        "Người nhận bàn giao rollback: chưa có"
    )
    llm_rel = (
        "Yêu cầu hợp lệ.\n"
        "- **Bàn giao rollback**: Chưa có người nhận bàn giao rollback nhưng điều kiện này **chưa được vi phạm** vì chưa tới giờ deploy [src_rel_policy_c0001]."
    )
    vr = verify_and_reconcile_answer(query=q_rel, chunks=[sec_policy], llm_answer=llm_rel, status="COMPLETE")
    _, final_rel, _, _ = check_product_evidence_claims("COMPLETE", vr["final_answer"], f"[{sec_policy.chunk_id}] {sec_policy.text}", q_rel, [], evidence_chunks=[sec_policy])
    assert "chưa được vi phạm" not in final_rel.casefold()
    assert final_rel.count("Cảnh báo nhất quán") == 1

    # Scenario IND-03 (Procurement policy missing NGO discount chunk -> blocks silent 0% VERIFIED & strips wrong title)
    hosp_tier = SourceChunk(
        "src_med_tier_c0000", "src_med_tier", "MedCloud Pricing",
        "| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí triển khai |\n| --- | --- | --- | --- | --- |\n"
        "| MedCloud | Enterprise | 150.000.000 | năm | 25.000.000 |\n", 0
    )
    q_med = "Tổ chức phi lợi nhuận muốn mua gói MedCloud Enterprise (theo chính sách ưu đãi phi lợi nhuận), tổng chi phí năm đầu là bao nhiêu và ai phê duyệt?"
    spec_med = select_formula(q_med, chunks=[hosp_tier])
    assert execute_formula(spec_med).status != CalcStatus.VERIFIED
    appr_med = resolve_approval_authority(q_med, [hosp_tier])
    assert appr_med.status == "UNKNOWN"
    reconciled_med, chg_med = reconcile_approval_in_answer("Khoản chiết khấu do Phó Tổng Giám đốc duyệt.", appr_med)
    assert chg_med is True and "Phó Tổng Giám đốc" not in reconciled_med
