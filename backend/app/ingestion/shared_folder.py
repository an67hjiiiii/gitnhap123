"""Kết nối nguồn: thư mục chung trên máy chủ (đợt 10). Quản trị đặt SHARED_FOLDER_PATH; người dùng bấm đồng bộ để nạp tệp mới.

Chỉ đọc trong thư mục đã cấu hình (không theo liên kết ra ngoài), chỉ định dạng đã hỗ trợ, tối đa 2 MB mỗi tệp như khi tải lên.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.ingestion.documents import SUPPORTED_DOCUMENT_EXTENSIONS

MAX_BYTES = 2_000_000
MAX_FILES = 300


def shared_root() -> Path | None:
    raw = os.getenv("SHARED_FOLDER_PATH", "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser()
    return root.resolve() if root.is_dir() else None


def list_shared_files(root: Path) -> tuple[list[Path], list[dict]]:
    """Tệp nạp được và tệp bỏ qua (kèm lý do). Đường dẫn tương đối dùng làm tên tài liệu."""
    files, skipped = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        real = path.resolve()
        if root not in real.parents:  # liên kết trỏ ra ngoài thư mục chung
            skipped.append({"name": rel, "reason": "ngoài thư mục chung"})
        elif path.suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
            skipped.append({"name": rel, "reason": "định dạng chưa hỗ trợ"})
        elif path.stat().st_size > MAX_BYTES:
            skipped.append({"name": rel, "reason": "lớn hơn 2 MB"})
        elif len(files) >= MAX_FILES:
            skipped.append({"name": rel, "reason": f"quá {MAX_FILES} tệp mỗi lần"})
        else:
            files.append(path)
    return files, skipped


__all__ = ["MAX_BYTES", "list_shared_files", "shared_root"]
