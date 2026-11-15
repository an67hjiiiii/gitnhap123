"""Kiểm thử sơ đồ tư duy, giải thích, báo cáo Word, kiểm tra kho, chủ đề câu hỏi và câu hỏi tiếp nối."""
import asyncio
import io
import json
import zipfile
from types import SimpleNamespace
from xml.dom import minidom

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis import reading
from app.api.analysis import build_router
from app.core.types import SourceChunk
from app.research.conversation_context import ConversationContext, resolve_follow_up

DOC = "# Cổng thanh toán\n\n## 1. Đăng nhập\n\n- Mật khẩu băm bằng bcrypt\n- Khóa sau 5 lần sai\n\n## 2. Thanh toán\n\n### 2.1 Hoàn tiền\n\nHoàn tiền trong 7 ngày."
CHUNKS = [SourceChunk("s_c0", "s", "pay.md", DOC, 0)]


class Provider:
    def __init__(self, obj):
        self.obj = obj

    async def generate_structured(self, **_):
        return SimpleNamespace(text=json.dumps(self.obj, ensure_ascii=False), usage=None)


# ---------------- Sơ đồ tư duy
def test_outline_follows_headings_and_bullets():
    root = reading.mindmap_outline("pay.md", CHUNKS)["root"]
    assert root["label"] == "Cổng thanh toán"
    login, pay = root["children"]
    assert login["label"] == "1. Đăng nhập" and [c["label"] for c in login["children"]] == ["Mật khẩu băm bằng bcrypt", "Khóa sau 5 lần sai"]
    assert pay["children"][0]["label"] == "2.1 Hoàn tiền" and pay["children"][0]["chunk_id"] == "s_c0"


def test_outline_without_headings_uses_first_sentences_and_keeps_underscores():
    root = reading.mindmap_outline("x.md", [SourceChunk("x_c0", "x", "x.md", "Cột created_at lưu thời điểm. Câu hai.", 0)])["root"]
    assert root["children"][0]["label"] == "Cột created_at lưu thời điểm"


def test_ai_mindmap_drops_bad_chunk_ids_duplicates_and_invalid_links():
    obj = {"central": "PayNhanh", "branches": [
        {"label": "Đăng nhập", "chunk_id": "D1", "children": [{"label": "Khóa tài khoản", "chunk_id": "bịa", "details": ["5 lần sai"]}]},
        {"label": "Đăng nhập", "chunk_id": "D1", "children": []},
        {"label": "Thanh toán", "chunk_id": "D1", "children": [{"label": "Hoàn tiền", "chunk_id": "D1", "details": []}]}],
        "links": [{"from": "Khóa tài khoản", "to": "Hoàn tiền", "label": "bảo vệ"}, {"from": "Đăng nhập", "to": "Khóa tài khoản", "label": "cha con"},
                  {"from": "Không có", "to": "Hoàn tiền", "label": "x"}]}
    out = asyncio.run(reading.mindmap_ai(Provider(obj), "pay.md", CHUNKS))
    labels = [c["label"] for c in out["root"]["children"]]
    assert labels == ["Đăng nhập", "Thanh toán"]
    assert out["root"]["children"][0]["children"][0]["chunk_id"] == "s_c0"  # mã đoạn bịa được thay bằng đoạn của nút cha
    assert len(out["links"]) == 1 and out["links"][0]["label"] == "bảo vệ"
    assert out["root"]["children"][0]["children"][0]["children"][0]["label"] == "5 lần sai"


def test_explain_requires_text_from_model():
    out = asyncio.run(reading.explain_selection(Provider({"explanation": "Mã chống trừ tiền hai lần.", "example": ""}), "a.md", "idempotency key", "ctx"))
    assert out["explanation"].startswith("Mã")
    try:
        asyncio.run(reading.explain_selection(Provider({"explanation": "", "example": ""}), "a.md", "x", "ctx"))
        raise AssertionError("phải báo lỗi khi mô hình không giải thích")
    except ValueError:
        pass


def test_answer_report_lists_sources_from_evidence_not_model():
    obj = {"title": "Báo cáo", "summary": "Tóm tắt.", "sections": [{"heading": "Nội dung", "body": "Hoàn tiền trong 7 ngày."}], "recommendations": ["Kiểm tra"]}
    out = asyncio.run(reading.answer_report(Provider(obj), "Hoàn tiền?", "Trong 7 ngày.", CHUNKS))
    assert "## Nguồn tham khảo" in out["markdown"] and "pay.md (đoạn 1)" in out["markdown"] and "cần người kiểm tra" in out["markdown"]


# ---------------- Word
def test_docx_is_valid_package_with_table_and_vietnamese():
    data = reading.markdown_to_docx("# Tiêu đề\n\nĐoạn **đậm** và `mã`.\n\n- ý một\n\n| Cột | Giá trị |\n|---|---|\n| a & b | <1> |\n")
    z = zipfile.ZipFile(io.BytesIO(data))
    assert {"[Content_Types].xml", "word/document.xml", "word/styles.xml"} <= set(z.namelist())
    for name in z.namelist():
        minidom.parseString(z.read(name))
    doc = z.read("word/document.xml").decode()
    assert "Tiêu đề" in doc and "<w:tbl>" in doc and "a &amp; b" in doc and 'w:val="Title"' in doc


# ---------------- Kiểm tra kho, chủ đề
def test_library_quality_flags_duplicates_and_empty_sources():
    other = SourceChunk("t_c0", "t", "copy.md", DOC, 0)
    out = reading.library_quality([{"source_id": "s", "source_name": "pay.md"}, {"source_id": "t", "source_name": "copy.md"},
                                   {"source_id": "z", "source_name": "scan.pdf"}], {"s": CHUNKS, "t": [other]})
    assert out["duplicates"][0]["score"] == 1.0
    by = {d["source_name"]: d for d in out["docs"]}
    assert by["scan.pdf"]["issues"][0]["code"] == "no_text" and any(i["code"] == "duplicate_doc" for i in by["pay.md"]["issues"])


def test_topics_use_document_vocabulary_and_compare_weeks():
    vocab = reading.bigram_vocabulary(["thanh toán thanh toán hoàn tiền hoàn tiền quy trình quy trình"])
    runs = [{"query": "Quy trình thanh toán hoàn tiền?", "created_at": "2026-11-12T00:00:00+00:00"},
            {"query": "Thanh toán lỗi thì sao?", "created_at": "2026-11-03T00:00:00+00:00"}]
    from datetime import datetime, timezone
    out = reading.question_topics(runs, vocab, now=datetime(2026, 11, 13, tzinfo=timezone.utc))
    terms = {t["term"]: t for t in out["topics"]}
    assert "trình thanh" not in terms and terms["thanh toán"]["previous"] == 1 and terms["hoàn tiền"]["count"] == 1
    assert len(out["daily"]) == 14 and sum(d["runs"] for d in out["daily"]) == 2


# ---------------- Câu hỏi tiếp nối
def test_follow_up_resolution():
    ctx = ConversationContext(text="[USER] Thanh toán online là gì?", last_user_request="Thanh toán online là gì?")
    assert resolve_follow_up("Làm sao cho an toàn?", ctx) == "Thanh toán online là gì?"
    assert resolve_follow_up("Còn hoàn tiền thì sao?", ctx) == "Thanh toán online là gì?"
    assert resolve_follow_up("Quy trình xử lý sự cố mức P1 gồm những bước nào?", ctx) is None
    assert resolve_follow_up("Làm sao cho an toàn?", ConversationContext()) is None


# ---------------- API
class Store:
    def chunks(self, ids=None):
        return [c for c in CHUNKS if ids is None or c.source_id in ids]

    def list_sources(self):
        return [{"source_id": "s", "source_name": "pay.md", "chunk_count": 1}]


class Pipe:
    source_store = Store()


def api(role="USER"):
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1", "role": role}, owner_pipeline=lambda u, *a: Pipe(),
                                    session_factory=lambda: None))
    return TestClient(app)


def test_mindmap_export_and_library_endpoints():
    body = api().post("/api/studio/mindmap", json={"source_id": "s"}).json()
    assert body["mode"] == "outline" and body["source_name"] == "pay.md"
    assert api().post("/api/studio/mindmap", json={"source_id": "nope"}).status_code == 404
    res = api().post("/api/studio/export/docx", json={"markdown": "# A"})
    assert res.status_code == 200 and res.content[:2] == b"PK"
    assert api().get("/api/studio/library-quality").json()["documents"] == 1
    assert api().post("/api/studio/related", json={"source_id": "s"}).json() == {"related": []}
    assert api().post("/api/studio/related", json={"source_id": "nope"}).status_code == 404


def test_admin_feedback_is_admin_only():
    assert api().get("/api/studio/admin/feedback").status_code == 403
    assert api("ADMIN").get("/api/studio/admin/feedback").status_code == 503  # cần PostgreSQL
