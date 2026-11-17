"""Chạy bộ câu hỏi tuần tự với backend scratch, lưu JSONL có thể tiếp tục."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import http.cookiejar
from pathlib import Path

FLAGS = ("CHUNK_MODE", "INGEST_CLEAN", "VERSION_PROPOSE", "VERSION_FILTER",
         "VERSION_DIFF", "RETRIEVAL_FUSION", "QUERY_NORMALIZE")
EXPECTED = {"CHUNK_MODE": "legal", "INGEST_CLEAN": "rules", "VERSION_PROPOSE": "1",
            "VERSION_FILTER": "on", "VERSION_DIFF": "1", "RETRIEVAL_FUSION": "off"}
COLUMNS = ("id", "muc_hiem", "nhom_noi_dung", "kieu_cau", "ma_chuoi", "luot", "cau_hoi",
           "kieu_loi", "dap_an_tham_khao", "phien_ban_dung", "do_chac")
HERE = Path(__file__).resolve().parent


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, data=None, headers=None, timeout=300):
        body = data
        h = dict(headers or {})
        if isinstance(data, (dict, list)):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                raw = response.read()
                try: result = json.loads(raw or b"{}")
                except (ValueError, UnicodeDecodeError): result = {"body": raw.decode("utf-8", "replace")}
                return response.status, result
        except urllib.error.HTTPError as exc:
            return exc.code, {"error": exc.read()[:1000].decode("utf-8", "replace")}
        except Exception as exc:
            return 0, {"error": str(exc)}

    def login(self):
        # Scratch-only credentials may be overridden by environment; never print or persist them.
        email = os.environ.get("QSET_EMAIL", "qset-scratch@example.test")
        password = os.environ.get("QSET_PASSWORD", "qset-scratch-pass-123")
        code, _ = self.call("POST", "/api/auth/login", {"identifier": email, "password": password})
        if code != 200:
            self.call("POST", "/api/auth/register", {"email": email, "password": password,
                                                        "display_name": "Question Set Scratch"})
            code, _ = self.call("POST", "/api/auth/login", {"identifier": email, "password": password})
        return code


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing: raise ValueError("Thiếu cột CSV: " + ", ".join(missing))
        return [{k: (row.get(k) or "") for k in COLUMNS} for row in reader]


def ordered_rows(rows):
    indexed = list(enumerate(rows))
    grouped = {}
    for index, row in indexed:
        key = row.get("ma_chuoi", "").strip()
        if key: grouped.setdefault(key, []).append((index, row))
    for group in grouped.values(): group.sort(key=lambda x: (numeric_order(x[1].get("luot", "")), x[0]))
    out, done = [], set()
    for index, row in indexed:
        key = row.get("ma_chuoi", "").strip()
        if not key:
            out.append(row)
        elif key not in done:
            out.extend(item for _, item in grouped[key]); done.add(key)
    return out


def numeric_order(value):
    try: return (0, float(value))
    except (TypeError, ValueError): return (1, str(value))


def file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def git_state():
    def git(*args):
        try: return subprocess.run(["git", *args], cwd=HERE.parent.parent, capture_output=True, check=False).stdout
        except OSError: return b""
    return {"head": git("rev-parse", "HEAD").decode("ascii", "replace").strip(),
            "diff_sha256": hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest()}


def source_manifest(client):
    code, result = client.call("GET", "/api/sources")
    sources = result.get("sources", []) if isinstance(result, dict) else []
    normalized = []
    for s in sources:
        normalized.append({"name": s.get("source_name") or s.get("doc_name") or "",
                           "size": s.get("size", s.get("file_size", s.get("size_bytes")))})
    return code, sorted(normalized, key=lambda x: x["name"])


def build_manifest(csv_path, client, flags):
    code, sources = source_manifest(client)
    return {"git": git_state(), "flags": {k: flags.get(k, "") for k in FLAGS},
            "sources_http": code, "sources": sources, "csv_sha256": file_sha(csv_path)}


def read_flags(out):
    path = out / "flags.json"
    values = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict): values.update({k: str(v) for k, v in loaded.items()})
        except (OSError, ValueError): print("CẢNH BÁO: flags.json không đọc được; dùng biến môi trường.", flush=True)
    for key in FLAGS:
        if key in os.environ: values[key] = os.environ[key]
    return values


def warn_flags(flags):
    bad = [(key, flags.get(key, "<chưa đặt>"), expected) for key, expected in EXPECTED.items()
           if flags.get(key) != expected]
    if bad:
        print("CẢNH BÁO CỜ KHÔNG CHUẨN: " + "; ".join(f"{k}={v} (chuẩn {e})" for k, v, e in bad), flush=True)


def extract_top(client, response):
    events = response.get("events") or []
    selected = next((e.get("selected") for e in events if e.get("stage") == "vanilla_retrieval"), None) or []
    result = []
    for item in selected[:5]:
        cid = item if isinstance(item, str) else item.get("chunk_id", item.get("id"))
        chunk = item if isinstance(item, dict) and ("text" in item or "source_name" in item) else None
        if cid and chunk is None:
            from urllib.parse import quote
            _, chunk = client.call("GET", "/api/chunks/" + quote(str(cid), safe=""))
        chunk = chunk or {}
        match = re.search(r"Điều\s+\d+", chunk.get("text", ""), re.I)
        name = chunk.get("source_name") or chunk.get("doc_name") or "?"
        result.append(f"{name}#{match.group(0) if match else ''}")
    guard = [note for event in events if event.get("stage") == "answer_guard"
             for note in (event.get("notes") or [])]
    return result, guard


def append_jsonl(path, row):
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())


def run_command(args, client=None):
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    csv_path = Path(args.csv).resolve()
    rows = ordered_rows(read_csv(csv_path))
    client = client or Client(args.base)
    flags = read_flags(out); warn_flags(flags)
    manifest = build_manifest(csv_path, client, flags)
    manifest_path, results_path = out / "manifest.json", out / "results.jsonl"
    old = None
    try: old = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError): pass
    existing = load_results(results_path)
    expected_ids = {str(r["id"]) for r in rows}
    if not args.force and old == manifest and expected_ids.issubset(existing):
        print("BỎ QUA: không đổi"); return 0
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    login_code = client.login()
    if login_code != 200: print(f"Đăng nhập scratch thất bại: HTTP {login_code}", flush=True)
    conversations = {}
    for row in rows:
        rid = str(row["id"])
        if rid in existing: continue
        group = row.get("ma_chuoi", "").strip()
        payload = {"message": row["cau_hoi"], "product_mode": True}
        if group in conversations: payload["conversation_id"] = conversations[group]
        start = time.perf_counter()
        code, response = client.call("POST", "/api/chat", payload, timeout=900)
        secs = round(time.perf_counter() - start, 3)
        if isinstance(response, dict) and response.get("conversation_id"):
            if group: conversations[group] = response["conversation_id"]
        top5, guard = extract_top(client, response if isinstance(response, dict) else {})
        record = {**row, "id": row["id"], "cau_hoi": row["cau_hoi"],
                  "answer": (response.get("answer", "") if isinstance(response, dict) else ""),
                  "status": response.get("status", "error") if isinstance(response, dict) else "error",
                  "top5": top5, "guard_notes": guard, "secs": secs, "http": code}
        append_jsonl(results_path, record); existing[rid] = record
        print(f"{rid}: HTTP {code} {secs:.3f}s", flush=True)
    return 0


def load_results(path):
    result = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if "id" in row: result[str(row["id"])] = row
                except ValueError: continue
    except OSError: pass
    return result


NUMBER = r"\d+(?:[.,]\d+)?"
VALUE_RE = re.compile(rf"(?<![\w/])({NUMBER})\s*(phút|phut|giờ|gio|tháng|thang|năm|nam|ngày|ngay)?", re.I)
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _num(v):
    return float(v.replace(",", "."))


def extract_values(text):
    values = []
    dates = [(m.start(), m.end(), f"date:{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}")
             for m in DATE_RE.finditer(text or "")]
    for m in VALUE_RE.finditer(text or ""):
        if any(a <= m.start() < b for a, b, _ in dates): continue
        n, unit = _num(m.group(1)), (m.group(2) or "").lower()
        if unit in ("phút", "phut"): value = f"phut:{n:g}"
        elif unit in ("giờ", "gio"): value = f"phut:{n * 60:g}"
        elif unit in ("tháng", "thang"): value = f"thang:{n:g}"
        elif unit in ("năm", "nam"): value = f"thang:{n * 12:g}"
        elif unit in ("ngày", "ngay"): value = f"ngay:{n:g}"
        else: value = f"so:{n:g}"
        values.append(value)
    # Các cách ghi số bằng chữ thường gặp trong câu trả lời tiếng Việt.
    lower = (text or "").lower()
    if re.search(r"\bmột\s+năm\b", lower): values.append("thang:12")
    if re.search(r"\bmột\s+giờ\b", lower): values.append("phut:60")
    if re.search(r"\bmột\s+ngày\b", lower): values.append("ngay:1")
    values.extend(x[2] for x in dates)
    return sorted(set(values))


def markdown_table(headers, rows):
    clean = lambda x: str(x).replace("|", "\\|").replace("\n", " ")
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "".join(
        "| " + " | ".join(clean(v) for v in row) + " |\n" for row in rows)


def summary_command(out):
    out = Path(out); records = list(load_results(out / "results.jsonl").values())
    lines = ["# Tóm tắt bộ câu hỏi", "", f"Số câu: {len(records)}", ""]
    def stats(label, key):
        groups = {}
        for r in records: groups.setdefault(str(r.get(key, "")), []).append(r)
        lines.extend([f"## Theo {label}", "", markdown_table([label, "Số câu", "Giây TB", "% guard bỏ số", '% "chưa tìm thấy"'], [
            (name, len(items), f"{sum(float(x.get('secs') or 0) for x in items)/len(items):.2f}",
             f"{100*sum(any('số' in str(n).lower() or 'number' in str(n).lower() for n in x.get('guard_notes', [])) for x in items)/len(items):.1f}%",
             f"{100*sum('chưa tìm thấy' in str(x.get('answer', '')).lower() for x in items)/len(items):.1f}%")
            for name, items in sorted(groups.items())]), ""])
    for key, label in (("muc_hiem", "mức hiếm"), ("kieu_loi", "kiểu lỗi"), ("kieu_cau", "kiểu câu")): stats(label, key)
    by_group = {}
    for r in records:
        key = str(r.get("nhom_noi_dung", "")).strip()
        if key: by_group.setdefault(key, []).append(r)
    inconsistent = []
    for key, items in sorted(by_group.items()):
        if len(items) < 2: continue
        vals = {tuple(extract_values(str(x.get("answer", "")))) for x in items}
        if len(vals) > 1:
            inconsistent.append((key, "không nhất quán", ", ".join(str(x.get("id", "")) for x in items)))
    lines.extend(["## NHẤT QUÁN theo nhóm nội dung", ""])
    lines.append(markdown_table(["nhom_noi_dung", "Kết quả", "ID"], inconsistent or [("—", "nhất quán", "")]))
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with (out / "cham_tay.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "cau_hoi", "dap_an_tham_khao", "answer", "dung", "mot_phan", "sai", "nhan_loi"])
        writer.writeheader()
        for r in records:
            writer.writerow({"id": r.get("id", ""), "cau_hoi": r.get("cau_hoi", ""),
                             "dap_an_tham_khao": r.get("dap_an_tham_khao", ""), "answer": r.get("answer", ""),
                             "dung": "", "mot_phan": "", "sai": "", "nhan_loi": ""})


def ingest_command(directory, base):
    client = Client(base); code = client.login()
    if code != 200: print(f"Đăng nhập scratch thất bại: HTTP {code}"); return 1
    allowed = {".txt", ".md", ".docx", ".pdf"}
    for path in sorted(Path(directory).rglob("*") if Path(directory).is_dir() else []):
        if not path.is_file() or path.suffix.lower() not in allowed: continue
        boundary = "----qset" + str(time.time_ns())
        content_type = {".txt": "text/plain", ".md": "text/markdown", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".pdf": "application/pdf"}[path.suffix.lower()]
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                f'Content-Type: {content_type}\r\n\r\n').encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        status, _ = client.call("POST", "/api/sources/file", body,
                                {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=900)
        print(f"{path.name}: HTTP {status}", flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chạy bộ câu hỏi trên backend scratch.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Chạy CSV tuần tự và lưu kết quả tiếp tục được.")
    run.add_argument("--csv", required=True); run.add_argument("--out", required=True)
    run.add_argument("--base", default="http://127.0.0.1:8110"); run.add_argument("--force", action="store_true")
    summ = sub.add_parser("summary", help="Tạo summary.md và cham_tay.csv, không chấm bằng mô hình.")
    summ.add_argument("--out", required=True)
    ing = sub.add_parser("ingest", help="Nạp tài liệu lên backend scratch.")
    ing.add_argument("--dir", required=True); ing.add_argument("--base", default="http://127.0.0.1:8110")
    ing.epilog = "CHỈ dùng với backend scratch (8110, DB scratch mới); không dùng với 8000. Mật khẩu lấy từ QSET_PASSWORD hoặc mặc định scratch, không in ra."
    args = parser.parse_args(argv)
    if args.command == "run": return run_command(args)
    if args.command == "summary": summary_command(args.out); return 0
    return ingest_command(args.dir, args.base)


if __name__ == "__main__":
    raise SystemExit(main())
