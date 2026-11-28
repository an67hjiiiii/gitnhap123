"""Bước điều phối "chọn nguồn tri thức" (23/11, chỉ ô chat sản phẩm; thực nghiệm A/B/C không đi qua).

Mỗi việc lấy tri thức từ một trong ba nguồn:
- documents: chỉ tài liệu, có trích dẫn (câu hỏi gắn với tài liệu: "theo nội quy…", nêu tên tài liệu);
- general: kiến thức chung của mô hình, gắn nhãn rõ, không trích dẫn (không có tài liệu, hoặc tài liệu không nói tới);
- both: trả lời theo tài liệu, phần giải thích phổ thông tài liệu không có được bổ sung ở dòng "Kiến thức chung:".
Câu gắn với tài liệu mà tài liệu không có vẫn trả lời "tài liệu không nêu", không chuyển sang kiến thức chung.
"""
from __future__ import annotations

import re
import unicodedata

from app.core.answer_checks import apply_calc, clean, strip_invalid_inline_citations
from app.core.structured_output import parse_answer_json
from app.core.types import RunMetrics, TaskResult
from app.ingestion.doc_type import _fold
from app.research.progress import answer_streamer, emit_validated_answer

DOCUMENTS, GENERAL, BOTH = "documents", "general", "both"
GENERAL_MISSING = "answered from general knowledge, not from the user's documents"

_CONCEPT_DEFINITION = re.compile(
    r"^\s*(?:thế nào là|khái niệm|định nghĩa)?\s*(?:nghị định|thông tư|quyết định|nghị quyết|chỉ thị|luật|bộ luật|hợp đồng|nghi dinh|thong tu|quyet dinh|luat)\s+(?:là gì|la gi|như thế nào|nhu the nao)(?:\s|$|[?.,;])"
    r"|^\s*(?:what is|define|explain)\s+(?:a|an|the)?\s*(?:decree|circular|regulation|law|decision)(?:\s|$|[?.,;])",
    re.I,
)
_DOC_BOUND = re.compile(
    r"\b(theo|trong|căn cứ|dựa (vào|trên)|đối chiếu)\s+(các\s+|bản\s+|file\s+)?"
    r"(tài liệu|văn bản|nội quy|quy chế|quy định(?:\s+(?:của\s+)?(?:công ty|phòng|ban|bộ phận|đơn vị))?|hợp đồng|kế hoạch|hướng dẫn|báo cáo|đặc tả|biên bản|chính sách|tệp|bảng)"
    r"|\btài liệu (này|đã (tải|gửi)|của (tôi|công ty|mình)|hiện có)"
    r"|\b(của|tại|trong)\s+(công ty|doanh nghiệp|tổ chức|đơn vị)\b"
    r"|(?:đúng|phù hợp|tuân thủ|vi phạm)\s+(?:nội quy|quy định|quy chế|chính sách|điều khoản)"
    r"|\b(?:nội quy|quy định|quy chế|chính sách)\s+(?:của\s+)?(?:phòng|ban|bộ phận|khối|trường|công ty|doanh nghiệp)\b"
    r"|\b(?:đơn xin nghỉ|trích hợp đồng|bảng chấm công|bảng điểm|phiếu đề xuất)\b(?=[\s\S]{0,400}(?:quy định|nội quy|quy chế|chính sách|phê duyệt|chiết khấu|kiểm tra|đối chiếu))"
    r"|\b(?:within|violate[sd]?|comply with|compliant with|according to)\s+(?:company|internal|department)\s+(?:policy|policies|rules?)\b"
    r"|\b(according to|based on|in) (the|this|my) (document|file|contract|policy|report|plan|manual|spec)",
    re.I,
)
_DOC_BOUND_FOLDED = re.compile(
    r"\b(?:theo|trong|can cu|dua vao|dua tren|doi chieu)\s+(?:cac\s+|ban\s+|file\s+)?"
    r"(?:tai lieu|van ban|noi quy|quy che|quy dinh(?:\s+(?:cua\s+)?(?:cong ty|phong|ban|bo phan|don vi))?|hop dong|ke hoach|huong dan|bao cao|dac ta|bien ban|chinh sach|tep|bang|nghi dinh|thong tu|luat|bo luat|dieu)\b"
    r"|\btai lieu (?:nay|da (?:tai|gui)|cua (?:toi|cong ty|minh)|hien co)"
    r"|\b(?:cua|tai|trong)\s+(?:cong ty|doanh nghiep|to chuc|don vi)\b"
    r"|(?:dung|phu hop|tuan thu|vi pham)\s+(?:noi quy|quy dinh|quy che|chinh sach|dieu khoan)"
    r"|\b(?:noi quy|quy dinh|quy che|chinh sach)\s+(?:cua\s+)?(?:phong|ban|bo phan|khoi|truong|cong ty|doanh nghiep)\b"
    r"|\b(?:don xin nghi|trich hop dong|bang cham cong|bang diem|phieu de xuat)\b(?=[\s\S]{0,400}(?:quy dinh|noi quy|quy che|chinh sach|phe duyet|chiet khau|kiem tra|doi chieu))"
    r"|\b(?:nghi dinh|thong tu|quyet dinh|nghi quyet|chi thi|bo luat|luat)\s+(?:so\s+)?(?=[a-z0-9/\-]*\d)[a-z0-9/\-]{2,}\b"
    r"|\bluat\s+[a-z\s]{2,45}\b(?:19|20)\d{2}\b"
    r"|\b(?:theo|trong|can cu|quy dinh tai)\s+(?:nghi dinh|thong tu|quyet dinh|nghi quyet|chi thi|bo luat)\b"
    r"|\b(?:theo|trong|can cu|quy dinh tai)\s+luat\s+[a-z]{2,}\b"
    r"|\b(?:dieu|khoan)\s+\d+(?:\s+(?:luat|bo luat|nghi dinh|thong tu|quyet dinh|hop dong|noi quy|quy che)\b|\s+cua\s+(?:luat|nghi dinh|thong tu|bo luat)|\b)"
    r"|\b(?:according to|based on|in)\s+(?:the|this|my)\s+(?:document|file|contract|policy|report|plan|manual|spec|decree|circular|regulation|law)\b"
    r"|\b(?:decree|circular|law)\s+(?:no\.?\s*)?(?=[a-z0-9/\-]*\d)[a-z0-9/\-]{2,}\b"
    r"|\b(?:article|section|clause)\s+\d+\s+(?:of|in)\s+(?:the\s+)?(?:law|decree|circular|contract|policy|regulation)\b",
    re.I,
)
def _fold_ks(text: str) -> str:
    s = (text or "").replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii").lower()
_EXPLAIN = re.compile(r"\b(vì sao|tại sao|giải thích|là gì|nghĩa là gì|why|explain|what is)\b", re.I)
_EXPLAIN_FOLDED = re.compile(r"\b(vi sao|tai sao|giai thich|la gi|nghia la gi|why|explain|what is)\b", re.I)

BOTH_HINT = (
    "NGUỒN TRI THỨC: trả lời phần có trong EVIDENCE như quy tắc trên. Nếu một phần câu hỏi là kiến thức phổ thông (giải thích lý do, khái niệm) "
    "mà EVIDENCE không có, được bổ sung ngắn ở một đoạn riêng mở đầu đúng bằng \"Kiến thức chung:\" (không trích dẫn, không gán cho tài liệu). "
    "Không dùng kiến thức chung cho số liệu, quy định, thời hạn của tài liệu."
)

_LABEL = {
    ("vi", False): "**Kiến thức chung** (bạn chưa gửi tài liệu cho câu này, trả lời theo hiểu biết của mô hình, nên kiểm tra lại với nguồn tin cậy):",
    ("vi", True): "Tài liệu bạn gửi không có thông tin này. **Theo kiến thức chung** (không từ tài liệu, nên kiểm tra lại):",
    ("en", False): "**General knowledge** (no documents were provided; answered from the model's knowledge, please verify):",
    ("en", True): "Your documents do not contain this information. **From general knowledge** (not from your documents, please verify):",
}
_ORG_LABEL = {
    "vi": "Không tìm thấy thông tin này trong các tài liệu bạn được phép xem. **Theo kiến thức chung** (không từ tài liệu nội bộ, nên kiểm tra lại):",
    "en": "This information was not found in the documents you have access to. **From general knowledge** (not from internal documents, please verify):",
}


_GENERIC_FILENAME_TOKENS = frozenset({
    "quy", "che", "nhan", "su", "phuc", "loi", "bao", "cao", "tai", "chinh", "marketing", "kien", "truc",
    "nen", "tang", "sla", "chien", "luoc", "thi", "truong", "dao", "tao", "noi", "hop", "dong", "van", "ban",
    "chinh", "sach", "huong", "dan", "dac", "ta", "ke", "hoach", "du", "an", "mau", "phien", "final", "draft",
    "report", "policy", "manual", "guide", "system", "platform", "document", "spec", "architecture", "version",
    "xlsx", "docx", "pdf", "md", "txt", "csv", "xls", "pptx", "company", "cong", "ty", "he", "thong", "lo", "trinh",
})


def _corpus_entity_tokens(corpus_names: list[str] | None) -> set[str]:
    """Trích các định danh riêng nổi bật từ tên tài liệu trong kho (vd. 'vietcore', 'novatech', 'paynhanh')."""
    if not corpus_names:
        return set()
    entities: set[str] = set()
    for name in corpus_names:
        stem = str(name or "").rsplit(".", 1)[0]
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9]{4,}", stem):
            low = tok.casefold()
            if low not in _GENERIC_FILENAME_TOKENS and not re.fullmatch(r"v\d+.*", low):
                if any(ch.isupper() for ch in tok[1:]) or tok[0].isupper():
                    entities.add(low)
    return entities


def doc_bound(query: str, named_documents: list[str] | None = None, corpus_names: list[str] | None = None) -> bool:
    """Câu hỏi gắn với tài liệu hoặc thực thể/doanh nghiệp nội bộ trong kho: chỉ được trả lời từ tài liệu."""
    if named_documents:
        return True
    q = (query or "").strip()
    if not q or _CONCEPT_DEFINITION.search(q):
        return False
    if _DOC_BOUND.search(q) or _DOC_BOUND_FOLDED.search(_fold_ks(q)):
        return True
    entities = _corpus_entity_tokens(corpus_names)
    if entities:
        q_tokens = {t.casefold() for t in re.findall(r"[A-Za-z0-9]{5,}", q)}
        if entities & q_tokens:
            return True
    return False


def _query_grounded_in_evidence(query: str, evidence: list | None) -> bool:
    """Kiểm tra phần nội dung chính ngoài cụm giải thích chung có thực sự khớp với bằng chứng đã truy xuất hay không."""
    if not evidence:
        return False
    from app.retrieval.text import terms
    folded = _fold(query or "")
    main = re.sub(
        r"^\s*(?:the nao la\s+)?(?:nghi dinh|thong tu|quyet dinh|nghi quyet|chi thi|luat|bo luat|hop dong)\s+(?:la gi|nhu the nao)\b",
        "",
        folded,
    ).strip()
    q_terms = terms(main or folded) - {"va", "nhu", "the", "nao", "la", "gi", "vi", "sao", "lam", "de", "ra", "mot"}
    if not q_terms:
        return False
    ev_terms = set().union(*(terms(getattr(c, "text", str(c))) for c in evidence[:4]))
    overlap = len(q_terms & ev_terms) / max(1, min(len(q_terms), 6))
    return overlap >= 0.34


def choose_source(query: str, evidence_count: int, *, bound: bool, evidence: list | None = None) -> str:
    if bound:
        return DOCUMENTS
    if evidence_count == 0:
        return GENERAL
    q = (query or "").strip()
    if _CONCEPT_DEFINITION.search(q) and evidence is not None and not _query_grounded_in_evidence(q, evidence):
        return GENERAL
    return BOTH if (_EXPLAIN.search(q) or _EXPLAIN_FOLDED.search(_fold(q))) else DOCUMENTS


def label(reply_language: str | None, had_documents: bool, *, in_org: bool = False) -> str:
    lang = "en" if reply_language == "en" else "vi"
    if in_org and had_documents:
        return _ORG_LABEL[lang]
    return _LABEL[(lang, had_documents)]


async def answer_general(provider, question: str, metrics: RunMetrics, *, task_id: str = "T1", domain: str = "general",
                         role: str = "General Assistant", reply_language: str | None = None, had_documents: bool = False,
                         max_output_tokens: int | None = None, user_request: str | None = None, stream: bool = False,
                         in_org: bool = False, num_ctx: int | None = None,
                         request_timeout: float | None = None,
                         keep_alive: str | int | float | None = None) -> TaskResult:
    """Trả lời bằng kiến thức chung của mô hình. Nhãn do mã gắn (không để mô hình tự quyết), không có trích dẫn."""
    english = reply_language == "en"
    org_guard = (
        " Never claim that an internal project code, salary, or organization policy 'does not exist in reality'; "
        "simply note that it is not available in the accessible documents."
        if in_org else ""
    )
    system = (
        f"GENERAL_KNOWLEDGE_ANSWERER. Role={role}. The user's documents do not cover this question, so answer from well-established "
        "general knowledge. Be accurate and concise. If checking internal company rules, policies, deadlines, or attached forms is required "
        "and internal evidence is missing, state clearly that internal evidence is missing instead of guessing or fabricating compliance. "
        "If a fact is uncertain, depends on country or may have changed recently "
        "(laws, prices, versions), say so briefly instead of guessing. Never invent the current date, current year, document citations, "
        "article numbers or exact figures. "
        "Do not say the answer comes from the user's documents. Do not mention internal task IDs." + org_guard + " "
        + ("Write the answer in English." if english else "Viết câu trả lời bằng tiếng Việt, kể cả khi câu hỏi hoặc mục tiêu việc viết bằng tiếng Anh.")
    )
    context = f"USER REQUEST (full question, for context):\n{user_request[:2500]}\n\n" if user_request and user_request != question else ""
    user = (
        f"{context}QUESTION TO ANSWER:\n{question}\n\n"
        + ("Write in English as Markdown. " if english else "Viết bằng tiếng Việt, dạng Markdown. ")
        # đo 23/11: prompt ép tiêu đề/mục làm mô hình 4B tự thêm chi tiết bịa ("thủ đô Úc là Sydney… theo Luật…"); câu đơn giản phải ngắn
        + ("Match the length to the question: a simple factual question gets 1-3 plain sentences with NO headings and no extra facts "
           "(population, laws, history) the user did not ask for. Only multi-part, how-to, comparison or planning requests get '### ' headings, "
           "numbered steps or a Markdown table (at most about 300 words). Code goes in fenced code blocks. "
           "Any number that needs calculating must be written ONLY as [[= expression ]] (digits, + - * / // and parentheses; powers as repeated "
           "multiplication, e.g. 100*1.06*1.06), also in the opening sentence; never write a computed result yourself, the system replaces it.")
        + ' Return JSON {"answer": "<Markdown answer>"}.'
    )
    structured = getattr(provider, "generate_structured", None)
    limit_ok = max_output_tokens is not None and getattr(provider, "supports_per_call_output_tokens", False)
    extra_opts: dict = {}
    if num_ctx is not None and getattr(provider, "supports_num_ctx", False):
        extra_opts["num_ctx"] = num_ctx
    if request_timeout is not None and getattr(provider, "supports_per_call_timeout", False):
        extra_opts["timeout"] = request_timeout
    if keep_alive is not None and getattr(provider, "supports_keep_alive", False):
        extra_opts["keep_alive"] = keep_alive
    if callable(structured) and limit_ok:
        result = await structured(system=system, user=user, response_schema={"type": "object", "properties": {"answer": {"type": "string"}},
                                                                             "required": ["answer"], "additionalProperties": False},
                                  max_output_tokens=max_output_tokens, **extra_opts, **(answer_streamer(provider, buffered=True) if stream else {}))
    else:
        result = await provider.generate(system=system, user=user, **extra_opts)
    metrics.add_usage(result.usage)
    text = str(parse_answer_json(result.text).get("answer") or "").strip() or result.text.strip()
    text = apply_calc(clean(text))
    text, _ = strip_invalid_inline_citations(text, set())
    if not text:
        return TaskResult(task_id=task_id, domain=domain, status="NO_EVIDENCE", answer="", missing_information=["general answer was empty"],
                          source=GENERAL)
    final_answer = f"{label(reply_language, had_documents, in_org=in_org)}\n\n{text}"
    if stream:
        emit_validated_answer(final_answer)
    return TaskResult(task_id=task_id, domain=domain, status="PARTIAL" if had_documents else "COMPLETE",
                      answer=final_answer,
                      missing_information=[GENERAL_MISSING], source=GENERAL)
