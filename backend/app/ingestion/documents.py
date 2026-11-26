from __future__ import annotations

import csv
import hashlib
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from app.retrieval.text import normalize_text


DOCUMENT_INGESTION_VERSION = "s2-document-ingestion-v1"
MAX_DOCUMENT_BYTES = 20_000_000  # 21/11: nâng từ 2 MB theo yêu cầu chủ dự án; giới hạn giải nén Office giữ 40 MB
SUPPORTED_TEXT_EXTENSIONS = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".sql": "text/plain",  # lược đồ CSDL: giao diện Studio cho phép chọn .sql
    ".csv": "text/csv",  # bảng dữ liệu CSV: hỗ trợ tải trực tiếp vào kho tài liệu
}
SUPPORTED_DOCUMENT_EXTENSIONS = {
    **SUPPORTED_TEXT_EXTENSIONS,
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
# Word/Excel là tệp zip chứa XML: chặn tệp nén bom bằng giới hạn dung lượng sau giải nén.
MAX_OFFICE_UNZIPPED_BYTES = 40_000_000


class DocumentTypeError(ValueError):
    """Raised when a document is outside the bounded local ingestion scope."""


@dataclass(frozen=True)
class ExtractedDocument:
    source_name: str
    text: str
    source_type: str
    source_format: str
    byte_size: int
    source_hash: str
    provenance: dict[str, Any]


def extract_document(
    data: bytes | str,
    source_name: str,
    *,
    origin: str = "upload",
    content_type: str | None = None,
) -> ExtractedDocument:
    """Extract UTF-8 TXT/MD or selectable text from a PDF.

    The PDF boundary deliberately uses text extraction only.  Scanned-image
    PDFs fail explicitly; OCR is outside the Sprint 2 contract.
    """

    clean_name = str(source_name or "").strip()
    if not clean_name:
        raise ValueError("source_name must not be empty")
    suffix = Path(clean_name).suffix.casefold()
    source_type = SUPPORTED_DOCUMENT_EXTENSIONS.get(suffix)
    if source_type is None:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise DocumentTypeError(
            f"unsupported document type {suffix or '<none>'}; supported: {supported}"
        )

    if suffix == ".pdf":
        if not isinstance(data, bytes):
            raise TypeError("PDF document data must be bytes")
        byte_size = len(data)
        _assert_size(byte_size)
        raw_text, page_count = _extract_pdf_text(data)
    elif suffix in (".docx", ".xlsx"):
        if not isinstance(data, bytes):
            raise TypeError("Office document data must be bytes")
        byte_size = len(data)
        _assert_size(byte_size)
        raw_text = _extract_docx_text(data) if suffix == ".docx" else _extract_xlsx_text(data)
    elif suffix == ".csv":
        if isinstance(data, bytes):
            byte_size = len(data)
            _assert_size(byte_size)
            try:
                decoded = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise UnicodeError("document must be valid UTF-8") from exc
        elif isinstance(data, str):
            decoded = data.lstrip("\ufeff")
            byte_size = len(data.encode("utf-8"))
            _assert_size(byte_size)
        else:
            raise TypeError("document data must be bytes or text")
        raw_text = _extract_csv_text(decoded)
    elif isinstance(data, bytes):
        byte_size = len(data)
        _assert_size(byte_size)
        try:
            raw_text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnicodeError("document must be valid UTF-8") from exc
    elif isinstance(data, str):
        raw_text = data
        byte_size = len(data.encode("utf-8"))
        _assert_size(byte_size)
    else:
        raise TypeError("document data must be bytes or text")

    text = normalize_text(raw_text)
    if not text:
        raise ValueError("text must not be empty")

    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    provenance: dict[str, Any] = {
        "ingestion_version": DOCUMENT_INGESTION_VERSION,
        "source_type": source_type,
        "source_format": suffix.lstrip("."),
        "source_hash": source_hash,
        "byte_size": byte_size,
        "origin": str(origin or "upload").strip() or "upload",
    }
    if isinstance(content_type, str) and content_type.strip():
        provenance["declared_content_type"] = content_type.strip().lower()
    if suffix == ".pdf":
        provenance.update({"page_count": page_count, "parser": "pypdf-text-v1"})
    elif suffix in (".docx", ".xlsx"):
        provenance["parser"] = f"stdlib-ooxml-{suffix.lstrip('.')}-v1"
    elif suffix == ".csv":
        provenance["parser"] = "stdlib-csv-v1"

    return ExtractedDocument(
        source_name=clean_name,
        text=text,
        source_type=source_type,
        source_format=suffix.lstrip("."),
        byte_size=byte_size,
        source_hash=source_hash,
        provenance=provenance,
    )


def _assert_size(byte_size: int) -> None:
    if byte_size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"document exceeds the {MAX_DOCUMENT_BYTES}-byte size limit")


_GLUED_BULLET_RE = re.compile(r"(?<=[\.\!\?\)\:;])-\s+(?=[A-ZÀ-Ỹ0-9])")


def _clean_glued_bullets(text: str) -> str:
    """Tách các mục danh sách bị dính liền vào cuối câu trước (vd. '...nguyên lương.- Cộng thâm niên:')."""
    return _GLUED_BULLET_RE.sub("\n- ", text)


def _extract_pdf_text(data: bytes) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise DocumentTypeError("PDF text extraction requires pypdf") from exc

    try:
        reader = PdfReader(BytesIO(data), strict=False)
        pages = [_clean_glued_bullets(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise DocumentTypeError("PDF text extraction failed") from exc

    text = "\n\n".join(page for page in pages if page.strip()).strip()
    if not text:
        raise DocumentTypeError(
            "PDF contains no extractable text; scanned-image OCR is not supported"
        )
    return text, len(reader.pages)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _office_xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    # expat >= 2.4 chặn mở rộng thực thể lồng (billion laughs); ElementTree không tải thực thể ngoài
    return ElementTree.fromstring(archive.read(info))


def _open_office(data: bytes, kind: str) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentTypeError(f"{kind} file is damaged or not a real {kind} file") from exc
    if sum(info.file_size for info in archive.infolist()) > MAX_OFFICE_UNZIPPED_BYTES:
        raise DocumentTypeError(f"{kind} file is too large after decompression")
    return archive


def _extract_docx_text(data: bytes) -> str:
    """Đoạn văn theo thứ tự; giữ ngắt dòng mềm (<w:br/>), danh sách (<w:numPr>), tiêu đề '#'; bảng thành dòng 'ô | ô'."""
    with _open_office(data, "DOCX") as archive:
        try:
            root = _office_xml(archive, "word/document.xml")
        except ElementTree.ParseError as exc:
            raise DocumentTypeError("DOCX text extraction failed") from exc
    body = root.find(f"{_W}body") if root is not None else None
    if body is None:
        raise DocumentTypeError("DOCX file has no document body")

    def para(p: ElementTree.Element) -> str:
        pieces: list[str] = []
        for node in p.iter():
            if node.tag == f"{_W}t":
                pieces.append(node.text or "")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                pieces.append("\n")
            elif node.tag == f"{_W}tab":
                pieces.append(" ")
        raw = "".join(pieces)
        lines = [ln.strip() for ln in raw.split("\n")]
        cleaned = "\n".join(ln for ln in lines if ln)
        return _clean_glued_bullets(cleaned).strip()

    def heading_prefix(p: ElementTree.Element) -> str:
        style = p.find(f"{_W}pPr/{_W}pStyle")
        val = (style.get(f"{_W}val") or "").casefold() if style is not None else ""
        if not val:
            return ""
        m = re.search(r"heading\s*([1-6])", val)
        if m:
            lvl = int(m.group(1))
            return "#" * min(lvl, 3) + " "
        if "heading" in val or val == "title":
            return "# "
        return ""

    blocks: list[str] = []
    for el in body:
        if el.tag == f"{_W}p":
            text = para(el)
            if not text:
                continue
            h_pref = heading_prefix(el)
            if h_pref:
                blocks.append(f"{h_pref}{text}")
                continue
            is_list_item = el.find(f"{_W}pPr/{_W}numPr") is not None
            if is_list_item and not re.match(r"^(?:[-*•+]|\d+[.)])\s+", text):
                text = f"- {text}"
            blocks.append(text)
        elif el.tag == f"{_W}tbl":
            rows = [
                " | ".join(
                    " ".join(filter(None, (para(p).replace("\n", " ") for p in cell.iter(f"{_W}p"))))
                    for cell in row.findall(f"{_W}tc")
                )
                for row in el.findall(f"{_W}tr")
            ]
            if rows := [r for r in rows if r.strip(" |")]:
                blocks.append("\n".join(rows))
    text = "\n\n".join(blocks)
    if not text.strip():
        raise DocumentTypeError("DOCX contains no text")
    return text


def _column_index(ref: str | None, fallback: int) -> int:
    """Chỉ số cột từ địa chỉ ô ("C7" -> 2); Excel bỏ qua ô trống nên không đếm theo thứ tự."""
    letters = "".join(ch for ch in (ref or "") if ch.isalpha()).upper()
    if not letters:
        return fallback
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def xlsx_sheets(data: bytes) -> list[tuple[str, list[list[str]]]]:
    """Các trang tính dưới dạng bảng (hàng x cột, giữ đúng vị trí cột); ô công thức lấy giá trị đã lưu."""
    out: list[tuple[str, list[list[str]]]] = []
    with _open_office(data, "XLSX") as archive:
        try:
            shared_root = _office_xml(archive, "xl/sharedStrings.xml")
            workbook = _office_xml(archive, "xl/workbook.xml")
            rels = _office_xml(archive, "xl/_rels/workbook.xml.rels")
            shared = ["".join(t.text or "" for t in si.iter(f"{_S}t")) for si in shared_root.findall(f"{_S}si")] if shared_root is not None else []
            targets = {r.get("Id"): r.get("Target") for r in (rels if rels is not None else [])}
            sheets = workbook.find(f"{_S}sheets") if workbook is not None else None
            for sheet in (list(sheets) if sheets is not None else []):
                target = targets.get(sheet.get(f"{_R}id")) or ""
                path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
                sheet_root = _office_xml(archive, path)
                if sheet_root is None:
                    continue
                rows: list[list[str]] = []
                for row in sheet_root.iter(f"{_S}row"):
                    cells: dict[int, str] = {}
                    for position, c in enumerate(row.findall(f"{_S}c")):
                        kind, v = c.get("t"), c.find(f"{_S}v")
                        if kind == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared):
                            value = shared[int(v.text)]
                        elif kind == "inlineStr":
                            value = "".join(t.text or "" for t in c.iter(f"{_S}t"))
                        else:
                            value = v.text if v is not None and v.text else ""
                        cells[_column_index(c.get("r"), position)] = value.strip()
                    if any(cells.values()):
                        rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
                out.append((sheet.get("name") or "Sheet", rows))
        except ElementTree.ParseError as exc:
            raise DocumentTypeError("XLSX text extraction failed") from exc
    return out


def _extract_xlsx_text(data: bytes) -> str:
    """Mỗi trang tính một phần '## tên trang', mỗi hàng một dòng 'ô | ô'."""
    sections = [f"## {name}\n" + "\n".join(" | ".join(row) for row in rows) for name, rows in xlsx_sheets(data) if rows]
    text = "\n\n".join(sections)
    if not text.strip():
        raise DocumentTypeError("XLSX contains no cell values")
    return text


def _extract_csv_text(text: str) -> str:
    """Đọc bảng CSV (tự nhận dấu phẩy hoặc chấm phẩy) thành các dòng 'ô | ô' nhất quán với XLSX."""
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        raise ValueError("text must not be empty")
    return "\n".join(" | ".join(row) for row in rows)


__all__ = [
    "DOCUMENT_INGESTION_VERSION",
    "MAX_DOCUMENT_BYTES",
    "SUPPORTED_TEXT_EXTENSIONS",
    "SUPPORTED_DOCUMENT_EXTENSIONS",
    "DocumentTypeError",
    "ExtractedDocument",
    "extract_document",
    "xlsx_sheets",
]
