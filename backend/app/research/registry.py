"""Bộ lĩnh vực (domain pack): tác tử, từ khóa nhận diện, mẫu lập kế hoạch theo từng ngành.

`software` giữ nguyên 3 tác tử, từ khóa, mẫu và prompt của CAP1 (mặc định, dùng cho thực nghiệm A/B/C).
Các bộ khác thêm tác tử `general` cho câu ngoài phạm vi và quy tắc giữ ngôn ngữ của yêu cầu.
Bộ đang dùng đặt theo từng lượt chạy qua ContextVar (`use_pack`), đọc bằng `active_pack()`.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_PACK = "software"

_SOFTWARE_AGENTS = {
    "security": {
        "name": "Security Analyst",
        "capabilities": ["authentication", "authorization", "JWT", "security review"],
        "scope": "Security requirements and access-control concerns",
        "exclusions": ["SQL tuning", "API response design unless security-related"],
    },
    "database": {
        "name": "Database Analyst",
        "capabilities": ["schema", "query", "transaction", "data consistency"],
        "scope": "Database and data-access concerns",
        "exclusions": ["authentication policy", "general UI review"],
    },
    "api_architecture": {
        "name": "API/Architecture Analyst",
        "capabilities": ["API", "endpoint", "architecture", "integration"],
        "scope": "API and system-architecture concerns",
        "exclusions": ["deep database tuning", "security policy ownership"],
    },
}
_SOFTWARE_HINTS = {
    "security": ("security", "auth", "authentication", "authorization", "jwt", "token", "permission", "identity",
                 "login", "session", "signed", "tamper", "ký", "mã hóa", "đăng nhập", "phân quyền"),
    "database": ("database", "db", "schema", "query", "sql", "index", "transaction", "consistency", "table",
                 "persistence", "relational", "cơ sở dữ liệu", "giao dịch", "lược đồ", "truy vấn"),
    "api_architecture": ("api", "endpoint", "rest", "service", "architecture", "integration", "contract", "response",
                         "kiến trúc", "giao diện api"),
}
_SOFTWARE_PATTERNS = [
    ("planning_security.md", "Authentication, authorization, JWT, identity and access-control requests should remain separate atomic obligations when the user asks for distinct concerns."),
    ("planning_database.md", "Database review requests commonly decompose into schema/data model, query/access, transaction/consistency, and performance only when the user actually asks for them."),
    ("planning_api.md", "API and architecture requests commonly separate endpoint contract, error handling, integration boundary, dependency, and architecture decisions. Preserve user-stated dependencies."),
    ("planning_multi_domain.md", "Multi-domain software review requests should create one task per independent obligation, preserve required dependencies, avoid merging merely because terms are semantically similar, and avoid inventing tasks not requested."),
]
# Từ neo riêng của từng mẫu (không dùng từ chung như "review", "request").
_SOFTWARE_ANCHORS = {
    "planning_security.md": frozenset({"security", "authentication", "authorization", "jwt", "identity", "access-control", "control"}),
    "planning_database.md": frozenset({"database", "schema", "data", "model", "query", "transaction", "consistency", "performance"}),
    "planning_api.md": frozenset({"api", "architecture", "endpoint", "error", "handling", "integration", "dependency"}),
    "planning_multi_domain.md": frozenset({"multi-domain", "independent", "semantically", "merge", "invent"}),
}

_GENERAL_AGENT = {
    "name": "General Analyst",
    "capabilities": ["summary", "definitions", "cross-cutting rules", "anything not covered by another domain"],
    "scope": "Cross-cutting or unclassified subjects in the supplied documents",
    "exclusions": ["subjects clearly owned by another listed domain"],
}
# Chỉ áp dụng cho bộ ngoài `software` để prompt nghiên cứu của CAP1 không đổi.
_LANGUAGE_RULES = (
    "- Write every goal and evidence_needs phrase in the same language as the CURRENT REQUEST; "
    "copy key terms exactly as the request writes them, never translate them.\n"
    "- Use the general domain for cross-cutting or unclassified subjects; never route a subject "
    "to a domain whose scope does not cover it.\n"
)
_EXTRACTION_LANGUAGE_RULE = (
    "- Write every description in the same language as the CURRENT REQUEST and keep its key terms "
    "exactly as written; never translate them. Use the general domain for unclassified concerns.\n"
)


def _agent(name: str, scope: str, capabilities: list[str], exclusions: list[str]) -> dict:
    return {"name": name, "scope": scope, "capabilities": capabilities, "exclusions": exclusions}


def _pack(label: str, agents: dict, hints: dict, patterns: list[tuple[str, str]]) -> dict:
    """Bộ ngoài software: neo của mẫu suy ra từ từ khóa tác tử để câu tiếng Việt cũng gọi được mẫu."""
    from app.retrieval.text import terms  # nhập muộn tránh vòng import

    agents = {"general": _GENERAL_AGENT, **agents}
    hints = {"general": (), **hints}
    all_hints = " ".join(h for values in hints.values() for h in values)
    anchors, keywords = {}, {}
    for name, _ in patterns:
        domain_hints = hints.get(name.removeprefix("planning_").removesuffix(".md"), ())
        anchors[name] = frozenset(terms(" ".join(domain_hints) or all_hints))
        # mẫu viết tiếng Anh; từ khóa tiếng Việt chỉ để chấm điểm, không đưa vào prompt (mô hình hay chép nguyên vào evidence_needs)
        keywords[name] = " ".join(domain_hints)
    return {"label": label, "agents": agents, "hints": hints, "patterns": patterns, "anchors": anchors, "pattern_keywords": keywords,
            "plan_rules": _LANGUAGE_RULES, "extraction_rules": _EXTRACTION_LANGUAGE_RULE, "default_domain": "general"}


PACKS: dict[str, dict] = {
    "software": {
        "label": "Phần mềm", "agents": _SOFTWARE_AGENTS, "hints": _SOFTWARE_HINTS, "patterns": _SOFTWARE_PATTERNS,
        "anchors": _SOFTWARE_ANCHORS, "plan_rules": "", "extraction_rules": "", "default_domain": "api_architecture",
    },
    "general": _pack("Tổng quát", {}, {}, [
        ("planning_general.md", "Split a request into one task per independent subject the user asks about; keep the "
         "document's own terms; do not invent subjects that were not requested."),
    ]),
    "education": _pack("Giáo dục", {
        "academic_affairs": _agent(
            "Academic Affairs Analyst", "Training rules: curriculum, credits, registration, grading, exams, academic warning, graduation",
            ["curriculum", "credits", "grading", "exams", "academic warning", "graduation"],
            ["scholarships and tuition", "staff and research rules"]),
        "student_affairs": _agent(
            "Student Affairs Analyst", "Student support and conduct: scholarships, tuition and fee waivers, conduct score, discipline, dormitory, insurance",
            ["scholarship", "tuition", "conduct score", "student discipline", "dormitory"],
            ["curriculum and grading rules", "staff and research rules"]),
        "faculty_research": _agent(
            "Faculty & Research Analyst", "Lecturers and research: teaching workload, research projects, publications, staff evaluation",
            ["teaching workload", "research project", "publication", "staff evaluation"],
            ["student scholarships", "student grading rules"]),
    }, {
        "academic_affairs": ("tín chỉ", "học phần", "đăng ký học", "điểm trung bình", "học kỳ", "cảnh báo học tập", "thôi học",
                             "tốt nghiệp", "chương trình đào tạo", "khảo thí", "kỳ thi", "lịch thi", "chuẩn đầu ra", "bảo lưu",
                             "credit", "curriculum", "grade", "exam", "graduation"),
        "student_affairs": ("học bổng", "học phí", "miễn giảm", "điểm rèn luyện", "rèn luyện", "kỷ luật", "ký túc xá",
                            "khen thưởng", "bảo hiểm y tế", "scholarship", "tuition", "dormitory"),
        "faculty_research": ("giảng viên", "giờ chuẩn", "nghiên cứu khoa học", "đề tài", "công bố", "bài báo", "đánh giá viên chức",
                             "lecturer", "research", "publication"),
    }, [
        ("planning_academic_affairs.md", "Academic rule requests commonly separate eligibility conditions, limits (credits, scores, deadlines), "
         "consequences, and who decides or signs. Keep each asked rule as its own task."),
        ("planning_student_affairs.md", "Scholarship, tuition and discipline requests commonly separate criteria, amounts, the review "
         "procedure step by step, and the approving body. Keep each asked subject as its own task."),
        ("planning_faculty_research.md", "Lecturer and research requests commonly separate workload norms, project procedure, "
         "evaluation criteria and approval authority."),
        ("planning_multi_domain.md", "Requests that mix several education subjects should create one task per independent subject, "
         "keep required order between steps, and avoid inventing subjects that were not requested."),
    ]),
    "legal_admin": _pack("Hành chính – Pháp lý", {
        "legal_basis": _agent(
            "Legal Basis Analyst", "Legal basis: which article or regulation applies, validity, rights, obligations, penalties",
            ["legal article", "validity", "rights and obligations", "penalties"],
            ["step-by-step filing procedure", "commercial contract terms"]),
        "procedure": _agent(
            "Administrative Procedure Analyst", "Administrative procedures: dossier, competent authority, processing time, fees, steps",
            ["dossier", "competent authority", "processing time", "fees"],
            ["interpreting penalties", "commercial contract terms"]),
        "contract": _agent(
            "Contract Analyst", "Contracts: parties, obligations, payment, breach penalties, termination, disputes",
            ["parties", "payment terms", "breach penalty", "termination", "dispute"],
            ["administrative filing steps"]),
    }, {
        "legal_basis": ("điều luật", "nghị định", "thông tư", "luật", "hiệu lực", "căn cứ pháp lý", "xử phạt", "chế tài",
                        "vi phạm hành chính", "quyền và nghĩa vụ", "law", "decree", "regulation"),
        "procedure": ("thủ tục", "hồ sơ", "thẩm quyền", "thời hạn giải quyết", "lệ phí", "tiếp nhận", "một cửa", "giấy phép",
                      "cấp phép", "procedure", "permit", "dossier"),
        "contract": ("hợp đồng", "bên a", "bên b", "thanh lý", "chấm dứt hợp đồng", "tranh chấp", "bồi thường", "phạt vi phạm",
                     "contract", "breach"),
    }, [
        ("planning_legal_basis.md", "Legal questions commonly separate the applicable article, conditions, obligations and the penalty. "
         "Quote article numbers exactly as the documents write them."),
        ("planning_procedure.md", "Procedure questions commonly separate required dossier, steps in order, competent authority, "
         "processing time and fees. Preserve the order of steps."),
        ("planning_contract.md", "Contract questions commonly separate obligations of each party, payment, breach penalties, "
         "termination and dispute resolution."),
        ("planning_multi_domain.md", "Requests that mix legal basis, procedure and contract subjects should create one task per "
         "independent subject and avoid inventing subjects that were not requested."),
    ]),
    "business_hr": _pack("Doanh nghiệp – Nhân sự", {
        "hr_policy": _agent(
            "HR Policy Analyst", "Employment rules: leave, working hours, overtime, pay and benefits, recruitment, labour discipline",
            ["leave", "overtime", "salary and benefits", "recruitment", "labour discipline"],
            ["purchasing and internal workflows", "customer and sales policy"]),
        "operations": _agent(
            "Operations & Process Analyst", "Internal processes: approvals, purchasing, advances and payments, reporting, KPIs",
            ["approval workflow", "purchasing", "advance payment", "reporting", "KPI"],
            ["employee leave and pay", "customer policy"]),
        "sales_customer": _agent(
            "Sales & Customer Analyst", "Customer-facing policy: pricing, discounts, warranty, returns, complaints, sales targets",
            ["pricing", "discount", "warranty", "returns", "complaints"],
            ["employee rules", "internal purchasing"]),
    }, {
        "hr_policy": ("nghỉ phép", "phép năm", "làm thêm giờ", "làm thêm", "tăng ca", "lương", "thưởng", "phúc lợi", "tuyển dụng",
                      "kỷ luật", "chấm công", "bảo hiểm xã hội", "hợp đồng lao động", "thử việc", "leave", "overtime", "payroll"),
        "operations": ("quy trình nội bộ", "phê duyệt", "mua sắm", "tạm ứng", "thanh toán", "kho", "kpi", "báo cáo định kỳ",
                       "đề xuất", "approval", "purchasing", "workflow"),
        "sales_customer": ("khách hàng", "bán hàng", "báo giá", "chiết khấu", "bảo hành", "đổi trả", "khiếu nại", "doanh số",
                           "customer", "sales", "warranty"),
    }, [
        ("planning_hr_policy.md", "HR policy questions commonly separate eligibility, amounts or rates, the request procedure and "
         "who approves at each level. Keep each asked policy as its own task."),
        ("planning_operations.md", "Internal process questions commonly separate steps in order, required documents, approval "
         "levels and limits."),
        ("planning_sales_customer.md", "Customer policy questions commonly separate conditions, time limits, amounts and the "
         "handling procedure."),
        ("planning_multi_domain.md", "Requests that mix several business subjects should create one task per independent subject "
         "and avoid inventing subjects that were not requested."),
    ]),
}

# ---------------- Đợt 5 (19/11, nhóm đã đồng ý): tác tử theo LOẠI VIỆC dùng chung mọi ngành, ngành là kiến thức nạp thêm.
# Chỉ ô chat sản phẩm dùng; bộ Phần mềm và điều kiện A/B/C của thực nghiệm giữ nguyên.
WORK_PACK = "work"
PACKS[WORK_PACK] = _pack("Theo loại việc", {
    "conditions": _agent(
        "Conditions & Rules Analyst", "Who is entitled to what: eligibility conditions, thresholds, limits, required criteria, exceptions",
        ["eligibility", "thresholds", "limits", "criteria", "exceptions"],
        ["step-by-step procedures", "contract obligations", "arithmetic over data tables"]),
    "procedure": _agent(
        "Procedure & Approval Analyst", "How things are done: steps in order, who performs, who approves at each level, deadlines, required documents",
        ["steps", "approval levels", "deadlines", "required documents", "responsible person"],
        ["eligibility thresholds", "contract clause interpretation"]),
    "terms": _agent(
        "Terms & Commitments Analyst", "Rights and obligations: contract clauses, commitments, penalties, termination, disputes, validity of terms",
        ["rights and obligations", "penalties", "termination", "disputes", "clause validity"],
        ["administrative steps", "numeric calculations"]),
    "figures": _agent(
        "Figures & Calculation Analyst", "Numbers in the documents: amounts, rates, percentages, formulas, data tables, computing a value from rules",
        ["amounts", "rates", "percentages", "formulas", "tables"],
        ["approval workflow", "contract interpretation without numbers"]),
}, {
    "conditions": ("có được", "được không", "đủ điều kiện", "điều kiện", "tiêu chuẩn", "ngưỡng", "tối thiểu", "tối đa", "trường hợp nào",
                   "ai được", "đối tượng", "eligible", "eligibility", "condition"),
    "procedure": ("thủ tục", "quy trình", "các bước", "trình tự", "duyệt", "phê duyệt", "cấp duyệt", "hồ sơ", "giấy tờ", "nộp",
                  "thời hạn", "bao lâu thì", "procedure", "approve", "steps"),
    "terms": ("hợp đồng", "điều khoản", "cam kết", "nghĩa vụ", "quyền", "phạt", "bồi thường", "chấm dứt", "tranh chấp", "bên a",
              "bên b", "contract", "clause", "penalty"),
    "figures": ("bao nhiêu", "tính", "số tiền", "tỷ lệ", "phần trăm", "%", "lương", "điểm trung bình", "tổng", "công thức",
                "mức", "how much", "calculate", "rate"),
}, [
    ("planning_conditions.md", "Eligibility questions commonly separate each condition with its threshold, the facts of the case, "
     "and exceptions. Keep each asked condition as its own task."),
    ("planning_procedure.md", "Procedure questions commonly separate steps in order, responsible person, approval level, deadline "
     "and required documents. Preserve the order of steps."),
    ("planning_terms.md", "Contract and commitment questions commonly separate each party's obligations, penalties, termination "
     "and dispute resolution."),
    ("planning_figures.md", "Calculation questions commonly separate the rule or rate, the input numbers and the computation."),
    ("planning_multi_domain.md", "Requests that mix several kinds of work should create one task per independent subject and "
     "avoid inventing subjects that were not requested."),
])

# ---------------- Văn phòng 3D (Đợt 4 kế hoạch Văn phòng, 23/11): 6 chuyên gia ngành + Data Analyst, khớp nhân vật 3D.
# Mặc định của ô chat sản phẩm từ Đợt 9 (23/11, chủ dự án duyệt sau đo Đợt 8); PRODUCT_AGENT_PACK=work để quay về bộ cũ.
# Câu ngoài các ngành này (hành chính – pháp lý, đời sống) do Chuyên viên tổng hợp (`general`) trả lời.
OFFICE_PACK = "office"
PACKS[OFFICE_PACK] = _pack("Văn phòng chuyên gia", {
    "software": _agent(
        "Software & IT Analyst", "Software and IT: requirements, system design, APIs, databases, security, source code, IT operations",
        ["requirements", "architecture", "API", "database", "security", "source code"],
        ["business strategy", "salary and leave rules", "accounting"]),
    "business": _agent(
        "Business & Strategy Analyst", "Running a business: business models, operating plans, sales, partners, commercial contracts, strategy",
        ["business model", "operating plan", "sales", "partners", "commercial contracts", "strategy"],
        ["software design", "employee leave rules", "detailed arithmetic"]),
    "marketing": _agent(
        "Marketing Analyst", "Markets and customers: market research, campaigns, branding, communication, advertising results",
        ["market research", "customers", "campaigns", "branding", "advertising metrics"],
        ["accounting records", "employee rules", "software design"]),
    "hr": _agent(
        "HR & Workplace Rules Analyst", "People at work: recruitment, labour contracts, leave, salary policy, discipline, evaluation, internal rules",
        ["recruitment", "labour contracts", "leave", "salary policy", "discipline", "internal rules"],
        ["marketing campaigns", "software design", "financial statements"]),
    "finance": _agent(
        "Finance & Accounting Analyst", "Money: budgets, costs, revenue, invoices, accounting records, financial statements, taxes, fees",
        ["budget", "costs", "revenue", "invoices", "financial statements", "taxes and fees"],
        ["recruitment", "software design", "marketing creative"]),
    "education": _agent(
        "Education & Research Analyst", "Study and research: academic regulations, credits, grades, scholarships, theses, papers, course material",
        ["academic regulations", "credits and grades", "scholarships", "theses", "research papers"],
        ["company finance", "marketing", "software operations"]),
    "analyst": _agent(
        "Data Analyst", "Numbers in the documents: computing a value from rules, rates, percentages, comparing figures, trends in tables",
        ["calculation", "rates", "percentages", "comparison", "tables", "trends"],
        ["interpreting rules without numbers", "approval workflow"]),
}, {
    "software": ("khóa api", "paynhanh", "merchant", "webhook", "mã hóa", "nfr-", "fr-", "phần mềm", "hệ thống", "api", "cơ sở dữ liệu", "database", "csdl", "bảo mật", "mã nguồn", "code", "lập trình",
                 "yêu cầu chức năng", "kiến trúc", "máy chủ", "đặc tả", "software", "server", "python", "javascript", "thuật toán", "giao thức", "tcp", "udp", "sql", "nosql",
                 "khóa chính", "khóa ngoại", "ràng buộc thực thể", "ràng buộc tham chiếu", "nhật ký kiểm toán"),
    "business": ("quyết định đầu tư", "vốn đầu tư", "góp vốn", "hoàn vốn", "đồng sáng lập", "nhà cung cấp", "quán", "kinh doanh", "doanh nghiệp", "chiến lược", "mô hình kinh doanh", "kế hoạch kinh doanh", "bán hàng", "đối tác",
                 "khách hàng doanh nghiệp", "hợp đồng mua bán", "thương mại", "business", "strategy"),
    "marketing": ("ctr", "cpa", "kol", "tiktok", "facebook", "kênh quảng cáo", "đơn hàng", "marketing", "tiếp thị", "quảng cáo", "chiến dịch", "thương hiệu", "truyền thông", "thị trường", "khách hàng mục tiêu",
                  "ctr", "roas", "fanpage", "campaign"),
    "hr": ("làm việc từ xa", "nghỉ ốm", "quy chế làm việc", "đi muộn", "người lao động", "nhân sự", "nhân viên", "tuyển dụng", "ứng viên", "nghỉ phép", "phép năm", "hợp đồng lao động", "thử việc", "kỷ luật",
           "nội quy", "chấm công", "làm thêm giờ", "bảo hiểm xã hội", "đánh giá nhân viên", "recruit", "leave"),
    "finance": ("khoản chi", "quyết toán", "giá vốn", "thuế thu nhập", "dự phòng", "tài chính", "kế toán", "ngân sách", "chi phí", "doanh thu", "lợi nhuận", "hóa đơn", "thuế", "báo cáo tài chính",
                "công tác phí", "thanh toán", "tạm ứng", "thu chi", "budget", "invoice"),
    "education": ("ôn thi", "kỳ thi", "môn học", "học tập", "khóa chính", "khóa ngoại", "dạng chuẩn", "chuẩn hóa", "bài giảng", "học kỳ", "rèn luyện", "sinh viên", "học phần", "tín chỉ", "điểm trung bình", "học bổng", "tốt nghiệp", "khóa luận", "luận văn", "giảng viên",
                  "học vụ", "nghiên cứu khoa học", "bài báo", "đào tạo", "student", "thesis"),
    # không dùng "tính" đơn lẻ: trùng "tính năng", "tính chất"
    "analyst": ("bao nhiêu", "tính toán", "tính tiền", "tính ra", "tỷ lệ", "phần trăm", "tổng cộng", "trung bình", "so sánh số liệu",
                "xu hướng", "công thức", "how much", "calculate", "rate"),
}, [
    ("planning_software.md", "Software questions commonly separate requirement, design, data, interface and security concerns."),
    ("planning_business.md", "Business questions commonly separate goal, plan, parties and commercial terms."),
    ("planning_marketing.md", "Marketing questions commonly separate audience, campaign, channel and measured results."),
    ("planning_hr.md", "HR questions commonly separate who is covered, the rule or condition, the procedure and the entitlement."),
    ("planning_finance.md", "Finance questions commonly separate the item of money, the rule or rate, and the amount or report."),
    ("planning_education.md", "Education questions commonly separate the student's situation, the academic rule and the required action."),
    ("planning_analyst.md", "Calculation questions commonly separate the rule or rate, the input numbers and the computation."),
    ("planning_multi_domain.md", "Requests that mix several fields should create one task per independent subject and "
     "avoid inventing subjects that were not requested."),
])

# Bộ tác tử được chọn theo ý nghĩa câu hỏi (ô chat sản phẩm).
SELECTION_PACKS = frozenset({WORK_PACK, OFFICE_PACK})


def product_agent_pack() -> str:
    """Bộ tác tử cho ô chat sản phẩm: biến môi trường PRODUCT_AGENT_PACK (work | office), mặc định office (Đợt 9)."""
    name = os.getenv("PRODUCT_AGENT_PACK", OFFICE_PACK).strip().lower()
    return name if name in SELECTION_PACKS else OFFICE_PACK


# Kiến thức ngành nạp cho tác tử theo loại tài liệu trong phạm vi hỏi (nhãn tự phân loại ở đợt 3).
WORK_KNOWLEDGE: dict[str, dict[str, str]] = {
    "contract": {"terms": "For contracts, check the contents listed in Article 398 of the Vietnamese Civil Code 2015 "
                          "(subject, quantity/quality, price and payment, time/place/method, rights and obligations, liability for breach, dispute resolution)."},
    "transcript": {"figures": "Grade tables use the 4-point or 10-point scale as written in the table header; compare numbers exactly as written.",
                   "conditions": "Scholarship or warning thresholds come from the regulation document, not from the grade table."},
    "regulation": {"conditions": "Quote the article (Điều) and clause (Khoản) that sets each threshold.",
                   "procedure": "Regulations name the approving body; copy its title exactly."},
    "internal_rules": {"figures": "Leave and overtime rates come from the internal rules; prorate by months when the rules say so.",
                       "procedure": "Approval levels often depend on the number of days or the amount; pick the level that matches."},
    "legal_doc": {"terms": "Check the effective date and whether the document replaces another before applying it.",
                  "procedure": "Administrative procedures list dossier, competent authority, processing time and fees."},
    "software_spec": {"conditions": "Requirement IDs (FR-, NFR-) identify each requirement; keep them exactly."},
}

_ACTIVE: ContextVar[str] = ContextVar("domain_pack", default=DEFAULT_PACK)
_WORK_DOC_TYPES: ContextVar[frozenset[str]] = ContextVar("work_doc_types", default=frozenset())
_WORK_ALLOWED: ContextVar[tuple[str, ...] | None] = ContextVar("work_allowed", default=None)


@contextmanager
def use_work_context(doc_types, allowed: list[str] | None = None):
    """Bộ "work": loại tài liệu trong phạm vi hỏi (để nạp kiến thức) và các tác tử được chọn cho câu hỏi này."""
    t1 = _WORK_DOC_TYPES.set(frozenset(t for t in doc_types if t))
    t2 = _WORK_ALLOWED.set(tuple(allowed) if allowed else None)
    try:
        yield
    finally:
        _WORK_DOC_TYPES.reset(t1)
        _WORK_ALLOWED.reset(t2)


def pack_name(name: str | None) -> str:
    """Tên bộ hợp lệ; None hoặc rỗng là `software` (hành vi cũ)."""
    name = (name or DEFAULT_PACK).strip()
    if name not in PACKS:
        raise ValueError(f"Unknown domain pack: {name}")
    return name


@contextmanager
def use_pack(name: str | None):
    token = _ACTIVE.set(pack_name(name))
    try:
        yield PACKS[_ACTIVE.get()]
    finally:
        _ACTIVE.reset(token)


def active_pack_name() -> str:
    return _ACTIVE.get()


def active_pack() -> dict:
    return PACKS[_ACTIVE.get()]


def active_domains() -> tuple[str, ...]:
    domains = tuple(active_pack()["agents"])
    allowed = _WORK_ALLOWED.get() if _ACTIVE.get() in SELECTION_PACKS else None
    return tuple(d for d in domains if d in allowed or d == "general") if allowed else domains


# Giữ tên cũ cho mã gọi trực tiếp (công cụ phân tích của ngành Phần mềm).
REGISTRY = _SOFTWARE_AGENTS


def validate_domain(domain: str) -> None:
    if domain not in active_pack()["agents"]:
        raise ValueError(f"Unknown task domain: {domain}")


def profile(domain: str) -> dict:
    validate_domain(domain)
    agent = active_pack()["agents"][domain]
    if _ACTIVE.get() not in SELECTION_PACKS:
        return agent
    if _ACTIVE.get() == OFFICE_PACK:
        # chuyên gia ngành không trùng tên tác tử theo loại việc: nạp mọi ghi chú của loại tài liệu đang hỏi
        notes = list(dict.fromkeys(n for t in sorted(_WORK_DOC_TYPES.get()) for n in WORK_KNOWLEDGE.get(t, {}).values()))
    else:
        notes = [WORK_KNOWLEDGE[t][domain] for t in sorted(_WORK_DOC_TYPES.get()) if domain in WORK_KNOWLEDGE.get(t, {})]
    return {**agent, "scope": agent["scope"] + (" Domain knowledge: " + " ".join(notes) if notes else "")}

