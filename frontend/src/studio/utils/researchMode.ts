// "Chế độ nhà nghiên cứu" (đợt 6): hiện nhóm Nghiên cứu trên thanh bên cho người không phải quản trị.
// Hệ thống chưa có vai trò nhà nghiên cứu riêng; đây là tùy chọn hiển thị của từng tài khoản trên trình duyệt, không phải quyền.
// Khóa theo tài khoản: người khác đăng nhập cùng máy không thừa hưởng lựa chọn này.
const key = (uid?: string) => `oq-research-mode:${uid || 'anon'}`;
export const RESEARCH_EVENT = 'oq-research-mode';

export function researchMode(uid?: string): boolean {
  try { return localStorage.getItem(key(uid)) === '1'; } catch { return false; }
}

export function setResearchMode(on: boolean, uid?: string): void {
  try { localStorage.removeItem('oq-research-mode'); if (on) localStorage.setItem(key(uid), '1'); else localStorage.removeItem(key(uid)); } catch { /* chặn lưu trữ: chỉ đổi trong phiên */ }
  window.dispatchEvent(new CustomEvent(RESEARCH_EVENT, { detail: on }));
}
