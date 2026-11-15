"""Lập danh mục giấy phép thư viện bên thứ ba được đóng gói cùng OrchestrIQ Studio -> THIRD_PARTY_LICENSES.md.

Nguồn dữ liệu (đọc từ máy, không gọi mạng):
- Giao diện: frontend/package-lock.json, chỉ gói chạy thật (bỏ gói "dev": công cụ build/test không phát hành).
- Backend: các gói Python cài trong backend/.venv mà requirements.txt cần khi chạy (bỏ pytest), tính cả gói phụ thuộc.
Gói không ghi giấy phép được đánh dấu "Chưa rõ" để kiểm tra tay, không đoán.
Dùng: backend/.venv/Scripts/python.exe scripts/dev/licenses.py
"""
from __future__ import annotations

import json
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNKNOWN = "Chưa rõ"
DEV_ONLY_PY = {"pytest", "pluggy", "iniconfig", "colorama", "packaging"}  # chỉ phục vụ chạy test
# những giấy phép cần đọc kỹ điều khoản trước khi bán (không phải loại MIT/BSD/Apache dễ dãi)
REVIEW = re.compile(r"gpl|agpl|lgpl|sspl|busl|commons clause|see license|standard|proprietary|" + UNKNOWN.lower(), re.I)


def frontend_packages() -> list[tuple[str, str, str]]:
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    rows = []
    for path, info in lock.get("packages", {}).items():
        if not path or info.get("dev") or info.get("devOptional"):
            continue
        name = path.split("node_modules/")[-1]
        lic = info.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type")
        rows.append((name, info.get("version", ""), (lic or UNKNOWN).strip()))
    return sorted(set(rows))


def _req_name(req: str) -> str:
    return re.split(r"[\s;\[<>=!~(]", req.strip(), maxsplit=1)[0].lower().replace("_", "-")


def python_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr.strip()
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    classifiers = [c for c in classifiers if c not in ("OSI Approved",)]
    if classifiers:
        return ", ".join(sorted(set(classifiers)))
    lic = (meta.get("License") or "").strip()
    # một số gói chép cả văn bản giấy phép vào trường License: chỉ giữ dòng đầu
    return lic.splitlines()[0][:80] if lic else UNKNOWN


def backend_packages() -> list[tuple[str, str, str]]:
    reqs = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8").splitlines()
    todo = [_req_name(r) for r in reqs if r.strip() and not r.startswith("#")]
    seen: dict[str, metadata.Distribution] = {}
    while todo:
        name = todo.pop()
        if name in seen or name in DEV_ONLY_PY:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[name] = dist
        for r in dist.requires or []:
            # bỏ phụ thuộc chỉ dùng cho tùy chọn (extra) chưa được yêu cầu
            if "extra ==" in r and not re.search(r'extra == "standard"|extra == "binary"', r):
                continue
            todo.append(_req_name(r))
    return sorted((d.metadata["Name"], d.version, python_license(d)) for d in seen.values())


# Thành phần chạy kèm nhưng không nằm trong hai danh sách trên (khách tự cài hoặc tải về).
EXTERNAL = [
    ("Ollama", "máy chủ chạy mô hình cục bộ", "MIT"),
    ("qwen3:4b (Qwen3)", "mô hình ngôn ngữ, tải qua Ollama", "Apache-2.0"),
    ("nomic-embed-text", "mô hình embedding, tải qua Ollama", "Apache-2.0"),
    ("PostgreSQL 16", "cơ sở dữ liệu (ảnh Docker postgres:16)", "PostgreSQL License"),
    ("Docker Desktop", "chạy PostgreSQL; khách tự cài", "Điều khoản Docker (miễn phí cho tổ chức nhỏ, doanh nghiệp lớn cần gói trả phí)"),
]


# Ghi chú cho những giấy phép đã đọc (cập nhật khi đổi phiên bản hoặc điều khoản thay đổi).
NOTES = """## Ghi chú về các dòng cần đọc kỹ

- **GSAP, @gsap/react** (giấy phép Standard "no charge" của GSAP/Webflow): cho phép dùng miễn phí trong sản phẩm thương mại;
  điều khoản cấm dùng trong công cụ cạnh tranh với trình dựng hoạt ảnh trực quan của Webflow. OrchestrIQ Studio là công cụ phân tích
  tài liệu, không thuộc loại đó. Đọc lại https://gsap.com/standard-license trước mỗi lần phát hành.
- **psycopg, psycopg-binary** (LGPL-3.0): được dùng như thư viện, không sửa mã nguồn, cài riêng qua pip nên khách có thể thay bản khác.
  Khi phân phối cần giữ thông báo giấy phép và chỉ nguồn tải (https://www.psycopg.org).
- Phông chữ Inter Tight và Be Vietnam Pro (OFL-1.1): được nhúng và bán kèm phần mềm; không được bán riêng phông chữ.
"""


def table(rows: list[tuple[str, str, str]]) -> str:
    out = ["| Gói | Phiên bản | Giấy phép |", "|---|---|---|"]
    out += [f"| {n} | {v} | {'**' + lic + '**' if REVIEW.search(lic) else lic} |" for n, v, lic in rows]
    return "\n".join(out)


def main() -> int:
    fe, be = frontend_packages(), backend_packages()
    flagged = [r for r in fe + be if REVIEW.search(r[2])]
    doc = f"""# Giấy phép thư viện bên thứ ba

Tệp này được tạo tự động bằng `scripts/dev/licenses.py` từ `frontend/package-lock.json` và môi trường `backend/.venv`.
Chạy lại script mỗi khi đổi thư viện. Dòng **in đậm** là giấy phép cần đọc kỹ điều khoản trước khi bán ({len(flagged)} dòng).

## Thành phần chạy kèm

| Thành phần | Vai trò | Giấy phép |
|---|---|---|
""" + "\n".join(f"| {a} | {b} | {c} |" for a, b, c in EXTERNAL) + f"""

## Giao diện (JavaScript, {len(fe)} gói được phát hành)

{table(fe)}

## Backend (Python, {len(be)} gói)

{table(be)}

{NOTES}"""
    (ROOT / "THIRD_PARTY_LICENSES.md").write_text(doc, encoding="utf-8")
    print(f"Đã ghi THIRD_PARTY_LICENSES.md: {len(fe)} gói giao diện, {len(be)} gói backend, {len(flagged)} dòng cần đọc kỹ.")
    for n, v, lic in flagged:
        print(f"  cần đọc kỹ: {n} {v}: {lic}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
