export type ErrorContext = 'login' | 'session' | 'upload' | 'chat' | 'general';

export function friendlyMessage(input: {
  status?: number;
  detail?: string;
  network?: boolean;
  timeout?: boolean;
  context?: ErrorContext;
}): string {
  const { status, detail, network, timeout, context = 'general' } = input;
  if (typeof detail === 'string' && detail.trim() && /[áàảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]/i.test(detail)) return detail;
  if (status === 401 && context === 'login') return 'Email hoặc mật khẩu chưa đúng. Bạn kiểm tra lại nhé.';
  if (status === 401) return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.';
  if (status === 403) return 'Bạn chưa có quyền thực hiện thao tác này.';
  if (status === 404) return 'Không tìm thấy nội dung được yêu cầu. Có thể nó đã bị xoá.';
  if (status === 409) return 'Nội dung này đã tồn tại hoặc đang được xử lý. Hãy làm mới trang rồi thử lại.';
  if (status === 422 && context === 'upload') return 'Tệp chưa hợp lệ. Dùng PDF, Markdown, TXT hoặc SQL, tối đa 2 MB.';
  if (status === 422) return 'Thông tin chưa hợp lệ. Bạn kiểm tra lại các ô đã nhập.';
  if (status === 429) return 'Bạn thao tác hơi nhanh. Vui lòng đợi một lát rồi thử lại.';
  if (status === 500) return 'Máy chủ gặp lỗi. Vui lòng thử lại sau ít phút.';
  if (status === 502 || status === 503 || status === 504) return 'Máy chủ đang bận hoặc đang khởi động. Vui lòng thử lại sau ít phút.';
  if (network) return 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.';
  if (timeout) return 'Máy chủ phản hồi quá lâu. Vui lòng thử lại.';
  return 'Có lỗi xảy ra. Vui lòng thử lại.';
}

export function contextOfPath(path: string): ErrorContext {
  if (path === '/auth/login' || path === '/auth/register') return 'login';
  if (path === '/sources' || path.startsWith('/sources/')) return 'upload';
  if (path === '/chat' || path.startsWith('/chat/')) return 'chat';
  if (path.startsWith('/auth/')) return 'session';
  return 'general';
}
