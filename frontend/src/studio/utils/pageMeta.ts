// Tên trang và một câu mô tả, hiện trên thanh trên cùng (máy tính và điện thoại). Đợt 1 (khung mới, 20/11).
import type { NavigationTab } from '../types';

export const PAGE_META: Record<NavigationTab, { title: string; desc: string }> = {
  orchestration: { title: 'Không gian làm việc', desc: 'Hỏi về tài liệu, gọi kỹ năng hoặc chia việc cho nhiều tác tử.' },
  chat: { title: 'Trò chuyện', desc: 'Hỏi đáp trên kho tài liệu.' },
  library: { title: 'Tài liệu', desc: 'Tải lên, phân loại, mở hồ sơ và theo dõi bản cũ, bản mới.' },
  documents: { title: 'Hồ sơ tài liệu', desc: 'Mục lục, đoạn, tóm tắt và câu hỏi gợi ý của một tài liệu.' },
  consistency: { title: 'Kiểm tra mâu thuẫn', desc: 'Tìm chỗ các tài liệu nói khác nhau.' },
  compare: { title: 'So sánh phiên bản', desc: 'Đối chiếu hai bản theo Chương, Điều, Khoản: thêm, sửa, bỏ, giữ.' },
  toolkit: { title: 'Kỹ năng', desc: 'Danh mục kỹ năng theo ngành, chạy ngay trên tài liệu đã chọn.' },
  office: { title: 'Văn phòng Agent', desc: 'Xem đội Agent nhận việc, chia việc và tổng hợp câu trả lời trong văn phòng 3D.' },
  results: { title: 'Kết quả & công việc', desc: 'Kết quả đã lưu, việc cần xem xét, đơn từ và thông báo.' },
  tasks: { title: 'Đơn từ', desc: 'Gửi đơn, kiểm tra theo quy định và duyệt theo cấp.' },
  overview: { title: 'Tổng quan', desc: 'Việc đang dở, cảnh báo kho tài liệu và đơn đang chờ.' },
  organization: { title: 'Tổ chức', desc: 'Thành viên, cấp bậc, đơn vị và mức mật tài liệu.' },
  notifications: { title: 'Thông báo', desc: 'Lời mời, duyệt trong tổ chức và hoạt động gần đây của tài khoản.' },
  settings: { title: 'Cài đặt', desc: 'Hồ sơ, giao diện, nguồn tài liệu và thông tin hệ thống.' },
  evaluation: { title: 'Phòng đánh giá', desc: 'Chạy các điều kiện A, B, C trên cùng bộ câu hỏi.' },
  benchmarks: { title: 'Thực nghiệm', desc: 'Nhật ký lượt chạy và so sánh ba phương pháp.' },
  rating: { title: 'Chấm mù', desc: 'Người chấm chấm câu trả lời mà không biết phương pháp.' },
  users: { title: 'Người dùng', desc: 'Cấp, khóa tài khoản và phân quyền.' },
  db_explorer: { title: 'Cơ sở dữ liệu', desc: 'Xem bảng và sức khỏe hệ thống.' },
};

export const pageMeta = (tab: string) => PAGE_META[tab as NavigationTab] ?? { title: 'OrchestrIQ Studio', desc: '' };
