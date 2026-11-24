// Đợt 6: kênh nhỏ giữ lượt chạy đang diễn ra trong ô chat để văn phòng 3D (mở sau cũng được) theo dõi trực tiếp.
// Nhẹ, không phụ thuộc three.js: trang chat nhập file này mà không tải văn phòng.
import type { LiveEvent } from './liveDirector';

export interface LiveSession { id: number; question: string; events: LiveEvent[]; ended: boolean; failed: boolean }
type Listener = (session: LiveSession, event: LiveEvent | null) => void;

let current: LiveSession | null = null;
let seq = 0;
const listeners = new Set<Listener>();
const notify = (event: LiveEvent | null) => { if (current) listeners.forEach(fn => fn(current!, event)); };

export function startLive(question: string): void {
  current = { id: ++seq, question, events: [], ended: false, failed: false };
  notify(null);
}

export function pushLive(event: LiveEvent): void {
  if (!current || current.ended) return;
  // mốc thời gian lúc trình duyệt nhận (luồng stream không gửi ts) để dòng thời gian của câu đang chạy có số đo thật
  const stamped = event.type === 'progress' && !(event as { ts?: string }).ts ? { ...event, ts: new Date().toISOString() } : event;
  current.events.push(stamped);
  notify(stamped);
}

export function endLive(failed: boolean): void {
  if (!current || current.ended) return;
  current.ended = true;
  current.failed = failed;
  notify(null);
}

export const getLive = (): LiveSession | null => current;

export function subscribeLive(fn: Listener): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
