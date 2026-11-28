"""Batch 134.1 Targeted Runtime Fix Tests (Test-First RED -> GREEN, Zero Ollama).

Covers:
1. B134-P0-NUMCTX: Total prompt budget vs configurable num_ctx, Research Mode A/B/C preservation,
   trailing chunk trimming when constrained, and controlled failure on fixed-prompt overflow.
2. B134-P1-TIMEOUT: Calibrated product timeout & output limits, zero retry on ReadTimeout,
   accurate status=FAILED (never COMPLETE), and error taxonomy (request_timeout vs provider_http_error vs budget_exhausted).
3. B134-P1-SELECT-EMB: Reused embedder across owner_pipeline calls, safe static description caching
   keyed by (model, version, base_url, dimension, pack), zero caching of queries/examples,
   cache invalidation, concurrent safety, and routing parity.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.core.types import ProviderResult, RunMetrics, SourceChunk, Usage
from app.providers.fake import FakeProvider
from app.providers.ollama import OllamaProvider
from app.research.agent_selection import OFFICE_PACK, WORK_PACK, select_agents
from app.research.pipeline import ResearchPipeline
from app.research.token_budget import count_qwen_tokens
from app.research.vanilla import answer_vanilla
from app.retrieval.embeddings import OllamaEmbedder, make_embedder
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


def _chunk(i: int, text: str, src: str = "doc") -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{src}_c{i:04d}",
        source_id=src,
        source_name=f"{src}.pdf",
        text=text,
        index=i,
        provenance={},
    )


# ==============================================================================
# 1. B134-P0-NUMCTX
# ==============================================================================


def test_b134_p0_product_mode_sets_safe_num_ctx_and_preserves_research_abc(monkeypatch):
    from app.providers import ollama as mod

    sent: list[dict] = []

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"status":"COMPLETE","answer":"OK [doc_c0000]","citations":["doc_c0000"],"missing_information":[]}'},
                    "prompt_eval_count": 200, "eval_count": 20}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def post(self, url, json):
            sent.append(json)
            return FakeResp()

    monkeypatch.delenv("PRODUCT_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.setattr(mod, "_async_client", lambda *a, **k: FakeClient())

    provider = mod.OllamaProvider(model="qwen3:4b")
    ev = [_chunk(0, "Điều 1. Phạm vi điều chỉnh của Luật Giao dịch điện tử 2023.")]

    # Research Mode (product=False) MUST NOT inject num_ctx silently
    asyncio.run(answer_vanilla(provider, "Phạm vi điều chỉnh là gì?", ev, RunMetrics(), product=False))
    # Product Mode (product=True) MUST pass bounded safe num_ctx (>= 8192 by default on normal machines)
    asyncio.run(answer_vanilla(provider, "Phạm vi điều chỉnh là gì?", ev, RunMetrics(), product=True, max_output_tokens=1200))

    assert "num_ctx" not in sent[0]["options"]
    assert "num_ctx" in sent[1]["options"]
    assert 4096 < sent[1]["options"]["num_ctx"] <= 16384


def test_b134_p0_prompt_budget_prevents_silent_head_truncation_and_trims_trailing_chunks(tmp_path, monkeypatch):
    from app.providers import ollama as mod

    monkeypatch.setenv("PRODUCT_NUM_CTX", "4096")
    monkeypatch.setenv("OLLAMA_MAX_NUM_CTX", "16384")

    captured: list[dict] = []

    class SpyOllama(mod.OllamaProvider):
        async def _generate(self, *, system: str, user: str, response_schema=None, max_output_tokens=None, on_text=None, num_ctx=None, timeout=None):
            captured.append({"system": system, "user": user, "num_ctx": num_ctx, "max_output_tokens": max_output_tokens})
            return ProviderResult(
                text='{"status":"COMPLETE","answer":"Theo Điều 22 [doc_c0000].","citations":["doc_c0000"],"missing_information":[]}',
                usage=Usage(1200, 30),
                request_id="spy_1",
                model="qwen3:4b",
            )

    # Simulate AI-03 (~15,771 chars, 11 chunks) hitting a constrained 4096 num_ctx laptop config:
    # Budget guard MUST trim trailing chunks cleanly so USER REQUEST and #1 chunk fit inside 4096!
    evidence = [
        _chunk(i, f"Điều {22 + i}. Nội dung pháp lý rất chi tiết về chữ ký điện tử và quy trình xác thực số thứ tự {i}. " * 14)
        for i in range(11)
    ]
    query = "Theo Khoản 1 Điều 22 Luật Giao dịch điện tử năm 2023, chữ ký điện tử gồm những loại nào?"
    res = asyncio.run(
        answer_vanilla(
            SpyOllama(model="qwen3:4b"),
            query,
            evidence,
            RunMetrics(),
            reply_language="vi",
            product=True,
            max_output_tokens=1200,
        )
    )

    assert len(captured) == 1
    req = captured[0]
    assert req["num_ctx"] == 4096
    assert "USER REQUEST:\n" + query in req["user"]
    assert "[doc_c0000]" in req["user"]  # #1 top-ranked chunk MUST NOT be evicted!
    assert "[doc_c0010]" not in req["user"]  # trailing chunks trimmed cleanly
    prompt_tokens = count_qwen_tokens(req["system"] + "\n" + req["user"])
    assert prompt_tokens + (req["max_output_tokens"] or 0) <= req["num_ctx"]
    assert "trailing_evidence_trimmed_to_num_ctx" in res.missing_information


def test_b134_p0_huge_fixed_prompt_overflow_returns_controlled_partial_without_calling_model(monkeypatch):
    from app.providers import ollama as mod

    monkeypatch.setenv("PRODUCT_NUM_CTX", "2048")
    calls = 0

    class NeverCallOllama(mod.OllamaProvider):
        async def _generate(self, **kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("Model must not be called when fixed prompt already overflows num_ctx")

    huge_query = ("Phân tích rất dài về điều khoản hợp đồng và trách nhiệm bồi thường thiệt hại " * 180).strip()
    ev = [_chunk(0, "Điều 1. Quy định ngắn gọn.")]
    res = asyncio.run(
        answer_vanilla(
            NeverCallOllama(model="qwen3:4b"),
            huge_query,
            ev,
            RunMetrics(),
            reply_language="vi",
            product=True,
            max_output_tokens=1200,
        )
    )
    assert calls == 0
    assert res.status == "PARTIAL"
    assert "prompt_exceeds_num_ctx" in res.missing_information


def test_b134_p0_product_default_8192_keeps_all_ai03_size_chunks_without_drop(monkeypatch):
    from app.providers import ollama as mod

    monkeypatch.delenv("PRODUCT_NUM_CTX", raising=False)
    captured: list[dict] = []

    class SpyOllama(mod.OllamaProvider):
        async def _generate(self, *, system: str, user: str, response_schema=None, max_output_tokens=None, on_text=None, num_ctx=None, timeout=None):
            captured.append({"system": system, "user": user, "num_ctx": num_ctx, "max_output_tokens": max_output_tokens})
            return ProviderResult(
                text='{"status":"COMPLETE","answer":"Đủ ý [doc_c0000] [doc_c0010].","citations":["doc_c0000","doc_c0010"],"missing_information":[]}',
                usage=Usage(4800, 100),
                request_id="spy_2",
                model="qwen3:4b",
            )

    # 11 chunks totaling ~14,500 chars (~4,400 Qwen tokens) MUST ALL fit under default PRODUCT_NUM_CTX=8192!
    evidence = [
        _chunk(i, f"Điều {22 + i}. Nội dung pháp lý về chữ ký điện tử, dịch vụ tin cậy và lưu trữ chứng từ số thứ {i}. " * 10)
        for i in range(11)
    ]
    res = asyncio.run(
        answer_vanilla(
            SpyOllama(model="qwen3:4b"),
            "Theo Điều 22 Luật Giao dịch điện tử 2023 có mấy loại chữ ký điện tử?",
            evidence,
            RunMetrics(),
            reply_language="vi",
            product=True,
            max_output_tokens=1200,
        )
    )
    assert len(captured) == 1
    assert captured[0]["num_ctx"] >= 8192
    assert "[doc_c0000]" in captured[0]["user"] and "[doc_c0010]" in captured[0]["user"]
    assert res.status == "COMPLETE"


# ==============================================================================
# 2. B134-P1-TIMEOUT
# ==============================================================================


def test_b134_p1_timeout_and_output_calibration_and_read_timeout_taxonomy(tmp_path, monkeypatch):
    from app.providers import ollama as mod

    monkeypatch.setenv("PROVIDER", "ollama")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.delenv("LOCAL_LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("PRODUCT_LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("PRODUCT_SIMPLE_MAX_OUTPUT_TOKENS", raising=False)

    seen_client_timeouts: list[float] = []
    sent_payloads: list[dict] = []

    store = SourceStore(str(tmp_path / "src"))
    imp = store.import_text("long.md", "Điều 1. Quy định về chữ ký điện tử trong giao dịch.")
    cid = store.chunks([imp["source_id"]])[0].chunk_id

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "message": {"content": f'{{"status":"COMPLETE","answer":"Có [{cid}].","citations":["{cid}"],"missing_information":[]}}'},
                "prompt_eval_count": 300,
                "eval_count": 40,
            }

    class FakeClient:
        async def post(self, url, json):
            sent_payloads.append(json)
            return FakeResp()

    def spy_client(timeout: float):
        seen_client_timeouts.append(float(timeout))
        return FakeClient()

    monkeypatch.setattr(mod, "_async_client", spy_client)
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    run = asyncio.run(pipe.run("Chữ ký điện tử là gì?", "C", provider_name="ollama", product_mode=True, domain_pack=OFFICE_PACK))

    assert run["status"] == "COMPLETE"
    assert seen_client_timeouts[-1] >= 240.0  # calibrated product timeout above 180s AI-03 cliff
    assert sent_payloads[-1]["options"]["num_predict"] == 1200
    assert run["effective_config"]["product_num_ctx"] >= 8192


def test_b134_p1_read_timeout_zero_retries_and_never_complete(tmp_path, monkeypatch):
    from app.providers import ollama as mod

    monkeypatch.setenv("PROVIDER", "ollama")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    monkeypatch.setenv("RETRY_LIMIT", "2")
    monkeypatch.setenv("OLLAMA_CONNECT_RETRIES", "2")

    post_attempts = 0

    class TimeoutClient:
        async def post(self, url, json):
            nonlocal post_attempts
            post_attempts += 1
            raise httpx.ReadTimeout("timed out reading from Ollama")

    monkeypatch.setattr(mod, "_async_client", lambda *a, **k: TimeoutClient())
    store = SourceStore(str(tmp_path / "src"))
    store.import_text("doc.md", "Điều 22. Chữ ký điện tử chuyên dùng.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))

    run = asyncio.run(pipe.run("Điều 22 quy định gì?", "C", provider_name="ollama", product_mode=True, domain_pack=OFFICE_PACK))
    assert post_attempts == 1  # ReadTimeout MUST NOT trigger retry loops!
    assert run["status"] == "FAILED"
    assert run["lifecycle_status"] == "FAILED"
    failed_ev = next(e for e in run["events"] if e["stage"] == "run_failed")
    assert failed_ev["error_category"] == "request_timeout"
    assert failed_ev["error_type"] == "ReadTimeout"


def test_b134_p1_http_error_vs_budget_exhausted_distinction(tmp_path, monkeypatch):
    from app.providers import ollama as mod

    monkeypatch.setenv("PROVIDER", "ollama")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")

    req = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
    resp = httpx.Response(503, request=req)

    class HttpErrClient:
        async def post(self, url, json):
            raise httpx.HTTPStatusError("service unavailable", request=req, response=resp)

    monkeypatch.setattr(mod, "_async_client", lambda *a, **k: HttpErrClient())
    store = SourceStore(str(tmp_path / "src"))
    store.import_text("doc.md", "Điều 1. Phạm vi điều chỉnh.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))

    run_err = asyncio.run(pipe.run("Phạm vi điều chỉnh là gì?", "C", provider_name="ollama", product_mode=True, domain_pack=OFFICE_PACK))
    assert run_err["status"] == "FAILED"
    failed_ev = next(e for e in run_err["events"] if e["stage"] == "run_failed")
    assert failed_ev["error_category"] == "provider_http_error"
    assert failed_ev["http_status"] == 503


# ==============================================================================
# 3. B134-P1-SELECT-EMB
# ==============================================================================


def test_b134_p1_make_embedder_reuses_instance_and_invalidates_on_config_change(monkeypatch):
    from app.retrieval import embeddings as emb_mod

    monkeypatch.setenv("EMBEDDING_BACKEND", "ollama")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    e1 = make_embedder(768)
    e2 = make_embedder(768)
    assert e1 is e2  # owner_pipeline across requests reuses identical embedder!

    # Config / endpoint change MUST invalidate / isolate key cleanly
    monkeypatch.setenv("EMBEDDING_MODEL", "bge-m3")
    e3 = make_embedder(768)
    assert e3 is not e1 and e3.model == "bge-m3"

    # Optional explicit cache reset hook works cleanly
    emb_mod.clear_embedder_cache()
    e4 = make_embedder(768)
    assert e4 is not e3


def test_b134_p1_select_agents_caches_static_descriptions_safely_never_queries_or_examples(monkeypatch):
    from app.research import agent_selection as sel_mod

    sel_mod.clear_embedding_cache()
    calls: list[str] = []

    class TrackingEmbedder:
        def __init__(self, model: str, base_url: str, dimension: int = 4):
            self.model = model
            self.base_url = base_url
            self.dimension = dimension
            self.version = f"ollama:{model}:{dimension}"

        def embed(self, text: str) -> tuple[float, ...]:
            calls.append(text)
            t = text.casefold()
            return (
                1.0 if "phần mềm" in t or "api" in t else 0.1,
                1.0 if "nhân sự" in t or "nghỉ phép" in t else 0.1,
                1.0 if "tài chính" in t or "ngân sách" in t else 0.1,
                1.0 if "kinh doanh" in t or "hợp đồng" in t else 0.1,
            )

    emb_req1 = TrackingEmbedder("nomic-embed-text", "http://127.0.0.1:11434")
    emb_req2 = TrackingEmbedder("nomic-embed-text", "http://127.0.0.1:11434")

    # Request 1 embeds 1 query + 7 static office descriptions = 8 calls
    r1 = select_agents("API bảo mật đăng nhập thế nào?", emb_req1.embed, examples=[("SECRET tenant project salary note", "hr")], pack=OFFICE_PACK)
    assert len(calls) == 9  # 1 query + 7 descriptions + 1 example
    calls.clear()

    # Request 2 with a DIFFERENT user query + DIFFERENT embedder object (same config) reuses 7 cached descriptions!
    # User query AND tenant example MUST NOT come from global cache across requests!
    r2 = select_agents("Quy định nghỉ phép năm ra sao?", emb_req2.embed, examples=[("SECRET tenant project salary note", "hr")], pack=OFFICE_PACK)
    assert len(calls) == 2  # ONLY 1 new query + 1 example (0 description re-embeds!)
    assert all("SECRET" in c or "nghỉ phép năm" in c.casefold() for c in calls)

    # Parity check vs clean single-run cold execution
    sel_mod.clear_embedding_cache()
    r2_fresh = select_agents("Quy định nghỉ phép năm ra sao?", TrackingEmbedder("nomic-embed-text", "http://127.0.0.1:11434").embed,
                             examples=[("SECRET tenant project salary note", "hr")], pack=OFFICE_PACK)
    assert r2 == r2_fresh

    # Changing endpoint or model MUST invalidate / separate cache key!
    calls.clear()
    emb_other_endpoint = TrackingEmbedder("nomic-embed-text", "http://127.0.0.1:11439")
    select_agents("Quy định nghỉ phép năm ra sao?", emb_other_endpoint.embed, pack=OFFICE_PACK)
    assert len(calls) == 8  # fresh embed for different endpoint!


def test_b134_p1_select_agents_concurrent_cold_cache_single_compute_and_batch_embed(monkeypatch):
    from app.research import agent_selection as sel_mod

    sel_mod.clear_embedding_cache()
    single_calls: list[str] = []
    batch_calls: list[list[str]] = []

    emb = OllamaEmbedder(dimension=4, model="nomic-embed-text", base_url="http://127.0.0.1:11439")

    def fake_post(url, json, timeout=60.0):
        inp = json["input"]
        if isinstance(inp, list):
            batch_calls.append(list(inp))
            vecs = [[1.0, 0.2, 0.2, 0.2] if "Phần mềm" in t else [0.2, 1.0, 0.2, 0.2] for t in inp]
        else:
            single_calls.append(inp)
            vecs = [[1.0, 0.2, 0.2, 0.2]]

        class Resp:
            def raise_for_status(self): pass
            def json(self): return {"embeddings": vecs}

        return Resp()

    monkeypatch.setattr("app.retrieval.embeddings._client", lambda *a, **k: SimpleNamespace(post=fake_post))

    def worker(idx: int):
        return select_agents(f"Yêu cầu API hệ thống số {idx}", emb.embed, pack=OFFICE_PACK)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(worker, range(6)))

    assert len(results) == 6 and all(r["primary"] == results[0]["primary"] for r in results)
    # Batch embed used once on cold cache -> ONLY 1 batch HTTP call for all 7 static descriptions across 6 threads!
    assert len(batch_calls) == 1 and len(batch_calls[0]) == 7
    assert len(single_calls) == 6  # 1 query embed per request, ZERO duplicate description embeds!


def test_b134_hardware_ram_cap_and_research_abc_unmodified_and_wall_budget_distinction(tmp_path, monkeypatch):
    from app.providers import ollama as mod
    from app.research import token_budget as tb

    # Low-RAM safeguard prevents blind num_ctx=16384 OOM (8 GB nominal -> 8192 cap; <6 GB -> 4096 cap)
    monkeypatch.setenv("PRODUCT_NUM_CTX", "16384")
    monkeypatch.setenv("OLLAMA_MAX_NUM_CTX", "16384")
    monkeypatch.setattr(tb, "_system_total_ram_mb", lambda: 7886)
    assert tb.resolve_product_num_ctx() == 8192
    monkeypatch.setattr(tb, "_system_total_ram_mb", lambda: 4096)
    assert tb.resolve_product_num_ctx() == 4096

    # Explicit budget_exhausted (wall_timeout) event differs cleanly from ReadTimeout (request_timeout)
    monkeypatch.setenv("MAX_DAG_WALL_SECONDS", "0.02")
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")

    class SlowFake(FakeProvider):
        async def generate(self, *, system: str, user: str) -> ProviderResult:
            await asyncio.sleep(0.1)
            return await super().generate(system=system, user=user)

    store = SourceStore(str(tmp_path / "src"))
    store.import_text("doc.md", "Điều 1. Nội dung kiểm tra timeout.")
    pipe = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    with patch("app.research.pipeline.get_provider", return_value=SlowFake()):
        budget_run = asyncio.run(pipe.run("Nội dung kiểm tra?", "A", provider_name="fake", product_mode=False))
    assert budget_run["status"] == "FAILED"
    assert budget_run["lifecycle_status"] == "FAILED"
    budget_ev = next(e for e in budget_run["events"] if e["stage"] == "run_budget_exceeded")
    assert budget_ev["reason"] == "wall_timeout"
    assert not any(e["stage"] == "run_failed" for e in budget_run["events"])

    # Research A with OllamaProvider never injects num_ctx and preserves 700 output / 180s timeout
    monkeypatch.delenv("MAX_DAG_WALL_SECONDS", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    seen_req: list[tuple[float, dict]] = []

    class Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"message": {"content": '{"status":"NO_EVIDENCE","answer":"Không có.","citations":[],"missing_information":[]}'},
                    "prompt_eval_count": 50, "eval_count": 10}

    def fake_client(t: float):
        class C:
            async def post(self, url, json):
                seen_req.append((t, json))
                return Resp()
        return C()

    monkeypatch.setattr(mod, "_async_client", fake_client)
    research_run = asyncio.run(pipe.run("Nội dung kiểm tra?", "A", provider_name="ollama", product_mode=False))
    assert research_run["status"] in {"COMPLETE", "NO_EVIDENCE", "PARTIAL"}
    assert "product_num_ctx" not in research_run["effective_config"]
    assert seen_req and seen_req[0][0] == 180.0 and "num_ctx" not in seen_req[0][1]["options"]

