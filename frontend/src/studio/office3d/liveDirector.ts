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
}

export type LiveTempo = 'realtime' | 'easy';

export interface LiveController {
  resetToSleep(): void;
  /** robot tự đi tới đưa hồ sơ; onArrive gọi khi đã trao xong */
  walkAndHandoff?(from: AgentId, to: AgentId, item: CarryItemKind, label?: string, onArrive?: () => void): void;
  wakeAgents(ids: AgentId[]): void;
  putAgentsToSleep(ids: AgentId[]): void;
  setAgentAction(id: AgentId, action: RobotAction, text?: string, carry?: CarryItemKind, spot?: 'whiteboard' | 'board_review' | 'reception' | 'cabinet' | 'easel'): void;
  setLiveScene(opts: {
    lead?: AgentId | null;
    effects?: Partial<{ requestArrived: boolean; cabinetOpen: boolean; whiteboardCards: number; analystChartActive: boolean; qcApproved: boolean; finalReportReady: boolean }>;
    dispatch?: { from: AgentId; toList: AgentId[] };
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
  finished: boolean;
  failed: boolean;
  /** số giây đang chờ mô hình (không có sự kiện mới); null khi đang có việc diễn ra */
  waitingSec: number | null;
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

export class LiveDirector {
  private c: LiveController;
  private onState: (s: LiveState) => void;
  private state: LiveState = { question: '', headline: '', steps: [], awake: [], finished: false, failed: false, waitingSec: null };
  private awake = new Set<AgentId>();
  private cards = 0;
  private answering = false;
  private noDocs = false;              // knowledge_source_policy báo không có tài liệu: RAG ngủ
  private route: string | null = null; // SIMPLE_PROJECT_QUESTION | COMPLEX_PROJECT_REQUEST
  private synthesizing = false;
  private taskDomain = new Map<string, string>();
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
    this.answering = false;
    this.noDocs = false;
    this.route = null;
    this.synthesizing = false;
    this.taskDomain.clear();
    this.spots.clear();
    this.acts.clear();
    this.walking.clear();
    this.handQueue.clear();
    this.pendingAct.clear();
    this.sleepAfterWalk.clear();
    this.state = { question, headline: 'Orchestrator nhận câu hỏi', steps: [], awake: [], finished: false, failed: false, waitingSec: null };
    this.c.resetToSleep();
    this.wake('orchestrator');
    this.act('orchestrator', 'receiving', 'Nhận câu hỏi', 'request_brief', 'reception');
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
        const text = simple ? 'Câu đơn giản: tra tài liệu rồi trả lời' : 'Câu nhiều ý: lập kế hoạch chia việc';
        this.act('orchestrator', 'thinking', text);
        return this.headline(text);
      }
      case 'knowledge_source_policy': {
        // bước chọn nguồn tri thức (23/11): Orchestrator quyết định lấy tri thức từ tài liệu, kiến thức chung hay cả hai
        this.noDocs = e.has_documents === false;
        const text = e.document_bound ? 'Nguồn: chỉ tài liệu' : e.has_documents ? 'Nguồn: tài liệu, thiếu thì kiến thức chung' : 'Nguồn: kiến thức chung (không có tài liệu)';
        this.act('orchestrator', 'thinking', text);
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
          this.scene(who, text, 85, { cabinetOpen: false });
          return this.step('write', 'Viết câu trả lời', who);
        }
        if (!general) return;
        this.wake(who);
        const text = `${label(domain)} trả lời bằng ${e.source === 'general' ? 'kiến thức chung' : 'tài liệu + kiến thức chung'}`;
        this.act(who, 'working_computer', text, 'specialist_doc');
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
        if (e.selected_count === 0) {
          // tra rồi mà không có đoạn nào liên quan: không mở tủ, không gửi gói tài liệu
          this.act('rag', 'thinking', `Không có đoạn tài liệu liên quan${forWho}`);
          this.scene('rag', `RAG không thấy đoạn tài liệu liên quan${forWho}`, 30, { cabinetOpen: false });
          return this.step(key, 'Tìm tài liệu', 'rag');
        }
        // gói tài liệu bay tới người đang cần: chuyên gia của việc con, Orchestrator khi lập kế hoạch, người viết ở câu đơn giản
        const to: AgentId = e.stage === 'task_retrieval' ? characterFor(domain) : e.stage === 'planning_retrieval' ? 'orchestrator' : 'integrator';
        const n = typeof e.selected_count === 'number' ? ` (${e.selected_count} đoạn)` : '';
        this.act('rag', 'cabinet_rag', `Tìm đoạn tài liệu${forWho}${n}`, 'rag_folder', 'cabinet');
        this.scene('rag', `RAG Specialist tìm tài liệu${forWho}${n}`, 30, { cabinetOpen: true });
        this.give('rag', to, 'rag_folder', `Mang tài liệu tới ${to === 'orchestrator' ? 'Orchestrator' : to === 'integrator' ? 'người viết' : label(domain)}`);
        return this.step(key, 'Tìm tài liệu', 'rag');
      }
      case 'planning_generation':
      case 'planning_repair':
      case 'plan_anchoring':
      case 'decomposition':
      case 'normalization': {
        // thẻ việc trên bảng: 1 thẻ nháp khi bắt đầu; khi máy chủ báo số việc con thật thì đúng bằng số đó (tối đa 6 chỗ)
        this.cards = typeof e.task_count === 'number' ? Math.min(6, e.task_count) : Math.max(1, this.cards);
        const text = e.stage === 'planning_repair' ? 'Sửa kế hoạch' : 'Lập kế hoạch chia việc';
        this.act('orchestrator', 'planning_board', text, 'plan_card', 'whiteboard');
        this.scene('orchestrator', text, 40, { whiteboardCards: this.cards, cabinetOpen: false });
        return this.step('plan', 'Lập kế hoạch', 'orchestrator');
      }
      case 'plan_verification':
        this.wake('reviewer');
        this.act('reviewer', 'reviewing_paper', 'Kiểm tra kế hoạch có bỏ sót yêu cầu không', 'approved_sheet', 'board_review');
        this.scene('reviewer', 'Reviewer kiểm tra kế hoạch', 45);
        return this.step('verify', 'Kiểm tra kế hoạch', 'reviewer');
      case 'planning_rejected':
        this.act('reviewer', 'reviewing_paper', 'Kế hoạch chưa qua bước kiểm tra');
        this.headline('Kế hoạch chưa qua bước kiểm tra của CAP1');
        return this.markLast('fail');
      case 'parallel_execution': {
        // máy chủ báo sẽ chạy cùng lúc các việc không phụ thuộc nhau (Đợt 7): chỉ khi đó văn phòng mới vẽ nhiều người làm cùng lúc
        const first = e.waves?.[0] ?? [];
        const text = first.length > 1 ? `Giao cùng lúc ${first.length} việc: ${first.join(', ')}` : 'Giao việc lần lượt theo thứ tự phụ thuộc';
        this.act('orchestrator', 'planning_board', text, 'plan_card', 'whiteboard');
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
        this.act(who, action, text, 'specialist_doc', who === 'analyst' ? 'easel' : undefined);
        this.scene(who, text, 55, { analystChartActive: who === 'analyst', cabinetOpen: false });
        this.give('orchestrator', who, 'specialist_doc', `Giao việc cho ${label(domain)}`);
        return this.step(`task-${taskId}`, label(domain), who);
      }
      case 'task_completed': {
        const d = domain ?? (taskId ? this.taskDomain.get(taskId) : undefined);
        const who = characterFor(d);
        const ok = e.result?.status !== 'NO_EVIDENCE';
        this.act(who, 'completed', ok ? `Xong việc ${taskId ?? ''}`.trim() : `Không tìm thấy bằng chứng cho ${taskId ?? 'việc này'}`, 'none');
        this.wake('integrator');
        this.scene(who, `${label(d)} gửi kết quả cho Integrator`, 70);
        this.give(who, 'integrator', who === 'analyst' ? 'analytics_sheet' : 'specialist_doc', 'Mang kết quả về Integrator');
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
          return this.headline(t);
        }
        const n = typeof e.added === 'number' ? e.added : null;
        const text = n === 0 ? `${label(d)} tìm thêm tài liệu: không có đoạn mới` : `${label(d)} tìm thêm tài liệu${n !== null ? `: ${n} đoạn mới` : ''}`;
        if (this.tempo === 'easy') {
          // Dễ theo dõi: chuyên gia tự đi tới tủ hồ sơ
          this.act(who, 'cabinet_rag', text, 'rag_folder', 'cabinet');
          this.scene(who, text, 60, { cabinetOpen: true });
        } else {
          // Thời gian thật (bước ngắn): RAG mở tủ, gói tài liệu bay tới chuyên gia; không có đoạn mới thì không gửi gói
          this.wake('rag');
          this.act('rag', n === 0 ? 'thinking' : 'cabinet_rag', n === 0 ? `Không có đoạn mới cho ${label(d)}` : `Tìm thêm cho ${label(d)}`, n === 0 ? undefined : 'rag_folder', n === 0 ? undefined : 'cabinet');
          this.scene(who, text, 60, { cabinetOpen: n !== 0 });
          if (n !== 0) this.give('rag', who, 'rag_folder', `Mang thêm tài liệu cho ${label(d)}`);
        }
        return;
      }
      case 'agent_tool_result': {
        const d = domain ?? (taskId ? this.taskDomain.get(taskId) : undefined);
        const who = characterFor(d);
        const fixed = e.before === 'NO_EVIDENCE' && e.after && e.after !== 'NO_EVIDENCE';
        const text = fixed ? `${label(d)} trả lời được sau khi tìm thêm` : `${label(d)} làm lại: vẫn ${e.after === 'NO_EVIDENCE' ? 'chưa có bằng chứng' : (e.after ?? '').toLowerCase()}`;
        this.act(who, 'working_computer', text, 'specialist_doc');  // về bàn viết lại
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
        this.give('reviewer', writer, 'approved_sheet', 'Trả bài để viết lại');
        this.act(writer, writer === 'integrator' ? 'integrating' : 'working_computer', 'Viết lại theo góp ý của Reviewer', writer === 'integrator' ? 'final_report' : 'specialist_doc');
        this.scene(writer, `Reviewer trả bài${n ? ` (${n} ý)` : ''}, ${writer === 'integrator' ? 'Integrator' : label(d)} viết lại`, 92);
        return this.step('revise', 'Viết lại theo góp ý', writer);
      }
      case 'synthesis_started':
        if (e.revision) {  // viết lại sau khi Reviewer trả bài: vẫn là bước "Viết lại theo góp ý"
          this.act('integrator', 'integrating', 'Viết lại theo góp ý của Reviewer', 'final_report');
          return this.step('revise', 'Viết lại theo góp ý', 'integrator');
        }
        this.synthesizing = true;
        this.wake('integrator');
        this.act('integrator', 'integrating', 'Tổng hợp câu trả lời', 'final_report');
        this.scene('integrator', 'Integrator tổng hợp câu trả lời', 80);
        return this.step('write', 'Tổng hợp câu trả lời', 'integrator');
      case 'review_started':
        this.wake('reviewer');
        this.act('reviewer', 'reviewing_paper', 'Đối chiếu từng ý với tài liệu');
        this.scene('reviewer', 'Reviewer đối chiếu từng ý với tài liệu', 90);
        return this.step('review', 'Đối chiếu câu trả lời', 'reviewer');
      case 'review_finished': {
        const n = Array.isArray(e.unsupported) ? e.unsupported.length : typeof e.unsupported === 'number' ? e.unsupported : 0;
        const ok = e.review_status === 'ok';
        this.act('reviewer', 'completed', !ok ? 'Chưa đối chiếu được' : n ? `${n} ý chưa thấy trong tài liệu` : 'Các ý đều có trong tài liệu');
        this.c.setLiveScene({ effects: { qcApproved: ok && n === 0 } });
        return this.markStep('review', ok ? 'done' : 'fail');
      }
      case 'run_finished':
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
    const text = recorded ? `Lúc chạy thật chờ mô hình ${sec} giây` : `Đang chờ mô hình · ${sec} giây`;
    // giữ nguyên hành động đang làm (gõ máy, viết bảng): chỉ đổi dòng chữ, robot không dừng tay
    for (const who of holders) this.act(who, this.acts.get(who) ?? 'thinking', text, undefined, this.spots.get(who));
    this.state = { ...this.state, waitingSec: sec };
    this.onState(this.state);
  }

  /** Kết thúc lượt: Integrator bàn giao, các Agent khác về ngủ. */
  finish(failed: boolean): void {
    if (this.state.finished) return;
    if (failed) {
      this.act('orchestrator', 'idle', 'Lượt chạy không hoàn thành');
      this.scene('orchestrator', 'Lượt chạy không hoàn thành', 100);
      this.markLast('fail');
    } else {
      this.wake('integrator');
      this.act('integrator', 'completed', 'Đã gửi câu trả lời', 'final_report');
      this.scene('integrator', 'Đã gửi câu trả lời', 100, { finalReportReady: true, cabinetOpen: false, analystChartActive: false });
      this.state.steps = this.state.steps.map(s => (s.state === 'now' ? { ...s, state: 'done' } : s));
    }
    const restAll = [...this.awake].filter(id => id !== (failed ? 'orchestrator' : 'integrator'));
    // robot đang đi trao hồ sơ: trao xong rồi mới về ngủ (không cắt ngang giữa đường)
    restAll.filter(id => this.walking.has(id)).forEach(id => this.sleepAfterWalk.add(id));
    const rest = restAll.filter(id => !this.walking.has(id));
    if (rest.length) this.c.putAgentsToSleep(rest);
    rest.forEach(id => this.awake.delete(id));
    this.state = { ...this.state, finished: true, failed, awake: [...this.awake], waitingSec: null };
    this.onState(this.state);
  }

  private acts = new Map<AgentId, RobotAction>();

  /** Trao hồ sơ: chế độ Dễ theo dõi thì robot tự đi tới đưa (xếp hàng nếu đang bận); Thời gian thật thì gói bay. */
  private give(from: AgentId, to: AgentId, item: CarryItemKind, text: string): void {
    if (from === to || this.quiet) return;
    if (this.tempo !== 'easy' || !this.c.walkAndHandoff) return this.c.setLiveScene({ dispatch: { from, toList: [to] } });
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
    this.c.wakeAgents([id]);
    this.state = { ...this.state, awake: [...this.awake] };
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
    this.state = { ...this.state, steps: next, waitingSec: null };
    this.onState(this.state);
  }

  private markStep(key: string, st: LiveStepState): void {
    this.state = { ...this.state, steps: this.state.steps.map(s => (s.key === key ? { ...s, state: st } : s)), waitingSec: null };
    this.onState(this.state);
  }

  private markLast(st: LiveStepState): void {
    const steps = [...this.state.steps];
    if (steps.length) steps[steps.length - 1] = { ...steps[steps.length - 1], state: st };
    this.state = { ...this.state, steps };
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
