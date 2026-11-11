"""Kiểm thử các phần chuyển từ C1SE.27: chia ngân sách thích ứng, chọn evidence theo token Qwen3,
chọn embedder, lưu vết nguồn gốc. Không gọi LLM, không cần PostgreSQL/Ollama."""
import json

import pytest

from app.core.types import SourceChunk
from app.research.adaptive_budget import allocate_task_budgets
from app.research.provenance import build_provenance, code_manifest
from app.research.token_budget import count_qwen_tokens
from app.research.token_context import TokenContextController, context_policy, plan_task_budgets
from app.retrieval.embeddings import LocalHashEmbedder, OllamaEmbedder, make_embedder


def chunk(cid, text, score=0.5):
    return SourceChunk(chunk_id=cid, source_id="s", source_name="s.md", text=text, index=0, score=score)


def test_allocation_proportional_and_exact_total():
    limits = allocate_task_budgets({"a": 300, "b": 100}, {"a": 0, "b": 0}, {"a": 300, "b": 100}, 200)
    assert sum(limits.values()) == 200
    assert limits["a"] == 150 and limits["b"] == 50


def test_allocation_gives_full_need_when_budget_suffices():
    assert allocate_task_budgets({"a": 30, "b": 10}, {"a": 0, "b": 0}, {"a": 30, "b": 10}, 500) == {"a": 30, "b": 10}


def test_allocation_rejects_inconsistent_tasks():
    with pytest.raises(ValueError):
        allocate_task_budgets({"a": 1}, {"b": 0}, {"a": 1}, 10)


def test_qwen_token_count_is_real_not_char_proxy():
    text = "Mỗi nhân viên tạo tối đa 50 yêu cầu hoàn tiền mỗi ngày."
    n = count_qwen_tokens(text)
    assert 0 < n < len(text)


def test_token_controller_respects_budget_and_dedup():
    a = chunk("c1", "Quy tắc bốn mắt: người tạo không tự duyệt.", 0.9)
    dup = chunk("c2", "Quy tắc bốn mắt: người tạo không tự duyệt.", 0.8)
    b = chunk("c3", "CSKH cấp 2 duyệt tối đa 5.000.000đ.", 0.7)
    budget = count_qwen_tokens(a.text)
    selected, dropped = TokenContextController(budget).select([b, dup, a])
    assert [c.chunk_id for c in selected] == ["c1"]
    reasons = {d["chunk_id"]: d["reason"] for d in dropped}
    assert reasons == {"c2": "exact_duplicate", "c3": "qwen_token_budget"}


def test_plan_task_budgets_sums_to_total_when_scarce():
    long = chunk("x", "dữ liệu " * 200)
    short = chunk("y", "API")
    plan = plan_task_budgets({"T1": [long], "T2": [short]}, 50)
    assert sum(plan["limits"].values()) == 50 and plan["limits"]["T1"] > plan["limits"]["T2"]


def test_context_policy_default_keeps_old_behaviour(monkeypatch):
    monkeypatch.delenv("CONTEXT_POLICY", raising=False)
    assert context_policy() == "char_proxy"
    monkeypatch.setenv("CONTEXT_POLICY", "bogus")
    with pytest.raises(ValueError):
        context_policy()


def test_make_embedder_default_hash_and_ollama_option(monkeypatch):
    monkeypatch.delenv("EMBEDDING_BACKEND", raising=False)
    assert isinstance(make_embedder(768), LocalHashEmbedder)
    monkeypatch.setenv("EMBEDDING_BACKEND", "ollama")
    emb = make_embedder(768)
    assert isinstance(emb, OllamaEmbedder) and emb.version == "ollama:nomic-embed-text:768"
    monkeypatch.setenv("EMBEDDING_BACKEND", "nope")
    with pytest.raises(ValueError):
        make_embedder(768)


def test_provenance_has_code_hash_and_no_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:SECRET-PASS@h/db")
    prov = build_provenance(provider_name="fake", model="fake-model", embedding_version="lexical", context_policy="char_proxy")
    assert len(prov["code"]["manifest_sha256"]) == 64 and prov["code"]["file_count"] > 10
    assert prov["model"]["digest"] is None  # không gọi Ollama với provider fake
    assert "SECRET-PASS" not in json.dumps(prov)
    assert code_manifest() is code_manifest()  # tính một lần mỗi tiến trình
