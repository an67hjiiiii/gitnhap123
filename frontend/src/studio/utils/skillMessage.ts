// Thẻ kết quả kỹ năng lưu trong cuộc trò chuyện: "<tóm tắt>" + "<!--skill-card:{json}-->" (backend /api/conversations/skill-card).
export type StoredCard = { skill: string; label: string; reason: string; data: any };

const MARK = /<!--skill-card:([\s\S]*?)-->/;

export function parseSkillMessage(content: string): { summary: string; card: StoredCard } | null {
  const m = MARK.exec(content || '');
  if (!m) return null;
  try {
    const card = JSON.parse(m[1]);
    return card && typeof card.skill === 'string' && card.data ? { summary: content.replace(MARK, '').trim(), card } : null;
  } catch { return null; }
}

const OVERALL: Record<string, string> = { ELIGIBLE: 'Đủ điều kiện', NOT_ELIGIBLE: 'Không đủ điều kiện', INSUFFICIENT_INFO: 'Thiếu dữ kiện để kết luận', NO_RULE: 'Không thấy quy định phù hợp', UNRESOLVED: 'Chưa xác định' };

/** Một dòng tóm tắt dễ đọc: hiện trong lịch sử và là phần duy nhất đưa vào ngữ cảnh câu hỏi tiếp nối. */
export function summarizeSkill(skill: string, label: string, data: any): string {
  const head = `Kỹ năng ${label}: `;
  switch (skill) {
    case 'conditions': return head + (OVERALL[data.overall] ?? 'Chưa xác định') + (data.conditions?.length ? ` (${data.conditions.map((c: any) => `${c.condition}: ${c.verdict === 'MET' ? 'đạt' : c.verdict === 'NOT_MET' ? 'không đạt' : 'chưa rõ'}`).join('; ')})` : '') + '.';
    case 'procedure': return head + (data.steps?.length ? `${data.steps.length} bước: ${data.steps.map((s: any) => s.action).join(' → ')}` : 'không thấy các bước trong tài liệu') + '.';
    case 'approver': return head + (data.approver ? `người duyệt là ${data.approver}` : 'không thấy quy định cấp duyệt') + '.';
    case 'contract_review': return head + (data.risks?.length ? `${data.risks.length} điều khoản cần lưu ý` : 'không thấy điều khoản rủi ro rõ ràng') + '.';
    case 'validity': return head + (data.documents || []).map((d: any) => `${d.number || d.source_name}: ${d.status}`).join('; ') + '.';
    case 'quiz': return head + (data.items?.length ? `${data.items.length} câu: ${data.items.map((q: any) => q.question).join(' | ').slice(0, 400)}` : 'chưa tạo được câu hỏi có căn cứ') + '.';
    case 'compare': { const c = data.counts || {}; return head + `${data.old?.source_name} → ${data.new?.source_name}: thêm ${c.ADDED ?? 0}, sửa ${(c.MODIFIED ?? 0) + (c.MOVED_MODIFIED ?? 0)}, bỏ ${c.REMOVED ?? 0}, giữ ${c.UNCHANGED ?? 0} mục.`; }
    default: return head.trim();
  }
}
