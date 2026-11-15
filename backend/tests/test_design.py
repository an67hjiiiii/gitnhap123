"""Gói thiết kế kỹ thuật: ý chính, phân bổ ngữ cảnh, phần thiết kế có căn cứ, độ phủ và bản nháp xuất ra."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis import design
from app.api.analysis import build_router
from app.core.types import SourceChunk, Usage

EV = [SourceChunk("c1", "s1", "db.md", "Bảng refunds có cột refunded_amount, tiền lưu BIGINT.", 0, 0.8),
      SourceChunk("c2", "s1", "db.md", "Khóa dòng bằng SELECT ... FOR UPDATE.", 1, 0.7)]


class Provider:
    def __init__(self, *payloads):
        self.payloads, self.schemas = list(payloads), []

    async def generate_structured(self, *, system, user, response_schema, max_output_tokens=None):
        self.schemas.append(response_schema)
        return SimpleNamespace(text=json.dumps(self.payloads.pop(0)), usage=Usage(200, 80))


def run(coro):
    return asyncio.run(coro)


def test_key_points_filters_invalid_and_numbers_ids():
    p = Provider({"points": [{"text": "Lưu yêu cầu hoàn tiền", "domain": "database"}, {"text": "x", "domain": "ui"},
                             {"text": "API tạo hoàn tiền", "domain": "api_architecture"}]})
    out = run(design.key_points(p, "Thêm hoàn tiền một phần cho merchant"))
    assert [(x["id"], x["domain"]) for x in out["points"]] == [("P1", "database"), ("P2", "api_architecture")]
    assert out["input_tokens"] == 200 and out["flags"] == []


def test_key_points_fallback_when_model_returns_nothing():
    out = run(design.key_points(Provider({"points": []}), "Thêm bảng, khóa chính và chỉ mục database cho đơn hàng"))
    assert out["flags"] == ["fallback_single_point"] and out["points"][0]["domain"] == "database"


def test_allocate_evidence_prefers_unused_chunks_but_keeps_best():
    ranked = [SourceChunk(f"c{i}", "s", "a.md", "t", i, 1 - i / 10) for i in range(6)]
    picked, shared = design.allocate_evidence(ranked, 3, {"c0", "c1"})
    assert [c.chunk_id for c in picked] == ["c0", "c2", "c3"] and shared == 1
    picked, _ = design.allocate_evidence(ranked[:3], 3, {"c1", "c2"})
    assert [c.chunk_id for c in picked] == ["c0", "c1", "c2"]  # thiếu đoạn mới thì dùng lại đoạn trùng


def test_database_section_marks_grounded_items_and_builds_sql():
    payload = {"tables": [{"name": "Refund Requests", "purpose": "Lưu hoàn tiền", "citations": ["c1", "bịa"],
                           "columns": [{"name": "refund_id", "type": "VARCHAR(24)", "constraints": "PRIMARY KEY"},
                                       {"name": "amount", "type": "BIGINT", "constraints": "NOT NULL"}]},
                          {"name": "audit_x", "purpose": "Mới", "citations": [], "columns": [{"name": "id", "type": "", "constraints": ""}]}],
               "indexes": [{"table": "refund_requests", "columns": "payment_id, created_at", "purpose": "Tra cứu"}],
               "notes": [{"text": "Khóa dòng khi hoàn tiền", "citations": ["c2"]}]}
    out = run(design.design_section(Provider(payload), "Hoàn tiền một phần", "database", [{"id": "P1", "text": "Lưu", "domain": "database"}], EV))
    t1, t2 = out["section"]["tables"]
    assert t1["name"] == "refund_requests" and t1["citations"] == ["c1"] and t1["grounded"] is True
    assert t2["grounded"] is False and t2["columns"][0]["type"] == "TEXT"
    assert "CREATE TABLE refund_requests (" in out["sql"] and "amount BIGINT NOT NULL" in out["sql"]
    assert "CREATE INDEX ix_refund_requests_payment_id_created_at ON refund_requests (payment_id, created_at);" in out["sql"]
    assert out["section"]["notes"][0]["grounded"] is True and out["output_tokens"] == 80


def test_api_section_drops_invalid_endpoints_and_builds_openapi():
    payload = {"endpoints": [{"method": "POST", "path": "/v1/payments/{id}/refunds", "purpose": "Tạo hoàn tiền", "citations": [],
                              "request": ["amount: integer"], "responses": ["201: Đã tạo", "422 REFUND_EXCEEDS_AMOUNT"]},
                             {"method": "FETCH", "path": "/x", "purpose": "", "citations": [], "request": [], "responses": []},
                             {"method": "GET", "path": "refunds", "purpose": "", "citations": [], "request": [], "responses": []}],
               "notes": []}
    out = run(design.design_section(Provider(payload), "Hoàn tiền", "api_architecture", [{"id": "P1", "text": "API", "domain": "api_architecture"}], EV))
    assert [e["path"] for e in out["section"]["endpoints"]] == ["/v1/payments/{id}/refunds"]
    assert '"/v1/payments/{id}/refunds":' in out["openapi"] and '"422":' in out["openapi"] and "post:" in out["openapi"]


def test_section_schema_restricts_citations_to_evidence():
    p = Provider({"controls": [], "permissions": [], "notes": []})
    out = run(design.design_section(p, "Hoàn tiền", "security", [{"id": "P1", "text": "Phân quyền", "domain": "security"}], EV))
    assert p.schemas[0]["properties"]["controls"]["items"]["properties"]["citations"]["items"]["enum"] == ["c1", "c2"]
    assert out["flags"] == ["empty_section"]


def test_coverage_requires_a_section_and_fills_unjudged_points():
    points = [{"id": "P1", "text": "Lưu", "domain": "database"}, {"id": "P2", "text": "API", "domain": "api_architecture"},
              {"id": "P3", "text": "Quyền", "domain": "security"}]
    sections = {"database": {"tables": [{"name": "refunds", "purpose": "x", "columns": [{"name": "id", "type": "TEXT", "constraints": ""}]}], "indexes": [], "notes": []},
                "api_architecture": {"endpoints": [], "notes": []}, "security": {"controls": [], "permissions": [], "notes": []}}
    payload = {"coverage": [{"point_id": "P1", "status": "COVERED", "sections": ["database"], "note": "Có bảng"},
                            {"point_id": "P2", "status": "COVERED", "sections": ["api_architecture"], "note": "?"}]}
    out = run(design.coverage(Provider(payload), "Hoàn tiền", points, sections))["coverage"]
    assert out[0]["status"] == "COVERED" and out[0]["sections"] == ["database"]
    assert out[1]["status"] == "PARTIAL" and out[1]["flags"] == ["no_section"]  # phần API trống thì không thể "đã bao phủ"
    assert out[2]["status"] == "MISSING" and out[2]["flags"] == ["not_judged"]


def test_openapi_without_endpoints_is_valid_yaml_shape():
    assert design.to_openapi({"endpoints": []}).strip().endswith("paths: {}")


class Pipeline:
    class source_store:  # noqa: N801 - giả lập thuộc tính
        @staticmethod
        def chunks(source_ids=None):
            return EV if source_ids == ["s1"] else []

    def _retrieve_candidates(self, query, chunks, *, top_k, min_score, source_ids, fallback_trace):
        return chunks[:top_k]


def client(*payloads):
    app = FastAPI()
    provider = Provider(*payloads)
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: Pipeline(),
                                    session_factory=lambda: None, provider_factory=lambda: provider))
    return TestClient(app)


def test_design_api_flow():
    c = client({"points": [{"text": "Lưu hoàn tiền", "domain": "database"}]}, {"tables": [], "indexes": [], "notes": []})
    points = c.post("/api/studio/design/points", json={"request": "Thêm hoàn tiền một phần"}).json()["points"]
    r = c.post("/api/studio/design/section", json={"request": "Thêm hoàn tiền một phần", "domain": "database", "points": points,
                                                   "source_ids": ["s1"], "avoid_chunk_ids": ["c1"]})
    assert r.status_code == 200 and r.json()["shared_chunks"] == 1 and "sql" in r.json()
    assert c.post("/api/studio/design/section", json={"request": "Thêm hoàn tiền một phần", "domain": "database", "points": points,
                                                      "source_ids": ["khac"]}).status_code == 404
    assert c.post("/api/studio/design/points", json={"request": "ngắn"}).status_code == 422


def test_sql_constraints_normalized_to_valid_syntax():
    assert design.sql_constraints("PK") == "PRIMARY KEY"
    assert design.sql_constraints("NOT NULL, FK -> orders") == "NOT NULL REFERENCES orders"
    assert design.sql_constraints("FK -> payments(payment_id), CHECK (amount > 0, amount < 10)") == "REFERENCES payments(payment_id) CHECK (amount > 0, amount < 10)"
    assert design.sql_constraints("UNIQUE, mô tả tự do") == "UNIQUE"


def test_openapi_response_description_drops_duplicated_code():
    yaml = design.to_openapi({"endpoints": [{"method": "GET", "path": "/v1/x", "purpose": "Xem", "request": [], "responses": ["404: Không có"]}]})
    assert 'description: "Không có"' in yaml
