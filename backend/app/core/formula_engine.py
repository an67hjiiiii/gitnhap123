"""Structured Formula Selection & Unit-Checked Decimal Calculator (B139.2 Phase B + C).

Reuses `structured_evidence.py`, `operand_grounding.py`, and `answer_checks.fmt`.
Uses `Decimal` for monetary/exact arithmetic, restricted AST (never eval/exec),
and explicit status codes without inventing ungrounded business defaults.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import operator
import re
from typing import Any

from app.core.answer_checks import IMG_MARK
from app.core.operand_grounding import (
    _matches_conditions,
    are_units_compatible,
    derive_hourly_rate,
    ground_operand,
    verify_expression_grounding,
)
from app.core.structured_evidence import (
    EvidenceRole,
    StructuredEvidence,
    ValidationStatus,
    _EXAMPLE_MARKER,
    _PERIOD_UNIT_MAP,
    _infer_attribute,
    _infer_conditions,
    _is_table_separator,
    _table_cells,
    _tier_bounds_from_text,
    extract_structured_evidence,
    parse_localized_number,
)
from app.core.types import SourceChunk


class CalcStatus:
    VERIFIED = "VERIFIED"
    MISSING_OPERAND = "MISSING_OPERAND"
    INVALID_UNIT = "INVALID_UNIT"
    AMBIGUOUS_FORMULA = "AMBIGUOUS_FORMULA"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"


class FormulaType:
    ARITHMETIC = "ARITHMETIC"
    PERCENTAGE = "PERCENTAGE"
    DISCOUNT_WITH_FIXED_FEE = "DISCOUNT_WITH_FIXED_FEE"
    QUANTITY_UNIT_PRICE = "QUANTITY_UNIT_PRICE"
    TIERED_PRICING = "TIERED_PRICING"
    FIXED_PLUS_VARIABLE = "FIXED_PLUS_VARIABLE"
    TAX_OR_SURCHARGE = "TAX_OR_SURCHARGE"
    RATIO = "RATIO"
    AVERAGE = "AVERAGE"
    TIME_CONVERSION = "TIME_CONVERSION"
    UNIT_CONVERSION = "UNIT_CONVERSION"
    OVERTIME_PAY = "OVERTIME_PAY"
    MULTI_STEP = "MULTI_STEP"
    UNIT_MISMATCH_TEST = "UNIT_MISMATCH_TEST"


@dataclass
class TierBracket:
    label: str
    min_qty: float | int = 0
    max_qty: float | int | None = None
    min_inclusive: bool = True
    max_inclusive: bool = False
    unit_price: Decimal = Decimal("0")
    fixed_fee: Decimal = Decimal("0")
    unit: str = "VND/year"
    per_unit: bool = False


@dataclass
class FormulaSpec:
    intent: str
    formula_type: str
    required_operands: list[str] = field(default_factory=list)
    operand_roles: dict[str, str] = field(default_factory=dict)
    unit_constraints: dict[str, str] = field(default_factory=dict)
    applicability_conditions: list[str] = field(default_factory=list)
    evidence_references: list[str] = field(default_factory=list)
    calculation_steps: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    pre_status: str | None = None
    pre_reason: str = ""


@dataclass
class FormulaExecutionResult:
    status: str
    value: Decimal | None = None
    formatted_value: str = ""
    unit: str = ""
    currency: str = ""
    steps: list[str] = field(default_factory=list)
    evidence_references: list[str] = field(default_factory=list)
    reason: str = ""
    params: dict[str, Any] = field(default_factory=dict)


_MAX_AST_NODES = 64
_MAX_EXPONENT = Decimal("6")
_MAX_ABS_VAL = Decimal("1e15")

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
}


def _count_nodes(node: ast.AST) -> int:
    return 1 + sum(_count_nodes(child) for child in ast.iter_child_nodes(node))


def _eval_decimal_node(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval_decimal_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        d = Decimal(str(node.value))
        if abs(d) > _MAX_ABS_VAL:
            raise ValueError("numeric literal exceeds magnitude bound")
        return d
    if isinstance(node, ast.UnaryOp):
        v = _eval_decimal_node(node.operand)
        if isinstance(node.op, ast.UAdd):
            return v
        if isinstance(node.op, ast.USub):
            return -v
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.BinOp):
        left = _eval_decimal_node(node.left)
        right = _eval_decimal_node(node.right)
        if isinstance(node.op, ast.Pow):
            if right < Decimal("0") or right > _MAX_EXPONENT or right != int(right):
                raise ValueError("exponent out of safe bounds")
            res = left ** int(right)
        elif type(node.op) in _BIN_OPS:
            if isinstance(node.op, (ast.Div, ast.FloorDiv)) and right == 0:
                raise ZeroDivisionError("division by zero")
            res = _BIN_OPS[type(node.op)](left, right)
        else:
            raise ValueError(f"disallowed operator: {type(node.op).__name__}")
        if abs(res) > _MAX_ABS_VAL:
            raise OverflowError("intermediate result exceeds safe magnitude bound")
        return res
    raise ValueError(f"disallowed AST syntax: {type(node).__name__}")


def safe_eval_decimal_ast(expr: str) -> tuple[Decimal | None, str | None]:
    """Safely evaluate restricted Decimal arithmetic AST without ever calling eval/exec."""
    raw = (expr or "").strip()
    if not raw or len(raw) > 240:
        return None, "expression empty or exceeds length limit"
    if re.search(r"[A-Za-z_]", raw):
        return None, "identifiers/calls disallowed in arithmetic AST"
    try:
        tree = ast.parse(raw, mode="eval")
        if _count_nodes(tree) > _MAX_AST_NODES:
            return None, "expression exceeds maximum AST complexity"
        val = _eval_decimal_node(tree)
        # Normalize trailing fractional zeros neatly
        val_norm = val.normalize() if "." in str(val) else val
        if val_norm == val_norm.to_integral_value():
            val_norm = Decimal(int(val_norm))
        return val_norm, None
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, InvalidOperation) as exc:
        return None, str(exc)


def _fmt_dec(val: Decimal) -> str:
    """Clean decimal string for calculation step display without spurious trailing .0."""
    if val == val.to_integral_value():
        return str(int(val))
    return format(val.normalize(), "f").rstrip("0").rstrip(".")


def format_decimal(value: Decimal, currency: str = "") -> str:
    """Format Decimal in standard Vietnamese grouping (dot thousands, comma decimals)."""
    if value == value.to_integral_value():
        s = f"{int(value):,}".replace(",", ".")
    else:
        q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP).normalize()
        raw = format(q, "f").rstrip("0").rstrip(".") if "." in format(q, "f") else format(q, "f")
        if "." in raw:
            whole, frac = raw.split(".", 1)
            s = f"{int(whole):,}".replace(",", ".") + "," + frac
        else:
            s = f"{int(raw):,}".replace(",", ".")
    return f"{s} {currency}".strip() if currency else s


_TIER_QTY_RE = re.compile(
    r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s+(?:sinh viên|học viên|ghế|người dùng|người|tài khoản|tấn|kg|kiện|chuyến|users?|seats?|students?)\b",
    re.I,
)
_MINUTES_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:phút|minutes?|min)\b", re.I)
_OVERTIME_TYPE_RE = {
    "weekday": re.compile(r"(?:ngày thường|weekday)[^.\n;]{0,30}?(\d+(?:[.,]\d+)?)\s*(?:giờ|hours?|hrs?)|(\d+(?:[.,]\d+)?)\s*(?:giờ|hours?|hrs?)[^.\n;]{0,20}?(?:ngày thường|weekday)", re.I),
    "rest": re.compile(r"(?:nghỉ(?:\s+hằng)?\s*tuần|rest(?:\s+day)?)[^.\n;]{0,30}?(\d+(?:[.,]\d+)?)\s*(?:giờ|hours?|hrs?)|(\d+(?:[.,]\d+)?)\s*(?:giờ|hours?|hrs?)[^.\n;]{0,20}?(?:nghỉ(?:\s+hằng)?\s*tuần|rest(?:\s+day)?)", re.I),
    "holiday": re.compile(r"(?:ngày\s+(?:nghỉ\s+)?lễ|holiday)[^.\n;]{0,30}?(\d+(?:[.,]\d+)?)\s*(?:giờ|hours?|hrs?)|(\d+(?:[.,]\d+)?)\s*(?:giờ|hours?|hrs?)[^.\n;]{0,20}?(?:ngày\s+(?:nghỉ\s+)?lễ|holiday)", re.I),
}
_PCT_KIND_MAP = {
    "weekday": re.compile(r"(?:ngày thường|weekday)[^.\n;%]{0,60}?(\d+(?:[.,]\d+)?)\s*%", re.I),
    "rest": re.compile(r"(?:nghỉ(?:\s+hằng)?\s*tuần|rest)[^.\n;%]{0,60}?(\d+(?:[.,]\d+)?)\s*%", re.I),
    "holiday": re.compile(r"(?:ngày\s+(?:nghỉ\s+)?lễ|holiday)[^.\n;%]{0,80}?(\d+(?:[.,]\d+)?)\s*%", re.I),
}
_PER_UNIT_PERIOD_CUES = ("người dùng/", "tài khoản/", "user/", "account/", "seat/", "student/", "kg", "tấn")
_PERIOD_UNIT_CUES = {
    "sinh viên": ("sinh viên", "học viên", "student"),
    "tài khoản": ("tài khoản", "người dùng", "user", "seat"),
    "khối lượng": ("tấn", "kg"),
}


def _query_customer_conditions(query: str) -> set[str]:
    q = (query or "").casefold()
    conds: set[str] = set()
    if any(k in q for k in ("công lập", "bệnh viện công", "trường công", "cơ quan nhà nước", "public")):
        conds.add("public_institution")
    if any(k in q for k in ("tư nhân", "private")):
        conds.add("private_institution")
    if "phi lợi nhuận" in q or "nonprofit" in q or "non-profit" in q:
        conds.add("nonprofit")
    if "vip" in q:
        conds.add("vip_member")
    if "y tế tuyến tỉnh" in q:
        conds.add("provincial_health")
    if "3 năm" in q:
        conds.add("multi_year_3yr")
    return conds


def _extract_table_pricing_rows(chunks: list[SourceChunk], allowed_source_ids: set[str] | None) -> list[dict[str, Any]]:
    """Parse structured pricing & tier tables directly from Markdown pipe tables in authorized chunks."""
    rows: list[dict[str, Any]] = []
    for ch in chunks:
        if allowed_source_ids is not None and ch.source_id not in allowed_source_ids:
            continue
        lines = (ch.text or "").splitlines()
        headers: list[str] = []
        for idx, raw in enumerate(lines):
            ln = raw.strip()
            if not ln or "|" not in ln:
                headers = []
                continue
            if idx + 1 < len(lines) and _is_table_separator(lines[idx + 1].strip()):
                headers = _table_cells(ln)
                continue
            if _is_table_separator(ln) or not headers or _EXAMPLE_MARKER.search(ln):
                continue
            cells = _table_cells(ln)
            if len(cells) < 2:
                continue
            entity_base = cells[0]
            if entity_base.casefold() in {"sản phẩm", "dịch vụ", "tuyến", "mức chiết khấu trên giá niêm yết", "yêu cầu"}:
                continue
            tier_desc = ""
            unit_col_val = ""
            unit_price_val: Decimal | None = None
            fixed_fee_val = Decimal("0")
            currency = "VND"
            for ci, cell in enumerate(cells):
                hdr = headers[ci] if ci < len(headers) else ""
                hdr_cf = hdr.casefold()
                if re.search(r"\b(?:gói|phân hạng|hạng mục|hạng|trọng lượng|khối lượng|tier|plan|package)\b", hdr_cf):
                    tier_desc = cell
                elif re.search(r"(?:đơn giá|giá thuê bao|giá cước|cước vận chuyển|giá niêm yết|unit price|price)", hdr_cf):
                    m_cur = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)", cell)
                    if m_cur:
                        if "usd" in cell.casefold() or "$" in cell or "usd" in hdr_cf:
                            currency = "USD"
                        v, _, st = parse_localized_number(m_cur.group(1), locale_hint="en" if currency == "USD" else "vi", unit_hint="vnd")
                        if v is not None and st == ValidationStatus.VALIDATED:
                            unit_price_val = Decimal(str(v))
                elif re.search(r"\b(?:đơn vị tính|đơn vị|chu kỳ tính|billing\s*cycle|unit)\b", hdr_cf):
                    unit_col_val = cell.strip()
                elif re.search(r"(?:triển khai|cài đặt|cố định|khởi tạo|bảo hiểm|niêm phong|setup|fixed|one-time|một lần)", hdr_cf):
                    m_fx = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)", cell)
                    if m_fx:
                        fx_loc = "en" if ("usd" in cell.casefold() or "$" in cell or "usd" in hdr_cf or currency == "USD") else "vi"
                        v, _, st = parse_localized_number(m_fx.group(1), locale_hint=fx_loc, unit_hint="vnd")
                        if v is not None and st == ValidationStatus.VALIDATED:
                            fixed_fee_val = Decimal(str(v))
            if unit_price_val is None:
                continue
            tier_conds = _tier_bounds_from_text(tier_desc or entity_base)
            min_q: float = 0.0
            max_q: float | None = None
            min_inc = True
            max_inc = True
            for tc in tier_conds:
                if tc.startswith("min_qty="):
                    min_q = float(tc.split("=", 1)[1])
                elif tc.startswith("max_qty="):
                    max_q = float(tc.split("=", 1)[1])
                elif tc.startswith("min_inc="):
                    min_inc = tc.split("=", 1)[1] == "1"
                elif tc.startswith("max_inc="):
                    max_inc = tc.split("=", 1)[1] == "1"
            per_unit = any(cue in unit_col_val.casefold() for cue in _PER_UNIT_PERIOD_CUES)
            period_norm = _PERIOD_UNIT_MAP.get(unit_col_val.casefold(), unit_col_val.casefold())
            unit_str = f"{currency}/{period_norm}" if period_norm else f"{currency}/year"
            rows.append({
                "entity_base": entity_base,
                "tier_desc": tier_desc,
                "label": f"{entity_base} - {tier_desc}".strip(" -"),
                "bracket": TierBracket(
                    label=f"{entity_base} ({tier_desc})" if tier_desc else entity_base,
                    min_qty=min_q,
                    max_qty=max_q,
                    min_inclusive=min_inc,
                    max_inclusive=max_inc,
                    unit_price=unit_price_val,
                    fixed_fee=fixed_fee_val,
                    unit=unit_str,
                    per_unit=per_unit,
                ),
                "has_bounds": bool(tier_conds),
                "currency": currency,
                "chunk_id": ch.chunk_id,
                "source_id": ch.source_id,
                "tier_unit_hints": [
                    k for k in ("sinh viên", "học viên", "người dùng", "tài khoản", "tấn", "kg", "users", "seats")
                    if k in f"{tier_desc} {unit_col_val}".casefold()
                ],
            })
    return rows


def _collect_discount_rate(
    pool: list[StructuredEvidence],
    chunks: list[SourceChunk],
    query: str,
    *,
    allowed_source_ids: set[str] | None,
) -> tuple[Decimal, bool, str | None, str]:
    """Return `(discount_pct, applies_to_fixed_fee, status_override, reason)` for query conditions."""
    q_conds = _query_customer_conditions(query)
    q_cf = (query or "").casefold()
    authorized_text = "\n".join(
        c.text for c in chunks
        if (allowed_source_ids is None or c.source_id in allowed_source_ids)
    ).casefold()
    no_fixed_disc = bool(
        re.search(
            r"(?:không\s+(?:chiết khấu|giảm(?:\s+giá)?|áp dụng giảm)\s+[^.\n]*?(?:phí\s+(?:triển khai|cố định|kỹ sư|khởi tạo|niêm phong|bảo hiểm|cấu hình|cài đặt|di chuyển)|fixed fee)|"
            r"(?:setup|fixed|deployment|installation)\s+fee\s+(?:is\s+)?excluded|excludes?\s+(?:setup|fixed|deployment)\s+fee|on\s+unit\s+price\s+only)",
            authorized_text,
        )
    )
    disc_items = [
        it for it in pool
        if it.attribute == "discount_rate"
        and it.data_type == "percentage"
        and it.unit == "percent"
        and it.validation_status == ValidationStatus.VALIDATED
        and it.evidence_role not in {EvidenceRole.DOCUMENT_EXAMPLE, EvidenceRole.UNKNOWN}
        and (allowed_source_ids is None or it.source_id in {"user_input", "derived"} or it.source_id in allowed_source_ids)
    ]
    matched: list[StructuredEvidence] = []
    for it in disc_items:
        iconds = {c for c in it.applicable_conditions if not c.startswith(("min_", "max_")) and c != "excludes_fixed_fee"}
        # Check customer-group and multi-year constraints strictly
        if "multi_year_3yr" in iconds and "multi_year_3yr" not in q_conds:
            continue
        group_conds = iconds & {"public_institution", "private_institution", "nonprofit", "vip_member", "provincial_health"}
        if group_conds and not (group_conds & q_conds):
            continue
        if it.entity and it.entity.casefold() not in q_cf and not any(tok in q_cf for tok in it.entity.casefold().split("|")[0].split() if len(tok) >= 3):
            continue
        matched.append(it)

    if not matched:
        group_q_conds = q_conds & {"public_institution", "private_institution", "nonprofit", "vip_member", "provincial_health"}
        asks_policy_disc = bool(
            group_q_conds
            or re.search(r"(?:chính\s+sách\s+(?:công\s+lập|ưu\s+đãi|chiết\s+khấu|giảm\s+giá)|ưu\s+đãi\s+phi\s+lợi\s+nhuận|ngoài\s+chính\s+sách)", q_cf)
        )
        # Fail closed when query invokes a group/discount policy that is absent from retrieved authorized rules
        if asks_policy_disc and not re.search(r"(?:không\s+(?:có|áp\s+dụng)\s+(?:chiết\s+khấu|giảm\s+giá)|0\s*%)", authorized_text):
            return (
                Decimal("0"),
                False,
                CalcStatus.MISSING_OPERAND,
                "customer-group discount policy missing from retrieved evidence",
            )
        return Decimal("0"), (not no_fixed_disc), None, ""
    distinct = {Decimal(str(it.value)) for it in matched}
    if len(distinct) > 1:
        # Conflict across multiple official discount rules matching the same scope
        return Decimal("0"), False, CalcStatus.CONFLICT, f"conflicting official discount rates: {sorted(str(x) for x in distinct)}"
    if any("excludes_fixed_fee" in it.applicable_conditions for it in matched):
        no_fixed_disc = True
    return next(iter(distinct)), (not no_fixed_disc), None, ""


def _match_tier(qty: float, brackets: list[TierBracket]) -> TierBracket | None:
    for b in brackets:
        lo_ok = qty >= b.min_qty if b.min_inclusive else qty > b.min_qty
        if b.max_qty is None:
            hi_ok = True
        else:
            hi_ok = qty <= b.max_qty if b.max_inclusive else qty < b.max_qty
        if lo_ok and hi_ok:
            return b
    return None


def select_formula(
    query: str,
    *,
    chunks: list[SourceChunk] | None = None,
    allowed_source_ids: set[str] | None = None,
    formula: str | None = None,
    **kwargs: Any,
) -> FormulaSpec:
    """Select an evidence-grounded formula spec, or mark missing/ambiguous/conflicting status explicitly."""
    chunks = chunks or []
    pool = extract_structured_evidence(chunks, query=query, allowed_source_ids=allowed_source_ids)
    q_cf = (query or "").casefold()
    chunk_text = "\n".join(c.text for c in chunks)
    refs = [c.chunk_id for c in chunks]

    # 1. Explicit unit-mismatch probe / guardrail mode
    if formula == FormulaType.UNIT_MISMATCH_TEST:
        left_u = str(kwargs.get("left_unit") or "VND/day")
        right_u = str(kwargs.get("right_unit") or "hour")
        valid = are_units_compatible("VND/hour", "VND/hour") and not (left_u in {"VND/day", "VND/month"} and right_u == "hour")
        return FormulaSpec(
            intent="unit_compatibility_check",
            formula_type=FormulaType.UNIT_MISMATCH_TEST,
            unit_constraints={"left": left_u, "right": right_u},
            evidence_references=refs,
            pre_status=CalcStatus.VERIFIED if valid else CalcStatus.INVALID_UNIT,
            pre_reason=f"incompatible units: {left_u} * {right_u}",
        )

    # 2. Ambiguity guard (e.g., VAT inclusive vs exclusive asked without resolving which applies)
    if ("chưa gồm" in chunk_text.casefold() and "đã gồm" in chunk_text.casefold()) and ("hay" in q_cf or "or" in q_cf):
        return FormulaSpec(
            intent="tax_calculation",
            formula_type=FormulaType.TAX_OR_SURCHARGE,
            evidence_references=refs,
            pre_status=CalcStatus.AMBIGUOUS_FORMULA,
            pre_reason="two tax interpretations present (tax-exclusive vs tax-inclusive) without disambiguation",
        )

    # 3. Overtime Pay (monthly -> daily -> hourly OR direct hourly rate)
    if formula == FormulaType.OVERTIME_PAY or any(k in q_cf for k in ("làm thêm", "tăng ca", "overtime")):
        sal_m = ground_operand(pool, attribute="salary_monthly", target_unit="VND/month", allowed_source_ids=allowed_source_ids)
        sal_d = ground_operand(pool, attribute="salary_daily", target_unit="VND/day", allowed_source_ids=allowed_source_ids)
        wd = ground_operand(pool, attribute="workdays_per_month", target_unit="working_day", allowed_source_ids=allowed_source_ids)
        active_hpd_conds: list[str] = []
        if any(k in q_cf for k in ("chưa thành niên", "dưới 15", "dưới 18", "minor")):
            active_hpd_conds.append("minor_worker")
        if any(k in q_cf for k in ("nặng nhọc", "độc hại", "nguy hiểm", "hazardous")):
            active_hpd_conds.append("hazardous_work")
        if any(k in q_cf for k in ("theo tuần", "ca theo tuần", "weekly", "per week")):
            active_hpd_conds.append("weekly_schedule")
        hpd = ground_operand(
            pool,
            attribute="hours_per_day",
            target_unit="hour/day",
            active_conditions=active_hpd_conds or None,
            allowed_source_ids=allowed_source_ids,
        )
        hourly = ground_operand(pool, attribute="hourly_rate", target_unit="VND/hour", allowed_source_ids=allowed_source_ids)

        case_text = query
        query_ent = ""
        for ev_it in pool:
            if ev_it.attribute == "hourly_rate" and ev_it.entity and ev_it.entity.casefold() in q_cf:
                query_ent = ev_it.entity
                break
        if query_ent:
            hourly = ground_operand(pool, attribute="hourly_rate", entity=query_ent, target_unit="VND/hour", allowed_source_ids=allowed_source_ids)

        # Distinguish actual contractual hours vs statutory maximums when multiple statutory scopes (e.g. 8h daily vs 10h weekly) exist
        all_hpd = [
            it for it in pool
            if it.attribute == "hours_per_day"
            and it.validation_status == ValidationStatus.VALIDATED
            and _matches_conditions(it, active_hpd_conds or None)
            and (allowed_source_ids is None or it.source_id in {"user_input", "derived"} or it.source_id in allowed_source_ids)
        ]
        stat_max_all = [
            it for it in pool
            if it.attribute == "hours_per_day"
            and it.validation_status == ValidationStatus.VALIDATED
            and "statutory_max" in it.applicable_conditions
            and not (({"minor_worker", "hazardous_work"} & set(it.applicable_conditions)) - set(active_hpd_conds))
            and (allowed_source_ids is None or it.source_id in {"user_input", "derived"} or it.source_id in allowed_source_ids)
        ]
        has_actual_hpd = any("actual_schedule" in it.applicable_conditions for it in all_hpd)
        multi_stat_hpd = (not active_hpd_conds) and (len({str(it.value) for it in stat_max_all}) > 1)

        if sal_m.status == ValidationStatus.VALIDATED and wd.status == ValidationStatus.VALIDATED and (has_actual_hpd or not multi_stat_hpd):
            if hpd.status != ValidationStatus.VALIDATED:
                return FormulaSpec(
                    intent="overtime_pay",
                    formula_type=FormulaType.OVERTIME_PAY,
                    required_operands=["salary_monthly", "workdays_per_month", "hours_per_day"],
                    evidence_references=refs,
                    pre_status=CalcStatus.MISSING_OPERAND,
                    pre_reason="missing actual_hours_per_day evidence (refusing silent /8 assumption)",
                    params={"oracle_review_required": True, "formula_template": f"({format_decimal(Decimal(str(sal_m.operand_value)))} / {_fmt_dec(Decimal(str(wd.operand_value)))} / actual_hours_per_day) * weighted_overtime_hours"},
                )
            _, drv_res = derive_hourly_rate(
                pool,
                hours_per_day=float(hpd.operand_value),
                workdays_per_month=float(wd.operand_value),
                allowed_source_ids=allowed_source_ids,
            )
            if drv_res.status != ValidationStatus.VALIDATED:
                return FormulaSpec(
                    intent="overtime_pay",
                    formula_type=FormulaType.OVERTIME_PAY,
                    evidence_references=refs,
                    pre_status=CalcStatus.MISSING_OPERAND,
                    pre_reason=drv_res.reason,
                )
            hourly_rate = Decimal(str(sal_m.operand_value)) / Decimal(str(wd.operand_value)) / Decimal(str(hpd.operand_value))
            rate_refs = [sal_m.chunk_id, wd.chunk_id, hpd.chunk_id]
            rate_step = f"hourly_rate = {_fmt_dec(Decimal(str(sal_m.operand_value)))} / {_fmt_dec(Decimal(str(wd.operand_value)))} / {_fmt_dec(Decimal(str(hpd.operand_value)))} = {_fmt_dec(hourly_rate)} VND/hour"
        elif hourly.status == ValidationStatus.VALIDATED:
            hourly_rate = Decimal(str(hourly.operand_value))
            rate_refs = [hourly.chunk_id]
            rate_step = f"Hourly rate from company evidence [{hourly.chunk_id}] = {_fmt_dec(hourly_rate)} VND/hour"
        elif sal_m.status == ValidationStatus.VALIDATED and wd.status == ValidationStatus.VALIDATED and multi_stat_hpd and not has_actual_hpd:
            return FormulaSpec(
                intent="overtime_pay",
                formula_type=FormulaType.OVERTIME_PAY,
                required_operands=["salary_monthly", "workdays_per_month", "actual_hours_per_day"],
                evidence_references=refs,
                pre_status=CalcStatus.MISSING_OPERAND,
                pre_reason="multiple statutory maximums (8h daily / 10h weekly) found without actual_hours_per_day schedule (ORACLE_REVIEW_REQUIRED)",
                params={
                    "oracle_review_required": True,
                    "formula_template": f"({format_decimal(Decimal(str(sal_m.operand_value)))} / {_fmt_dec(Decimal(str(wd.operand_value)))} / actual_hours_per_day) * weighted_overtime_hours",
                },
            )
        elif sal_d.status == ValidationStatus.VALIDATED:
            if hpd.status != ValidationStatus.VALIDATED or (not has_actual_hpd and any("statutory_max" in it.applicable_conditions for it in all_hpd)):
                return FormulaSpec(
                    intent="overtime_pay",
                    formula_type=FormulaType.OVERTIME_PAY,
                    required_operands=["salary_daily", "actual_hours_per_day"],
                    evidence_references=refs,
                    pre_status=CalcStatus.MISSING_OPERAND,
                    pre_reason="missing actual_hours_per_day evidence (statutory maximum does not establish actual schedule)",
                    params={"oracle_review_required": True, "formula_template": f"({_fmt_dec(Decimal(str(sal_d.operand_value)))} / actual_hours_per_day) * weighted_overtime_hours"},
                )
            hourly_rate = Decimal(str(sal_d.operand_value)) / Decimal(str(hpd.operand_value))
            rate_refs = [sal_d.chunk_id, hpd.chunk_id]
            rate_step = f"hourly_rate = {_fmt_dec(Decimal(str(sal_d.operand_value)))} / {_fmt_dec(Decimal(str(hpd.operand_value)))} = {_fmt_dec(hourly_rate)} VND/hour"
        else:
            return FormulaSpec(
                intent="overtime_pay",
                formula_type=FormulaType.OVERTIME_PAY,
                evidence_references=refs,
                pre_status=CalcStatus.MISSING_OPERAND,
                pre_reason="missing salary/hourly rate or workdays evidence",
            )

        weighted_hours = Decimal("0")
        ot_steps = [rate_step]
        found_ot = False
        for kind, pat in _OVERTIME_TYPE_RE.items():
            m = pat.search(case_text)
            if not m:
                continue
            raw_h = m.group(1) or m.group(2)
            hrs = Decimal(raw_h.replace(",", "."))
            if hrs == 0:
                continue
            found_ot = True
            pm = _PCT_KIND_MAP[kind].search(chunk_text)
            if not pm:
                return FormulaSpec(
                    intent="overtime_pay",
                    formula_type=FormulaType.OVERTIME_PAY,
                    evidence_references=refs,
                    pre_status=CalcStatus.MISSING_OPERAND,
                    pre_reason=f"missing overtime multiplier percentage for {kind}",
                )
            pct = Decimal(pm.group(1).replace(",", ".")) / Decimal("100")
            part = hourly_rate * hrs * pct
            weighted_hours += part
            ot_steps.append(f"{kind}: {hourly_rate} * {hrs}h * {pct} = {part} VND")

        if not found_ot:
            return FormulaSpec(
                intent="overtime_pay",
                formula_type=FormulaType.OVERTIME_PAY,
                evidence_references=refs,
                pre_status=CalcStatus.MISSING_OPERAND,
                pre_reason="no overtime hours found in query/OCR",
            )
        return FormulaSpec(
            intent="overtime_pay",
            formula_type=FormulaType.OVERTIME_PAY,
            required_operands=["hourly_rate", "overtime_hours", "overtime_multiplier"],
            unit_constraints={"rate": "VND/hour", "time": "hour", "output": "VND"},
            evidence_references=list(dict.fromkeys([*rate_refs, *refs])),
            calculation_steps=ot_steps,
            params={"verified_value": weighted_hours, "unit": "VND", "currency": "VND"},
        )

    # 4. Time conversion + hourly rate ("Quy đổi N phút sang giờ và tính phí...")
    if (formula == FormulaType.TIME_CONVERSION) or ("phút" in q_cf and ("giờ" in q_cf or "hour" in q_cf)):
        mm = _MINUTES_RE.search(query)
        rate_ev = ground_operand(pool, target_unit="VND/hour", allowed_source_ids=allowed_source_ids)
        if mm and rate_ev.status == ValidationStatus.VALIDATED:
            mins = Decimal(mm.group(1).replace(",", "."))
            hrs = mins / Decimal("60")
            rate_val = Decimal(str(rate_ev.operand_value))
            return FormulaSpec(
                intent="time_conversion_fee",
                formula_type=FormulaType.TIME_CONVERSION,
                required_operands=["minutes", "hourly_rate"],
                unit_constraints={"time": "minute->hour", "rate": "VND/hour", "output": "VND"},
                evidence_references=refs,
                calculation_steps=[f"{mins} min / 60 = {hrs} hour", f"{hrs} hour * {rate_val} VND/hour = {hrs * rate_val} VND"],
                params={"verified_value": hrs * rate_val, "unit": "VND", "currency": "VND"},
            )

    # 5. Tiered Pricing (explicit brackets)
    if formula == FormulaType.TIERED_PRICING or "tier_brackets" in kwargs:
        brackets: list[TierBracket] = kwargs.get("tier_brackets") or []
        qty = kwargs.get("quantity")
        if qty is None:
            qm = _TIER_QTY_RE.search(query)
            if qm:
                v, _, st = parse_localized_number(qm.group(1), locale_hint="vi", unit_hint=qm.group(0))
                if v is not None and st == ValidationStatus.VALIDATED:
                    qty = Decimal(str(v))
        if qty is None or not brackets:
            return FormulaSpec(intent="tiered_pricing", formula_type=FormulaType.TIERED_PRICING, evidence_references=refs, pre_status=CalcStatus.MISSING_OPERAND, pre_reason="missing quantity or tier brackets")
        matched = _match_tier(float(qty), brackets)
        if matched is None:
            return FormulaSpec(intent="tiered_pricing", formula_type=FormulaType.TIERED_PRICING, evidence_references=refs, pre_status=CalcStatus.UNSUPPORTED, pre_reason=f"no tier matches quantity {qty}")
        disc = Decimal(str(kwargs.get("discount_pct", 0))) / Decimal("100")
        apply_fixed = bool(kwargs.get("discount_applies_to_fixed_fee", False))
        base = (matched.unit_price * Decimal(str(qty))) if matched.per_unit else matched.unit_price
        disc_base = base * (Decimal("1") - disc)
        fixed = matched.fixed_fee * (Decimal("1") - disc) if apply_fixed else matched.fixed_fee
        total = disc_base + fixed
        cur = "USD" if "USD" in matched.unit else "VND"
        return FormulaSpec(
            intent="tiered_pricing",
            formula_type=FormulaType.TIERED_PRICING,
            required_operands=["quantity", "tier_unit_price", "fixed_fee", "discount_rate"],
            evidence_references=refs,
            calculation_steps=[
                f"Matched tier '{matched.label}' for qty={qty}: base={base} {cur}",
                f"Apply discount {disc * 100}% to base only ({apply_fixed=}): {disc_base} {cur}",
                f"Add fixed fee {fixed} {cur} => total = {total} {cur}",
            ],
            params={"verified_value": total, "unit": cur, "currency": cur},
        )

    # 5b. Automated Table-Aware Tiered + Fixed Fee + Discount Selection (zero manual kwargs!)
    if not kwargs and any(k in q_cf for k in ("tổng tiền", "tổng chi phí", "tổng cộng", "chi phí", "giá", "gói", "hợp đồng", "cước", "lô", "tuyến", "thuê bao", "phí", "total cost", "cost", "price", "fee", "order")):
        table_rows = _extract_table_pricing_rows(chunks, allowed_source_ids)
        if table_rows:
            matched_rows = [r for r in table_rows if r["entity_base"].casefold() in q_cf]
            if not matched_rows and len({r["entity_base"].casefold() for r in table_rows}) == 1:
                matched_rows = table_rows
            if matched_rows:
                # Further narrow by explicit non-bounded tier name if query mentions it (e.g. "Cơ bản" vs "Doanh nghiệp")
                named = [r for r in matched_rows if r["tier_desc"] and not r["has_bounds"] and r["tier_desc"].casefold() in q_cf]
                if named:
                    matched_rows = named
                brackets_auto = [r["bracket"] for r in matched_rows]
                qm = _TIER_QTY_RE.search(query)
                qty_val: Decimal | None = None
                if qm:
                    qv, _, qst = parse_localized_number(qm.group(1), locale_hint="vi", unit_hint=qm.group(0))
                    if qv is not None and qst == ValidationStatus.VALIDATED:
                        qty_val = Decimal(str(qv))
                if len(brackets_auto) > 1 and any(r["has_bounds"] for r in matched_rows):
                    if qty_val is None:
                        return FormulaSpec(
                            intent="tiered_pricing",
                            formula_type=FormulaType.TIERED_PRICING,
                            evidence_references=refs,
                            pre_status=CalcStatus.AMBIGUOUS_FORMULA,
                            pre_reason="multiple pricing tiers exist without quantity to disambiguate tier",
                        )
                    chosen_bracket = _match_tier(float(qty_val), brackets_auto)
                    if chosen_bracket is None:
                        return FormulaSpec(
                            intent="tiered_pricing",
                            formula_type=FormulaType.TIERED_PRICING,
                            evidence_references=refs,
                            pre_status=CalcStatus.UNSUPPORTED,
                            pre_reason=f"no tier matches quantity {qty_val}",
                        )
                    matched_row = next(r for r in matched_rows if r["bracket"] is chosen_bracket)
                elif len(matched_rows) == 1:
                    matched_row = matched_rows[0]
                    chosen_bracket = matched_row["bracket"]
                else:
                    matched_row = None
                    chosen_bracket = None

                if matched_row is not None and chosen_bracket is not None:
                    disc_pct, apply_fixed, st_ovr, disc_reason = _collect_discount_rate(
                        pool, chunks, query, allowed_source_ids=allowed_source_ids
                    )
                    if st_ovr:
                        return FormulaSpec(intent="tiered_pricing", formula_type=FormulaType.TIERED_PRICING, evidence_references=refs, pre_status=st_ovr, pre_reason=disc_reason)
                    q_effective = qty_val if (chosen_bracket.per_unit and qty_val is not None) else Decimal("1")
                    if chosen_bracket.per_unit and qty_val is None:
                        return FormulaSpec(intent="tiered_pricing", formula_type=FormulaType.TIERED_PRICING, evidence_references=refs, pre_status=CalcStatus.MISSING_OPERAND, pre_reason="per-unit pricing requires quantity")
                    base = (chosen_bracket.unit_price * q_effective) if chosen_bracket.per_unit else chosen_bracket.unit_price
                    disc_base = base * (Decimal("1") - disc_pct / Decimal("100"))
                    include_fixed = chosen_bracket.fixed_fee > 0 and (
                        any(k in q_cf for k in ("triển khai", "cố định", "khởi tạo", "niêm phong", "bảo hiểm", "gồm phí", "kèm phí", "năm đầu"))
                        or not any(k in q_cf for k in ("không gồm", "chưa gồm"))
                    )
                    fixed = (chosen_bracket.fixed_fee * (Decimal("1") - disc_pct / Decimal("100")) if apply_fixed else chosen_bracket.fixed_fee) if include_fixed else Decimal("0")
                    total = disc_base + fixed
                    cur = matched_row["currency"]
                    return FormulaSpec(
                        intent="tiered_pricing",
                        formula_type=FormulaType.TIERED_PRICING,
                        required_operands=["tier_unit_price", "fixed_fee", "discount_rate"],
                        evidence_references=list(dict.fromkeys([matched_row["chunk_id"], *refs])),
                        calculation_steps=[
                            f"Selected table tier '{chosen_bracket.label}': base={_fmt_dec(base)} {cur}",
                            f"Apply discount {_fmt_dec(disc_pct)}% (apply_to_fixed={apply_fixed}): discounted_base={_fmt_dec(disc_base)} {cur}",
                            f"Add fixed fee {_fmt_dec(fixed)} {cur} => total = {_fmt_dec(total)} {cur}",
                        ],
                        params={
                            "verified_value": total, "unit": cur, "currency": cur,
                            "base": base, "discount_pct": disc_pct, "fixed": fixed, "total": total,
                        },
                    )

    # 6. Discount + Fixed/Variable Fees from Bullet Lists & Prose (structural parameters OR evidence-extracted)
    if formula == FormulaType.DISCOUNT_WITH_FIXED_FEE or (not kwargs and (
        any(k in q_cf for k in ("chiết khấu", "giảm", "discount", "tổng tiền", "tổng chi phí", "tổng cộng", "hết bao nhiêu"))
    )):
        if kwargs:
            up = Decimal(str(kwargs["unit_price"]))
            q_val = Decimal(str(kwargs.get("quantity", 1)))
            disc_pct = Decimal(str(kwargs.get("discount_pct", 0)))
            fixed = Decimal(str(kwargs.get("fixed_fee", 0)))
            apply_fixed = bool(kwargs.get("discount_applies_to_fixed_fee", False))
            base = up * q_val * (Decimal("1") - disc_pct / Decimal("100"))
            fixed_part = fixed * (Decimal("1") - disc_pct / Decimal("100")) if apply_fixed else fixed
            total = base + fixed_part
            return FormulaSpec(
                intent="discount_with_fixed_fee",
                formula_type=FormulaType.DISCOUNT_WITH_FIXED_FEE,
                evidence_references=refs,
                calculation_steps=[f"{up} * {q_val} * (1 - {disc_pct}%) = {base}", f"+ fixed fee {fixed_part} = {total}"],
                params={"verified_value": total, "unit": "VND", "currency": "VND"},
            )

        q_conds = _query_customer_conditions(query)
        disc_pct, apply_fixed, st_ovr, disc_reason = _collect_discount_rate(
            pool, chunks, query, allowed_source_ids=allowed_source_ids
        )
        if st_ovr:
            return FormulaSpec(intent="discount", formula_type=FormulaType.DISCOUNT_WITH_FIXED_FEE, evidence_references=refs, pre_status=st_ovr, pre_reason=disc_reason)

        authorized_pool = [
            it for it in pool
            if it.validation_status == ValidationStatus.VALIDATED
            and it.data_type == "currency"
            and it.source_id != "user_input"
            and it.evidence_role not in {EvidenceRole.DOCUMENT_EXAMPLE, EvidenceRole.UNKNOWN}
            and (allowed_source_ids is None or it.source_id in allowed_source_ids)
        ]
        # Candidate base unit prices
        price_cands = [it for it in authorized_pool if it.attribute == "unit_price" and isinstance(it.value, (int, float))]
        # Filter by entity match if multiple distinct entities exist
        ent_matched_prices = [
            it for it in price_cands
            if it.entity and (it.entity.casefold() in q_cf or any(tok in q_cf for tok in it.entity.casefold().split("|")[0].split() if len(tok) >= 3))
        ]
        if ent_matched_prices:
            price_cands = ent_matched_prices

        # Filter by customer-group condition (e.g. Cơ quan nhà nước vs Doanh nghiệp tư nhân) cleanly!
        group_keys = {"public_institution", "private_institution", "nonprofit", "vip_member", "provincial_health"}
        any_grouped = any(set(it.applicable_conditions) & group_keys for it in price_cands)
        if any_grouped:
            group_matched = [
                it for it in price_cands
                if (set(it.applicable_conditions) & group_keys) and ((set(it.applicable_conditions) & group_keys) <= q_conds)
            ]
            if group_matched:
                price_cands = group_matched
            elif not (q_conds & group_keys) and len({str(it.value) for it in price_cands}) > 1:
                return FormulaSpec(
                    intent="discount_with_fixed_fee",
                    formula_type=FormulaType.DISCOUNT_WITH_FIXED_FEE,
                    evidence_references=refs,
                    pre_status=CalcStatus.AMBIGUOUS_FORMULA,
                    pre_reason="multiple customer-group rates exist without customer group in query",
                )

        if not price_cands:
            return FormulaSpec(intent="discount", formula_type=FormulaType.DISCOUNT_WITH_FIXED_FEE, evidence_references=refs, pre_status=CalcStatus.MISSING_OPERAND, pre_reason="no authorized unit_price evidence found")
        distinct_prices = {Decimal(str(it.value)) for it in price_cands}
        if len(distinct_prices) > 1:
            return FormulaSpec(
                intent="discount",
                formula_type=FormulaType.DISCOUNT_WITH_FIXED_FEE,
                evidence_references=refs,
                pre_status=CalcStatus.CONFLICT,
                pre_reason=f"conflicting unit_price values: {sorted(str(x) for x in distinct_prices)}",
            )

        chosen_price = price_cands[0]
        up = Decimal(str(chosen_price.value))
        cur = chosen_price.currency or "VND"

        # Fixed / one-time fees mentioned alongside or requested in query
        fixed_total = Decimal("0")
        fixed_refs: list[str] = []
        fixed_steps: list[str] = []
        fixed_cands = [
            it for it in authorized_pool
            if it.attribute in {"fixed_fee", "deployment_fee"} and isinstance(it.value, (int, float))
        ]
        # Avoid double counting same value/line; add matching fixed fee(s) whose descriptive keywords appear in query (e.g. "kỹ sư", "cấu hình", "cài đặt", "triển khai")
        seen_fx_spans: set[tuple[str, str]] = set()
        for fx in fixed_cands:
            if (fx.chunk_id, str(fx.value)) in seen_fx_spans:
                continue
            span_ctx = " ".join(w for w in re.findall(r"[^\W\d_]{2,}", f"{fx.source_span} {fx.attribute}".casefold()) if len(w) >= 2)
            # Check query against full chunk line containing fixed fee
            fx_line = next((ln for ln in chunk_text.splitlines() if fx.source_span in ln), fx.source_span).casefold()
            fx_kws = {w for w in re.findall(r"[^\W\d_]{2,}", fx_line) if w not in {"phí", "đồng", "vnd", "lần", "cố", "định", "không", "giảm", "giá", "áp", "dụng"}}
            if any(w in q_cf for w in fx_kws) or any(k in q_cf for k in ("triển khai", "cài đặt", "cấu hình", "kỹ sư", "kiểm tra", "kèm")):
                fx_val = Decimal(str(fx.value))
                # Optional multiplier like "2 lần cử kỹ sư" or "1 lượt"
                m_rep = re.search(r"(\d+)\s*(?:lần|lượt)", q_cf)
                rep = Decimal(m_rep.group(1)) if (m_rep and ("/lần" in fx_line or "/lượt" in fx_line)) else Decimal("1")
                fx_amt = fx_val * rep
                fx_eff = fx_amt * (Decimal("1") - disc_pct / Decimal("100")) if apply_fixed else fx_amt
                fixed_total += fx_eff
                fixed_refs.append(fx.chunk_id)
                fixed_steps.append(f"+ fixed fee {_fmt_dec(fx_amt)} {cur} (discounted={apply_fixed}) = {_fmt_dec(fx_eff)} {cur}")
                seen_fx_spans.add((fx.chunk_id, str(fx.value)))

        disc_base = up * (Decimal("1") - disc_pct / Decimal("100"))
        total = disc_base + fixed_total
        return FormulaSpec(
            intent="discount_calculation",
            formula_type=FormulaType.DISCOUNT_WITH_FIXED_FEE,
            evidence_references=list(dict.fromkeys([chosen_price.chunk_id, *fixed_refs])),
            calculation_steps=[f"{_fmt_dec(up)} {cur} * (1 - {_fmt_dec(disc_pct)}%) = {_fmt_dec(disc_base)} {cur}", *fixed_steps, f"total = {_fmt_dec(total)} {cur}"],
            params={
                "verified_value": total, "unit": cur, "currency": cur,
                "base": up, "discount_pct": disc_pct, "fixed": fixed_total, "total": total,
            },
        )

    # 7. Tax / Surcharge
    if formula == FormulaType.TAX_OR_SURCHARGE:
        base = Decimal(str(kwargs["base"]))
        tax = Decimal(str(kwargs["tax_pct"]))
        total = base * (Decimal("1") + tax / Decimal("100"))
        cur = str(kwargs.get("currency") or "VND")
        return FormulaSpec(intent="tax_or_surcharge", formula_type=FormulaType.TAX_OR_SURCHARGE, evidence_references=refs, calculation_steps=[f"{base} * (1 + {tax}%) = {total}"], params={"verified_value": total, "unit": cur, "currency": cur})

    # 8. Average (simple or weighted)
    if formula == FormulaType.AVERAGE:
        vals = [Decimal(str(v)) for v in (kwargs.get("values") or [])]
        weights = [Decimal(str(w)) for w in (kwargs.get("weights") or [])]
        unit = str(kwargs.get("unit") or "")
        if not vals:
            return FormulaSpec(intent="average", formula_type=FormulaType.AVERAGE, pre_status=CalcStatus.MISSING_OPERAND, pre_reason="empty values list")
        if weights:
            if len(weights) != len(vals) or sum(weights) == 0:
                return FormulaSpec(intent="average", formula_type=FormulaType.AVERAGE, pre_status=CalcStatus.UNSUPPORTED, pre_reason="invalid weights")
            avg = sum(v * w for v, w in zip(vals, weights)) / sum(weights)
        else:
            avg = sum(vals) / Decimal(len(vals))
        return FormulaSpec(intent="average", formula_type=FormulaType.AVERAGE, evidence_references=refs, calculation_steps=[f"average = {avg}"], params={"verified_value": avg, "unit": unit})

    # 9. Ratio
    if formula == FormulaType.RATIO:
        num = Decimal(str(kwargs["numerator"]))
        den = Decimal(str(kwargs["denominator"]))
        if den == 0:
            return FormulaSpec(intent="ratio", formula_type=FormulaType.RATIO, pre_status=CalcStatus.UNSUPPORTED, pre_reason="division by zero")
        val = (num / den) * (Decimal("100") if kwargs.get("as_percent") else Decimal("1"))
        return FormulaSpec(intent="ratio", formula_type=FormulaType.RATIO, evidence_references=refs, calculation_steps=[f"{num} / {den} = {val}"], params={"verified_value": val, "unit": "percent" if kwargs.get("as_percent") else ""})

    # 10. Generic Unit Conversion
    if formula == FormulaType.UNIT_CONVERSION:
        amt = Decimal(str(kwargs["amount"]))
        fac = Decimal(str(kwargs["factor"]))
        to_u = str(kwargs.get("to_unit") or "")
        res_v = amt * fac
        return FormulaSpec(intent="unit_conversion", formula_type=FormulaType.UNIT_CONVERSION, evidence_references=refs, calculation_steps=[f"{amt} {kwargs.get('from_unit')} * {fac} = {res_v} {to_u}"], params={"verified_value": res_v, "unit": to_u})

    # 11. Multi-step restricted Decimal AST
    if formula == FormulaType.MULTI_STEP or "steps_expr" in kwargs:
        expr = str(kwargs.get("steps_expr") or "")
        cur = str(kwargs.get("currency") or kwargs.get("unit") or "")
        unit = str(kwargs.get("unit") or cur)
        val, err = safe_eval_decimal_ast(expr)
        if val is None:
            return FormulaSpec(intent="multi_step_ast", formula_type=FormulaType.MULTI_STEP, evidence_references=refs, pre_status=CalcStatus.UNSUPPORTED, pre_reason=err or "AST evaluation failed")
        return FormulaSpec(intent="multi_step_ast", formula_type=FormulaType.MULTI_STEP, evidence_references=refs, calculation_steps=[f"{expr} = {val}"], params={"verified_value": val, "unit": unit, "currency": cur if cur in {"VND", "USD"} else ""})

    return FormulaSpec(
        intent="unmatched",
        formula_type=formula or FormulaType.ARITHMETIC,
        evidence_references=refs,
        pre_status=CalcStatus.MISSING_OPERAND,
        pre_reason="insufficient structured operands to select formula",
    )


def execute_formula(spec: FormulaSpec) -> FormulaExecutionResult:
    """Execute a selected `FormulaSpec` deterministically using Decimal arithmetic and unit checks."""
    if spec.pre_status is not None and spec.pre_status != CalcStatus.VERIFIED:
        return FormulaExecutionResult(
            status=spec.pre_status,
            evidence_references=spec.evidence_references,
            reason=spec.pre_reason,
            params=dict(spec.params),
        )
    val = spec.params.get("verified_value")
    if val is None:
        return FormulaExecutionResult(
            status=CalcStatus.MISSING_OPERAND,
            evidence_references=spec.evidence_references,
            reason=spec.pre_reason or "missing computed value",
            params=dict(spec.params),
        )
    dec_val = val if isinstance(val, Decimal) else Decimal(str(val))
    if dec_val == dec_val.to_integral_value():
        dec_val = Decimal(int(dec_val))
    else:
        dec_val = dec_val.normalize()
    cur = str(spec.params.get("currency") or "")
    unit = str(spec.params.get("unit") or cur)
    return FormulaExecutionResult(
        status=CalcStatus.VERIFIED,
        value=dec_val,
        formatted_value=format_decimal(dec_val, cur),
        unit=unit,
        currency=cur,
        steps=spec.calculation_steps,
        evidence_references=spec.evidence_references,
        reason="verified deterministic Decimal calculation",
        params=dict(spec.params),
    )
