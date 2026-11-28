"""B139.2O Test-First Suite: Ollama context stability, lifecycle keep_alive, metrics instrumentation & intra-run embed deduplication.

ZERO Ollama POSTs: all HTTP traffic is captured locally via mocked httpx AsyncClient / FakeProvider.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core import config as cfg_mod
from app.core.types import ProviderResult, RunMetrics, SourceChunk, Task, TaskResult, Usage
from app.providers.ollama import OllamaProvider
from app.research.pipeline import ResearchPipeline
from app.retrieval.embeddings import OllamaEmbedder, clear_embedder_cache, make_embedder
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _chunk(i: int, text: str, sid: str = "src_1111111111111111") -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{sid}_c{i:04d}",
        source_id=sid,
        source_name="policy.md",
        text=text,
        index=i,
        provenance={},
    )


def _mock_ollama_chat(monkeypatch, captured: list[dict], *, stream_chunks: list[str] | None = None):
    from app.providers import ollama as ollama_mod

    def fake_response_for(payload: dict) -> dict:
        sys_prompt = ((payload.get("messages") or [{}])[0].get("content") or "").upper()
        user_prompt = ((payload.get("messages") or [{}, {}])[1].get("content") or "")
        fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
        if "OBLIGATION_CONCERN_EXTRACTOR" in sys_prompt:
            c_doms = ((((fmt.get("properties") or {}).get("concerns") or {}).get("items") or {}).get("properties") or {}).get("domain", {}).get("enum") or ["general"]
            c_dom = "security" if "security" in c_doms else ("software" if "software" in c_doms else c_doms[0])
            content = json.dumps({
                "obligations": [{"obligation_id": "O1", "description": "Phân tích chính sách hệ thống và điều khoản", "required": True}],
                "concerns": [{"concern_id": "C1", "description": "Rà soát rủi ro bảo mật hệ thống", "domain": c_dom}],
            }, ensure_ascii=False)
        elif "TASK_PLAN_BUILDER" in sys_prompt:
            t_props = (((fmt.get("properties") or {}).get("tasks") or {}).get("items") or {}).get("properties") or {}
            t_doms = (t_props.get("domain") or {}).get("enum") or ["general"]
            t_dom1 = "analyst" if "analyst" in t_doms else t_doms[0]
            c_enum = ((t_props.get("covers_concerns") or {}).get("items") or {}).get("enum") or []
            # First planning attempt triggers repair intentionally; repair attempt succeeds cleanly
            if "REPAIR" not in user_prompt.upper() and "FIX" not in user_prompt.upper() and sum(
                1 for p in captured if "TASK_PLAN_BUILDER" in ((p.get("messages") or [{}])[0].get("content") or "").upper()
            ) == 1:
                content = json.dumps({
                    "tasks": [{
                        "task_id": "t1",
                        "goal": "Phân tích chung",
                        "domain": t_dom1,
                        "depends_on": [],
                        "evidence_needs": ["hệ thống"],
                        "covers_obligations": [],
                        "covers_concerns": [],
                    }]
                }, ensure_ascii=False)
            else:
                content = json.dumps({
                    "tasks": [{
                        "task_id": "t1",
                        "goal": "Phân tích chính sách hệ thống và điều khoản",
                        "domain": t_dom1,
                        "depends_on": [],
                        "evidence_needs": ["chính sách", "điều khoản", "chiết khấu", "xác thực"],
                        "covers_obligations": ["O1"],
                        "covers_concerns": list(c_enum),
                    }]
                }, ensure_ascii=False)
        elif "WORKER" in sys_prompt:
            content = json.dumps({
                "status": "COMPLETE",
                "answer": "Mức chiết khấu 12% được quy định rõ [src_1111111111111111_c0000].",
                "citations": ["src_1111111111111111_c0000"],
                "missing_information": [],
            }, ensure_ascii=False)
        elif "REVIEWER" in sys_prompt:
            content = json.dumps({"claims": [{"claim": "Mức chiết khấu 12%", "supported": True}]}, ensure_ascii=False)
        elif "SYNTHESIZER" in sys_prompt:
            content = json.dumps({"answer": "Chính sách áp dụng chiết khấu 12% [src_1111111111111111_c0000]."}, ensure_ascii=False)
        elif "VANILLA_RAG_ANSWERER" in sys_prompt:
            content = json.dumps({
                "status": "COMPLETE",
                "answer": "Chiết khấu là 12% [src_1111111111111111_c0000].",
                "citations": ["src_1111111111111111_c0000"],
                "missing_information": [],
            }, ensure_ascii=False)
        elif "GENERAL_KNOWLEDGE_ANSWERER" in sys_prompt:
            content = json.dumps({"answer": "Giải thích khái niệm chiết khấu thương mại."}, ensure_ascii=False)
        elif "CASEWORK" in sys_prompt or "CONDITION" in sys_prompt:
            content = json.dumps({"conditions": []}, ensure_ascii=False)
        elif "DESIGN_ANALYST" in sys_prompt:
            content = json.dumps({"points": [{"text": "Kiểm tra đầu vào", "domain": "security"}]}, ensure_ascii=False)
        elif "TRACEABILITY_CHECKER" in sys_prompt:
            content = json.dumps({
                "status": "COVERED",
                "citations": ["src_1111111111111111_c0000"],
                "covered_points": ["Đạt yêu cầu"],
                "missing_points": [],
                "note": "Đã đáp ứng.",
            }, ensure_ascii=False)
        else:
            content = json.dumps({"answer": "OK"}, ensure_ascii=False)
        return {
            "message": {"content": content},
            "prompt_eval_count": 320,
            "eval_count": 48,
            "total_duration": 2_400_000_000,
            "load_duration": 4_500_000,
            "prompt_eval_duration": 300_000_000,
            "eval_duration": 2_050_000_000,
            "done": True,
        }

    class FakeResp:
        def __init__(self, data: dict):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    class FakeStreamCM:
        def __init__(self, payload: dict):
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            final = fake_response_for(self._payload)
            if stream_chunks:
                for ch in stream_chunks:
                    yield json.dumps({"message": {"content": ch}, "done": False})
                yield json.dumps({**final, "message": {"content": ""}, "done": True})
            else:
                txt = final["message"]["content"]
                mid = max(1, len(txt) // 2)
                yield json.dumps({"message": {"content": txt[:mid]}, "done": False})
                yield json.dumps({**final, "message": {"content": txt[mid:]}, "done": True})

    class FakeClient:
        async def post(self, url, json):
            captured.append(dict(json))
            return FakeResp(fake_response_for(json))

        def stream(self, method, url, json):
            captured.append(dict(json))
            return FakeStreamCM(json)

    monkeypatch.setattr(ollama_mod, "_async_client", lambda *a, **k: FakeClient())
    return FakeClient


# 1. Product mode s3_planning + repair + worker + synthesizer + reviewer MUST use uniform num_ctx & keep_alive
def test_b139_2o_product_s3_planning_repair_worker_synth_reviewer_uniform_num_ctx(tmp_path, monkeypatch):
    sent: list[dict] = []
    _mock_ollama_chat(monkeypatch, sent)
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PRODUCT_REVIEWER", "on")
    monkeypatch.delenv("PRODUCT_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.setenv("PRODUCT_OLLAMA_KEEP_ALIVE", "10m")

    from app.research import token_budget as tb
    monkeypatch.setattr(tb, "_system_total_ram_mb", lambda: 8192)

    store = SourceStore(str(tmp_path / "src"))
    store.import_text("policy.md", "# Chính sách chiết khấu\nDoanh nghiệp mua số lượng lớn được chiết khấu 12%.\nRà soát rủi ro bảo mật.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))

    q = "Phân tích chính sách chiết khấu 12% và rà soát rủi ro áp dụng sai mức trong tài liệu?"
    run = asyncio.run(pipe.run(q, condition="C", provider_name="ollama", product_mode=True, domain_pack="office"))

    assert run["status"] in {"COMPLETE", "PARTIAL"}
    assert len(sent) >= 5, f"Expected extraction + plan + repair + workers + synth + reviewer, got {len(sent)}"
    num_ctxs = [p.get("options", {}).get("num_ctx") for p in sent]
    keep_alives = [p.get("keep_alive") for p in sent]
    assert all(ctx == 8192 for ctx in num_ctxs), f"Inconsistent num_ctx across s3 pipeline calls: {num_ctxs}"
    assert all(ka == "10m" for ka in keep_alives), f"Inconsistent keep_alive across pipeline calls: {keep_alives}"


# 2. Vanilla RAG streaming vs non-streaming + general knowledge preserve uniform num_ctx & keep_alive
def test_b139_2o_vanilla_stream_nonstream_and_general_knowledge_consistent_config(monkeypatch):
    from app.research.knowledge_source import answer_general
    from app.research.progress import progress_sink
    from app.research.vanilla import answer_vanilla

    sent: list[dict] = []
    _mock_ollama_chat(monkeypatch, sent)
    monkeypatch.delenv("PRODUCT_NUM_CTX", raising=False)
    monkeypatch.setenv("PRODUCT_OLLAMA_KEEP_ALIVE", "10m")

    provider = OllamaProvider(model="qwen3:4b")
    ev = [_chunk(0, "Điều 1. Chiết khấu 12%.")]

    asyncio.run(answer_vanilla(provider, "Chiết khấu bao nhiêu?", ev, RunMetrics(), product=True, num_ctx=8192, keep_alive="10m"))
    tok = progress_sink.set(lambda evt: None)
    try:
        asyncio.run(answer_vanilla(provider, "Chiết khấu bao nhiêu?", ev, RunMetrics(), product=True, num_ctx=8192, keep_alive="10m"))
    finally:
        progress_sink.reset(tok)
    asyncio.run(answer_general(provider, "Chiết khấu thương mại là gì?", RunMetrics(), max_output_tokens=1200, num_ctx=8192, keep_alive="10m"))

    assert len(sent) == 3
    assert sent[0]["stream"] is False and sent[1]["stream"] is True
    assert all(p["options"]["num_ctx"] == 8192 for p in sent)
    assert all(p.get("keep_alive") == "10m" for p in sent)


# 3. Configuration precedence & intentional caller override & Research A/B/C parity
def test_b139_2o_config_precedence_intentional_override_and_research_abc_parity(tmp_path, monkeypatch):
    from app.research import token_budget as tb

    sent: list[dict] = []
    _mock_ollama_chat(monkeypatch, sent)
    monkeypatch.setattr(tb, "_system_total_ram_mb", lambda: 32768)
    monkeypatch.setenv("OLLAMA_MAX_NUM_CTX", "16384")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")

    # Precedence: caller override > PRODUCT_NUM_CTX > OLLAMA_NUM_CTX > default 8192
    monkeypatch.setenv("OLLAMA_NUM_CTX", "4096")
    monkeypatch.delenv("PRODUCT_NUM_CTX", raising=False)
    assert tb.resolve_product_num_ctx() == 4096

    monkeypatch.setenv("PRODUCT_NUM_CTX", "6144")
    assert tb.resolve_product_num_ctx() == 6144

    # Research Mode A/B/C parity: when env overrides unset, Research A/B/C MUST NOT inject num_ctx or keep_alive
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("PRODUCT_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)
    monkeypatch.setenv("PRODUCT_OLLAMA_KEEP_ALIVE", "10m")

    store = SourceStore(str(tmp_path / "src_abc"))
    store.import_text("spec.md", "Điều 1. Hệ thống dùng xác thực Bearer token.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs_abc")))
    for cond in ("A", "B", "C"):
        sent.clear()
        run = asyncio.run(pipe.run("Phân tích hệ thống và kiểm tra xác thực?", cond, provider_name="ollama", product_mode=False))
        assert run["status"] in {"COMPLETE", "PARTIAL", "NO_EVIDENCE"}
        assert "product_num_ctx" not in run["effective_config"]
        assert all("num_ctx" not in p["options"] for p in sent), f"Research {cond} silently injected num_ctx: {sent}"
        assert all("keep_alive" not in p for p in sent), f"Research {cond} silently injected keep_alive: {sent}"

    # Intentional explicit num_ctx=16384 override works without silent clamping to 8192 on 32GB host
    sent.clear()
    prov = OllamaProvider(model="qwen3:4b")
    asyncio.run(prov.generate(system="S", user="U", num_ctx=16384))
    assert sent[0]["options"]["num_ctx"] == 16384


# 4. Context overflow safety (no silent truncation)
def test_b139_2o_context_overflow_fails_closed_without_truncation(monkeypatch):
    sent: list[dict] = []
    _mock_ollama_chat(monkeypatch, sent)
    prov = OllamaProvider(model="qwen3:4b")
    huge_prompt = "x " * 1200
    with pytest.raises(ValueError, match="exceed safe num_ctx budget"):
        asyncio.run(prov.generate(system="S", user=huge_prompt, num_ctx=512))
    assert sent == []


# 5. Keep-alive validation & strict separation between embedding and generation options
def test_b139_2o_keep_alive_policy_and_embedder_option_isolation(monkeypatch):
    # Must never allow forcing permanent residency (-1)
    with pytest.raises(ValueError):
        cfg_mod.resolve_ollama_keep_alive("-1")
    with pytest.raises(ValueError):
        cfg_mod.resolve_ollama_keep_alive(-1)
    with pytest.raises(ValueError):
        cfg_mod.resolve_ollama_keep_alive("invalid_duration")

    clear_embedder_cache()
    monkeypatch.setenv("EMBEDDING_BACKEND", "ollama")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("PRODUCT_NUM_CTX", "8192")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    monkeypatch.setenv("OLLAMA_EMBED_KEEP_ALIVE", "2m")

    embed_payloads: list[dict] = []

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"embeddings": [[0.1, 0.2, 0.3, 0.4]], "total_duration": 16_000_000, "load_duration": 4_000_000}

    monkeypatch.setattr(
        "app.retrieval.embeddings._client",
        lambda *a, **k: SimpleNamespace(post=lambda url, json, timeout=60.0: (embed_payloads.append(dict(json)), Resp())[1]),
    )
    emb = make_embedder(4)
    vec = emb.embed("test embedding")
    assert len(vec) == 4 and len(embed_payloads) == 1
    assert "options" not in embed_payloads[0]
    assert "num_ctx" not in embed_payloads[0]
    assert "think" not in embed_payloads[0]
    assert embed_payloads[0]["keep_alive"] == "2m"


# 6. Provider metrics parsing (ns -> ms, TTFT on stream vs None on sync, no fabricated metrics, no prompt leakage)
def test_b139_2o_provider_metrics_parsing_and_stage_telemetry_no_prompt_leak(tmp_path, monkeypatch):
    sent: list[dict] = []
    _mock_ollama_chat(monkeypatch, sent, stream_chunks=['{"status":"COMPLETE",', '"answer":"OK [src_1111111111111111_c0000]","citations":["src_1111111111111111_c0000"],"missing_information":[]}'])

    prov = OllamaProvider(model="qwen3:4b")
    secret_marker = "TOP_SECRET_CREDENTIAL_STRING_XYZ"
    res_sync = asyncio.run(prov.generate(system="S", user=f"Check {secret_marker}", num_ctx=8192, keep_alive="10m"))
    assert res_sync.metrics["total_duration_ms"] == 2400.0
    assert res_sync.metrics["load_duration_ms"] == 4.5
    assert res_sync.metrics["prompt_eval_count"] == 320
    assert res_sync.metrics["prompt_eval_duration_ms"] == 300.0
    assert res_sync.metrics["eval_count"] == 48
    assert res_sync.metrics["eval_duration_ms"] == 2050.0
    assert res_sync.metrics["ttft_ms"] is None  # NEVER fabricated on non-streaming call
    assert res_sync.metrics["effective_num_ctx"] == 8192
    assert res_sync.metrics["effective_keep_alive"] == "10m"
    assert secret_marker not in json.dumps(res_sync.metrics)

    res_stream = asyncio.run(
        prov.generate_structured(
            system="S",
            user="Check",
            response_schema={"type": "object"},
            on_text=lambda txt: None,
            num_ctx=8192,
        )
    )
    assert res_stream.metrics["ttft_ms"] is not None and res_stream.metrics["ttft_ms"] >= 0.0

    # Pipeline telemetry records per-stage metrics cleanly while omitting private prompts
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    store = SourceStore(str(tmp_path / "src_m"))
    store.import_text("policy.md", "Điều 1. Chiết khấu 12%.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs_m")))
    run = asyncio.run(pipe.run("Chiết khấu là bao nhiêu?", condition="C", provider_name="ollama", product_mode=True))
    calls = (run.get("metrics") or {}).get("provider_calls") or []
    assert len(calls) >= 1
    assert all(c.get("stage") for c in calls)
    assert all("user" not in c and "system" not in c and "prompt" not in c for c in calls)


# 7. Studio Analysis modules & V2 flags ON/OFF consistency
def test_b139_2o_studio_analysis_uniform_num_ctx_and_v2_flags_parity(tmp_path, monkeypatch):
    from app.analysis import casework, design, traceability

    sent: list[dict] = []
    _mock_ollama_chat(monkeypatch, sent)
    monkeypatch.delenv("PRODUCT_NUM_CTX", raising=False)
    monkeypatch.setenv("PRODUCT_OLLAMA_KEEP_ALIVE", "10m")

    prov = OllamaProvider(model="qwen3:4b")
    ev = [_chunk(0, "Điều 1. Hỗ trợ 100% khi đủ 10 điểm.")]
    asyncio.run(casework.check_conditions(prov, "Đủ điều kiện không?", "Có 10 điểm", ev))
    asyncio.run(design.key_points(prov, "Thiết kế API kiểm tra phân quyền bảo mật"))
    req = traceability.Requirement("FR-01", "Kiểm tra phân quyền", "Hệ thống phải kiểm tra phân quyền", ["security"], "security")
    asyncio.run(traceability.check_requirement(prov, req, ev))

    assert len(sent) >= 3
    assert all(p["options"].get("num_ctx") == 8192 for p in sent), f"Analysis modules omitted num_ctx: {sent}"

    # V2 experimental flags ON vs OFF preserve uniform num_ctx=8192
    for flag in ("off", "on"):
        sent.clear()
        monkeypatch.setenv("PRODUCT_STRUCTURED_EVIDENCE", flag)
        monkeypatch.setenv("PRODUCT_ADVANCED_REASONING", flag)
        monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
        store = SourceStore(str(tmp_path / f"src_{flag}"))
        store.import_text("policy.md", "Điều 1. Chiết khấu 12% cho trường công lập.")
        pipe = ResearchPipeline(store, RunStore(str(tmp_path / f"runs_{flag}")))
        asyncio.run(pipe.run("Chiết khấu là bao nhiêu?", condition="C", provider_name="ollama", product_mode=True))
        assert len(sent) >= 1 and all(p["options"].get("num_ctx") == 8192 for p in sent)


# 8. Intra-run duplicate embed elimination without unsafe cross-user / ACL sharing
def test_b139_2o_intra_run_embed_dedup_respects_acl_isolation(tmp_path, monkeypatch):
    from app.research import agent_selection as sel_mod
    from app.retrieval.candidate_index import CandidateIndex
    from app.storage.vector_store import InMemoryVectorStore

    sel_mod.clear_embedding_cache()
    embed_calls: list[str] = []

    class TrackingEmbedder:
        version = "track:v1"
        model = "nomic-embed-text"
        base_url = "http://127.0.0.1:11434"
        dimension = 4

        def embed(self, text: str) -> tuple[float, ...]:
            embed_calls.append(text)
            return (1.0, 0.2, 0.2, 0.2)

    store_a = SourceStore(str(tmp_path / "src_u1"))
    s1 = store_a.import_text("doc_hr.md", "Điều 1. Quy định nghỉ phép năm là 12 ngày.")
    store_a.import_text("other.md", "Tài liệu khác về hợp đồng dịch vụ.")
    idx_a = CandidateIndex(store_a, InMemoryVectorStore(), owner_user_id="user_a", embedder=TrackingEmbedder())
    idx_a.index_source(s1["source_id"])
    embed_calls.clear()

    pipe = ResearchPipeline(store_a, RunStore(str(tmp_path / "runs_u1")), candidate_index=idx_a, retrieval_backend="qdrant")
    sent: list[dict] = []
    _mock_ollama_chat(monkeypatch, sent)
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("PRODUCT_AGENT_PACK", "office")

    # Query triggers select_agents + preferred/rest _retrieve_hybrid; identical query must only embed ONCE inside this run!
    q = "Theo doc_hr, quy định nghỉ phép năm là bao nhiêu ngày?"
    asyncio.run(pipe.run(q, condition="C", provider_name="ollama", product_mode=True, domain_pack="office"))

    q_count_run1 = sum(1 for c in embed_calls if c == q)
    assert q_count_run1 == 1, f"Expected intra-run dedup (1 embed for query), saw {q_count_run1} in {embed_calls}"

    # Second independent run MUST still perform its own fresh embed & ACL lookup (no cross-run/cross-user stale query cache)
    embed_calls.clear()
    asyncio.run(pipe.run(q, condition="C", provider_name="ollama", product_mode=True, domain_pack="office"))
    assert sum(1 for c in embed_calls if c == q) == 1
