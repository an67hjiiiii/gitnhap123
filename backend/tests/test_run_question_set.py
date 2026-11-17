import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_question_set.py"
SPEC = importlib.util.spec_from_file_location("run_question_set", SCRIPT)
qset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qset)


def test_groups_conversation_rows_by_sequence():
    rows = [
        {"id": "a", "ma_chuoi": "x", "luot": "2"},
        {"id": "b", "ma_chuoi": "y", "luot": "1"},
        {"id": "c", "ma_chuoi": "x", "luot": "1"},
        {"id": "d", "ma_chuoi": "", "luot": "1"},
    ]
    assert [r["id"] for r in qset.ordered_rows(rows)] == ["c", "a", "b", "d"]


def test_normalize_numbers_units_and_dates():
    assert qset.extract_values("30 phút") == ["phut:30"]
    assert qset.extract_values("0,5 giờ") == ["phut:30"]
    assert qset.extract_values("12 tháng") == ["thang:12"]
    assert qset.extract_values("một năm (12 tháng)") == ["thang:12"]
    assert qset.extract_values("Ngày 03/04/2025") == ["date:2025-04-03"]


def test_summary_reports_inconsistency():
    tmp_path = SCRIPT.parent / "_qset_test_summary"
    if tmp_path.exists(): shutil.rmtree(tmp_path)
    tmp_path.mkdir()
    records = [
        {"id": "1", "nhom_noi_dung": "CS_API", "muc_hiem": "thường", "kieu_loi": "đơn vị",
         "kieu_cau": "trực tiếp", "answer": "Thời hạn là 30 phút", "secs": 2, "guard_notes": []},
        {"id": "2", "nhom_noi_dung": "CS_API", "muc_hiem": "thường", "kieu_loi": "đơn vị",
         "kieu_cau": "trực tiếp", "answer": "Thời hạn là 0,5 giờ", "secs": 4, "guard_notes": []},
        {"id": "3", "nhom_noi_dung": "CS_DANGNHAP", "muc_hiem": "hiếm", "kieu_loi": "số",
         "kieu_cau": "trực tiếp", "answer": "12 tháng", "secs": 1, "guard_notes": []},
        {"id": "4", "nhom_noi_dung": "CS_DANGNHAP", "muc_hiem": "hiếm", "kieu_loi": "số",
         "kieu_cau": "trực tiếp", "answer": "một năm", "secs": 1, "guard_notes": []},
    ]
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    qset.summary_command(tmp_path)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    table = summary.split("## NHẤT QUÁN theo nhóm nội dung", 1)[1]
    assert "CS_API" not in table
    assert "CS_DANGNHAP" not in table
    shutil.rmtree(tmp_path)


def test_manifest_match_skips_when_results_complete(monkeypatch, capsys):
    tmp_path = SCRIPT.parent / "_qset_test_manifest"
    if tmp_path.exists(): shutil.rmtree(tmp_path)
    tmp_path.mkdir()
    csv_file = tmp_path / "input.csv"
    csv_file.write_text(
        "id,muc_hiem,nhom_noi_dung,kieu_cau,ma_chuoi,luot,cau_hoi,kieu_loi,dap_an_tham_khao,phien_ban_dung,do_chac\n"
        "X1,,,,,1,Câu hỏi,,,,\n", encoding="utf-8")
    out = tmp_path / "out"; out.mkdir()
    fake = SimpleNamespace(call=lambda *a, **kw: (200, {"sources": []}), login=lambda: 200)
    monkeypatch.setattr(qset, "read_flags", lambda _: {k: v for k, v in qset.EXPECTED.items()})
    manifest = qset.build_manifest(csv_file, fake, qset.EXPECTED)
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (out / "results.jsonl").write_text(json.dumps({"id": "X1"}) + "\n", encoding="utf-8")
    args = SimpleNamespace(out=str(out), csv=str(csv_file), base="unused", force=False)
    assert qset.run_command(args, client=fake) == 0
    assert "BỎ QUA: không đổi" in capsys.readouterr().out
    shutil.rmtree(tmp_path)


def test_run_sends_group_conversation_and_appends_results(monkeypatch):
    tmp_path = SCRIPT.parent / "_qset_test_run"
    if tmp_path.exists(): shutil.rmtree(tmp_path)
    tmp_path.mkdir()
    csv_file = tmp_path / "input.csv"
    header = ",".join(qset.COLUMNS)
    csv_file.write_text(header + "\n" +
        "A,,,,thread,2,Câu hai,,,,\n" + "B,,,,thread,1,Câu một,,,,\n", encoding="utf-8")
    out = tmp_path / "out"
    class Fake:
        def __init__(self): self.payloads = []; self.n = 0
        def call(self, method, path, data=None, **kwargs):
            if path == "/api/sources": return 200, {"sources": []}
            if path == "/api/chat":
                self.payloads.append(data); self.n += 1
                return 200, {"answer": "Đã trả lời", "status": "ok", "conversation_id": "conv1", "events": []}
            return 404, {}
        def login(self): return 200
    fake = Fake()
    monkeypatch.setattr(qset, "read_flags", lambda _: {k: v for k, v in qset.EXPECTED.items()})
    args = SimpleNamespace(out=str(out), csv=str(csv_file), base="unused", force=False)
    assert qset.run_command(args, client=fake) == 0
    assert [p["message"] for p in fake.payloads] == ["Câu một", "Câu hai"]
    assert fake.payloads[1]["conversation_id"] == "conv1"
    assert len(qset.load_results(out / "results.jsonl")) == 2
    shutil.rmtree(tmp_path)
