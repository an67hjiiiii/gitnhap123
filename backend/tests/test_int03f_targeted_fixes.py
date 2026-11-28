"""INT-03F Test-First RED/GREEN suite for targeted AI & QA runtime fixes on int02."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.answer_checks import IMG_MARK, _reconcile_rule_conclusions, check_product_evidence_claims
from app.core.types import RunMetrics, SourceChunk, Task
from app.providers.base import ProviderResult
from app.providers.fake import FakeProvider
from app.providers.ollama import OllamaProvider
from app.research.pipeline import ResearchPipeline
from app.research.registry import use_pack
from app.research.verified_reasoning import _retract_speculative_totals, verify_and_reconcile_answer
from app.retrieval.embeddings import OllamaEmbedder
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


# ---------------------------------------------------------------------------
# 1. §2 Rule Engine applicability scope (no leave-rule leak into contract Qs)
# ---------------------------------------------------------------------------


def test_int03f_01_rule_scope_blocks_leave_balance_on_contract_query() -> None:
    c_ha07 = SourceChunk(
        "src_aadf23faaa3faec1_c0003",
        "src_aadf23faaa3faec1",
        "HA_07_Hop_dong_cung_cap_phan_mem_HA-Edu.docx",
        "Điều 9.1 Bên A vi phạm chịu phạt 30% tổng giá trị hợp đồng. Điều 9.2 Tổng trách nhiệm bồi thường của Bên B tối đa 5.000.000 đồng.",
        3,
        provenance={"doc_type": "contract"},
    )
    c_blld = SourceChunk(
        "src_1791660bc8f54d33_c0098",
        "src_1791660bc8f54d33",
        "LD_Bo_luat_Lao_dong_2019_so_45-2019-QH14.pdf",
        "Điều 113. Nghỉ hằng năm: Người lao động làm việc đủ 12 tháng thì được nghỉ phép hằng năm 12 ngày.",
        98,
        provenance={"doc_type": "legal_doc"},
    )
    c_overtime = SourceChunk(
        "src_f4d8c24ed56dead2_c0000",
        "src_f4d8c24ed56dead2",
        "HA_08_Bang_gio_lam_them_thang_11.xlsx",
        "## Lam_them\nHọ tên | Ngày phép đã nghỉ\nPhạm Minh Hải | 4",
        0,
        provenance={"doc_type": "other"},
    )
    q_r08a = (
        "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không? Rủi ro cho bên A là gì?\n\n"
        f"{IMG_MARK}\n"
        "TRÍCH HỢP ĐỒNG 27/2026/HĐ-HAEDU\n"
        "Điều 9. Phạt vi phạm 30%, bồi thường Bên B không vượt quá 5.000.000 đồng."
    )
    llm_safe = (
        "Chưa đủ căn cứ kết luận có vi phạm hay không (Luật Thương mại chưa được nạp, Bộ luật Dân sự chưa được nạp). "
        "Rủi ro cho Bên A là chịu phạt 30% và giới hạn bồi thường 5.000.000 đồng [src_aadf23faaa3faec1_c0003]."
    )
    vr = verify_and_reconcile_answer(
        query=q_r08a,
        chunks=[c_ha07, c_blld, c_overtime],
        llm_answer=llm_safe,
        status="PARTIAL",
    )
    out = vr["final_answer"]
    assert "Số ngày phép còn lại" not in out
    assert "src_f4d8c24ed56dead2_c0000" not in out
    sr = vr.get("structured_result") or {}
    assert "remaining_balance" not in [c.get("condition_id") for c in (sr.get("condition_verdicts") or [])]


def test_int03f_02_leave_query_keeps_unknown_balance_without_citing_overtime_sheet() -> None:
    c_overtime = SourceChunk(
        "src_f4d8c24ed56dead2_c0000",
        "src_f4d8c24ed56dead2",
        "HA_08_Bang_gio_lam_them_thang_11.xlsx",
        "## Lam_them\nHọ tên | Giờ làm thêm ngày thường | Ngày phép đã nghỉ\nPhạm Minh Hải | 6 | 4",
        0,
        provenance={"doc_type": "other"},
    )
    c_leave_rule = SourceChunk(
        "src_leave_rule_c0001",
        "src_leave_rule",
        "HA_01_Noi_quy_lao_dong_2026.docx",
        "Nghỉ phép hằng năm từ 03 ngày trở lên phải nộp đơn trước ít nhất 05 ngày làm việc và có người nhận bàn giao.",
        1,
        provenance={"doc_type": "internal_policy"},
    )
    q_leave = (
        "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        f"{IMG_MARK}\n"
        "ĐƠN XIN NGHỈ PHÉP\n"
        "Xin nghỉ phép năm từ 07/12/2026 đến 11/12/2026 (5 ngày làm việc)\n"
        "Ngày gửi đơn: 03/12/2026\n"
        "Người nhận bàn giao khách hàng: chưa có"
    )
    vr = verify_and_reconcile_answer(
        query=q_leave,
        chunks=[c_overtime, c_leave_rule],
        llm_answer="Đơn hợp lệ.",
        status="COMPLETE",
    )
    out = vr["final_answer"]
    assert "UNKNOWN" in out
    assert "src_f4d8c24ed56dead2_c0000" not in out


# ---------------------------------------------------------------------------
# 2. §3 R-02 string mangling, question echo, and worker provider failure
# ---------------------------------------------------------------------------


def test_int03f_03_rule_reconcile_does_not_mangle_spacing_or_rewrite_questions() -> None:
    draft = (
        "Đơn nghỉ phép của Phạm Minh Hải có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
        "### Kết luận\n"
        "Đơn nghỉ phép hợp lệ nhưng chưa có người nhận bàn giao."
    )
    missing: list[str] = []
    out, changed = _reconcile_rule_conclusions(draft, missing)
    assert "Hảichưa" not in out
    assert "Đơn nghỉ phép của Phạm Minh Hải có đúng nội quy và quy định phòng Kinh doanh không?" in out
    assert changed is True


def test_int03f_04_question_echo_stripped_from_product_answer_prefix() -> None:
    q = "Điều khoản này có vi phạm Luật Thương mại / Bộ luật Dân sự không? Rủi ro cho bên A là gì?"
    ev_chunk = SourceChunk(
        "src_c1",
        "src_1",
        "Contract.docx",
        "Phạt vi phạm 30% tổng giá trị hợp đồng. Bồi thường tối đa 5.000.000 đồng.",
        1,
    )
    llm = f"{q}\n\nRủi ro cho Bên A là chịu phạt 30% và bồi thường tối đa 5.000.000 đồng [src_c1]."
    st, ans, _, _ = check_product_evidence_claims(
        "PARTIAL", llm, ev_chunk.text, q, [], evidence_chunks=[ev_chunk]
    )
    assert not ans.lstrip().startswith(q)
    assert "30%" in ans


def test_int03f_05_all_workers_failed_skips_synth_marks_failed_and_tracks_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("RETRY_LIMIT", "0")
    monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", "on")
    monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", "on")

    ss = SourceStore(tmp_path / "sources")
    ss.import_text(
        "HA_01.md",
        "Nghỉ phép từ 03 ngày phải báo trước 05 ngày làm việc và phải bàn giao công việc.",
    )
    rs = RunStore(tmp_path / "runs")
    pipe = ResearchPipeline(ss, rs)

    synth_called = False

    class Worker504Fake(FakeProvider):
        async def generate_grounded(self, *, system: str, user: str, evidence_ids: list[str], **kwargs: Any):
            req = httpx.Request("POST", "http://127.0.0.1:11439/api/chat")
            resp = httpx.Response(504, request=req, json={"error": "UPSTREAM_ReadError"})
            raise httpx.HTTPStatusError("504 Gateway Timeout", request=req, response=resp)

        async def generate(self, *, system: str, user: str, **kwargs: Any) -> ProviderResult:
            nonlocal synth_called
            if "SYNTHESIZER" in system.upper():
                synth_called = True
            return await super().generate(system=system, user=user, **kwargs)

    from unittest.mock import patch

    with use_pack("office"), patch("app.research.pipeline.get_provider", return_value=Worker504Fake()):
        run = asyncio.run(
            pipe.run(
                "Đơn này có đúng nội quy và quy định phòng Kinh doanh không?\n\n"
                f"{IMG_MARK}\nĐƠN XIN NGHỈ PHÉP\n"
                "Xin nghỉ từ 07/12/2026 đến 11/12/2026\nNgày gửi đơn: 03/12/2026\nNgười nhận bàn giao: chưa có",
                "C",
                provider_name="fake",
                product_mode=True,
            )
        )

    assert synth_called is False
    assert run["status"] == "FAILED"
    assert run["lifecycle_status"] == "FAILED"
    assert run["citations"] == []
    fin_ev = next(e for e in run["events"] if e.get("stage") in ("run_finished", "run_failed"))
    assert fin_ev["lifecycle_status"] == "FAILED"
    assert run["effective_config"]["attempted_llm_calls"] > run["metrics"]["llm_calls"]


# ---------------------------------------------------------------------------
# 3. §4 G-01 speculative math retraction vs sufficient operand precision
# ---------------------------------------------------------------------------


def test_int03f_06_g01_missing_operand_retracts_inline_equals_and_empty_headers() -> None:
    q_g01 = (
        "Trường đại học Bách Khoa Miền Trung là trường công lập muốn mua gói HA-Edu cho 4.000 sinh viên "
        "và ký hợp đồng 1 năm (không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm "
        "phí triển khai là bao nhiêu và ai phê duyệt mức chiết khấu này?"
    )
    ch_partial = SourceChunk(
        "src_aadf23faaa3faec1_c0001",
        "src_aadf23faaa3faec1",
        "HA_07_Hop_dong_cung_cap_phan_mem_HA-Edu.docx",
        "Chiết khấu trường công lập 12% do Ban Giám hiệu trường đại học phê duyệt.",
        1,
    )
    speculative_llm = (
        "### Mức chiết khấu\n"
        "- **Mức chiết khấu** được áp dụng cho trường đại học công lập là **12%**.\n\n"
        "### Chi tiết tính toán\n"
        "1. **Tổng giá trị năm đầu**:\n"
        "- **Phí triển khai**: 120% * 15 * 95.000.000 = **1.710.000.000**\n\n"
        "2. **Tính toán chiết khấu**:\n"
        "- **Mức chiết khấu**: 12% (trường công lập)\n"
        "- **Giá trị sau chiết khấu**: 337.066.666,67 * (1 - 12%) = **296.618.666,67**"
    )
    vr = verify_and_reconcile_answer(
        query=q_g01,
        chunks=[ch_partial],
        llm_answer=speculative_llm,
        status="COMPLETE",
    )
    out = vr["final_answer"]
    assert "MISSING_OPERAND" in out
    assert "1.710.000.000" not in out
    assert "296.618.666,67" not in out
    assert "337.066.666,67" not in out
    assert "95.000.000" not in out
    assert "**Tổng giá trị năm đầu**:" not in out
    assert "12%" in out


def test_int03f_07_g01_sufficient_operands_keeps_verified_calculation() -> None:
    q_g01 = (
        "Trường đại học Bách Khoa Miền Trung là trường công lập muốn mua gói HA-Edu cho 4.000 sinh viên "
        "và ký hợp đồng 1 năm (không chiết khấu thêm ngoài chính sách công lập), tổng tiền năm đầu gồm "
        "phí triển khai là bao nhiêu và ai phê duyệt mức chiết khấu này?"
    )
    ch_price = SourceChunk(
        "src_ha02_c0002",
        "src_ha02",
        "HA_02_So_tay_phong_Kinh_doanh_2026.md",
        "| Sản phẩm | Gói | Đơn giá | Đơn vị tính | Phí triển khai |\n|---|---|---|---|---|\n"
        "| HA-Edu | Từ 3.000 sinh viên | 260.000.000 đ | năm | 50.000.000 đ |\n"
        "- Trường đại học công lập được giảm 5%; không giảm phí triển khai; Giám đốc Khối Doanh nghiệp phê duyệt.",
        2,
    )
    vr = verify_and_reconcile_answer(
        query=q_g01,
        chunks=[ch_price],
        llm_answer="Tổng tiền năm đầu là **297.000.000** đồng, do Giám đốc Khối Doanh nghiệp phê duyệt.",
        status="COMPLETE",
    )
    out = vr["final_answer"]
    assert vr["calc_status"] == "VERIFIED"
    assert "297.000.000" in out


# ---------------------------------------------------------------------------
# 4. §5 X-QA-Run-Session header propagation helper
# ---------------------------------------------------------------------------


def test_int03f_08_qa_run_session_header_propagated_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QA_RUN_SESSION", "int03f-test-sess")
    prov = OllamaProvider(base_url="http://127.0.0.1:11439")
    emb = OllamaEmbedder(base_url="http://127.0.0.1:11439")
    assert prov._extra_headers().get("X-QA-Run-Session") == "int03f-test-sess"
    assert emb._extra_headers().get("X-QA-Run-Session") == "int03f-test-sess"


def test_int03f_09_proxy_v3_mock_upstream_session_and_budget_enforcement(tmp_path: Path) -> None:
    proxy_dir = Path(r"D:\CAPTONE\CAP1_QA_RUNTIME\B139_2F4_HYBRID_RETRIEVAL_RECOVERY_20261127\evidence")
    if str(proxy_dir) not in sys.path:
        sys.path.insert(0, str(proxy_dir))
    import threading
    import urllib.error
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import ollama_budget_proxy_v3 as p3

    class _MockUp(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0") or 0)
            _ = self.rfile.read(n)
            body = json.dumps({"message": {"content": "ok"}, "prompt_eval_count": 5, "eval_count": 1}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    up = ThreadingHTTPServer(("127.0.0.1", 0), _MockUp)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    bp = tmp_path / "b.json"
    lp = tmp_path / "l.csv"
    bp.write_text(
        json.dumps(
            {
                "version": "MOCK",
                "upstream_url": f"http://127.0.0.1:{up.server_address[1]}",
                "approved": True,
                "active_run_session": "sess-ok",
                "require_run_session": True,
                "gen_max": 1,
                "gen_used": 0,
                "query_embed_max": 1,
                "query_embed_used": 0,
                "ingest_embed_max": 0,
                "ingest_embed_used": 0,
                "total_max": 2,
            }
        ),
        encoding="utf-8",
    )
    px = ThreadingHTTPServer(("127.0.0.1", 0), p3.make_handler(bp, lp))
    threading.Thread(target=px.serve_forever, daemon=True).start()

    def _post(hdrs: dict[str, str]):
        req = urllib.request.Request(
            f"http://127.0.0.1:{px.server_address[1]}/api/chat",
            data=json.dumps({"model": "qwen3:4b", "messages": [{"role": "user", "content": "hi"}]}).encode(),
            headers={"Content-Type": "application/json", **hdrs},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    try:
        assert _post({}) == 403
        assert _post({"X-QA-Run-Session": "bad"}) == 403
        assert _post({"X-QA-Run-Session": "sess-ok"}) == 200
        assert _post({"X-QA-Run-Session": "sess-ok"}) == 429
    finally:
        px.shutdown()
        up.shutdown()
