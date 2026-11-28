"""Structured Evidence Schema & Deterministic Bilingual Extractor (B139.1 Phase A + B).

Reuses `SourceChunk` and `answer_checks` premise-trap guards without duplicating frameworks.
Zero LLM calls; never invents confidence scores (`confidence=None` unless empirically measured).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from app.core.answer_checks import IMG_MARK, _PREMISE_TRAP_AFTER, _PREMISE_TRAP_BEFORE
from app.core.types import SourceChunk

SCHEMA_VERSION = "structured-evidence-v1"


class EvidenceRole:
    USER_INPUT = "USER_INPUT"
    DOCUMENT_EVIDENCE = "DOCUMENT_EVIDENCE"
    DERIVED_VALUE = "DERIVED_VALUE"
    DOCUMENT_EXAMPLE = "DOCUMENT_EXAMPLE"
    OFFICIAL_RULE = "OFFICIAL_RULE"
    UNKNOWN = "UNKNOWN"


class ValidationStatus:
    VALIDATED = "VALIDATED"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"


VALID_ROLES = frozenset({
    EvidenceRole.USER_INPUT,
    EvidenceRole.DOCUMENT_EVIDENCE,
    EvidenceRole.DERIVED_VALUE,
    EvidenceRole.DOCUMENT_EXAMPLE,
    EvidenceRole.OFFICIAL_RULE,
    EvidenceRole.UNKNOWN,
})

VALID_STATUSES = frozenset({
    ValidationStatus.VALIDATED,
    ValidationStatus.UNKNOWN,
    ValidationStatus.AMBIGUOUS,
    ValidationStatus.CONFLICT,
    ValidationStatus.UNSUPPORTED,
})


@dataclass
class StructuredEvidence:
    """Versioned typed evidence fact extracted from documents, user inputs, or validated derivations."""

    evidence_id: str
    source_id: str
    chunk_id: str
    source_span: str
    entity: str = ""
    attribute: str = ""
    value: Any = None
    data_type: str = "unknown"
    unit: str = ""
    currency: str = ""
    applicable_conditions: list[str] = field(default_factory=list)
    effective_date: str = ""
    evidence_role: str = EvidenceRole.UNKNOWN
    derivation: dict[str, Any] | None = None
    validation_status: str = ValidationStatus.UNKNOWN
    confidence: float | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StructuredEvidence":
        return cls(**payload)


_VI_GROUPED_THOUSANDS = re.compile(r"^-?\d{1,3}(?:\.\d{3})+(?:,\d+)?$")
_EN_GROUPED_THOUSANDS = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_COUNT_UNIT_HINT = re.compile(
    r"\b(?:sinh viên|nhân viên|người|khách|tài khoản|users?|seats?|students?|vnd|đồng|đ|usd|\$|triệu|tỷ|nghìn|ngàn|ngày|giờ|tuần|tháng|năm|gb|mb|kg)\b",
    re.I,
)
_AMBIGUOUS_SINGLE_THOUSAND = re.compile(r"^-?\d{1,3}\.\d{3}$")


def parse_localized_number(
    text: str,
    *,
    locale_hint: str = "auto",
    unit_hint: str = "",
) -> tuple[float | int | None, str, str]:
    """Parse VN/EN formatted numbers cleanly, returning `(value, data_type, validation_status)`."""
    raw = (text or "").strip().replace(" ", "")
    if not raw:
        return None, "unknown", ValidationStatus.UNKNOWN

    loc = (locale_hint or "auto").strip().lower()
    has_vi_unit = bool(_COUNT_UNIT_HINT.search(unit_hint or ""))

    if _AMBIGUOUS_SINGLE_THOUSAND.fullmatch(raw) and loc == "auto" and not has_vi_unit:
        return None, "unknown", ValidationStatus.AMBIGUOUS

    if "," in raw and "." not in raw:
        if _EN_GROUPED_THOUSANDS.fullmatch(raw) and loc == "en":
            norm = raw.replace(",", "")
            return int(norm), "integer", ValidationStatus.VALIDATED
        norm = raw.replace(",", ".")
        val = float(norm)
        return (int(val), "integer", ValidationStatus.VALIDATED) if val.is_integer() else (val, "decimal", ValidationStatus.VALIDATED)

    if _VI_GROUPED_THOUSANDS.fullmatch(raw) and (loc in {"vi", "auto"} or has_vi_unit):
        if "," in raw:
            val = float(raw.replace(".", "").replace(",", "."))
            return (int(val), "integer", ValidationStatus.VALIDATED) if val.is_integer() else (val, "decimal", ValidationStatus.VALIDATED)
        return int(raw.replace(".", "")), "integer", ValidationStatus.VALIDATED

    if _EN_GROUPED_THOUSANDS.fullmatch(raw):
        norm = raw.replace(",", "")
        val = float(norm)
        return (int(val), "integer", ValidationStatus.VALIDATED) if val.is_integer() else (val, "decimal", ValidationStatus.VALIDATED)

    try:
        val = float(raw.replace(",", "."))
    except ValueError:
        return None, "unknown", ValidationStatus.UNKNOWN
    if "." in raw or "," in raw:
        return (int(val), "integer", ValidationStatus.VALIDATED) if val.is_integer() else (val, "decimal", ValidationStatus.VALIDATED)
    return int(val), "integer", ValidationStatus.VALIDATED


_EXAMPLE_MARKER = re.compile(
    r"\b(?:ví dụ|minh họa|chẳng hạn|for example|e\.g\.|giả sử|hợp đồng cũ|từng áp dụng|từng giảm|sample|illustrative)\b",
    re.I,
)
_OFFICIAL_MARKER = re.compile(
    r"(?:^#+\s+|\b(?:quy định|chính sách|bảng giá|niêm yết|nội quy|nghị định|thông tư|luật|điều\s+\d+|khoản\s+\d+|mục\s+\d+|policy|sla|official|effective)\b)",
    re.I | re.M,
)
_PREMISE_QUESTION = re.compile(r"\?\s*$")

_DOC_IDENTIFIER = re.compile(
    r"\b(?:Nghị\s*định|Thông\s*tư|Quyết\s*định|Luật|Công\s*văn|Hợp\s*đồng)\s+(?:số\s*:?\s*)?[\d/\-A-ZĐÂÊÔƯ]+(?:\s*/\s*[\dA-ZĐÂÊÔƯ\-]+)*"
    r"|\b(?:Điều|Khoản|Mục|Chương)\s+\d+[a-zđ]?\b"
    r"|\btháng\s+\d{1,2}(?:\s+năm\s+\d{4})?\b"
    r"|\bnăm\s+\d{4}\b",
    re.I,
)
_DATE_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_EFFECTIVE_CUE = re.compile(r"\b(?:hiệu lực(?:\s+từ)?|áp dụng từ|effective(?:\s+date)?(?:\s+from)?)\b", re.I)

_RANGE_BETWEEN = re.compile(
    r"\b(?:từ|from)\s+(\d[\d.,]*)\s*(%?)\s*(?:đến|tới|to|-)\s*(\d[\d.,]*)\s*(%?)\s*(?:(sinh viên|nhân viên|tài khoản|người|giờ/ngày|giờ|ngày(?:\s+làm\s+việc)?|tháng|năm|users?|seats?|hours?(?:/day)?|days?))?",
    re.I,
)
_RANGE_HYPHEN_UNIT = re.compile(
    r"(?<![/\-])\b(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s+(giờ/ngày|giờ|ngày(?:\s+làm\s+việc)?|tháng|hours?(?:/day)?|days?|%|gb|mb)\b",
    re.I,
)
_CURRENCY_RE = re.compile(
    r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(tỷ|triệu|nghìn|ngàn)?\s*(?:VND|VNĐ|đồng|đ|USD|\$)(?:\s*/\s*(năm|tháng|ngày|giờ|year|month|day|hour|người\s*dùng/tháng|user/month))?",
    re.I,
)
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_NUMBER_WORD_VAL: dict[str, int] = {
    "một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5, "sáu": 6,
    "bảy": 7, "tám": 8, "chín": 9, "mười": 10, "mười hai": 12,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
}
_NL_NUM_ALT = r"(?:\d{1,2}(?:[.,]\d+)?|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười\s+hai|mười|one|two|three|four|five|six|seven|eight|nine|ten|twelve)"
_NL_HOURS_PER_DAY_RE = re.compile(
    rf"(?<![\w/])\b({_NL_NUM_ALT})\s+(?:giờ|tiếng|hours?)\s+"
    r"(?:trong\s+(?:0?1|một|one)\s+(?:ngày(?:\s+làm\s+việc)?)|mỗi\s+ngày(?:\s+làm\s+việc)?|một\s+ngày(?:\s+làm\s+việc)?|"
    r"per\s+(?:working\s+)?day|in\s+(?:one|1|a)\s+(?:working\s+)?day|a\s+day)\b",
    re.I,
)
_NL_HOURS_PER_WEEK_RE = re.compile(
    rf"(?<![\w/])\b(\d{{1,3}}(?:[.,]\d+)?)\s+(?:giờ|tiếng|hours?)\s+"
    r"(?:trong\s+(?:0?1|một|one)\s+tuần|mỗi\s+tuần|một\s+tuần|/\s*tuần|per\s+week|in\s+(?:one|1|a)\s+week|a\s+week)\b",
    re.I,
)
_DURATION_QTY_RE = re.compile(
    r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s+(giờ/ngày|hours?/day|giờ|tiếng|hours?|ngày\s+làm\s+việc|working\s+days?|ngày\s+công|ngày|days?|tháng|months?|năm|years?|sinh\s+viên|nhân\s+viên|tài\s+khoản|users?|seats?|students?|gb|mb|tb|kg)\b",
    re.I,
)

_SCALE_MAP = {"tỷ": 1_000_000_000.0, "triệu": 1_000_000.0, "nghìn": 1_000.0, "ngàn": 1_000.0}
_PERIOD_UNIT_MAP = {
    "năm": "year", "year": "year",
    "tháng": "month", "month": "month",
    "ngày": "day", "day": "day",
    "giờ": "hour", "hour": "hour",
    "người dùng/tháng": "user/month", "user/month": "user/month",
}


def _normalize_unit(raw_unit: str) -> tuple[str, str]:
    u = " ".join((raw_unit or "").strip().lower().split())
    if u in {"giờ", "tiếng", "hour", "hours"}:
        return "hour", "duration"
    if u in {"giờ/ngày", "hour/day", "hours/day"}:
        return "hour/day", "duration"
    if u in {"ngày làm việc", "working day", "working days", "ngày công"}:
        return "working_day", "duration"
    if u in {"ngày", "day", "days"}:
        return "day", "duration"
    if u in {"tháng", "month", "months"}:
        return "month", "duration"
    if u in {"năm", "year", "years"}:
        return "year", "duration"
    if u in {"gb", "mb", "tb"}:
        return u.upper(), "quantity"
    if u in {"sinh viên", "students", "student"}:
        return "student", "quantity"
    if u in {"nhân viên"}:
        return "employee", "quantity"
    if u in {"tài khoản", "user", "users", "seat", "seats"}:
        return "account", "quantity"
    return u, "quantity"


_PRODUCT_OR_SERVICE_COL = re.compile(r"^(?:sản phẩm|dịch vụ|product|service|tuyến|route|họ tên|name)$", re.I)
_TIER_OR_VARIANT_COL = re.compile(r"^(?:gói|phân hạng|hạng|trọng lượng|khối lượng|tier|plan|package|nội dung|khách hàng)$", re.I)
_UNIT_COL = re.compile(r"^(?:đơn vị tính|đơn vị|chu kỳ tính|billing\s*cycle|unit)$", re.I)
_APPROVAL_COL = re.compile(r"(?:người\s+phê\s+duyệt|cấp\s+phê\s+duyệt|thẩm\s+quyền|approv(?:er|ing\s+authority)|authority)", re.I)
_HEADING_ENTITY_CUE = re.compile(r"(?:áp dụng cho(?:\s+gói)?(?:\s+thiết bị(?:\s+y tế)?)?|gói\s+dịch vụ|sản phẩm)\s+([A-Z][\w\-]+(?:\s+[A-Z][\w\-]+){0,2})")
_CAP_PCT_CUE = re.compile(r"(?:không vượt(?:\s+quá)?|tối đa|capped at|max(?:imum)?)\s*$", re.I)
_EXCLUSION_CLAUSE = re.compile(r"(?:không\s+(?:chiết khấu|giảm(?:\s+giá)?|áp dụng giảm)|without\s+discount)\s+([^.;\n]+)", re.I)
_FIXED_FEE_CUE = (
    "triển khai", "deployment", "cài đặt", "cố định", "khởi tạo", "kiểm tra tại chỗ",
    "phí kiểm tra", "phí khảo sát", "niêm phong", "bảo hiểm cố định", "di chuyển",
    "cấu hình", "một lần", "fixed", "one-time", "setup", "installation", "onboarding",
)
_UNIT_PRICE_CUE = (
    "đơn giá", "giá niêm yết", "base price", "unit price", "price",
    "phí gói", "phí gia hạn", "phí thuê bao", "cước vận chuyển", "giá cước",
    "phí hiệu chuẩn", "thuê bao", "phí dịch vụ", "gói ",
)


def _infer_attribute(context: str, data_type: str, unit: str) -> str:
    ctx = (context or "").casefold()
    if data_type == "duration" and "ngày công" in ctx:
        return "workdays_per_month"
    if data_type == "duration" and (unit == "hour/day" or "giờ/ngày" in ctx or "hour/day" in ctx):
        return "hours_per_day"
    if data_type == "duration" and unit == "hour/week":
        return "hours_per_week"
    if data_type == "currency":
        if any(k in ctx for k in ("lương giờ", "hourly rate", "hourly")):
            return "hourly_rate"
        if any(k in ctx for k in ("lương ngày", "daily rate", "daily salary")) or unit in {"VND/day", "USD/day"}:
            return "salary_daily"
        if any(k in ctx for k in ("lương", "salary")):
            return "salary_monthly" if unit == "VND/month" else "salary"
        if "triển khai" in ctx or "deployment" in ctx:
            return "deployment_fee"
        if any(k in ctx for k in _FIXED_FEE_CUE):
            return "fixed_fee"
        if any(k in ctx for k in _UNIT_PRICE_CUE):
            return "unit_price"
        if any(k in ctx for k in ("phạt", "penalty", "vi phạm")):
            return "penalty_amount"
        return "currency"
    if data_type == "percentage":
        if any(k in ctx for k in ("phạt", "penalty", "vi phạm")):
            return "penalty_rate"
        if any(k in ctx for k in ("làm thêm", "tăng ca", "overtime")):
            return "overtime_multiplier"
        if any(k in ctx for k in ("chiết khấu", "discount", "giảm", "ưu đãi")):
            return "discount_rate"
    if any(k in ctx for k in ("làm thêm", "tăng ca", "overtime")):
        return "overtime_hours" if unit == "hour" else "overtime_rate"
    if any(k in ctx for k in ("thông báo", "response time", "phê duyệt", "báo trước", "thời hạn")):
        return "notification_deadline"
    if any(k in ctx for k in ("hiệu lực", "effective")):
        return "effective_date"
    if unit in {"GB", "MB", "TB"} or "storage" in ctx:
        return "storage_limit"
    return data_type


def _working_hours_conditions(clause: str, base_conds: list[str]) -> list[str]:
    """Tag working-hour evidence with schedule scope (actual vs statutory_max; daily vs weekly)."""
    c_cf = (clause or "").casefold()
    out = list(base_conds)
    is_stat_max = bool(re.search(
        r"(?:không\s+(?:được\s+)?quá|tối\s+đa|at\s+most|not\s+exceed(?:ing)?|shall\s+not\s+exceed|maximum|statutory\s+cap)",
        c_cf,
    ))
    is_actual = bool(re.search(
        r"(?:thời\s+giờ\s+làm\s+việc\s+thực\s+tế|thực\s+tế\s+của|quy\s+định\s+công\s+ty|nội\s+quy\s+công\s+ty|quy\s+chế\s+[^\n:]{0,20}:|"
        r"ca\s+làm\s+việc|làm\s+việc\s+chuẩn|actual\s+(?:contractual|working|shift)|contractual\s+shift|regular\s+working\s+schedule|"
        r"normal\s+working\s+schedule|company\s+working\s+hours)",
        c_cf,
    ))
    if is_actual:
        out.append("actual_schedule")
    elif is_stat_max:
        out.append("statutory_max")
    if re.search(r"(?:theo\s+tuần|weekly|per\s+week)", c_cf):
        out.append("weekly_schedule")
    elif "daily_schedule" not in out:
        out.append("daily_schedule")
    return list(dict.fromkeys(out))


def _infer_conditions(line_text: str, section_heading: str = "") -> list[str]:
    conds: list[str] = []
    cf = (line_text or "").casefold()
    sec_cf = (section_heading or "").casefold()
    combined = f"{sec_cf} {cf}"
    if any(k in cf for k in ("công lập", "bệnh viện công", "cơ quan nhà nước", "trường công", "public")):
        conds.append("public_institution")
    if any(k in cf for k in ("tư nhân", "doanh nghiệp tư nhân", "private")):
        conds.append("private_institution")
    if "phi lợi nhuận" in cf or "non-profit" in cf or "nonprofit" in cf:
        conds.append("nonprofit")
    if "vip" in cf or "thành viên vip" in cf:
        conds.append("vip_member")
    if "y tế tuyến tỉnh" in cf:
        conds.append("provincial_health")
    if any(k in cf for k in ("hợp đồng 3 năm", "3 năm trả trước", "năm thứ hai và thứ ba")):
        conds.append("multi_year_3yr")
    if any(k in cf for k in ("chưa thành niên", "chưa đủ 15", "dưới 15 tuổi", "dưới 18 tuổi", "minor")):
        conds.append("minor_worker")
    if any(k in cf for k in ("nặng nhọc", "độc hại", "nguy hiểm", "hazardous")):
        conds.append("hazardous_work")
    if "kinh doanh" in combined:
        conds.append("department=Kinh doanh")
    if "weekday" in cf or "ngày thường" in cf:
        conds.append("weekday")
    if "holiday" in cf or "ngày lễ" in cf:
        conds.append("holiday")
    if "downtime" in cf:
        conds.append("downtime")
    return list(dict.fromkeys(conds))


def _line_role(line: str, chunk: SourceChunk, default_official: bool) -> str:
    if _EXAMPLE_MARKER.search(line):
        return EvidenceRole.DOCUMENT_EXAMPLE
    if default_official or _OFFICIAL_MARKER.search(line):
        return EvidenceRole.OFFICIAL_RULE
    return EvidenceRole.DOCUMENT_EVIDENCE


def _table_cells(line: str) -> list[str]:
    if "|" not in line:
        return []
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(bool(c) and set(c) <= {"-", ":"} for c in cells)


def _tier_bounds_from_text(text: str) -> list[str]:
    """Extract structured tier range tokens (min_qty/max_qty/exclusivity) from tier descriptions cleanly."""
    t = (text or "").strip()
    conds: list[str] = []
    m_bet = re.search(
        r"\btừ\s+(\d[\d.,]*)\s*(?:đến|tới|-)\s*(\d[\d.,]*)\s*(sinh\s+viên|học\s+viên|người\s+dùng|tài\s+khoản|users?|seats?|students?|tấn|kg|giờ|ngày)?",
        t,
        re.I,
    )
    if m_bet:
        lo, _, _ = parse_localized_number(m_bet.group(1), locale_hint="vi", unit_hint=m_bet.group(0) + " người")
        hi, _, _ = parse_localized_number(m_bet.group(2), locale_hint="vi", unit_hint=m_bet.group(0) + " người")
        if lo is not None and hi is not None:
            conds.extend([f"min_qty={lo}", f"max_qty={hi}", "min_inc=1", "max_inc=1"])
            return conds
    m_lt = re.search(
        r"\b(?:dưới|nhỏ hơn|ít hơn|under|below|<)\s*(\d[\d.,]*)\s*(sinh\s+viên|học\s+viên|người\s+dùng|tài\s+khoản|users?|seats?|students?|tấn|kg)?",
        t,
        re.I,
    )
    if m_lt:
        hi, _, _ = parse_localized_number(m_lt.group(1), locale_hint="vi", unit_hint=m_lt.group(0) + " người")
        if hi is not None:
            conds.extend(["min_qty=0", f"max_qty={hi}", "min_inc=1", "max_inc=0"])
            return conds
    m_ge = re.search(
        r"(?:\btừ\b|>=)\s*(\d[\d.,]*)\s*(?:\+|trở lên)?\s*(sinh\s+viên|học\s+viên|người\s+dùng|tài\s+khoản|users?|seats?|students?|tấn|kg)?",
        t,
        re.I,
    )
    if m_ge:
        lo, _, _ = parse_localized_number(m_ge.group(1), locale_hint="vi", unit_hint=m_ge.group(0) + " người")
        if lo is not None:
            conds.extend([f"min_qty={lo}", "min_inc=1"])
            return conds
    m_le = re.search(
        r"\b(?:đến|tối đa|không quá|up to|<=)\s*(\d[\d.,]*)\s*(sinh\s+viên|học\s+viên|người\s+dùng|tài\s+khoản|users?|seats?|students?|tấn|kg)?",
        t,
        re.I,
    )
    if m_le:
        hi, _, _ = parse_localized_number(m_le.group(1), locale_hint="vi", unit_hint=m_le.group(0) + " người")
        if hi is not None:
            conds.extend(["min_qty=0", f"max_qty={hi}", "min_inc=1", "max_inc=1"])
            return conds
    return conds


def _table_row_entity(line: str, headers: list[str] | None = None) -> tuple[str, list[str], str]:
    """Return `(entity_label, tier_conditions, inherited_period_unit)` for a Markdown/pipe table row."""
    cells = _table_cells(line)
    if not cells or _is_table_separator(line):
        return "", [], ""
    first = cells[0]
    if first.casefold() in {"sản phẩm", "khách hàng / gói", "mức chiết khấu trên giá niêm yết", "nội dung", "họ tên", "entity", "item", "dịch vụ", "tuyến"}:
        return "", [], ""

    headers = headers or []
    prod_val = ""
    tier_val = ""
    period_val = ""
    for i, cell in enumerate(cells):
        hdr = headers[i].strip() if i < len(headers) else ""
        if hdr and _UNIT_COL.match(hdr):
            period_val = _PERIOD_UNIT_MAP.get(cell.strip().casefold(), cell.strip().casefold())
        elif hdr and _TIER_OR_VARIANT_COL.match(hdr):
            tier_val = cell
        elif hdr and _PRODUCT_OR_SERVICE_COL.match(hdr):
            prod_val = cell

    if not prod_val and not tier_val:
        prod_val = first
        if len(cells) > 1 and not re.search(r"\d", cells[1]) and "|" not in cells[1]:
            # Only append second cell when it is clearly a tier/package descriptor, not numeric amount
            pass

    if not prod_val:
        prod_val = first

    tier_conds = _tier_bounds_from_text(tier_val or prod_val)
    entity = f"{prod_val} | {tier_val}".strip(" |") if (tier_val and tier_val != prod_val) else prod_val
    return entity, tier_conds, period_val


def _header_for_span(line: str, pos: int, headers: list[str]) -> str:
    if not headers or "|" not in line:
        return ""
    pipe_idx = line[:max(0, pos)].count("|")
    col = pipe_idx - 1 if line.lstrip().startswith("|") else pipe_idx
    if 0 <= col < len(headers):
        return headers[col]
    return ""


def _mask_span(buf: list[str], start: int, end: int) -> None:
    for i in range(start, end):
        buf[i] = " "


def _extract_from_text_lines(
    text: str,
    *,
    source_id: str,
    chunk_id: str,
    chunk_role_default_official: bool,
    forced_role: str | None = None,
    locale: str = "auto",
) -> list[StructuredEvidence]:
    items: list[StructuredEvidence] = []
    seq = 0
    chunk_effective_date = ""
    active_headers: list[str] = []
    active_section = ""
    active_doc_entity = ""

    def next_id() -> str:
        nonlocal seq
        seq += 1
        return f"ev_{chunk_id}_{seq:03d}"

    # Pre-scan chunk heading / early lines for chunk-level effective date & document entity
    for ln in (text or "").splitlines()[:5]:
        if not active_doc_entity:
            hm = _HEADING_ENTITY_CUE.search(ln)
            if hm:
                active_doc_entity = hm.group(1).strip(" .,:;")
        if _EFFECTIVE_CUE.search(ln):
            dm = _DATE_DMY.search(ln)
            if dm:
                d, m, y = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
                if 1 <= m <= 12 and 1 <= d <= 31:
                    chunk_effective_date = f"{y:04d}-{m:02d}-{d:02d}"
                    break

    raw_lines = (text or "").splitlines()
    for idx_ln, raw_ln in enumerate(raw_lines):
        ln = raw_ln.strip()
        if not ln:
            active_headers = []
            continue
        if re.match(r"^#+\s+", ln):
            active_section = re.sub(r"^#+\s+", "", ln).strip()
            active_headers = []
            if not active_doc_entity:
                hm = _HEADING_ENTITY_CUE.search(active_section)
                if hm:
                    active_doc_entity = hm.group(1).strip(" .,:;")
        if "|" in ln and idx_ln + 1 < len(raw_lines) and _is_table_separator(raw_lines[idx_ln + 1].strip()):
            active_headers = _table_cells(ln)
            continue
        if _is_table_separator(ln):
            continue
        # Handle pipe-separated header line without separator (e.g. XLSX export: Họ tên | Lương giờ (đồng) | ...)
        if "|" in ln and not active_headers and re.match(r"^(?:Họ tên|Sản phẩm|Dịch vụ|Tên|STT)\s*\|", ln, re.I):
            active_headers = _table_cells(ln)
            continue
        if "|" not in ln:
            active_headers = []
        row_entity, tier_conds, row_period = _table_row_entity(ln, active_headers)
        entity = row_entity or active_doc_entity
        role = forced_role or _line_role(ln, SourceChunk(chunk_id, source_id, "", text, 0), chunk_role_default_official)
        conds = _infer_conditions(ln, active_section)
        if tier_conds:
            conds = [*conds, *tier_conds]
        buf = list(ln)
        is_approval_table = any(_APPROVAL_COL.search(h) for h in active_headers)

        # 1. Document identifiers
        for m in _DOC_IDENTIFIER.finditer(ln):
            items.append(StructuredEvidence(
                evidence_id=next_id(),
                source_id=source_id,
                chunk_id=chunk_id,
                source_span=m.group(0),
                entity=entity,
                attribute="document_identifier",
                value=m.group(0),
                data_type="identifier",
                effective_date=chunk_effective_date,
                evidence_role=forced_role or role,
                validation_status=ValidationStatus.VALIDATED,
            ))
            _mask_span(buf, m.start(), m.end())

        # 2. Explicit dates (dd/mm/yyyy)
        work = "".join(buf)
        for m in _DATE_DMY.finditer(work):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                iso = f"{y:04d}-{mo:02d}-{d:02d}"
                is_eff = bool(_EFFECTIVE_CUE.search(ln[:m.end()]))
                if is_eff and not chunk_effective_date:
                    chunk_effective_date = iso
                items.append(StructuredEvidence(
                    evidence_id=next_id(),
                    source_id=source_id,
                    chunk_id=chunk_id,
                    source_span=m.group(0),
                    entity=entity,
                    attribute="effective_date" if is_eff else "date",
                    value=iso,
                    data_type="date",
                    applicable_conditions=conds,
                    effective_date=iso if is_eff else chunk_effective_date,
                    evidence_role=forced_role or role,
                    validation_status=ValidationStatus.VALIDATED,
                ))
                _mask_span(buf, m.start(), m.end())

        # 3. Ranges ("từ A đến B", "8-10 giờ/ngày")
        work = "".join(buf)
        for pattern, is_hyphen in ((_RANGE_BETWEEN, False), (_RANGE_HYPHEN_UNIT, True)):
            work = "".join(buf)
            for m in pattern.finditer(work):
                lo_raw, hi_raw = m.group(1), m.group(3 if not is_hyphen else 2)
                raw_unit = (m.group(5) if not is_hyphen else m.group(3)) or (m.group(2) if not is_hyphen else "") or ""
                norm_u, _ = _normalize_unit(raw_unit)
                if raw_unit == "%":
                    norm_u = "percent"
                v_lo, _, s_lo = parse_localized_number(lo_raw, locale_hint="en" if is_hyphen else locale, unit_hint=raw_unit or ln)
                v_hi, _, s_hi = parse_localized_number(hi_raw, locale_hint="en" if is_hyphen else locale, unit_hint=raw_unit or ln)
                if v_lo is not None and v_hi is not None and s_lo == ValidationStatus.VALIDATED and s_hi == ValidationStatus.VALIDATED:
                    items.append(StructuredEvidence(
                        evidence_id=next_id(),
                        source_id=source_id,
                        chunk_id=chunk_id,
                        source_span=m.group(0),
                        entity=entity,
                        attribute=_infer_attribute(ln, "range", norm_u),
                        value={"min": v_lo, "max": v_hi, "min_inclusive": True, "max_inclusive": True},
                        data_type="range",
                        unit=norm_u,
                        applicable_conditions=conds,
                        effective_date=chunk_effective_date,
                        evidence_role=forced_role or role,
                        validation_status=ValidationStatus.VALIDATED,
                    ))
                    _mask_span(buf, m.start(), m.end())

        # 4. Currency ("17,5 triệu đồng/tháng", "260.000.000 VND/năm", "1,250 USD/month")
        work = "".join(buf)
        for m in _CURRENCY_RE.finditer(work):
            num_raw, scale_kw, period_kw = m.group(1), m.group(2), m.group(3)
            cur = "USD" if ("usd" in m.group(0).casefold() or "$" in m.group(0)) else "VND"
            en_comma_thousands = (
                "," in num_raw and "." not in num_raw
                and bool(re.fullmatch(r"\d{1,3}(?:,\d{3})+", num_raw))
                and (
                    cur == "USD"
                    or bool(re.search(r"\b(?:daily|monthly|salary|rate|price|fee|cost|usd|vnd/day|vnd/month|hour|per)\b", ln, re.I))
                )
            )
            loc = "en" if en_comma_thousands else ("vi" if cur == "VND" else locale)
            val, _, st = parse_localized_number(num_raw, locale_hint=loc, unit_hint=m.group(0))
            if val is not None and st == ValidationStatus.VALIDATED:
                if scale_kw:
                    val = val * _SCALE_MAP[scale_kw.casefold()]
                    if float(val).is_integer():
                        val = int(val)
                col_hdr = _header_for_span(ln, m.start(), active_headers)
                period = _PERIOD_UNIT_MAP.get((period_kw or "").casefold(), "")
                if not period and "/tháng" in ln.casefold() and cur in m.group(0):
                    after = ln[m.end():m.end() + 10].strip().casefold()
                    for pk, pv in _PERIOD_UNIT_MAP.items():
                        if after.startswith("/" + pk):
                            period = pv
                            break
                # Inherit period from table column ("Đơn vị tính" / "Chu kỳ tính") ONLY for unit_price column, NOT one-time fixed fee column!
                attr_ctx = col_hdr or ln
                inferred_attr = _infer_attribute(attr_ctx, "currency", f"{cur}/{period}" if period else cur)
                if not period and row_period and inferred_attr == "unit_price":
                    period = row_period
                unit = f"{cur}/{period}" if period else cur
                items.append(StructuredEvidence(
                    evidence_id=next_id(),
                    source_id=source_id,
                    chunk_id=chunk_id,
                    source_span=m.group(0),
                    entity=entity,
                    attribute=inferred_attr,
                    value=val,
                    data_type="currency",
                    unit=unit,
                    currency=cur,
                    applicable_conditions=conds,
                    effective_date=chunk_effective_date,
                    evidence_role=forced_role or role,
                    validation_status=ValidationStatus.VALIDATED,
                ))
                _mask_span(buf, m.start(), m.end())

        # 4b. Header-unit currency columns in XLSX tables without per-cell unit (e.g. `Lương giờ (đồng)` -> `84135`)
        if "|" in ln and active_headers:
            work = "".join(buf)
            for m in re.finditer(r"(?<![/\-\d.])\b(\d{4,12})\b(?![\d.])", work):
                col_hdr = _header_for_span(ln, m.start(), active_headers)
                col_cf = col_hdr.casefold()
                if any(k in col_cf for k in ("lương giờ", "đồng", "vnd", "giá", "phí")) and "id" not in col_cf:
                    cur = "USD" if "usd" in col_cf else "VND"
                    unit = "VND/hour" if "giờ" in col_cf else cur
                    attr = _infer_attribute(col_hdr, "currency", unit)
                    items.append(StructuredEvidence(
                        evidence_id=next_id(),
                        source_id=source_id,
                        chunk_id=chunk_id,
                        source_span=m.group(0),
                        entity=entity,
                        attribute=attr,
                        value=int(m.group(1)),
                        data_type="currency",
                        unit=unit,
                        currency=cur,
                        applicable_conditions=conds,
                        effective_date=chunk_effective_date,
                        evidence_role=forced_role or role,
                        validation_status=ValidationStatus.VALIDATED,
                    ))
                    _mask_span(buf, m.start(), m.end())

        # 5. Percentages
        work = "".join(buf)
        for m in _PERCENT_RE.finditer(work):
            val, _, st = parse_localized_number(m.group(1), locale_hint="en" if "." in m.group(1) and "," not in m.group(1) else locale, unit_hint="%")
            if val is not None and st == ValidationStatus.VALIDATED:
                before_pct = ln[max(0, m.start() - 32):m.start()]
                if is_approval_table:
                    pct_attr = "approval_threshold"
                elif _CAP_PCT_CUE.search(before_pct):
                    pct_attr = "discount_cap"
                else:
                    col_or_ctx = _header_for_span(ln, m.start(), active_headers)
                    if not col_or_ctx:
                        # Combine section heading so "được thêm 5%" inside "## 4. Chính sách chiết khấu" inherits discount_rate
                        col_or_ctx = f"{active_section} {ln}"
                    pct_attr = _infer_attribute(col_or_ctx, "percentage", "percent")
                pct_conds = list(conds)
                if pct_attr == "discount_rate" and _EXCLUSION_CLAUSE.search(ln):
                    pct_conds.append("excludes_fixed_fee")
                items.append(StructuredEvidence(
                    evidence_id=next_id(),
                    source_id=source_id,
                    chunk_id=chunk_id,
                    source_span=m.group(0),
                    entity=entity,
                    attribute=pct_attr,
                    value=float(val),
                    data_type="percentage",
                    unit="percent",
                    applicable_conditions=pct_conds,
                    effective_date=chunk_effective_date,
                    evidence_role=forced_role or role,
                    validation_status=ValidationStatus.VALIDATED,
                ))
                _mask_span(buf, m.start(), m.end())

        # 6a. Natural-language per-week and per-day working hours ("08 giờ trong 01 ngày", "Eight hours per day", "48 giờ trong 01 tuần")
        work = "".join(buf)
        for m in _NL_HOURS_PER_WEEK_RE.finditer(work):
            val, _, st = parse_localized_number(m.group(1), locale_hint=locale, unit_hint="hour/week")
            if val is not None and st == ValidationStatus.VALIDATED:
                clause = re.split(r"[.;\n]", ln[:m.end()])[-1]
                nl_conds = _infer_conditions(clause, active_section) or conds
                items.append(StructuredEvidence(
                    evidence_id=next_id(),
                    source_id=source_id,
                    chunk_id=chunk_id,
                    source_span=m.group(0),
                    entity=entity,
                    attribute="hours_per_week",
                    value=val,
                    data_type="duration",
                    unit="hour/week",
                    applicable_conditions=nl_conds,
                    effective_date=chunk_effective_date,
                    evidence_role=forced_role or role,
                    validation_status=ValidationStatus.VALIDATED,
                ))
                _mask_span(buf, m.start(), m.end())

        work = "".join(buf)
        for m in _NL_HOURS_PER_DAY_RE.finditer(work):
            tok = " ".join(m.group(1).strip().lower().split())
            if tok in _NUMBER_WORD_VAL:
                val: float | int | None = _NUMBER_WORD_VAL[tok]
                st = ValidationStatus.VALIDATED
            else:
                loc_h = "en" if ("." in tok and len(tok.split(".")[-1]) != 3) else locale
                val, _, st = parse_localized_number(tok, locale_hint=loc_h, unit_hint="hour/day")
            if val is not None and st == ValidationStatus.VALIDATED:
                clause = re.split(r"(?<!\d)[.;\n]|(?<=\d)[.;\n](?!\d)", ln[:m.end()])[-1]
                nl_conds = _working_hours_conditions(clause, _infer_conditions(clause, active_section))
                if tier_conds:
                    nl_conds = list(dict.fromkeys([*nl_conds, *tier_conds]))
                items.append(StructuredEvidence(
                    evidence_id=next_id(),
                    source_id=source_id,
                    chunk_id=chunk_id,
                    source_span=m.group(0),
                    entity=entity,
                    attribute="hours_per_day",
                    value=val,
                    data_type="duration",
                    unit="hour/day",
                    applicable_conditions=nl_conds,
                    effective_date=chunk_effective_date,
                    evidence_role=forced_role or role,
                    validation_status=ValidationStatus.VALIDATED,
                ))
                _mask_span(buf, m.start(), m.end())

        # 6. Durations & Typed Quantities
        work = "".join(buf)
        for m in _DURATION_QTY_RE.finditer(work):
            raw_num, raw_u = m.group(1), m.group(2)
            norm_u, dtype = _normalize_unit(raw_u)
            loc_h = "vi" if "." in raw_num and len(raw_num.split(".")[-1]) == 3 else ("en" if "." in raw_num else locale)
            val, _, st = parse_localized_number(raw_num, locale_hint=loc_h, unit_hint=raw_u)
            if val is not None and st == ValidationStatus.VALIDATED:
                attr = _infer_attribute(_header_for_span(ln, m.start(), active_headers) or ln[:m.end() + 20], dtype, norm_u)
                clause_dur = re.split(r"(?<!\d)[.;\n]|(?<=\d)[.;\n](?!\d)", ln[:m.end()])[-1]
                dur_conds = _working_hours_conditions(clause_dur, conds) if attr == "hours_per_day" else conds
                items.append(StructuredEvidence(
                    evidence_id=next_id(),
                    source_id=source_id,
                    chunk_id=chunk_id,
                    source_span=m.group(0),
                    entity=entity,
                    attribute=attr,
                    value=val,
                    data_type=dtype,
                    unit=norm_u,
                    applicable_conditions=dur_conds,
                    effective_date=chunk_effective_date,
                    evidence_role=forced_role or role,
                    validation_status=ValidationStatus.VALIDATED,
                ))
                _mask_span(buf, m.start(), m.end())

    return items


def extract_structured_evidence(
    chunks: list[SourceChunk],
    *,
    query: str = "",
    allowed_source_ids: set[str] | None = None,
    locale: str = "auto",
) -> list[StructuredEvidence]:
    """Extract typed, provenance-bound evidence from authorized chunks and validated user inputs."""
    out: list[StructuredEvidence] = []

    for chunk in chunks:
        if allowed_source_ids is not None and chunk.source_id not in allowed_source_ids:
            continue
        doc_type = str((chunk.provenance or {}).get("doc_type") or "").strip().lower()
        default_official = doc_type in {"legal_doc", "policy", "contract"} or bool(_OFFICIAL_MARKER.search(chunk.text))
        out.extend(
            _extract_from_text_lines(
                chunk.text,
                source_id=chunk.source_id,
                chunk_id=chunk.chunk_id,
                chunk_role_default_official=default_official,
                locale=locale,
            )
        )

    if query:
        if IMG_MARK in query:
            typed_part, img_part = query.split(IMG_MARK, 1)
            out.extend(
                _extract_from_text_lines(
                    img_part,
                    source_id="user_input",
                    chunk_id="user_ocr",
                    chunk_role_default_official=False,
                    forced_role=EvidenceRole.USER_INPUT,
                    locale=locale,
                )
            )
        else:
            typed_part = query

        # User typed text: isolate premise traps ("mỗi nhân viên được nghỉ 30 ngày đúng không?") as UNKNOWN/UNSUPPORTED
        typed_items = _extract_from_text_lines(
            typed_part,
            source_id="user_input",
            chunk_id="user_query",
            chunk_role_default_official=False,
            forced_role=EvidenceRole.USER_INPUT,
            locale=locale,
        )
        for item in typed_items:
            idx = typed_part.find(item.source_span)
            before = typed_part[max(0, idx - 48):idx] if idx >= 0 else ""
            after = typed_part[idx + len(item.source_span):min(len(typed_part), idx + len(item.source_span) + 40)] if idx >= 0 else ""
            if idx >= 0 and (_PREMISE_TRAP_BEFORE.search(before) or _PREMISE_TRAP_AFTER.search(after)):
                item.evidence_role = EvidenceRole.UNKNOWN
                item.validation_status = ValidationStatus.UNSUPPORTED
            elif _PREMISE_QUESTION.search(typed_part) and item.data_type == "identifier":
                item.evidence_role = EvidenceRole.USER_INPUT
            out.append(item)

    return out


def evaluate_extraction_quality(predicted: list[StructuredEvidence], gold: list[dict[str, Any]]) -> dict[str, float | int]:
    """Compute precision, recall, F1, provenance accuracy, and unknown handling on labeled fixtures."""
    filtered_pred = [p for p in predicted if p.data_type != "identifier"]
    matched_pred: set[int] = set()
    tp = 0
    prov_ok = 0

    for g in gold:
        hit_idx = None
        for idx, p in enumerate(filtered_pred):
            if idx in matched_pred:
                continue
            if p.value == g["value"] and p.unit == g.get("unit", "") and p.evidence_role == g.get("evidence_role", p.evidence_role):
                hit_idx = idx
                break
        if hit_idx is not None:
            matched_pred.add(hit_idx)
            tp += 1
            if filtered_pred[hit_idx].chunk_id == g.get("chunk_id"):
                prov_ok += 1

    fp = max(0, len(filtered_pred) - tp)
    fn = max(0, len(gold) - tp)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "provenance_accuracy": round(prov_ok / tp, 4) if tp else 0.0,
    }
