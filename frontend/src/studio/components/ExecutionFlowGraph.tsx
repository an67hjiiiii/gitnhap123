import { percent } from '../utils/measurement';
import React from 'react';
import { 
  Compass, 
  GitFork, 
  Filter, 
  Users, 
  Search, 
  Scissors, 
  Cpu, 
  FileCheck, 
  CheckCircle2, 
  Loader2, 
  Info,
  ChevronRight,
  Database,
  Code2,
  Shield
} from 'lucide-react';
import { ModeExecutionResult } from '../types';

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
}

export const PIPELINE_STEPS: PipelineStep[] = [
  {
    id: 'step-1',
    stepNumber: 1,
    title: 'Truy Xuất Lập Kế Hoạch (Planning Retrieval)',
    shortTitle: 'Truy xuất Kế hoạch',
    tag: 'Qdrant Vectors',
    description: 'Truy xuất các khối tri thức định hướng tổng quan từ Qdrant để xây dựng bức tranh kiến trúc hệ thống trước khi phân tách bài toán.',
    scientificRole: 'Cung cấp ngữ cảnh nền tảng giúp LLM tránh phân rã mù quáng hoặc sai lệch nghiệp vụ.',
    icon: <Compass className="w-4 h-4 text-sky-600" />,
    category: 'planning'
  },
  {
    id: 'step-2',
    stepNumber: 2,
    title: 'Phân Rã Nhiệm Vụ Có Hỗ Trợ Truy Xuất (Task Decomposition)',
    shortTitle: 'Phân rã Nhiệm vụ',
    tag: 'LLM Orchestrator',
    description: 'Phân tích yêu cầu kỹ thuật phức tạp thành các Subtasks chuyên biệt dựa trên tài liệu định hướng vừa truy xuất được.',
    scientificRole: 'Chia nhỏ bài toán lớn thành các đơn vị công việc độc lập, giảm độ phức tạp tính toán cho từng tác tử.',
    icon: <GitFork className="w-4 h-4 text-indigo-600" />,
    category: 'planning'
  },
  {
    id: 'step-3',
    stepNumber: 3,
    title: 'Chuẩn Hóa & Khử Trùng Lặp Nhiệm Vụ (Normalization)',
    shortTitle: 'Chuẩn hóa & Khử lặp',
    tag: 'Deduplication',
    description: 'Kiểm tra xung đột, đối chiếu các định danh trùng lặp và làm sạch ranh giới trách nhiệm giữa các phân rã.',
    scientificRole: 'Gộp bảo thủ các nhiệm vụ trùng nội dung chuẩn hóa, giữ lại yêu cầu gốc và phụ thuộc để kiểm tra.',
    icon: <Filter className="w-4 h-4 text-purple-600" />,
    category: 'planning'
  },
  {
    id: 'step-4',
    stepNumber: 4,
    title: 'Phân Công Tác Tử Chuyên Môn (Agent Assignment)',
    shortTitle: 'Phân công Tác tử',
    tag: 'Multi-Agent',
    description: 'Gán từng nhiệm vụ theo miền trách nhiệm cho DatabaseAgent, APIAgent hoặc SecurityAgent; không bắt buộc sử dụng đủ ba vai trò.',
    scientificRole: 'Áp dụng mô hình chuyên môn hóa cao (Specialized Agents) thay vì một LLM đơn độc làm tất cả.',
    icon: <Users className="w-4 h-4 text-emerald-600" />,
    category: 'retrieval'
  },
  {
    id: 'step-5',
    stepNumber: 5,
    title: 'Truy Xuất Riêng Biệt Theo Nhiệm Vụ (Task-Specific Retrieval)',
    shortTitle: 'Truy xuất Riêng',
    tag: 'Truy vấn nhiệm vụ',
    description: 'Mỗi nhiệm vụ có truy vấn riêng tới Qdrant trong workspace hiện tại; ngữ cảnh được quản lý theo ID nhiệm vụ.',
    scientificRole: 'Tập trung ngữ cảnh trúng đích, loại bỏ thông tin rác không liên quan đến phạm vi của từng tác tử.',
    icon: <Search className="w-4 h-4 text-cyan-600" />,
    category: 'retrieval'
  },
  {
    id: 'step-6',
    stepNumber: 6,
    title: 'Phân Bổ Ngữ Cảnh Nhận Thức Chồng Lặp (Overlap-Aware Allocation)',
    shortTitle: 'Phân bổ Shared Brief',
    tag: 'Core Innovation',
    description: 'Đóng góp nghiên cứu cốt lõi của đề tài C1SE.27: Bóc tách các thực thể và phân đoạn trùng lặp vào Shared Brief, chỉ cấp ngữ cảnh độc quyền cho từng Agent.',
    scientificRole: 'Mục tiêu giảm ngữ cảnh trùng lặp; hiệu quả token, độ trễ và tài nguyên cần được kiểm chứng qua thực nghiệm.',
    icon: <Scissors className="w-4 h-4 text-rose-600" />,
    category: 'optimization'
  },
  {
    id: 'step-7',
    stepNumber: 7,
    title: 'Thực thi các tác tử',
    shortTitle: 'Thực thi tác tử',
    tag: 'Thực thi LLM',
    description: 'Các nhiệm vụ chạy tuần tự theo DAG trên mô hình cục bộ; nhiệm vụ phụ thuộc nhận kết quả của tiền nhiệm đã hoàn tất.',
    scientificRole: 'Đo độ trễ và chất lượng đầu ra để đánh giá cơ chế điều phối trong điều kiện thực nghiệm.',
    icon: <Cpu className="w-4 h-4 text-amber-600" />,
    category: 'execution'
  },
  {
    id: 'step-8',
    stepNumber: 8,
    title: 'Tổng Hợp Bản Thiết Kế Kiến Trúc (Synthesis Blueprint)',
    shortTitle: 'Tổng hợp Kiến trúc',
    tag: 'ADR Document',
    description: 'Sinh bản tổng hợp từ đầu ra tác tử. Bộ cấp phát ngữ cảnh và kiểm chứng độ bao phủ còn cần hoàn thiện; chất lượng chưa được chấm tự động.',
    scientificRole: 'Lưu đầu ra để đối chiếu và đánh giá bằng rubric trong thực nghiệm.',
    icon: <FileCheck className="w-4 h-4 text-teal-600" />,
    category: 'execution'
  }
];

interface ExecutionFlowGraphProps {
  currentStepIndex: number; // 0 to 8 (0 = idle, 1..8 = active step, 8 = all completed)
  isAnalyzing: boolean;
  result: ModeExecutionResult | null;
  onSelectStep: (step: PipelineStep) => void;
  selectedStepId?: string | null;
}

export const ExecutionFlowGraph: React.FC<ExecutionFlowGraphProps> = ({
  currentStepIndex,
  isAnalyzing,
  result,
  onSelectStep,
  selectedStepId
}) => {
  const getStepStatus = (stepNumber: number) => {
    if (result) return 'idle';
    if (!isAnalyzing) return 'idle';
    if (stepNumber < currentStepIndex) return 'completed';
    if (stepNumber === currentStepIndex) return 'running';
    return 'idle';
  };

  const getMetricSummary = (stepNumber: number) => {
    if (!result) return null;
    switch (stepNumber) {
      case 1:
        return `${result.retrieved_chunks_count} chunks`;
      case 2:
        return `${result.subtasks.length} nhiệm vụ`;
      case 3:
        return null;
      case 4:
        return `${result.agent_results.length} tác tử`;
      case 5:
        return null;
      case 6:
        return (result.tokens_saved != null && result.tokens_saved > 0) ? `-${result.tokens_saved} tok` : 'Chưa xác nhận';
      case 7:
        return `${result.latency_ms} ms`;
      case 8:
        return result.task_coverage == null ? 'Chưa đánh giá độ phủ' : `${percent(result.task_coverage, 0)} phủ`;
      default:
        return null;
    }
  };

  return (
    <div className="pipeline-panel bg-white border border-slate-200 rounded-xl p-4 sm:p-5 shadow-2xs space-y-3.5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-100">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xs sm:text-sm font-bold text-slate-900 tracking-tight">
              02 / Quy trình điều phối
            </h2>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
              8 bước nghiên cứu
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Khám phá từng bước để xem vai trò, đầu vào và kết quả. Trạng thái từng bước chưa được API cung cấp.
          </p>
        </div>

        <div className="flex items-center gap-3 text-[11px] font-mono text-slate-500 self-start sm:self-auto">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-slate-300" />
            <span>Chưa xác nhận</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
            <span>Đang chạy</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span>Hoàn thành</span>
          </div>
        </div>
      </div>

      {/* Interactive 8-Stage Flow Grid */}
      <div className="pipeline-grid">
        {PIPELINE_STEPS.map((step) => {
          const status = getStepStatus(step.stepNumber);
          const isSelected = selectedStepId === step.id;
          const metric = getMetricSummary(step.stepNumber);

          return (
            <button
              type="button"
              aria-label={`Xem bước ${step.stepNumber}: ${step.shortTitle}`}
              key={step.id}
              onClick={() => onSelectStep(step)}
              className={`p-2.5 rounded-xl border transition-all cursor-pointer relative flex flex-col justify-between min-h-[118px] group ${
                isSelected 
                  ? 'border-indigo-600 bg-indigo-50/40 ring-2 ring-indigo-200 shadow-xs' 
                  : status === 'running'
                  ? 'border-indigo-500 bg-indigo-50/60 ring-2 ring-indigo-300 shadow-sm animate-pulse'
                  : status === 'completed'
                  ? 'border-slate-200 hover:border-indigo-300 bg-white hover:bg-slate-50/80 shadow-2xs'
                  : 'border-slate-200/80 bg-slate-50/50 hover:bg-white text-slate-400'
              }`}
              title={`Nhấp để soi chi tiết: ${step.title}`}
            >
              {/* Top row: Step number & Status icon */}
              <div className="flex items-center justify-between">
                <span 
                  className={`w-5 h-5 rounded-md font-mono text-[10px] font-bold flex items-center justify-center ${
                    status === 'completed' 
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' 
                      : status === 'running'
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-100 text-slate-500'
                  }`}
                >
                  {step.stepNumber}
                </span>

                <div>
                  {status === 'running' ? (
                    <Loader2 className="w-3.5 h-3.5 text-indigo-600 animate-spin" />
                  ) : status === 'completed' ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                  ) : (
                    <div className="w-2 h-2 rounded-full bg-slate-300" />
                  )}
                </div>
              </div>

              {/* Middle row: Icon and Short Title */}
              <div className="my-1.5 space-y-1">
                <div className="flex items-center gap-1.5">
                  <div className="p-1 rounded-md bg-slate-50 border border-slate-100 group-hover:scale-105 transition-transform flex-shrink-0">
                    {step.icon}
                  </div>
                  <span className="text-[10px] font-mono text-slate-400 truncate">
                    {step.tag}
                  </span>
                </div>
                <h3 className={`text-xs font-semibold leading-tight line-clamp-2 ${
                  status === 'completed' || status === 'running' || isSelected ? 'text-slate-900' : 'text-slate-600'
                }`}>
                  {step.shortTitle}
                </h3>
              </div>

              {/* Bottom row: Telemetry metric chip */}
              <div className="pt-1 border-t border-slate-100 flex items-center justify-between text-[10px] font-mono">
                {metric ? (
                  <span className="font-semibold text-indigo-600 bg-indigo-50 px-1.5 py-0.2 rounded border border-indigo-100 truncate">
                    {metric}
                  </span>
                ) : (
                  <span className="text-slate-400 text-[9px]">Chi tiết</span>
                )}
                <ChevronRight className="w-3 h-3 text-slate-300 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" />
              </div>
            </button>
          );
        })}
      </div>

      {/* Active Agent Subtasks Quick Status (when result exists) */}
      {result && result.agent_results && result.agent_results.length > 0 && (
        <div className="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3 text-xs bg-slate-50/70 p-2.5 rounded-lg">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-700 text-[11px] flex items-center gap-1">
              <Users className="w-3.5 h-3.5 text-indigo-600" />
              Đầu ra tác tử đã nhận:
            </span>
            <div className="flex flex-wrap items-center gap-1.5">
              {result.agent_results.map((agent, aIdx) => {
                const isDb = agent.agent_role.includes('Database');
                const isApi = agent.agent_role.includes('API');
                return (
                  <span
                    key={aIdx}
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium border flex items-center gap-1 ${
                      isDb 
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200' 
                        : isApi 
                        ? 'bg-sky-50 text-sky-700 border-sky-200' 
                        : 'bg-rose-50 text-rose-700 border-rose-200'
                    }`}
                  >
                    {isDb ? <Database className="w-2.5 h-2.5" /> : isApi ? <Code2 className="w-2.5 h-2.5" /> : <Shield className="w-2.5 h-2.5" />}
                    <span>{agent.task_id ? `${agent.task_id} · ` : ''}{agent.agent_role}: {agent.latency_ms}ms</span>
                  </span>
                );
              })}
            </div>
          </div>

          <div className="flex items-center gap-1.5 text-[11px] font-mono text-slate-500">
            <Info className="w-3 h-3 text-slate-400" />
            <span>Bấm vào bất kỳ ô nào ở trên để mở bảng soi chi tiết kỹ thuật</span>
          </div>
        </div>
      )}
    </div>
  );
};
