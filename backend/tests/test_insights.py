"""Kiểm thử đèn báo độ tin cậy, hồ sơ tài liệu (chạy tại máy) và các API mới của Studio."""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis import grounding, insights
from app.api.analysis import build_router
from app.core.types import SourceChunk

DOC = SourceChunk("src_a_c0000", "src_a", "a.md",
                  "Giao dịch trên 50 triệu đồng phải được hai người duyệt theo quy tắc bốn mắt. "
                  "Mật khẩu được băm bằng bcrypt với cost 12.", 0)
OTHER = SourceChunk("src_b_c0000", "src_b", "b.md", "Hệ thống ghi nhật ký kiểm toán cho mọi giao dịch duyệt bởi hai người.", 0)


# ---------------- Đèn báo độ tin cậy
def test_supported_sentence_needs_overlap_and_numbers():
    out = grounding.ground_answer("Giao dịch trên 50 triệu đồng phải được hai người duyệt theo quy tắc bốn mắt.", [DOC])
    assert out["sentences"][0]["level"] == "supported" and out["sentences"][0]["source_name"] == "a.md"


def test_wrong_number_is_not_supported():
    row = grounding.ground_answer("Giao dịch trên 90 triệu đồng phải được hai người duyệt theo quy tắc bốn mắt.", [DOC])["sentences"][0]
    assert row["level"] != "supported" and row["missing_numbers"]


def test_unrelated_sentence_is_unsupported_and_no_evidence_is_safe():
    assert grounding.ground_answer("Kubernetes tự động mở rộng pod theo tải CPU.", [DOC])["counts"]["unsupported"] == 1
    assert grounding.ground_answer("Kubernetes tự động mở rộng pod theo tải CPU.", [])["sentences"][0]["chunk_id"] is None


def test_answer_sentences_drop_source_line_and_chunk_ids():
    sents = grounding.answer_sentences("- Mật khẩu băm bằng bcrypt cost 12 [src_ab12_c0003].\n\nNguồn: a.md")
    assert sents == ["Mật khẩu băm bằng bcrypt cost 12 ."] or all("src_" not in s and "Nguồn" not in s for s in sents)


def test_run_evidence_ids_unique_in_order():
    run = {"events": [{"stage": "vanilla_retrieval", "selected": ["x", "y"]}, {"stage": "other", "selected": ["z"]}],
           "task_results": [{"citations": ["y", "w"]}]}
    assert grounding.run_evidence_ids(run) == ["x", "y", "w"]


# ---------------- Hồ sơ tài liệu tại máy
def test_pii_scan_masks_and_never_returns_raw_values():
    text = "Liên hệ an.nguyen@paynhanh.vn, SĐT 0912 345 678, thẻ 4111 1111 1111 1111, mã 1234 5678 9012 3456."
    out = insights.pii_scan(text)
    types = [f["type"] for f in out["findings"]]
    assert "email" in types and "phone" in types and types.count("card") == 1  # số thứ hai không qua Luhn
    assert "an.nguyen@paynhanh.vn" not in str(out["findings"]) and "an.nguyen@paynhanh.vn" not in out["masked_text"]
    assert "[ĐÃ CHE]" in out["masked_text"]


def test_quality_report_flags_short_doc():
    q = insights.quality_report([DOC], [])
    assert any(i["code"] == "too_short" for i in q["issues"]) and q["score"] < 100


def test_related_documents_ranks_by_overlap():
    unrelated = SourceChunk("src_c_c0000", "src_c", "c.md", "Thực đơn căng tin tuần này gồm phở và bún chả.", 0)
    rel = insights.related_documents("src_a", {"src_a": [DOC], "src_b": [OTHER], "src_c": [unrelated]}, {"src_b": "b.md", "src_c": "c.md"})
    assert rel[0]["source_name"] == "b.md" and rel[0]["score"] > rel[-1]["score"]


def test_glossary_takes_definitions_from_document():
    defined, pending = insights.glossary_candidates("- **RTO**: thời gian khôi phục tối đa sau sự cố.\nDịch vụ dùng `idempotency_key` khi gọi lại. Mỗi idempotency_key chỉ dùng một lần.")
    assert defined[0]["term"] == "RTO" and any(p["term"] == "idempotency_key" for p in pending)
    assert not any(p["term"] == "RTO" for p in pending)  # đã có định nghĩa thì không hỏi mô hình


def test_glossary_never_returns_raw_personal_data():
    # dòng liên hệ dạng "Tên: nội dung" bị nhận như định nghĩa; giá trị nhạy cảm phải bị che như tab Riêng tư
    text = ("- Quản lý phòng khám: chị Lan, email lan.nguyen@smilecare-demo.vn, điện thoại 0905 123 456.\n"
            "- Kế toán: anh Minh, CCCD 048090001234, thẻ 4111 1111 1111 1111.\n"
            "Hệ thống gọi `send_sms` tới 0905 123 456. Hàm `send_sms` gửi OTP.")
    defined, pending = insights.glossary_candidates(text)
    shown = " ".join(d["definition"] for d in defined) + " " + " ".join(p["context"] for p in pending)
    for raw in ("lan.nguyen@smilecare-demo.vn", "0905 123 456", "048090001234", "4111 1111 1111 1111"):
        assert raw not in shown
    assert "[ĐÃ CHE]" in shown and {d["term"] for d in defined} == {"Quản lý phòng khám", "Kế toán"}


def test_compare_versions_reports_changed_rule():
    out = insights.compare_versions("# Hạn mức\nGiới hạn 50 triệu\nGiữ nguyên", "# Hạn mức\nGiới hạn 100 triệu\nGiữ nguyên")
    assert out["changed"] == 1 and out["changes"][-1]["section"] == "# Hạn mức"


def test_summarize_changes_without_changes_skips_model():
    assert asyncio.run(insights.summarize_changes(None, []))["input_tokens"] == 0


# ---------------- API (phụ thuộc giả)
class Store:
    def chunks(self, ids=None):
        return [c for c in (DOC, OTHER) if ids is None or c.source_id in ids]

    def chunk(self, cid):
        return next((c.__dict__.copy() for c in (DOC, OTHER) if c.chunk_id == cid), None)


class Runs:
    def get(self, run_id):
        return {"run_id": run_id, "answer": "Giao dịch trên 50 triệu đồng phải được hai người duyệt theo quy tắc bốn mắt.",
                "events": [{"stage": "vanilla_retrieval", "selected": ["src_a_c0000"]}]} if run_id == "run_1" else None


class Pipe:
    source_store, run_store = Store(), Runs()


def api(session=None):
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda u, *a: Pipe(),
                                    session_factory=lambda: session))
    return TestClient(app)


def test_grounding_endpoint_uses_run_evidence():
    body = api().post("/api/studio/grounding", json={"run_id": "run_1"}).json()
    assert body["counts"]["supported"] == 1 and body["evidence_chunks"] == 1
    assert api().post("/api/studio/grounding", json={"run_id": "nope"}).status_code == 404


def test_profile_local_and_masked():
    body = api().post("/api/studio/profile/local", json={"source_id": "src_a"}).json()
    assert body["source_name"] == "a.md" and body["related"][0]["source_name"] == "b.md" and "masked_text" not in str(body["pii"])
    assert api().post("/api/studio/profile/local", json={"source_id": "missing"}).status_code == 404


def test_compare_docs_without_summary_is_local():
    body = api().post("/api/studio/compare-docs", json={"old_source_id": "src_a", "new_source_id": "src_b", "summarize": False}).json()
    assert body["summary"] is None and body["old_name"] == "a.md" and body["similarity"] < 1


def test_feedback_validates_rating_and_needs_postgres():
    assert api().post("/api/studio/feedback", json={"run_id": "run_1", "rating": 5}).status_code == 422
    assert api(session=None).post("/api/studio/feedback", json={"run_id": "run_1", "rating": 1}).status_code == 503
    assert api().post("/api/studio/feedback", json={"run_id": "nope", "rating": 1}).status_code == 404
