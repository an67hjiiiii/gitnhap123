"""The legal provenance passed to the guard matches the prompt's evidence."""
import asyncio
import json

import pytest

from app.chat.answer_guard import GuardResult
from app.core.types import ProviderResult, RunMetrics, SourceChunk
from app.research.vanilla import answer_vanilla


@pytest.mark.parametrize("mode", ["legal", " LEGAL ", "plain"])
def test_vanilla_guard_receives_exact_labels_only_in_legal_mode(monkeypatch, mode):
    monkeypatch.setenv("CHUNK_MODE", mode)
    version = "Số hiệu: CS-API-03; Phiên bản: 2.0; Hiệu lực từ: 01/10/2026"
    chunks = [SourceChunk("c1", "s1", "CS_API_v2.txt", "API key hết hạn sau 12 tháng.", 0,
                          provenance={"version_line": version, "section_path": "Điều 4. Thời hạn"}),
              SourceChunk("c2", "s2", "legacy.txt", "Nội dung không có phiên bản.", 1),
              SourceChunk("c3", "s3", "other.txt", "Đoạn không được dẫn.", 2,
                          provenance={"version_line": version})]
    expected = [(f"Tài liệu: {c.source_name}\nPhiên bản: {version}\n{c.text}"
                 if mode.strip().lower() == "legal" and c.provenance.get("version_line") else c.text)
                for c in chunks]
    calls = []

    class Provider:
        async def generate(self, *, system, user):
            if mode.strip().lower() == "legal":
                assert f"[c1] Tài liệu: CS_API_v2.txt\nPhiên bản: {version}\nVị trí: Điều 4. Thời hạn" in user
            return ProviderResult(json.dumps({"status": "COMPLETE", "answer": "API key hết hạn sau 12 tháng.",
                                              "citations": ["c1", "c2"]}))

    class Checker:
        def guard(self, answer, **kwargs):
            calls.append(kwargs)
            return GuardResult(answer)

        def needs_verification(self, query, answer):
            return False

    asyncio.run(answer_vanilla(Provider(), "Thời hạn?", chunks, RunMetrics(), checker=Checker()))
    assert len(calls) == 1
    assert calls[0]["evidence_texts"] == expected
    assert calls[0]["cited_texts"] == expected[:2]
