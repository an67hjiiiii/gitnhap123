from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.research.product_intents import _normalize_intent_text
from app.retrieval.multilingual import detect_language


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    reply: str | None
    needs_llm: bool
    reason: str
    language: str


INTENTS = (
    "greeting",
    "thanks",
    "farewell",
    "out_of_scope",
    "about_system",
    "document_question",
    "general_knowledge",
    "history_answer",
    "corpus_overview",
    "follow_up",
    "ambiguous",
)
# Rules first (cheap, predictable); the model is asked only for ambiguous short messages.
_ARITHMETIC = re.compile(r"\d+(?:[.,]\d+)?\s*(?:[+\-*/x×÷^])\s*\d+")
_VI_CHARS = re.compile("[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]")
_DEFINITION_VI = re.compile(r"^(?:giai thich |cho biet )?[a-z0-9][a-z0-9 .+#/-]{0,40} la (?:gi|cai gi)$")
_DEFINITION_EN = re.compile(r"^(?:what is|what are|what s|define|explain)(?: an?)? (?!the )[a-z0-9][a-z0-9 .+#/-]{0,40}$")
_DOC_WORDS = ("tai lieu", "document", "file", "yeu cau", "requirement", "ho so", "he thong cua", "du an")
_HISTORY_CUES = ("o tren", "vua roi", "luc nay", "ban nay", "truoc do", "ban vua", "o truong hop", "trong truong hop",
                 "above", "earlier", "you just said", "you said", "previous answer", "in case")
_OVERVIEW = ("trong tai lieu co gi", "tai lieu co gi", "co nhung tai lieu nao", "co tai lieu nao", "kho co gi",
             "kho tai lieu co gi", "danh sach tai lieu", "liet ke tai lieu", "tong quan kho", "tong quan tai lieu",
             "cac tai lieu da tai", "what documents", "which documents", "list documents", "list the documents",
             "what s in the documents", "what is in the documents", "what do the documents contain")
_NO_DOCS = ("kien thuc chung", "khong can tai lieu", "khong dung tai lieu", "khong can xem tai lieu",
            "general knowledge", "without the documents", "without documents", "no documents needed")
_GREETINGS = ("xin chao", "chao ban", "chao", "hello", "hi", "hey", "alo")
_THANKS = ("cam on ban", "cam on", "thanks", "thank you")
_FAREWELLS = ("tam biet", "hen gap lai", "bye")
_ABOUT = (
    "ban la ai",
    "ban lam duoc gi",
    "toi co the hoi gi",
    "ban giup duoc gi",
    "who are you",
    "what can you do",
    "how do you work",
    "huong dan su dung",
)
_OUT_OF_SCOPE = (
    "weather",
    "thoi tiet",
    "joke",
    "ke chuyen cuoi",
    "chuyen cuoi",
    "cau chuyen cuoi",
    "bai tho",
    "poem",
    "football score",
    "bong da score",
    "lottery",
    "horoscope",
    "gia vang",
    "recipe",
    "recipes",
    "nau an",
    "translate this for me",
    "translate this",
)
_TECH_TERMS = ("tai lieu", "document", "file", "yeu cau", "requirement", "api", "database", "bao mat", "security")
_FOLLOWUP_TERMS = (
    "no",
    "do",
    "cai do",
    "y do",
    "vay thi",
    "tiep theo",
    "giai thich them",
    "chi tiet hon",
    "it",
    "that",
    "they",
    "them",
    "this one",
    "what about",
)


def _language(message: str, normalized: str) -> str:
    if _VI_CHARS.search(message.casefold()):  # short messages like "REST là gì?" fool the detector
        return "vi"
    lang = detect_language(message)
    if lang == "en" and any(
        normalized == phrase or normalized.startswith(phrase + " ")
        for phrase in (*_GREETINGS[:3], *_THANKS[:2], *_FAREWELLS[:2], *_ABOUT[:5])
    ):
        return "vi"
    return "vi" if lang == "mixed" else lang


def _reply(intent: str, language: str) -> str:
    if language == "vi":
        if intent == "greeting":
            return "Ch\u00e0o b\u1ea1n! H\u00e3y t\u1ea3i t\u00e0i li\u1ec7u l\u00ean r\u1ed3i h\u1ecfi t\u00f4i v\u1ec1 n\u1ed9i dung, API ho\u1eb7c y\u00eau c\u1ea7u trong \u0111\u00f3 nh\u00e9."
        if intent == "thanks":
            return "R\u1ea5t vui \u0111\u01b0\u1ee3c h\u1ed7 tr\u1ee3! B\u1ea1n c\u1ee9 t\u1ea3i t\u00e0i li\u1ec7u l\u00ean v\u00e0 h\u1ecfi th\u00eam v\u1ec1 n\u1ed9i dung trong \u0111\u00f3 nh\u00e9."
        if intent == "farewell":
            return "T\u1ea1m bi\u1ec7t b\u1ea1n! Khi c\u1ea7n, h\u00e3y t\u1ea3i t\u00e0i li\u1ec7u l\u00ean v\u00e0 h\u1ecfi t\u00f4i v\u1ec1 n\u1ed9i dung trong \u0111\u00f3 nh\u00e9."
        if intent == "about_system":
            return "T\u00f4i l\u00e0 tr\u1ee3 l\u00fd t\u00e0i li\u1ec7u k\u1ef9 thu\u1eadt. H\u00e3y t\u1ea3i t\u00e0i li\u1ec7u l\u00ean r\u1ed3i h\u1ecfi v\u1ec1 API ho\u1eb7c y\u00eau c\u1ea7u trong \u0111\u00f3."
        return "T\u00f4i t\u1eadp trung h\u1ed7 tr\u1ee3 t\u00e0i li\u1ec7u k\u1ef9 thu\u1eadt. B\u1ea1n c\u00f3 th\u1ec3 h\u1ecfi \u201cAPI n\u00e0y x\u00e1c th\u1ef1c th\u1ebf n\u00e0o?\u201d ho\u1eb7c \u201cY\u00eau c\u1ea7u b\u1ea3o m\u1eadt l\u00e0 g\u00ec?\u201d"
    if intent == "greeting":
        return "Hello! Upload a document and ask me about its contents, APIs, or requirements."
    if intent == "thanks":
        return "You\u2019re welcome! Upload a document whenever you\u2019re ready, and ask me about it."
    if intent == "farewell":
        return "Goodbye! You can upload a document anytime and ask me about its contents."
    if intent == "about_system":
        return "I\u2019m a technical document assistant. Upload a document and ask me about its APIs or requirements."
    return 'I focus on technical documents. You could ask "How does this API authenticate?" or "What are the security requirements?"'


_DEFINITION_STOP = {"la", "gi", "cai", "what", "is", "are", "s", "a", "an", "the", "define", "explain", "giai", "thich",
                    "cho", "biet", "nghia", "co"}


def definition_terms(message: str) -> list[str]:
    """Key words of a definition-like question ("REST là gì?" -> ["rest"])."""
    return [w for w in _normalize_intent_text(message).split() if w not in _DEFINITION_STOP]


def mentions_terms(terms: list[str], texts) -> bool:
    """True when every key term occurs as a whole word in at least one of the texts."""
    if not terms:
        return False
    for text in texts:
        words = set(_normalize_intent_text(text).split())
        if all(t in words for t in terms):
            return True
    return False


def classify_intent(message: str, *, has_history: bool = False, has_sources: bool = True) -> IntentDecision:
    normalized = _normalize_intent_text(message)
    language = _language(message, normalized)
    words = normalized.split()

    def decision(intent: str, reason: str, *, needs_llm: bool = False) -> IntentDecision:
        reply = (
            _reply(intent, language)
            if intent in {"greeting", "thanks", "farewell", "out_of_scope", "about_system"}
            else None
        )
        return IntentDecision(intent, reply, needs_llm, reason, language)

    for intent, phrases in (("greeting", _GREETINGS), ("thanks", _THANKS), ("farewell", _FAREWELLS)):
        if len(words) <= 6 and any(normalized == phrase or normalized.startswith(phrase + " ") for phrase in phrases):
            return decision(intent, intent.upper())
    if any(normalized == phrase or normalized.startswith(phrase + " ") for phrase in _ABOUT):
        return decision("about_system", "ABOUT_SYSTEM")
    if not any(term in normalized for term in _TECH_TERMS) and any(phrase in normalized for phrase in _OUT_OF_SCOPE):
        return decision("out_of_scope", "OUT_OF_SCOPE")
    if len(words) <= 12 and any(phrase in normalized for phrase in _OVERVIEW):
        return decision("corpus_overview", "OVERVIEW_RULE")
    mentions_docs = any(term in normalized for term in ("tai lieu", "document", "file"))
    if any(phrase in normalized for phrase in _NO_DOCS) or (
        _ARITHMETIC.search(message) and not mentions_docs
        and any(w in normalized for w in ("bang bao nhieu", "tinh", "calculate", "compute", "what is", "=", "bao nhieu"))
    ):
        return decision("general_knowledge", "SELF_CONTAINED")
    if has_history and any(cue in normalized for cue in _HISTORY_CUES):
        return decision("history_answer", "HISTORY_CUE")
    if (_DEFINITION_VI.match(normalized) or _DEFINITION_EN.match(normalized)) and not any(w in normalized for w in _DOC_WORDS):
        return decision("general_knowledge", "DEFINITION")
    if has_history and len(words) <= 8 and any(term in normalized for term in _FOLLOWUP_TERMS):
        return decision("follow_up", "FOLLOW_UP")
    if "?" in message or (
        any(term in normalized for term in ("tai lieu", "document", "file"))
        and words
        and words[0] in {"explain", "describe", "summarize", "review", "phan tich", "giai thich", "cho biet"}
    ):
        return decision("document_question", "NO_SOURCES" if not has_sources else "DOCUMENT_QUESTION")
    if len(words) <= 3 and "?" not in message:
        return decision("ambiguous", "AMBIGUOUS", needs_llm=True)
    return decision("document_question", "NO_SOURCES" if not has_sources else "DOCUMENT_QUESTION")


async def classify_with_llm(provider, message: str) -> IntentDecision:
    language = _language(message, _normalize_intent_text(message))
    schema = {
        "type": "object",
        "properties": {"intent": {"type": "string", "enum": list(INTENTS)}},
        "required": ["intent"],
        "additionalProperties": False,
    }
    try:
        result = await provider.generate_structured(
            system="Classify the message intent. Return the schema only.",
            user=message,
            response_schema=schema,
            max_output_tokens=64,
        )
        payload = json.loads(result.text if hasattr(result, "text") else result)
        intent = payload.get("intent") if isinstance(payload, dict) else None
        if intent not in INTENTS:
            raise ValueError("invalid intent")
        return IntentDecision(intent, None, False, "LLM_CLASSIFIED", language)
    except Exception:
        return IntentDecision("document_question", None, False, "LLM_FALLBACK", language)
