// Chuyển bản ghi lượt chạy của CAP1 (/api/chat, /api/runs/{id}) sang dạng các màn hình Studio đang dùng.
// Chỉ ánh xạ số đo có thật; số CAP1 không đo (token tiết kiệm, độ phủ, CPU, token theo từng tác tử) để null.
import { AgentResult, ContextChunk, ExecutionMode, ModeExecutionResult, SubTask } from '../types';

export type Cap1Run = Record<string, any>;

export const MODE_TO_CONDITION: Record<Exclude<ExecutionMode, 'ablation_comparison'>, string> = {
  vanilla_rag: 'A', naive_multi_agent: 'B', proposed_adaptive: 'C',
};
const CONDITION_TO_MODE: Record<string, ModeExecutionResult['mode']> = {
  A: 'vanilla_rag', B: 'naive_multi_agent', C: 'proposed_adaptive', 'C-P': 'proposed_adaptive', 'C-N': 'proposed_adaptive', 'C-O': 'proposed_adaptive',
};
export const CONDITION_LABEL: Record<string, string> = {
  A: 'Vanilla RAG (A)', B: 'Multi-Agent cơ bản (B)', C: 'Điều phối đầy đủ (C)',
  'C-P': 'C bỏ lập kế hoạch (C-P)', 'C-N': 'C bỏ chuẩn hóa (C-N)', 'C-O': 'C bỏ tối ưu ngữ cảnh (C-O)',
};
const ROLE: Record<string, string> = { database: 'DatabaseAgent', api_architecture: 'APIAgent', security: 'SecurityAgent',
  // tác tử của các bộ lĩnh vực ngoài Phần mềm (backend app/research/registry.py): hiện tên tiếng Việt
  general: 'Tổng hợp', academic_affairs: 'Học vụ', student_affairs: 'Công tác sinh viên', faculty_research: 'Giảng viên – Nghiên cứu',
  legal_basis: 'Căn cứ pháp lý', procedure: 'Quy trình và phê duyệt', contract: 'Hợp đồng',
  // bộ theo loại việc (đợt 5); "procedure" dùng chung tên với bộ Hành chính – Pháp lý
  conditions: 'Điều kiện và quy định', terms: 'Điều khoản và cam kết', figures: 'Số liệu và tính toán',
  hr_policy: 'Chính sách nhân sự', operations: 'Quy trình nội bộ', sales_customer: 'Khách hàng – Bán hàng',
  // bộ office (văn phòng 3D, 23/11)
  software: 'Phần mềm và CNTT', business: 'Kinh doanh và chiến lược', marketing: 'Marketing', hr: 'Nhân sự', finance: 'Tài chính và kế toán',
  education: 'Giáo dục và nghiên cứu', analyst: 'Phân tích số liệu' };

// Câu trả lời của worker/synthesizer đôi khi là chuỗi JSON; lấy phần chữ như giao diện chat CAP1 (chatModel.mjs).
export function answerText(raw: unknown): string {
  const text = String(raw ?? '').trim();
  if (!text.startsWith('{')) return text;
  try {
    const parsed = JSON.parse(text);
    const own = [parsed.answer, parsed.final_answer, parsed.text].find(v => typeof v === 'string' && v.trim());
    if (own) return own;
    // Bộ tổng hợp đôi khi chép lại cả cấu trúc {"task_results":[{"answer":...}]}: ghép phần chữ của từng việc.
    const parts = (Array.isArray(parsed.task_results) ? parsed.task_results : []).map((r: any) => r?.answer).filter((v: unknown) => typeof v === 'string' && v.trim());
    return parts.length ? parts.join('\n\n') : text;
  } catch {
    // JSON bị cụt (mô hình chạm giới hạn độ dài): lấy phần "answer" đọc được, bỏ ký tự thoát.
    const m = text.match(/"(?:answer|final_answer|text)"\s*:\s*"((?:[^"\\]|\\.)*)/);
    if (!m) return text;
    const body = m[1].replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
    return text.trimEnd().endsWith('}') ? body : `${body}\n\n_(Câu trả lời bị cắt do chạm giới hạn độ dài của mô hình.)_`;
  }
}

const event = (run: Cap1Run, stage: string) => (run.events || []).find((e: any) => e.stage === stage);

export function modeOf(condition: string): ModeExecutionResult['mode'] {
  return CONDITION_TO_MODE[(condition || '').toUpperCase()] ?? 'proposed_adaptive';
}

export function adaptRun(run: Cap1Run): ModeExecutionResult {
  const m = run.metrics || {};
  const tasks: any[] = run.tasks || [];
  const results: any[] = run.task_results || [];
  const handoff = event(run, 'validated_plan_handoff');
  const retrievals: any[] = (run.events || []).filter((e: any) => e.stage === 'task_retrieval');
  const subtasks: SubTask[] = tasks.map(t => {
    const r = results.find(x => x.task_id === t.task_id);
    const rt = retrievals.find(e => e.task_id === t.task_id);
    return {
      id: t.task_id, agent_role: ROLE[t.domain] ?? t.domain, title: t.goal, description: t.goal,
      retrieval_query: (t.evidence_needs || []).join('; '),
      status: r ? (r.status === 'FAILED' ? 'failed' : 'completed') : 'pending',
      requirement_ids: t.covers_obligations ?? undefined, depends_on: t.depends_on,
      evidence_ids: r?.evidence_ids, assigned_context_count: rt?.selected?.length ?? 0, output: r?.answer,
    };
  });
  const agent_results: AgentResult[] = results.map(r => {
    const t = tasks.find(x => x.task_id === r.task_id);
    const chunks: ContextChunk[] = (r.evidence_ids || []).map((id: string) => ({
      id, text: '', source_file: id, file_type: '', domain_tags: [], similarity_score: 0,
    }));
    return {
      task_id: r.task_id, agent_role: ROLE[r.domain] ?? r.domain, subtask_title: t?.goal ?? r.task_id,
      latency_ms: null as unknown as number, tokens_used: null as unknown as number, // CAP1 không đo token theo từng tác tử
      content: [answerText(r.answer), r.missing_information?.length ? `\n\nThông tin còn thiếu: ${r.missing_information.join('; ')}` : ''].join(''),
      relevant_chunks: chunks,
    };
  });
  const status = String(run.status || '');
  return {
    mode: modeOf(run.condition),
    mode_display_name: CONDITION_LABEL[run.condition] ?? `Điều kiện ${run.condition}`,
    latency_ms: Number(m.latency_ms ?? 0),
    total_tokens: Number(m.input_tokens ?? 0) + Number(m.output_tokens ?? 0),
    prompt_tokens: Number(m.input_tokens ?? 0),
    completion_tokens: Number(m.output_tokens ?? 0),
    tokens_saved: null,
    token_saving_ratio: null,
    cpu_percent: m.cpu_percent ?? (null as unknown as number),
    ram_usage_mb: m.peak_rss_mb ?? (null as unknown as number),
    ram_delta_mb: null as unknown as number,
    task_coverage: null,
    subtasks,
    agent_results,
    final_answer: status && status !== 'COMPLETE' ? `**Trạng thái: ${status}**\n\n${answerText(run.answer)}` : answerText(run.answer),
    retrieved_chunks_count: Number(m.retrieved_chunks ?? 0),
    raw: run,
    planning_trace: {
      requirements: (handoff?.obligations || []).map((o: any) => ({ id: o.obligation_id, text: o.description })),
      execution_order: handoff?.execution_order,
    },
    execution_trace: results.map(r => ({ task_id: r.task_id, status: r.status, depends_on: tasks.find(t => t.task_id === r.task_id)?.depends_on ?? [], elapsed_ms: 0 })),
  };
}
