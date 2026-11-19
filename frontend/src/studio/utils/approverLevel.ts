// Gợi ý cấp duyệt cho đơn từ từ tên người duyệt mà kỹ năng "Ai duyệt" trích trong quy định (đợt 10).
// Luật cố định; người gửi vẫn tự chọn cấp. Không nhận ra thì trả null, không đoán.
const fold = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase();

export function suggestLevel(approver: string | null | undefined): 'MANAGER' | 'EXECUTIVE' | null {
  const t = fold(approver || '');
  if (!t.trim()) return null;
  if (/giam doc|hieu truong|ban giam|tong giam|chu tich|hoi dong quan tri/.test(t)) return 'EXECUTIVE';
  if (/truong phong|truong khoa|truong bo phan|truong nhom|quan ly|pho phong/.test(t)) return 'MANAGER';
  return null;
}
