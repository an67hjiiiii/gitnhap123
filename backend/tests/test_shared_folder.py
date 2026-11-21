"""Đợt 10: kết nối thư mục chung — chỉ đọc trong thư mục cấu hình, đúng định dạng, đúng giới hạn kích thước."""
from app.ingestion.shared_folder import list_shared_files, shared_root


def test_lists_supported_files_and_explains_skipped(tmp_path, monkeypatch):
    (tmp_path / "phong_dao_tao").mkdir()
    (tmp_path / "phong_dao_tao" / "quy_che.txt").write_text("Điều 1. Quy chế.", encoding="utf-8")
    (tmp_path / "noi_quy.md").write_text("# Nội quy", encoding="utf-8")
    (tmp_path / "virus.exe").write_bytes(b"MZ")
    (tmp_path / "lon.txt").write_bytes(b"a" * 20_000_001)
    files, skipped = list_shared_files(tmp_path.resolve())
    assert [p.relative_to(tmp_path).as_posix() for p in files] == ["noi_quy.md", "phong_dao_tao/quy_che.txt"]
    reasons = {s["name"]: s["reason"] for s in skipped}
    assert reasons == {"virus.exe": "định dạng chưa hỗ trợ", "lon.txt": "lớn hơn 20 MB"}


def test_not_configured_or_missing_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("SHARED_FOLDER_PATH", raising=False)
    assert shared_root() is None
    monkeypatch.setenv("SHARED_FOLDER_PATH", str(tmp_path / "khong_co"))
    assert shared_root() is None
    monkeypatch.setenv("SHARED_FOLDER_PATH", str(tmp_path))
    assert shared_root() == tmp_path.resolve()
