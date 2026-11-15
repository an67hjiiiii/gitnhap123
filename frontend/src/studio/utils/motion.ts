// Tùy chọn hiệu ứng dùng chung với landing (khóa 'orchestriq-motion-v2'): mặc định "đầy đủ" kể cả khi hệ điều hành
// bật giảm chuyển động (Windows: tắt "Animation effects"); chọn "theo thiết bị" thì mới làm theo hệ điều hành.
const KEY = 'orchestriq-motion-v2';

export function motionMode(): 'full' | 'auto' {
  try { return localStorage.getItem(KEY) === 'auto' ? 'auto' : 'full'; } catch { return 'full'; }
}

export function setMotionMode(mode: 'full' | 'auto') {
  try { localStorage.setItem(KEY, mode); } catch { /* trình duyệt có thể chặn lưu */ }
}

/** Có chạy hiệu ứng chuyển động không. */
export function motionAllowed(): boolean {
  if (typeof window === 'undefined') return false;
  return motionMode() === 'full' || !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
