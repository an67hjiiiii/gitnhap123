// Trợ giúp cho Không gian làm việc 3 cột (Đợt 2): luật cố định, không gọi mô hình.
import { progressLabel } from './progress.ts';
import type { ProgressEvent } from './progress.ts';

export type SuggestKey = 'conditions' | 'procedure' | 'approver' | 'contract_review' | 'validity';
const fold = (v: string) => v.normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/gi, 'd').toLowerCase();

/** Kỹ năng đề xuất theo loại tài liệu trong phạm vi hỏi và câu đang gõ. Chỉ trả kỹ năng có đường gọi thật. */
export function suggestSkills(docTypes: (string | null | undefined)[], question = ''): { key: SuggestKey; why: string }[] {
  const types = new Set(docTypes.filter(Boolean) as string[]);
  const q = fold(question);
  const out: { key: SuggestKey; why: string }[] = [];
  const add = (key: SuggestKey, why: string) => { if (!out.some(o => o.key === key)) out.push({ key, why }); };
  if (/dieu kien|du dieu kien|co duoc|han muc/.test(q)) add('conditions', 'Câu hỏi về điều kiện');
  if (/quy trinh|cac buoc|thu tuc|lam the nao/.test(q)) add('procedure', 'Câu hỏi về quy trình');
  if (/ai duyet|phe duyet|cap duyet|tham quyen/.test(q)) add('approver', 'Câu hỏi về người duyệt');
  if (types.has('contract')) add('contract_review', 'Có hợp đồng trong phạm vi');
  if (types.has('legal_doc') || types.has('regulation')) { add('validity', 'Có văn bản quy định'); add('conditions', 'Có văn bản quy định'); }
  if (types.has('internal_rules')) { add('procedure', 'Có nội quy'); add('approver', 'Có nội quy'); }
  return out.slice(0, 3);
}

type RunLike = { status?: string; condition?: string; events?: any[]; task_results?: any[]; metrics?: { input_tokens?: number; output_tokens?: number; latency_ms?: number } };

/** Quá trình xử lý của một lượt chạy: các bước (theo sự kiện thật, bỏ trùng), tác tử, token, thời gian. */
export function traceOf(run: RunLike | undefined | null) {
  if (!run) return null;
  const steps: string[] = [];
  for (const e of run.events || []) {
    const label = progressLabel(e as ProgressEvent);
    if (label && steps[steps.length - 1] !== label) steps.push(label);
  }
  const agents = [...new Set((run.task_results || []).map((r: any) => r.domain || r.agent_role).filter(Boolean))] as string[];
  const m = run.metrics || {};
  const tokens = m.input_tokens == null && m.output_tokens == null ? null : (m.input_tokens ?? 0) + (m.output_tokens ?? 0);
  return { steps, agents, tasks: (run.task_results || []).length, tokens, ms: m.latency_ms ?? null, status: run.status ?? null };
}

const STOP = new Set(['nhung', 'cac', 'nao', 'gom', 'la', 'gi', 'co', 'khong', 'the', 'cua', 'cho', 'trong', 've', 'va', 'duoc', 'nay', 'mot', 'bao', 'nhieu', 'tai', 'lieu', 'hay', 'voi', 'khi', 'thi', 'de', 'ai']);
/** Từ khóa của câu hỏi để tô trong đoạn trích (bỏ dấu khi so, bỏ từ chức năng). */
export function keyTerms(question: string): string[] {
  return [...new Set(question.split(/[^\p{L}\p{N}]+/u).filter(w => w.length >= 2 && !STOP.has(fold(w))).map(fold))].slice(0, 12);
}
/** Cắt đoạn văn thành phần thường / phần tô theo từ khóa (so không dấu, giữ nguyên chữ gốc). */
export function highlightParts(text: string, terms: string[]): { t: string; hit: boolean }[] {
  if (!terms.length) return [{ t: text, hit: false }];
  const parts: { t: string; hit: boolean }[] = [];
  for (const tok of text.split(/([\p{L}\p{N}]+)/u)) {
    if (!tok) continue;
    const hit = /[\p{L}\p{N}]/u.test(tok) && terms.includes(fold(tok));
    const last = parts[parts.length - 1];
    if (last && last.hit === hit) last.t += tok; else parts.push({ t: tok, hit });
  }
  return parts;
}
