"""Đọc Word/Excel bằng thư viện chuẩn: văn bản, tiêu đề, bảng, trang tính; tệp hỏng và tệp nén bom bị chặn."""
import io
import zipfile

import pytest

from app.ingestion.documents import DocumentTypeError, extract_document

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_docx_paragraphs_headings_tables():
    doc = (f'<w:document {W}><w:body>'
           '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Điều 10. Cảnh báo học tập</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Điểm trung bình dưới </w:t></w:r><w:r><w:t>1,0 thì bị cảnh báo.</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Loại</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Mức</w:t></w:r></w:p></w:tc></w:tr>'
           '<w:tr><w:tc><w:p><w:r><w:t>Giỏi</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>100%</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    out = extract_document(_zip({"word/document.xml": doc}), "quy_che.docx")
    assert out.text == "# Điều 10. Cảnh báo học tập\n\nĐiểm trung bình dưới 1,0 thì bị cảnh báo.\n\nLoại | Mức\nGiỏi | 100%"
    assert out.provenance["parser"] == "stdlib-ooxml-docx-v1" and out.source_format == "docx"


def test_xlsx_sheets_shared_inline_and_numbers():
    files = {
        "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="Lương" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst {S}><si><t>Loại ngày</t></si><si><t>Hệ số</t></si><si><t>Ngày lễ</t></si></sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData>'
                                    '<row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>'
                                    '<row><c t="s"><v>2</v></c><c><v>300</v></c></row>'
                                    '<row><c t="inlineStr"><is><t>Ghi chú</t></is></c></row>'
                                    '</sheetData></worksheet>',
    }
    out = extract_document(_zip(files), "luong.xlsx")
    assert out.text == "## Lương\nLoại ngày | Hệ số\nNgày lễ | 300\nGhi chú"


def test_damaged_and_bomb_files_rejected():
    with pytest.raises(DocumentTypeError):
        extract_document(b"not a zip", "x.docx")
    bomb = _zip({"word/document.xml": b"0" * 41_000_000})  # nén còn vài chục KB, giải nén vượt giới hạn
    assert len(bomb) < 2_000_000
    with pytest.raises(DocumentTypeError, match="too large"):
        extract_document(bomb, "x.docx")
    with pytest.raises(DocumentTypeError, match="no cell values"):
        extract_document(_zip({"xl/workbook.xml": f"<workbook {S}><sheets/></workbook>"}), "empty.xlsx")
