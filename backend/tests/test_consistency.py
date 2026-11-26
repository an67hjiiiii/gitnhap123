"""Kiểm tra mâu thuẫn: tách câu quy định, ghép cặp nghi vấn và xét bằng mô hình."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis.consistency import candidate_pairs, extract_statements, judge_pair
from app.api.analysis import build_router
from app.core.types import SourceChunk, Usage

SRS = SourceChunk("a_c0", "a", "srs.md", "## Bảo mật\n- Khóa tài khoản 15 phút sau 5 lần đăng nhập sai liên tiếp.\n- Trang chủ có logo.\n"
                  "| NFR-01 | Hiệu năng API tạo đơn | 95% yêu cầu phản hồi dưới 300 ms |", 0)
SEC = SourceChunk("b_c0", "b", "sec.md", "Tài khoản bị khóa 30 phút sau 5 lần đăng nhập sai liên tiếp. Dữ liệu sandbox bị xóa sau 90 ngày.", 0)
OPS = SourceChunk("c_c0", "c", "ops.md", "Khóa tài khoản 15 phút sau 5 lần đăng nhập sai liên tiếp.", 0)


def test_extract_statements_keeps_normative_and_numeric_lines():
    code = SourceChunk("d_c0", "d", "api.md", '{ "amount": 450000, "reason": "tra lai" }\nVí dụ: đơn 1.200.000 VND được hoàn 450.000 VND.', 0)
    assert extract_statements([code]) == []  # mã/JSON và câu ví dụ không phải quy định
    texts = [s.text for s in extract_statements([SRS, SEC])]
    assert "Khóa tài khoản 15 phút sau 5 lần đăng nhập sai liên tiếp." in texts
    assert "NFR-01 · Hiệu năng API tạo đơn · 95% yêu cầu phản hồi dưới 300 ms" in texts
    assert "Trang chủ có logo." not in texts  # không có con số hay từ quy định
    assert len([t for t in texts if t.startswith("Tài khoản bị khóa")]) == 1  # câu được tách khỏi đoạn


def test_candidate_pairs_flag_different_numbers_across_documents_only():
    pairs = candidate_pairs(extract_statements([SRS, SEC, OPS]))
    texts = [(p["a"]["source_name"], p["b"]["source_name"], p["reason"]) for p in pairs]
    assert ("srs.md", "sec.md", "numbers_differ") in texts and ("sec.md", "ops.md", "numbers_differ") in texts
    assert all(a != b for a, b, _ in texts)
    assert not any({p["a"]["source_name"], p["b"]["source_name"]} == {"srs.md", "ops.md"} for p in pairs)  # cùng con số: không nghi vấn


class Provider:
    def __init__(self, payload):
        self.payload = payload

    async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None):
        return SimpleNamespace(text=json.dumps(self.payload), usage=Usage(150, 40))


def test_judge_pair_validates_verdict():
    a = {"source_name": "srs.md", "text": "Khóa 15 phút"}; b = {"source_name": "sec.md", "text": "Khóa 30 phút"}
    ok = asyncio.run(judge_pair(Provider({"verdict": "CONTRADICTION", "severity": "HIGH", "same_subject": True, "value_a": "15 phút",
                                          "value_b": "30 phút", "explanation": "15 khác 30"}), a, b))
    assert ok["verdict"] == "CONTRADICTION" and ok["severity"] == "HIGH" and ok["input_tokens"] == 150
    made_up = asyncio.run(judge_pair(Provider({"verdict": "CONTRADICTION", "severity": "HIGH", "same_subject": True, "value_a": "15 phút",
                                               "value_b": "45 phút", "explanation": ""}), a, b))
    assert made_up["verdict"] == "UNRELATED" and made_up["flags"] == ["unverified_values"]  # 45 không có trong câu B
    other = asyncio.run(judge_pair(Provider({"verdict": "CONTRADICTION", "severity": "LOW", "same_subject": False, "value_a": "15", "value_b": "30", "explanation": ""}), a, b))
    assert other["verdict"] == "UNRELATED" and other["flags"] == ["different_subject"]
    bad = asyncio.run(judge_pair(Provider({"verdict": "MAYBE", "severity": "X", "explanation": ""}), a, b))
    assert bad["verdict"] == "UNRELATED" and bad["severity"] == "LOW" and bad["flags"] == ["invalid_model_output"]


def test_consistency_api():
    class Pipeline:
        class source_store:  # noqa: N801
            @staticmethod
            def chunks(source_ids=None):
                return [c for c in (SRS, SEC, OPS) if c.source_id in (source_ids or [])]

    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: Pipeline(), session_factory=lambda: None,
                                    provider_factory=lambda: Provider({"verdict": "CONTRADICTION", "severity": "HIGH", "same_subject": True, "value_a": "15", "value_b": "30", "explanation": "x"})))
    c = TestClient(app)
    r = c.post("/api/studio/consistency/candidates", json={"source_ids": ["a", "b"]}).json()
    assert r["statements"] >= 3 and r["pairs"][0]["reason"] == "numbers_differ"
    assert c.post("/api/studio/consistency/candidates", json={"source_ids": []}).status_code == 422
    assert c.post("/api/studio/consistency/candidates", json={"source_ids": ["a"]}).status_code == 200
    j = c.post("/api/studio/consistency/judge", json={"a": r["pairs"][0]["a"], "b": r["pairs"][0]["b"]}).json()
    assert j["verdict"] == "CONTRADICTION"


def test_only_numeric_same_scope_conflicts_are_confirmed():
    from app.analysis.consistency import unconfirmed_reason
    assert unconfirmed_reason("15 phút", "30 phút", "Khóa 15 phút", "Khóa 30 phút") is None
    assert unconfirmed_reason("không được vượt", "vượt số đã thanh toán", "Tổng hoàn không được vượt", "Lỗi khi tổng hoàn vượt số đã thanh toán") == "non_numeric_unverified"
    assert unconfirmed_reason("200 yêu cầu mỗi giây", "100 yêu cầu/giây", "Đỉnh 200 yêu cầu tạo đơn mỗi giây",
                              "Tạo đơn 100 yêu cầu/giây cho mỗi merchant") == "different_scope"
    assert unconfirmed_reason("5 lần", "5 lần", "Khóa sau 5 lần", "Khóa sau 5 lần") == "unverified_values"
