"""Đợt 4: thẻ kết quả kỹ năng lưu trong tin nhắn; ngữ cảnh hội thoại cho mô hình chỉ lấy dòng tóm tắt."""
from app.research.conversation_context import build_conversation_context


def test_skill_card_payload_is_not_sent_to_model_context():
    card = '<!--skill-card:{"skill":"approver","data":{"approver":"Giám đốc khối","rule":"a \u003e b"}}-->'
    conv = {"messages": [
        {"message_id": "m1", "role": "USER", "content": "Nghỉ 6 ngày ai duyệt?"},
        {"message_id": "m2", "role": "ASSISTANT", "content": "Kỹ năng Ai duyệt: Giám đốc khối.\n\n" + card},
    ]}
    ctx = build_conversation_context(conv)
    assert "Kỹ năng Ai duyệt: Giám đốc khối." in ctx.text
    assert "skill-card" not in ctx.text and '"approver"' not in ctx.text


def test_plain_messages_unchanged():
    conv = {"messages": [{"message_id": "m1", "role": "USER", "content": "Thử việc bao lâu?"},
                         {"message_id": "m2", "role": "ASSISTANT", "content": "Tối đa 60 ngày <b>[src_x_c0]</b>."}]}
    assert "Tối đa 60 ngày <b>[src_x_c0]</b>." in build_conversation_context(conv).text
