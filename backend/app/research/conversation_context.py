from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_MAX_MESSAGES = 6
DEFAULT_MAX_CHARS = 6_000


@dataclass(frozen=True)
class ConversationContext:
    """Bounded same-conversation history, never corpus evidence."""

    text: str = ""
    message_ids: tuple[str, ...] = ()
    truncated: bool = False
    last_user_request: str = ""

    def to_trace(self) -> dict[str, Any]:
        return {
            "message_ids": list(self.message_ids),
            "message_count": len(self.message_ids),
            "chars": len(self.text),
            "truncated": self.truncated,
            "source": "conversation_history",
            "is_rag_evidence": False,
        }


def build_conversation_context(
    conversation: Mapping[str, Any] | None,
    *,
    current_message_id: str | None = None,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ConversationContext:
    """Render only recent messages from one already-authorized conversation."""

    if not isinstance(conversation, Mapping):
        return ConversationContext()
    rows = conversation.get("messages")
    if not isinstance(rows, list):
        return ConversationContext()
    message_limit = max(0, int(max_messages))
    char_limit = max(0, int(max_chars))
    eligible = [
        item
        for item in rows
        if isinstance(item, Mapping)
        and str(item.get("message_id") or "") != str(current_message_id or "")
        and str(item.get("role") or "").upper() in {"USER", "ASSISTANT"}
        and isinstance(item.get("content"), str)
        and item.get("content", "").strip()
    ]
    selected = eligible[-message_limit:] if message_limit else []
    truncated = len(selected) < len(eligible)
    rendered_reversed: list[str] = []
    kept_ids_reversed: list[str] = []
    used = 0
    last_user_request = ""
    for item in reversed(selected):
        role = str(item.get("role") or "").upper()
        content = str(item.get("content") or "").strip()
        line = f"[{role}] {content}"
        remaining = char_limit - used
        if remaining <= 0:
            truncated = True
            break
        if len(line) > remaining:
            line = line[:remaining].rstrip()
            truncated = True
        if not line:
            truncated = True
            break
        rendered_reversed.append(line)
        kept_ids_reversed.append(str(item.get("message_id")))
        if role == "USER" and not last_user_request:
            last_user_request = line[len("[USER] "):]
        used += len(line)
        if used >= char_limit:
            if len(rendered_reversed) < len(selected):
                truncated = True
            break
    rendered = "\n".join(reversed(rendered_reversed))
    if len(rendered) > char_limit:
        rendered = rendered[:char_limit].rstrip()
        truncated = True
    return ConversationContext(
        text=rendered,
        message_ids=tuple(reversed(kept_ids_reversed)),
        truncated=truncated,
        last_user_request=last_user_request,
    )


# Câu hỏi tiếp nối ngắn ("Làm sao cho an toàn?", "Còn hoàn tiền thì sao?") thường không nhắc lại chủ đề.
_FOLLOW_MARKERS = re.compile(
    r"\b(nó|đó|đấy|kia|ở trên|nói trên|trước đó|vừa rồi|như vậy|như thế|thế còn|còn|vậy thì|thì sao|tiếp theo|chi tiết hơn|"
    r"cụ thể hơn|ví dụ|it|its|they|them|that|this|those|what about|how about)\b",
    re.IGNORECASE,
)
_FILLER = set("""gì nào sao làm thế bao nhiêu ai đâu hãy giúp tôi bạn ở là những cách có được không thì khi như cái các và của
cho với trong về từ theo nếu này đó kia một mình nó vậy còn nữa thêm cần phải nên muốn biết hơn rõ cụ thể chi tiết ví dụ
the what how why when which who is are do does a an of to in for on and or it this that""".split())


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("đ", "d")


def resolve_follow_up(query: str, context: ConversationContext) -> str | None:
    """Câu hỏi trước mà câu này đang hỏi tiếp, hoặc None nếu câu này tự đủ nghĩa.

    Coi là hỏi tiếp khi có từ chỉ trỏ ("nó", "còn ... thì sao") hoặc câu chỉ còn tối đa hai chữ nội dung
    sau khi bỏ hư từ. Lịch sử chỉ dùng để hiểu ý, không bao giờ là bằng chứng.
    """
    previous = (context.last_user_request or "").strip()
    if not previous or _fold(previous) == _fold(query.strip()):
        return None
    filler = {_fold(w) for w in _FILLER}
    content = [w for w in re.findall(r"\w+", _fold(query)) if w not in filler and not w.isdigit()]
    if _FOLLOW_MARKERS.search(query) or len(content) <= 2:
        return previous
    return None


__all__ = [
    "ConversationContext",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MAX_MESSAGES",
    "build_conversation_context",
    "resolve_follow_up",
]
