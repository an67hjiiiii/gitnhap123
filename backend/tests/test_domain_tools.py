"""Công cụ riêng theo ngành: luật cố định (so sánh, tính toán, lọc mục thiếu căn cứ) phải đúng bất kể mô hình trả gì."""
import asyncio
import io
import json
import zipfile
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis import domain_tools as dt
from app.api.analysis import build_router
from app.core.types import SourceChunk, Usage
from app.ingestion.documents import DocumentTypeError
from app.research.registry import use_pack

EDU = SourceChunk("e1", "qc", "quy_che.md", "## Điều 15. Học bổng\n1. Điểm trung bình học kỳ từ 3,2 trở lên, điểm rèn luyện từ 70 trở lên.", 0)
EDU10 = SourceChunk("e0", "qc", "quy_che.md", "## Điều 10. Cảnh báo\n1. Điểm trung bình học kỳ dưới 1,0.", 1)
HR = SourceChunk("h1", "nq", "noi_quy.md", "## Mục 3. Nghỉ phép\n1. Làm đủ 12 tháng được nghỉ 12 ngày; cứ đủ 5 năm được cộng thêm 1 ngày.\n"
                 "2. Làm thêm ngày thường 150%, ngày nghỉ hằng tuần 200%, ngày lễ 300%. Không quá 40 giờ mỗi tháng.\n"
                 "3. Nghỉ dưới 5 ngày do Trưởng phòng duyệt; từ 5 ngày trở lên do Giám đốc khối duyệt.", 0)
CONTRACT = SourceChunk("c1", "hd", "hop_dong.md", "Điều 5. Bên A có quyền đơn phương chấm dứt hợp đồng bất cứ lúc nào mà không cần báo trước.\n"
                       "Điều 6. Phạt vi phạm bằng 20% giá trị hợp đồng.", 0)


class Provider:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    async def generate_structured(self, *, system, user, response_schema, **_):
        self.calls += 1
        return SimpleNamespace(text=json.dumps(self.payload, ensure_ascii=False), usage=Usage(100, 20))


def run(coro):
    return asyncio.run(coro)


# ---------------- bảng dữ liệu
def _xlsx(rows_xml: str) -> bytes:
    S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {S} {R}><sheets><sheet name="DS" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {S}><sheetData>{rows_xml}</sheetData></worksheet>")
    return buf.getvalue()


def test_parse_table_keeps_columns_when_cells_are_empty():
    data = _xlsx('<row><c r="A1" t="inlineStr"><is><t>MSSV</t></is></c><c r="B1" t="inlineStr"><is><t>ĐTB</t></is></c>'
                 '<c r="C1" t="inlineStr"><is><t>Rèn luyện</t></is></c></row>'
                 '<row><c r="A2" t="inlineStr"><is><t>SV01</t></is></c><c r="C2"><v>80</v></c></row>')
    table = dt.parse_table(data, "ds.xlsx")
    assert table["columns"] == ["MSSV", "ĐTB", "Rèn luyện"] and table["rows"] == [["SV01", "", "80"]]
    csv_table = dt.parse_table("MSSV;ĐTB\nSV01;3,4\n".encode(), "ds.csv")
    assert csv_table["rows"] == [["SV01", "3,4"]]
    with pytest.raises(DocumentTypeError):
        dt.parse_table(b"MSSV\n", "ds.csv")
    with pytest.raises(DocumentTypeError):
        dt.parse_table(b"x", "ds.pdf")


# ---------------- Giáo dục
def test_thresholds_are_grounded_and_corrected():
    payload = {"rules": [
        {"label": "Điểm trung bình học kỳ", "op": ">=", "value": "3,2", "unit": "", "citation": "e0"},  # dẫn nhầm Điều 10
        {"label": "Điểm rèn luyện", "op": ">=", "value": "70", "unit": "điểm", "citation": "e1"},
        {"label": "Điểm rèn luyện", "op": ">=", "value": "70", "unit": "điểm", "citation": "e1"},     # trùng
        {"label": "IELTS", "op": ">=", "value": "6.5", "unit": "", "citation": "e1"},                  # số không có trong quy chế
        {"label": "Học phí", "op": "<", "value": "x", "unit": "", "citation": "e1"},                    # không phải số
    ]}
    with use_pack("education"):
        out = run(dt.extract_thresholds(Provider(payload), "Xét học bổng", [EDU10, EDU]))
    assert [(r["label"], r["op"], r["value"], r["citation"]) for r in out["rules"]] == [
        ("Điểm trung bình học kỳ", ">=", 3.2, "e1"), ("Điểm rèn luyện", ">=", 70.0, "e1")]
    assert out["removed"] == 2


def test_roster_evaluation_is_deterministic():
    rules = [{"label": "ĐTB", "op": ">=", "value": 3.2, "column": 1}, {"label": "Rèn luyện", "op": ">=", "value": 70, "column": 2}]
    rows = [["SV01", "3,4", "80"], ["SV02", "3.19", "90"], ["SV03", "3,5", ""], ["SV04", "3,2", "70"]]
    out = dt.evaluate_roster(rules, ["MSSV", "ĐTB", "RL"], rows, id_column=0)
    assert [(r["name"], r["status"]) for r in out["results"]] == [("SV01", "PASS"), ("SV02", "FAIL"), ("SV03", "MISSING"), ("SV04", "PASS")]
    assert out["summary"] == {"total": 4, "PASS": 2, "FAIL": 1, "MISSING": 1}
    with pytest.raises(ValueError):
        dt.evaluate_roster([{"label": "x", "op": ">=", "value": 1, "column": 9}], ["A"], [["1"]])


def test_number_parsing_formats():
    assert dt._number("1.200.000") == 1200000 and dt._number("1,200,000") == 1200000
    assert dt._number("3,4") == 3.4 and dt._number("75%") == 75 and dt._number("") is None and dt._number("abc") is None


def test_quiz_items_need_four_distinct_options_and_grounded_answer():
    good = {"question": "Điểm rèn luyện tối thiểu để xét học bổng?", "options": ["50", "60", "70", "80"], "answer": 2, "explanation": "", "citation": "e1"}
    payload = {"items": [good,
                         {**good, "question": "Câu trùng đáp án sai?", "answer": 3},                       # 80 không có trong đoạn
                         {**good, "question": "Ba phương án?", "options": ["a", "b", "c"]},
                         {**good, "question": "Phương án trùng?", "options": ["70", "70", "60", "50"]},
                         {**good, "question": "Không trích dẫn?", "citation": "zz"},
                         good]}
    with use_pack("education"):
        out = run(dt.generate_items(Provider(payload), "quiz", [EDU], 5))
    assert [i["question"] for i in out["items"]] == [good["question"]] and out["removed"] == 4


def test_faq_answers_cannot_add_numbers():
    payload = {"items": [{"question": "Được nghỉ mấy ngày phép?", "answer": "12 ngày khi làm đủ 12 tháng.", "citation": "h1"},
                         {"question": "Làm thêm ngày lễ?", "answer": "Được 400% lương giờ.", "citation": "h1"}]}
    with use_pack("business_hr"):
        out = run(dt.generate_items(Provider(payload), "faq", [HR], 5))
    assert [i["question"] for i in out["items"]] == ["Được nghỉ mấy ngày phép?"] and out["removed"] == 1


def test_split_articles_and_lookup_filters_citations():
    text = "# Quy chế\nChương II. ĐÀO TẠO\n## Điều 10. Cảnh báo học tập\nĐiểm dưới 1,0.\n**Điều 15. Học bổng**\nTừ 3,2 trở lên."
    arts = dt.split_articles("qc.md", text)
    assert [(a["number"], a["title"], a["chapter"]) for a in arts] == [("10", "Cảnh báo học tập", "Chương II. ĐÀO TẠO"), ("15", "Học bổng", "Chương II. ĐÀO TẠO")]
    with use_pack("education"):
        out = run(dt.lookup_articles(Provider({"answer": "Cần điểm từ 3,2 trở lên (Điều 15).", "articles": ["A1", "A9"]}), "Điều kiện học bổng?", arts))
        bad = run(dt.lookup_articles(Provider({"answer": "Cần điểm 3,6.", "articles": []}), "Điều kiện học bổng?", arts))
    assert out["cited"] == ["qc.md#15"] and out["flags"] == [] and out["articles"][0]["number"] == "15"
    assert set(bad["flags"]) == {"no_article_cited", "numbers_not_in_articles"}


# ---------------- Nhân sự
def test_pay_rates_grounded_and_compute():
    payload = {"fields": [{"key": "leave_base_days", "value": "12", "citation": "h1"}, {"key": "leave_extra_days", "value": "1", "citation": "h1"},
                          {"key": "leave_every_years", "value": "5", "citation": "h1"}, {"key": "ot_weekday_pct", "value": "150", "citation": "h1"},
                          {"key": "ot_rest_pct", "value": "200", "citation": "h1"}, {"key": "ot_holiday_pct", "value": "350", "citation": "h1"},
                          {"key": "ot_month_cap", "value": "40", "citation": "h1"}]}
    with use_pack("business_hr"):
        out = run(dt.extract_pay_rates(Provider(payload), [HR]))
    rates = {k: (v["value"] if v else None) for k, v in out["rates"].items()}
    assert rates["ot_holiday_pct"] is None and rates["leave_base_days"] == 12 and rates["ot_month_cap"] == 40  # 350% không có trong nội quy
    rates["ot_holiday_pct"] = 300
    res = dt.compute_pay(rates, [
        {"name": "An", "months": 6, "hourly": 50000, "weekday_hours": 10, "rest_hours": 0, "holiday_hours": 0, "used_days": 2},
        {"name": "Bình", "months": 132, "hourly": 40000, "weekday_hours": 20, "rest_hours": 10, "holiday_hours": 15, "used_days": 0},
        {"name": "Chi", "months": 24, "hourly": None, "weekday_hours": 5, "rest_hours": 0, "holiday_hours": 0, "used_days": 0},
    ])["employees"]
    assert (res[0]["leave_days"], res[0]["leave_left"], res[0]["overtime_pay"]) == (6, 4, 750000)   # 12*6/12; 50000*10*1.5
    assert res[1]["leave_days"] == 14 and res[1]["overtime_pay"] == 40000 * (20 * 1.5 + 10 * 2 + 15 * 3)  # 11 năm: +2 ngày
    assert any("vượt mức tối đa 40" in n for n in res[1]["notes"])
    assert res[2]["overtime_pay"] is None and any("lương giờ" in n for n in res[2]["notes"])
    missing = dt.compute_pay({k: None for k in dt.PAY_FIELDS}, [{"name": "D", "months": 30, "weekday_hours": 2, "hourly": 10}])["employees"][0]
    assert missing["leave_days"] is None and missing["overtime_pay"] is None and len(missing["notes"]) == 2


def test_approver_must_appear_in_rule():
    with use_pack("business_hr"):
        ok = run(dt.find_approver(Provider({"approver": "Giám đốc khối", "rule": "từ 5 ngày trở lên do Giám đốc khối duyệt", "citation": "h1"}), "Nghỉ phép 6 ngày", [HR]))
        bad = run(dt.find_approver(Provider({"approver": "Tổng giám đốc", "rule": "", "citation": "h1"}), "Xin nghỉ phép", [HR]))  # không nêu số ngày: luật ngưỡng không áp dụng
    assert ok["approver"] == "Giám đốc khối" and ok["citation"] == "h1"
    assert bad["approver"] == "" and bad["citation"] is None


# ---------------- Pháp lý
def test_contract_risks_need_verbatim_quote():
    payload = {"risks": [
        {"quote": "Phạt vi phạm bằng 20% giá trị hợp đồng", "level": "MEDIUM", "reason": "Mức phạt cao", "citation": "c1"},
        {"quote": "bên a có quyền  đơn phương chấm dứt hợp đồng bất cứ lúc nào", "level": "HIGH", "reason": "Một phía", "citation": "c1"},
        {"quote": "Bên B chịu mọi chi phí phát sinh không giới hạn", "level": "HIGH", "reason": "Bịa", "citation": "c1"},
    ]}
    with use_pack("legal_admin"):
        out = run(dt.contract_risks(Provider(payload), [CONTRACT]))
    assert [r["level"] for r in out["risks"]] == ["HIGH", "MEDIUM"] and out["removed"] == 1
    assert len(dt.CONTRACT_CRITERIA) == 9 and sum(1 for c in dt.CONTRACT_CRITERIA if c[2] == "Điều 398 BLDS 2015") == 7


def test_document_validity_without_model():
    old = ("CHÍNH PHỦ\nSố: 15/2020/NĐ-CP\nHà Nội, ngày 03 tháng 02 năm 2020\nNGHỊ ĐỊNH\nĐiều 30. Nghị định này có hiệu lực thi hành kể từ ngày 15 tháng 4 năm 2020.")
    new = ("CHÍNH PHỦ\nSố: 14/2022/NĐ-CP\nHà Nội, ngày 27 tháng 01 năm 2022\nNGHỊ ĐỊNH sửa đổi\nĐiều 4. Nghị định này có hiệu lực kể từ ngày 28 tháng 01 năm 2022 "
           "và thay thế Nghị định số 15/2020/NĐ-CP. Căn cứ Luật số 86/2015/QH13.")
    future = "BỘ X\nSố: 01/2030/TT-BX\nngày 01 tháng 01 năm 2030\nThông tư này có hiệu lực từ ngày 01 tháng 03 năm 2030."
    out = dt.document_validity([("a", "nd15.md", old), ("b", "nd14.md", new), ("c", "tt.md", future), ("d", "ghi_chu.md", "Ghi chú nội bộ")], date(2026, 11, 19))
    by = {d["source_id"]: d for d in out["documents"]}
    assert by["a"]["number"] == "15/2020/NĐ-CP" and by["a"]["status"] == "REPLACED" and "14/2022/NĐ-CP" in by["a"]["status_note"]
    assert by["b"]["status"] == "IN_FORCE" and by["b"]["replaces"] == ["15/2020/NĐ-CP"] and by["b"]["references"] == ["86/2015/QH13"]
    assert by["b"]["issued"] == "2022-01-27" and by["b"]["kind"] == "Nghị định"
    assert by["c"]["status"] == "NOT_YET" and by["d"]["status"] == "UNKNOWN" and by["d"]["number"] is None


# ---------------- API
class Store:
    def chunks(self, source_ids):
        return [HR] if source_ids == ["hr"] else []


class Pipeline:
    source_store = Store()

    def _retrieve_candidates(self, query, chunks, *, top_k, min_score, source_ids, fallback_trace):
        return chunks[:top_k]


def _client(payload=None):
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: Pipeline(),
                                    session_factory=lambda: None, provider_factory=lambda: Provider(payload or {})))
    return TestClient(app)


def test_tools_api_validation_and_flow():
    c = _client({"approver": "Trưởng phòng", "rule": "Nghỉ dưới 5 ngày do Trưởng phòng duyệt", "citation": "h1"})
    r = c.post("/api/studio/tools/table", files={"file": ("ds.csv", "MSSV,ĐTB\nSV01,3.4\n".encode(), "text/csv")})
    assert r.status_code == 200 and r.json()["columns"] == ["MSSV", "ĐTB"]
    assert c.post("/api/studio/tools/table", files={"file": ("ds.pdf", b"x", "application/pdf")}).status_code == 422
    body = {"rules": [{"label": "ĐTB", "op": ">=", "value": 3.2, "column": 5}], "columns": ["MSSV", "ĐTB"], "rows": [["SV01", "3.4"]]}
    assert c.post("/api/studio/tools/roster/evaluate", json=body).status_code == 422
    body["rules"][0]["column"] = 1
    assert c.post("/api/studio/tools/roster/evaluate", json=body).json()["summary"]["PASS"] == 1
    assert c.post("/api/studio/tools/pay-compute", json={"rates": {"hack": 1}, "employees": [{"name": "A"}]}).status_code == 422
    assert c.post("/api/studio/tools/pay-compute", json={"rates": {"leave_base_days": 12}, "employees": [{"name": "A", "months": 12}]}).json()["employees"][0]["leave_days"] == 12
    assert c.post("/api/studio/tools/approver", json={"request": "Nghỉ 2 ngày", "source_ids": ["hr"], "domain_pack": "business_hr"}).json()["approver"] == "Trưởng phòng"
    assert c.post("/api/studio/tools/lookup", json={"question": "Nghỉ phép?", "source_ids": ["hr"]}).status_code == 422  # nội quy chia theo Mục, không theo Điều
    assert c.post("/api/studio/tools/validity", json={"source_ids": ["nope"]}).status_code == 404
    assert len(c.get("/api/studio/tools/contract-criteria").json()["criteria"]) == 9


class Seq:
    def __init__(self, *payloads):
        self.payloads, self.calls = list(payloads), []

    async def generate_structured(self, *, system, user, response_schema, **kw):
        self.calls.append({"user": user, **kw})
        return SimpleNamespace(text=json.dumps(self.payloads[min(len(self.calls), len(self.payloads)) - 1], ensure_ascii=False), usage=Usage(10, 5))


def test_quiz_is_generated_in_batches_without_duplicates():
    q = lambda text, ans: {"question": text, "options": ["50", "60", "70", "80"], "answer": ans, "explanation": "", "citation": "e1"}
    first = {"items": [q(f"Câu {i}", 2) for i in range(5)]}
    second = {"items": [q("Câu 0", 2), q("Câu mới", 2), q("Câu sai", 3)]}
    with use_pack("education"):
        p = Seq(first, second)
        out = run(dt.generate_items(p, "quiz", [EDU], 8))
    assert len(p.calls) == 2 and all(c["max_output_tokens"] == 1600 for c in p.calls)
    assert "ALREADY ASKED" in p.calls[1]["user"] and "Write every field in Vietnamese." not in p.calls[1]["user"]
    assert [i["question"] for i in out["items"]] == [f"Câu {i}" for i in range(5)] + ["Câu mới"] and out["removed"] == 1


def test_approver_retries_once_when_empty():
    with use_pack("business_hr"):
        p = Seq({"approver": "", "rule": "", "citation": "h1"}, {"approver": "Giám đốc khối", "rule": "từ 5 ngày trở lên do Giám đốc khối duyệt", "citation": "h1"})
        out = run(dt.find_approver(p, "Đơn nghỉ phép 6 ngày", [HR]))
    assert len(p.calls) == 2 and "approval levels" in p.calls[1]["user"] and out["approver"] == "Giám đốc khối" and out["input_tokens"] == 20


def test_procedure_blanks_absent_fields():
    from app.analysis.casework import _present
    assert _present("Không có thông tin về thời hạn") == "" and _present("không nêu") == "" and _present("5 ngày làm việc") == "5 ngày làm việc"


class ContractStore:
    def chunks(self, source_ids):
        return [CONTRACT] if source_ids == ["hd"] else []


class ContractPipeline(Pipeline):
    source_store = ContractStore()


def test_contract_criterion_without_any_term_is_missing():
    app = FastAPI()
    covered = {"status": "COVERED", "citations": ["c1"], "covered_points": ["có"], "missing_points": [], "note": ""}
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: ContractPipeline(),
                                    session_factory=lambda: None, provider_factory=lambda: Provider(covered)))
    c = TestClient(app)
    dispute = c.post("/api/studio/traceability/check", json={"requirement": {"req_id": "BLDS398-g", "title": "Phương thức giải quyết tranh chấp"},
                                                             "source_ids": ["hd"], "domain_pack": "legal_admin"}).json()
    assert dispute["status"] == "MISSING" and "terms_absent" in dispute["flags"] and dispute["citations"] == []
    penalty = c.post("/api/studio/traceability/check", json={"requirement": {"req_id": "BLDS398-e", "title": "Trách nhiệm do vi phạm hợp đồng"},
                                                            "source_ids": ["hd"], "domain_pack": "legal_admin"}).json()
    assert penalty["status"] == "COVERED"


def test_contract_risks_flags_non_contract_documents():
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: ContractPipeline(),
                                    session_factory=lambda: None, provider_factory=lambda: Provider({"risks": []})))
    assert TestClient(app).post("/api/studio/tools/contract-risks", json={"source_ids": ["hd"]}).json()["looks_like_contract"] is True
    app2 = FastAPI()
    app2.include_router(build_router(current_user=lambda r: {"user_id": "u1"}, owner_pipeline=lambda user, *a: Pipeline(),
                                     session_factory=lambda: None, provider_factory=lambda: Provider({"risks": []})))
    assert TestClient(app2).post("/api/studio/tools/contract-risks", json={"source_ids": ["hr"]}).json()["looks_like_contract"] is False


def test_validity_partial_and_pending_replacement():
    base = "Số: 15/2020/NĐ-CP\nngày 03 tháng 02 năm 2020\nCăn cứ Luật số 86/2015/QH13. Nghị định có hiệu lực từ ngày 15 tháng 4 năm 2020."
    partial = "Số: 20/2023/NĐ-CP\nngày 01 tháng 01 năm 2023\nBãi bỏ Điều 5 của Nghị định số 15/2020/NĐ-CP. Nghị định này có hiệu lực từ ngày 01 tháng 02 năm 2023."
    pending = "Số: 30/2030/NĐ-CP\nngày 01 tháng 01 năm 2030\nNghị định này có hiệu lực từ ngày 01 tháng 03 năm 2030, thay thế Nghị định số 15/2020/NĐ-CP."
    adjust = "Số: 40/2024/NĐ-CP\nngày 01 tháng 01 năm 2024\nThay thế nội dung điều chỉnh tại Nghị định số 15/2020/NĐ-CP. Có hiệu lực từ ngày 01 tháng 02 năm 2024."
    out = dt.document_validity([("a", "a", base), ("b", "b", partial), ("c", "c", pending)], date(2026, 11, 19))["documents"]
    a = out[0]
    assert a["status"] == "IN_FORCE" and "một phần bởi 20/2023/NĐ-CP" in a["status_note"] and "Sẽ bị thay thế bởi 30/2030/NĐ-CP" in a["status_note"]
    assert out[1]["amends"] == ["15/2020/NĐ-CP"] and out[1]["replaces"] == []
    later = dt.document_validity([("a", "a", base), ("c", "c", pending)], date(2030, 6, 1))["documents"][0]
    assert later["status"] == "REPLACED"
    assert dt.document_validity([("a", "a", base), ("d", "d", adjust)], date(2026, 11, 19))["documents"][0]["status"] == "REPLACED"  # "điều chỉnh" không phải "Điều 5"
    # số hiệu lấy ở dòng "Số:", không lấy số văn bản được viện dẫn đứng trước
    cited_first = "Căn cứ Luật số 86/2015/QH13;\nSố: 07/2025/QĐ-UBND\nngày 01 tháng 01 năm 2025"
    assert dt.document_validity([("e", "e", cited_first)])["documents"][0]["number"] == "07/2025/QĐ-UBND"


def test_score_threshold_point_is_not_a_structure_number():
    from app.analysis.casework import _rule_text
    from app.analysis.traceability import _numbers
    assert _numbers(_rule_text("Sinh viên đạt điểm 7 trở lên")) == {"7"}
    assert _numbers(_rule_text("Theo Điều 10, khoản 2: dưới 1,0")) == {"1.0"}


def test_missing_months_is_explained():
    row = dt.compute_pay({"leave_base_days": 12}, [{"name": "X", "months": None}])["employees"][0]
    assert row["leave_days"] is None and any("số tháng" in n for n in row["notes"])


def test_lookup_distinguishes_same_article_number_in_two_documents():
    a = dt.split_articles("quy_che_A.md", "Điều 10. Học bổng\nTừ 3,2 trở lên.")
    b = dt.split_articles("quy_che_B.md", "Điều 10. Học bổng\nTừ 3,5 trở lên.")
    with use_pack("education"):
        out = run(dt.lookup_articles(Provider({"answer": "Từ 3,5 trở lên.", "articles": ["A1", "A2"]}), "Học bổng từ bao nhiêu điểm?", a + b))
    assert set(out["cited"]) == {"quy_che_A.md#10", "quy_che_B.md#10"} and out["flags"] == []


def test_approver_level_decided_by_day_threshold_not_by_model():
    """Chạy thật 19/11: đơn nghỉ 6 ngày, quy định "từ 5 ngày trở lên do Giám đốc khối duyệt", mô hình trả Trưởng phòng."""
    wrong = {"approver": "Trưởng phòng", "rule": "dưới 5 ngày do Trưởng phòng duyệt", "citation": "h1"}
    with use_pack("business_hr"):
        six = run(dt.find_approver(Provider(wrong), "Xin nghỉ phép 6 ngày thì ai duyệt?", [HR]))
        three = run(dt.find_approver(Provider({**wrong, "approver": "Giám đốc khối"}), "Nghỉ 3 ngày ai duyệt?", [HR]))
    assert six["approver"] == "Giám đốc khối" and six["citation"] == "h1" and "ngưỡng" in six["rule"]
    assert three["approver"] == "Trưởng phòng"


def test_approver_by_days_rule_parser():
    text = "Đơn xin nghỉ phép từ 5 ngày trở lên phải gửi trước ít nhất 7 ngày và do Giám đốc khối duyệt; dưới 5 ngày do Trưởng phòng duyệt."
    assert dt.approver_by_days("nghỉ 5 ngày", text) == "Giám đốc khối"
    assert dt.approver_by_days("nghỉ 4,5 ngày", text) == "Trưởng phòng"
    assert dt.approver_by_days("nghỉ phép", text) is None  # đơn không nêu số ngày: không đoán
    assert dt.approver_by_days("nghỉ 6 ngày", "Trưởng phòng duyệt mọi đơn.") is None


def test_approver_by_days_colon_and_must_be_approved_forms():
    """Thử theo vai 20/11: "Nghỉ từ 3 ngày trở lên: Giám đốc duyệt" phải nhận được (đơn 4 ngày → Giám đốc)."""
    rule = "2. Nghỉ dưới 3 ngày: Trưởng phòng duyệt. Nghỉ từ 3 ngày trở lên: Giám đốc duyệt."
    assert dt.approver_by_days("Xin nghỉ phép 4 ngày", rule) == "Giám đốc"
    assert dt.approver_by_days("Xin nghỉ phép 2 ngày", rule) == "Trưởng phòng"
    assert dt.approver_by_days("Nghỉ 3 ngày", "3. Nghỉ từ 3 ngày liên tiếp trở lên phải được Giám đốc phê duyệt.") == "Giám đốc"
    assert dt.approver_by_days("Nghỉ 6 ngày", "Nghỉ phép từ 5 ngày trở lên do Giám đốc duyệt; dưới 5 ngày do Trưởng phòng duyệt.") == "Giám đốc"
    assert dt.approver_by_days("Xin nghỉ phép", rule) is None
