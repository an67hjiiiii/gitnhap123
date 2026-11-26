"""Gói thiết kế kỹ thuật (Technical Design Package).

Từ một yêu cầu tính năng: tách ý chính, ba tác tử (CSDL, API, bảo mật) viết phần thiết kế của mình dựa trên
tài liệu tham chiếu, rồi kiểm tra ý chính đã được bao phủ chưa. Mỗi bước là một lời gọi riêng nên giao diện hiện
được tiến độ và đo token/thời gian theo từng tác tử. Không đi qua planner/bước kiểm tra kế hoạch của CAP1.
"""

from __future__ import annotations

import re
import time

from app.analysis.traceability import _decode, assign_agent
from app.core.citations import validate_citations
from app.core.types import SourceChunk
from app.research.registry import profile, use_pack

DOMAINS = ("database", "api_architecture", "security")
DOMAIN_LABEL = {"database": "database", "api_architecture": "API and integration", "security": "security and access control"}
# Từ gợi ý thêm vào câu truy xuất của từng tác tử: mỗi tác tử đọc phần tài liệu thuộc chuyên môn của mình.
DOMAIN_QUERY = {
    "database": "bảng cột khóa chỉ mục ràng buộc giao dịch lưu trữ dữ liệu",
    "api_architecture": "API endpoint request response mã lỗi tích hợp webhook",
    "security": "phân quyền xác thực bảo mật mã hóa nhật ký kiểm toán",
}
EVIDENCE_CHARS = 900
MAX_POINTS = 8
_STR = {"type": "string"}
_IDENT = re.compile(r"[^A-Za-z0-9_]")
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _citations_schema(evidence_ids: list[str]) -> dict:
    items = {"type": "string", "enum": list(dict.fromkeys(evidence_ids))} if evidence_ids else _STR
    return {"type": "array", "items": items}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


async def _call(provider, system: str, user: str, schema: dict, max_tokens: int) -> tuple[dict, dict]:
    structured = getattr(provider, "generate_structured", None)
    started = time.perf_counter()
    response = (
        await structured(system=system, user=user, response_schema=schema, max_output_tokens=max_tokens)
        if callable(structured) else await provider.generate(system=system, user=user)
    )
    usage = getattr(response, "usage", None)
    return _decode(response.text), {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def _text(value: object, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


# ---------------- Bước 1: ý chính của yêu cầu
async def key_points(provider, request: str) -> dict:
    schema = _obj({"points": _arr(_obj({"text": _STR, "domain": {"type": "string", "enum": list(DOMAINS)}}))})
    system = (
        "DESIGN_ANALYST. Split the feature request into 3-8 concrete, checkable design points that a technical design "
        "must satisfy. Assign each point to the most suitable domain: database, api_architecture or security. "
        "Do not add requirements that the request does not state or clearly imply. Return JSON only."
    )
    user = (f"FEATURE REQUEST:\n{request}\n\n"
            'Schema: {"points":[{"text":"...","domain":"database|api_architecture|security"}]}\n'
            "NGÔN NGỮ: Viết text bằng tiếng Việt, mỗi ý một câu ngắn.")
    obj, measured = await _call(provider, system, user, schema, 600)
    points: list[dict] = []
    for item in obj.get("points") or []:
        if isinstance(item, dict) and _text(item.get("text")) and item.get("domain") in DOMAINS and len(points) < MAX_POINTS:
            points.append({"id": f"P{len(points) + 1}", "text": _text(item["text"]), "domain": item["domain"]})
    flags = []
    if not points:  # mô hình không tách được: giữ nguyên yêu cầu làm một ý, nói rõ
        with use_pack("software"):
            fallback_domain = assign_agent(request)[1]
        points = [{"id": "P1", "text": _text(request), "domain": fallback_domain}]
        flags.append("fallback_single_point")
    return {"points": points, "flags": flags, **measured}


# ---------------- Bước 2: phân bổ ngữ cảnh và phần thiết kế của từng tác tử
def section_query(request: str, domain: str, points: list[dict]) -> str:
    own = [p["text"] for p in points if p.get("domain") == domain] or [p["text"] for p in points]
    return f"{request}\n" + "\n".join(own) + f"\n{DOMAIN_QUERY[domain]}"


def allocate_evidence(ranked: list[SourceChunk], top_k: int, avoid: set[str]) -> tuple[list[SourceChunk], int]:
    """Ưu tiên đoạn mà tác tử khác chưa dùng; đoạn liên quan nhất vẫn giữ dù trùng. Trả về (đoạn, số đoạn trùng)."""
    picked = [c for i, c in enumerate(ranked) if i == 0 or c.chunk_id not in avoid][:top_k]
    if len(picked) < top_k:
        have = {c.chunk_id for c in picked}
        picked += [c for c in ranked if c.chunk_id not in have][: top_k - len(picked)]
    return picked, sum(c.chunk_id in avoid for c in picked)


def _section_schema(domain: str, ids: list[str]) -> dict:
    cit = _citations_schema(ids)
    notes = _arr(_obj({"text": _STR, "citations": cit}))
    if domain == "database":
        column = _obj({"name": _STR, "type": _STR, "constraints": _STR})
        return _obj({
            "tables": _arr(_obj({"name": _STR, "purpose": _STR, "columns": _arr(column), "citations": cit})),
            "indexes": _arr(_obj({"table": _STR, "columns": _STR, "purpose": _STR})),
            "notes": notes,
        })
    if domain == "api_architecture":
        return _obj({
            "endpoints": _arr(_obj({"method": {"type": "string", "enum": list(_METHODS)}, "path": _STR, "purpose": _STR,
                                    "request": _arr(_STR), "responses": _arr(_STR), "citations": cit})),
            "notes": notes,
        })
    return _obj({
        "controls": _arr(_obj({"risk": _STR, "control": _STR, "citations": cit})),
        "permissions": _arr(_obj({"role": _STR, "actions": _arr(_STR)})),
        "notes": notes,
    })


_SCHEMA_HINT = {
    "database": '{"tables":[{"name":"snake_case","purpose":"...","columns":[{"name":"...","type":"BIGINT|VARCHAR(64)|...","constraints":"PK|NOT NULL|FK -> ..."}],"citations":["chunk_id"]}],"indexes":[{"table":"...","columns":"...","purpose":"..."}],"notes":[{"text":"...","citations":["chunk_id"]}]}',
    "api_architecture": '{"endpoints":[{"method":"POST","path":"/v1/...","purpose":"...","request":["field: type"],"responses":["201: ..."],"citations":["chunk_id"]}],"notes":[{"text":"...","citations":["chunk_id"]}]}',
    "security": '{"controls":[{"risk":"...","control":"...","citations":["chunk_id"]}],"permissions":[{"role":"...","actions":["..."]}],"notes":[{"text":"...","citations":["chunk_id"]}]}',
}


def _grounded(items: list, evidence: list[SourceChunk], limit: int, clean) -> list[dict]:
    out = []
    for item in items[:limit] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        data = clean(item)
        if not data:
            continue
        valid, _ = validate_citations([str(x) for x in item.get("citations") or []], evidence)
        out.append({**data, "citations": valid, "grounded": bool(valid)})
    return out


def _clean_section(domain: str, obj: dict, evidence: list[SourceChunk]) -> dict:
    notes = _grounded(obj.get("notes"), evidence, 6, lambda n: {"text": _text(n.get("text"), 400)} if _text(n.get("text")) else None)
    if domain == "database":
        def table(t):
            name = _IDENT.sub("_", _text(t.get("name"), 64)).strip("_").lower()
            cols = [{"name": _IDENT.sub("_", _text(c.get("name"), 64)).strip("_").lower(), "type": _text(c.get("type"), 40) or "TEXT",
                     "constraints": _text(c.get("constraints"), 120)}
                    for c in (t.get("columns") or [])[:16] if isinstance(c, dict) and _text(c.get("name"))]
            return {"name": name, "purpose": _text(t.get("purpose")), "columns": cols} if name and cols else None
        indexes = [{"table": _text(i.get("table"), 64), "columns": _text(i.get("columns"), 120), "purpose": _text(i.get("purpose"))}
                   for i in (obj.get("indexes") or [])[:8] if isinstance(i, dict) and _text(i.get("table"))]
        return {"tables": _grounded(obj.get("tables"), evidence, 6, table), "indexes": indexes, "notes": notes}
    if domain == "api_architecture":
        def endpoint(e):
            method, path = _text(e.get("method"), 8).upper(), _text(e.get("path"), 160)
            if method not in _METHODS or not path.startswith("/"):
                return None
            return {"method": method, "path": path, "purpose": _text(e.get("purpose")),
                    "request": [_text(x, 160) for x in (e.get("request") or [])[:12] if _text(x)],
                    "responses": [_text(x, 160) for x in (e.get("responses") or [])[:10] if _text(x)]}
        return {"endpoints": _grounded(obj.get("endpoints"), evidence, 8, endpoint), "notes": notes}
    controls = _grounded(obj.get("controls"), evidence, 8,
                         lambda c: {"risk": _text(c.get("risk")), "control": _text(c.get("control"), 400)} if _text(c.get("control")) else None)
    permissions = [{"role": _text(p.get("role"), 60), "actions": [_text(a, 120) for a in (p.get("actions") or [])[:10] if _text(a)]}
                   for p in (obj.get("permissions") or [])[:8] if isinstance(p, dict) and _text(p.get("role"))]
    return {"controls": controls, "permissions": permissions, "notes": notes}


async def design_section(provider, request: str, domain: str, points: list[dict], evidence: list[SourceChunk]) -> dict:
    with use_pack("software"):
        agent = profile(domain)
    own = [p for p in points if p.get("domain") == domain] or points
    system = (
        f"DESIGN_AGENT. Role={agent['name']}. Scope={agent['scope']}. Write the {DOMAIN_LABEL[domain]} part of a technical "
        "design for the feature request. Reuse names, values and rules from the REFERENCE EVIDENCE when they apply and cite "
        "the chunk IDs you used. You may propose new elements the feature needs; leave their citations empty. "
        "Stay inside your scope and keep it concise. Return JSON only."
    )
    block = "\n\n".join(f"[{c.chunk_id}] ({c.source_name})\n{c.text[:EVIDENCE_CHARS]}" for c in evidence) or "(không có)"
    user = (
        f"FEATURE REQUEST:\n{request}\n\nDESIGN POINTS FOR YOU:\n" + "\n".join(f"- {p['id']}: {p['text']}" for p in own)
        + f"\n\nREFERENCE EVIDENCE:\n{block}\n\nSchema: {_SCHEMA_HINT[domain]}\n"
        "NGÔN NGỮ: Viết purpose, notes, risk, control, actions bằng tiếng Việt; tên bảng, cột, đường dẫn API dùng tiếng Anh snake_case."
    )
    obj, measured = await _call(provider, system, user, _section_schema(domain, [c.chunk_id for c in evidence]), 1200)
    section = _clean_section(domain, obj, evidence)
    flags = [] if any(section[k] for k in section if k != "notes") or section["notes"] else ["empty_section"]
    extra = {"sql": to_sql(section)} if domain == "database" else {"openapi": to_openapi(section)} if domain == "api_architecture" else {}
    return {"domain": domain, "agent_name": agent["name"], "section": section, "flags": flags, **extra,
            "evidence": [{"chunk_id": c.chunk_id, "source_name": c.source_name} for c in evidence], **measured}


# ---------------- Bước 3: kiểm tra độ phủ ý chính
def section_text(domain: str, section: dict) -> str:
    lines: list[str] = []
    if domain == "database":
        for t in section.get("tables", []):
            lines.append(f"Bảng {t['name']}: {t['purpose']} | cột: " + ", ".join(f"{c['name']} {c['type']} {c['constraints']}".strip() for c in t["columns"]))
        lines += [f"Chỉ mục {i['table']}({i['columns']}): {i['purpose']}" for i in section.get("indexes", [])]
    elif domain == "api_architecture":
        for e in section.get("endpoints", []):
            lines.append(f"{e['method']} {e['path']}: {e['purpose']} | vào: {'; '.join(e['request'])} | ra: {'; '.join(e['responses'])}")
    else:
        lines += [f"Rủi ro: {c['risk']} -> Biện pháp: {c['control']}" for c in section.get("controls", [])]
        lines += [f"Vai trò {p['role']}: {', '.join(p['actions'])}" for p in section.get("permissions", [])]
    lines += [f"Ghi chú: {n['text']}" for n in section.get("notes", [])]
    return "\n".join(lines)


async def coverage(provider, request: str, points: list[dict], sections: dict[str, dict]) -> dict:
    ids = [p["id"] for p in points]
    schema = _obj({"coverage": _arr(_obj({
        "point_id": {"type": "string", "enum": ids}, "status": {"type": "string", "enum": ["COVERED", "PARTIAL", "MISSING"]},
        "sections": _arr({"type": "string", "enum": list(DOMAINS)}), "note": _STR}))})
    rendered = {d: section_text(d, sections.get(d) or {}) for d in DOMAINS}
    system = (
        "DESIGN_REVIEWER. For each design point decide whether the DESIGN SECTIONS address it: COVERED (fully), PARTIAL or "
        "MISSING. List the sections that address it. Judge only from the sections. Return JSON only."
    )
    user = (f"FEATURE REQUEST:\n{request}\n\nDESIGN POINTS:\n" + "\n".join(f"- {p['id']}: {p['text']}" for p in points)
            + "\n\nDESIGN SECTIONS:\n" + "\n\n".join(f"[{d}]\n{rendered[d] or '(trống)'}" for d in DOMAINS)
            + '\n\nSchema: {"coverage":[{"point_id":"P1","status":"COVERED|PARTIAL|MISSING","sections":["database"],"note":"..."}]}\n'
            "NGÔN NGỮ: note bằng tiếng Việt, một câu.")
    obj, measured = await _call(provider, system, user, schema, 700)
    judged = {str(c.get("point_id")): c for c in obj.get("coverage") or [] if isinstance(c, dict)}
    result = []
    for p in points:
        c = judged.get(p["id"])
        if c is None:
            result.append({"point_id": p["id"], "status": "MISSING", "sections": [], "note": "Mô hình không đánh giá ý này.", "flags": ["not_judged"]})
            continue
        status = str(c.get("status") or "").upper()
        status = status if status in ("COVERED", "PARTIAL", "MISSING") else "PARTIAL"
        cited = [s for s in dict.fromkeys(c.get("sections") or []) if s in DOMAINS and rendered[s]]
        flags = []
        if status == "COVERED" and not cited:
            status, flags = "PARTIAL", ["no_section"]  # "đã bao phủ" phải chỉ ra phần thiết kế cụ thể
        result.append({"point_id": p["id"], "status": status, "sections": cited, "note": _text(c.get("note"), 300), "flags": flags})
    return {"coverage": result, **measured}


# ---------------- Bản nháp xuất ra
def sql_constraints(text: str) -> str:
    """Ràng buộc viết tắt của mô hình ("PK", "FK -> orders(id)", "NOT NULL, UNIQUE") thành cú pháp SQL."""
    out = []
    for part in re.split(r",\s*(?![^()]*\))", text or ""):
        part = part.strip()
        if not part:
            continue
        upper = part.upper()
        if upper in ("PK", "PRIMARY", "PRIMARY KEY"):
            out.append("PRIMARY KEY")
        elif fk := re.match(r"(?:FK|FOREIGN KEY|REFERENCES)\s*(?:->|→|:|TO)?\s*([A-Za-z_][\w.]*)\s*(\(\s*\w+\s*\))?", part, re.I):
            out.append(f"REFERENCES {_IDENT.sub('_', fk.group(1)).lower()}{(fk.group(2) or '').replace(' ', '')}")
        elif upper in ("NN", "NOT NULL", "UNIQUE", "NULL") or upper.startswith(("CHECK", "DEFAULT", "UNIQUE")):
            out.append("NOT NULL" if upper == "NN" else part)
        # phần còn lại là mô tả tự do: bỏ khỏi DDL để câu lệnh chạy được
    return " ".join(out)


def to_sql(section: dict) -> str:
    """CREATE TABLE nháp từ phần thiết kế CSDL; tên đã được làm sạch, ràng buộc đổi về cú pháp SQL."""
    blocks = ["-- Bản nháp do tác tử CSDL đề xuất; cần kỹ sư kiểm tra trước khi dùng."]
    for t in section.get("tables", []):
        cols = ",\n".join(f"  {c['name']} {c['type'] or 'TEXT'}{(' ' + sql_constraints(c['constraints'])) if sql_constraints(c['constraints']) else ''}" for c in t["columns"])
        blocks.append(f"-- {t['purpose']}\nCREATE TABLE {t['name']} (\n{cols}\n);")
    for i in section.get("indexes", []):
        table = _IDENT.sub("_", i["table"]).strip("_").lower()
        cols = ", ".join(_IDENT.sub("_", c.strip()).strip("_").lower() for c in i["columns"].split(",") if c.strip())
        if table and cols:
            blocks.append(f"CREATE INDEX ix_{table}_{cols.replace(', ', '_')} ON {table} ({cols});  -- {i['purpose']}")
    return "\n\n".join(blocks) + "\n"


def _yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_openapi(section: dict, title: str = "Thiết kế API") -> str:
    """Khung OpenAPI 3.0 nháp (paths, phương thức, mô tả, mã phản hồi)."""
    lines = ["openapi: 3.0.3", "info:", f"  title: {_yaml_str(title)}", "  version: 0.1.0-draft", "paths:"]
    by_path: dict[str, list[dict]] = {}
    for e in section.get("endpoints", []):
        by_path.setdefault(e["path"], []).append(e)
    if not by_path:
        lines[-1] = "paths: {}"
    for path, endpoints in by_path.items():
        lines.append(f"  {_yaml_str(path)}:")
        for e in endpoints:
            lines += [f"    {e['method'].lower()}:", f"      summary: {_yaml_str(e['purpose'] or e['path'])}"]
            if e["request"]:
                lines.append(f"      description: {_yaml_str('Trường vào: ' + '; '.join(e['request']))}")
            lines.append("      responses:")
            codes = [(m.group(1), r[m.end():].lstrip(" :-–—") or r) for r in e["responses"] if (m := re.match(r"\s*(\d{3})\b", r))]
            for code, text in codes or [("200", "Thành công")]:
                lines += [f"        \"{code}\":", f"          description: {_yaml_str(text)}"]
    return "\n".join(lines) + "\n"
