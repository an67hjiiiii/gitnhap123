// Thông tin điền sẵn cho Word theo mẫu (đợt 10): tên cơ quan, địa danh, người ký. Chỉ để tiện, lưu trên trình duyệt này.
export type DocTemplateInfo = { org: string; place: string; signer: string };
const KEY = 'oq-doc-template';

export function loadDocTemplate(): DocTemplateInfo {
  try { return { org: '', place: '', signer: '', ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { return { org: '', place: '', signer: '' }; }
}

export function saveDocTemplate(v: DocTemplateInfo): void {
  try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* chặn lưu trữ: lần sau điền lại */ }
}

export const DOC_KIND_LABEL: Record<string, string> = { to_trinh: 'Tờ trình', bien_ban: 'Biên bản', thong_bao: 'Thông báo', bao_cao: 'Báo cáo' };
