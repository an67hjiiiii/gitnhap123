"""Verified Answer Integration for Experimental V2 Mode (B139.2 -> B139.2F -> B139.2F2).

Reconciles LLM output against deterministic Formula Selection, Decimal Unit Calculator,
Date-Interval & Structured Rule Evaluation, Robust Numerical Claim Reconciliation, and
Document Identifier awareness BEFORE buffered streaming emits.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
import re
from typing import Any

from app.core.answer_checks import IMG_MARK, _RULE_NEGATIVE, _RULE_POSITIVE, deduplicate_warnings
from app.core.approval_authority import (
    ApprovalResolution,
    is_approval_query,
    reconcile_approval_in_answer,
    resolve_approval_authority,
)
from app.core.formula_engine import (
    CalcStatus,
    execute_formula,
    select_formula,
)
from app.core.operand_grounding import identifier_numbers_in_text
from app.core.rule_evidence import RuleConditionEvidence, assess_rule_conditions
from app.core.types import SourceChunk

# True calculation cues (FIX-02 B139.2F: never match factual deadline lookups like "chậm nhất bao nhiêu giờ")
_LOOKUP_ONLY_RE = re.compile(
    r"(?:chậm nhất|tối đa|tối thiểu|trong vòng|kéo dài)\s+(?:là\s+)?bao\s+nhiêu\s+(?:giờ|ngày|tuần|tháng|năm)"
    r"|\bcó\s+bao\s+nhiêu\s+(?:điều|khoản|chương|loại|bước|mục|tài liệu|phân hệ)\b",
    re.I,
)
_TRUE_CALC_RE = re.compile(
    r"(?:bao nhiêu tiền|hết bao nhiêu|tổng\s+(?:tiền|chi phí|cước|lương|cộng|thanh toán|số tiền)|"
    r"tiền làm thêm|làm thêm(?:\s+tối thiểu)?|tăng ca|chiết khấu|thuế|trung bình|quy đổi\s+\d|"
    r"phạt\s+\d|tính\s+(?:lương|tổng|tỷ lệ|tiền|phí|thuế)|gồm phí|kèm\s+\d*\s*lần|"
    r"còn\s+bao\s+nhiêu\s+(?:giờ|ngày)\s+(?:nữa|đến\s+hạn))",
    re.I,
)
_RULE_INTENT_RE = re.compile(
    r"\b(?:đúng nội quy|đúng quy định|hợp lệ|đủ điều kiện|vi phạm luật|được hưởng|được duyệt|"
    r"compliant|eligible|within policy|satisf(?:y|ies)\s+(?:[^\n.]{0,25}\s+)?policy|comply\s+with)\b",
    re.I,
)


@dataclass
class VerifiedStructuredResult:
    """Single authoritative structured representation driving factual conclusions & deterministic section rendering."""
    intent: str
    overall_verdict: str
    facts: list[str] = field(default_factory=list)
    applicable_conditions: list[str] = field(default_factory=list)
    condition_verdicts: list[dict[str, Any]] = field(default_factory=list)
    calculation_steps: list[str] = field(default_factory=list)
    approval_authority: dict[str, Any] | None = None
    unknown_conditions: list[str] = field(default_factory=list)
    evidence_references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
_NUM_EXTRACT = re.compile(
    r"\b\d{1,3}(?:\.\d{3})+(?:,\d+)?|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?|\b\d+(?:[.,]\d+)?\b"
)
# Monetary token matcher handling both VN ('310.478.564,31 đồng', '42 triệu VND') & EN ('1,250,000.50 USD', '$1,250.50')
_MONEY_SPAN_RE = re.compile(
    r"(?P<pre_cur>\$\s*)?"
    r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
    r"\*{0,2}\s*(?P<scale>tỷ|triệu|nghìn|ngàn|million|billion|k)?\s*"
    r"(?P<post_cur>VND|VNĐ|đồng|đ|USD|\$)?",
    re.I,
)
_SCALE_FACTOR = {
    "tỷ": Decimal("1000000000"),
    "billion": Decimal("1000000000"),
    "triệu": Decimal("1000000"),
    "million": Decimal("1000000"),
    "nghìn": Decimal("1000"),
    "ngàn": Decimal("1000"),
    "k": Decimal("1000"),
}
_TOTAL_CUE_RE = re.compile(
    r"(?:=|\b(?:tổng(?:\s+(?:tiền|chi phí|cước|lương|cộng|thanh toán|số tiền))?|"
    r"thành\s+tiền|tạm\s+tính|cần\s+thanh\s+toán|làm\s+thêm(?:\s+tối\s+thiểu)?|"
    r"phí\s+triển\s+khai|giá\s+trị\s+sau\s+chiết\s+khấu|"
    r"grand\s+total|total(?:\s+(?:cost|amount|fee|pay|salary))?)\b)",
    re.I,
)
_ASSERTED_TOTAL_LINE_RE = re.compile(
    r"^\s*(?:[-*•]|\d+[.)])?\s*\**(?:Tổng(?:\s+(?:tiền|chi phí|cước|lương|cộng|thanh toán|cộng năm đầu))?|Tiền làm thêm|Ngày thường|Ngày lễ|Total)\b[^\n]*(?:\d{1,3}(?:[.,]\d{3})+|\$\s*\d)",
    re.I,
)
_COUNT_OR_UNIT_AFTER_RE = re.compile(
    r"^\s*\*{0,2}\s*(?:sinh viên|nhân viên|tài khoản|người|khách|users?|seats?|students?|ngày|giờ|tuần|tháng|năm|%)\b",
    re.I,
)
_INLINE_CIT_RE = re.compile(r"\[?(src_[0-9a-f]+_c\d{4}|[A-Za-z0-9_]+_c\d{4})\]?", re.I)


def _needs_calculation(query: str, formula_kwargs: dict[str, Any]) -> bool:
    if formula_kwargs:
        return True
    q = query or ""
    # When image OCR/case text is attached, inspect the user's question before IMG_MARK so quoted
    # contract penalty numbers (e.g. "phạt 30%") do not misclassify legal compliance reviews as math.
    q_intent = q.split(IMG_MARK, 1)[0].strip() if IMG_MARK in q else q
    if _TRUE_CALC_RE.search(q_intent):
        return True
    if IMG_MARK in q and re.search(
        r"\b(?:vi phạm(?:\s+luật)?|hợp\s+lệ|rủi\s+ro|risks?|compliant|legal)\b",
        q_intent,
        re.I,
    ) and not re.search(r"(?:bao\s+nhiêu|tính\b|total|cost|price|chi\s+phí|tổng\s+tiền|tổng\s+cộng)", q_intent, re.I):
        return False
    if _LOOKUP_ONLY_RE.search(q_intent):
        return False
    if re.search(r"\b(?:total cost|calculate|chi phí|giá bao nhiêu|bao nhiêu tiền)\b", q_intent, re.I):
        return True
    return False if IMG_MARK in q else bool(_TRUE_CALC_RE.search(q))


def _parse_any_num(tok: str) -> Decimal | None:
    t = (tok or "").strip()
    if not t:
        return None
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return None


def _canonical_dec_str(d: Decimal) -> str:
    """Match answer_checks._norm cleanly (e.g. Decimal('36000000.0') -> '36000000')."""
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f").rstrip("0").rstrip(".")


def _split_sentences_preserve_numbers(line: str) -> list[str]:
    """Split line on sentence boundaries without breaking on dots inside '4.000' or '310.478.564,31'."""
    if not line.strip():
        return [line]
    return re.split(r"(?<=[.!?])\s+(?!\d)", line)


def _extract_claim_values(segment: str) -> list[Decimal]:
    """Extract asserted monetary claim numbers from a sentence/row that follows a total/equals cue."""
    out: list[Decimal] = []
    # Find earliest total-claim cue position
    m_cue = _TOTAL_CUE_RE.search(segment)
    if not m_cue:
        return out
    search_from = m_cue.start()
    cleaned = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", " ", segment)
    cleaned = _INLINE_CIT_RE.sub(" ", cleaned)
    for m in _MONEY_SPAN_RE.finditer(cleaned):
        if m.start() < search_from:
            continue
        after = cleaned[m.end():m.end() + 28]
        has_money_marker = bool(m.group("pre_cur") or m.group("post_cur") or m.group("scale"))
        if not has_money_marker and _COUNT_OR_UNIT_AFTER_RE.match(after):
            continue
        val = _parse_any_num(m.group("num"))
        if val is None:
            continue
        sc = (m.group("scale") or "").strip().casefold()
        if sc in _SCALE_FACTOR:
            val = val * _SCALE_FACTOR[sc]
        if abs(val) >= Decimal("1000") or has_money_marker or "=" in segment[search_from:m.start()]:
            out.append(val)
    return out


def _llm_contains_number(answer: str, target: Decimal) -> bool:
    for m in _NUM_EXTRACT.finditer(answer or ""):
        v = _parse_any_num(m.group(0))
        if v is not None and abs(v - target) <= Decimal("1"):
            return True
    return False


def _llm_has_contradicting_total(answer: str, expected: Decimal) -> bool:
    seen_totals: set[Decimal] = set()
    for ln in (answer or "").splitlines():
        segs = [ln] if "|" in ln else _split_sentences_preserve_numbers(ln)
        for seg in segs:
            for v in _extract_claim_values(seg):
                seen_totals.add(v)
                if abs(v - expected) > Decimal("5"):
                    return True
    return len(seen_totals) > 1


def _cleanup_orphaned_tables_and_tail(text: str) -> str:
    """Remove Markdown table headers left with 0 body rows, orphaned empty label headers, and dangling connectors."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if "|" in ln and i + 1 < len(lines) and re.fullmatch(r"[\s|:\-]+", lines[i + 1].strip()) and "-" in lines[i + 1]:
            # Check if any non-empty body row follows the separator
            j = i + 2
            has_body = False
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                has_body = True
                j += 1
            if not has_body:
                # Also drop a preceding heading introducing the empty comparison table if immediately adjacent
                if out and out[-1].lstrip().startswith("#"):
                    out.pop()
                i = i + 2
                continue
        out.append(ln)
        i += 1
    # Drop numbered/bold label lines ending in ':' and markdown headings left with no child content
    for _pass in range(2):
        pruned: list[str] = []
        n = len(out)
        for idx, ln in enumerate(out):
            s = ln.strip()
            is_empty_label = bool(re.match(r"^(?:\d+[.)]\s+)?\*{2}[^*\n]+\*{2}\s*:\s*$", s))
            is_heading = s.startswith("#")
            if is_empty_label or is_heading:
                nxt = next((out[k].strip() for k in range(idx + 1, n) if out[k].strip()), "")
                if not nxt or nxt.startswith(("#", ">")) or re.match(r"^\d+[.)]\s+\*{2}", nxt):
                    continue
            pruned.append(ln)
        out = pruned
    cleaned = "\n".join(out)
    cleaned = re.sub(r"(?im)^[^\n]*(?:\bvì|\bbởi vì|\bnhư sau)\s*:\s*$", "", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _strip_wrong_total_sentences(answer: str, expected: Decimal) -> tuple[str, list[str]]:
    """Remove sentences/bullets/table rows asserting a conflicting monetary total while preserving dates/conditions/citations."""
    kept_lines: list[str] = []
    rescued_cits: list[str] = []
    for ln in (answer or "").splitlines():
        if "|" in ln:
            # Table row: check whole row as a unit
            claims = _extract_claim_values(ln)
            if claims and any(abs(v - expected) > Decimal("5") for v in claims):
                rescued_cits.extend(_INLINE_CIT_RE.findall(ln))
                continue
            kept_lines.append(ln)
            continue

        segs = _split_sentences_preserve_numbers(ln)
        kept_segs: list[str] = []
        for s in segs:
            claims = _extract_claim_values(s)
            if claims and any(abs(v - expected) > Decimal("5") for v in claims):
                rescued_cits.extend(_INLINE_CIT_RE.findall(s))
                continue
            kept_segs.append(s)
        joined = " ".join(kept_segs).strip()
        if joined:
            kept_lines.append(joined)
    return _cleanup_orphaned_tables_and_tail("\n".join(kept_lines)), list(dict.fromkeys(rescued_cits))


_SPECULATIVE_ARITH_RE = re.compile(r"\d[\d.,]*%?\s*(?:[*×÷]|\s/\s)\s*(?:\([^)\n]+\)|\d[\d.,]*)|\[\[\s*=")


def _retract_speculative_totals(answer: str) -> str:
    """When calculation cannot be verified (MISSING_OPERAND/CONFLICT/etc.), remove speculative computed totals & empty tables."""
    kept: list[str] = []
    for ln in (answer or "").splitlines():
        if "|" in ln and re.search(r"(?:VND|VNĐ|đồng|\$|USD|=|\d{1,3}(?:[.,]\d{3})+)", ln, re.I) and not re.fullmatch(r"[\s|:\-]+", ln.strip()):
            # Strip table rows that assert calculated totals; keep header temporarily for cleanup pass
            if _extract_claim_values(ln) or any(abs(v) >= Decimal("1000") for m in _MONEY_SPAN_RE.finditer(ln) if (v := _parse_any_num(m.group("num"))) is not None and (m.group("post_cur") or m.group("pre_cur"))):
                continue
        if _ASSERTED_TOTAL_LINE_RE.match(ln):
            continue
        if _SPECULATIVE_ARITH_RE.search(ln) and "chưa" not in ln.casefold():
            continue
        claims = _extract_claim_values(ln)
        if claims and any(abs(v) >= Decimal("1000") for v in claims) and "chưa" not in ln.casefold():
            continue
        kept.append(ln)
    return _cleanup_orphaned_tables_and_tail("\n".join(kept))


def _parse_dmy(s: str) -> date | None:
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", s)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _working_days_between(d_start: date, d_end: date) -> int:
    """Count exclusive weekday business days between submit date and start date (`d_start < d <= d_end`, Mon-Fri)."""
    if d_end <= d_start:
        return 0
    cur = d_start + timedelta(days=1)
    cnt = 0
    while cur <= d_end:
        if cur.weekday() < 5:
            cnt += 1
        cur += timedelta(days=1)
    return cnt


def _assess_rule_case(
    query: str,
    chunks: list[SourceChunk],
    allowed_source_ids: set[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Evaluate structured conditions dynamically against case input & authorized chunks without company hardcoding."""
    case_text = query.split(IMG_MARK, 1)[1] if IMG_MARK in query else query
    auth_chunks = [c for c in chunks if allowed_source_ids is None or c.source_id in allowed_source_ids]
    ev_text = "\n".join(c.text for c in auth_chunks)

    conditions: list[RuleConditionEvidence] = []
    rendered_notes: list[dict[str, str]] = []

    m_sub = re.search(r"(?:ngày\s+(?:gửi|nộp|đăng ký)\s*(?:đơn|phiếu)?|submitted(?:\s+on)?)\s*:[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{4})", case_text, re.I)
    m_rng = re.search(r"(?:từ|trip\s*:)\s*[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{4})\s*(?:đến|to|-)\s*[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{4})", case_text, re.I)
    d_sub = _parse_dmy(m_sub.group(1)) if m_sub else None
    d_leave_start = _parse_dmy(m_rng.group(1)) if m_rng else None
    d_leave_end = _parse_dmy(m_rng.group(2)) if m_rng else None

    def _find_rule_chunk_id(pat: re.Pattern[str]) -> str:
        for ch in auth_chunks:
            if pat.search(ch.text or ""):
                return ch.chunk_id
        return ""

    # 1. Advance notice threshold across all loaded rule chunks (strictest binding requirement wins)
    _notice_pat = re.compile(
        r"(?:(?:gửi|nộp|báo)\s+[^\n.;]{1,35}?|submitted)[^\n.;]{0,70}?(?:ít nhất|tối thiểu|at least)\s*(\d+)\s*(ngày làm việc|working days?|ngày|days?)",
        re.I,
    )
    req_matches = list(_notice_pat.finditer(ev_text))
    req_days = [int(m.group(1)) for m in req_matches]
    req_notice = max(req_days) if req_days else None
    requires_workdays = any("làm việc" in m.group(2).casefold() or "working" in m.group(2).casefold() for m in req_matches)
    notice_cid = _find_rule_chunk_id(_notice_pat) if req_matches else ""
    if d_sub and d_leave_start and req_notice is not None:
        cal_days = (d_leave_start - d_sub).days
        work_days = _working_days_between(d_sub, d_leave_start)
        notice_met = (work_days >= req_notice and cal_days >= req_notice) if requires_workdays else (cal_days >= req_notice)
        verdict = "MET" if notice_met else "NOT_MET"
        conditions.append(RuleConditionEvidence(
            condition_id="notice_period",
            description=f"Gửi đơn trước ít nhất {req_notice:02d} {'ngày làm việc' if requires_workdays else 'ngày'}",
            kind="mandatory",
            verdict=verdict,
            chunk_id=notice_cid,
            case_fact=f"Từ {d_sub.strftime('%d/%m/%Y')} đến {d_leave_start.strftime('%d/%m/%Y')}: {cal_days} ngày lịch / {work_days} ngày làm việc",
        ))
        cite_part = f" [{notice_cid}]" if notice_cid else ""
        if not notice_met:
            rendered_notes.append({
                "id": "notice_period",
                "status": "NOT_MET",
                "bullet": (
                    f"- **Thời hạn báo trước (`NOT_MET`):** Từ {d_sub.strftime('%d/%m/%Y')} đến {d_leave_start.strftime('%d/%m/%Y')} "
                    f"chỉ có **{cal_days} ngày lịch** (**{work_days} ngày làm việc** không tính cuối tuần), "
                    f"không đạt yêu cầu tối thiểu **{req_notice:02d} {'ngày làm việc' if requires_workdays else 'ngày'}**.{cite_part}"
                ),
            })

    # 2. Seasonal / peak restriction
    leave_days: int | None = None
    _peak_pat = re.compile(
        r"(?:(?:mùa|giai đoạn)\s+cao\s+điểm[^\n.;]*?\(([^)]+)\)[^\n.;]*?quá\s*(\d+)\s*ngày(?:\s+liên\s+tiếp)?|"
        r"above\s*(\d+)\s*days?[^\n.;]*?(?:peak\s+month\s*(\d{1,2})))",
        re.I,
    )
    if d_leave_start and d_leave_end:
        m_leave_len = re.search(r"\((\d+)\s*(?:ngày(?:\s+làm\s+việc)?|working\s+days?|days?)\)", case_text, re.I)
        leave_days = int(m_leave_len.group(1)) if m_leave_len else ((d_leave_end - d_leave_start).days + 1)
        m_peak = _peak_pat.search(ev_text)
        if m_peak:
            peak_cid = _find_rule_chunk_id(_peak_pat)
            leave_month = d_leave_start.month
            if m_peak.group(1) and m_peak.group(2):
                peak_spec, peak_max = m_peak.group(1).casefold(), int(m_peak.group(2))
                month_in_peak = f"tháng {leave_month}" in peak_spec
                if not month_in_peak:
                    for mr in re.finditer(r"tháng\s*(\d+)\s*đến\s*tháng\s*(\d+)", peak_spec):
                        if int(mr.group(1)) <= leave_month <= int(mr.group(2)):
                            month_in_peak = True
                            break
            else:
                peak_max = int(m_peak.group(3))
                month_in_peak = int(m_peak.group(4)) == leave_month
            if month_in_peak and leave_days > peak_max:
                cite_part = f" [{peak_cid}]" if peak_cid else ""
                conditions.append(RuleConditionEvidence(
                    condition_id="peak_season",
                    description=f"Mùa cao điểm (tháng {leave_month}) hạn chế nghỉ quá {peak_max:02d} ngày liên tiếp",
                    kind="mandatory",
                    verdict="NOT_MET",
                    chunk_id=peak_cid,
                    case_fact=f"Xin nghỉ {leave_days} ngày trong tháng {leave_month}",
                ))
                rendered_notes.append({
                    "id": "peak_season",
                    "status": "NOT_MET",
                    "bullet": (
                        f"- **Mùa cao điểm (`NOT_MET`):** Tháng {leave_month} thuộc mùa cao điểm hạn chế nghỉ quá "
                        f"**{peak_max:02d} ngày liên tiếp** (đơn xin {leave_days} ngày).{cite_part}"
                    ),
                })

        # 3. Multi-level approval rule when duration meets threshold
        _appr_pat = re.compile(r"(?:nghỉ\s+|mua\s+sắm\s+)?từ\s*(\d+)\s*ngày(?:\s+liên\s+tiếp)?[^\n.]*?phải\s+được\s+([^.\n]+?)\s+phê\s+duyệt", re.I)
        m_appr = _appr_pat.search(ev_text)
        if m_appr and leave_days >= int(m_appr.group(1)):
            appr_cid = _find_rule_chunk_id(_appr_pat)
            approvers = m_appr.group(2).strip()
            has_approval_fact = bool(re.search(r"(?:đã\s+phê\s+duyệt|đã\s+duyệt|xác\s+nhận\s+duyệt)", case_text, re.I))
            verdict_ap = "MET" if has_approval_fact else "UNKNOWN"
            conditions.append(RuleConditionEvidence(
                condition_id="multi_level_approval",
                description=f"Nghỉ từ {m_appr.group(1)} ngày cần {approvers} phê duyệt",
                kind="approval",
                chunk_id=appr_cid,
                approval_roles=[r.strip() for r in re.split(r"\bvà\b|,", approvers) if r.strip()],
                verdict=verdict_ap,
            ))
            if not has_approval_fact:
                cite_part = f" [{appr_cid}]" if appr_cid else ""
                rendered_notes.append({
                    "id": "multi_level_approval",
                    "status": "UNKNOWN",
                    "bullet": (
                        f"- **Phê duyệt bắt buộc (`UNKNOWN`):** Từ {m_appr.group(1)} ngày liên tiếp cần "
                        f"**{approvers}** phê duyệt (chưa có xác nhận phê duyệt trong đơn).{cite_part}"
                    ),
                })

    # 4. Mandatory handoff / prerequisite field explicitly marked absent ("chưa có", "không có")
    _handoff_pat = re.compile(
        r"(?:(?:phải|cần|bắt\s+buộc)[^\n.;]{0,40}?(?:bàn\s+giao|kế\s+hoạch\s+rollback|người\s+trực\s+thay)|must\s+include\s+[^\n.;]*handoff)",
        re.I,
    )
    handoff_required = bool(_handoff_pat.search(ev_text))
    handoff_missing = bool(re.search(r"(?:bàn\s+giao|handoff|rollback)[^\n:]*:\s*(?:chưa\s+có|không\s+có|chưa|trống|none|missing)\b", case_text, re.I))
    if handoff_required and handoff_missing:
        handoff_cid = _find_rule_chunk_id(_handoff_pat)
        cite_part = f" [{handoff_cid}]" if handoff_cid else ""
        conditions.append(RuleConditionEvidence(
            condition_id="handoff_requirement",
            description="Bàn giao công việc/kế hoạch thay thế cho người trực thay",
            kind="mandatory",
            verdict="NOT_MET",
            chunk_id=handoff_cid,
            case_fact="chưa có người nhận bàn giao",
        ))
        rendered_notes.append({
            "id": "handoff_requirement",
            "status": "NOT_MET",
            "bullet": f"- **Bàn giao công việc (`NOT_MET`):** Quy định bắt buộc bàn giao cho người trực thay, nhưng đơn ghi **chưa có** người nhận bàn giao.{cite_part}",
        })

    # 5. Remaining leave / quota unknown check — only applies to leave-related queries & policy chunks
    _leave_query_pat = re.compile(
        r"(?:nghỉ\s*phép|nghỉ\s*hằng\s*năm|phép\s*năm|đơn\s+xin\s+nghỉ|leave\s+request|annual\s+leave|remaining\s+leave)",
        re.I,
    )
    _bal_pat = re.compile(r"(?:nghỉ\s+phép|nghỉ\s+hằng\s+năm|phép\s+năm|annual\s+leave|leave\s+balance)", re.I)
    _bal_policy_pat = re.compile(
        r"(?:quy\s+định|tối\s+đa|được\s+nghỉ|được\s+hưởng|nộp\s+đơn|báo\s+trước|phê\s+duyệt|bàn\s+giao|annual\s+leave|policy)",
        re.I,
    )
    if _leave_query_pat.search(query or "") and _bal_pat.search(ev_text) and not re.search(r"ngày\s+phép\s+đã\s+nghỉ\s*[:=]?\s*\d+", case_text, re.I):
        bal_cid = ""
        for ch in auth_chunks:
            ch_txt = ch.text or ""
            sname_cf = (ch.source_name or "").casefold()
            # Never cite an overtime/timesheet table (e.g. Lam_them) as leave-quota policy evidence
            if "## lam_them" in ch_txt.casefold() or "lam_them" in sname_cf or "chấm công" in sname_cf:
                continue
            if _bal_pat.search(ch_txt) and _bal_policy_pat.search(ch_txt):
                bal_cid = ch.chunk_id
                break
        cite_part = f" [{bal_cid}]" if bal_cid else ""
        conditions.append(RuleConditionEvidence(
            condition_id="remaining_balance",
            description="Số ngày phép còn lại",
            kind="mandatory",
            verdict="UNKNOWN",
            chunk_id=bal_cid,
            missing_evidence_reason="missing leave history",
        ))
        rendered_notes.append({
            "id": "remaining_balance",
            "status": "UNKNOWN",
            "bullet": f"- **Số ngày phép còn lại (`UNKNOWN`):** Chưa rõ (chưa có dữ liệu số ngày phép đã nghỉ trong phạm vi tài liệu đang đối chiếu).{cite_part}",
        })

    assessment = assess_rule_conditions(
        conditions,
        evidence_chunks=auth_chunks,
        allowed_source_ids=allowed_source_ids,
    )
    return assessment.to_dict(), rendered_notes


_CONTRA_POSITIVES_RE = re.compile(
    r"(?:→\s*)?(?:\*{1,2}|_{1,2})?(?:thỏa mãn|đáp ứng|hợp lệ|đạt yêu cầu|đúng quy định|đúng nội quy|đúng yêu cầu|không vi phạm|đã được phê duyệt|thuộc phạm vi được phê duyệt)(?:\*{1,2}|_{1,2})?",
    re.I,
)
_EXACT_TOPIC_UNMET_CUES = {
    "notice_period": re.compile(r"(?:gửi\s+đơn|nộp\s+đơn|thời\s+gian\s+gửi|báo\s+trước|03\s+ngày|05\s+ngày|\btrước\s+ít\s+nhất\b|\d{1,2}/\d{1,2}(?:/\d{4})?\s*→)", re.I),
    "handoff_requirement": re.compile(r"(?:bàn\s+giao|trực\s+thay|chưa\s+có)", re.I),
    "peak_season": re.compile(r"(?:cao\s+điểm|tháng\s+\d{1,2}\b)", re.I),
    "multi_level_approval": re.compile(r"(?:phê\s+duyệt|thẩm\s+quyền|trưởng\s+phòng|giám\s+đốc)", re.I),
}
_OVERALL_PASS_PROSE_RE = re.compile(
    r"(?<!không\s)(?<!chưa\s)\b(?:đơn(?:\s+xin\s+nghỉ\s+phép)?\s+(?:đạt\s+yêu\s+cầu|hợp\s+lệ|đủ\s+điều\s+kiện|đúng\s+quy\s+định|đúng\s+nội\s+quy))\b",
    re.I,
)


def _extract_full_dmy_set(text: str) -> set[tuple[int, int, int]]:
    out: set[tuple[int, int, int]] = set()
    for m in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text or ""):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.add((d, mo, y))
    return out


def _reconcile_rule_reasoning(
    query: str,
    chunks: list[SourceChunk],
    llm_answer: str,
    *,
    allowed_source_ids: set[str] | None = None,
) -> tuple[str, bool, list[str], str, dict[str, Any]]:
    """Single Source of Truth rule rendering driven by VerifiedStructuredResult (heading-independent, fabricated-fact safe)."""
    assessment, notes = _assess_rule_case(query, chunks, allowed_source_ids=allowed_source_ids)
    overall = assessment.get("overall", "UNRESOLVED")
    conds = assessment.get("conditions") or []
    unmet_ids = {c["condition_id"] for c in conds if c.get("verdict") in {"NOT_MET", "UNKNOWN"}}
    notes_by_id = {n["id"]: n["bullet"] for n in notes}
    auth_chunks = [c for c in chunks if allowed_source_ids is None or c.source_id in allowed_source_ids]
    auth_chunk_ids = {c.chunk_id for c in auth_chunks}

    grounded_dates = _extract_full_dmy_set(f"{query or ''}\n" + "\n".join(c.text or "" for c in auth_chunks))
    llm_dates = _extract_full_dmy_set(llm_answer or "")
    fabricated_dates = llm_dates - grounded_dates
    grounded_years = set(re.findall(r"\b(?:19\d{2}|20\d{2})\b", f"{query or ''}\n" + "\n".join(c.text or "" for c in auth_chunks)))
    llm_years = set(re.findall(r"\b(?:19\d{2}|20\d{2})\b", llm_answer or ""))
    fabricated_years = (llm_years - grounded_years) if grounded_years else set()

    _case_part = query.split(IMG_MARK, 1)[1] if IMG_MARK in (query or "") else (query or "")
    _m_sub = re.search(
        r"(?:ngày\s+(?:gửi|nộp|đăng ký)\s*(?:đơn|phiếu)?|submitted(?:\s+on)?)\s*:[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        _case_part,
        re.I,
    )
    _m_rng = re.search(
        r"(?:từ|trip\s*:)\s*[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{4})\s*(?:đến|to|-)\s*[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        _case_part,
        re.I,
    )
    _d_sub = _parse_dmy(_m_sub.group(1)) if _m_sub else None
    _d_start = _parse_dmy(_m_rng.group(1)) if _m_rng else None
    date_order_note = ""
    date_interval_contradiction = False
    if _d_sub and _d_start:
        _cal_delta = (_d_start - _d_sub).days
        if _cal_delta > 0:
            date_order_note = (
                f"- **Đối chiếu ngày tháng xác thực (`DATE_CHECK`):** Ngày gửi đơn "
                f"**{_d_sub.strftime('%d/%m/%Y')}** ở trước ngày bắt đầu **{_d_start.strftime('%d/%m/%Y')}** "
                f"(**{_cal_delta} ngày lịch**), không nằm trong khoảng thời gian nghỉ."
            )
            if re.search(
                r"(?:nằm\s+trong|thuộc|trong)\s+(?:khoảng|giai\s+đoạn|thời\s+gian)\s+(?:từ|nghỉ|\d{1,2}/\d{1,2})",
                llm_answer or "",
                re.I,
            ):
                date_interval_contradiction = True

    if not conds and not fabricated_dates and not fabricated_years and not date_interval_contradiction:
        return llm_answer, False, [], overall, assessment

    policy_only_re = re.compile(
        r"(?:theo\s+(?:chính\s+sách|quy\s+định\s+(?:chung|công\s+ty))[^\n]{0,30}(?:khi|nếu|phải)|"
        r"hợp\s+lệ\s+khi|is\s+compliant\s+when|policy\s+requires)",
        re.I,
    )
    case_claim_leak_re = re.compile(
        r"(?:\b(?:đơn\s+này|trường\s+hợp\s+này|người\s+làm\s+đơn|nhân\s+viên\s+đã|đã\s+được[^\n.]{0,30}phê\s+duyệt|"
        r"còn\s+dư\s+\d+|submitted)\b|→\s*(?:\*{0,2})đúng|✓|\bPASS\b)",
        re.I,
    )

    if overall in {"NOT_ELIGIBLE", "INSUFFICIENT_INFO", "CONFLICT"} or fabricated_dates or fabricated_years or date_interval_contradiction:
        # When overall is INSUFFICIENT_INFO solely because of uncollected leave-balance history (no NOT_MET, no unverified
        # approval gap, no fabricated date/year, no date interval contradiction, and no fabricated balance/approval claims),
        # preserve valid positive explanation on the checked conditions and append the structured UNKNOWN verification note cleanly.
        unknown_conds = {str(c.get("condition_id") or "") for c in conds if c.get("verdict") == "UNKNOWN"}
        has_not_met = any(c.get("verdict") == "NOT_MET" for c in conds)
        has_overclaim = bool(
            fabricated_dates
            or fabricated_years
            or date_interval_contradiction
            or case_claim_leak_re.search(llm_answer or "")
            or re.search(r"\b(?:được\s+phê\s+duyệt|còn\s+dư\s+\d+\s+ngày|đủ\s+\d+\s+ngày\s+phép)\b", llm_answer or "", re.I)
        )
        if overall == "INSUFFICIENT_INFO" and not has_not_met and unknown_conds <= {"remaining_balance"} and not has_overclaim:
            note_bullets = [n["bullet"] for n in notes]
            out_bal = (llm_answer or "").strip()
            if note_bullets and "### Đối chiếu quy định xác thực (V2 Rule Check)" not in out_bal:
                out_bal = f"{out_bal}\n\n### Đối chiếu quy định xác thực (V2 Rule Check)\n" + "\n".join(note_bullets)
            out_final_bal = deduplicate_warnings(out_bal)
            return out_final_bal, False, note_bullets, overall, assessment

        # Preserve only pure abstract policy statements free of fabricated dates/years or case-satisfaction claims
        preserved_policy: list[str] = []
        for ln in (llm_answer or "").splitlines():
            s_strip = ln.strip()
            if not s_strip or s_strip.startswith(("#", ">")):
                continue
            if not policy_only_re.search(ln):
                continue
            if case_claim_leak_re.search(ln):
                continue
            if (_extract_full_dmy_set(ln) - grounded_dates) or (fabricated_years and (set(re.findall(r"\b(?:19\d{2}|20\d{2})\b", ln)) & fabricated_years)):
                continue
            if date_interval_contradiction and re.search(r"(?:nằm\s+trong|thuộc|trong)\s+(?:khoảng|giai\s+đoạn|thời\s+gian)", ln, re.I):
                continue
            # Keep only authorized inline citations on that pure policy line
            cleaned_ln = re.sub(
                r"\[(src_[0-9a-f]+_c\d{4}|[A-Za-z0-9_]+_c\d{4})\]",
                lambda m: m.group(0) if m.group(1) in auth_chunk_ids else "",
                ln,
            ).strip()
            if cleaned_ln and cleaned_ln not in preserved_policy:
                preserved_policy.append(cleaned_ln)

        # Build complete authoritative bullet list directly from VerifiedStructuredResult conditions
        ssot_bullets: list[str] = []
        for c in conds:
            cid_cond = str(c.get("condition_id") or "")
            if cid_cond in notes_by_id:
                ssot_bullets.append(notes_by_id[cid_cond])
            else:
                verdict = str(c.get("verdict") or "UNKNOWN")
                desc = str(c.get("description") or cid_cond)
                fact = str(c.get("case_fact") or "Đã đối chiếu theo dữ kiện hợp lệ")
                ch_ref = f" [{c['chunk_id']}]" if c.get("chunk_id") else ""
                ssot_bullets.append(f"- **{desc} (`{verdict}`):** {fact}.{ch_ref}")
        if date_order_note and not any(c.get("condition_id") == "notice_period" for c in conds):
            ssot_bullets.append(date_order_note)
        if not conds and overall == "UNRESOLVED" and (fabricated_years or fabricated_dates or date_interval_contradiction):
            overall = "INSUFFICIENT_INFO"
            ssot_bullets.append(
                "- **Thiếu quy định nội bộ xác thực (`UNKNOWN`):** Không thể tự khẳng định tuân thủ nội quy/quy định phòng ban khi chưa có điều khoản nội bộ phù hợp được đối chiếu."
            )

        if overall == "NOT_ELIGIBLE":
            banner = (
                "> **Cảnh báo nhất quán (`NOT_ELIGIBLE`):** Chưa đủ điều kiện kết luận đạt do có điều kiện "
                "bắt buộc chưa thỏa mãn hoặc vi phạm trong phần đối chiếu bên dưới."
            )
            verdict_line = "Yêu cầu/đơn **chưa đủ điều kiện / không thỏa mãn quy định** (`NOT_ELIGIBLE`)."
        elif overall in {"INSUFFICIENT_INFO", "CONFLICT"}:
            banner = (
                f"> **Cảnh báo nhất quán (`{overall}`):** Chưa đủ căn cứ kết luận đạt do còn điều kiện "
                "hoặc phê duyệt bắt buộc chưa được xác nhận."
            )
            verdict_line = f"Yêu cầu/đơn **chưa đủ căn cứ kết luận đạt** (`{overall}`) do còn điều kiện chưa rõ (`UNKNOWN`)."
        else:
            # ELIGIBLE overall, but LLM hallucinated ungrounded dates -> remove fabricated-date lines while keeping verdict
            banner = (
                "> **Kiểm chứng dữ kiện:** Đã loại bỏ các mốc ngày không có trong đơn/tài liệu để bảo đảm tính xác thực."
            )
            verdict_line = "Yêu cầu/đơn đạt các điều kiện đã kiểm chứng (`ELIGIBLE`)."

        sections: list[str] = [banner, verdict_line]
        if ssot_bullets:
            sections.append("### Đối chiếu quy định xác thực (V2 Rule Check)\n" + "\n".join(ssot_bullets))
        if preserved_policy:
            sections.append("### Quy định chung áp dụng\n" + "\n".join(preserved_policy))

        # Preserve any authorized citations from LLM draft / conditions not yet present in authoritative body
        rendered = "\n\n".join(sections)
        all_auth_cits: list[str] = []
        for cid in _INLINE_CIT_RE.findall(llm_answer or ""):
            if cid in auth_chunk_ids and cid not in all_auth_cits:
                all_auth_cits.append(cid)
        for c in conds:
            cid = str(c.get("chunk_id") or "")
            if cid and cid in auth_chunk_ids and cid not in all_auth_cits:
                all_auth_cits.append(cid)
        missing_cits = [cid for cid in all_auth_cits if cid not in rendered]
        if missing_cits:
            rendered += "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in missing_cits)

        out_final = deduplicate_warnings(rendered)
        changed = out_final.strip() != (llm_answer or "").strip()
        note_bullets = [n["bullet"] for n in notes]
        return out_final, changed, note_bullets, overall, assessment

    return llm_answer, False, [n["bullet"] for n in notes], overall, assessment


def verify_and_reconcile_answer(
    *,
    query: str,
    chunks: list[SourceChunk],
    llm_answer: str,
    status: str = "COMPLETE",
    allowed_source_ids: set[str] | None = None,
    **formula_kwargs: Any,
) -> dict[str, Any]:
    """Run verified deterministic calculation/rule/identifier reconciliation without calling LLM/Ollama."""
    evidence_text = "\n".join(c.text for c in chunks)
    ignored_ids = sorted(identifier_numbers_in_text(f"{query}\n{evidence_text}"))
    needs_calc = _needs_calculation(query or "", formula_kwargs)
    needs_rule = bool(_RULE_INTENT_RE.search(query or ""))
    needs_approval = is_approval_query(query or "")

    if not needs_calc and not needs_rule and not needs_approval:
        return {
            "applied": False,
            "mode": "bypassed_general_or_lookup",
            "status": status,
            "final_answer": deduplicate_warnings(llm_answer),
            "contradicted_llm": False,
            "ignored_identifier_numbers": ignored_ids,
            "verified_summary": "",
        }

    if needs_calc:
        spec = select_formula(query, chunks=chunks, allowed_source_ids=allowed_source_ids, **formula_kwargs)
        res = execute_formula(spec)
        appr_res: ApprovalResolution | None = None
        if needs_approval:
            appr_res = resolve_approval_authority(
                query,
                chunks,
                allowed_source_ids=allowed_source_ids,
                calc_context=res.params or spec.params,
            )

        if res.status == CalcStatus.VERIFIED and res.value is not None:
            has_expected = _llm_contains_number(llm_answer, res.value)
            contradicted = (not has_expected) or _llm_has_contradicting_total(llm_answer, res.value)
            cite_str = ", ".join(f"[{cid}]" for cid in dict.fromkeys(res.evidence_references))
            steps_md = "\n".join(f"- {s}" for s in res.steps)
            verified_block = (
                f"**Kết quả đã xác minh ({spec.formula_type}):** **{res.formatted_value}**"
                + (f" ({res.unit})" if res.unit and res.unit not in res.formatted_value else "")
                + (f"\n\n### Các bước tính xác thực\n{steps_md}" if steps_md else "")
                + (f"\n\nCăn cứ trích dẫn: {cite_str}" if cite_str else "")
            )
            verified_nums = {
                _canonical_dec_str(p)
                for text_part in [res.formatted_value, *res.steps]
                for m in _NUM_EXTRACT.finditer(text_part)
                if (p := _parse_any_num(m.group(0))) is not None
            }
            ignored_all = sorted({*ignored_ids, *verified_nums})
            if contradicted:
                preserved_rest, rescued_cits = _strip_wrong_total_sentences(llm_answer, res.value)
                corr_banner = (
                    f"> **Đã hiệu chỉnh bằng phép tính xác thực:** Kết quả tự sinh trước đó không khớp phép tính kiểm chứng; "
                    f"giá trị chính xác theo bằng chứng là **{res.formatted_value}**."
                )
                parts = [corr_banner, verified_block]
                if preserved_rest:
                    parts.append(preserved_rest)
                missing_rescued = [cid for cid in rescued_cits if cid not in "\n".join(parts)]
                if missing_rescued:
                    parts.append("Nguồn: " + ", ".join(f"[{cid}]" for cid in missing_rescued))
                final_ans = "\n\n".join(parts)
            elif res.formatted_value in (llm_answer or ""):
                final_ans = llm_answer
            else:
                final_ans = f"{verified_block}\n\n{llm_answer}".strip()

            appr_changed = False
            if appr_res is not None:
                final_ans, appr_changed = reconcile_approval_in_answer(final_ans, appr_res)
                contradicted = contradicted or appr_changed
            final_ans = deduplicate_warnings(final_ans)
            structured = VerifiedStructuredResult(
                intent="calculation_and_approval" if appr_res is not None else "calculation",
                overall_verdict="VERIFIED",
                facts=[f"computed_total={res.formatted_value}"],
                calculation_steps=list(res.steps),
                approval_authority=asdict(appr_res) if appr_res is not None else None,
                unknown_conditions=[appr_res.missing_condition] if (appr_res and appr_res.missing_condition) else [],
                evidence_references=list(dict.fromkeys(res.evidence_references + ([appr_res.chunk_id] if appr_res and appr_res.chunk_id else []))),
            )
            return {
                "applied": True,
                "mode": "calculator_verified",
                "calc_status": res.status,
                "status": "COMPLETE" if status == "COMPLETE" else status,
                "final_answer": final_ans,
                "contradicted_llm": contradicted,
                "verified_value": str(res.value),
                "verified_summary": verified_block,
                "ignored_identifier_numbers": ignored_all,
                "structured_result": structured.to_dict(),
            }

        if res.status in {CalcStatus.MISSING_OPERAND, CalcStatus.INVALID_UNIT, CalcStatus.AMBIGUOUS_FORMULA, CalcStatus.CONFLICT, CalcStatus.UNSUPPORTED}:
            if IMG_MARK in (query or "") or res.status in {CalcStatus.INVALID_UNIT, CalcStatus.AMBIGUOUS_FORMULA, CalcStatus.CONFLICT, CalcStatus.MISSING_OPERAND}:
                cleaned_body = _retract_speculative_totals(llm_answer)
                oracle_rev = bool((res.params or {}).get("oracle_review_required"))
                formula_tpl = str((res.params or {}).get("formula_template") or "")
                tpl_line = f" Công thức xác thực: `{formula_tpl}` (thiếu `actual_hours_per_day`)." if formula_tpl else ""
                note = (
                    f"> **Kiểm chứng tính toán ({res.status}):** Chưa đủ căn cứ hợp lệ để chốt con số cuối cùng "
                    f"({res.reason}).{tpl_line} Không khẳng định tổng số tiền chưa được kiểm chứng; vui lòng bổ sung hoặc làm rõ dữ kiện còn thiếu."
                )
                final_ans = f"{note}\n\n{cleaned_body}".strip() if cleaned_body else note
                if appr_res is not None:
                    final_ans, _ = reconcile_approval_in_answer(final_ans, appr_res)
                final_ans = deduplicate_warnings(final_ans)
                structured = VerifiedStructuredResult(
                    intent="calculation",
                    overall_verdict=res.status,
                    unknown_conditions=list(spec.required_operands),
                    evidence_references=list(res.evidence_references),
                )
                return {
                    "applied": True,
                    "mode": "calculator_guarded",
                    "calc_status": res.status,
                    "oracle_review_required": oracle_rev,
                    "status": "PARTIAL",
                    "final_answer": final_ans,
                    "contradicted_llm": bool(cleaned_body != (llm_answer or "").strip()),
                    "verified_summary": note,
                    "ignored_identifier_numbers": ignored_ids,
                    "structured_result": structured.to_dict(),
                }

    # Rule intent verification (FIX-03: structured rule assessment + deterministic affected-section consistency)
    if needs_rule:
        reconciled, rule_changed, rule_notes, overall, assessment = _reconcile_rule_reasoning(
            query or "",
            chunks,
            llm_answer,
            allowed_source_ids=allowed_source_ids,
        )
        has_contradiction = bool(_RULE_NEGATIVE.search(reconciled) and _RULE_POSITIVE.search(reconciled))
        if rule_changed or has_contradiction or rule_notes or overall in {"NOT_ELIGIBLE", "INSUFFICIENT_INFO"}:
            conds = assessment.get("conditions") or []
            structured = VerifiedStructuredResult(
                intent="rule",
                overall_verdict=overall,
                facts=[c.get("case_fact", "") for c in conds if c.get("case_fact")],
                applicable_conditions=[c.get("description", "") for c in conds],
                condition_verdicts=conds,
                approval_authority={"roles": assessment.get("approval_requirements", [])} if assessment.get("approval_requirements") else None,
                unknown_conditions=[c["description"] for c in conds if c.get("verdict") == "UNKNOWN"],
                evidence_references=[c["chunk_id"] for c in conds if c.get("chunk_id")],
            )
            return {
                "applied": True,
                "mode": "rule_contradiction_detected" if (rule_changed or has_contradiction) else "rule_verified",
                "rule_overall": overall,
                "status": "PARTIAL" if overall != "ELIGIBLE" else ("COMPLETE" if status == "COMPLETE" else status),
                "final_answer": deduplicate_warnings(reconciled),
                "contradicted_llm": bool(rule_changed or has_contradiction),
                "verified_summary": "; ".join(rule_notes) if rule_notes else "contradictory rule assertion reconciled",
                "ignored_identifier_numbers": ignored_ids,
                "structured_result": structured.to_dict(),
            }

    if needs_approval:
        appr_only = resolve_approval_authority(query, chunks, allowed_source_ids=allowed_source_ids)
        final_ans, appr_changed = reconcile_approval_in_answer(llm_answer, appr_only)
        if appr_changed:
            structured = VerifiedStructuredResult(
                intent="approval",
                overall_verdict=appr_only.status,
                approval_authority=asdict(appr_only),
                unknown_conditions=[appr_only.missing_condition] if appr_only.missing_condition else [],
                evidence_references=[appr_only.chunk_id] if appr_only.chunk_id else [],
            )
            return {
                "applied": True,
                "mode": "approval_reconciled",
                "status": "PARTIAL" if appr_only.status != "VERIFIED" else status,
                "final_answer": deduplicate_warnings(final_ans),
                "contradicted_llm": True,
                "verified_summary": appr_only.authority or appr_only.missing_condition,
                "ignored_identifier_numbers": ignored_ids,
                "structured_result": structured.to_dict(),
            }

    return {
        "applied": bool(ignored_ids),
        "mode": "identifier_audit_only",
        "status": status,
        "final_answer": deduplicate_warnings(llm_answer),
        "contradicted_llm": False,
        "verified_summary": "",
        "ignored_identifier_numbers": ignored_ids,
    }
