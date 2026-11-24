// Giới thiệu từng Agent cho người dùng và trạng thái THẬT của vai đó trong hệ thống (cập nhật 23/11: bộ office mặc định,
// bước chọn nguồn tri thức). Không ghi là "đã có" khi máy chủ chưa làm; ví dụ lấy từ tài liệu mẫu và câu đã chạy thử.
import type { AgentId } from './types';

export type SystemStatus = 'live' | 'partial' | 'ready' | 'planned';

export const STATUS_LABEL: Record<SystemStatus, string> = {
  live: 'Đang chạy thật',
  partial: 'Có một phần',
  ready: 'Có sẵn, chưa bật',
  planned: 'Chưa có, dự kiến',
};

export interface AgentGuide {
  role: string;        // một câu: Agent này là ai
  when: string;        // khi nào được gọi
  status: SystemStatus;
  does: string[];      // việc làm thật trong hệ thống hôm nay
  examples: string[];  // câu hỏi mẫu Agent này nhận
  from: string;        // nhận gì, từ ai
  to: string;          // giao gì, cho ai
  limit?: string;      // giới hạn hiện tại (nói thật)
}

const SPECIALIST_WHEN = 'Khi Orchestrator thấy câu hỏi thuộc ngành này (so nghĩa và từ khóa). Câu ngoài các ngành thì không gọi, giao Chuyên viên tổng hợp.';
const SPECIALIST_FROM = 'Việc con từ Orchestrator và các đoạn tài liệu do RAG tìm';
const SPECIALIST_TO = 'Phần trả lời có trích dẫn (hoặc có nhãn "Kiến thức chung") cho Integrator';

export const AGENT_GUIDE: Record<AgentId, AgentGuide> = {
  orchestrator: {
    role: 'Người nhận câu hỏi, hiểu yêu cầu, chọn chuyên gia, chọn nguồn tri thức và lập kế hoạch chia việc.',
    when: 'Luôn làm việc, ở mọi câu hỏi.',
    status: 'live',
    does: [
      'Nhận ra câu đơn giản (trả lời thẳng) hay câu nhiều ý (lập kế hoạch).',
      'Chọn tối đa 3 chuyên gia theo nghĩa câu hỏi và từ khóa; câu ngoài ngành giao Chuyên viên tổng hợp.',
      'Chọn nguồn tri thức cho từng việc: tài liệu, kiến thức chung, hoặc cả hai.',
      'Câu nhiều ý: chia việc con, xếp thứ tự phụ thuộc rồi giao cho từng chuyên gia.',
    ],
    examples: [
      'Nghỉ phép 4 ngày ai duyệt, làm thêm ngày lễ trả bao nhiêu? → 2 việc con cho Nhân sự.',
      'Thủ đô của Úc? → không có tài liệu, trả lời bằng kiến thức chung.',
    ],
    from: 'Câu hỏi của người dùng trong ô chat',
    to: 'Kế hoạch và các việc con cho chuyên gia',
  },
  rag: {
    role: 'Người mở tủ hồ sơ: tìm đúng đoạn tài liệu để các Agent khác dựa vào đó trả lời.',
    when: 'Mỗi khi câu hỏi cần dựa vào tài liệu đã tải lên.',
    status: 'live',
    does: [
      'Tìm kết hợp theo nghĩa (mô hình nomic-embed-text) và theo từ khóa.',
      'Câu hỏi nêu tên tài liệu thì chỉ tìm trong tài liệu đó (ví dụ bản 2026, không lẫn bản 2024).',
      'Chia số đoạn tài liệu vừa đủ cho từng việc con để mô hình không bị quá tải.',
    ],
    examples: ['Theo quy chế 2026, nghỉ ốm 3 ngày cần giấy gì? → chỉ tìm trong Quy chế 2026.'],
    from: 'Việc con từ Orchestrator',
    to: 'Các đoạn tài liệu kèm mã trích dẫn cho chuyên gia',
    limit: 'Câu hỏi tiếng Anh trên tài liệu tiếng Việt đôi khi tìm sót.',
  },
  analyst: {
    role: 'Người làm việc với con số: đọc bảng, tính toán, so sánh tỷ lệ.',
    when: 'Khi câu hỏi hỏi "bao nhiêu", cần tính tiền, tỷ lệ hay đọc bảng số liệu.',
    status: 'partial',
    does: [
      'Đọc bảng số trong tài liệu và chép đúng số.',
      'Viết phép tính để máy chủ tính ra con số cuối, không để mô hình tự nhẩm.',
      'So sánh hai con số, tính phần trăm.',
    ],
    examples: ['Quán bán 200 ly/ngày, giá 35.000 đồng, 30 ngày → doanh thu 210.000.000 đồng/tháng.'],
    from: 'Đoạn tài liệu có bảng hoặc con số',
    to: 'Con số đã tính kèm phép tính cho Integrator',
    limit: 'Mô hình vẫn có thể chọn nhầm số đầu vào; chưa phân tích xu hướng theo thời gian.',
  },
  reviewer: {
    role: 'Người kiểm định: soát kế hoạch và câu trả lời, tìm chỗ thiếu ý hoặc thiếu nguồn.',
    when: 'Ở câu nhiều ý (kiểm tra kế hoạch) và khi bật đối chiếu câu trả lời.',
    status: 'partial',
    does: [
      'Kiểm tra kế hoạch có bỏ sót yêu cầu nào của câu hỏi không; thiếu thì cho sửa một lần.',
      'Kiểm tra mã trích dẫn trỏ đúng đoạn tài liệu đã dùng.',
      'Đối chiếu từng ý câu trả lời với tài liệu (bật bằng PRODUCT_REVIEWER=on).',
    ],
    examples: ['Kế hoạch quên một ý của câu hỏi → yêu cầu sửa; vẫn thiếu thì dừng, không trả lời sai.'],
    from: 'Kế hoạch của Orchestrator, câu trả lời của Integrator',
    to: 'Kết quả kiểm tra: đạt, cần sửa, hoặc ý chưa có trong tài liệu',
    limit: 'Đối chiếu từng ý chưa bật mặc định (thêm khoảng 1,6 giây mỗi câu nhiều ý).',
  },
  integrator: {
    role: 'Người tổng hợp: ghép kết quả của các Agent thành một câu trả lời hoàn chỉnh.',
    when: 'Luôn làm việc, ở bước cuối của mọi câu hỏi.',
    status: 'live',
    does: [
      'Ghép phần trả lời của các chuyên gia, bỏ trùng, giữ đủ mọi ý được hỏi.',
      'Giữ nguyên trích dẫn; phần kiến thức chung để riêng, có nhãn.',
      'Trả lời đúng ngôn ngữ của câu hỏi, có bảng khi cần so sánh.',
    ],
    examples: ['3 ý ở 3 tài liệu khác nhau → một câu trả lời 3 mục, mục nào cũng có nguồn.'],
    from: 'Kết quả từng việc con của các chuyên gia',
    to: 'Câu trả lời cuối gửi người dùng',
  },
  software: {
    role: 'Chuyên gia phần mềm: yêu cầu kỹ thuật, API, cơ sở dữ liệu, bảo mật, lập trình.',
    when: SPECIALIST_WHEN,
    status: 'live',
    does: ['Đọc đặc tả yêu cầu, thiết kế API, cơ sở dữ liệu, quy định bảo mật.', 'Không có tài liệu: trả lời câu lập trình, mạng bằng kiến thức chung (có nhãn).'],
    examples: ['Hệ thống PayNhanh được lưu những số nào của thẻ?', 'Viết hàm Python kiểm tra số nguyên tố.'],
    from: SPECIALIST_FROM,
    to: SPECIALIST_TO,
  },
  business: {
    role: 'Chuyên gia kinh doanh: mô hình kinh doanh, vốn góp, đối tác, hợp đồng thương mại.',
    when: SPECIALIST_WHEN,
    status: 'live',
    does: ['Đọc kế hoạch kinh doanh, điều khoản góp vốn, quyền quyết định.', 'Trả lời câu về chiến lược, đối tác, hợp đồng mua bán.'],
    examples: ['Quyết định đầu tư 60 triệu đồng có cần cả hai đồng sáng lập đồng ý không?'],
    from: SPECIALIST_FROM,
    to: SPECIALIST_TO,
  },
  marketing: {
    role: 'Chuyên gia marketing: chiến dịch, kênh quảng cáo, khách hàng, chỉ số hiệu quả.',
    when: SPECIALIST_WHEN,
    status: 'live',
    does: ['Đọc báo cáo chiến dịch, ngân sách theo kênh.', 'Tính và so sánh chỉ số CTR, CPA, đơn hàng theo kênh.'],
    examples: ['CTR của kênh Facebook trong chiến dịch quý IV là bao nhiêu?'],
    from: SPECIALIST_FROM,
    to: SPECIALIST_TO,
  },
  hr: {
    role: 'Chuyên gia nhân sự: nội quy, quy chế, nghỉ phép, lương thưởng, kỷ luật.',
    when: SPECIALIST_WHEN,
    status: 'live',
    does: ['Đọc nội quy, quy chế làm việc, hợp đồng lao động.', 'Trả lời ai duyệt, bao nhiêu ngày, được hưởng gì theo đúng điều khoản.'],
    examples: ['Nhân viên thử việc có được nghỉ phép năm không?', 'Tạm ứng 7 triệu đồng thì ai duyệt?'],
    from: SPECIALIST_FROM,
    to: SPECIALIST_TO,
  },
  finance: {
    role: 'Chuyên gia tài chính: thu chi, ngân sách, báo cáo tài chính, thuế phí.',
    when: SPECIALIST_WHEN,
    status: 'live',
    does: ['Đọc báo cáo thu chi, dự toán, kế hoạch và thực hiện.', 'So sánh số kế hoạch với số thực hiện, tính chênh lệch.'],
    examples: ['Giá vốn hàng bán năm 2026 vượt kế hoạch bao nhiêu?'],
    from: SPECIALIST_FROM,
    to: SPECIALIST_TO,
  },
  education: {
    role: 'Chuyên gia giáo dục và nghiên cứu: quy chế học vụ, tín chỉ, học bổng, tài liệu môn học.',
    when: SPECIALIST_WHEN,
    status: 'live',
    does: ['Đọc quy chế đào tạo, đề cương, tài liệu môn học.', 'Lập kế hoạch học tập, ôn thi khi được yêu cầu.'],
    examples: ['Mỗi học kỳ đăng ký tối đa bao nhiêu tín chỉ?', 'Lập kế hoạch ôn thi 2 tuần cho môn Toán cao cấp.'],
    from: SPECIALIST_FROM,
    to: SPECIALIST_TO,
  },
};
