import type {
  ActivityStage,
  AgentId,
  AgentProfile,
  ComplexityScenario,
  ComplexityTier,
  CoreAgentId,
  RobotAction,
  SpecialistAgentId,
} from './types';

/**
 * Compact Scandinavian Architectural Cutaway Office (17.6m wide x 13.4m deep):
 * Every robot is 35–40% larger and crystal clear in overview framing!
 *
 * - North Back Wall (z = -6.4): Live 3D Mission Control Screen showing current question & progress
 * - Upper Left (x = -5.6, z = -4.2): Tủ Hồ Sơ & Thư Viện Tài Liệu (02. RAG Specialist)
 * - Upper Center (x = 0, z = -3.8): Khu Điều Phối & Bảng Kế Hoạch (01. Orchestrator — gộp Planner)
 * - Upper Right (x = +5.6, z = -3.9): Bàn Biên Tập & Đóng Quyển (05. Integrator — gộp Writer)
 * - Mid Left (x = -5.4, z = -0.1): Bàn Bản Vẽ & Giá Biểu Đồ (03. Data Analyst — Tùy chọn)
 * - Mid Center (x = 0, z = -0.4): Thảm Hội Ý Trung Tâm & Bục Nhận Yêu Cầu (Reception / Brainstorming)
 * - Mid Right (x = +5.4, z = -0.1): Bàn Kiểm Định & Ghế Nghỉ (04. Reviewer — Có điều kiện)
 * - Main Walkway (z = +2.15): Clean wide oak corridor connecting Core Studio to 6 Specialist Bays
 * - South Wing (z = +4.6): 6 Phòng Ban Chuyên Ngành làm việc trên máy tính!
 */
export const MAIN_WALKWAY_Z = 2.15;
export const HUDDLE_CENTER: [number, number] = [0, -0.45];
export const RECEPTION_SPOT: [number, number] = [0, -1.25];
export const WHITEBOARD_SPOT: [number, number] = [0.2, -4.35];
export const CABINET_SPOT: [number, number] = [-5.45, -4.45];
export const ANALYST_EASEL_SPOT: [number, number] = [-3.85, -0.55];

export const AGENT_PROFILES: Record<AgentId, AgentProfile> = {
  // ===== 5 CORE / CONDITIONAL / OPTIONAL AGENTS =====
  orchestrator: {
    id: 'orchestrator',
    code: '01',
    availability: 'always',
    availabilityLabelVi: 'Cốt lõi · Gộp Planner',
    name: 'Orchestrator',
    shortName: 'Orchestrator',
    titleVi: 'Giám đốc Điều phối & Lập kế hoạch',
    roomLabel: 'Khu Điều Phối & Bảng Kế Hoạch',
    roomSubtitle: 'Nhận yêu cầu · Lập kế hoạch · Chia việc',
    duties: [
      'Nhận câu hỏi từ người dùng tại Bục Tiếp Nhận',
      'Cầm bảng phân công & gậy chỉ huy lập kế hoạch lên bảng',
      'Đánh thức đúng chuyên gia và chia việc trực tiếp tới từng phòng ban',
    ],
    accentHex: '#d97706',
    accentNumber: 0xd97706,
    stationCenter: [0, -3.9],
    workPos: [0, -3.75],
    workFacingYaw: 0,
    sleepPos: [0, -3.55],
    sleepFacingYaw: Math.PI,
    sleepSeated: false,
    workSeated: false,
    corridorEntry: [0, 1.0],
    corridorZ: MAIN_WALKWAY_Z,
  },
  rag: {
    id: 'rag',
    code: '02',
    availability: 'always',
    availabilityLabelVi: 'Cốt lõi · Truy xuất RAG',
    name: 'RAG Specialist',
    shortName: 'RAG Specialist',
    titleVi: 'Chuyên viên Truy xuất Tài liệu RAG',
    roomLabel: 'Tủ Hồ Sơ & Thư Viện RAG',
    roomSubtitle: 'Kéo tủ hồ sơ · Lấy tài liệu liên quan',
    duties: [
      'Mở ngăn kéo tủ hồ sơ & đọc kho tài liệu người dùng tải lên',
      'Trích lọc đúng tập hồ sơ ngữ cảnh cho từng chuyên gia',
      'Ôm tập hồ sơ đi bàn giao tận bàn cho phòng ban phụ trách',
    ],
    accentHex: '#0891b2',
    accentNumber: 0x0891b2,
    stationCenter: [-5.6, -4.2],
    workPos: [-5.45, -4.35],
    workFacingYaw: Math.PI, // facing the filing cabinet along north wall
    sleepPos: [-6.45, -3.2],
    sleepFacingYaw: -Math.PI * 0.5, // slumped at reading desk on west side
    sleepSeated: true,
    workSeated: false,
    corridorEntry: [-3.4, 1.0],
    corridorZ: MAIN_WALKWAY_Z,
  },
  analyst: {
    id: 'analyst',
    code: '03',
    availability: 'optional',
    availabilityLabelVi: 'Tùy chọn · Khi có số liệu',
    name: 'Data Analyst',
    shortName: 'Data Analyst',
    titleVi: 'Chuyên viên Phân tích Số liệu',
    roomLabel: 'Bàn Bản Vẽ & Biểu Đồ',
    roomSubtitle: 'Bút · Máy tính · Thước kẻ trên giấy & bảng',
    duties: [
      'Chỉ thức dậy khi câu hỏi cần tính toán, phân tích KPI, biểu đồ',
      'Cầm bút, thước kẻ và máy tính tính toán trên bản giấy & bảng biểu đồ',
      'Nằm gục ngủ trên bàn khi câu hỏi không cần phân tích số liệu',
    ],
    accentHex: '#2563eb',
    accentNumber: 0x2563eb,
    stationCenter: [-5.4, -0.1],
    workPos: [-5.4, 0.42],
    workFacingYaw: Math.PI, // seated facing drafting table north
    sleepPos: [-5.4, 0.42],
    sleepFacingYaw: Math.PI,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [-3.0, 1.1],
    corridorZ: MAIN_WALKWAY_Z,
  },
  reviewer: {
    id: 'reviewer',
    code: '04',
    availability: 'conditional',
    availabilityLabelVi: 'Có điều kiện · Câu hỏi vừa/khó',
    name: 'Reviewer',
    shortName: 'Reviewer',
    titleVi: 'Chuyên viên Kiểm định Chất lượng',
    roomLabel: 'Bàn Kiểm Định & Duyệt Hồ Sơ',
    roomSubtitle: 'Cầm bảng kẹp giấy & bút chấm duyệt',
    duties: [
      'Nằm gục ngủ khi câu hỏi dễ / khá dễ không cần kiểm định',
      'Thức dậy cầm kẹp giấy & bút đối chiếu kết quả các chuyên gia',
      'Đóng dấu đạt chuẩn hoặc yêu cầu bổ sung trước khi tổng hợp',
    ],
    accentHex: '#dc2626',
    accentNumber: 0xdc2626,
    stationCenter: [5.4, -0.1],
    workPos: [5.4, 0.42],
    workFacingYaw: Math.PI, // facing QC desk
    sleepPos: [5.4, 0.42],
    sleepFacingYaw: Math.PI,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [3.0, 1.1],
    corridorZ: MAIN_WALKWAY_Z,
  },
  integrator: {
    id: 'integrator',
    code: '05',
    availability: 'always',
    availabilityLabelVi: 'Cốt lõi · Gộp Writer',
    name: 'Integrator',
    shortName: 'Integrator',
    titleVi: 'Tổng hợp & Biên soạn Đầu ra',
    roomLabel: 'Bàn Biên Tập & Đóng Quyển',
    roomSubtitle: 'Tổng hợp · Viết báo cáo · Trả kết quả',
    duties: [
      'Nhận bài đã duyệt từ các chuyên gia & Reviewer',
      'Biên soạn nội dung mạch lạc, trình bày hoàn chỉnh (gộp Writer)',
      'Đóng quyển báo cáo cuối cùng và bàn giao cho người dùng',
    ],
    accentHex: '#7c3aed',
    accentNumber: 0x7c3aed,
    stationCenter: [5.6, -4.0],
    workPos: [5.6, -3.45],
    workFacingYaw: Math.PI,
    sleepPos: [5.6, -3.45],
    sleepFacingYaw: Math.PI,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [3.4, 1.0],
    corridorZ: MAIN_WALKWAY_Z,
  },

  // ===== 6 SPECIALIST DEPARTMENTS (Working on desktop computers across South Wing) =====
  software: {
    id: 'software',
    code: '06',
    availability: 'specialist',
    availabilityLabelVi: 'Chuyên ngành · CNTT',
    name: 'Software Engineer',
    shortName: 'Software',
    titleVi: 'Kỹ sư Phần mềm',
    roomLabel: 'Phòng CNTT',
    roomSubtitle: 'Thiết kế API · Database · Code',
    duties: [
      'Phân tích yêu cầu kỹ thuật & thiết kế kiến trúc hệ thống',
      'Lập trình & kiểm thử trên máy tính chuyên dụng',
    ],
    accentHex: '#3730a3',
    accentNumber: 0x3730a3,
    stationCenter: [-6.75, 4.65],
    workPos: [-6.75, 4.55],
    workFacingYaw: 0, // facing south monitor at z = 5.35
    sleepPos: [-6.75, 4.55],
    sleepFacingYaw: 0,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [-6.75, 2.85],
    corridorZ: MAIN_WALKWAY_Z,
  },
  business: {
    id: 'business',
    code: '07',
    availability: 'specialist',
    availabilityLabelVi: 'Chuyên ngành · Kinh doanh',
    name: 'Business Consultant',
    shortName: 'Business',
    titleVi: 'Chuyên gia Kinh doanh',
    roomLabel: 'Phòng Kinh doanh',
    roomSubtitle: 'Mô hình · Chiến lược tăng trưởng',
    duties: [
      'Phân tích mô hình kinh doanh & kế hoạch vận hành',
      'Xây dựng lộ trình chiến lược trên máy tính',
    ],
    accentHex: '#9a3412',
    accentNumber: 0x9a3412,
    stationCenter: [-4.05, 4.65],
    workPos: [-4.05, 4.55],
    workFacingYaw: 0,
    sleepPos: [-4.05, 4.55],
    sleepFacingYaw: 0,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [-4.05, 2.85],
    corridorZ: MAIN_WALKWAY_Z,
  },
  marketing: {
    id: 'marketing',
    code: '08',
    availability: 'specialist',
    availabilityLabelVi: 'Chuyên ngành · Marketing',
    name: 'Marketing Agent',
    shortName: 'Marketing',
    titleVi: 'Chuyên viên Marketing',
    roomLabel: 'Phòng Marketing',
    roomSubtitle: 'Thị trường · Chiến dịch quảng cáo',
    duties: [
      'Nghiên cứu thị trường & phân tích hiệu quả quảng cáo',
      'Thiết lập phễu truyền thông trên máy tính',
    ],
    accentHex: '#ea580c',
    accentNumber: 0xea580c,
    stationCenter: [-1.35, 4.65],
    workPos: [-1.35, 4.55],
    workFacingYaw: 0,
    sleepPos: [-1.35, 4.55],
    sleepFacingYaw: 0,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [-1.35, 2.85],
    corridorZ: MAIN_WALKWAY_Z,
  },
  hr: {
    id: 'hr',
    code: '09',
    availability: 'specialist',
    availabilityLabelVi: 'Chuyên ngành · Nhân sự',
    name: 'HR Specialist',
    shortName: 'HR',
    titleVi: 'Chuyên viên Nhân sự',
    roomLabel: 'Phòng Nhân sự',
    roomSubtitle: 'Hồ sơ ứng viên · Đánh giá nhân sự',
    duties: [
      'Sàng lọc hồ sơ ứng viên & xây dựng mô tả công việc',
      'Tổng hợp bảng chấm điểm phỏng vấn trên máy tính',
    ],
    accentHex: '#db2777',
    accentNumber: 0xdb2777,
    stationCenter: [1.35, 4.65],
    workPos: [1.35, 4.55],
    workFacingYaw: 0,
    sleepPos: [1.35, 4.55],
    sleepFacingYaw: 0,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [1.35, 2.85],
    corridorZ: MAIN_WALKWAY_Z,
  },
  finance: {
    id: 'finance',
    code: '10',
    availability: 'specialist',
    availabilityLabelVi: 'Chuyên ngành · Tài chính',
    name: 'Finance Agent',
    shortName: 'Finance',
    titleVi: 'Chuyên viên Tài chính',
    roomLabel: 'Phòng Tài chính',
    roomSubtitle: 'Ngân sách · Thu chi · Báo cáo',
    duties: [
      'Phân tích thu chi, dòng tiền & lập dự toán ngân sách',
      'Kiểm tra bảng cân đối tài chính trên máy tính',
    ],
    accentHex: '#15803d',
    accentNumber: 0x15803d,
    stationCenter: [4.05, 4.65],
    workPos: [4.05, 4.55],
    workFacingYaw: 0,
    sleepPos: [4.05, 4.55],
    sleepFacingYaw: 0,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [4.05, 2.85],
    corridorZ: MAIN_WALKWAY_Z,
  },
  education: {
    id: 'education',
    code: '11',
    availability: 'specialist',
    availabilityLabelVi: 'Chuyên ngành · Giáo dục',
    name: 'Education & Research',
    shortName: 'Education',
    titleVi: 'Chuyên viên Giáo dục & Nghiên cứu',
    roomLabel: 'Phòng Nghiên cứu',
    roomSubtitle: 'Học thuật · Tài liệu đào tạo',
    duties: [
      'Đọc hiểu tài liệu chuyên sâu & tổng hợp khung nghiên cứu',
      'Soạn thảo giáo trình & báo cáo học thuật trên máy tính',
    ],
    accentHex: '#a21caf',
    accentNumber: 0xa21caf,
    stationCenter: [6.75, 4.65],
    workPos: [6.75, 4.55],
    workFacingYaw: 0,
    sleepPos: [6.75, 4.55],
    sleepFacingYaw: 0,
    sleepSeated: true,
    workSeated: true,
    corridorEntry: [6.75, 2.85],
    corridorZ: MAIN_WALKWAY_Z,
  },
};

export const CORE_AGENT_IDS: CoreAgentId[] = [
  'orchestrator',
  'rag',
  'analyst',
  'reviewer',
  'integrator',
];

export const SPECIALIST_AGENT_IDS: SpecialistAgentId[] = [
  'software',
  'business',
  'marketing',
  'hr',
  'finance',
  'education',
];

export const ALL_AGENT_IDS: AgentId[] = [
  ...CORE_AGENT_IDS,
  ...SPECIALIST_AGENT_IDS,
];

export const ACTION_LABELS_VI: Record<RobotAction, string> = {
  sleeping: 'Zzz',
  waking_up: 'Vừa thức dậy',
  idle: 'Sẵn sàng',
  walking: 'Đang di chuyển',
  receiving: 'Nhận yêu cầu / hồ sơ',
  planning_board: 'Lập kế hoạch & chia việc',
  cabinet_rag: 'Mở tủ lấy tài liệu RAG',
  drafting_analysis: 'Tính toán bằng bút, thước & máy tính',
  working_computer: 'Xử lý trên máy tính',
  thinking: 'Đang suy nghĩ phương án',
  brainstorming: 'Hội ý nhóm tại trung tâm',
  reviewing_paper: 'Cầm giấy & bút kiểm định',
  handing_over: 'Đang bàn giao hồ sơ',
  integrating: 'Tổng hợp & đóng quyển báo cáo',
  completed: 'Đã bàn giao hoàn tất',
};

export const COMPLEXITY_META: Record<
  ComplexityTier,
  { label: string; range: string; accent: string }
> = {
  easy: { label: 'Dễ', range: '5 – 10 giây', accent: '#10b981' },
  fairly_easy: { label: 'Khá dễ', range: '10 – 20 giây', accent: '#0ea5e9' },
  medium: { label: 'Vừa', range: '30 – 60 giây', accent: '#f59e0b' },
  hard: { label: 'Khó · Chuyên sâu', range: '2 – 3 phút', accent: '#7c3aed' },
};

export function computeStudioWalkPath(
  fromPos: [number, number],
  toPos: [number, number],
  fromCorridorEntry: [number, number],
  toCorridorEntry: [number, number],
): Array<[number, number]> {
  const pts: Array<[number, number]> = [];
  const fromSouth = fromPos[1] > 2.5;
  const toSouth = toPos[1] > 2.5;

  if (fromSouth !== toSouth) {
    pts.push(fromCorridorEntry);
    pts.push([fromCorridorEntry[0], MAIN_WALKWAY_Z]);
    pts.push([toCorridorEntry[0], MAIN_WALKWAY_Z]);
    pts.push(toCorridorEntry);
  } else if (fromSouth && toSouth) {
    pts.push([fromPos[0], MAIN_WALKWAY_Z]);
    pts.push([toPos[0], MAIN_WALKWAY_Z]);
  }
  pts.push(toPos);
  return pts;
}

/**
 * 4 Crystal-Clear Step-by-Step Complexity Scenarios:
 * Every stage shows unmistakable action: Nhận câu hỏi -> Lập kế hoạch -> Mở tủ lấy tài liệu RAG
 * -> Chia việc tới phòng ban -> Thực thi cụ thể (máy tính / bút thước máy tính / giấy bút kiểm định) -> Tổng hợp & Trả lời!
 */
export const COMPLEXITY_SCENARIOS: ComplexityScenario[] = [
  // ===== 1. EASY (5 - 10s -> 9s) =====
  {
    id: 'tier-easy',
    tier: 'easy',
    tierLabelVi: 'Câu hỏi Dễ',
    durationRangeVi: '5 – 10 giây',
    targetDurationSec: 9,
    userRole: 'Nhân viên nội bộ',
    requestTitle: 'Tra cứu nhanh quy định nghỉ phép năm trong sổ tay nhân sự',
    summary:
      'Chỉ 3 Agent cốt lõi thức (Orchestrator → RAG Specialist → Integrator). 8 Agent còn lại nằm gục ngủ Zzz.',
    awakeAgents: ['orchestrator', 'rag', 'integrator'],
    stages: [
      {
        id: 'e-1',
        stepLabel: '1. Nhận & Lập kế hoạch',
        headline: 'Bước 1 · Orchestrator nhận câu hỏi & giao thẳng RAG',
        detail:
          'Orchestrator bước ra nhận câu hỏi tại Bục Tiếp Nhận, đánh giá là câu hỏi Dễ nên chỉ đánh thức RAG Specialist và Integrator.',
        durationSec: 2.6,
        leadActor: 'orchestrator',
        agentDirectives: [
          {
            agentId: 'orchestrator',
            action: 'planning_board',
            actionText: 'Nhận câu hỏi Dễ & vạch nhanh 2 bước',
            carryItem: 'request_brief',
            targetSpot: 'whiteboard',
          },
          {
            agentId: 'rag',
            action: 'waking_up',
            actionText: 'Thức dậy tiến tới Tủ Hồ Sơ',
          },
        ],
        dispatchTargets: {
          from: 'orchestrator',
          toList: ['rag'],
          label: 'Giao tìm mục phép năm',
        },
        effects: { requestArrived: true, whiteboardCards: 2 },
      },
      {
        id: 'e-2',
        stepLabel: '2. Lấy tài liệu RAG',
        headline: 'Bước 2 · RAG kéo ngăn tủ hồ sơ lấy sổ tay phép năm',
        detail:
          'RAG Specialist mở ngăn kéo tủ tài liệu, rút tập sổ tay nhân sự và ôm hồ sơ đi sang giao trực tiếp cho Integrator.',
        durationSec: 3.4,
        leadActor: 'rag',
        agentDirectives: [
          {
            agentId: 'rag',
            action: 'cabinet_rag',
            actionText: 'Kéo tủ hồ sơ rút tập sổ tay nhân sự',
            carryItem: 'rag_folder',
            targetSpot: 'cabinet',
          },
          {
            agentId: 'orchestrator',
            action: 'idle',
            actionText: 'Theo dõi tiến độ xử lý',
            targetSpot: 'home',
          },
        ],
        handoff: {
          from: 'rag',
          to: 'integrator',
          item: 'rag_folder',
          label: 'Mang tập sổ tay sang Integrator',
        },
        effects: { requestArrived: true, cabinetOpen: true, whiteboardCards: 2 },
      },
      {
        id: 'e-3',
        stepLabel: '3. Biên soạn & Trả lời',
        headline: 'Bước 3 · Integrator viết tóm tắt & trả kết quả ngay',
        detail:
          'Integrator (gộp Writer) trình bày gọn 3 gạch đầu dòng chính sách phép năm và bàn giao kết quả hoàn chỉnh.',
        durationSec: 3.0,
        leadActor: 'integrator',
        agentDirectives: [
          {
            agentId: 'integrator',
            action: 'integrating',
            actionText: 'Biên soạn tóm tắt & đóng quyển trả lời',
            carryItem: 'final_report',
          },
        ],
        effects: { requestArrived: true, whiteboardCards: 2, finalReportReady: true },
      },
    ],
  },

  // ===== 2. FAIRLY EASY (10 - 20s -> 16s) =====
  {
    id: 'tier-fairly-easy',
    tier: 'fairly_easy',
    tierLabelVi: 'Câu hỏi Khá dễ',
    durationRangeVi: '10 – 20 giây',
    targetDurationSec: 16,
    userRole: 'Nhân viên Nhân sự',
    requestTitle: 'Lọc nhanh 15 hồ sơ ứng viên & viết bảng tóm tắt phỏng vấn',
    summary:
      'Đánh thức 4 Agent (Orchestrator → RAG → Phòng HR → Integrator). Data Analyst, Reviewer & 5 phòng kia nằm ngủ Zzz.',
    awakeAgents: ['orchestrator', 'rag', 'hr', 'integrator'],
    stages: [
      {
        id: 'fe-1',
        stepLabel: '1. Nhận & Lập kế hoạch',
        headline: 'Bước 1 · Orchestrator nhận yêu cầu & lập kế hoạch chia việc',
        detail:
          'Orchestrator nhận bộ 15 CV, gắn 3 thẻ việc lên bảng kế hoạch và gửi lệnh đánh thức RAG cùng phòng Nhân sự (HR).',
        durationSec: 3.5,
        leadActor: 'orchestrator',
        agentDirectives: [
          {
            agentId: 'orchestrator',
            action: 'planning_board',
            actionText: 'Lập kế hoạch 3 bước & gọi phòng HR',
            carryItem: 'plan_card',
            targetSpot: 'whiteboard',
          },
          { agentId: 'rag', action: 'waking_up', actionText: 'Thức dậy chuẩn bị mở tủ hồ sơ' },
          { agentId: 'hr', action: 'waking_up', actionText: 'Thức dậy bật máy tính phòng HR' },
        ],
        dispatchTargets: {
          from: 'orchestrator',
          toList: ['rag', 'hr'],
          label: 'Phân công lọc 15 CV',
        },
        effects: { requestArrived: true, whiteboardCards: 3 },
      },
      {
        id: 'fe-2',
        stepLabel: '2. Mở tủ lấy tài liệu',
        headline: 'Bước 2 · RAG kéo tủ rút hồ sơ JD chuẩn & 15 bản CV',
        detail:
          'RAG Specialist kéo ngăn kéo tủ tài liệu, ôm tập CV bước xuống hành lang giao tận bàn máy tính cho phòng HR.',
        durationSec: 4.3,
        leadActor: 'rag',
        agentDirectives: [
          {
            agentId: 'rag',
            action: 'cabinet_rag',
            actionText: 'Mở tủ rút tập 15 CV & tiêu chuẩn JD',
            carryItem: 'rag_folder',
            targetSpot: 'cabinet',
          },
          { agentId: 'hr', action: 'thinking', actionText: 'Mở khung tiêu chí chấm điểm ứng viên' },
        ],
        handoff: {
          from: 'rag',
          to: 'hr',
          item: 'rag_folder',
          label: 'Mang tập 15 CV xuống bàn máy tính HR',
        },
        effects: { requestArrived: true, cabinetOpen: true, whiteboardCards: 3 },
      },
      {
        id: 'fe-3',
        stepLabel: '3. Phòng HR xử lý máy tính',
        headline: 'Bước 3 · Phòng HR sàng lọc ứng viên trực tiếp trên máy tính',
        detail:
          'Chuyên viên HR gõ máy tính chấm điểm từng ứng viên, chọn Top 3 sáng giá và đi lên bàn giao cho Integrator.',
        durationSec: 4.6,
        leadActor: 'hr',
        agentDirectives: [
          {
            agentId: 'hr',
            action: 'working_computer',
            actionText: 'Chấm điểm & lọc Top 3 CV trên máy tính',
            carryItem: 'specialist_doc',
          },
          {
            agentId: 'orchestrator',
            action: 'idle',
            actionText: 'Giám sát tiến độ phòng Nhân sự',
            targetSpot: 'home',
          },
        ],
        handoff: {
          from: 'hr',
          to: 'integrator',
          item: 'specialist_doc',
          label: 'Nộp danh sách Top 3 ứng viên',
        },
        effects: { requestArrived: true, whiteboardCards: 3 },
      },
      {
        id: 'fe-4',
        stepLabel: '4. Tổng hợp & Trả lời',
        headline: 'Bước 4 · Integrator biên soạn bảng phỏng vấn & hoàn tất',
        detail:
          'Integrator trình bày bảng so sánh ứng viên gọn đẹp kèm bộ câu hỏi phỏng vấn và xuất kết quả.',
        durationSec: 3.6,
        leadActor: 'integrator',
        agentDirectives: [
          {
            agentId: 'integrator',
            action: 'integrating',
            actionText: 'Biên soạn bảng đánh giá & đóng quyển',
            carryItem: 'final_report',
          },
        ],
        effects: { requestArrived: true, whiteboardCards: 3, finalReportReady: true },
      },
    ],
  },

  // ===== 3. MEDIUM (30 - 60s -> 42s) =====
  {
    id: 'tier-medium',
    tier: 'medium',
    tierLabelVi: 'Câu hỏi Vừa',
    durationRangeVi: '30 – 60 giây',
    targetDurationSec: 42,
    userRole: 'Trưởng nhóm Marketing',
    requestTitle: 'Phân tích hiệu quả chiến dịch quảng cáo Quý IV & tối ưu ngân sách',
    summary:
      'Đủ 6 bước trực quan: Nhận câu hỏi → Lập kế hoạch → Mở tủ RAG → Marketing máy tính + Analyst bút/thước/máy tính → Reviewer giấy & bút kiểm định → Integrator đóng quyển.',
    awakeAgents: [
      'orchestrator',
      'rag',
      'marketing',
      'analyst',
      'reviewer',
      'integrator',
    ],
    stages: [
      {
        id: 'm-1',
        stepLabel: '1. Nhận câu hỏi',
        headline: 'Bước 1 · Tiếp nhận yêu cầu & đánh giá độ phức tạp Vừa',
        detail:
          'Yêu cầu xuất hiện tại Bục Tiếp Nhận. Orchestrator cầm bảng phân công bước ra đọc kỹ đề bài và quyết định kích hoạt 6 Agent.',
        durationSec: 5.0,
        leadActor: 'orchestrator',
        agentDirectives: [
          {
            agentId: 'orchestrator',
            action: 'receiving',
            actionText: 'Đọc câu hỏi: Phân tích quảng cáo Q4',
            carryItem: 'request_brief',
            targetSpot: 'reception',
          },
        ],
        effects: { requestArrived: true, whiteboardCards: 1 },
      },
      {
        id: 'm-2',
        stepLabel: '2. Lập kế hoạch & Chia việc',
        headline: 'Bước 2 · Orchestrator lên bảng lập kế hoạch & đánh thức 3 vị trí',
        detail:
          'Orchestrator cầm gậy chỉ huy vạch 5 thẻ việc trên bảng kế hoạch, phát lệnh đánh thức RAG, Phòng Marketing và Data Analyst (Reviewer vẫn ngủ chờ đến khâu kiểm định).',
        durationSec: 6.5,
        leadActor: 'orchestrator',
        agentDirectives: [
          {
            agentId: 'orchestrator',
            action: 'planning_board',
            actionText: 'Vạch 5 thẻ việc & phân công rõ từng phòng',
            carryItem: 'plan_card',
            targetSpot: 'whiteboard',
          },
          { agentId: 'rag', action: 'waking_up', actionText: 'Thức dậy đi tới Tủ Hồ Sơ' },
          { agentId: 'marketing', action: 'waking_up', actionText: 'Thức dậy khởi động máy tính' },
          { agentId: 'analyst', action: 'waking_up', actionText: 'Thức dậy chuẩn bị bút, thước & máy tính' },
          { agentId: 'reviewer', action: 'sleeping', actionText: 'Zzz' },
        ],
        dispatchTargets: {
          from: 'orchestrator',
          toList: ['rag', 'marketing', 'analyst'],
          label: 'Phân công việc Q4',
        },
        effects: { requestArrived: true, whiteboardCards: 5 },
      },
      {
        id: 'm-3',
        stepLabel: '3. Mở tủ lấy tài liệu RAG',
        headline: 'Bước 3 · RAG Specialist kéo tủ lấy tập báo cáo chi tiêu Ads Q4',
        detail:
          'RAG kéo ngăn tủ tài liệu, rút tập số liệu CTR/ROAS tháng 10–12 rồi ôm hồ sơ đi xuống hành lang giao tận bàn cho Marketing.',
        durationSec: 7.5,
        leadActor: 'rag',
        agentDirectives: [
          {
            agentId: 'rag',
            action: 'cabinet_rag',
            actionText: 'Kéo ngăn tủ rút tập báo cáo Ads Q4',
            carryItem: 'rag_folder',
            targetSpot: 'cabinet',
          },
          { agentId: 'marketing', action: 'thinking', actionText: 'Chuẩn bị bảng đánh giá kênh quảng cáo' },
          {
            agentId: 'analyst',
            action: 'drafting_analysis',
            actionText: 'Kẻ bảng tính ROAS bằng thước & bút',
          },
          { agentId: 'reviewer', action: 'sleeping', actionText: 'Zzz' },
        ],
        handoff: {
          from: 'rag',
          to: 'marketing',
          item: 'rag_folder',
          label: 'Giao tập báo cáo Q4 tới phòng Marketing',
        },
        effects: { requestArrived: true, cabinetOpen: true, whiteboardCards: 5 },
      },
      {
        id: 'm-4',
        stepLabel: '4. Thực thi song song',
        headline: 'Bước 4 · Marketing chạy máy tính & Analyst đo vẽ biểu đồ trên giấy/bảng',
        detail:
          'Phòng Marketing đánh giá chiến dịch trên màn hình máy tính; Data Analyst cầm bút, thước kẻ và máy tính bấm số liệu rồi chuyển kết quả sang bàn Kiểm định.',
        durationSec: 9.0,
        leadActor: 'analyst',
        agentDirectives: [
          {
            agentId: 'marketing',
            action: 'working_computer',
            actionText: 'Phân tích kênh quảng cáo trên máy tính',
            carryItem: 'specialist_doc',
          },
          {
            agentId: 'analyst',
            action: 'drafting_analysis',
            actionText: 'Cầm bút, thước & máy tính vẽ xu hướng ROAS',
            carryItem: 'analytics_sheet',
          },
          {
            agentId: 'orchestrator',
            action: 'idle',
            actionText: 'Theo dõi tiến độ Marketing & Analyst',
            targetSpot: 'home',
          },
          { agentId: 'reviewer', action: 'waking_up', actionText: 'Thức dậy chuẩn bị giấy & bút kiểm định' },
        ],
        handoff: {
          from: 'marketing',
          to: 'reviewer',
          item: 'specialist_doc',
          label: 'Gửi kết quả sang bàn Reviewer kiểm định',
        },
        effects: { requestArrived: true, whiteboardCards: 5, analystChartActive: true },
      },
      {
        id: 'm-5',
        stepLabel: '5. Reviewer cầm giấy & bút duyệt',
        headline: 'Bước 5 · Reviewer cầm bảng kẹp giấy & bút đối chiếu từng con số',
        detail:
          'Reviewer rà soát chéo số liệu giữa Marketing và Data Analyst, tích xanh đạt chuẩn bằng bút duyệt rồi mang bộ hồ sơ lên cho Integrator.',
        durationSec: 7.5,
        leadActor: 'reviewer',
        agentDirectives: [
          {
            agentId: 'reviewer',
            action: 'reviewing_paper',
            actionText: 'Cầm bảng giấy & bút chấm duyệt đạt chuẩn',
            carryItem: 'approved_sheet',
          },
          {
            agentId: 'analyst',
            action: 'drafting_analysis',
            actionText: 'Đối chiếu phụ lục số liệu',
          },
          {
            agentId: 'integrator',
            action: 'thinking',
            actionText: 'Lên dàn ý báo cáo điều hành',
          },
        ],
        handoff: {
          from: 'reviewer',
          to: 'integrator',
          item: 'approved_sheet',
          label: 'Chuyển hồ sơ đã chấm duyệt sang Integrator',
        },
        effects: { requestArrived: true, whiteboardCards: 5, analystChartActive: true, qcApproved: true },
      },
      {
        id: 'm-6',
        stepLabel: '6. Tổng hợp & Trả lời',
        headline: 'Bước 6 · Integrator biên soạn & đóng quyển báo cáo Q4 hoàn chỉnh',
        detail:
          'Integrator (gộp Writer) hợp nhất biểu đồ và khuyến nghị ngân sách thành báo cáo hoàn chỉnh trả cho người dùng.',
        durationSec: 6.5,
        leadActor: 'integrator',
        agentDirectives: [
          {
            agentId: 'integrator',
            action: 'integrating',
            actionText: 'Biên soạn & đóng quyển báo cáo Q4',
            carryItem: 'final_report',
          },
          {
            agentId: 'orchestrator',
            action: 'planning_board',
            actionText: 'Đánh dấu hoàn tất toàn bộ kế hoạch',
            targetSpot: 'whiteboard',
          },
        ],
        effects: { requestArrived: true, whiteboardCards: 5, qcApproved: true, finalReportReady: true },
      },
    ],
  },

  // ===== 4. HARD / DEEP COLLABORATIVE (2 - 3 minutes -> 144s = 2m 24s) =====
  {
    id: 'tier-hard',
    tier: 'hard',
    tierLabelVi: 'Câu hỏi Khó · Chuyên sâu',
    durationRangeVi: '2 – 3 phút',
    targetDurationSec: 144,
    userRole: 'Ban Giám đốc · Dự án lớn',
    requestTitle:
      'Thiết kế hệ thống E-Commerce AI, mô hình kinh doanh, ngân sách 2027 & kế hoạch ra mắt',
    summary:
      'Đánh thức 9 Agent hoạt động chuyên sâu ~2p24s: Nhận bài → Lập kế hoạch → Mở tủ RAG → 4 phòng ban chạy máy tính + Analyst vẽ biểu đồ → Hội ý vòng tròn giữa phòng → Reviewer chấm duyệt & yêu cầu sửa → Tổng hợp.',
    awakeAgents: [
      'orchestrator',
      'rag',
      'analyst',
      'reviewer',
      'integrator',
      'software',
      'business',
      'marketing',
      'finance',
    ],
    stages: [
      {
        id: 'h-1',
        stepLabel: '1. Nhận & Lập kế hoạch lớn',
        headline: 'Giai đoạn 1 · Orchestrator đọc đề án lớn & đánh thức 9 Agent',
        detail:
          'Đề bài khó kéo dài: Orchestrator vạch 6 luồng việc lên bảng, phát lệnh đánh thức 4 phòng ban (CNTT, Kinh doanh, Marketing, Tài chính) cùng RAG và Data Analyst.',
        durationSec: 16,
        leadActor: 'orchestrator',
        agentDirectives: [
          {
            agentId: 'orchestrator',
            action: 'planning_board',
            actionText: 'Chia 6 luồng việc lớn lên bảng kế hoạch',
            carryItem: 'plan_card',
            targetSpot: 'whiteboard',
          },
          { agentId: 'rag', action: 'waking_up', actionText: 'Thức dậy mở tủ kho dữ liệu' },
          { agentId: 'software', action: 'waking_up', actionText: 'Thức dậy bật máy phòng CNTT' },
          { agentId: 'business', action: 'waking_up', actionText: 'Thức dậy bật máy phòng Kinh doanh' },
          { agentId: 'marketing', action: 'waking_up', actionText: 'Thức dậy bật máy phòng Marketing' },
          { agentId: 'finance', action: 'waking_up', actionText: 'Thức dậy bật máy phòng Tài chính' },
          { agentId: 'analyst', action: 'waking_up', actionText: 'Thức dậy chuẩn bị bút, thước & máy tính' },
        ],
        dispatchTargets: {
          from: 'orchestrator',
          toList: ['rag', 'software', 'business', 'marketing', 'finance', 'analyst'],
          label: 'Triệu tập 9 Agent',
        },
        effects: { requestArrived: true, whiteboardCards: 6 },
      },
      {
        id: 'h-2',
        stepLabel: '2. Mở tủ RAG đa nguồn',
        headline: 'Giai đoạn 2 · RAG kéo tủ rút hồ sơ kỹ thuật, thị trường & tài chính',
        detail:
          'RAG Specialist trích lọc tài liệu nền tảng từ tủ hồ sơ và đi xuống hành lang phân phối cho các phòng chuyên ngành.',
        durationSec: 20,
        leadActor: 'rag',
        agentDirectives: [
          {
            agentId: 'rag',
            action: 'cabinet_rag',
            actionText: 'Mở tủ lấy hồ sơ Kỹ thuật + Thị trường + Vốn',
            carryItem: 'rag_folder',
            targetSpot: 'cabinet',
          },
          { agentId: 'software', action: 'thinking', actionText: 'Suy nghĩ kiến trúc hệ thống & DB' },
          { agentId: 'business', action: 'thinking', actionText: 'Phác thảo mô hình kinh doanh' },
          { agentId: 'finance', action: 'thinking', actionText: 'Dự trù cấu trúc vốn 2027' },
          { agentId: 'marketing', action: 'thinking', actionText: 'Lập chân dung khách hàng mục tiêu' },
        ],
        handoff: {
          from: 'rag',
          to: 'software',
          item: 'rag_folder',
          label: 'Giao bộ tài liệu nền tảng xuống dãy phòng ban',
        },
        effects: { requestArrived: true, cabinetOpen: true, whiteboardCards: 6 },
      },
      {
        id: 'h-3',
        stepLabel: '3. 4 Phòng ban & Analyst làm việc',
        headline: 'Giai đoạn 3 · 4 Phòng chạy máy tính & Data Analyst tính toán trên bảng',
        detail:
          'CNTT thiết kế API/DB, Kinh doanh lập lộ trình, Marketing dựng phễu, Tài chính chạy dự toán; Data Analyst cầm bút, thước & máy tính vẽ mô phỏng doanh thu.',
        durationSec: 28,
        leadActor: 'software',
        agentDirectives: [
          {
            agentId: 'software',
            action: 'working_computer',
            actionText: 'Thiết kế API, Database trên máy tính',
            carryItem: 'specialist_doc',
          },
          {
            agentId: 'business',
            action: 'working_computer',
            actionText: 'Lập mô hình tăng trưởng trên máy tính',
            carryItem: 'specialist_doc',
          },
          {
            agentId: 'marketing',
            action: 'working_computer',
            actionText: 'Thiết kế chiến dịch ra mắt trên máy tính',
            carryItem: 'specialist_doc',
          },
          {
            agentId: 'finance',
            action: 'working_computer',
            actionText: 'Tính bảng dòng tiền CAPEX/OPEX trên máy',
            carryItem: 'specialist_doc',
          },
          {
            agentId: 'analyst',
            action: 'drafting_analysis',
            actionText: 'Cầm bút, thước & máy tính dựng 3 kịch bản',
            carryItem: 'analytics_sheet',
          },
          {
            agentId: 'orchestrator',
            action: 'planning_board',
            actionText: 'Cập nhật tiến độ 4 phòng trên bảng',
            targetSpot: 'whiteboard',
          },
        ],
        effects: { requestArrived: true, whiteboardCards: 6, analystChartActive: true },
      },
      {
        id: 'h-4',
        stepLabel: '4. Hội ý giữa phòng',
        headline: 'Giai đoạn 4 · Cả nhóm đứng quây vòng giữa phòng hội ý đồng bộ',
        detail:
          'Orchestrator, CNTT, Kinh doanh và Tài chính rời bàn bước ra thảm trung tâm thảo luận cân đối giữa chi phí hạ tầng Cloud và ngân sách tăng trưởng.',
        durationSec: 24,
        leadActor: 'business',
        agentDirectives: [
          {
            agentId: 'orchestrator',
            action: 'brainstorming',
            actionText: 'Chủ trì phiên hội ý đồng bộ',
            targetSpot: 'huddle',
          },
          {
            agentId: 'software',
            action: 'brainstorming',
            actionText: 'Trình bày phương án tối ưu Cloud',
            targetSpot: 'huddle',
          },
          {
            agentId: 'business',
            action: 'brainstorming',
            actionText: 'Thống nhất chiến lược định giá',
            targetSpot: 'huddle',
          },
          {
            agentId: 'finance',
            action: 'brainstorming',
            actionText: 'Chốt hạn mức ngân sách IT & Marketing',
            targetSpot: 'huddle',
          },
          {
            agentId: 'marketing',
            action: 'working_computer',
            actionText: 'Cập nhật phễu chuyển đổi theo hạn mức mới',
          },
          {
            agentId: 'analyst',
            action: 'drafting_analysis',
            actionText: 'Tính lại điểm hòa vốn bằng máy tính & thước',
          },
        ],
        effects: { requestArrived: true, whiteboardCards: 6, analystChartActive: true },
      },
      {
        id: 'h-5',
        stepLabel: '5. Reviewer chấm duyệt & sửa',
        headline: 'Giai đoạn 5 · Reviewer cầm giấy & bút kiểm định chéo, chốt đạt chuẩn',
        detail:
          'Reviewer thức dậy cầm bảng kẹp giấy & bút rà soát chéo toàn bộ số liệu, yêu cầu Tài chính & CNTT chỉnh khớp 4% dự phòng rồi ký duyệt gửi sang Integrator.',
        durationSec: 26,
        leadActor: 'reviewer',
        agentDirectives: [
          {
            agentId: 'reviewer',
            action: 'reviewing_paper',
            actionText: 'Cầm giấy & bút rà soát mâu thuẫn, ký duyệt',
            carryItem: 'approved_sheet',
          },
          {
            agentId: 'finance',
            action: 'working_computer',
            actionText: 'Hiệu chỉnh khớp 4% quỹ dự phòng trên máy',
            targetSpot: 'home',
          },
          {
            agentId: 'software',
            action: 'working_computer',
            actionText: 'Bổ sung phương án dự phòng SLA 99.95%',
            targetSpot: 'home',
          },
          {
            agentId: 'business',
            action: 'working_computer',
            actionText: 'Chốt chỉ tiêu doanh thu quý I–IV',
            targetSpot: 'home',
          },
          {
            agentId: 'analyst',
            action: 'drafting_analysis',
            actionText: 'Xác thực lại biểu đồ hoàn vốn ROI',
          },
        ],
        handoff: {
          from: 'reviewer',
          to: 'integrator',
          item: 'approved_sheet',
          label: 'Chuyển bộ hồ sơ đã ký duyệt sang Integrator',
        },
        effects: { requestArrived: true, whiteboardCards: 6, analystChartActive: true, qcApproved: true },
      },
      {
        id: 'h-6',
        stepLabel: '6. Biên soạn & Đóng quyển',
        headline: 'Giai đoạn 6 · Integrator tổng hợp & đóng quyển đề án 2027 hoàn chỉnh',
        detail:
          'Integrator (gộp Writer) hợp nhất kiến trúc phần mềm, chiến lược kinh doanh, ngân sách 2027 và kế hoạch Marketing thành bộ đề án hoàn chỉnh bàn giao.',
        durationSec: 30,
        leadActor: 'integrator',
        agentDirectives: [
          {
            agentId: 'integrator',
            action: 'integrating',
            actionText: 'Biên soạn & đóng quyển đề án hoàn chỉnh',
            carryItem: 'final_report',
          },
          {
            agentId: 'orchestrator',
            action: 'planning_board',
            actionText: 'Xác nhận hoàn tất toàn bộ 6 luồng việc',
            targetSpot: 'whiteboard',
          },
          {
            agentId: 'reviewer',
            action: 'idle',
            actionText: 'Xác nhận chất lượng bàn giao cuối',
          },
        ],
        effects: { requestArrived: true, whiteboardCards: 6, qcApproved: true, finalReportReady: true },
      },
    ],
  },
];

export function buildCustomComplexityScenario(params: {
  tier: ComplexityTier;
  requestTitle: string;
  specialists: SpecialistAgentId[];
  enableAnalyst: boolean;
  enableReviewer: boolean;
}): ComplexityScenario {
  const specs = params.specialists;
  const awake = new Set<AgentId>(['orchestrator', 'rag', 'integrator', ...specs]);
  if (params.enableAnalyst) awake.add('analyst');
  if (params.enableReviewer) awake.add('reviewer');

  const scale =
    params.tier === 'easy'
      ? 0.45
      : params.tier === 'fairly_easy'
        ? 0.85
        : params.tier === 'medium'
          ? 2.1
          : 5.5;

  const stages: ActivityStage[] = [
    {
      id: 'c-1',
      stepLabel: '1. Nhận & Lập kế hoạch',
      headline: 'Bước 1 · Orchestrator nhận câu hỏi & đánh thức đúng đội ngũ',
      detail: `Đánh thức ${awake.size} Agent phù hợp (${11 - awake.size} Agent còn lại nằm ngủ Zzz).`,
      durationSec: Math.max(2.5, Math.round(3.5 * scale)),
      leadActor: 'orchestrator',
      agentDirectives: [
        {
          agentId: 'orchestrator',
          action: 'planning_board',
          actionText: 'Lập kế hoạch & phân công phòng ban',
          carryItem: 'plan_card',
          targetSpot: 'whiteboard',
        },
        ...Array.from(awake)
          .filter((a) => a !== 'orchestrator' && a !== 'integrator')
          .map((agentId) => ({
            agentId,
            action: 'waking_up' as RobotAction,
            actionText: 'Thức dậy chuẩn bị nhận việc',
          })),
      ],
      dispatchTargets: {
        from: 'orchestrator',
        toList: Array.from(awake).filter((a) => a !== 'orchestrator' && a !== 'integrator'),
        label: 'Phân công nhiệm vụ',
      },
      effects: { requestArrived: true, whiteboardCards: Math.min(6, awake.size) },
    },
    {
      id: 'c-2',
      stepLabel: '2. Mở tủ lấy tài liệu RAG',
      headline: 'Bước 2 · RAG kéo tủ rút tài liệu & mang giao tận bàn',
      detail: 'Tìm kiếm ngữ cảnh trong tủ tài liệu RAG và bàn giao hồ sơ cho chuyên gia.',
      durationSec: Math.max(2.8, Math.round(4.5 * scale)),
      leadActor: 'rag',
      agentDirectives: [
        {
          agentId: 'rag',
          action: 'cabinet_rag',
          actionText: 'Kéo tủ rút tài liệu RAG liên quan',
          carryItem: 'rag_folder',
          targetSpot: 'cabinet',
        },
        ...specs.map((specId) => ({
          agentId: specId as AgentId,
          action: 'thinking' as RobotAction,
          actionText: 'Chuẩn bị phương án xử lý',
        })),
      ],
      handoff: {
        from: 'rag',
        to: specs[0] ?? (params.enableAnalyst ? 'analyst' : 'integrator'),
        item: 'rag_folder',
        label: 'Giao tập tài liệu RAG',
      },
      effects: { requestArrived: true, cabinetOpen: true, whiteboardCards: Math.min(6, awake.size) },
    },
  ];

  if (specs.length > 0 || params.enableAnalyst) {
    stages.push({
      id: 'c-3',
      stepLabel: '3. Phòng ban & Phân tích',
      headline: 'Bước 3 · Chuyên gia chạy máy tính & phân tích số liệu song song',
      detail:
        params.tier === 'hard'
          ? 'Thực hiện phân tích chuyên sâu và hội ý liên phòng ban giữa phòng.'
          : 'Các phòng ban chuyên môn xử lý trên máy tính và tính toán số liệu.',
      durationSec: Math.max(3.5, Math.round(6.5 * scale)),
      leadActor: specs[0] ?? 'analyst',
      agentDirectives: [
        ...specs.map((s) => ({
          agentId: s as AgentId,
          action: (params.tier === 'hard' ? 'brainstorming' : 'working_computer') as RobotAction,
          actionText:
            params.tier === 'hard'
              ? 'Hội ý & xử lý chuyên sâu'
              : AGENT_PROFILES[s].duties[0],
          carryItem: 'specialist_doc' as const,
          targetSpot: (params.tier === 'hard' ? 'huddle' : 'home') as 'huddle' | 'home',
        })),
        ...(params.enableAnalyst
          ? [
              {
                agentId: 'analyst' as AgentId,
                action: 'drafting_analysis' as RobotAction,
                actionText: 'Cầm bút, thước & máy tính phân tích KPI',
                carryItem: 'analytics_sheet' as const,
              },
            ]
          : []),
      ],
      handoff: {
        from: specs[0] ?? 'analyst',
        to: params.enableReviewer ? 'reviewer' : 'integrator',
        item: 'specialist_doc',
        label: params.enableReviewer ? 'Gửi Reviewer chấm duyệt' : 'Nộp Integrator tổng hợp',
      },
      effects: {
        requestArrived: true,
        whiteboardCards: Math.min(6, awake.size),
        analystChartActive: params.enableAnalyst,
      },
    });
  }

  if (params.enableReviewer) {
    stages.push({
      id: 'c-4',
      stepLabel: '4. Reviewer kiểm định',
      headline: 'Bước 4 · Reviewer cầm giấy & bút rà soát chất lượng',
      detail: 'Kiểm tra chéo độ chính xác và ký duyệt trước khi đóng gói sản phẩm.',
      durationSec: Math.max(3.0, Math.round(4.2 * scale)),
      leadActor: 'reviewer',
      agentDirectives: [
        {
          agentId: 'reviewer',
          action: 'reviewing_paper',
          actionText: 'Cầm bảng giấy & bút kiểm định đạt chuẩn',
          carryItem: 'approved_sheet',
        },
        ...specs.map((s) => ({
          agentId: s as AgentId,
          action: 'working_computer' as RobotAction,
          actionText: 'Sẵn sàng bổ sung khi cần',
          targetSpot: 'home' as const,
        })),
      ],
      handoff: {
        from: 'reviewer',
        to: 'integrator',
        item: 'approved_sheet',
        label: 'Bàn giao bản đã duyệt sang Integrator',
      },
      effects: {
        requestArrived: true,
        whiteboardCards: Math.min(6, awake.size),
        qcApproved: true,
      },
    });
  }

  stages.push({
    id: 'c-final',
    stepLabel: `${stages.length + 1}. Tổng hợp & Trả lời`,
    headline: 'Bước cuối · Integrator biên soạn & đóng quyển kết quả hoàn chỉnh',
    detail: 'Tổng hợp toàn bộ nội dung thành báo cáo mạch lạc và bàn giao.',
    durationSec: Math.max(3.0, Math.round(4.5 * scale)),
    leadActor: 'integrator',
    agentDirectives: [
      {
        agentId: 'integrator',
        action: 'integrating',
        actionText: 'Tổng hợp & đóng quyển báo cáo cuối',
        carryItem: 'final_report',
      },
    ],
    effects: {
      requestArrived: true,
      whiteboardCards: Math.min(6, awake.size),
      qcApproved: params.enableReviewer,
      finalReportReady: true,
    },
  });

  const totalSec = stages.reduce((acc, st) => acc + st.durationSec, 0);
  const meta = COMPLEXITY_META[params.tier];

  return {
    id: `custom-${Date.now()}`,
    tier: params.tier,
    tierLabelVi: `Tùy chỉnh · ${meta.label}`,
    durationRangeVi: `~${totalSec}s`,
    targetDurationSec: totalSec,
    userRole: 'Kịch bản tùy chỉnh',
    requestTitle: params.requestTitle,
    summary: `Kích hoạt ${awake.size} Agent, ${11 - awake.size} Agent ngủ Zzz.`,
    awakeAgents: Array.from(awake),
    stages,
  };
}
