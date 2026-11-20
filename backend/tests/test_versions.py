"""Đợt 4: so sánh phiên bản theo Điều/Khoản bằng mã, trên hai bản quy chế mẫu."""
from pathlib import Path

from app.analysis.versions import compare_versions, split_units

SAMPLES = Path(__file__).resolve().parents[2] / "frontend/public/samples/mau"
OLD = (SAMPLES / "Quy_che_lam_viec_2024_MAU.md").read_text(encoding="utf-8")
NEW = (SAMPLES / "Quy_che_lam_viec_2026_MAU.md").read_text(encoding="utf-8")


def test_split_articles_with_chapters_and_clauses():
    units = split_units(OLD)
    assert [u.key for u in units] == [f"Điều {i}" for i in range(1, 9)]
    d4 = units[3]
    assert d4.title == "Nghỉ phép năm" and d4.chapter.startswith("Chương II") and set(d4.clauses) == {"1", "2", "3"}


def test_split_headings_when_no_articles():
    units = split_units("# Tên\n## 1. Mục đích\nA\n## 2. Phạm vi\nB\n### 2.1 Chi tiết\nC")
    assert [(u.number, u.title) for u in units] == [("1", "Mục đích"), ("2", "Phạm vi"), ("2.1", "Chi tiết")]


def test_compare_classifies_changes():
    r = compare_versions(OLD, NEW)
    by = {(it["old"] or {}).get("key", "-") + ">" + (it["new"] or {}).get("key", "-"): it for it in r["items"]}
    assert by["Điều 2>Điều 2"]["change"] == "UNCHANGED"
    assert by["Điều 1>Điều 1"]["change"] == "MODIFIED"
    d4 = by["Điều 4>Điều 4"]
    assert d4["change"] == "MODIFIED"
    assert {c["clause"]: c["change"] for c in d4["clauses"]} == {"1": "MODIFIED", "2": "MODIFIED", "4": "ADDED"}
    assert "12" in d4["numbers_changed"] and "14" in d4["numbers_changed"]
    assert by["-" + ">Điều 6"]["change"] == "ADDED"                       # Làm việc từ xa
    assert by["Điều 6>Điều 7"]["change"] == "MOVED_MODIFIED"            # Công tác phí: đổi số và đổi mức tiền
    assert by["Điều 7>-"]["change"] == "REMOVED"                         # Khen thưởng bị bỏ
    assert r["counts"]["ADDED"] == 1 and r["counts"]["REMOVED"] == 1


def test_identical_versions_all_unchanged():
    r = compare_versions(OLD, OLD)
    assert r["counts"]["UNCHANGED"] == 8 and sum(r["counts"].values()) == 8


def test_compare_endpoint_checks_scope_and_returns_names():
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.analysis import build_router
    from app.retrieval.text import make_chunks

    old = make_chunks("Quy chế 2024", OLD)
    new = make_chunks("Quy chế 2026", NEW)
    mine = {old[0].source_id: old, new[0].source_id: new}
    store = SimpleNamespace(chunks=lambda ids: [c for i in (ids or []) for c in mine.get(i, [])])  # chỉ tài liệu của người dùng
    pipe = SimpleNamespace(source_store=store)
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u"}, owner_pipeline=lambda user, *a: pipe, session_factory=lambda: None))
    c = TestClient(app)
    r = c.post("/api/studio/tools/compare", json={"old_source_id": old[0].source_id, "new_source_id": new[0].source_id})
    assert r.status_code == 200 and r.json()["new"]["source_name"] == "Quy chế 2026" and r.json()["counts"]["ADDED"] == 1
    assert c.post("/api/studio/tools/compare", json={"old_source_id": old[0].source_id, "new_source_id": "src_cua_nguoi_khac"}).status_code == 404
    assert c.post("/api/studio/tools/compare", json={"old_source_id": old[0].source_id, "new_source_id": old[0].source_id}).status_code == 422
