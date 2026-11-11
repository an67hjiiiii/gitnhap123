// Tám bước của một lượt chạy CAP1, mỗi bước gom các sự kiện (events[].stage) mà pipeline CAP1 thực sự ghi lại.
import React from 'react';
import { CheckCircle2, Compass, Cpu, FileCheck, GitFork, Gauge, Search, ShieldCheck } from 'lucide-react';

export interface PipelineStep {
  id: string;
  stepNumber: number;
  title: string;
  shortTitle: string;
  tag: string;
  description: string;
  scientificRole: string;
  icon: React.ReactNode;
  category: 'planning' | 'retrieval' | 'optimization' | 'execution';
  stages: string[];
}

export const PIPELINE_STEPS: PipelineStep[] = [
  { id: 'step-1', stepNumber: 1, shortTitle: 'Hiểu yêu cầu', title: 'Hiểu yêu cầu và trích nghĩa vụ', tag: 'Mô hình ngôn ngữ', category: 'planning',
    stages: ['request_understanding', 'obligation_concern_extraction', 'product_request_routing'],
    description: 'Đọc yêu cầu, tách thành các nghĩa vụ bắt buộc và mối quan tâm (dữ liệu, API, bảo mật) để làm chuẩn kiểm tra kế hoạch.',
    scientificRole: 'Danh sách nghĩa vụ là thước đo để biết kế hoạch có bỏ sót yêu cầu hay không.', icon: <Compass size={18} /> },
  { id: 'step-2', stepNumber: 2, shortTitle: 'Truy xuất kế hoạch', title: 'Truy xuất tài liệu để lập kế hoạch', tag: 'Chỉ mục vector / từ khóa', category: 'retrieval',
    stages: ['planning_retrieval', 'vanilla_retrieval'],
    description: 'Tìm các đoạn tài liệu liên quan để kế hoạch bám theo tài liệu của người dùng. Ở điều kiện A đây là lượt truy xuất duy nhất.',
    scientificRole: 'Kế hoạch dựa trên bằng chứng thay vì kiến thức chung của mô hình.', icon: <Search size={18} /> },
  { id: 'step-3', stepNumber: 3, shortTitle: 'Lập kế hoạch', title: 'Sinh kế hoạch và phân rã nhiệm vụ', tag: 'Cờ P (lập kế hoạch)', category: 'planning',
    stages: ['planning_generation', 'decomposition'],
    description: 'Chia yêu cầu thành các nhiệm vụ cho ba vai trò Dữ liệu, API/Kiến trúc và Bảo mật, kèm phụ thuộc giữa nhiệm vụ.',
    scientificRole: 'Bỏ bước này ở điều kiện C-P để đo đóng góp của lập kế hoạch.', icon: <GitFork size={18} /> },
  { id: 'step-4', stepNumber: 4, shortTitle: 'Kiểm tra kế hoạch', title: 'Kiểm tra và sửa kế hoạch', tag: 'Xác minh có giới hạn', category: 'planning',
    stages: ['plan_verification', 'planning_repair', 'planning_rejected'],
    description: 'Đối chiếu kế hoạch với các nghĩa vụ: thiếu hoặc giao sai vai trò thì sửa một lần; vẫn sai thì từ chối, không chạy tiếp.',
    scientificRole: 'Chặn kế hoạch sai trước khi tốn token thực thi; từ chối được ghi lại, không che giấu.', icon: <ShieldCheck size={18} /> },
  { id: 'step-5', stepNumber: 5, shortTitle: 'Chuẩn hóa', title: 'Chuẩn hóa nhiệm vụ và bàn giao', tag: 'Cờ N (chuẩn hóa)', category: 'optimization',
    stages: ['normalization', 'validated_plan_handoff'],
    description: 'Gộp nhiệm vụ trùng, giữ đủ nghĩa vụ, xác định thứ tự thực thi theo phụ thuộc.',
    scientificRole: 'Bỏ bước này ở điều kiện C-N để đo đóng góp của chuẩn hóa.', icon: <FileCheck size={18} /> },
  { id: 'step-6', stepNumber: 6, shortTitle: 'Truy xuất & ngân sách', title: 'Truy xuất riêng từng nhiệm vụ và chia ngân sách', tag: 'Cờ O (tối ưu ngữ cảnh)', category: 'optimization',
    stages: ['adaptive_budget_plan', 'task_retrieval'],
    description: 'Mỗi nhiệm vụ tự tìm tài liệu của mình; khi bật CONTEXT_POLICY=adaptive_qwen, ngân sách token được chia theo nhu cầu và đếm bằng tokenizer Qwen3 thật.',
    scientificRole: 'Bỏ bước tối ưu ở điều kiện C-O để đo đóng góp của phân bổ ngữ cảnh.', icon: <Gauge size={18} /> },
  { id: 'step-7', stepNumber: 7, shortTitle: 'Thực thi tác tử', title: 'Thực thi các nhiệm vụ', tag: 'Mô hình ngôn ngữ', category: 'execution',
    stages: ['task_completed', 'run_budget_exceeded'],
    description: 'Các tác tử trả lời nhiệm vụ của mình theo thứ tự phụ thuộc, chỉ được trích những đoạn tài liệu đã giao.',
    scientificRole: 'Trích dẫn ngoài danh sách bằng chứng bị đánh dấu không hợp lệ.', icon: <Cpu size={18} /> },
  { id: 'step-8', stepNumber: 8, shortTitle: 'Tổng hợp', title: 'Tổng hợp câu trả lời cuối', tag: 'Mô hình ngôn ngữ', category: 'execution',
    stages: ['run_finished', 'run_failed'],
    description: 'Gom kết quả các nhiệm vụ thành câu trả lời cuối kèm trạng thái: đủ bằng chứng, một phần, không có bằng chứng hoặc thất bại.',
    scientificRole: 'Trạng thái cuối cho biết mức độ được tài liệu hỗ trợ, không phải điểm chất lượng.', icon: <CheckCircle2 size={18} /> },
];

export const STAGE_LABEL: Record<string, string> = {
  run_started: 'Bắt đầu', request_understanding: 'Hiểu yêu cầu', obligation_concern_extraction: 'Trích nghĩa vụ và mối quan tâm',
  product_request_routing: 'Định tuyến yêu cầu', vanilla_retrieval: 'Truy xuất (điều kiện A)', planning_retrieval: 'Truy xuất lập kế hoạch',
  planning_generation: 'Sinh kế hoạch', plan_verification: 'Kiểm tra kế hoạch', planning_repair: 'Sửa kế hoạch', planning_rejected: 'Từ chối kế hoạch',
  decomposition: 'Phân rã', normalization: 'Chuẩn hóa nhiệm vụ', validated_plan_handoff: 'Bàn giao kế hoạch đã kiểm',
  adaptive_budget_plan: 'Chia ngân sách token', task_retrieval: 'Truy xuất cho nhiệm vụ', task_completed: 'Nhiệm vụ xong',
  run_budget_exceeded: 'Vượt ngân sách lượt chạy', run_finished: 'Kết thúc', run_failed: 'Thất bại',
};

export function stepEvents(raw: any, step: PipelineStep): any[] {
  return (raw?.events || []).filter((e: any) => step.stages.includes(e.stage));
}
