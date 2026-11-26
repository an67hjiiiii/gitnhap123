"""Truy vết yêu cầu (Requirements Traceability).

Trích các yêu cầu có mã (FR-/NFR-/UC-...) từ tài liệu đặc tả, rồi với từng yêu cầu: chọn tác tử theo
chuyên môn, truy xuất bằng chứng riêng trong tài liệu thiết kế và để mô hình cục bộ kết luận có trích dẫn.
Không đi qua planner/bước kiểm tra kế hoạch của CAP1, nên luồng nghiên cứu A/B/C giữ nguyên.
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass

from app.core.citations import validate_citations
from app.core.types import SourceChunk
from app.research.decomposer import _contains_hint, detect_domains  # cùng bộ gợi ý với planner
from app.research.registry import active_pack, profile

STATUSES = ("COVERED", "PARTIAL", "MISSING")
MAX_REQUIREMENTS = 60
MAX_BODY_CHARS = 900

# Mã yêu cầu ở đầu dòng: tiêu đề Markdown, gạch đầu dòng hoặc ô đầu của dòng bảng.
_REQUIREMENT_LINE = re.compile(
    r"^(?:#{1,6}\s+|[-*+]\s+|\|\s*)?\*{0,2}((?:FR|NFR|UC|REQ|BR|SR|SEC)[-_]?\d{1,3}(?:\.\d{1,2})?)\*{0,2}"
    r"(?![\w-])\s*[:.\-–—|]*\s*(.*)$",
    re.IGNORECASE,
)


def _resolve_profile(agent_id: str) -> dict:
    agents = active_pack()["agents"]
    if agent_id in agents:
        return profile(agent_id)
    if agent_id in ("security", "database", "api_architecture") and "software" in agents:
        return profile("software")
    return profile(active_pack()["default_domain"])


@dataclass(frozen=True)
class Requirement:
    req_id: str
    title: str
    body: str
    domains: list[str]
    agent: str

    def to_dict(self) -> dict:
        return {**asdict(self), "agent_name": _resolve_profile(self.agent)["name"]}


def assign_agent(text: str) -> tuple[list[str], str]:
    """Chuyên môn nhận diện được và tác tử phụ trách theo bộ lĩnh vực đang dùng (Phần mềm: mặc định API/kiến trúc)."""
    domains = detect_domains(text) if text.strip() else []
    if not domains:
        return [], active_pack()["default_domain"]
    folded = text.casefold()
    hints = active_pack()["hints"]
    score = {d: sum(_contains_hint(folded, hint) for hint in hints[d]) for d in domains}
    return domains, max(domains, key=lambda d: (score[d], -domains.index(d)))


def _normalize_id(raw: str) -> str:
    rid = raw.upper().replace("_", "-")
    return re.sub(r"^([A-Z]+)(\d)", r"\1-\2", rid)


def extract_requirements(text: str) -> list[Requirement]:
    """Trích yêu cầu có mã; mỗi yêu cầu kéo dài tới mã kế tiếp hoặc tiêu đề kế tiếp. Mã trùng lấy lần đầu."""
    found: list[dict] = []
    seen: set[str] = set()
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _REQUIREMENT_LINE.match(line)
        if match:
            rid = _normalize_id(match.group(1))
            current = None
            if rid in seen:
                continue
            title = match.group(2)
            is_row = line.startswith("|")
            if is_row:
                title = " · ".join(cell.strip() for cell in title.split("|") if cell.strip())
            item = {"req_id": rid, "title": title.strip(" *"), "body": []}
            seen.add(rid)
            found.append(item)
            current = None if is_row else item  # một dòng bảng là trọn một yêu cầu
            continue
        if current is None:
            continue
        if line.startswith("#"):
            current = None
        elif line and not (line.startswith("|") and set(line) <= set("|-: ")):
            current["body"].append(line)
    requirements = []
    for item in found[:MAX_REQUIREMENTS]:
        body = "\n".join(item["body"])[:MAX_BODY_CHARS]
        domains, agent = assign_agent(f"{item['title']}\n{body}")
        requirements.append(Requirement(item["req_id"], item["title"], body, domains, agent))
    return requirements


_LIST_LINE = re.compile(r"^(?:[-*+•☐□]|\d{1,3}[.)]|[a-zđ][.)])\s+(.+)$", re.IGNORECASE)


def criteria_from_lines(lines: list[str]) -> list[Requirement]:
    """Mỗi dòng không rỗng là một tiêu chí, mã TC-01, TC-02...; bỏ dòng trùng; tác tử chọn theo bộ lĩnh vực đang dùng."""
    out: list[Requirement] = []
    seen: set[str] = set()
    for line in lines:
        text = " ".join(line.split())[:MAX_BODY_CHARS]
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        domains, agent = assign_agent(text)
        out.append(Requirement(f"TC-{len(out) + 1:02d}", text, "", domains, agent))
        if len(out) == MAX_REQUIREMENTS:
            break
    return out


def extract_checklist(text: str) -> list[Requirement]:
    """Danh mục trong tài liệu: dòng gạch đầu dòng hoặc đánh số (1. / 1) / a) / ☐) thành tiêu chí."""
    items = [m.group(1).strip(" *") for line in text.splitlines() if (m := _LIST_LINE.match(line.strip()))]
    return criteria_from_lines([i for i in items if len(i) >= 4])


def requirement_query(requirement: Requirement) -> str:
    return f"{requirement.title}\n{requirement.body}"[:700]


def _tokens(text: str) -> list[str]:
    words = re.findall(r"\w+", text.casefold())
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]  # cặp âm tiết: "hoàn tiền", "khóa api"


def bm25_rank(query: str, chunks: list[SourceChunk], k1: float = 1.2, b: float = 0.75) -> list[SourceChunk]:
    """BM25 trên các đoạn được chọn; điểm > 0 mới giữ, cao xuống thấp."""
    docs = [Counter(_tokens(c.text)) for c in chunks]
    if not docs:
        return []
    avg_len = sum(sum(d.values()) for d in docs) / len(docs) or 1.0
    df = Counter(t for d in docs for t in d)
    terms = set(_tokens(query))
    scored = []
    for chunk, doc in zip(chunks, docs):
        length = sum(doc.values())
        score = sum(
            math.log((len(docs) - df[t] + 0.5) / (df[t] + 0.5) + 1) * doc[t] * (k1 + 1)
            / (doc[t] + k1 * (1 - b + b * length / avg_len))
            for t in terms if doc.get(t)
        )
        if score > 0:
            scored.append(SourceChunk(**{**chunk.__dict__, "score": round(score, 4)}))
    return sorted(scored, key=lambda c: (-c.score, c.chunk_id))


def evidence_for(pipeline, query: str, chunks: list[SourceChunk], *, top_k: int, min_score: float,
                 source_ids: list[str]) -> list[SourceChunk]:
    """Bằng chứng cho một yêu cầu: BM25 trước, thiếu thì bù bằng truy xuất vector của pipeline.

    Chỉ dùng trong chức năng phân tích. Đo trên 12 câu có đáp án (bộ tài liệu thử): đoạn đúng vào top 4 ở
    12/12 câu với BM25, 6/12 với vector nomic (yếu với tiếng Việt). Luồng nghiên cứu A/B/C giữ truy xuất gốc.
    """
    picked = bm25_rank(query, chunks)[:top_k]
    if len(picked) < top_k:
        have = {c.chunk_id for c in picked}
        vector = pipeline._retrieve_candidates(query, chunks, top_k=top_k, min_score=min_score, source_ids=source_ids, fallback_trace={})
        picked += [c for c in vector if c.chunk_id not in have][: top_k - len(picked)]
    return picked


_ID_TOKEN = re.compile(r"\b[A-Z]{1,5}-\d+\b")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[str]:
    """Con số mục tiêu (300, 99.9, 500000000); bỏ mã yêu cầu như FR-04."""
    found = set()
    for raw in _NUMBER.findall(_ID_TOKEN.sub(" ", text)):
        value = raw.replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw) else raw.replace(",", ".")
        found.add(value.lstrip("0") or "0")
    return found


def _response_schema(evidence_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": list(STATUSES)},
            "citations": {"type": "array", "items": {"type": "string", "enum": list(dict.fromkeys(evidence_ids))}},
            "covered_points": {"type": "array", "items": {"type": "string"}},
            "missing_points": {"type": "array", "items": {"type": "string"}},
            "note": {"type": "string"},
        },
        "required": ["status", "citations", "covered_points", "missing_points", "note"],
        "additionalProperties": False,
    }


def _decode(text: str) -> dict:
    for candidate in (text, (re.search(r"\{.*\}", text, re.S) or [None])[0]):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _strings(value: object, limit: int = 8) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()][:limit] if isinstance(value, list) else []


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("đ", "d")


def missing_term_groups(text: str, groups: list[list[str]]) -> list[list[str]]:
    """Nhóm thuật ngữ không có cách nói nào xuất hiện trong văn bản (so khớp nguyên từ, bỏ dấu)."""
    folded = _fold(text)
    return [g for g in groups if not any(re.search(rf"(?<![a-z0-9]){re.escape(_fold(t))}(?![a-z0-9])", folded) for t in g)]


async def check_requirement(provider, requirement: Requirement, evidence: list[SourceChunk],
                            required_terms: list[list[str]] | None = None) -> dict:
    """Kết luận một yêu cầu đã được tài liệu thiết kế đáp ứng chưa. Kết luận là gợi ý; người dùng duyệt lại."""
    started = time.perf_counter()
    agent = _resolve_profile(requirement.agent)
    result = {
        "req_id": requirement.req_id,
        "agent": requirement.agent,
        "agent_name": agent["name"],
        "evidence": [{"chunk_id": c.chunk_id, "source_name": c.source_name, "score": round(float(c.score or 0), 4)} for c in evidence],
        "citations": [], "covered_points": [], "missing_points": [], "flags": [],
        "input_tokens": 0, "output_tokens": 0,
    }
    if not evidence:
        return {**result, "status": "MISSING", "note": "Không tìm thấy đoạn nào trong tài liệu thiết kế liên quan đến yêu cầu này.",
                "flags": ["no_evidence"], "latency_ms": int((time.perf_counter() - started) * 1000)}

    evidence_text = "\n\n".join(f"[{c.chunk_id}] ({c.source_name})\n{c.text}" for c in evidence)
    system = (
        f"TRACEABILITY_CHECKER. Role={agent['name']}. Scope={agent['scope']}. "
        "Decide whether the DESIGN EVIDENCE satisfies the REQUIREMENT, using only the supplied evidence. "
        "COVERED: the evidence explicitly addresses every key point. PARTIAL: only some key points. "
        "MISSING: the evidence does not address the requirement. Cite only supplied chunk IDs that support covered points. "
        "Return JSON only."
    )
    user = (
        f"REQUIREMENT {requirement.req_id}: {requirement.title}\n{requirement.body}\n\nDESIGN EVIDENCE:\n{evidence_text}\n\n"
        'Schema: {"status":"COVERED|PARTIAL|MISSING","citations":["chunk_id"],"covered_points":["..."],'
        '"missing_points":["..."],"note":"<một câu>"}\n'
        "NGÔN NGỮ: Viết covered_points, missing_points và note bằng tiếng Việt, ngắn gọn; giữ nguyên mã kỹ thuật."
    )
    structured = getattr(provider, "generate_structured", None)
    response = (
        await structured(system=system, user=user, response_schema=_response_schema([c.chunk_id for c in evidence]))
        if callable(structured) else await provider.generate(system=system, user=user)
    )
    obj = _decode(response.text)
    status = str(obj.get("status") or "").upper()
    flags: list[str] = []
    if status not in STATUSES:
        status, flags = "PARTIAL", ["invalid_model_output"]
    valid, invalid = validate_citations([str(x) for x in obj.get("citations") or []], evidence)
    if invalid:
        flags.append("invalid_citation_removed")
    missing_points = _strings(obj.get("missing_points"))
    if status == "COVERED" and not valid:
        status = "PARTIAL"  # kết luận "đáp ứng" phải có căn cứ
        flags.append("no_valid_citation")
    if status == "COVERED" and missing_points:
        status = "PARTIAL"  # còn điểm thiếu thì chưa thể "đáp ứng đầy đủ"
        flags.append("has_missing_points")
    targets = _numbers(f"{requirement.title}\n{requirement.body}")
    if status == "COVERED" and targets - _numbers(" ".join(c.text for c in evidence if c.chunk_id in valid)):
        status = "PARTIAL"  # yêu cầu định lượng: mọi con số mục tiêu phải có trong đoạn được trích
        flags.append("numbers_not_in_evidence")
    if status == "COVERED" and required_terms and missing_term_groups(" ".join(c.text for c in evidence if c.chunk_id in valid), required_terms):
        status = "PARTIAL"  # tiêu chí có thuật ngữ cốt lõi: đoạn được trích phải nhắc tới nó
        flags.append("terms_not_in_evidence")
    usage = getattr(response, "usage", None)
    return {
        **result,
        "status": status,
        "citations": valid,
        "covered_points": _strings(obj.get("covered_points")),
        "missing_points": missing_points,
        "note": str(obj.get("note") or "").strip()[:500],
        "flags": flags,
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
