from __future__ import annotations

import asyncio

from app.core.types import RunMetrics, SourceChunk, Usage
from app.research.pipeline import ResearchPipeline
from app.research.vanilla import answer_vanilla
from app.retrieval.multilingual import build_query_variants, detect_language


def chunk(cid: str, text: str) -> SourceChunk:
    return SourceChunk(chunk_id=cid, source_id=f"src-{cid}", source_name=f"{cid}.md", text=text, index=0)


class CaptureProvider:
    def __init__(self, answer: str = "PostgreSQL là authoritative store."):
        self.system = ""
        self.answer = answer

    async def generate_grounded(self, *, system, user, evidence_ids):
        self.system = system
        return type("R", (), {"text": '{"status":"COMPLETE","answer":"' + self.answer + '","citations":["en-c1"],"missing_information":[]}', "usage": Usage(input_tokens=1, output_tokens=1)})()


def test_language_detection_and_cross_language_variants_preserve_identifiers():
    assert detect_language("Theo tài liệu, database có thẩm quyền là gì?") == "vi"
    variants = build_query_variants("What is the owner_id authorization rule?")
    assert variants[0].label == "original"
    assert any("owner" in v.text.lower() for v in variants)
    assert all("owner_id" in v.text for v in variants)


def test_six_cross_language_retrieval_combinations_and_deduplication():
    chunks = [
        chunk("en-c1", "PostgreSQL is the authoritative store for product business state."),
        chunk("vi-c1", "PostgreSQL là nguồn dữ liệu có thẩm quyền cho trạng thái nghiệp vụ."),
        chunk("vi-c2", "Tài nguyên của owner khác phải trả về 404 và không được suy ra quyền sở hữu."),
    ]
    pipe = ResearchPipeline(source_store=None, run_store=None)
    cases = [
        ("What is the authoritative business state store?", "en-c1"),
        ("Kho dữ liệu có thẩm quyền cho trạng thái nghiệp vụ là gì?", "en-c1"),
        ("Nguồn dữ liệu có thẩm quyền cho trạng thái nghiệp vụ là gì?", "vi-c1"),
        ("What happens when a resource belongs to another owner?", "vi-c2"),
        ("Theo tài liệu, PostgreSQL có vai trò gì và resource của owner khác xử lý ra sao?", "vi-c2"),
        ("What is PostgreSQL's role and what happens to another owner's resource?", "vi-c2"),
    ]
    for query, expected in cases:
        found = pipe._retrieve_candidates(query, chunks, top_k=3, min_score=0.18, source_ids=None)
        assert expected in {c.chunk_id for c in found}, query
        assert len({c.chunk_id for c in found}) == len(found)


def test_grounded_answer_defaults_to_vietnamese_and_preserves_original_locator():
    provider = CaptureProvider()
    result = asyncio.run(answer_vanilla(provider, "What is authoritative?", [chunk("en-c1", "PostgreSQL is authoritative.")], RunMetrics()))
    assert "Vietnamese" in provider.system
    assert result.citations == ["en-c1"]
    assert "[en-c1]" in result.answer


def test_no_evidence_stays_honest():
    provider = CaptureProvider()
    result = asyncio.run(answer_vanilla(provider, "Unsupported", [], RunMetrics()))
    assert result.status == "NO_EVIDENCE"
    assert result.citations == []


def test_plain_vietnamese_words_are_not_treated_as_identifiers():
    # Từ tiếng Việt không dấu ("thu", "sau", "bao") từng lọt vào biến thể và kéo đoạn mở đầu tài liệu lên đầu.
    alt = [v.text for v in build_query_variants("Khóa API bị thu hồi mất hiệu lực sau bao lâu?") if v.label == "cross_language_concepts"]
    assert alt and "API" in alt[0].split()
    assert not {"thu", "sau", "bao"} & set(alt[0].split())
    assert [v.label for v in build_query_variants("Đơn thanh toán hết hạn sau bao lâu? Theo tài liệu")] == ["original"]
    ids = build_query_variants("Làm sao kiểm tra chữ ký HMAC-SHA256 cho merchant_id trong PostgreSQL?")[1].text.split()
    assert {"HMAC-SHA256", "merchant_id", "PostgreSQL"} <= set(ids)
