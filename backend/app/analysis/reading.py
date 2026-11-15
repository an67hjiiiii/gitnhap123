"""Đọc và trình bày tài liệu: sơ đồ tư duy, giải thích đoạn bôi đen, báo cáo từ câu trả lời, xuất Word,
kiểm tra cả kho tài liệu, chủ đề được hỏi nhiều.

Sơ đồ "theo cấu trúc", xuất Word, kiểm tra kho và chủ đề chạy tại máy. Sơ đồ "AI tóm lược", giải thích và báo cáo
gọi mô hình cục bộ; mọi nút sơ đồ trỏ về đoạn tài liệu sinh ra nó (mã đoạn ràng buộc enum).
"""

from __future__ import annotations

import io
import math
import re
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from app.analysis.design import _call, _obj, _text
from app.analysis.evaluation import _content_tokens, _fold
from app.analysis.insights import _doc_text, quality_report

_STR = {"type": "string"}
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")
MAX_NODES = 140


def _label(value: object, limit: int = 70) -> str:
    text = re.sub(r"[*`#>]+|(?<!\w)_|_(?!\w)", "", str(value or ""))  # giữ dấu _ trong tên cột như created_at
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = _text(text, 400).strip(" :;,.-")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ---------------- Sơ đồ tư duy theo cấu trúc (tại máy)
def mindmap_outline(source_name: str, chunks, items_per_node: int = 5) -> dict:
    """Cây đề mục của tài liệu (#, ##, ...), mỗi đề mục kèm tối đa vài gạch đầu dòng đầu tiên của nó."""
    ordered = sorted(chunks, key=lambda c: c.index)
    root = {"id": "n0", "label": _label(re.sub(r"\.[^.]+$", "", source_name).replace("_", " ")),
            "chunk_id": ordered[0].chunk_id if ordered else None, "children": []}
    stack: list[tuple[int, dict]] = [(0, root)]
    count, titled = 1, False

    def add(parent: dict, label: str, chunk_id: str, kind: str) -> dict | None:
        nonlocal count
        if count >= MAX_NODES or not label:
            return None
        node = {"id": f"n{count}", "label": label, "chunk_id": chunk_id, "kind": kind, "children": []}
        count += 1
        parent["children"].append(node)
        return node

    for chunk in ordered:
        for line in chunk.text.splitlines():
            line = line.strip()
            heading = _HEADING.match(line)
            if heading:
                level, label = len(heading.group(1)), _label(heading.group(2))
                if level == 1 and not titled and not root["children"]:
                    root.update(label=label, chunk_id=chunk.chunk_id)
                    titled = True
                    continue
                while len(stack) > 1 and stack[-1][0] >= level:
                    stack.pop()
                node = add(stack[-1][1], label, chunk.chunk_id, "heading")
                if node:
                    stack.append((level, node))
                continue
            bullet = _BULLET.match(line)
            parent = stack[-1][1]
            if bullet and parent is not root and sum(c["kind"] == "item" for c in parent["children"]) < items_per_node:
                add(parent, _label(bullet.group(1), 60), chunk.chunk_id, "item")

    if not root["children"]:  # tài liệu không có đề mục: mỗi đoạn một nhánh, nhãn là câu đầu
        for chunk in ordered[:12]:
            first = re.split(r"(?<=[.!?])\s|\n", chunk.text.strip(), maxsplit=1)[0]
            add(root, _label(first, 60), chunk.chunk_id, "heading")
    return {"mode": "outline", "root": root, "links": [], "nodes": count}


# ---------------- Sơ đồ tư duy do mô hình tóm lược
def _walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


async def mindmap_ai(provider, source_name: str, chunks) -> dict:
    # Mã đoạn thật dài (src_<16 hex>_c0001) làm mô hình hết token trước khi đóng JSON: dùng mã ngắn D1, D2... rồi đổi lại.
    ordered = sorted(chunks, key=lambda c: c.index)
    per = max(250, 6000 // max(1, len(ordered)))
    alias, parts, size = {}, [], 0
    for i, c in enumerate(ordered, 1):
        part = f"[D{i}] {c.text[:per]}"
        if parts and size + len(part) > 6000:
            break
        alias[f"D{i}"] = c.chunk_id
        parts.append(part)
        size += len(part)
    text, used, ids = "\n\n".join(parts), len(parts), [c.chunk_id for c in ordered]
    cid = {"type": "string", "enum": list(alias)}
    # Lá là chuỗi (details) thay vì đối tượng lồng cấp ba: qwen3:4b trả về {} với lược đồ lồng ba cấp đối tượng.
    mid = _obj({"label": _STR, "chunk_id": cid, "details": {"type": "array", "items": _STR}})
    top = _obj({"label": _STR, "chunk_id": cid, "children": {"type": "array", "items": mid}})
    schema = _obj({"central": _STR, "branches": {"type": "array", "items": top},
                   "links": {"type": "array", "items": _obj({"from": _STR, "to": _STR, "label": _STR})}})
    system = ("MIND_MAP_BUILDER. Organize the technical document into a mind map an engineer can scan in 30 seconds. "
              "Use only the excerpts. Make 4-7 main branches that together cover the WHOLE document, not just its start. "
              "Each branch has 2-5 sub-topics; details are 1-3 concrete facts per sub-topic (limits, numbers, components, "
              "rules) copied exactly. Labels are short noun phrases of 2-7 words, never full sentences. chunk_id is the "
              "excerpt the node comes from. links connect two sub-topics in DIFFERENT branches that depend on each other "
              "(a flow step, a rule that protects a component), using their exact labels. Write every label in Vietnamese; "
              "keep technical names (table, endpoint, algorithm) as written. Return JSON only.")
    user = f"DOCUMENT: {source_name}\n\nEXCERPTS:\n{text}\n\nTối đa 7 nhánh, 6 liên kết. NGÔN NGỮ: mọi nhãn viết bằng tiếng Việt."
    obj, measured = await _call(provider, system, user, schema, 2000)

    count = 1
    root = {"id": "n0", "label": _label(obj.get("central")) or _label(source_name), "chunk_id": ids[0] if ids else None,
            "kind": "root", "children": []}

    def build(parent: dict, items, depth: int, limit: int) -> None:
        nonlocal count
        seen = set()
        for item in (items or [])[:limit]:
            if isinstance(item, str):
                item = {"label": item}
            if not isinstance(item, dict) or count >= MAX_NODES:
                continue
            label = _label(item.get("label"), 60)
            if not label or label.casefold() in seen:
                continue
            seen.add(label.casefold())
            chunk_id = alias.get(item.get("chunk_id")) or parent.get("chunk_id")
            node = {"id": f"n{count}", "label": label, "chunk_id": chunk_id, "kind": "item" if depth == 3 else "heading", "children": []}
            count += 1
            parent["children"].append(node)
            if depth < 3:
                build(node, item.get("children") if depth == 1 else item.get("details"), depth + 1, 5 if depth == 1 else 3)

    build(root, obj.get("branches"), 1, 7)
    by_label = {n["label"].casefold(): n for n in _walk(root)}
    parent_of = {c["id"]: n["id"] for n in _walk(root) for c in n["children"]}
    links, seen_links = [], set()
    for link in obj.get("links") or []:
        if not isinstance(link, dict):
            continue
        a, b = by_label.get(_label(link.get("from"), 60).casefold()), by_label.get(_label(link.get("to"), 60).casefold())
        if not a or not b or a is b or parent_of.get(a["id"]) == b["id"] or parent_of.get(b["id"]) == a["id"]:
            continue
        key = tuple(sorted((a["id"], b["id"])))
        if key in seen_links:
            continue
        seen_links.add(key)
        links.append({"from": a["id"], "to": b["id"], "label": _label(link.get("label"), 40)})
    return {"mode": "ai", "root": root, "links": links[:6], "nodes": count, "chunks_read": used, "chunks_total": len(chunks), **measured}


# ---------------- Bôi đen để hỏi
async def explain_selection(provider, source_name: str, selection: str, context: str) -> dict:
    schema = _obj({"explanation": _STR, "example": _STR})
    system = ("PLAIN_EXPLAINER. Explain the highlighted passage to a colleague who is not a specialist, in simple words. "
              "Use the surrounding document context to understand what it means in THIS document. If it is a technical "
              "term, say what it is and why it matters here. Do not invent rules, numbers or facts that are not in the "
              "context; general well-known meaning of a term is allowed. Return JSON only.")
    user = (f"DOCUMENT: {source_name}\n\nCONTEXT:\n{context[:2400]}\n\nHIGHLIGHTED:\n{selection}\n\n"
            'Schema: {"explanation":"giải thích dễ hiểu, 2-4 câu","example":"một ví dụ đời thường ngắn, để trống nếu không cần"}\n'
            "NGÔN NGỮ: tiếng Việt.")
    obj, measured = await _call(provider, system, user, schema, 450)
    explanation = _text(obj.get("explanation"), 1200)
    if not explanation:
        raise ValueError("Mô hình không trả lời được phần giải thích.")
    return {"explanation": explanation, "example": _text(obj.get("example"), 400), **measured}


# ---------------- Báo cáo từ câu trả lời
async def answer_report(provider, question: str, answer: str, evidence) -> dict:
    excerpts = "\n\n".join(f"[{c.chunk_id}] ({c.source_name}) {c.text[:700]}" for c in evidence[:8])
    schema = _obj({"title": _STR, "summary": _STR,
                   "sections": {"type": "array", "items": _obj({"heading": _STR, "body": _STR})},
                   "recommendations": {"type": "array", "items": _STR}})
    system = ("REPORT_WRITER. Turn the answer and its source excerpts into a complete, well-structured report for a "
              "project stakeholder. Use only the answer and the excerpts; keep numbers, limits and identifiers exact; do "
              "not add facts. Write 3-5 sections (context, main content, risks or notes when the sources support them). "
              "Return JSON only.")
    user = (f"QUESTION:\n{question}\n\nANSWER:\n{answer[:4000]}\n\nSOURCE EXCERPTS:\n{excerpts or '(không có)'}\n\n"
            'Schema: {"title":"tiêu đề báo cáo","summary":"tóm tắt 2-4 câu","sections":[{"heading":"tên mục","body":'
            '"nội dung mục, có thể nhiều đoạn, gạch đầu dòng bắt đầu bằng - "}],"recommendations":["khuyến nghị cụ thể"]}\n'
            "NGÔN NGỮ: tiếng Việt.")
    obj, measured = await _call(provider, system, user, schema, 1600)
    title = _text(obj.get("title"), 160) or _text(question, 160)
    sections = [(_text(s.get("heading"), 120), str(s.get("body") or "").strip()[:4000])
                for s in (obj.get("sections") or []) if isinstance(s, dict)]
    sections = [(h, b) for h, b in sections if h and b]
    if not sections:
        raise ValueError("Mô hình không viết được nội dung báo cáo.")
    recs = [_text(r, 400) for r in (obj.get("recommendations") or [])[:8] if _text(r)]
    sources, seen = [], set()
    for c in evidence:
        key = (c.source_name, c.index)
        if key not in seen:
            seen.add(key)
            sources.append(f"- {c.source_name} (đoạn {c.index + 1})")
    md = [f"# {title}", "", f"**Câu hỏi:** {question.strip()}", "", "## Tóm tắt", "", _text(obj.get("summary"), 1500), ""]
    for heading, body in sections:
        md += [f"## {heading}", "", body, ""]
    if recs:
        md += ["## Khuyến nghị", "", *[f"- {r}" for r in recs], ""]
    if sources:
        md += ["## Nguồn tham khảo", "", *sources, ""]
    md += ["---", "", "*Báo cáo do mô hình cục bộ biên soạn từ câu trả lời và tài liệu đã truy xuất; cần người kiểm tra trước khi dùng chính thức.*"]
    return {"title": title, "markdown": "\n".join(md), **measured}


# ---------------- Xuất Word (.docx) bằng thư viện chuẩn
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _runs(text: str, bold: bool = False) -> str:
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)", _CTRL.sub("", text)):
        if not part:
            continue
        props = "<w:b/>" if bold else ""
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            part, props = part[2:-2], "<w:b/>"
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            part, props = part[1:-1], '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:shd w:val="clear" w:color="auto" w:fill="F1F3F5"/>'
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            part, props = part[1:-1], props + "<w:i/>"
        rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def _para(text: str, style: str | None = None, indent: int = 0) -> str:
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + (f'<w:ind w:left="{indent}" w:hanging="260"/>' if indent else "")
    return f"<w:p>{f'<w:pPr>{ppr}</w:pPr>' if ppr else ''}{_runs(text)}</w:p>"


def _table(rows: list[list[str]]) -> str:
    cols = max(len(r) for r in rows)
    border = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="BFC5CC"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join(f'<w:gridCol w:w="{9600 // cols}"/>' for _ in range(cols))
    body = []
    for i, row in enumerate(rows):
        cells = []
        for j in range(cols):
            shade = '<w:shd w:val="clear" w:color="auto" w:fill="EEF1F4"/>' if i == 0 else ""
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{9600 // cols}" w:type="dxa"/>{shade}</w:tcPr>'
                         f'<w:p>{_runs(row[j] if j < len(row) else "", bold=i == 0)}</w:p></w:tc>')
        body.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return (f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{border}</w:tblBorders></w:tblPr>'
            f"<w:tblGrid>{grid}</w:tblGrid>{''.join(body)}</w:tbl><w:p/>")


def markdown_to_docx(markdown: str) -> bytes:
    """Markdown đơn giản (đề mục, đoạn, gạch đầu dòng, bảng, đậm/nghiêng/mã) thành tệp .docx mở được bằng Word."""
    blocks, para, table = [], [], []
    first_heading = True

    def flush() -> None:
        if para:
            blocks.append(_para(" ".join(para)))
            para.clear()
        if table:
            blocks.append(_table(table))
            table.clear()

    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if line.startswith("|") and line.endswith("|"):
            if para:
                blocks.append(_para(" ".join(para))); para.clear()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                table.append(cells)
            continue
        if table:
            blocks.append(_table(table)); table.clear()
        heading = _HEADING.match(line)
        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        number = re.match(r"^(\d+[.)])\s+(.+)$", line)
        if not line or re.fullmatch(r"-{3,}|\*{3,}", line):
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            style = "Title" if level == 1 and first_heading else f"Heading{min(3, max(1, level - 1))}"
            first_heading = False
            blocks.append(_para(heading.group(2), style))
        elif bullet:
            flush()
            blocks.append(_para("•\t" + bullet.group(1), indent=520))
        elif number:
            flush()
            blocks.append(_para(f"{number.group(1)}\t{number.group(2)}", indent=520))
        else:
            para.append(line)
    flush()

    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}><w:body>{"".join(blocks)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
                'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')

    def style(sid: str, name: str, size: int, color: str = "1F2933", bold: bool = True, before: int = 240) -> str:
        return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
                f'<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="{before}" w:after="120"/></w:pPr>'
                f'<w:rPr>{"<w:b/>" if bold else ""}<w:color w:val="{color}"/><w:sz w:val="{size}"/></w:rPr></w:style>')

    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {ns}><w:docDefaults><w:rPrDefault><w:rPr>'
              '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:lang w:val="vi-VN"/>'
              '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="288" w:lineRule="auto"/></w:pPr>'
              '</w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
              '<w:qFormat/></w:style>' + style("Title", "Title", 40, "0E5E6F", before=0) + style("Heading1", "heading 1", 30, "0E5E6F")
              + style("Heading2", "heading 2", 26) + style("Heading3", "heading 3", 23) + "</w:styles>")
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/styles.xml", styles)
    return buf.getvalue()


# ---------------- Kiểm tra cả kho tài liệu
def _vector(chunks) -> Counter:
    return Counter(t for t in _content_tokens(_doc_text(chunks)) if len(t) > 2)


def library_quality(sources: list[dict], chunks_by_source: dict[str, list], duplicate_at: float = 0.9) -> dict:
    """Từng tài liệu: điểm chất lượng và vấn đề; cả kho: các cặp tài liệu gần như trùng nhau."""
    names = {s["source_id"]: s["source_name"] for s in sources}
    vectors = {sid: _vector(ch) for sid, ch in chunks_by_source.items() if ch}
    norms = {sid: (sum(v * v for v in vec.values()) ** 0.5) or 1.0 for sid, vec in vectors.items()}
    sids = sorted(vectors)
    pairs = []
    for i, a in enumerate(sids):
        for b in sids[i + 1:]:
            score = sum(vectors[a][t] * vectors[b][t] for t in set(vectors[a]) & set(vectors[b])) / (norms[a] * norms[b])
            if score >= duplicate_at:
                pairs.append({"a": names.get(a, a), "b": names.get(b, b), "a_id": a, "b_id": b, "score": round(score, 3)})
    twin = {}
    for p in pairs:
        twin.setdefault(p["a_id"], []).append(p["b"]); twin.setdefault(p["b_id"], []).append(p["a"])
    docs = []
    for s in sources:
        sid, chunks = s["source_id"], chunks_by_source.get(s["source_id"]) or []
        if not chunks:
            docs.append({"source_id": sid, "source_name": s["source_name"], "score": 0, "words": 0, "chunks": 0,
                         "issues": [{"level": "high", "code": "no_text", "message": "Không trích được chữ nào; có thể là bản scan (ảnh) hoặc tệp hỏng. Hệ thống chưa nhận dạng chữ trong ảnh."}]})
            continue
        # shortcut: so từng đoạn với mọi đoạn khác (bình phương số đoạn); kho vài nghìn đoạn thì cần chỉ mục MinHash
        others = [c for oid, och in chunks_by_source.items() if oid != sid for c in och]
        q = quality_report(chunks, others)
        if sid in twin:
            q["issues"].insert(0, {"level": "high", "code": "duplicate_doc", "message": "Gần như trùng hoàn toàn với: " + ", ".join(sorted(twin[sid]))})
            q["score"] = max(0, q["score"] - 35)
        docs.append({"source_id": sid, "source_name": s["source_name"], "score": q["score"], "words": q["words"],
                     "chunks": q["chunks"], "issues": q["issues"]})
    docs.sort(key=lambda d: (d["score"], d["source_name"]))
    return {"documents": len(docs), "with_issues": sum(bool(d["issues"]) for d in docs), "duplicates": pairs, "docs": docs}


# ---------------- Chủ đề được hỏi nhiều
_ASK_STOP = {_fold(w) for w in """gì nào sao làm thế bao nhiêu ai đâu hãy giúp tôi bạn ở là những cách có được không hỏi nói biết
vậy thì khi như cái các và của cho với trong về từ theo nếu này đó kia một mình chúng ta em anh chị xin vui lòng ra sử dụng dùng
phải cần nên bị đã sẽ đang thể nhiều rất mỗi mọi nào cũng
the what how why when which who is are do does a an of to in for on and or""".split()}


def bigram_vocabulary(texts) -> Counter:
    """Tần suất cặp chữ liền nhau trong kho tài liệu; dùng để tách từ ghép tiếng Việt (thanh toán, hoàn tiền)."""
    vocab: Counter = Counter()
    for text in texts:
        folded = re.findall(r"\w+", _fold(text))
        vocab.update(f"{a} {b}" for a, b in zip(folded, folded[1:]))
    return vocab


def _query_terms(query: str, display: dict, vocabulary: Counter | None = None) -> set[str]:
    words = re.findall(r"\w+", query)
    keep = [(w, _fold(w)) for w in words]
    candidates = []
    for i in range(len(keep) - 1):
        (w1, f1), (w2, f2) = keep[i], keep[i + 1]
        if f1 in _ASK_STOP or f2 in _ASK_STOP or f1.isdigit() or f2.isdigit() or len(f1) < 2 or len(f2) < 2:
            continue
        candidates.append((i, f"{f1} {f2}", f"{w1.lower()} {w2.lower()}"))
    if vocabulary is not None:  # chọn cặp không chồng nhau, ưu tiên cặp gặp nhiều trong tài liệu ("trình thanh" bị loại)
        candidates.sort(key=lambda c: -vocabulary[c[1]])
    used, terms = set(), set()
    for i, key, shown in candidates:
        if vocabulary is not None and (vocabulary[key] < 2 or i in used or i + 1 in used):
            continue
        used.update((i, i + 1))
        terms.add(key)
        display.setdefault(key, shown)
    for w, f in keep:  # từ kỹ thuật một chữ: viết tắt (API, OTP) hoặc từ tiếng Anh dài
        if (w.isupper() and 2 < len(w) <= 8) or (w == f and len(w) >= 6 and not w.isdigit()):
            terms.add(f)
            display.setdefault(f, w if w.isupper() else w.lower())
    return terms


def _when(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def question_topics(runs: list[dict], vocabulary: Counter | None = None, now: datetime | None = None, days: int = 7, limit: int = 8) -> dict:
    """Cụm từ xuất hiện trong câu hỏi 7 ngày qua so với 7 ngày trước đó, và số lượt hỏi mỗi ngày trong 14 ngày."""
    now = now or datetime.now(timezone.utc)
    current, previous, daily, display = Counter(), Counter(), Counter(), {}
    for run in runs:
        when = _when(run.get("created_at"))
        if not when:
            continue
        age = (now - when).total_seconds() / 86400
        if age < 0 or age >= 2 * days:
            continue
        terms = _query_terms(run.get("query") or "", display, vocabulary)
        (current if age < days else previous).update(terms)
        daily[when.date().isoformat()] += 1
    # cụm hai chữ đã chứa từ đơn thì bỏ từ đơn trùng
    top = [k for k, _ in current.most_common(limit * 3)]
    top = [k for k in top if " " in k or not any(k in other.split() for other in top if " " in other)][:limit]
    start = (now - timedelta(days=2 * days - 1)).date()
    return {
        "topics": [{"term": display[k], "count": current[k], "previous": previous[k]} for k in top if current[k] > 0],
        "daily": [{"date": (start + timedelta(days=i)).isoformat(), "runs": daily[(start + timedelta(days=i)).isoformat()]} for i in range(2 * days)],
        "window_days": days,
    }


STATUSES = ("COMPLETE", "PARTIAL", "NO_EVIDENCE", "FAILED")


def _pct(sorted_values: list[int], q: float) -> int | None:
    if not sorted_values:
        return None
    # phân vị kiểu nearest-rank: phần tử thứ ceil(q*n), luôn là một giá trị đo thật
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def usage_patterns(runs: list[dict], now: datetime | None = None, days: int = 14) -> dict:
    """Số liệu cho các biểu đồ Tổng quan, tính từ lượt chạy đã lưu (không ước lượng):
    lượt mỗi ngày tách theo kết quả, giờ cao điểm (thứ x giờ, theo giờ máy chủ), và theo từng cách trả lời:
    số lượt, số lượt đủ bằng chứng, thời gian và token trung bình (chỉ tính lượt có số đo)."""
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=days - 1)).date()
    daily: dict[str, Counter] = {}
    heat = [[0] * 24 for _ in range(7)]
    cond: dict[str, dict] = {}
    latencies: list[int] = []
    for run in runs:
        status = str(run.get("status") or "?").upper()
        when = _when(run.get("created_at"))
        if when:
            local = when.astimezone()
            heat[local.weekday()][local.hour] += 1
            if when.date() >= start:
                daily.setdefault(when.date().isoformat(), Counter())[status if status in STATUSES else "OTHER"] += 1
        c = cond.setdefault(str(run.get("condition") or "?"), {"runs": 0, "complete": 0, "lat": [], "tok": []})
        c["runs"] += 1
        c["complete"] += status == "COMPLETE"
        m = run.get("metrics") or {}
        if m.get("latency_ms"):
            c["lat"].append(int(m["latency_ms"]))
            latencies.append(int(m["latency_ms"]))
        if m.get("input_tokens") is not None:
            c["tok"].append(int(m.get("input_tokens") or 0) + int(m.get("output_tokens") or 0))
    latencies.sort()
    return {
        "daily_status": [{"date": d, **{s: daily.get(d, Counter())[s] for s in (*STATUSES, "OTHER")}}
                         for d in ((start + timedelta(days=i)).isoformat() for i in range(days))],
        "heatmap": heat,
        "by_condition": [{"condition": k, "runs": v["runs"], "complete": v["complete"],
                          "latency_avg_ms": round(sum(v["lat"]) / len(v["lat"])) if v["lat"] else None,
                          "tokens_avg": round(sum(v["tok"]) / len(v["tok"])) if v["tok"] else None}
                         for k, v in sorted(cond.items(), key=lambda kv: -kv[1]["runs"])],
        "latency_p50_ms": _pct(latencies, 0.5), "latency_p95_ms": _pct(latencies, 0.95),
    }
