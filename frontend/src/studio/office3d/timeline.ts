// Đợt 5 (23/11): dòng thời gian 2D "ai làm gì, mất bao lâu" của một lượt chạy, dựng từ run.events.
// Dùng lại LiveDirector nên các bước khớp đúng với văn phòng 3D. Nhẹ, không phụ thuộc three.js.
// Thời gian chỉ lấy từ mốc ts thật; thiếu mốc thì null (giao diện không ghi số).
import { LiveDirector, type LiveController, type LiveEvent, type LiveStepState } from './liveDirector.ts';
import type { AgentId } from './types';

export interface TimelineGroup {
  actor: AgentId;
  who: string;              // tên người làm
  steps: string[];          // các bước gộp trong nhóm (theo thứ tự)
  ms: number | null;        // tổng thời gian đo được của các bước
  state: LiveStepState;     // 'fail' nếu có bước lỗi
  eventIndex: number;       // chỉ số sự kiện (trong danh sách có stage) bắt đầu nhóm: dùng để tua văn phòng
}

const WHO: Partial<Record<AgentId, string>> = {
  orchestrator: 'Điều phối', rag: 'RAG', reviewer: 'Reviewer', integrator: 'Tổng hợp', analyst: 'Data Analyst',
  software: 'Phần mềm', business: 'Kinh doanh', marketing: 'Marketing', hr: 'Nhân sự', finance: 'Tài chính', education: 'Giáo dục',
};
const NOOP: LiveController = { resetToSleep() {}, wakeAgents() {}, putAgentsToSleep() {}, setAgentAction() {}, setLiveScene() {} };
// sự kiện báo BẮT ĐẦU một bước; các sự kiện khác báo bước đã XONG (pipeline ghi sau khi làm xong)
const STARTS = new Set(['task_started', 'synthesis_started', 'review_started']);

export function buildTimeline(all: Array<LiveEvent & { ts?: string }>): TimelineGroup[] {
  const events = all.filter(e => e.stage);
  const d = new LiveDirector(NOOP, () => {});
  d.start('');
  const firstAt = new Map<string, number>();     // bước → chỉ số sự kiện tạo ra nó
  const ms = new Map<string, number>();
  const startTs = new Map<string, number>();     // bước có sự kiện bắt đầu riêng (việc con, tổng hợp, đối chiếu)
  const add = (key: string | undefined, v: number) => { if (key && Number.isFinite(v) && v >= 0) ms.set(key, (ms.get(key) ?? 0) + v); };
  const endSpan = (key: string, t: number) => { const s0 = startTs.get(key); if (s0 !== undefined) { add(key, t - s0); startTs.delete(key); } };
  let prevTs = NaN;
  let measured = true;

  events.forEach((e, i) => {
    const t = e.ts ? Date.parse(e.ts) : NaN;
    if (!Number.isFinite(t)) measured = false;
    const gap = t - prevTs;
    const before = d.getState().steps.find(s => s.state === 'now' && !s.key.startsWith('task-'))?.key;
    d.handle(e);
    const steps = d.getState().steps;
    steps.forEach(s => { if (!firstAt.has(s.key)) firstAt.set(s.key, i); });
    const taskId = e.task_id ?? e.result?.task_id;
    const nowKey = [...steps].reverse().find(s => s.state === 'now' && !s.key.startsWith('task-'))?.key;
    if (STARTS.has(e.stage!)) {
      const key = e.stage === 'task_started' ? `task-${taskId}` : e.stage === 'synthesis_started' ? (e.revision ? 'revise' : 'write') : 'review';
      if (e.stage === 'review_started') endSpan('write', t);
      startTs.set(key, t);
    } else if (e.stage === 'task_completed') {
      if (startTs.has(`task-${taskId}`)) endSpan(`task-${taskId}`, t); else add(`task-${taskId}`, gap);
    } else if (e.stage === 'review_finished') {
      endSpan('review', t);
    } else if (e.stage === 'review_revision') {
      endSpan('write', t);  // bản đầu xong khi Reviewer trả bài; thời gian viết lại tính từ synthesis_started (revision)
    } else if (e.stage === 'run_finished' || e.stage === 'run_failed') {
      const open = startTs.has('write') || startTs.has('review') || startTs.has('revise');
      endSpan('write', t); endSpan('review', t); endSpan('revise', t);
      if (!open) add(before, gap);
    } else if (e.stage === 'knowledge_source') {
      if (steps.some(s => s.key === 'write') && !startTs.has('write') && (e.domain ?? 'general') === 'general') add('write', gap);  // đường đơn giản: thời gian viết
    } else if (i > 0 && !startTs.has(`task-${taskId}`)) {
      add(nowKey ?? before, gap);  // sự kiện báo xong: khoảng trước nó thuộc bước nó báo
    }
    if (Number.isFinite(t)) prevTs = t;
  });

  const groups: TimelineGroup[] = [];
  for (const s of d.getState().steps) {
    const v = measured && ms.has(s.key) ? ms.get(s.key)! : measured ? 0 : null;
    const last = groups[groups.length - 1];
    if (last && last.actor === s.actor) {
      last.steps.push(s.label);
      last.ms = last.ms === null || v === null ? null : last.ms + v;
      if (s.state === 'fail' || (s.state === 'now' && last.state === 'done')) last.state = s.state;
    } else {
      // 'now': lượt còn đang chạy (dòng thời gian của câu đang trả lời)
      groups.push({ actor: s.actor, who: WHO[s.actor] ?? s.actor, steps: [s.label], ms: v, state: s.state, eventIndex: firstAt.get(s.key) ?? 0 });
    }
  }
  return groups;
}

// run.events của câu đã lưu không đổi: nhớ kết quả để gõ phím (vẽ lại trang) không phải dựng lại
const cache = new WeakMap<object, TimelineGroup[]>();
export function timelineOf(events: Array<LiveEvent & { ts?: string }>): TimelineGroup[] {
  let g = cache.get(events);
  if (!g) { g = buildTimeline(events); cache.set(events, g); }
  return g;
}

/** "0,4 giây", "12 giây"; null → rỗng (chưa đo). */
export function fmtMs(v: number | null): string {
  if (v === null) return '';
  if (v < 100) return 'dưới 0,1 giây';  // bước tức thời (vd. kiểm tra kế hoạch bằng luật), không ghi "0 giây"
  const sec = v / 1000;
  return `${sec.toLocaleString('vi-VN', { maximumFractionDigits: sec < 10 ? 1 : 0 })} giây`;
}
