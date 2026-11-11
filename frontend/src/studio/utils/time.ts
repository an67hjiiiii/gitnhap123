// Backend lưu giờ UTC không kèm múi giờ (datetime.utcnow); thêm 'Z' để trình duyệt đổi đúng sang giờ máy.
export const serverDate = (s: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`);
