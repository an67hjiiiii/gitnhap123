"""Đợt 3: truy xuất lai chỉ ở chế độ sản phẩm; A/B/C giữ truy xuất cũ."""
import asyncio
from types import SimpleNamespace

from app.core.types import SourceChunk
from app.retrieval.hybrid import bm25_scores, continue_articles, fuse, heading_match, headings, tokens


def _c(i: int, text: str, src: str = "src_a") -> SourceChunk:
    return SourceChunk(chunk_id=f"{src}_c{i:04d}", source_id=src, source_name=src, text=text, index=i, provenance={})


INTRO = [_c(0, "# THIẾT KẾ CƠ SỞ DỮ LIỆU\nTài liệu mô tả cơ sở dữ liệu của hệ thống, nguyên tắc chung."),
         _c(0, "# ĐẶC TẢ API\nTài liệu mô tả API của hệ thống cơ sở.", "src_b")]
TABLES = _c(1, "## 2. Danh sách bảng chính\n| Bảng | Mục đích |\n| payments | đơn |\n| refunds | hoàn tiền |")
OTHER = _c(2, "## 6. Sao lưu và khôi phục\nSao lưu hằng ngày, giữ 30 ngày.")
ALL = INTRO + [TABLES, OTHER]


def test_tokens_fold_and_bigrams():
    t = tokens("CSDL gồm những bảng nào?")
    assert "csdl" in t and "bang" in t and "gom" not in t and "nao" not in t
    assert "co_so" in tokens("Cơ sở dữ liệu")


def test_headings_and_match():
    assert headings(TABLES.text) == "2. Danh sách bảng chính"
    assert headings("Điều 5. Thời gian thử việc\nNội dung") == "Điều 5. Thời gian thử việc"
    assert heading_match("Danh sách bảng nào?", TABLES) == 1.0
    assert heading_match("Danh sách bảng nào?", OTHER) == 0.0


def test_bm25_prefers_table_section():
    # như kho thật: "cơ sở dữ liệu" có ở nhiều đoạn (idf thấp), "bảng chính" chỉ ở đoạn danh sách bảng
    filler = [_c(10 + i, f"Cơ sở dữ liệu dùng PostgreSQL, mục {i}.", "src_f") for i in range(6)]
    s = bm25_scores("Cơ sở dữ liệu có những bảng chính nào?", ALL + filler)
    assert max(s, key=s.get) == TABLES.chunk_id


def test_fuse_lifts_section_over_intro_ranked_by_vector():
    # vector đưa phần mở đầu lên đầu (như lỗi 20/11); gộp phải đưa đoạn danh sách bảng lên trên
    vec = [INTRO[0].chunk_id, INTRO[1].chunk_id, OTHER.chunk_id, TABLES.chunk_id]
    out, trace = fuse("CSDL gồm những bảng nào?", ALL, vec, top_k=2)
    assert out[0].chunk_id == TABLES.chunk_id and trace["version"].startswith("product-hybrid")
    # đoạn chỉ BM25 tìm ra vẫn vào được (vector không trả)
    out2, trace2 = fuse("Danh sách bảng chính", ALL, [INTRO[0].chunk_id], top_k=2)
    assert TABLES.chunk_id in [c.chunk_id for c in out2] and TABLES.chunk_id in trace2["from_bm25_only"]


def test_fuse_never_returns_chunks_outside_scope():
    out, _ = fuse("bảng", [TABLES], ["src_x_c0001", TABLES.chunk_id], top_k=5)  # mã ngoài tập đoạn của chủ sở hữu bị bỏ
    assert [c.chunk_id for c in out] == [TABLES.chunk_id]


class _Index:
    def __init__(self, order):
        self.order = order
        self.calls = []

    def candidates(self, text, limit, source_ids=None):
        self.calls.append(limit)
        return [SimpleNamespace(score=0.9 - 0.01 * i, payload={"chunk_id": cid}) for i, cid in enumerate(self.order[:limit])]


def _pipe(order):
    from app.research.pipeline import ResearchPipeline
    p = ResearchPipeline.__new__(ResearchPipeline)
    p.candidate_index = _Index(order)
    return p


def test_research_conditions_keep_old_retrieval_and_product_uses_hybrid():
    order = [INTRO[0].chunk_id, INTRO[1].chunk_id, OTHER.chunk_id, TABLES.chunk_id]
    p = _pipe(order)
    old = p._retrieve_candidates("CSDL gồm những bảng nào?", ALL, top_k=2, min_score=0.0, source_ids=None)
    assert [c.chunk_id for c in old] == order[:2]          # đường cũ: đúng thứ tự vector, đúng top_k
    assert all(limit == 2 for limit in p.candidate_index.calls)
    new = p._retrieve_candidates("CSDL gồm những bảng nào?", ALL, top_k=2, min_score=0.0, source_ids=None, hybrid=True)
    assert new[0].chunk_id == TABLES.chunk_id


def test_pipeline_passes_hybrid_only_in_product_mode(monkeypatch):
    """Lượt A (thực nghiệm, product_mode=False) gọi truy xuất không có hybrid; lượt sản phẩm có hybrid=True."""
    import app.research.pipeline as pl

    seen = []
    orig = pl.ResearchPipeline._retrieve_candidates

    def spy(self, *a, **k):
        seen.append(k.get("hybrid", False))
        return orig(self, *a, **k)

    monkeypatch.setattr(pl.ResearchPipeline, "_retrieve_candidates", spy)
    src = open(pl.__file__, encoding="utf8").read()
    # mọi lời gọi truy xuất trong pipeline đều gắn với product_mode, không bật cứng
    assert src.count("hybrid=product_mode") == 3 and "hybrid=True" not in src


def test_strong_keyword_match_kept_when_vector_misses_it():
    """v3 (21/11): đoạn khớp từ khóa rất mạnh mà vector bỏ qua vẫn được giữ, không bị RRF đẩy ra khỏi top_k."""
    rule = _c(9, "Điều 5. Nghỉ hằng năm\nNgười lao động gửi đơn nghỉ phép trên hệ thống trước ít nhất 03 ngày làm việc.", "src_nq")
    noise = [_c(i, f"Điều {i}. Nội dung chung về lao động, đơn vị số {i} và ngày làm việc.", "src_x") for i in range(10)]
    vector_order = [c.chunk_id for c in noise]  # vector chỉ thấy các đoạn nhiễu
    out, trace = fuse("Nhân viên phải gửi đơn nghỉ phép năm trước ít nhất bao nhiêu ngày?", noise + [rule], vector_order, top_k=4)
    assert rule.chunk_id in [c.chunk_id for c in out] and len(out) == 4
    assert trace["version"].endswith("v3")


def test_article_cut_at_chunk_end_pulls_next_chunk():
    head = _c(24, "Điều 13. Nội dung cũ rất dài. " + "x" * 600 + "\nĐiều 14. Công nhận tốt nghiệp\n1. Sinh viên được xét khi có đủ các điều kiện sau:", "src_t")
    body = _c(25, "a) Tích lũy đủ học phần; b) Điểm trung bình tích lũy từ trung bình trở lên; c) Không bị truy cứu trách nhiệm hình sự.", "src_t")
    other = _c(3, "Điều 3. Phương thức đào tạo.", "src_t")
    out = continue_articles([head, other], [other, head, body])
    assert [c.chunk_id for c in out] == [head.chunk_id, body.chunk_id, other.chunk_id]
    assert [c.chunk_id for c in continue_articles([other], [other, head, body])] == [other.chunk_id]
