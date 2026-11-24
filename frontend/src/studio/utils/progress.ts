// Tên bước của pipeline (sự kiện backend gửi qua /api/chat/stream) → câu tiếng Việt cho người dùng; null = không hiện.
export type ProgressEvent = { stage: string; task_id?: string; classification?: string; agents?: string[]; source?: string; has_documents?: boolean; document_bound?: boolean };
const AGENT_VI: Record<string, string> = { conditions: 'Điều kiện', procedure: 'Quy trình', terms: 'Điều khoản', figures: 'Số liệu', general: 'Tổng hợp' };

export function progressLabel(e: ProgressEvent): string | null {
  const n = e.task_id?.match(/\d+/)?.[0];  // "T2", "task_2"
  const t = n ? `Nhiệm vụ ${n}` : 'Tác tử';
  switch (e.stage) {
    case 'product_request_routing':
      return e.classification === 'SIMPLE_PROJECT_QUESTION' ? 'Câu hỏi một ý: tìm trong tài liệu để trả lời thẳng' : 'Yêu cầu nhiều ý: chia việc cho các tác tử';
    case 'agent_selection': return e.agents?.length ? `Chọn tác tử: ${e.agents.map(a => AGENT_VI[a] ?? a).join(', ')}` : null;
    case 'request_understanding': case 'follow_up_resolved': return 'Đang hiểu câu hỏi';
    case 'vanilla_retrieval': return 'Đã tìm đoạn liên quan, đang viết câu trả lời';
    case 'obligation_concern_extraction': return 'Đang tách các việc cần làm trong yêu cầu';
    case 'planning_retrieval': return 'Đang tìm tài liệu để lập kế hoạch';
    case 'planning_generation': case 'decomposition': return 'Đang lập kế hoạch nhiều bước';
    case 'plan_verification': case 'planning_repair': case 'plan_anchoring': return 'Đang kiểm tra kế hoạch';
    case 'validated_plan_handoff': return 'Kế hoạch đạt, giao việc cho các tác tử';
    case 'knowledge_source_policy':
      return e.document_bound ? 'Câu hỏi theo tài liệu: chỉ dùng tài liệu' : e.has_documents ? 'Dùng tài liệu trước, thiếu thì bổ sung kiến thức chung' : 'Không có tài liệu: trả lời bằng kiến thức chung';
    case 'knowledge_source': return e.source === 'general' ? `${t}: trả lời bằng kiến thức chung` : e.source === 'both' ? `${t}: tài liệu + kiến thức chung` : null;
    case 'task_retrieval': return `${t}: đang đọc tài liệu`;
    case 'task_completed': return `${t}: xong`;
    case 'planning_rejected': return 'Kế hoạch chưa qua bước kiểm tra';
    default: return null;
  }
}
