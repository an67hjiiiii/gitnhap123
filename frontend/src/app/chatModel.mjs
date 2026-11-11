export const NO_EVIDENCE_COPY =
  "Không tìm thấy bằng chứng phù hợp trong các nguồn kiến thức hiện có. Bạn có thể tải thêm tài liệu hoặc đặt câu hỏi dựa trên các nguồn đang ở trạng thái READY.";

export function researchModeFromFlag(value) {
  return String(value ?? "").trim().toLowerCase() === "true";
}

export function displayConversationTitle(conversation) {
  const storedTitle = String(conversation?.title ?? "").trim();
  const cleanTitle = storedTitle.replace(/^Demo:\s*/i, "").trim();
  return cleanTitle || String(conversation?.first_message ?? "").trim().slice(0, 72) || "Cuộc trò chuyện mới";
}

export function conversationSidebarItems(conversations = []) {
  const seen = new Set();
  return conversations.filter((conversation) => {
    const id = String(conversation?.conversation_id ?? "");
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  }).map((conversation) => ({
    ...conversation,
    label: displayConversationTitle(conversation),
  }));
}

export function messagesForConversation(conversation, requestedConversationId) {
  if (!conversation || conversation.conversation_id !== requestedConversationId) return [];
  return [...(Array.isArray(conversation.messages) ? conversation.messages : [])]
    .sort((left, right) => Number(left.sequence_number ?? 0) - Number(right.sequence_number ?? 0));
}

export function buildChatRequest({ message, conversationId, researchMode, condition, provider }) {
  const body = { message };
  if (conversationId) body.conversation_id = conversationId;
  if (researchMode) {
    body.condition = condition;
    body.provider = provider;
  } else {
    body.product_mode = true;
  }
  return body;
}

export function productAnswerText(messageContent, run) {
  const status = String(run?.status ?? "").toUpperCase();
  if (status === "NO_EVIDENCE") return NO_EVIDENCE_COPY;
  if (status === "FAILED") return "Không thể hoàn thành yêu cầu này. Hãy thử lại sau.";

  const candidate = String(messageContent ?? run?.answer ?? "").trim();
  if (!candidate) return "Chưa có câu trả lời cho lượt chạy này.";
  if (candidate.toUpperCase() === "NO_EVIDENCE") return NO_EVIDENCE_COPY;
  if (candidate.toUpperCase() === "FAILED") return "Không thể hoàn thành yêu cầu này. Hãy thử lại sau.";
  if (candidate.startsWith("{") || candidate.startsWith("[")) {
    try {
      const parsed = JSON.parse(candidate);
      const answer = parsed && typeof parsed === "object"
        ? [parsed.answer, parsed.final_answer, parsed.text].find((value) => typeof value === "string" && value.trim())
        : null;
      if (answer) return answer.trim();
    } catch {
      // Keep malformed structured output out of the product answer surface.
    }
      return "Câu trả lời chưa sẵn sàng để hiển thị. Bạn có thể thử lại.";
  }
  return candidate;
}
