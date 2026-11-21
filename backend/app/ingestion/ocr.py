"""Nhận dạng chữ (OCR) cho bản scan và ảnh chụp (đợt 10), chạy cục bộ bằng Tesseract có gói tiếng Việt.

Không thêm thư viện Python: gọi chương trình `tesseract` (TESSERACT_CMD, PATH, hoặc thư mục cài mặc định trên Windows).
PDF scan: lấy ảnh nhúng trong từng trang bằng pypdf (đã có sẵn) rồi nhận dạng. Máy chưa cài Tesseract thì báo rõ, không đoán.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_EXTENSIONS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".tif": "image/tiff", ".tiff": "image/tiff"}
_WINDOWS_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
LANGS = "vie"  # 21/11: "vie+eng" làm rơi dấu cả dòng khi Tesseract đoán nhầm tiếng Anh; gói vie đã có đủ chữ Latin


def tesseract_cmd() -> str | None:
    cmd = os.getenv("TESSERACT_CMD", "").strip() or shutil.which("tesseract")
    if not cmd and _WINDOWS_DEFAULT.is_file():
        cmd = str(_WINDOWS_DEFAULT)
    return cmd or None


def ocr_status() -> dict:
    """{available, languages, reason}: có chạy OCR tiếng Việt được không."""
    cmd = tesseract_cmd()
    if not cmd:
        return {"available": False, "reason": "Máy chủ chưa cài Tesseract OCR."}
    try:
        out = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": f"Không chạy được Tesseract ({type(exc).__name__})."}
    langs = {line.strip() for line in (out.stdout + out.stderr).splitlines()[1:] if line.strip()}
    if "vie" not in langs:
        return {"available": False, "languages": sorted(langs), "reason": "Tesseract thiếu gói tiếng Việt (vie)."}
    return {"available": True, "languages": sorted(langs)}


def ocr_image(data: bytes, suffix: str = ".png") -> str:
    cmd = tesseract_cmd()
    if not cmd:
        raise RuntimeError("OCR_UNAVAILABLE")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"page{suffix}"
        path.write_bytes(data)
        out = subprocess.run([cmd, str(path), "stdout", "-l", LANGS], capture_output=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError("OCR_FAILED: " + out.stderr.decode("utf-8", "replace")[:200])
    return out.stdout.decode("utf-8", "replace").strip()


def ocr_pdf(data: bytes, max_pages: int = 50) -> str:
    """Nhận dạng ảnh nhúng của từng trang PDF scan (mỗi trang thường là một ảnh JPEG/PNG)."""
    from pypdf import PdfReader

    texts = []
    for number, page in enumerate(PdfReader(io.BytesIO(data)).pages[:max_pages], start=1):
        parts = []
        for image in page.images:
            suffix = Path(image.name).suffix.lower() or ".png"
            parts.append(ocr_image(image.data, suffix if suffix in IMAGE_EXTENSIONS else ".png"))
        if any(p.strip() for p in parts):
            texts.append(f"## Trang {number}\n" + "\n".join(p for p in parts if p.strip()))
    return "\n\n".join(texts)


__all__ = ["IMAGE_EXTENSIONS", "ocr_image", "ocr_pdf", "ocr_status", "tesseract_cmd"]
