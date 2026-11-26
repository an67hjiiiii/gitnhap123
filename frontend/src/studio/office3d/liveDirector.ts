// Đợt 6 (23/11): chuyển sự kiện THẬT của lượt chạy thành hành động trong văn phòng 3D.
// Quy tắc: chỉ diễn điều máy chủ báo; ai không được giao việc thì ngủ; việc chạy lần lượt thì diễn lần lượt;
// câu trả lời không chờ hoạt cảnh (lớp này chỉ nhận sự kiện, không chặn gì).
// Chỉ dùng `import type` để chạy được test bằng node --experimental-strip-types.
import type { AgentId, CarryItemKind, RobotAction } from './types';

export interface LiveEvent {
  type?: string;          // 'progress' | 'answer' | 'queue' (luồng trực tiếp); không có khi xem lại từ run.events
  stage?: string;
  task_id?: string;
  domain?: string;
  agents?: string[];
  classification?: string;
  position?: number;
  result?: { task_id?: string; domain?: string; status?: string };
  review_status?: string;
  limit?: number;
  waves?: string[][];
  unsupported?: unknown[] | number;  // run.events: danh sách; luồng trực tiếp: chỉ số lượng
  source?: string;          // knowledge_source: documents | general | both
  tool?: string;            // agent_tool: công cụ chuyên gia tự dùng (search: tự tìm thêm tài liệu)
  added?: number;           // agent_tool: số đoạn tài liệu mới tìm thêm được
  before?: string;          // agent_tool_result: trạng thái trước/sau khi làm lại
  after?: string;
  revision?: boolean;       // synthesis_started: Integrator viết lại sau khi Reviewer trả bài
  selected_count?: number;  // số đoạn tài liệu tìm được (chỉ số lượng)
  task_count?: number;      // số việc con của kế hoạch
  has_documents?: boolean;  // knowledge_source_policy
  document_bound?: boolean;
  // 25/11: số lượng cho các cơ chế điều phối (luồng trực tiếp gửi số; run.events lưu danh sách đầy đủ)
  removed?: number;         // normalization: số việc trùng đã gộp
  checked?: number;         // review_finished: số ý đã đối chiếu
  candidate_count?: number; // task_retrieval: số đoạn ứng viên
  dropped_count?: number;   // task_retrieval: số đoạn bị lọc (trùng / vượt ngân sách ngữ cảnh)
  budget_tasks?: number;    // adaptive_budget_plan: số việc được chia ngân sách
  total_tokens?: number;    // adaptive_budget_plan: tổng ngân sách ngữ cảnh (token)
  selected?: unknown[];
  candidates?: unknown[];
  dropped?: unknown[];
  tasks?: unknown[];
  limits?: Record<string, unknown>;
  // 26/11 (V4/V5): metadata sạch phục vụ Khung Chat Nội Bộ Văn Phòng (chỉ tên file sạch, mục tiêu ngắn & nhãn status)
  doc_names?: string[];
  task_goal?: string;
  status?: string;
}

/** Loại trao đổi giữa hai Agent: mỗi loại một màu trên đồ thị luồng 3D. */
export type FlowKind = 'dispatch' | 'rag' | 'result' | 'fail' | 'revise' | 'approve';
export interface FlowEdge { from: AgentId; to: AgentId; kind: FlowKind; count: number; label: string }
/** Tin nhắn hội thoại nội bộ trong nhóm chat công việc văn phòng, sinh trực tiếp từ sự kiện thật của pipeline. */
export type OfficeChatKind = 'plan' | 'rag' | 'work' | 'tool' | 'review' | 'revise' | 'done' | 'error';
export type OfficeChatPhase = 'intake' | 'work' | 'review' | 'done';
export type OfficeChatMood = 'focus' | 'happy' | 'warn';
export interface OfficeChatAttachment {
  icon: 'doc' | 'task' | 'qc_ok' | 'qc_warn' | 'done';
  title: string;
  subtitle?: string;
}
export interface OfficeChatMessage {
  id: string;
  from: AgentId;
  to: AgentId | 'all' | 'user';
  kind: OfficeChatKind;
  phase: OfficeChatPhase;
  mood: OfficeChatMood;
  text: string;
  badge?: string;
  attachment?: OfficeChatAttachment;
}
/** Số đo của lượt chạy, lấy từ sự kiện thật; null = máy chủ chưa báo (không đoán). */
export interface LiveMetrics {
  route: 'simple' | 'complex' | null;
  agents: number;
  tasks: number | null;
  removed: number | null;
  waves: number | null;
  parallel: number | null;
  budgetTokens: number | null;
  chunks: number | null;
  checked: number | null;
  unsupported: number | null;
  revisions: number;
  flows: number;
}
const NO_METRICS: LiveMetrics = { route: null, agents: 0, tasks: null, removed: null, waves: null, parallel: null, budgetTokens: null, chunks: null, checked: null, unsupported: null, revisions: 0, flows: 0 };
const count = (n?: number, arr?: unknown[]): number | null => (typeof n === 'number' ? n : Array.isArray(arr) ? arr.length : null);

export type LiveTempo = 'realtime' | 'easy';

export interface LiveController {
  resetToSleep(): void;
  /** hết lượt: robot đang đi thì đi nhanh cho xong ngay, không lết sau khi câu trả lời đã ra */
  settle?(): void;
  /** robot tự đi tới đưa hồ sơ; onArrive gọi khi đã trao xong */
  walkAndHandoff?(from: AgentId, to: AgentId, item: CarryItemKind, label?: string, onArrive?: () => void): void;
  wakeAgents(ids: AgentId[]): void;
  putAgentsToSleep(ids: AgentId[]): void;
  setAgentAction(id: AgentId, action: RobotAction, text?: string, carry?: CarryItemKind, spot?: 'whiteboard' | 'board_review' | 'reception' | 'cabinet' | 'easel'): void;
  setLiveScene(opts: {
    lead?: AgentId | null;
    effects?: Partial<{ requestArrived: boolean; cabinetOpen: boolean; whiteboardCards: number; analystChartActive: boolean; qcApproved: boolean; finalReportReady: boolean }>;
    dispatch?: { from: AgentId; toList: AgentId[] };
    /** loại và nhãn của lần trao đổi đi kèm dispatch (màu và chữ trên đường nối) */
    flow?: { kind: FlowKind; label: string };
    wall?: { tierLabel: string; requestTitle: string; stepText: string; progressPct: number };
  }): void;
}

export type LiveStepState = 'now' | 'done' | 'fail';
export interface LiveStep { key: string; label: string; actor: AgentId; state: LiveStepState }
export interface LiveState {
  question: string;
  headline: string;
  steps: LiveStep[];
  awake: AgentId[];
  /** V10: danh sách Agent đang thực sự làm việc tại thời điểm hiện tại (nguồn sự thật duy nhất cho cả 3D luồng nối lẫn Khung Chat). */
  activeWorkers: AgentId[];
  finished: boolean;
  failed: boolean;
  /** số giây đang chờ mô hình (không có sự kiện mới); null khi đang có việc diễn ra */
  waitingSec: number | null;
  /** mô tả tự nhiên công việc đang diễn ra (hiện trên thanh trạng thái & typing indicator thay cho "chờ mô hình") */
  activeWorkLabel: string | null;
  /** các cặp Agent đã trao đổi trong lượt (đồ thị luồng điều phối) */
  edges: FlowEdge[];
  /** hội thoại nội bộ văn phòng giữa các Agent sinh từ sự kiện thật */
  chatFeed: OfficeChatMessage[];
  metrics: LiveMetrics;
}

/** Tên tiếng Việt của tác tử máy chủ (bộ work, office, Phần mềm). */
export const DOMAIN_VI: Record<string, string> = {
  general: 'Chuyên viên tổng hợp', conditions: 'Agent Điều kiện', procedure: 'Agent Quy trình', terms: 'Agent Điều khoản', figures: 'Agent Số liệu',
  software: 'Chuyên gia Phần mềm', business: 'Chuyên gia Kinh doanh', marketing: 'Chuyên gia Marketing', hr: 'Chuyên gia Nhân sự',
  finance: 'Chuyên gia Tài chính', education: 'Chuyên gia Giáo dục', analyst: 'Data Analyst',
  security: 'Agent Bảo mật', database: 'Agent Dữ liệu', api_architecture: 'Agent Kiến trúc API',
};

const SPECIALISTS = new Set(['software', 'business', 'marketing', 'hr', 'finance', 'education']);

/** Nhân vật 3D làm việc của tác tử máy chủ. Chuyên viên tổng hợp (general) viết câu trả lời nên ngồi bàn Integrator;
 *  tác tử bộ work chưa có bàn riêng ngồi bàn RAG, nhãn vẫn ghi đúng tên tác tử thật. */
export function characterFor(domain?: string): AgentId {
  if (!domain) return 'rag';
  if (domain === 'general') return 'integrator';
  if (SPECIALISTS.has(domain)) return domain as AgentId;
  if (domain === 'analyst' || domain === 'figures') return 'analyst';
  if (domain === 'security' || domain === 'database' || domain === 'api_architecture') return 'software';
  return 'rag';
}

const label = (domain?: string) => DOMAIN_VI[domain ?? ''] ?? (domain ? `Agent ${domain}` : 'Agent');

/** Mô tả tự nhiên công việc hiện tại của Agent (dùng cho typing indicator & thanh trạng thái). */
function workHintFor(actor: AgentId, stepKey?: string): string {
  if (actor === 'orchestrator') {
    if (stepKey === 'plan') return 'Orchestrator đang phân rã yêu cầu & lập kế hoạch chia việc...';
    if (stepKey === 'select') return 'Orchestrator đang chọn chuyên gia phù hợp...';
    if (stepKey === 'source') return 'Orchestrator đang xác định nguồn tri thức ưu tiên...';
    return 'Orchestrator đang đọc hiểu yêu cầu & điều phối công việc...';
  }
  if (actor === 'rag') return 'RAG Specialist đang rà soát và trích lọc đoạn tài liệu liên quan...';
  if (actor === 'reviewer') {
    if (stepKey === 'verify') return 'Reviewer đang rà soát bảng kế hoạch để tránh bỏ sót ý...';
    return 'Reviewer đang đối chiếu từng số liệu và nhận định với tài liệu gốc...';
  }
  if (actor === 'integrator') {
    if (stepKey === 'revise') return 'Integrator đang hiệu chỉnh lại câu trả lời theo góp ý của Reviewer...';
    return 'Integrator đang tổng hợp dữ liệu và biên soạn câu trả lời hoàn chỉnh...';
  }
  if (actor === 'analyst') return 'Data Analyst đang tính toán và đối chiếu số liệu...';
  return `${label(actor)} đang phân tích tài liệu & viết nhận định chuyên môn...`;
}

function cleanDocNames(docs?: string[]): string {
  if (!Array.isArray(docs) || !docs.length) return '';
  const list = docs.filter((d): d is string => typeof d === 'string' && d.trim().length > 0);
  if (!list.length) return '';
  const head = list.slice(0, 2).join(', ');
  return list.length > 2 ? `${head} (+${list.length - 2} tài liệu)` : head;
}

function shortGoal(raw?: string, maxLen = 78): string {
  const s = (raw ?? '').replace(/\s+/g, ' ').trim();
  if (!s) return '';
  return s.length > maxLen ? `${s.slice(0, maxLen - 1).trim()}…` : s;
}

function specialistAckFor(who: AgentId, taskId?: string): string {
  const tag = taskId ? ` ${taskId}` : '';
  switch (who) {
    case 'finance':
      return `Đã nhận việc${tag}! Mình đang đối chiếu các bảng số liệu và chỉ tiêu tài chính liên quan ngay.`;
    case 'hr':
      return `Đã nhận việc${tag}! Mình đang rà quy chế nhân sự, chế độ phúc lợi và điều kiện áp dụng ngay.`;
    case 'software':
      return `Đã nhận việc${tag}! Mình đang kiểm tra thông số kỹ thuật, SLA và kiến trúc hệ thống ngay.`;
    case 'analyst':
      return `Đã nhận việc${tag}! Mình đang tổng hợp dữ liệu và kiểm chứng các phép tính liên quan ngay.`;
    case 'business':
      return `Đã nhận việc${tag}! Mình đang phân tích mục tiêu vận hành và các chỉ số kinh doanh liên quan ngay.`;
    case 'marketing':
      return `Đã nhận việc${tag}! Mình đang rà số liệu thị trường và kế hoạch triển khai liên quan ngay.`;
    case 'education':
      return `Đã nhận việc${tag}! Mình đang đối chiếu nội dung đào tạo và chuẩn đánh giá liên quan ngay.`;
    default:
      return `Đã nhận việc${tag}! Mình đang kiểm tra tài liệu liên quan và phân tích ngay đây.`;
  }
}

export class LiveDirector {
  private c: LiveController;
  private onState: (s: LiveState) => void;
  private state: LiveState = { question: '', headline: '', steps: [], awake: [], activeWorkers: [], finished: false, failed: false, waitingSec: null, activeWorkLabel: null, edges: [], chatFeed: [], metrics: { ...NO_METRICS } };
  private awake = new Set<AgentId>();
  private participants = new Set<AgentId>();
  private cards = 0;
  private msgSeq = 0;
  private finalStatus: string | null = null;
  private answering = false;
  private noDocs = false;              // knowledge_source_policy báo không có tài liệu: RAG ngủ
  private route: string | null = null; // SIMPLE_PROJECT_QUESTION | COMPLEX_PROJECT_REQUEST
  private synthesizing = false;
  private taskDomain = new Map<string, string>();
  private taskGoal = new Map<string, string>();
  private completedOkDomains: string[] = [];
  private missingEvidenceDomains: string[] = [];
  private spots = new Map<AgentId, Parameters<LiveController['setAgentAction']>[4]>();

  constructor(controller: LiveController, onState: (s: LiveState) => void) {
    this.c = controller;
    this.onState = onState;
  }

  getState(): LiveState { return this.state; }

  private tier = 'Trực tiếp';
  private tempo: LiveTempo = 'realtime';
  // robot đang đi trao hồ sơ: lệnh mới cho nó chờ tới khi trao xong; mỗi robot một hàng đợi trao
  private walking = new Set<AgentId>();
  private handQueue = new Map<AgentId, Array<{ to: AgentId; item: CarryItemKind; label: string }>>();
  private pendingAct = new Map<AgentId, [RobotAction, string | undefined, CarryItemKind | undefined, Parameters<LiveController['setAgentAction']>[4]]>();
  private sleepAfterWalk = new Set<AgentId>();

  /** 'realtime': bám sát sự kiện, trao việc bằng gói bay; 'easy': robot tự đi tới đưa hồ sơ. */
  setTempo(t: LiveTempo): void { this.tempo = t; }

  private quiet = false;
  /** Dựng ngay phần đã qua (mở văn phòng giữa chừng, tua): không đi trao, không ném gói cho các bước cũ. */
  catchUp(events: LiveEvent[]): void {
    this.quiet = true;
    try { events.forEach(e => this.handle(e)); } finally { this.quiet = false; }
  }

  /** tier: nhãn chế độ chiếu lên TV văn phòng ('Trực tiếp' | 'Xem lại'). */
  start(question: string, tier = 'Trực tiếp'): void {
    this.tier = tier;
    this.awake.clear();
    this.cards = 0;
    this.msgSeq = 0;
    this.finalStatus = null;
    this.answering = false;
    this.noDocs = false;
    this.route = null;
    this.synthesizing = false;
    this.taskDomain.clear();
    this.taskGoal.clear();
    this.completedOkDomains = [];
    this.missingEvidenceDomains = [];
    this.spots.clear();
    this.acts.clear();
    this.walking.clear();
    this.handQueue.clear();
    this.pendingAct.clear();
    this.sleepAfterWalk.clear();
    this.participants.clear();
    this.state = {
      question,
      headline: 'Orchestrator nhận câu hỏi',
      steps: [],
      awake: [],
      activeWorkers: ['orchestrator'],
      finished: false,
      failed: false,
      waitingSec: null,
      activeWorkLabel: workHintFor('orchestrator', 'receive'),
      edges: [],
      chatFeed: [],
      metrics: { ...NO_METRICS },
    };
    this.c.resetToSleep();
    this.wake('orchestrator');
    this.act('orchestrator', 'receiving', 'Nhận câu hỏi', 'request_brief', 'reception');
    this.say('orchestrator', 'all', 'plan', 'Mình vừa tiếp nhận yêu cầu mới từ khách hàng. Để mình đọc kỹ và phân loại đầu việc ngay nhé.');
    this.scene('orchestrator', 'Nhận câu hỏi', 5, { requestArrived: true });
    this.step('receive', 'Nhận câu hỏi', 'orchestrator');
  }

  handle(e: LiveEvent): void {
    if (this.state.finished) return;
    if (e.type === 'queue') {
      this.act('orchestrator', 'idle', `Đang chờ lượt, thứ tự ${e.position ?? '?'}`);
      return this.headline(`Máy đang trả lời người khác: chờ lượt thứ ${e.position ?? '?'}`);
    }
    if (e.type === 'answer') {
      // chữ đầu tiên: chỉ đánh thức người đang viết thật. Đường nhiều việc: chỉ sau synthesis_started.
      // Đường đơn giản: Chuyên viên tổng hợp (bàn Integrator) viết.
      if (this.answering || (this.route === 'COMPLEX_PROJECT_REQUEST' && !this.synthesizing)) return;
      this.answering = true;
      if (this.synthesizing) return;  // Integrator đã đang tổng hợp, không đổi gì
      // câu đơn giản có việc T1 (máy chủ mới): chuyên gia ngành đang làm T1 chính là người viết
      const writer = this.state.steps.find(s => s.state === 'now' && s.key.startsWith('task-'));
      if (writer) {
        this.act(writer.actor, 'working_computer', `${writer.label} đang viết câu trả lời`, 'specialist_doc', this.spots.get(writer.actor));
        return this.headline(`${writer.label} đang viết câu trả lời`);
      }
      this.wake('integrator');
      this.act('integrator', 'integrating', `${label('general')} đang viết câu trả lời`, 'final_report');
      this.scene('integrator', `${label('general')} đang viết câu trả lời`, 85);
      return this.step('write', 'Viết câu trả lời', 'integrator');
    }
    const domain = e.domain ?? e.result?.domain;
    const taskId = e.task_id ?? e.result?.task_id;
    switch (e.stage) {
      case 'agent_selection': {
        const picked = (e.agents ?? []).filter(a => a !== 'general');
        const text = picked.length ? `Chọn: ${picked.map(label).join(', ')}` : 'Chưa cần chuyên gia riêng';
        this.act('orchestrator', 'thinking', text);
        this.scene('orchestrator', text, 10);
        return this.step('select', 'Chọn chuyên gia', 'orchestrator');
      }
      case 'product_request_routing': {
        this.route = e.classification ?? null;
        const simple = e.classification === 'SIMPLE_PROJECT_QUESTION';
        this.metric({ route: simple ? 'simple' : e.classification === 'COMPLEX_PROJECT_REQUEST' ? 'complex' : null });
        const text = simple ? 'Câu đơn giản: tra tài liệu rồi trả lời' : 'Câu nhiều ý: lập kế hoạch chia việc';
        this.act('orchestrator', 'thinking', text);
        this.say(
          'orchestrator',
          'all',
          'plan',
          simple
            ? 'Câu này thuộc nhóm tra cứu gọn một chủ đề — mình đi nhánh nhanh, rút đúng tài liệu rồi trả lời thẳng luôn.'
            : 'Yêu cầu có nhiều ý cần đối chiếu — mình sẽ phân rã thành các đầu việc rõ ràng cho từng phòng nhé.',
          simple ? 'Nhánh nhanh' : 'Đa tác tử',
        );
        return this.headline(text);
      }
      case 'knowledge_source_policy': {
        // bước chọn nguồn tri thức (23/11): Orchestrator quyết định lấy tri thức từ tài liệu, kiến thức chung hay cả hai
        this.noDocs = e.has_documents === false;
        const text = e.document_bound ? 'Nguồn: chỉ tài liệu' : e.has_documents ? 'Nguồn: tài liệu, thiếu thì kiến thức chung' : 'Nguồn: kiến thức chung (không có tài liệu)';
        this.act('orchestrator', 'thinking', text);
        if (this.noDocs) {
          this.say(
            'orchestrator',
            'all',
            'plan',
            'Kho dự án hiện chưa có tài liệu đính kèm, mình chuyển hướng trả lời trực tiếp bằng kiến thức nền chuyên môn.',
          );
        }
        this.scene('orchestrator', text, 20);
        return this.step('source', 'Chọn nguồn tri thức', 'orchestrator');
      }
      case 'knowledge_source': {
        const who = characterFor(domain);
        const general = e.source === 'general' || e.source === 'both';
        if (who === 'integrator') {
          // đường đơn giản: Chuyên viên tổng hợp viết câu trả lời (Xem lại không có sự kiện answer nên dựng bước viết ở đây)
          this.wake(who);
          const text = general ? `${label(domain)} trả lời bằng ${e.source === 'general' ? 'kiến thức chung' : 'tài liệu + kiến thức chung'}` : `${label(domain)} viết câu trả lời từ tài liệu`;
          this.act(who, 'integrating', text, 'final_report');
          this.say(
            who,
            'all',
            'work',
            general
              ? `Mình đang biên soạn câu trả lời bằng ${e.source === 'general' ? 'kiến thức nền' : 'tài liệu kết hợp kiến thức nền'} đây.`
              : 'Mình đã nhận đủ đoạn tài liệu từ RAG, đang biên soạn câu trả lời gọn rõ gửi khách nhé.',
          );
          this.scene(who, text, 85, { cabinetOpen: false });
          return this.step('write', 'Viết câu trả lời', who);
        }
        if (!general) return;
        this.wake(who);
        const text = `${label(domain)} trả lời bằng ${e.source === 'general' ? 'kiến thức chung' : 'tài liệu + kiến thức chung'}`;
        this.act(who, 'working_computer', text, 'specialist_doc');
        this.say(
          who,
          'orchestrator',
          'work',
          `Đã rõ, mình sẽ xử lý phần này bằng ${e.source === 'general' ? 'kiến thức chuyên môn' : 'tài liệu kèm kiến thức chuyên môn'}.`,
        );
        return this.headline(text);
      }
      case 'request_understanding':
      case 'obligation_concern_extraction':
        this.act('orchestrator', 'thinking', 'Hiểu yêu cầu');
        this.headline('Orchestrator đọc và hiểu yêu cầu');
        return this.step('understand', 'Hiểu yêu cầu', 'orchestrator');  // bước riêng: dòng thời gian tính đúng thời gian trích nghĩa vụ
      case 'vanilla_retrieval':
      case 'planning_retrieval':
      case 'task_retrieval': {
        if (this.noDocs) {
          // không có tài liệu: RAG ngủ, Orchestrator nói rõ trả lời bằng kiến thức chung (một lần, không chen vào việc của chuyên gia)
          if (e.stage === 'task_retrieval') return;
          this.act('orchestrator', 'thinking', 'Không có tài liệu: trả lời bằng kiến thức chung');
          return this.headline('Không có tài liệu: trả lời bằng kiến thức chung');
        }
        this.wake('rag');
        const forWho = e.stage === 'task_retrieval' && domain ? ` cho ${label(domain)}` : '';
        const key = e.stage === 'task_retrieval' ? `retrieve-${taskId}` : 'retrieve';
        const selected = count(e.selected_count, e.selected);
        const dropped = count(e.dropped_count, e.dropped);
        const docsLabel = cleanDocNames(e.doc_names);
        if (selected !== null) this.metric({ chunks: (this.state.metrics.chunks ?? 0) + selected });
        // V5: với vanilla_retrieval có domain từ backend, RAG chuyển thẳng tới đúng chuyên gia ngành (không gửi nhầm Integrator!)
        const to: AgentId = e.stage === 'task_retrieval'
          ? characterFor(domain)
          : e.stage === 'planning_retrieval'
            ? 'orchestrator'
            : domain
              ? characterFor(domain)
              : 'integrator';
        if (e.stage === 'vanilla_retrieval' || e.stage === 'planning_retrieval') {
          this.say(
            'orchestrator',
            'rag',
            'plan',
            e.stage === 'planning_retrieval'
              ? 'Nhờ bạn rà nhanh kho tài liệu để mình nắm bối cảnh trước khi phân chia đầu việc nhé!'
              : `Nhờ bạn rút ngay các đoạn tài liệu khớp nhất rồi chuyển thẳng sang bàn ${to === 'integrator' ? 'Integrator' : label(domain)} nhé!`,
          );
        }
        if (selected === 0) {
          // tra rồi mà không có đoạn nào liên quan: không mở tủ, không gửi gói tài liệu
          this.act('rag', 'thinking', `Không có đoạn tài liệu liên quan${forWho}`);
          this.say('rag', to, 'rag', `Mình đã rà kỹ kho tài liệu${forWho} nhưng không thấy đoạn nào khớp trực tiếp với câu hỏi này.`);
          this.scene('rag', `RAG không thấy đoạn tài liệu liên quan${forWho}`, 30, { cabinetOpen: false });
          return this.step(key, 'Tìm tài liệu', 'rag');
        }
        // lọc bớt: đoạn trùng giữa các việc hoặc vượt ngân sách ngữ cảnh của việc đó (máy chủ chỉ báo số lượng)
        const n = selected !== null ? ` (${selected} đoạn${dropped ? `, lọc bớt ${dropped}` : ''})` : '';
        this.act('rag', 'cabinet_rag', `Tìm đoạn tài liệu${forWho}${n}`, 'rag_folder', 'cabinet');
        const fromDocs = docsLabel ? ` từ ${docsLabel}` : '';
        const ragMsg = `Mình vừa rút được ${selected !== null ? `${selected} đoạn` : 'các đoạn'} liên quan${fromDocs}${dropped ? ` (đã lọc bớt ${dropped} đoạn trùng)` : ''}, chuyển ngay hồ sơ qua bàn bạn nhé!`;
        this.say(
          'rag',
          to,
          'rag',
          ragMsg,
          selected !== null ? `${selected} đoạn` : 'Tài liệu',
          {
            icon: 'doc',
            title: docsLabel || 'Tập đoạn tài liệu liên quan',
            subtitle: selected !== null ? `${selected} đoạn trích chọn${dropped ? ` · lọc ${dropped} trùng` : ''}` : 'Hồ sơ ngữ cảnh RAG',
          },
        );
        this.scene('rag', `RAG Specialist tìm tài liệu${forWho}${n}`, 30, { cabinetOpen: true });
        this.give('rag', to, 'rag_folder', `Mang tài liệu tới ${to === 'orchestrator' ? 'Orchestrator' : to === 'integrator' ? 'người viết' : label(domain)}`,
          'rag', selected !== null ? `RAG · ${selected} đoạn` : 'RAG · tài liệu');
        return this.step(key, 'Tìm tài liệu', 'rag');
      }
      case 'normalization': {
        // khử trùng lặp việc con (cơ chế N): máy chủ báo số việc trùng đã gộp và số việc còn lại
        const n = count(e.task_count, e.tasks);
        const removed = typeof e.removed === 'number' ? e.removed : null;
        if (n !== null) this.cards = Math.min(6, n);
        this.metric({ tasks: n ?? this.state.metrics.tasks, removed });
        const text = removed ? `Khử trùng lặp: gộp ${removed} việc trùng${n !== null ? `, còn ${n} việc` : ''}`
          : `Chuẩn hóa kế hoạch${n !== null ? `: ${n} việc, không có việc trùng` : ''}`;
        this.act('orchestrator', 'planning_board', text, 'plan_card', 'whiteboard');
        this.say(
          'orchestrator',
          'all',
          'plan',
          removed
            ? `Mình vừa rà soát và gộp ${removed} đầu việc bị trùng${n !== null ? `, chốt lại còn ${n} việc gọn gàng` : ''}.`
            : `Mình đã chuẩn hóa xong bảng kế hoạch${n !== null ? ` gồm ${n} việc độc lập` : ''}, không có mục nào bị trùng lặp.`,
          n !== null ? `${n} việc` : undefined,
        );
        this.scene('orchestrator', text, 42, { whiteboardCards: this.cards, cabinetOpen: false });
        return this.step('plan', 'Lập kế hoạch', 'orchestrator');
      }
      case 'adaptive_budget_plan': {
        // phân bổ ngân sách ngữ cảnh theo nhu cầu từng việc (đoạn trùng chỉ tính một lần)
        const k = typeof e.budget_tasks === 'number' ? e.budget_tasks : e.limits ? Object.keys(e.limits).length : null;
        const tokens = typeof e.total_tokens === 'number' ? e.total_tokens : null;
        this.metric({ budgetTokens: tokens });
        const text = `Chia ngân sách ngữ cảnh${k !== null ? ` cho ${k} việc` : ''}${tokens !== null ? ` · tổng ${tokens} token` : ''}`;
        this.act('orchestrator', 'planning_board', text, 'plan_card', 'whiteboard');
        this.scene('orchestrator', text, 50);
        return;
      }
      case 'planning_generation':
      case 'planning_repair':
      case 'plan_anchoring':
      case 'decomposition': {
        // thẻ việc trên bảng: 1 thẻ nháp khi bắt đầu; khi máy chủ báo số việc con thật thì đúng bằng số đó (tối đa 6 chỗ)
        const n = count(e.task_count, e.tasks);
        this.cards = n !== null ? Math.min(6, n) : Math.max(1, this.cards);
        if (n !== null) this.metric({ tasks: n });
        const text = e.stage === 'planning_repair' ? 'Sửa kế hoạch' : e.stage === 'decomposition' && n !== null ? `Phân rã thành ${n} việc con` : 'Lập kế hoạch chia việc';
        this.act('orchestrator', 'planning_board', text, 'plan_card', 'whiteboard');
        if (e.stage === 'planning_repair') {
          this.say('orchestrator', 'reviewer', 'plan', 'Mình đang tinh chỉnh lại bản kế hoạch để bảo đảm phủ kín mọi ý khách hỏi.');
        }
        this.scene('orchestrator', text, 40, { whiteboardCards: this.cards, cabinetOpen: false });
        return this.step('plan', 'Lập kế hoạch', 'orchestrator');
      }
      case 'plan_fallback': {
        const n = count(e.task_count, e.tasks);
        if (n !== null) {
          this.cards = Math.min(6, n);
          this.metric({ tasks: n });
        }
        const text = `Dùng kế hoạch dự phòng${n !== null ? ` (${n} việc cốt lõi)` : ''}`;
        this.act('orchestrator', 'planning_board', text, 'plan_card', 'whiteboard');
        this.say(
          'orchestrator',
          'all',
          'plan',
          `Yêu cầu khá đồ sộ nên mình tự động kích hoạt kế hoạch dự phòng${n !== null ? ` gồm ${n} đầu việc cốt lõi` : ''} để bảo đảm trả lời đầy đủ không bị gián đoạn.`,
          'Dự phòng an toàn',
        );
        this.scene('orchestrator', text, 46, { whiteboardCards: this.cards, cabinetOpen: false });
        return this.step('plan', 'Lập kế hoạch', 'orchestrator');
      }
      case 'plan_verification':
        this.wake('reviewer');
        this.act('reviewer', 'reviewing_paper', 'Kiểm tra kế hoạch có bỏ sót yêu cầu không', 'approved_sheet', 'board_review');
        this.say('reviewer', 'orchestrator', 'review', 'Để mình ra bảng trắng soát nhanh kế hoạch xem có bỏ sót ý nào của khách hàng không nhé.');
        this.scene('reviewer', 'Reviewer kiểm tra kế hoạch', 45);
        return this.step('verify', 'Kiểm tra kế hoạch', 'reviewer');
      case 'planning_rejected':
        this.act('reviewer', 'reviewing_paper', 'Kế hoạch chưa qua bước kiểm tra');
        this.say('reviewer', 'orchestrator', 'error', 'Bảng kế hoạch hiện chưa đạt tiêu chuẩn kiểm định nên cần dừng lại để điều chỉnh.');
        this.headline('Kế hoạch chưa qua bước kiểm tra của CAP1');
        return this.markLast('fail');
      case 'parallel_execution': {
        // máy chủ báo sẽ chạy cùng lúc các việc không phụ thuộc nhau (Đợt 7): chỉ khi đó văn phòng mới vẽ nhiều người làm cùng lúc
        const first = e.waves?.[0] ?? [];
        if (Array.isArray(e.waves)) this.metric({ waves: e.waves.length, parallel: Math.max(0, ...e.waves.map(w => w.length)) });
        const text = first.length > 1 ? `Giao cùng lúc ${first.length} việc: ${first.join(', ')}` : 'Giao việc lần lượt theo thứ tự phụ thuộc';
        this.act('orchestrator', 'planning_board', text, 'plan_card', 'whiteboard');
        if (first.length > 1) {
          this.say(
            'orchestrator',
            'all',
            'plan',
            `Các đầu việc ${first.join(', ')} độc lập nhau — mọi người triển khai song song cùng lúc nhé!`,
            `Song song ${first.length}`,
          );
        }
        return this.headline(text);
      }
      case 'task_started': {
        const who = characterFor(domain);
        if (taskId && domain) this.taskDomain.set(taskId, domain);
        // kế hoạch đã qua kiểm tra (máy chủ bắt đầu giao việc): Reviewer rời bảng về bàn
        if (this.spots.get('reviewer') === 'board_review') this.act('reviewer', 'completed', 'Kế hoạch đã qua kiểm tra', 'none');
        this.wake(who);
        const text = `${label(domain)} làm việc ${taskId ?? ''}`.trim();
        const action: RobotAction = who === 'analyst' ? 'drafting_analysis' : who === 'rag' ? 'thinking' : 'working_computer';
        const goal = typeof e.task_goal === 'string' && e.task_goal.trim() ? e.task_goal.trim() : '';
        if (taskId && goal) this.taskGoal.set(taskId, shortGoal(goal));
        this.act(who, action, text, 'specialist_doc', who === 'analyst' ? 'easel' : undefined);
        this.say(
          'orchestrator',
          who,
          'work',
          goal
            ? `Mình giao đầu việc ${taskId ?? ''} cho ${label(domain)}: “${goal}”. Bạn rà kỹ căn cứ rồi báo lại nhé!`
            : `Mình giao đầu việc ${taskId ?? ''} cho ${label(domain)} phụ trách xử lý nhé!`,
          taskId,
          goal ? { icon: 'task', title: `Đầu việc ${taskId ?? ''}`.trim(), subtitle: goal } : undefined,
        );
        this.say(
          who,
          'orchestrator',
          'work',
          specialistAckFor(who, taskId),
        );
        this.scene(who, text, 55, { analystChartActive: who === 'analyst', cabinetOpen: false });
        this.give('orchestrator', who, 'specialist_doc', `Giao việc cho ${label(domain)}`, 'dispatch', `Giao ${taskId ?? 'việc'} · ${label(domain)}`);
        return this.step(`task-${taskId}`, label(domain), who);
      }
      case 'task_completed': {
        const d = domain ?? (taskId ? this.taskDomain.get(taskId) : undefined);
        const who = characterFor(d);
        const ok = e.result?.status !== 'NO_EVIDENCE';
        const goalHint = taskId ? this.taskGoal.get(taskId) : undefined;
        const domainName = label(d).replace(/^Chuyên gia\s+/i, '');
        if (ok) {
          if (!this.completedOkDomains.includes(domainName)) this.completedOkDomains.push(domainName);
        } else {
          if (!this.missingEvidenceDomains.includes(domainName)) this.missingEvidenceDomains.push(domainName);
        }
        this.act(who, 'completed', ok ? `Xong việc ${taskId ?? ''}`.trim() : `Không tìm thấy bằng chứng cho ${taskId ?? 'việc này'}`, 'none');
        this.wake('integrator');
        const subject = goalHint ? `phần “${goalHint}”` : `đầu việc ${taskId ?? ''}`.trim();
        this.say(
          who,
          'integrator',
          ok ? 'work' : 'error',
          ok
            ? `Mình đã hoàn thành ${subject}, chuyển kết quả kèm trích dẫn nguồn sang bàn bạn tổng hợp nhé!`
            : `Mình đã rà kỹ tài liệu cho ${subject} nhưng không thấy căn cứ trực tiếp — gửi ghi chú thiếu nguồn sang bạn nhé.`,
          ok ? `Xong ${taskId ?? ''}`.trim() : 'Thiếu nguồn',
        );
        this.scene(who, `${label(d)} gửi kết quả cho Integrator`, 70);
        this.give(who, 'integrator', who === 'analyst' ? 'analytics_sheet' : 'specialist_doc', 'Mang kết quả về Integrator',
          ok ? 'result' : 'fail', ok ? `Kết quả ${taskId ?? ''}`.trim() : `${taskId ?? 'Việc'}: thiếu bằng chứng`);
        return this.markStep(`task-${taskId}`, ok ? 'done' : 'fail');
      }
      case 'agent_tool': {
        // chuyên gia trả lời chưa đủ nên tự tìm thêm tài liệu (máy chủ báo sau khi tìm, kèm số đoạn mới)
        const d = domain ?? (taskId ? this.taskDomain.get(taskId) : undefined);
        const who = characterFor(d);
        this.wake(who);
        if (e.tool !== 'search') {
          const t = `${label(d)} dùng công cụ ${e.tool ?? ''}`.trim();
          this.act(who, 'working_computer', t, undefined, this.spots.get(who));
          this.say(who, 'orchestrator', 'tool', `Mình đang dùng công cụ ${e.tool ?? 'hỗ trợ'} để kiểm tra kỹ hơn phần dữ liệu này.`);
          return this.headline(t);
        }
        const n = typeof e.added === 'number' ? e.added : null;
        const text = n === 0 ? `${label(d)} tìm thêm tài liệu: không có đoạn mới` : `${label(d)} tìm thêm tài liệu${n !== null ? `: ${n} đoạn mới` : ''}`;
        if (n === 0) {
          this.say(who, 'rag', 'tool', 'Mình vừa rà thêm trong kho tài liệu nhưng chưa thấy đoạn mới nào bổ sung.');
        } else {
          this.say('rag', who, 'tool', `Mình vừa tìm bổ sung được${n !== null ? ` ${n} đoạn mới` : ' thêm tài liệu'} cho ${label(d)}, gửi ngay qua bàn bạn nhé!`, n !== null ? `+${n} đoạn` : 'Tìm thêm');
        }
        if (this.tempo === 'easy') {
          // Dễ theo dõi: chuyên gia tự đi tới tủ hồ sơ
          this.act(who, 'cabinet_rag', text, 'rag_folder', 'cabinet');
          this.scene(who, text, 60, { cabinetOpen: true });
        } else {
          // Thời gian thật (bước ngắn): RAG mở tủ, gói tài liệu bay tới chuyên gia; không có đoạn mới thì không gửi gói
          this.wake('rag');
          this.act('rag', n === 0 ? 'thinking' : 'cabinet_rag', n === 0 ? `Không có đoạn mới cho ${label(d)}` : `Tìm thêm cho ${label(d)}`, n === 0 ? undefined : 'rag_folder', n === 0 ? undefined : 'cabinet');
          this.scene(who, text, 60, { cabinetOpen: n !== 0 });
          if (n !== 0) this.give('rag', who, 'rag_folder', `Mang thêm tài liệu cho ${label(d)}`, 'rag', n !== null ? `Tìm thêm · ${n} đoạn` : 'Tìm thêm tài liệu');
        }
        return;
      }
      case 'agent_tool_result': {
        const d = domain ?? (taskId ? this.taskDomain.get(taskId) : undefined);
        const who = characterFor(d);
        const fixed = e.before === 'NO_EVIDENCE' && e.after && e.after !== 'NO_EVIDENCE';
        const text = fixed ? `${label(d)} trả lời được sau khi tìm thêm` : `${label(d)} làm lại: vẫn ${e.after === 'NO_EVIDENCE' ? 'chưa có bằng chứng' : (e.after ?? '').toLowerCase()}`;
        this.act(who, 'working_computer', text, 'specialist_doc');  // về bàn viết lại
        this.say(
          who,
          'orchestrator',
          'tool',
          fixed
            ? 'Tuyệt rồi, sau khi tìm bổ sung mình đã có đủ căn cứ để hoàn thiện phần này!'
            : 'Mình đã rà bổ sung nhưng tài liệu vẫn chưa đề cập rõ phần này, mình sẽ ghi chú minh bạch.',
        );
        return this.headline(text);
      }
      case 'review_revision': {
        // Reviewer trả bài (số ý chưa có căn cứ), người viết làm lại; câu đơn giản: người viết là chuyên gia của T1
        const n = typeof e.unsupported === 'number' ? e.unsupported : Array.isArray(e.unsupported) ? e.unsupported.length : null;
        const d = taskId ? this.taskDomain.get(taskId) : undefined;
        const writer: AgentId = d ? characterFor(d) : 'integrator';
        this.wake('reviewer');
        this.wake(writer);
        this.act('reviewer', 'reviewing_paper', n ? `Trả bài: ${n} ý chưa có căn cứ` : 'Trả bài', 'approved_sheet');
        this.metric({ revisions: this.state.metrics.revisions + 1 });
        this.say(
          'reviewer',
          writer,
          'revise',
          `Mình trả lại bản thảo${n ? ` (${n} ý chưa đủ căn cứ trong tài liệu)` : ''}, nhờ ${writer === 'integrator' ? 'Integrator' : label(d)} hiệu chỉnh lại cho chặt chẽ nhé.`,
          'Trả sửa QC',
        );
        this.give('reviewer', writer, 'approved_sheet', 'Trả bài để viết lại', 'revise', n ? `Trả bài · ${n} ý thiếu căn cứ` : 'Trả bài');
        this.act(writer, writer === 'integrator' ? 'integrating' : 'working_computer', 'Viết lại theo góp ý của Reviewer', writer === 'integrator' ? 'final_report' : 'specialist_doc');
        this.scene(writer, `Reviewer trả bài${n ? ` (${n} ý)` : ''}, ${writer === 'integrator' ? 'Integrator' : label(d)} viết lại`, 92);
        return this.step('revise', 'Viết lại theo góp ý', writer);
      }
      case 'synthesis_started': {
        if (e.revision) {  // viết lại sau khi Reviewer trả bài: vẫn là bước "Viết lại theo góp ý"
          this.act('integrator', 'integrating', 'Viết lại theo góp ý của Reviewer', 'final_report');
          this.say('integrator', 'reviewer', 'revise', 'Cảm ơn Reviewer đã chỉ rõ, mình đang hiệu chỉnh lại bản thảo cho bám sát tài liệu ngay.');
          return this.step('revise', 'Viết lại theo góp ý', 'integrator');
        }
        this.synthesizing = true;
        this.wake('integrator');
        this.act('integrator', 'integrating', 'Tổng hợp câu trả lời', 'final_report');
        const okList = this.completedOkDomains.join(', ');
        const missList = this.missingEvidenceDomains.join(', ');
        const synthMsg = okList && missList
          ? `Mình đã nhận đủ kết quả từ ${okList} và ghi nhận phần ${missList} chưa có trong tài liệu — đang hợp nhất rành mạch cả hai ý để trả lời khách.`
          : okList
            ? `Mình đã gom đủ kết quả từ ${okList}, đang hợp nhất mạch lạc kèm nguồn trích dẫn để trình bày câu trả lời hoàn chỉnh.`
            : missList
              ? `Các phòng (${missList}) đều xác nhận tài liệu chưa đề cập tới nội dung này — mình đang biên soạn phản hồi trung thực cho khách.`
              : 'Mình đã gom đủ phần việc từ các phòng, đang tổng hợp và trình bày câu trả lời hoàn chỉnh đây.';
        this.say('integrator', 'all', 'work', synthMsg);
        this.scene('integrator', 'Integrator tổng hợp câu trả lời', 80);
        return this.step('write', 'Tổng hợp câu trả lời', 'integrator');
      }
      case 'review_started':
        this.wake('reviewer');
        this.act('reviewer', 'reviewing_paper', 'Đối chiếu từng ý với tài liệu');
        this.say('reviewer', 'integrator', 'review', 'Chuyển bản thảo qua đây để mình đối chiếu từng số liệu và nhận định với tài liệu gốc trước khi gửi khách.');
        this.scene('reviewer', 'Reviewer đối chiếu từng ý với tài liệu', 90);
        return this.step('review', 'Đối chiếu câu trả lời', 'reviewer');
      case 'review_finished': {
        const n = Array.isArray(e.unsupported) ? e.unsupported.length : typeof e.unsupported === 'number' ? e.unsupported : 0;
        const ok = e.review_status === 'ok';
        const checked = typeof e.checked === 'number' ? e.checked : null;
        this.metric({ checked, unsupported: ok ? n : null });
        this.act('reviewer', 'completed', !ok ? 'Chưa đối chiếu được' : n ? `${n} ý chưa thấy trong tài liệu` : 'Các ý đều có trong tài liệu');
        // V5: ở câu đơn giản (chưa có synthesis_started), Reviewer gửi xác nhận về đúng chuyên gia T1 thay vì ngược thứ tự sang Integrator
        const simpleDomain = !this.synthesizing && taskId ? this.taskDomain.get(taskId) : undefined;
        const reviewTarget: AgentId = simpleDomain && simpleDomain !== 'general' ? characterFor(simpleDomain) : 'integrator';
        this.say(
          'reviewer',
          reviewTarget,
          ok && n === 0 ? 'done' : 'review',
          !ok
            ? 'Bước đối chiếu tự động chưa hoàn tất trọn vẹn, mình gửi lại kèm ghi chú để kiểm tra thêm.'
            : n === 0
              ? `Đã đối chiếu xong${checked !== null ? ` ${checked} ý` : ''} — mọi con số và nhận định đều khớp tài liệu gốc, đóng dấu đạt chuẩn!`
              : `Mình vừa soát xong: có ${n} ý chưa thấy nguyên văn trong tài liệu, cần chỉnh lại hoặc ghi chú minh bạch cho khách.`,
          ok && n === 0 ? 'Đạt QC' : n > 0 ? `${n} ý cần chú ý` : undefined,
          ok
            ? {
                icon: n === 0 ? 'qc_ok' : 'qc_warn',
                title: n === 0 ? 'Đạt kiểm định chất lượng (QC)' : `Cần lưu ý ${n} ý thiếu căn cứ`,
                subtitle: checked !== null ? `Đã đối chiếu ${checked} ý với tài liệu gốc` : undefined,
              }
            : undefined,
        );
        this.c.setLiveScene({ effects: { qcApproved: ok && n === 0 } });
        if (ok && n === 0) this.give('reviewer', reviewTarget, 'approved_sheet', 'Chuyển bài đã đạt kiểm định', 'approve', checked !== null ? `Đạt · ${checked} ý có căn cứ` : 'Đạt kiểm định');
        return this.markStep('review', ok ? 'done' : 'fail');
      }
      case 'run_finished':
        this.finalStatus = typeof e.status === 'string' ? e.status : null;
        return this.finish(false);
      case 'run_failed':
        return this.finish(true);
      default:
        return;
    }
  }

  /** Không có sự kiện mới một lúc: người đang giữ việc chuyển sang "đang suy nghĩ / chờ mô hình", đứng yên tại chỗ.
   *  recorded = true khi xem lại: số giây là khoảng chờ thật đã lưu, không phải thời gian diễn. */
  waiting(sec: number, recorded = false): void {
    if (this.state.finished) return;
    const now = this.state.steps.filter(s => s.state === 'now');
    // mọi chuyên gia đang làm việc con (song song thì nhiều người) cùng báo chờ; không có việc con thì người giữ bước cuối
    const tasks = now.filter(s => s.key.startsWith('task-')).map(s => s.actor);
    const holders = tasks.length ? [...new Set(tasks)] : [now.length ? now[now.length - 1].actor : 'orchestrator' as AgentId];
    const lastStep = now.length ? now[now.length - 1] : undefined;
    const text = recorded ? `Lúc chạy thật chờ mô hình ${sec} giây` : `Đang chờ mô hình · ${sec} giây`;
    // giữ nguyên hành động đang làm (gõ máy, viết bảng): chỉ đổi dòng chữ, robot không dừng tay
    for (const who of holders) this.act(who, this.acts.get(who) ?? 'thinking', text, undefined, this.spots.get(who));
    const activeWorkLabel = holders.length > 1
      ? `${holders.map(h => label(h)).join(' & ')} đang song song phân tích tài liệu...`
      : workHintFor(holders[0], lastStep?.key);
    this.state = { ...this.state, waitingSec: sec, activeWorkLabel };
    this.onState(this.state);
  }

  /** Kết thúc lượt: Integrator bàn giao, các Agent khác về ngủ. */
  finish(failed: boolean): void {
    if (this.state.finished) return;
    if (failed) {
      this.act('orchestrator', 'idle', 'Lượt chạy không hoàn thành');
      this.say(
        'orchestrator',
        'user',
        'error',
        'Rất tiếc, lượt xử lý gặp sự cố giữa chừng nên chưa thể hoàn tất câu trả lời.',
        'Thất bại',
        { icon: 'qc_warn', title: 'Lượt xử lý gián đoạn' },
      );
      this.scene('orchestrator', 'Lượt chạy không hoàn thành', 100);
      this.markLast('fail');
    } else {
      this.wake('integrator');
      this.act('integrator', 'completed', 'Đã gửi câu trả lời', 'final_report');
      const st = this.finalStatus;
      if (st === 'NO_EVIDENCE') {
        this.say(
          'integrator',
          'user',
          'review',
          'Tài liệu hiện có chưa chứa thông tin cho câu hỏi này — mình đã phản hồi trung thực với người dùng để tránh suy đoán.',
          'Không đủ bằng chứng',
          { icon: 'qc_warn', title: 'Không đủ bằng chứng trong tài liệu' },
        );
      } else if (st === 'PARTIAL') {
        this.say(
          'integrator',
          'user',
          'done',
          'Mình đã gửi câu trả lời cho người dùng — trình bày rõ phần có căn cứ trong tài liệu và ghi chú minh bạch phần chưa có thông tin.',
          'Một phần',
          { icon: 'done', title: 'Đã gửi câu trả lời · Một phần' },
        );
      } else {
        this.say(
          'integrator',
          'user',
          'done',
          'Hoàn tất! Mình đã tổng hợp đầy đủ bằng chứng kèm nguồn trích dẫn và gửi câu trả lời tới người dùng rồi nhé!',
          'Đủ bằng chứng',
          { icon: 'done', title: 'Đã gửi câu trả lời hoàn chỉnh' },
        );
      }
      this.scene('integrator', 'Đã gửi câu trả lời', 100, { finalReportReady: true, cabinetOpen: false, analystChartActive: false });
      this.state.steps = this.state.steps.map(s => (s.state === 'now' ? { ...s, state: 'done' } : s));
    }
    const restAll = [...this.awake].filter(id => id !== (failed ? 'orchestrator' : 'integrator'));
    // câu trả lời đã ra: bỏ các lần trao còn xếp hàng, robot đang đi thì đi nhanh cho xong rồi mới về ngủ
    this.handQueue.clear();
    restAll.filter(id => this.walking.has(id)).forEach(id => this.sleepAfterWalk.add(id));
    const rest = restAll.filter(id => !this.walking.has(id));
    if (rest.length) this.c.putAgentsToSleep(rest);
    rest.forEach(id => this.awake.delete(id));
    this.c.settle?.();
    this.state = { ...this.state, finished: true, failed, awake: [...this.awake], activeWorkers: [], waitingSec: null, activeWorkLabel: null };
    this.onState(this.state);
  }

  private acts = new Map<AgentId, RobotAction>();

  private say(
    from: AgentId,
    to: AgentId | 'all' | 'user',
    kind: OfficeChatKind,
    text: string,
    badge?: string,
    attachment?: OfficeChatAttachment,
  ): void {
    const clean = text.trim();
    if (!clean) return;
    const prev = this.state.chatFeed[this.state.chatFeed.length - 1];
    if (prev && prev.from === from && prev.to === to && prev.text === clean) return;
    const phase: OfficeChatPhase =
      to === 'user' || kind === 'done'
        ? 'done'
        : kind === 'review' || kind === 'revise'
          ? 'review'
          : kind === 'plan'
            ? 'intake'
            : 'work';
    const mood: OfficeChatMood =
      kind === 'error' || kind === 'revise' || attachment?.icon === 'qc_warn'
        ? 'warn'
        : kind === 'done' || attachment?.icon === 'qc_ok'
          ? 'happy'
          : 'focus';
    const msg: OfficeChatMessage = {
      id: `m${++this.msgSeq}`,
      from,
      to,
      kind,
      phase,
      mood,
      text: clean,
      ...(badge ? { badge } : {}),
      ...(attachment ? { attachment } : {}),
    };
    this.state = { ...this.state, chatFeed: [...this.state.chatFeed, msg] };
  }

  private metric(m: Partial<LiveMetrics>): void {
    this.state = { ...this.state, metrics: { ...this.state.metrics, ...m } };
  }

  /** Trao hồ sơ: chế độ Dễ theo dõi thì robot tự đi tới đưa (xếp hàng nếu đang bận); Thời gian thật thì gói bay theo đường nối.
   *  Mọi lần trao đều ghi vào đồ thị luồng của lượt (kể cả khi dựng lại phần đã qua). */
  private give(from: AgentId, to: AgentId, item: CarryItemKind, text: string, kind: FlowKind = 'dispatch', flowLabel?: string): void {
    if (from === to) return;
    const flow = { kind, label: flowLabel ?? text };
    const edges = [...this.state.edges];
    const i = edges.findIndex(x => x.from === from && x.to === to && x.kind === kind);
    if (i >= 0) edges[i] = { ...edges[i], count: edges[i].count + 1, label: flow.label };
    else edges.push({ from, to, kind, count: 1, label: flow.label });
    this.state = { ...this.state, edges, metrics: { ...this.state.metrics, flows: this.state.metrics.flows + 1 } };
    this.onState(this.state);
    if (this.quiet) return;
    if (this.tempo !== 'easy' || !this.c.walkAndHandoff) return this.c.setLiveScene({ dispatch: { from, toList: [to] }, flow });
    const q = this.handQueue.get(from) ?? [];
    q.push({ to, item, label: text });
    this.handQueue.set(from, q);
    if (!this.walking.has(from)) this.nextHand(from);
  }

  private nextHand(from: AgentId): void {
    const job = this.handQueue.get(from)?.shift();
    if (!job) {
      this.walking.delete(from);
      if (this.sleepAfterWalk.delete(from)) { this.pendingAct.delete(from); this.c.putAgentsToSleep([from]); return; }
      const p = this.pendingAct.get(from);
      this.pendingAct.delete(from);
      if (p) this.c.setAgentAction(from, ...p);
      return;
    }
    this.walking.add(from);
    this.c.walkAndHandoff!(from, job.to, job.item, job.label, () => this.nextHand(from));
  }

  private act(id: AgentId, action: RobotAction, text?: string, carry?: CarryItemKind, spot?: Parameters<LiveController['setAgentAction']>[4]): void {
    this.spots.set(id, spot);
    this.acts.set(id, action);
    if (this.walking.has(id)) { this.pendingAct.set(id, [action, text, carry, spot]); return; }  // đang đi trao: làm sau khi trao xong
    this.c.setAgentAction(id, action, text, carry, spot);
  }

  private wake(id: AgentId): void {
    if (this.awake.has(id)) return;
    this.awake.add(id);
    this.participants.add(id);
    this.c.wakeAgents([id]);
    this.state = { ...this.state, awake: [...this.awake], metrics: { ...this.state.metrics, agents: this.participants.size } };
  }

  private scene(lead: AgentId, text: string, pct: number, effects?: Parameters<LiveController['setLiveScene']>[0]['effects'],
    dispatch?: { from: AgentId; toList: AgentId[] }): void {
    this.c.setLiveScene({
      lead, effects, dispatch,
      wall: { tierLabel: this.tier, requestTitle: this.state.question.slice(0, 90), stepText: text, progressPct: pct },
    });
    this.headline(text);
  }

  // mọi thay đổi nhìn thấy được (dòng trạng thái, bước) đều kết thúc trạng thái chờ mô hình;
  // sự kiện văn phòng không diễn thì không xóa
  private headline(text: string): void {
    this.state = { ...this.state, headline: text, waitingSec: null };
    this.onState(this.state);
  }

  private step(key: string, text: string, actor: AgentId): void {
    const steps = this.state.steps;
    const last = steps[steps.length - 1];
    if (last?.key === key) return;
    // bước trước (trừ việc con, có sự kiện xong riêng) coi như xong khi sang bước mới
    const prev = steps.map(s => (s.state === 'now' && !s.key.startsWith('task-') ? { ...s, state: 'done' as const } : s));
    const next = prev.some(s => s.key === key)
      ? prev.map(s => (s.key === key ? { ...s, state: 'now' as const } : s))  // quay lại bước cũ (vd. tìm tài liệu lần 2)
      : [...prev, { key, label: text, actor, state: 'now' as const }];
    const activeWorkers = [...new Set(next.filter(s => s.state === 'now').map(s => s.actor))];
    this.state = { ...this.state, steps: next, activeWorkers, waitingSec: null, activeWorkLabel: workHintFor(actor, key) };
    this.onState(this.state);
  }

  private markStep(key: string, st: LiveStepState): void {
    const next = this.state.steps.map(s => (s.key === key ? { ...s, state: st } : s));
    const activeWorkers = [...new Set(next.filter(s => s.state === 'now').map(s => s.actor))];
    this.state = { ...this.state, steps: next, activeWorkers, waitingSec: null };
    this.onState(this.state);
  }

  private markLast(st: LiveStepState): void {
    const steps = [...this.state.steps];
    if (steps.length) steps[steps.length - 1] = { ...steps[steps.length - 1], state: st };
    const activeWorkers = [...new Set(steps.filter(s => s.state === 'now').map(s => s.actor))];
    this.state = { ...this.state, steps, activeWorkers };
    this.onState(this.state);
  }
}

/** Sự kiện đã lưu của một lượt chạy (run.events) → dãy để xem lại, kèm độ trễ thật giữa các mốc (ms). */
export function replayPlan(events: Array<LiveEvent & { ts?: string }>, maxGapMs = 6000): Array<{ delayMs: number; realGapMs: number; event: LiveEvent }> {
  let prev: number | null = null;
  return events.filter(e => e.stage).map((e) => {
    const t = e.ts ? Date.parse(e.ts) : NaN;
    const real = prev !== null && Number.isFinite(t) ? Math.max(0, t - prev) : 0;
    if (Number.isFinite(t)) prev = t;
    return { delayMs: Math.min(maxGapMs, real), realGapMs: real, event: e };
  });
}

/** Nhịp diễn (Đợt 3): mỗi bước hiện tối thiểu minStepMs; sự kiện dồn (>= mergeAt chờ) thì áp cùng lúc để robot
 *  không chạy theo từng bước ngắn. Không bỏ sự kiện nào nên trạng thái cuối giống hệt khi áp trực tiếp.
 *  Không có sự kiện quá idleMs (chỉ khi trackIdle) thì báo "chờ mô hình" kèm số giây đo bằng đồng hồ thật. */
type PaceItem = { event: LiveEvent } | { waitSec: number };
export interface PacerClock { now(): number; setTimeout(fn: () => void, ms: number): unknown; clearTimeout(id: unknown): void }
const realClock: PacerClock = {
  now: () => Date.now(),
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

export class LivePacer {
  private queue: PaceItem[] = [];
  private timer: unknown = null;
  private idleTimer: unknown = null;
  private lastApply = -Infinity;
  private lastEvent: number;
  private shownSec = -1;
  private d: Pick<LiveDirector, 'handle' | 'waiting' | 'getState'>;
  private opts: { minStepMs: number; idleMs: number; mergeAt: number; trackIdle: boolean; clock: PacerClock };

  constructor(d: Pick<LiveDirector, 'handle' | 'waiting' | 'getState'>, opts: Partial<LivePacer['opts']> = {}) {
    this.d = d;
    this.opts = { minStepMs: 700, idleMs: 1500, mergeAt: 3, trackIdle: true, clock: realClock, ...opts };
    this.lastEvent = this.opts.clock.now();
    this.armIdle();
  }

  /** Thay đổi tốc độ xem lại: nhịp tối thiểu chia theo tốc độ. */
  setMinStep(ms: number): void { this.opts.minStepMs = ms; }

  push(event: LiveEvent): void {
    this.queue.push({ event });
    this.lastEvent = this.opts.clock.now();
    this.schedule();
  }

  /** Xem lại: khoảng chờ mô hình đã lưu (giây thật), hiện theo đúng thứ tự giữa hai sự kiện. */
  pushWait(sec: number): void {
    this.queue.push({ waitSec: sec });
    this.schedule();
  }

  /** Áp ngay mọi sự kiện còn chờ (vd. lượt đã kết thúc khi mở văn phòng giữa chừng). */
  flush(): void {
    this.cancel();
    this.apply(this.queue.splice(0));
  }

  dispose(): void {
    this.cancel();
    if (this.idleTimer !== null) this.opts.clock.clearTimeout(this.idleTimer);
    this.idleTimer = null;
    this.queue = [];
  }

  private cancel(): void {
    if (this.timer !== null) this.opts.clock.clearTimeout(this.timer);
    this.timer = null;
  }

  private schedule(): void {
    if (this.timer !== null) return;
    const wait = Math.max(0, this.lastApply + this.opts.minStepMs - this.opts.clock.now());
    this.timer = this.opts.clock.setTimeout(() => this.drain(), wait);
  }

  private drain(): void {
    this.timer = null;
    if (!this.queue.length) return;
    // dồn nhiều thì gộp: áp hết, khoảng chờ cũ bỏ qua vì đã có bước mới
    const batch = this.queue.length >= this.opts.mergeAt ? this.queue.splice(0) : [this.queue.shift()!];
    this.apply(batch.length > 1 ? batch.filter(i => 'event' in i) : batch);
    this.lastApply = this.opts.clock.now();
    if (this.queue.length) this.schedule();
  }

  private apply(items: PaceItem[]): void {
    for (const it of items) {
      if ('event' in it) {
        this.d.handle(it.event);
        // đo độ trễ khi kiểm thử: trang kiểm thử đặt window.__officeTrace = [] thì ghi thời điểm áp từng sự kiện
        const tr = (globalThis as { __officeTrace?: unknown[] }).__officeTrace;
        if (Array.isArray(tr) && it.event.stage) tr.push({ stage: it.event.stage, task: it.event.task_id ?? it.event.result?.task_id, t: Date.now(), rx: Date.parse((it.event as { ts?: string }).ts ?? '') });
      }
      else this.d.waiting(it.waitSec, true);
    }
  }

  private armIdle(): void {
    if (!this.opts.trackIdle) return;
    this.idleTimer = this.opts.clock.setTimeout(() => {
      this.idleTimer = null;
      if (this.d.getState().finished) return;
      const idle = this.opts.clock.now() - Math.max(this.lastEvent, this.lastApply);
      const sec = Math.floor(idle / 1000);
      // kiểm tra dày (250 ms) để báo đúng lúc 1,5 giây; chỉ báo lại khi số giây đổi, robot không bị gọi lại liên tục
      if (!this.queue.length && idle >= this.opts.idleMs && (sec !== this.shownSec || this.d.getState().waitingSec === null)) {
        this.shownSec = sec;
        this.d.waiting(sec);
      }
      this.armIdle();
    }, 250);
  }
}
