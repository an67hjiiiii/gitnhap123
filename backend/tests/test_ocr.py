"""Đợt 10: OCR bằng Tesseract cục bộ — báo rõ khi chưa cài/thiếu tiếng Việt; gọi đúng ngôn ngữ vie+eng."""
import subprocess
from types import SimpleNamespace

from app.ingestion import ocr


def test_not_installed_reports_reason(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_cmd", lambda: None)
    st = ocr.ocr_status()
    assert st["available"] is False and "Tesseract" in st["reason"]


def test_missing_vietnamese_pack_is_reported(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_cmd", lambda: "tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="List of available languages (2):\neng\nosd\n", stderr="", returncode=0))
    st = ocr.ocr_status()
    assert st["available"] is False and "vie" in st["reason"]


def test_image_ocr_calls_tesseract_with_vietnamese(monkeypatch):
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return SimpleNamespace(stdout="QUYẾT ĐỊNH\nĐiều 1.".encode("utf-8"), stderr=b"", returncode=0)

    monkeypatch.setattr(ocr, "tesseract_cmd", lambda: "tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    assert ocr.ocr_image(b"\x89PNG", ".png") == "QUYẾT ĐỊNH\nĐiều 1."
    assert calls[0][0] == "tesseract" and calls[0][2:] == ["stdout", "-l", "vie+eng"]


def test_failed_ocr_raises(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_cmd", lambda: "tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=b"", stderr=b"Error opening data file", returncode=1))
    try:
        ocr.ocr_image(b"x", ".png")
    except RuntimeError as exc:
        assert "OCR_FAILED" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
