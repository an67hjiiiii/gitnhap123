import json
import re


def decode_structured_json(text: str):
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique_fields)


_ANSWER_FIELD = re.compile(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)', re.S)
_CITATIONS_FIELD = re.compile(r'"citations"\s*:\s*\[([^\]]*)\]', re.S)
_PLACEHOLDER = re.compile(r"[\s.…]*")


def parse_answer_json(text: str) -> dict:
    """Đọc JSON trả lời của worker/vanilla.

    Mô hình chạm giới hạn độ dài thì JSON bị cắt giữa chuỗi: giữ phần "answer" đọc được,
    hạ về PARTIAL và ghi rõ lý do, thay vì để JSONDecodeError làm sập cả lượt chạy.
    """
    text = text.strip()
    whole = re.search(r"\{.*\}", text, re.S)
    for candidate in (text, whole.group(0) if whole else None):
        if candidate is None:
            continue
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    match = _ANSWER_FIELD.search(text)
    if not match:
        return {"status": "PARTIAL", "answer": text, "citations": [], "missing_information": []}
    body = re.sub(r"\\(?:u[0-9a-fA-F]{0,3})?$", "", match.group(1))  # bỏ ký tự thoát bị cắt dở
    try:
        answer = json.loads(f'"{body}"')
    except ValueError:
        answer = body.replace('\\"', '"').replace("\\n", "\n")
    cited = _CITATIONS_FIELD.search(text)
    citations = re.findall(r'"([^"]+)"', cited.group(1)) if cited else []
    return {"status": "PARTIAL", "answer": answer, "citations": citations,
            "missing_information": ["model output truncated"]}


def partial_answer(text: str) -> str | None:
    """Phần "answer" đọc được của JSON đang sinh dở (hiện chữ dần); None khi chưa tới trường answer."""
    match = _ANSWER_FIELD.search(text)
    if not match:
        return None
    body = re.sub(r"\\(?:u[0-9a-fA-F]{0,3})?$", "", match.group(1))  # bỏ ký tự thoát bị cắt dở
    try:
        return json.loads(f'"{body}"')
    except ValueError:
        return body.replace('\\"', '"').replace("\\n", "\n")


def is_placeholder_answer(answer: str) -> bool:
    """Mô hình nhỏ đôi khi chép nguyên mẫu "answer":"..." trong schema."""
    return _PLACEHOLDER.fullmatch(answer or "") is not None
