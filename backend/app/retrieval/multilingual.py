from __future__ import annotations

"""Small, deterministic bilingual query representation for local retrieval.

The original query is always retained.  The bounded alternate representation
only expands generic concepts; it never translates identifiers or produces an
answer.  This is intentionally compatible with the existing hash/lexical
retrieval stack and keeps owner filtering in the caller's existing seams.
"""

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class RetrievalQueryVariant:
    label: str
    text: str
    language: str


_CONCEPTS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("architecture", ("architecture", "kiến trúc"), ("architecture", "kien truc")),
    ("api", ("api", "giao diện lập trình"), ("api", "giao dien lap trinh")),
    ("backend", ("backend", "máy chủ", "phía máy chủ"), ("backend", "may chu", "phia may chu")),
    ("frontend", ("frontend", "giao diện", "giao diện người dùng"), ("frontend", "giao dien", "giao dien nguoi dung")),
    ("database", ("database", "cơ sở dữ liệu"), ("database", "co so du lieu")),
    ("authoritative", ("authoritative", "có thẩm quyền", "chính thức"), ("authoritative", "co tham quyen", "chinh thuc")),
    ("business state", ("business state", "trạng thái nghiệp vụ"), ("business state", "trang thai nghiep vu")),
    ("owner", ("owner", "chủ sở hữu"), ("owner", "chu so huu")),
    ("user", ("user", "người dùng"), ("user", "nguoi dung")),
    ("resource", ("resource", "tài nguyên"), ("resource", "tai nguyen")),
    ("access", ("access", "truy cập"), ("access", "truy cap")),
    ("authentication", ("authentication", "xác thực"), ("authentication", "xac thuc")),
    ("authorization", ("authorization", "phân quyền"), ("authorization", "phan quyen")),
    ("security", ("security", "bảo mật"), ("security", "bao mat")),
    ("transaction", ("transaction", "giao dịch"), ("transaction", "giao dich")),
    ("consistency", ("consistency", "tính nhất quán"), ("consistency", "tinh nhat quan")),
    ("evidence", ("evidence", "bằng chứng"), ("evidence", "bang chung")),
    ("source", ("source", "nguồn"), ("source", "nguon")),
)


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn")


def detect_language(text: str) -> str:
    folded = _fold(text)
    vi_markers = {"cua", "va", "theo", "trong", "nguoi", "du lieu", "khong", "cho", "co"}
    vi = any(marker in folded.split() or marker in folded for marker in vi_markers) or any(
        c in text for c in "ăâđêôơưĂÂĐÊÔƠƯ"
    )
    en = bool(re.search(r"\b(the|what|which|how|when|where|according|must|does|is|are)\b", folded))
    return "mixed" if vi and en else "vi" if vi else "en"


def build_query_variants(query: str) -> list[RetrievalQueryVariant]:
    """Return original plus one bounded cross-language concept representation."""
    language = detect_language(query)
    variants = [RetrievalQueryVariant("original", query, language)]
    folded = _fold(query)
    concepts: list[str] = []
    target = "vi" if language == "en" else "en"
    for canonical, vi_terms, en_terms in _CONCEPTS:
        terms = en_terms if target == "en" else vi_terms
        if any(_fold(term) in folded for term in (*vi_terms, *en_terms)):
            concepts.extend(terms)
    # Keep identifiers and technical terms from the original representation.
    # Only identifier-shaped tokens (API, PostgreSQL, owner_id, HMAC-SHA256): plain words such as
    # unaccented Vietnamese syllables ("thu", "sau") would otherwise pollute the alternate query.
    technical = [token for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_:.+-]{2,}\b", query)
                 if re.search(r"[A-Z0-9_:.+-]", token[1:])]
    expansion = " ".join(dict.fromkeys([*concepts, *technical]))
    if expansion and _fold(expansion) != _fold(query):
        variants.append(RetrievalQueryVariant("cross_language_concepts", expansion, target))
    return variants


__all__ = ["RetrievalQueryVariant", "detect_language", "build_query_variants"]
