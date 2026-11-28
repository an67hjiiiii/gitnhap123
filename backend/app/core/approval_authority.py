"""Conditional Approval Authority Extraction & Resolution (B139.2F3 FIX-01).

Extracts actor, authority, action, threshold metric/bounds, applicability conditions,
exceptions, and sequential approval requirements from Markdown tables and policy prose
without hardcoding company names, job titles, or specific numbers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
import re
from typing import Any

from app.core.structured_evidence import (
    _APPROVAL_COL,
    _EXAMPLE_MARKER,
    _is_table_separator,
    _table_cells,
    parse_localized_number,
)
from app.core.types import SourceChunk

_APPROVAL_QUERY_RE = re.compile(
    r"(?:ai\s+(?:là\s+người\s+)?(?:phê\s+duyệt|duyệt|ký\s+duyệt|quyết\s+định|chấp\s+thuận)|"
    r"cấp\s+(?:phê\s+)?duyệt|thẩm\s+quyền\s+(?:phê\s+)?duyệt|"
    r"who\s+(?:approves?|must\s+approve|authorizes?|has\s+authority)|"
    r"approving\s+authority|approval\s+authority|self-authoriz)",
    re.I,
)
_SELF_AUTH_RE = re.compile(
    r"(?:tự\s+quyết|tự\s+phê\s+duyệt|self-authoriz|auto-approv|không\s+cần\s+(?:trình\s+)?duyệt)",
    re.I,
)
_FIXED_FEE_DISC_QUERY_RE = re.compile(
    r"(?:chiết\s+khấu|giảm(?:\s+giá)?|discount)[^\n?]{0,40}"
    r"(?:phí\s+(?:triển\s+khai|cố\s+định|cài\s+đặt|khởi\s+tạo|kỹ\s+sư)|setup\s+fee|fixed\s+fee)",
    re.I,
)
_SEQ_PROSE_RE = re.compile(
    r"(?:hợp\s+đồng|đơn|giao\s+dịch|chi\s+phí|nghỉ|contract|order|request|expense)[^\n.;]{0,80}?"
    r"(?:trên|vượt(?:\s+quá)?|từ|above|over|exceeding|>=?)\s*"
    r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(tỷ|triệu|nghìn|ngàn|%|ngày(?:\s+làm\s+việc)?|đồng|đ|vnd|usd|\$)?[^\n.;]{0,60}?"
    r"(?:phải\s+được|cần)\s+([^.\n;]+?)\s+(?:phê\s+duyệt|duyệt)",
    re.I,
)
_EXCEPTION_PROSE_RE = re.compile(
    r"không\s+(?:chiết\s+khấu|giảm(?:\s+giá)?)\s+([^,.;\n]+?)[\s,;]+trừ\s+khi\s+([^.\n;]+?)\s+(?:phê\s+duyệt|duyệt)",
    re.I,
)
_WRONG_APPROVER_CLAIM_RE = re.compile(
    r"(?:Mức\s+chiết\s+khấu(?:\s+này)?|Khoản\s+chiết\s+khấu|Đơn|Hợp\s+đồng|Yêu\s+cầu|The\s+discount|This\s+request)?"
    r"[^\n.]{0,60}?(?:được\s+(?:phê\s+)?duyệt\s+bởi|do\s+[^.\n]{2,50}?(?:phê\s+)?duyệt|tự\s+quyết|"
    r"approved\s+by|requires?\s+[^.\n]{2,50}?approval|self-authorized)",
    re.I,
)


@dataclass
class ApprovalRuleRecord:
    authority: str
    action: str
    metric_kind: str  # discount_rate | original_price | final_amount | fixed_fee_discount | duration_days
    min_val: Decimal | None = None
    max_val: Decimal | None = None
    min_inc: bool = True
    max_inc: bool = True
    unit: str = ""
    actor: str = ""
    self_authorized: bool = False
    sequential_roles: list[str] = field(default_factory=list)
    applicability_conditions: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    source_id: str = ""
    chunk_id: str = ""
    source_span: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "min_val": str(self.min_val) if self.min_val is not None else None,
            "max_val": str(self.max_val) if self.max_val is not None else None,
        }


@dataclass
class ApprovalResolution:
    status: str  # VERIFIED | UNKNOWN | CONFLICT | NOT_APPLICABLE
    authority: str = ""
    self_authorized: bool = False
    sequential_roles: list[str] = field(default_factory=list)
    metric_kind: str = ""
    metric_value: str = ""
    source_id: str = ""
    chunk_id: str = ""
    source_span: str = ""
    missing_condition: str = ""
    reason: str = ""
    matched_rule: dict[str, Any] | None = None


def _infer_metric_kind(header: str) -> str:
    h = (header or "").casefold()
    if any(k in h for k in ("chiết khấu", "discount", "giảm giá")):
        return "discount_rate"
    if any(k in h for k in ("giá niêm yết", "giá gốc", "original", "list price")):
        return "original_price"
    if any(k in h for k in ("cuối cùng", "sau giảm", "final", "giá trị hợp đồng", "tổng", "order amount", "contract value", "amount")):
        return "final_amount"
    if any(k in h for k in ("ngày", "days", "duration")):
        return "duration_days"
    return "generic_amount"


def _parse_threshold_bounds(text: str, metric_kind: str) -> tuple[Decimal | None, Decimal | None, bool, bool, str]:
    t = (text or "").strip()
    is_pct = "%" in t or metric_kind == "discount_rate"
    is_usd = "$" in t or "usd" in t.casefold()
    unit = "percent" if is_pct else ("USD" if is_usd else ("day" if metric_kind == "duration_days" else "VND"))
    loc = "en" if is_usd else "vi"

    def _to_dec(raw: str, scale: str = "") -> Decimal | None:
        v, _, _ = parse_localized_number(raw, locale_hint=loc, unit_hint="percent" if is_pct else unit)
        if v is None:
            return None
        d = Decimal(str(v))
        sc = (scale or "").strip().casefold()
        mult = {"tỷ": Decimal("1000000000"), "triệu": Decimal("1000000"), "nghìn": Decimal("1000"), "ngàn": Decimal("1000")}.get(sc, Decimal("1"))
        return d * mult

    num_pat = r"\$?\s*(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(tỷ|triệu|nghìn|ngàn)?\s*%?"
    m_bet = re.search(rf"(?:trên|above|>)\s*{num_pat}\s*(?:đến|tới|to|-)\s*{num_pat}", t, re.I)
    if m_bet:
        lo = _to_dec(m_bet.group(1), m_bet.group(2) or "")
        hi = _to_dec(m_bet.group(3), m_bet.group(4) or "")
        return lo, hi, False, True, unit

    m_from_to = re.search(rf"(?:từ|from)\s+{num_pat}\s*(?:đến|tới|to|-|–|—)\s*{num_pat}", t, re.I)
    if m_from_to:
        lo = _to_dec(m_from_to.group(1), m_from_to.group(2) or "")
        hi = _to_dec(m_from_to.group(3), m_from_to.group(4) or "")
        return lo, hi, True, True, unit

    m_dash = re.search(rf"^\s*{num_pat}\s*(?:-|–|—|đến|tới|to)\s*{num_pat}\s*$", t, re.I)
    if m_dash:
        lo = _to_dec(m_dash.group(1), m_dash.group(2) or "")
        hi = _to_dec(m_dash.group(3), m_dash.group(4) or "")
        return lo, hi, True, True, unit

    m_up_to = re.search(rf"(?:đến|tối đa|up\s+to|<=)\s*{num_pat}", t, re.I)
    if m_up_to:
        hi = _to_dec(m_up_to.group(1), m_up_to.group(2) or "")
        return Decimal("0"), hi, True, True, unit

    m_above = re.search(rf"(?:trên|vượt(?:\s+quá)?|above|over|exceeding|>)\s*{num_pat}", t, re.I)
    if m_above:
        lo = _to_dec(m_above.group(1), m_above.group(2) or "")
        return lo, None, False, False, unit

    m_gte = re.search(rf"(?:từ|>=)\s*{num_pat}", t, re.I)
    if m_gte:
        lo = _to_dec(m_gte.group(1), m_gte.group(2) or "")
        return lo, None, True, False, unit

    return None, None, True, True, unit


def _split_roles(raw_auth: str) -> list[str]:
    cleaned = re.sub(r"\s*(?:theo\s+thứ\s+tự|sequentially|lần\s+lượt)\s*", "", raw_auth, flags=re.I).strip()
    parts = [p.strip(" .;") for p in re.split(r"\s*(?:\bvà\b|\band\b|->|→|,)\s*", cleaned) if p.strip(" .;")]
    return parts if len(parts) > 1 else []


def extract_approval_rules(
    chunks: list[SourceChunk],
    *,
    allowed_source_ids: set[str] | None = None,
) -> list[ApprovalRuleRecord]:
    """Extract structured approval threshold rules from Markdown tables and policy prose."""
    rules: list[ApprovalRuleRecord] = []
    for ch in chunks:
        if allowed_source_ids is not None and ch.source_id not in allowed_source_ids:
            continue
        lines = (ch.text or "").splitlines()
        headers: list[str] = []
        for idx, raw in enumerate(lines):
            ln = raw.strip()
            if not ln or _EXAMPLE_MARKER.search(ln):
                if not ln:
                    headers = []
                continue
            if "|" in ln and idx + 1 < len(lines) and _is_table_separator(lines[idx + 1].strip()):
                headers = _table_cells(ln)
                continue
            if _is_table_separator(ln):
                continue
            if "|" in ln and headers:
                cells = _table_cells(ln)
                appr_idx = next((i for i, h in enumerate(headers) if _APPROVAL_COL.search(h)), None)
                if appr_idx is not None and len(cells) > appr_idx:
                    thresh_idx = next((i for i in range(len(headers)) if i != appr_idx), None)
                    if thresh_idx is not None and thresh_idx < len(cells):
                        mkind = _infer_metric_kind(headers[thresh_idx])
                        lo, hi, min_inc, max_inc, unit = _parse_threshold_bounds(cells[thresh_idx], mkind)
                        auth = cells[appr_idx].strip()
                        if auth and (lo is not None or hi is not None):
                            rules.append(ApprovalRuleRecord(
                                authority=auth,
                                action="approve",
                                metric_kind=mkind,
                                min_val=lo,
                                max_val=hi,
                                min_inc=min_inc,
                                max_inc=max_inc,
                                unit=unit,
                                self_authorized=bool(_SELF_AUTH_RE.search(auth)),
                                sequential_roles=_split_roles(auth),
                                source_id=ch.source_id,
                                chunk_id=ch.chunk_id,
                                source_span=ln,
                            ))
                continue
            headers = []

            m_exc = _EXCEPTION_PROSE_RE.search(ln)
            if m_exc:
                rules.append(ApprovalRuleRecord(
                    authority=m_exc.group(2).strip(),
                    action="exception_approval",
                    metric_kind="fixed_fee_discount",
                    exceptions=[m_exc.group(1).strip()],
                    source_id=ch.source_id,
                    chunk_id=ch.chunk_id,
                    source_span=ln,
                ))

            m_seq = _SEQ_PROSE_RE.search(ln)
            if m_seq:
                mkind = "duration_days" if "ngày" in (m_seq.group(2) or "").casefold() else "final_amount"
                lo, hi, min_inc, max_inc, unit = _parse_threshold_bounds(m_seq.group(0), mkind)
                auth = m_seq.group(3).strip()
                rules.append(ApprovalRuleRecord(
                    authority=auth,
                    action="approve",
                    metric_kind=mkind,
                    min_val=lo,
                    max_val=hi,
                    min_inc=min_inc,
                    max_inc=max_inc,
                    unit=unit,
                    self_authorized=bool(_SELF_AUTH_RE.search(auth)),
                    sequential_roles=_split_roles(auth),
                    source_id=ch.source_id,
                    chunk_id=ch.chunk_id,
                    source_span=ln,
                ))
    return rules


def is_approval_query(query: str) -> bool:
    return bool(_APPROVAL_QUERY_RE.search(query or ""))


def _extract_query_metrics(query: str, calc_context: dict[str, Any] | None) -> dict[str, Decimal]:
    metrics: dict[str, Decimal] = {}
    ctx = calc_context or {}
    for k in ("discount_pct", "base", "total", "duration_days"):
        v = ctx.get(k)
        if v is not None:
            metrics[k] = v if isinstance(v, Decimal) else Decimal(str(v))
    q = query or ""
    if "discount_pct" not in metrics:
        m_pct = re.search(r"chiết\s+khấu\s*(\d+(?:[.,]\d+)?)\s*%|(\d+(?:[.,]\d+)?)\s*%\s*(?:discount|chiết\s+khấu)", q, re.I)
        if m_pct:
            raw = m_pct.group(1) or m_pct.group(2)
            metrics["discount_pct"] = Decimal(raw.replace(",", "."))
    if "base" not in metrics:
        m_orig = re.search(r"(?:original\s+list\s+price|giá\s+niêm\s+yết)[^\d$]{0,20}\$?\s*(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)", q, re.I)
        if m_orig:
            v, _, _ = parse_localized_number(m_orig.group(1), locale_hint="en" if "$" in m_orig.group(0) else "vi")
            if v is not None:
                metrics["base"] = Decimal(str(v))
    if "total" not in metrics:
        m_tot = re.search(r"(?:giá\s+trị|tổng|contract\s+value|order\s+amount)[^\d$]{0,20}\$?\s*(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)", q, re.I)
        if m_tot:
            v, _, _ = parse_localized_number(m_tot.group(1), locale_hint="en" if "$" in m_tot.group(0) else "vi")
            if v is not None:
                metrics["total"] = Decimal(str(v))
    return metrics


def _matches_bracket(val: Decimal, r: ApprovalRuleRecord) -> bool:
    if r.min_val is not None:
        if r.min_inc and val < r.min_val:
            return False
        if not r.min_inc and val <= r.min_val:
            return False
    if r.max_val is not None:
        if r.max_inc and val > r.max_val:
            return False
        if not r.max_inc and val >= r.max_val:
            return False
    return True


def resolve_approval_authority(
    query: str,
    chunks: list[SourceChunk],
    *,
    allowed_source_ids: set[str] | None = None,
    calc_context: dict[str, Any] | None = None,
) -> ApprovalResolution:
    """Resolve authoritative approval role/actor from authorized chunks and verified metrics."""
    if not is_approval_query(query):
        return ApprovalResolution(status="NOT_APPLICABLE", reason="query does not ask about approval authority")

    rules = extract_approval_rules(chunks, allowed_source_ids=allowed_source_ids)
    if not rules:
        return ApprovalResolution(
            status="UNKNOWN",
            missing_condition="missing authorized approval authority policy rules",
            reason="no authorized approval rules extracted",
        )

    if _FIXED_FEE_DISC_QUERY_RE.search(query or ""):
        exc_rules = [r for r in rules if r.metric_kind == "fixed_fee_discount"]
        if exc_rules:
            auths = {r.authority.casefold(): r for r in exc_rules}
            if len(auths) > 1:
                return ApprovalResolution(status="CONFLICT", reason="conflicting exception approval rules")
            chosen = exc_rules[0]
            return ApprovalResolution(
                status="VERIFIED",
                authority=chosen.authority,
                self_authorized=chosen.self_authorized,
                sequential_roles=chosen.sequential_roles,
                metric_kind="fixed_fee_discount",
                source_id=chosen.source_id,
                chunk_id=chosen.chunk_id,
                source_span=chosen.source_span,
                reason="matched fixed-fee discount exception rule",
                matched_rule=chosen.to_dict(),
            )

    q_metrics = _extract_query_metrics(query, calc_context)
    metric_map = {
        "discount_rate": q_metrics.get("discount_pct"),
        "original_price": q_metrics.get("base"),
        "final_amount": q_metrics.get("total"),
        "generic_amount": q_metrics.get("total") if q_metrics.get("total") is not None else q_metrics.get("base"),
        "duration_days": q_metrics.get("duration_days"),
    }

    matched: list[tuple[ApprovalRuleRecord, Decimal]] = []
    missing_kinds: list[str] = []
    for r in rules:
        if r.metric_kind == "fixed_fee_discount":
            continue
        val = metric_map.get(r.metric_kind)
        if val is None:
            if r.metric_kind not in missing_kinds:
                missing_kinds.append(r.metric_kind)
            continue
        if _matches_bracket(val, r):
            matched.append((r, val))

    if not matched:
        missing_desc = ", ".join(missing_kinds) if missing_kinds else "applicable threshold metric"
        return ApprovalResolution(
            status="UNKNOWN",
            missing_condition=f"missing {missing_desc} to evaluate approval threshold",
            reason="threshold metric unavailable or no matching bracket",
        )

    # Prefer specific discount_rate / original_price / final_amount over generic_amount when multiple match
    specific = [(r, v) for r, v in matched if r.metric_kind != "generic_amount"]
    pool = specific or matched
    # Select precedence when multiple distinct policy tables/metrics exist
    q_cf = (query or "").casefold()
    kind_order = (
        ["discount_rate", "final_amount", "original_price", "duration_days", "generic_amount"]
        if any(k in q_cf for k in ("chiết khấu", "discount"))
        else ["final_amount", "original_price", "discount_rate", "duration_days", "generic_amount"]
    )
    available_kinds = {r.metric_kind for r, _ in pool}
    for pref_kind in kind_order:
        if pref_kind in available_kinds:
            pool = [(r, v) for r, v in pool if r.metric_kind == pref_kind]
            break

    distinct_auth = {r.authority.strip().casefold() for r, _ in pool}
    if len(distinct_auth) > 1:
        return ApprovalResolution(
            status="CONFLICT",
            reason=f"conflicting approval authorities: {sorted(r.authority for r, _ in pool)}",
        )

    chosen, mval = pool[0]
    return ApprovalResolution(
        status="VERIFIED",
        authority=chosen.authority,
        self_authorized=chosen.self_authorized,
        sequential_roles=chosen.sequential_roles,
        metric_kind=chosen.metric_kind,
        metric_value=str(mval),
        source_id=chosen.source_id,
        chunk_id=chosen.chunk_id,
        source_span=chosen.source_span,
        reason="matched verified approval threshold",
        matched_rule=chosen.to_dict(),
    )


def _strip_unsupported_approval_claims(
    answer: str,
    *,
    verified_auth_cf: str = "",
) -> tuple[str, bool]:
    """Strip LLM sentences asserting an unsupported approval authority role."""
    kept_lines: list[str] = []
    changed = False
    for ln in (answer or "").splitlines():
        segs = re.split(r"(?<=[.!?])\s+(?!\d)", ln) if ln.strip() else [ln]
        kept_segs: list[str] = []
        for s in segs:
            s_cf = s.casefold()
            if _WRONG_APPROVER_CLAIM_RE.search(s) and (not verified_auth_cf or verified_auth_cf not in s_cf):
                if not any(k in s_cf for k in ("chưa đủ căn cứ", "chưa rõ", "chưa xác định")):
                    changed = True
                    continue
            kept_segs.append(s)
        joined = " ".join(kept_segs).strip()
        if joined:
            kept_lines.append(joined)
        elif not ln.strip():
            kept_lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip(), changed


def reconcile_approval_in_answer(
    answer: str,
    res: ApprovalResolution,
) -> tuple[str, bool]:
    """Ensure final answer reflects verified approval authority without conflicting LLM title claims."""
    if res.status == "NOT_APPLICABLE":
        return answer, False
    if res.status == "UNKNOWN":
        cleaned, stripped = _strip_unsupported_approval_claims(answer)
        if res.missing_condition and res.missing_condition not in cleaned:
            note = f"**Thẩm quyền phê duyệt (`UNKNOWN`):** Chưa đủ căn cứ xác định ({res.missing_condition})."
            return f"{cleaned}\n\n{note}".strip(), True
        return cleaned, stripped
    if res.status == "CONFLICT":
        cleaned, stripped = _strip_unsupported_approval_claims(answer)
        note = f"**Thẩm quyền phê duyệt (`CONFLICT`):** Có mâu thuẫn giữa các tài liệu ({res.reason})."
        return f"{cleaned}\n\n{note}".strip(), True

    auth = res.authority
    ans = answer or ""
    auth_cf = auth.casefold()
    cleaned, changed = _strip_unsupported_approval_claims(ans, verified_auth_cf=auth_cf)
    if auth_cf not in cleaned.casefold():
        cite = f" [{res.chunk_id}]" if res.chunk_id and res.chunk_id not in cleaned else ""
        seq_note = f" (Trình tự: {' -> '.join(res.sequential_roles)})" if res.sequential_roles else ""
        self_note = " (Tự quyết)" if res.self_authorized and "tự quyết" not in auth_cf and "self" not in auth_cf else ""
        appr_line = f"**Thẩm quyền phê duyệt xác thực:** {auth}{self_note}{seq_note}{cite}"
        cleaned = f"{cleaned}\n\n{appr_line}".strip()
        changed = True
    return cleaned, changed


__all__ = [
    "ApprovalResolution",
    "ApprovalRuleRecord",
    "extract_approval_rules",
    "is_approval_query",
    "reconcile_approval_in_answer",
    "resolve_approval_authority",
]
