"""Opt-in legal structure and frozen B0 compatibility contracts (no stores/DB)."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
from statistics import median

import pytest

from app.core.types import ProviderResult, RunMetrics, SourceChunk, Task
from app.research.vanilla import answer_vanilla
from app.research.worker import execute_task
from app.retrieval.text import chunk_text, contextual_text, make_chunks, normalize_text


VERSION_ROOT = Path("D:/CAP1-Orchestration/work/version_test")
LEGAL_ROOT = Path("D:/CAP1-Orchestration/work/legal_corpus/clean")
ARTICLE = re.compile(r"^[ \t]*Điều[ \t]+(\d+)[ \t]*[.:]", re.MULTILINE)
MARKDOWN = ("# Chính sách\n\nMở đầu.\n\n## API\n\nGiới hạn.\n\n"
            "### Ngoại lệ\nTheo Điều 5 Thông tư này.\n\n## Kết thúc\nHoàn tất.")
# SHA256 of JSON [chunk_id, text, provenance], captured from unmodified B0.
BASELINES = {
    "CS_API_v1.txt": "69ba3a885e87707e861095bcbabe0f3ad23fa5907e7f606c6e8f0d6505e8fa9f",
    "CS_API_v2.txt": "3411a000f10ae49c1b35c069cff99a9f3494a03aee78f7ecc6c13a6722ab76cd",
    "CS_DANGNHAP_DUTHAO_v3.txt": "ebab30718adfcc067eb498b72fa06befd410e52d843afc11d82dc6fb8df3d8ca",
    "CS_DANGNHAP_v1.txt": "f55b9996a95be4c143b75bc955eeb9e36a126aaced702795cbc476b2caac86b9",
    "CS_DANGNHAP_v2.txt": "7e0b6f5eee1b463f85432b81bc14b6483204ee41f39c1fa4229aae631387cf70",
    "CS_NHATKY_v1.txt": "cd1d487cd84a8bba3605f1403736caba30b010abf58e15232498de33f7304386",
    "CS_NHATKY_v2.txt": "98f2dc25cc1dc782c73c1031ca9aa9f123bf4a9ad332078f90de15db748f42ae",
    "policy.md": "7f3323ba3d433515cf913cd864c12f20fa9940cdfa625d2b89c344d4c56b288a",
}


def fixture_text(name):
    if name == "policy.md":
        return MARKDOWN
    path = VERSION_ROOT / name
    if not path.exists():
        pytest.skip("External B0 policy fixture is not installed")
    return path.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("name", BASELINES)
def test_default_matches_frozen_b0(name, monkeypatch):
    monkeypatch.delenv("CHUNK_MODE", raising=False)
    text = fixture_text(name)
    chunks = make_chunks(name, text, provenance={"fixture": "B0"})
    payload = [[c.chunk_id, c.text, c.provenance] for c in chunks]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert digest == BASELINES[name]
    assert chunk_text(text) == [c.text for c in chunks]
    monkeypatch.setenv("CHUNK_MODE", "unknown")
    assert make_chunks(name, text, provenance={"fixture": "B0"}) == chunks


@pytest.mark.parametrize("name", [n for n in BASELINES if n != "policy.md"])
def test_synthetic_acceptance(name, monkeypatch):
    monkeypatch.setenv("CHUNK_MODE", "legal")
    text = fixture_text(name)
    chunks = make_chunks(name, text)
    articles = [c for c in chunks if c.provenance["chunk_kind"] == "article"]
    assert [c.provenance["article"] for c in articles] == ARTICLE.findall(text)
    assert sum(c.provenance["chunk_kind"] == "metadata" for c in chunks) == 1
    version = re.search(r"Phiên bản:[^\n]+", text)[0].strip()
    assert all(version in c.provenance["context_header"] for c in chunks)
    assert all(len(ARTICLE.findall(c.text)) <= 1 for c in chunks)
    assert chunks == make_chunks(name, text)
    assert chunk_text(text) == [c.text for c in chunks]


def test_structure_pdf_breaks_references_and_metadata(monkeypatch):
    monkeypatch.setenv("CHUNK_MODE", "legal")
    text = ("QUY ĐỊNH\nSố hiệu: AB-12\nPhiên bản: 2.0\nHiệu lực từ: 01/01/2026\n"
            "Tình trạng: Đã ban hành\nCăn cứ Luật hiện hành;\nChương I\nQUY ĐỊNH CHUNG\n"
            "Mục 1. Áp dụng\nĐiều 12: Trách nhiệm\n1. Nội dung theo Điều 5 Thông tư này.\n\n"
            "Tiếp nội dung.\f\n\n2. Nội dung tiếp theo.\nĐiều 13. Hiệu lực\nÁp dụng ngay.\n"
            "PHỤ LỤC I\nBảng biểu.\nChương II\nĐiều 14. Kiểm tra\nThực hiện.")
    chunks = make_chunks("policy.txt", text, provenance={"owner": "test"})
    article = next(c for c in chunks if c.provenance["article"] == "12")
    assert article.provenance["section_path"] == "Chương I > Mục 1. Áp dụng > Điều 12: Trách nhiệm"
    assert article.provenance["clause_range"] == "1-2"
    assert "\n\n" not in article.text and "\f" not in article.text
    assert "Tiếp nội dung." in article.text
    assert [c.provenance["article"] for c in chunks if c.provenance["chunk_kind"] == "article"] == ["12", "13", "14"]
    assert {c.provenance["chunk_kind"] for c in chunks} == {"metadata", "preamble", "article", "appendix"}
    assert chunks[-1].provenance["section_path"] == "Chương II > Điều 14. Kiểm tra"
    for c in chunks:
        assert c.provenance["owner"] == "test"
        for label in ("Số hiệu: AB-12", "Phiên bản: 2.0", "Hiệu lực từ: 01/01/2026", "Tình trạng: Đã ban hành"):
            assert label in c.provenance["context_header"]
            assert label in c.provenance["version_line"]
        assert c.chunk_id.startswith(c.provenance["doc_id"] + "_c")


def test_split_by_clauses_then_points_with_continuation_context(monkeypatch):
    monkeypatch.setenv("CHUNK_MODE", "legal")
    title = "Điều 2. Trách nhiệm"
    text = title + "\n1. " + "A" * 55 + "\n2. Các điểm:\na) " + "B" * 60 + "\nb) " + "C" * 60 + "\n3. " + "D" * 250
    chunks = make_chunks("long.txt", text, max_chars=110)
    assert len(chunks) > 3
    assert chunks[0].text == title + "\n1. " + "A" * 55
    assert any(c.text.startswith("b) ") for c in chunks)
    assert sum(c.text.count(title) for c in chunks) == 1
    assert [c.provenance["clause_range"] for c in chunks] == ["1", "2", "2", "3", "3", "3"]
    assert "".join(c.text for c in chunks).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(" ", "")
    for i, c in enumerate(chunks):
        assert len(c.text) <= 110
        assert c.provenance["context_header"].endswith(title)
        assert c.provenance["article"] == "2"
        assert c.chunk_id.endswith("_c0000" + (f"_p{i:04d}" if i else ""))
        assert c.index == c.provenance["chunk_index"] == i
    assert chunk_text(text, 110) == [c.text for c in chunks]


def test_one_metadata_block_and_no_false_reference_headings(monkeypatch):
    monkeypatch.setenv("CHUNK_MODE", "legal")
    text = "Tiêu đề\n\nPhiên bản: 1.0\n" + "Nội dung. " * 30 + "\nTheo Điều 5 Thông tư này."
    chunks = make_chunks("meta.txt", text, 40)
    assert len(chunks) == 1
    assert chunks[0].provenance["chunk_kind"] == "metadata"
    assert chunks[0].provenance["article"] is None
    assert chunks[0].provenance["clause_range"] is None
    assert chunks[0].provenance["section_path"] == ""
    assert make_chunks("empty.txt", " \n") == []
    with pytest.raises(ValueError, match="positive"):
        make_chunks("bad.txt", "Điều 1. Test", 0)


def corpus_metrics(path, monkeypatch):
    text = path.read_text(encoding="utf-8-sig")
    monkeypatch.delenv("CHUNK_MODE", raising=False)
    old = make_chunks(path.name, text)
    monkeypatch.setenv("CHUNK_MODE", "legal")
    new = make_chunks(path.name, text)
    recognized = sum(bool(ARTICLE.match(c.text)) and c.provenance["chunk_kind"] == "article" for c in new)
    return old, new, (len(old), len(new), recognized, len(ARTICLE.findall(normalize_text(text))),
                      sum(len(ARTICLE.findall(c.text)) >= 2 for c in old),
                      sum(len(ARTICLE.findall(c.text)) >= 2 for c in new),
                      max(len(c.text) for c in old), median(len(c.text) for c in old),
                      max(len(c.text) for c in new), median(len(c.text) for c in new))


def test_real_corpus_acceptance(monkeypatch):
    paths = sorted(LEGAL_ROOT.glob("*.txt"))
    if not paths:
        pytest.skip("External legal corpus is not installed")
    assert len(paths) == 9
    for path in paths:
        old, new, metrics = corpus_metrics(path, monkeypatch)
        assert metrics[2] == metrics[3], (path.name, metrics)
        assert metrics[5] == 0, (path.name, metrics)
        assert len({c.chunk_id for c in new}) == len(new)
        assert all(len(c.text) <= 1200 for c in new if c.provenance["chunk_kind"] != "metadata")
        assert chunk_text(path.read_text(encoding="utf-8-sig")) == [c.text for c in new]


@pytest.mark.parametrize("version", ["", "Phiên bản: 2.0\nHiệu lực: 2026\nTình trạng: Ban hành\n"])
def test_legal_retrieval_prefix_excludes_version_label(version, monkeypatch):
    monkeypatch.setenv("CHUNK_MODE", "legal")
    chunks = make_chunks("policy.txt", version + "Chương I\nĐiều 2. Đăng nhập\n1. " + "A" * 180, 80)
    articles = [c for c in chunks if c.provenance["chunk_kind"] == "article"]
    assert len(articles) > 1
    for chunk in chunks:
        before = dict(chunk.provenance)
        encoded = contextual_text(chunk)
        expected = "Tài liệu: policy.txt"
        if chunk.provenance["section_path"]:
            expected += " > " + chunk.provenance["section_path"]
        assert encoded == expected + "\n" + chunk.text
        assert "[" not in encoded
        assert chunk.provenance == before
        if version:
            assert "[Phiên bản: 2.0; Hiệu lực: 2026; Tình trạng: Ban hành]" in before["context_header"]
    assert all(contextual_text(c).startswith("Tài liệu: policy.txt > Chương I > Điều 2. Đăng nhập\n")
               for c in articles)
    if version:
        # Only the metadata body itself keeps version terms in BM25 input.
        from app.retrieval.bm25_index import get_index
        index = get_index(articles)
        assert "2026" not in index.postings


@pytest.mark.parametrize("mode", [None, "unknown", "legal"])
def test_contextual_text_legacy_and_disabled_mode_unchanged(mode, monkeypatch):
    if mode is None:
        monkeypatch.delenv("CHUNK_MODE", raising=False)
    else:
        monkeypatch.setenv("CHUNK_MODE", mode)
    chunk = SourceChunk("c1", "s1", "a.txt", "Raw body.", 0)
    assert contextual_text(chunk) == chunk.text
    chunk.provenance = {"context_header": "Tài liệu: a.txt > Section"}
    assert contextual_text(chunk) == "Tài liệu: a.txt > Section\nRaw body."
    if mode != "legal":
        chunk.provenance.update(chunk_kind="article", version_line="Phiên bản: 2")
        assert contextual_text(chunk) == "Tài liệu: a.txt > Section\nRaw body."


@pytest.mark.parametrize("answerer", ["vanilla", "worker"])
@pytest.mark.parametrize("mode", [None, "unknown", "legal"])
@pytest.mark.parametrize("version_line", [None, "", "Số hiệu: AB-12; Phiên bản: 2; Hiệu lực: 2026"])
@pytest.mark.parametrize("section_path", ["", "Chương I > Điều 2. Đăng nhập"])
def test_answer_prompt_version_and_legacy_bytes(answerer, mode, version_line, section_path, monkeypatch):
    if mode is None:
        monkeypatch.delenv("CHUNK_MODE", raising=False)
    else:
        monkeypatch.setenv("CHUNK_MODE", mode)
    provenance = {"section_path": section_path}
    if version_line is not None:
        provenance["version_line"] = version_line
    # Continuation chunks need the article title from provenance, not body text.
    chunks = [SourceChunk("c1", "s1", "policy.txt", "2. Nội dung tiếp theo.", 0, provenance=provenance),
              SourceChunk("c2", "s2", "", "Legacy body.", 1)]

    class Spy:
        user = ""

        async def generate(self, *, system, user):
            self.user = user
            return ProviderResult('{"status":"COMPLETE","answer":"Có.","citations":["c1"]}')

    spy = Spy()
    if answerer == "vanilla":
        asyncio.run(answer_vanilla(spy, "Yêu cầu", chunks, RunMetrics()))
        actual = spy.user.split("EVIDENCE:\n", 1)[1].split("\n\nSchema:", 1)[0]
    else:
        asyncio.run(execute_task(spy, Task("T1", "Yêu cầu"), chunks, RunMetrics()))
        actual = spy.user.split("[EVIDENCE]", 1)[1].split("[/EVIDENCE]", 1)[0]
    expected_header = "[c1] Tài liệu: policy.txt"
    if mode == "legal" and version_line:
        expected_header += "\nPhiên bản: " + version_line
        if section_path:
            expected_header += "\nVị trí: Điều 2. Đăng nhập"
    expected = expected_header + "\n2. Nội dung tiếp theo.\n\n[c2] Tài liệu: s2\nLegacy body."
    assert actual == expected
