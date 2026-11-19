// "Chế độ nhà nghiên cứu" (đợt 6): hiện nhóm Nghiên cứu trên thanh bên cho người không phải quản trị.
// Hệ thống chưa có vai trò nhà nghiên cứu riêng; đây là tùy chọn hiển thị của từng trình duyệt, không phải quyền.
const KEY = 'oq-research-mode';
export const RESEARCH_EVENT = 'oq-research-mode';

export function researchMode(): boolean {
  try { return localStorage.getItem(KEY) === '1'; } catch { return false; }
}

export function setResearchMode(on: boolean): void {
  try { if (on) localStorage.setItem(KEY, '1'); else localStorage.removeItem(KEY); } catch { /* chặn lưu trữ: chỉ đổi trong phiên */ }
  window.dispatchEvent(new CustomEvent(RESEARCH_EVENT, { detail: on }));
}
