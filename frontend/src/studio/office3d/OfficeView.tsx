import './office3d.css';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Building2, Compass, MessageSquareText, Moon, Play, RotateCcw, Users } from 'lucide-react';
import type { DocumentInfo } from '../types';
import { streamOfficeWorkSession, type WorkSessionEvent } from '../services/api';
import { AgentOrchestratorCanvas } from './AgentOrchestratorCanvas';
import { AgentGuidePanel } from './AgentGuidePanel';
import { OfficeChatFeed, OfficeLiveBubbles } from './OfficeChatFeed';
import { LiveDirector, LivePacer, replayPlan, type FlowEdge, type LiveState, type LiveTempo, type OfficeChatMessage } from './liveDirector';
import type { FlowLogItem } from './scene/flowGraph';

// nhịp diễn: Trực tiếp mặc định "Thời gian thật", Xem lại mặc định "Dễ theo dõi"; nhớ lựa chọn của người xem
const TEMPO_KEY = 'c27.officeTempo';
function readTempo(kind: 'live' | 'replay'): LiveTempo {
  try {
    const v = JSON.parse(localStorage.getItem(TEMPO_KEY) || '{}')[kind];
    if (v === 'realtime' || v === 'easy') return v;
  } catch { /* trình duyệt chặn lưu trữ: dùng mặc định */ }
  return kind === 'live' ? 'realtime' : 'easy';
}
function writeTempo(kind: 'live' | 'replay', t: LiveTempo) {
  try { localStorage.setItem(TEMPO_KEY, JSON.stringify({ ...JSON.parse(localStorage.getItem(TEMPO_KEY) || '{}'), [kind]: t })); } catch { /* không lưu được */ }
}
import { getLive, subscribeLive } from './liveBus';
import type { OfficeSource } from './OfficePanel';
import type {
  AgentId,
  CameraPresetId,
  Studio3DController,
  StudioTelemetrySnapshot,
  WeatherMode,
} from './types';

const WEATHER_BG_CLASS: Record<WeatherMode, string> = {
  sunny: 'bg-[#e6dfd3]',
  sunset: 'bg-[#d9b39a]',
  night: 'bg-[#0b1326]',
  storm: 'bg-[#1a2636]',
};

type QualityMode = 'auto' | 'high' | 'medium' | 'low';
const QUALITY_LABEL = { high: 'Cao', medium: 'Vừa', low: 'Thấp' } as const;

const WEATHER_OPTIONS: { id: WeatherMode; label: string }[] = [
  { id: 'sunny', label: 'Nắng đẹp' },
  { id: 'sunset', label: 'Hoàng hôn' },
  { id: 'night', label: 'Đêm sao' },
  { id: 'storm', label: 'Mưa giông' },
];

/** Logo thời tiết SVG riêng có màu sắc nhận diện rõ ràng cho từng chế độ bầu trời 3D. */
function WeatherLogo({ mode }: { mode: WeatherMode }) {
  if (mode === 'sunny') {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" className="o3d-wlogo">
        <circle cx="12" cy="12" r="5" fill="#f59e0b" />
        <g stroke="#f59e0b" strokeWidth="2" strokeLinecap="round">
          <line x1="12" y1="2.5" x2="12" y2="5" />
          <line x1="12" y1="19" x2="12" y2="21.5" />
          <line x1="2.5" y1="12" x2="5" y2="12" />
          <line x1="19" y1="12" x2="21.5" y2="12" />
          <line x1="5.3" y1="5.3" x2="7.1" y2="7.1" />
          <line x1="16.9" y1="16.9" x2="18.7" y2="18.7" />
          <line x1="18.7" y1="5.3" x2="16.9" y2="7.1" />
          <line x1="7.1" y1="16.9" x2="5.3" y2="18.7" />
        </g>
      </svg>
    );
  }
  if (mode === 'sunset') {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" className="o3d-wlogo">
        <defs>
          <linearGradient id="o3d-sunset-g" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#fb923c" />
            <stop offset="100%" stopColor="#ec4899" />
          </linearGradient>
        </defs>
        <path d="M5 15a7 7 0 0 1 14 0z" fill="url(#o3d-sunset-g)" />
        <line x1="3" y1="15.5" x2="21" y2="15.5" stroke="#ea580c" strokeWidth="2" strokeLinecap="round" />
        <line x1="6" y1="19" x2="18" y2="19" stroke="#f97316" strokeWidth="1.8" strokeLinecap="round" opacity="0.7" />
        <line x1="12" y1="3.5" x2="12" y2="5.8" stroke="#fb923c" strokeWidth="1.9" strokeLinecap="round" />
        <line x1="5.6" y1="6.4" x2="7.2" y2="8" stroke="#fb923c" strokeWidth="1.8" strokeLinecap="round" />
        <line x1="18.4" y1="6.4" x2="16.8" y2="8" stroke="#fb923c" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (mode === 'night') {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" className="o3d-wlogo">
        <path d="M15.8 14.9A6.6 6.6 0 0 1 9.1 8.2a6.6 6.6 0 0 1 .5-2.5A7.2 7.2 0 1 0 18.3 14.4a6.6 6.6 0 0 1-2.5.5z" fill="#6366f1" />
        <circle cx="17.5" cy="6.2" r="1.2" fill="#facc15" />
        <circle cx="14.5" cy="4.2" r="0.8" fill="#fde047" />
        <circle cx="19.5" cy="9.5" r="0.8" fill="#c7d2fe" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" className="o3d-wlogo">
      <path d="M7.5 14.5h9.2a3.3 3.3 0 0 0 .4-6.58A5 5 0 0 0 7.4 6.6a3.8 3.8 0 0 0 .1 7.9z" fill="#64748b" />
      <path d="M12.5 13.5l-2 4h2.2l-1.2 3.5 3.6-4.7h-2.2l1.2-2.8z" fill="#f59e0b" />
      <line x1="7.5" y1="16.8" x2="6.6" y2="19.4" stroke="#38bdf8" strokeWidth="1.7" strokeLinecap="round" />
      <line x1="16.8" y1="16.8" x2="15.9" y2="19.4" stroke="#38bdf8" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export default function OfficeView({
  source,
  onLiveState,
  docs = [],
  workspaceName,
  domainPack,
}: {
  source?: OfficeSource;
  onLiveState?: (s: LiveState) => void;
  docs?: DocumentInfo[];
  workspaceName?: string;
  domainPack?: string;
} = {}) {
  const controllerRef = useRef<Studio3DController | null>(null);
  // Đợt 6: có `source` là chế độ trực tiếp/xem lại theo sự kiện thật; không có là kịch bản minh họa
  const isLive = !!source;
  const [engineReady, setEngineReady] = useState(false);
  const [liveState, setLiveStateRaw] = useState<LiveState | null>(null);
  // bảng văn phòng trong ô chat cần dòng trạng thái để hiện lúc thu gọn
  const onLiveRef = useRef(onLiveState);
  onLiveRef.current = onLiveState;
  const setLiveState = useCallback((st: LiveState) => { setLiveStateRaw(st); onLiveRef.current?.(st); }, []);
  const [replayKey, setReplayKey] = useState(0);
  const speedRef = useRef(1);
  const [tempo, setTempoState] = useState<LiveTempo>(() => readTempo(source?.kind ?? 'live'));
  const tempoRef = useRef(tempo);
  const directorRef = useRef<LiveDirector | null>(null);
  const pacerRef = useRef<LivePacer | null>(null);
  // Thời gian thật: không giữ tối thiểu mỗi bước; Dễ theo dõi: mỗi bước ít nhất ~0,7 giây (chia theo tốc độ xem lại)
  const stepMs = () => (tempoRef.current === 'realtime' ? 0 : 700 / speedRef.current);
  useEffect(() => {  // đổi Trực tiếp ↔ Xem lại: dùng lựa chọn đã nhớ của chế độ đó
    if (!source) return;
    const t = readTempo(source.kind);
    tempoRef.current = t;
    setTempoState(t);
  }, [source?.kind]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [telemetry, setTelemetry] = useState<StudioTelemetrySnapshot | null>(null);
  const [, setFlowLogs] = useState<FlowLogItem[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<AgentId | null>(null);
  // bảng chọn Agent đóng sẵn để không che cảnh; bấm một Agent (trong cảnh hoặc bảng chọn) chỉ hiện thẻ của Agent đó
  const [rosterOpen, setRosterOpen] = useState(false);
  // Góc nhìn chính trên trang Văn phòng Agent độc lập: Trong văn phòng <-> Ra ngoài trường ĐH Duy Tân 360°
  const [viewScope, setViewScope] = useState<'inside' | 'campus'>('inside');
  // V6: Bố cục thống nhất — màn rộng (>= 900px) đặt Nhóm Chat dạng Floating Glass Card cạnh 3D (chỉ ở chế độ Trực tiếp/Xem lại);
  // khung hẹp (< 900px, cạnh ô Chat) dùng Segmented Switcher 1 khung toàn chiều cao!
  const pageRef = useRef<HTMLDivElement | null>(null);
  const [isNarrow, setIsNarrow] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [narrowTab, setNarrowTab] = useState<'3d' | 'chat'>('3d');
  const userToggledChatRef = useRef(false);

  useEffect(() => {
    const el = pageRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const sync = (w: number) => {
      const narrow = w < 900;
      setIsNarrow(narrow);
      if (!narrow && !userToggledChatRef.current) setChatOpen(true);
    };
    sync(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect && rect.width > 0) sync(rect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const handleToggleChat = useCallback(() => {
    if (isNarrow) {
      setNarrowTab((t) => (t === 'chat' ? '3d' : 'chat'));
      return;
    }
    userToggledChatRef.current = true;
    setChatOpen((v) => !v);
  }, [isNarrow]);

  const handleSelectAgent = useCallback((id: AgentId | null) => {
    setSelectedAgentId(id);
    if (id) setRosterOpen(false);
  }, []);
  const handleGuideSelect = useCallback((id: AgentId) => {
    setSelectedAgentId(id);
    setRosterOpen(false);
    setViewScope('inside');
    if (isNarrow) setNarrowTab('3d');
    controllerRef.current?.setCameraPreset(id);
  }, [isNarrow]);
  const [speedMultiplier, setSpeedMultiplier] = useState(1);
  const [showLabels] = useState(true);
  const [weather, setWeather] = useState<WeatherMode>('sunny');

  const [quality, setQuality] = useState<{ mode: QualityMode; level: 'high' | 'medium' | 'low' }>({ mode: 'auto', level: 'high' });
  // mức Tự động có thể tự hạ: đọc lại mỗi 2 giây để nhãn đúng
  useEffect(() => {
    const t = window.setInterval(() => { const q = controllerRef.current?.getQuality(); if (q) setQuality(prev => prev.mode === q.mode && prev.level === q.level ? prev : q); }, 2000);
    return () => window.clearInterval(t);
  }, []);
  const handleSetQuality = useCallback((mode: QualityMode) => {
    controllerRef.current?.setQualityMode(mode);
    const q = controllerRef.current?.getQuality();
    if (q) setQuality(q);
  }, []);

  const handleEngineReady = useCallback((controller: Studio3DController) => {
    controllerRef.current = controller;
    setEngineReady(true);
    controller.setShowFlowHistory?.(false);
    const q = controller.getQuality?.();
    if (q) setQuality(q);
    // Trang Văn phòng Agent độc lập: không chạy kịch bản minh họa ảo, giữ đội Agent gọn gàng đúng vị trí
    if (!isLive) controller.resetToSleep();
  }, [isLive]);

  useEffect(() => {
    const ctrl = controllerRef.current;
    if (!engineReady || !ctrl || !source) return;
    const director = new LiveDirector(ctrl, (st) => setLiveState({ ...st }));
    directorRef.current = director;
    director.setTempo(tempoRef.current);
    ctrl.setLiveTempo(tempoRef.current);
    if (source.kind === 'replay') {
      // xem lại: diễn theo khoảng cách thời gian thật giữa các mốc (chặn khoảng quá dài), chia theo tốc độ đang chọn;
      // khoảng chờ mô hình thật (>= 1,5 giây) hiện đúng số giây đã lưu
      director.start(source.question, 'Xem lại');
      const pacer = new LivePacer(director, { trackIdle: false, minStepMs: stepMs() });
      pacerRef.current = pacer;
      const plan = replayPlan(source.events as never);
      let i = 0;
      // tua: dựng ngay phần trước bước được chọn rồi diễn tiếp từ bước đó
      const seek = Math.min(source.seek ?? 0, plan.length);
      director.catchUp(plan.slice(0, seek).map(p => p.event));
      i = seek;
      let timer = 0;
      const next = () => {
        if (i >= plan.length) { pacer.push({ stage: 'run_finished' }); return; }
        const { delayMs, realGapMs, event } = plan[i++];
        if (realGapMs >= 1500) pacer.pushWait(Math.round(realGapMs / 1000));
        timer = window.setTimeout(() => { pacer.setMinStep(stepMs()); pacer.push(event); next(); }, delayMs / speedRef.current);
      };
      next();
      return () => { window.clearTimeout(timer); pacer.dispose(); };
    }
    // trực tiếp: dựng lại phần đã diễn ra (mở văn phòng giữa chừng) rồi theo dõi tiếp
    // nhịp: sự kiện mới đi qua hàng đợi (tối thiểu ~700 ms mỗi bước, dồn thì gộp; im quá 1,5 giây thì báo chờ mô hình)
    let sessionId = -1;
    let pacer: LivePacer | null = null;
    const load = () => {
      const live = getLive();
      if (!live) return;
      sessionId = live.id;
      pacer?.dispose();
      director.start(live.question);
      director.catchUp(live.events);  // phần đã qua: dựng ngay, không diễn lại từng bước
      if (live.ended) director.finish(live.failed);
      pacer = new LivePacer(director, { minStepMs: stepMs() });
      pacerRef.current = pacer;
    };
    load();
    const unsub = subscribeLive((live, event) => {
      if (live.id !== sessionId) return load();  // người dùng gửi câu hỏi mới
      if (event) pacer?.push(event);
      else if (live.ended) { pacer?.flush(); director.finish(live.failed); }
    });
    return () => { unsub(); pacer?.dispose(); };
  }, [engineReady, source, replayKey]);

  const handleSetSpeed = useCallback((mult: number) => {
    setSpeedMultiplier(mult);
    speedRef.current = mult;
    controllerRef.current?.setSpeed(mult);
  }, []);

  const handleToggleTempo = useCallback(() => {
    const t: LiveTempo = tempoRef.current === 'realtime' ? 'easy' : 'realtime';
    tempoRef.current = t;
    setTempoState(t);
    if (source) writeTempo(source.kind, t);
    directorRef.current?.setTempo(t);
    pacerRef.current?.setMinStep(stepMs());
    controllerRef.current?.setLiveTempo(t);
  }, [source]);  // eslint-disable-line react-hooks/exhaustive-deps

  const handleCycleSpeed = useCallback(() => {
    const next = speedMultiplier === 1 ? 2 : speedMultiplier === 2 ? 4 : 1;
    handleSetSpeed(next);
  }, [speedMultiplier, handleSetSpeed]);

  const handleSetCameraPreset = useCallback((preset: CameraPresetId) => {
    controllerRef.current?.setCameraPreset(preset);
  }, []);

  const handleSwitchScope = useCallback((scope: 'inside' | 'campus') => {
    setViewScope(scope);
    if (scope === 'campus') {
      setSelectedAgentId(null);
      setRosterOpen(false);
    }
    handleSetCameraPreset(scope === 'inside' ? 'overview' : 'city_exterior');
  }, [handleSetCameraPreset]);

  const handleToggleScope = useCallback(() => {
    handleSwitchScope(viewScope === 'inside' ? 'campus' : 'inside');
  }, [viewScope, handleSwitchScope]);

  const handleSetWeather = useCallback((mode: WeatherMode) => {
    setWeather(mode);
    controllerRef.current?.setWeather(mode);
  }, []);

  const handleCycleWeather = useCallback(() => {
    const idx = WEATHER_OPTIONS.findIndex((o) => o.id === weather);
    const next = WEATHER_OPTIONS[(idx + 1) % WEATHER_OPTIONS.length];
    handleSetWeather(next.id);
  }, [weather, handleSetWeather]);

  const handleReplay = useCallback(() => {
    if (source) setReplayKey((k) => k + 1);
  }, [source]);

  // lượt thật: các bước, số đo và đồ thị luồng chiếu lên TV & cảnh 3D
  useEffect(() => {
    if (!engineReady || !liveState) return;
    controllerRef.current?.setWallSteps(liveState.steps.map((st) => ({ label: st.label, state: st.state })));
  }, [engineReady, liveState?.steps]);

  useEffect(() => {
    if (!engineReady || !liveState) return;
    controllerRef.current?.setWallMetrics(liveState.metrics);
  }, [engineReady, liveState?.metrics]);

  useEffect(() => {
    if (!engineReady || !liveState) return;
    controllerRef.current?.syncFlowEdges(liveState.edges, liveState.finished);
  }, [engineReady, liveState?.edges, liveState?.finished]);

  // V10: đồng bộ 1:1 danh sách Agent đang thực sự làm việc -> tắt ngay luồng nối của Agent đã xong việc!
  useEffect(() => {
    if (!engineReady || !liveState) return;
    controllerRef.current?.syncActiveWorkers?.(liveState.activeWorkers, liveState.finished);
  }, [engineReady, liveState?.activeWorkers, liveState?.finished]);

  useEffect(() => {
    controllerRef.current?.setSpeed(speedMultiplier);
  }, [speedMultiplier]);

  // ---- Phiên làm việc tự động THẬT ở trang Văn phòng Agent độc lập (!isLive) ----
  // Mặc định các Agent ngủ yên tại bàn. Bấm nút "Làm việc" -> gọi /api/studio/office/work-session (LLM + RAG thật),
  // các Agent tự thức dậy, đứng dậy làm việc & trao đổi với nhau kèm luồng nối 3D, đoạn chat mờ nổi và khung chat đầy đủ.
  const [wsActive, setWsActive] = useState(false);
  const [wsRunning, setWsRunning] = useState(false);
  const [wsFailed, setWsFailed] = useState(false);
  const [wsTopic, setWsTopic] = useState('');
  const [wsTeam, setWsTeam] = useState<AgentId[]>([]);
  const [wsMessages, setWsMessages] = useState<OfficeChatMessage[]>([]);
  const [wsActiveWorkers, setWsActiveWorkers] = useState<AgentId[]>([]);
  const [wsLeadActor, setWsLeadActor] = useState<AgentId | null>(null);
  const [wsWorkLabel, setWsWorkLabel] = useState<string | null>(null);
  const [wsChatOpen, setWsChatOpen] = useState(false);
  const wsAbortRef = useRef<AbortController | null>(null);
  const wsSeqRef = useRef(0);
  const wsHistoryTopicsRef = useRef<string[]>([]);

  useEffect(() => () => { wsAbortRef.current?.abort(); }, []);

  const docIds = useMemo(() => docs.map((d) => String(d.id)), [docs]);

  const handleStartWorkSession = useCallback(async () => {
    wsAbortRef.current?.abort();
    const ac = new AbortController();
    wsAbortRef.current = ac;

    setRosterOpen(false);
    setSelectedAgentId(null);
    setViewScope('inside');
    setWsActive(true);
    setWsRunning(true);
    setWsFailed(false);
    setWsTopic('');
    setWsTeam(['orchestrator']);
    setWsMessages([]);
    setWsChatOpen(false); // Mặc định hiện đoạn chat mờ nổi trên sân khấu 3D; bấm vào hoặc bấm "Hội thoại" để mở khung chat đầy đủ
    setWsLeadActor('orchestrator');
    setWsActiveWorkers(['orchestrator']);
    setWsWorkLabel(
      docs.length > 0
        ? `Đang đọc ${docs.length} tài liệu trong "${workspaceName || 'không gian hiện tại'}" để khởi tạo phiên làm việc…`
        : 'Orchestrator đang tiếp nhận yêu cầu và đánh thức đội ngũ…',
    );

    const ctrl = controllerRef.current;
    ctrl?.resetToSleep();
    ctrl?.setShowFlowHistory?.(false);
    ctrl?.setCameraPreset('overview');
    ctrl?.wakeAgents(['orchestrator']);
    ctrl?.setAgentAction('orchestrator', 'receiving', 'Đang khởi tạo phiên làm việc mới…', 'request_brief', 'reception');
    ctrl?.setWallSteps([
      { label: 'Phân rã việc', state: 'now' },
      { label: 'Chuyên môn & RAG', state: 'todo' },
      { label: 'Kiểm định QC', state: 'todo' },
      { label: 'Tổng hợp bàn giao', state: 'todo' },
    ]);
    ctrl?.setLiveScene({
      lead: 'orchestrator',
      effects: { requestArrived: true },
      wall: {
        tierLabel: 'Phiên làm việc đa tác tử',
        requestTitle: docs.length > 0 ? `Kho ${workspaceName || 'hiện tại'} (${docs.length} tài liệu)` : 'Đang khởi tạo đề bài…',
        stepText: 'Orchestrator đang tiếp nhận yêu cầu',
        progressPct: 10,
      },
    });
    ctrl?.syncActiveWorkers?.(['orchestrator'], false);

    const pushMsg = (m: OfficeChatMessage) => setWsMessages((prev) => [...prev, m]);
    let sessionTopic = '';
    const sessionEdges: FlowEdge[] = [];
    const pushEdge = (e: FlowEdge) => {
      sessionEdges.push(e);
      controllerRef.current?.syncFlowEdges([...sessionEdges], false);
    };

    try {
      await streamOfficeWorkSession(
        {
          source_ids: docIds.length > 0 ? docIds : null,
          domain_pack: domainPack || 'general',
          exclude_topics: wsHistoryTopicsRef.current.slice(-6),
        },
        (ev: WorkSessionEvent) => {
          const c = controllerRef.current;
          if (ev.type === 'session_start') {
            sessionTopic = ev.topic;
            setWsTopic(ev.topic);
            wsHistoryTopicsRef.current = [...wsHistoryTopicsRef.current.slice(-8), ev.topic];
            const teamIds = ev.team as AgentId[];
            setWsTeam(teamIds);
            c?.wakeAgents(['orchestrator']);
            c?.setAgentAction('orchestrator', 'planning_board', 'Đang phân rã công việc cho các phòng ban…', 'plan_card', 'whiteboard');
            c?.setLiveScene({
              lead: 'orchestrator',
              effects: { requestArrived: true, whiteboardCards: 2 },
              wall: {
                tierLabel: ev.has_docs ? 'Phiên làm việc · Kho tài liệu thật' : 'Phiên làm việc đa tác tử',
                requestTitle: ev.topic,
                stepText: 'Đang phân rã công việc T1 & T2',
                progressPct: 18,
              },
            });
          } else if (ev.type === 'agent_thinking') {
            const aid = ev.agent_id as AgentId;
            const targets = (ev.targets ?? []) as AgentId[];
            setWsLeadActor(aid);
            setWsWorkLabel(ev.label);
            c?.wakeAgents([aid, ...targets]);

            if (aid === 'orchestrator') {
              c?.setAgentAction('orchestrator', 'planning_board', 'Đang phân công đầu việc…', 'plan_card', 'whiteboard');
              targets.forEach((t) => pushEdge({ from: 'orchestrator', to: t, kind: 'dispatch', count: 1, label: 'Giao đầu việc' }));
              c?.setLiveScene({
                lead: 'orchestrator',
                effects: { requestArrived: true, whiteboardCards: Math.max(2, targets.length) },
                dispatch: targets.length > 0 ? { from: 'orchestrator', toList: targets } : undefined,
                flow: { kind: 'dispatch', label: 'Giao đầu việc' },
                wall: {
                  tierLabel: 'Phiên làm việc đa tác tử',
                  requestTitle: sessionTopic || 'Đang điều phối',
                  stepText: ev.label,
                  progressPct: 24,
                },
              });
              c?.syncActiveWorkers?.(['orchestrator', ...targets], false);
              setWsActiveWorkers(['orchestrator', ...targets]);
            } else if (aid === 'rag') {
              c?.setAgentAction('rag', 'cabinet_rag', 'Đang rút đoạn tài liệu & lọc trùng…', 'rag_folder', 'cabinet');
              targets.forEach((t) => pushEdge({ from: 'rag', to: t, kind: 'rag', count: 1, label: 'Truyền tài liệu RAG' }));
              c?.setWallSteps([
                { label: 'Phân rã việc', state: 'done' },
                { label: 'Chuyên môn & RAG', state: 'now' },
                { label: 'Kiểm định QC', state: 'todo' },
                { label: 'Tổng hợp bàn giao', state: 'todo' },
              ]);
              c?.setLiveScene({
                lead: 'rag',
                effects: { cabinetOpen: true },
                dispatch: targets.length > 0 ? { from: 'rag', toList: targets } : undefined,
                flow: { kind: 'rag', label: 'Truyền đoạn RAG' },
                wall: {
                  tierLabel: 'Phiên làm việc đa tác tử',
                  requestTitle: sessionTopic || 'Truy xuất tài liệu',
                  stepText: ev.label,
                  progressPct: 38,
                },
              });
              c?.syncActiveWorkers?.(['rag', ...targets], false);
              setWsActiveWorkers(['rag', ...targets]);
            } else if (aid === 'reviewer') {
              c?.setAgentAction('reviewer', 'reviewing_paper', 'Đang kiểm định chéo kết quả…', 'approved_sheet');
              pushEdge({ from: 'reviewer', to: 'integrator', kind: 'approve', count: 1, label: 'Kiểm định & bàn giao' });
              c?.setWallSteps([
                { label: 'Phân rã việc', state: 'done' },
                { label: 'Chuyên môn & RAG', state: 'done' },
                { label: 'Kiểm định QC', state: 'now' },
                { label: 'Tổng hợp bàn giao', state: 'todo' },
              ]);
              c?.setLiveScene({
                lead: 'reviewer',
                effects: { qcApproved: true },
                dispatch: { from: 'reviewer', toList: ['integrator'] },
                flow: { kind: 'approve', label: 'Kiểm định & chuyển tổng hợp' },
                wall: {
                  tierLabel: 'Phiên làm việc đa tác tử',
                  requestTitle: sessionTopic || 'Kiểm định chéo',
                  stepText: ev.label,
                  progressPct: 76,
                },
              });
              c?.syncActiveWorkers?.(['reviewer', 'integrator'], false);
              setWsActiveWorkers(['reviewer', 'integrator']);
            } else if (aid === 'integrator') {
              c?.setAgentAction('integrator', 'integrating', 'Đang tổng hợp báo cáo hoàn chỉnh…', 'final_report');
              c?.setWallSteps([
                { label: 'Phân rã việc', state: 'done' },
                { label: 'Chuyên môn & RAG', state: 'done' },
                { label: 'Kiểm định QC', state: 'done' },
                { label: 'Tổng hợp bàn giao', state: 'now' },
              ]);
              c?.setLiveScene({
                lead: 'integrator',
                effects: { finalReportReady: true },
                wall: {
                  tierLabel: 'Phiên làm việc đa tác tử',
                  requestTitle: sessionTopic || 'Tổng hợp báo cáo',
                  stepText: ev.label,
                  progressPct: 90,
                },
              });
              c?.syncActiveWorkers?.(['integrator'], false);
              setWsActiveWorkers(['integrator']);
            } else {
              // Chuyên gia phòng ban đang làm việc tại bàn & trao đổi trực tiếp với phòng ban còn lại
              const peer = targets.find((t) => t !== aid) ?? null;
              c?.setAgentAction(aid, 'working_computer', ev.label, 'specialist_doc');
              c?.setWallSteps([
                { label: 'Phân rã việc', state: 'done' },
                { label: 'Chuyên môn & RAG', state: 'now' },
                { label: 'Kiểm định QC', state: 'todo' },
                { label: 'Tổng hợp bàn giao', state: 'todo' },
              ]);
              if (peer) {
                const edgeKind = peer === 'reviewer' ? 'result' : 'dispatch';
                const edgeLabel = peer === 'reviewer' ? 'Gửi bản rà soát QC' : 'Trao đổi liên phòng ban';
                pushEdge({ from: aid, to: peer, kind: edgeKind, count: 1, label: edgeLabel });
                c?.setLiveScene({
                  lead: aid,
                  effects: { analystChartActive: true },
                  dispatch: { from: aid, toList: [peer] },
                  flow: { kind: edgeKind, label: edgeLabel },
                  wall: {
                    tierLabel: 'Phiên làm việc đa tác tử',
                    requestTitle: sessionTopic || 'Phối hợp chuyên gia',
                    stepText: ev.label,
                    progressPct: peer === 'reviewer' ? 62 : 48,
                  },
                });
                c?.syncActiveWorkers?.([aid, peer], false);
                setWsActiveWorkers([aid, peer]);
              } else {
                c?.syncActiveWorkers?.([aid], false);
                setWsActiveWorkers([aid]);
              }
            }
          } else if (ev.type === 'rag_evidence') {
            pushMsg({
              id: `ws-${++wsSeqRef.current}`,
              phase: 'work',
              kind: 'rag',
              mood: 'focus',
              from: 'rag',
              to: 'all',
              text: ev.text,
              badge: `${ev.count} đoạn RAG`,
              attachment: ev.count > 0 ? {
                icon: 'doc',
                title: ev.files.slice(0, 2).join(', ') + (ev.files.length > 2 ? ` +${ev.files.length - 2}` : ''),
                subtitle: `${ev.count} đoạn trích dẫn thật từ kho tài liệu`,
              } : undefined,
            });
            c?.setAgentAction('rag', 'idle', 'Đã chuyển tài liệu xong');
          } else if (ev.type === 'agent_message') {
            const aid = ev.agent_id as AgentId;
            const toVal: AgentId | 'all' | 'user' = ev.to === 'all' || ev.to === 'user' ? ev.to : (ev.to as AgentId);
            const moodVal = ev.kind === 'done' ? 'happy' : ev.kind === 'review' ? 'happy' : 'focus';
            pushMsg({
              id: `ws-${++wsSeqRef.current}`,
              phase: ev.phase,
              kind: ev.kind,
              mood: moodVal,
              from: aid,
              to: toVal,
              text: ev.text,
              badge: ev.badge,
            });
            // Bắn thêm tia chuyển kết quả thật sang người nhận khi tin nhắn vừa gửi xong
            if (toVal !== 'all' && toVal !== 'user' && toVal !== aid) {
              const flowKind = ev.kind === 'review' ? 'approve' : ev.kind === 'plan' ? 'dispatch' : 'result';
              c?.setLiveScene({
                lead: aid,
                dispatch: { from: aid, toList: [toVal] },
                flow: { kind: flowKind, label: ev.badge || 'Bàn giao trao đổi' },
              });
            }
            if (aid !== 'integrator') {
              c?.setAgentAction(aid, 'idle', 'Đã hoàn tất phần việc');
            }
          } else if (ev.type === 'session_done') {
            setWsRunning(false);
            setWsWorkLabel(null);
            setWsActiveWorkers([]);
            setWsLeadActor('integrator');
            c?.setWallSteps([
              { label: 'Phân rã việc', state: 'done' },
              { label: 'Chuyên môn & RAG', state: 'done' },
              { label: 'Kiểm định QC', state: 'done' },
              { label: 'Tổng hợp bàn giao', state: 'done' },
            ]);
            c?.setLiveScene({
              lead: 'integrator',
              effects: { finalReportReady: true },
              wall: {
                tierLabel: 'Hoàn tất phiên làm việc',
                requestTitle: sessionTopic || 'Bàn giao hoàn tất',
                stepText: 'Đội ngũ đã trao đổi & tổng hợp xong',
                progressPct: 100,
              },
            });
            c?.syncFlowEdges([...sessionEdges], true);
            c?.syncActiveWorkers?.([], true);
            c?.setAgentAction('integrator', 'completed', 'Đã hoàn tất bàn giao', 'final_report');
          } else if (ev.type === 'error') {
            setWsFailed(true);
            setWsRunning(false);
            setWsWorkLabel(null);
            setWsActiveWorkers([]);
            c?.syncFlowEdges([], true);
            c?.syncActiveWorkers?.([], true);
            pushMsg({
              id: `ws-err-${++wsSeqRef.current}`,
              phase: 'review',
              kind: 'error',
              mood: 'warn',
              from: 'orchestrator',
              to: 'user',
              text: ev.detail,
              badge: 'Lỗi mô hình',
            });
          }
        },
        ac.signal,
      );
    } catch (err: any) {
      if (err?.name === 'AbortError') return;
      setWsFailed(true);
      setWsRunning(false);
      setWsWorkLabel(null);
      setWsActiveWorkers([]);
      controllerRef.current?.syncFlowEdges([], true);
      controllerRef.current?.syncActiveWorkers?.([], true);
      pushMsg({
        id: `ws-err-${++wsSeqRef.current}`,
        phase: 'review',
        kind: 'error',
        mood: 'warn',
        from: 'orchestrator',
        to: 'user',
        text: err?.message || 'Không thể kết nối máy chủ AI.',
        badge: 'Gián đoạn',
      });
    }
  }, [docIds, docs.length, domainPack, workspaceName]);

  const handleSleepOffice = useCallback(() => {
    wsAbortRef.current?.abort();
    setWsRunning(false);
    setWsActive(false);
    setWsChatOpen(false);
    setWsMessages([]);
    setWsActiveWorkers([]);
    setWsWorkLabel(null);
    setWsLeadActor(null);
    controllerRef.current?.syncFlowEdges([], true);
    controllerRef.current?.syncActiveWorkers?.([], true);
    controllerRef.current?.resetToSleep();
    controllerRef.current?.setCameraPreset('overview');
  }, []);

  const hasInteractiveFeed = isLive || wsActive;
  const chatMessages = isLive ? (liveState?.chatFeed ?? []) : wsMessages;
  const chatFinished = isLive ? Boolean(liveState?.finished) : !wsRunning;
  const chatActiveWork = isLive ? (liveState?.activeWorkLabel ?? null) : wsWorkLabel;
  const chatQuestion = isLive ? liveState?.question : (wsActive ? wsTopic : undefined);

  const chatActiveAgents: AgentId[] = useMemo(() => {
    if (isLive) return liveState?.awake ?? [];
    return wsActive ? wsTeam : [];
  }, [isLive, liveState?.awake, wsActive, wsTeam]);

  const chatLeadActor: AgentId | null = useMemo(() => {
    if (isLive) {
      const activeStep = liveState?.steps.slice().reverse().find((s) => s.state === 'now');
      return activeStep?.actor ?? null;
    }
    return wsActive ? wsLeadActor : null;
  }, [isLive, liveState?.steps, wsActive, wsLeadActor]);

  const chatActiveWorkers: AgentId[] = useMemo(() => {
    if (chatFinished) return [];
    return isLive ? (liveState?.activeWorkers ?? []) : wsActiveWorkers;
  }, [chatFinished, isLive, liveState?.activeWorkers, wsActiveWorkers]);

  const feedOpen = isLive ? chatOpen : wsChatOpen;
  const toggleFeedOpen = useCallback(() => {
    if (isLive) {
      handleToggleChat();
    } else {
      setWsChatOpen((v) => !v);
    }
  }, [isLive, handleToggleChat]);

  const showSideChat = hasInteractiveFeed && !isNarrow && feedOpen;
  const showFullTabChat = hasInteractiveFeed && isNarrow && narrowTab === 'chat';
  const showLiveStack = hasInteractiveFeed && ((isNarrow && narrowTab === '3d') || (!isNarrow && !feedOpen));

  return (
    <div
      ref={pageRef}
      data-quality={quality.level}
      className={`office3d-page relative flex overflow-hidden text-stone-900 select-none transition-colors duration-700 ${WEATHER_BG_CLASS[weather]}${isLive ? ' is-live-office' : ''}${isNarrow ? ' is-narrow' : ''}${showSideChat ? ' has-side-chat' : ''}${showFullTabChat ? ' is-chat-tab' : ''}`}
    >
      {/* Thanh chuyển đổi thống nhất cho bảng hẹp */}
      {hasInteractiveFeed && isNarrow && (
        <div className="o3d-narrow-bar">
          <div className="o3d-segmented" role="tablist" aria-label="Chế độ xem Văn phòng Agent">
            <button
              type="button"
              role="tab"
              aria-selected={narrowTab === '3d'}
              className={narrowTab === '3d' ? 'is-active' : ''}
              onClick={() => setNarrowTab('3d')}
            >
              <Building2 size={14} />
              <span>Văn phòng 3D</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={narrowTab === 'chat'}
              className={narrowTab === 'chat' ? 'is-active' : ''}
              onClick={() => setNarrowTab('chat')}
            >
              <MessageSquareText size={14} />
              <span>Hội thoại</span>
              {chatMessages.length > 0 && <em className="o3d-seg-count">{chatMessages.length}</em>}
              {!chatFinished && narrowTab === '3d' && <i className="o3d-seg-ping" aria-hidden="true" />}
            </button>
          </div>
          {isLive && (
            <span className={`o3d-narrow-state ${liveState?.finished ? (liveState.failed ? 'is-fail' : 'is-done') : 'is-live'}`}>
              {liveState?.finished ? (liveState.failed ? 'Gián đoạn' : 'Đã xong') : 'Đang chạy'}
            </span>
          )}
        </div>
      )}

      <div className="o3d-workspace-body">
        <div className={`o3d-stage${showFullTabChat ? ' is-hidden-under-chat' : ''}`}>
          {/* Full-viewport Architectural 3D AI Office with Eilik Companion Robots */}
          <AgentOrchestratorCanvas
            showLabels={showLabels}
            selectedAgentId={selectedAgentId}
            onEngineReady={handleEngineReady}
            onTelemetry={setTelemetry}
            onSelectAgent={handleSelectAgent}
            onFlowLogsUpdated={setFlowLogs}
          />

          {/* Thanh trên gọn: ở trang độc lập chỉ hiện tên Văn phòng & công cụ gọn; ở chế độ Trực tiếp hiện trạng thái thật */}
          <header className="o3d-top">
            {!isNarrow && (
              <div className="o3d-status-pill">
                <span className="o3d-status-title">Văn phòng Agent</span>
                {isLive ? (
                  <>
                    <span className={`o3d-mode ${source!.kind === 'live' ? 'is-live' : 'is-replay'}`} title={source!.kind === 'live' ? 'Theo sự kiện thật của câu hỏi đang chạy' : 'Diễn lại theo mốc thời gian đã lưu'}>
                      {source!.kind === 'live' ? 'Trực tiếp' : 'Xem lại'}
                    </span>
                    <span className="o3d-headline" aria-live="polite" title={liveState?.question}>
                      {liveState?.waitingSec != null && !liveState.finished && liveState.activeWorkLabel
                        ? liveState.activeWorkLabel
                        : (liveState?.headline ?? (source!.kind === 'live' ? 'Chưa có câu hỏi nào đang chạy' : 'Đang dựng văn phòng…'))}
                    </span>
                    {liveState?.waitingSec != null && !liveState.finished && (
                      <span className="o3d-wait" aria-hidden="true" title="Đang phân tích và xử lý dữ liệu">
                        {liveState.waitingSec} giây
                      </span>
                    )}
                    {liveState?.finished && <span className={`o3d-done ${liveState.failed ? 'is-fail' : ''}`}>{liveState.failed ? 'Không hoàn thành' : 'Đã xong'}</span>}
                  </>
                ) : wsActive ? (
                  <>
                    <span className={`o3d-mode ${wsRunning ? 'is-live' : 'is-replay'}`}>
                      {wsRunning ? 'Đang làm việc' : 'Hoàn tất phiên'}
                    </span>
                    <span className="o3d-headline" aria-live="polite" title={wsTopic}>
                      {wsWorkLabel ?? wsTopic}
                    </span>
                  </>
                ) : (
                  <span className="o3d-headline">
                    {viewScope === 'campus'
                      ? 'Khuôn viên Đại học Duy Tân · 120–122 Hoàng Minh Thảo'
                      : 'Các Agent đang nghỉ · bấm Làm việc để đội ngũ thức dậy phối hợp thật'}
                  </span>
                )}
              </div>
            )}

            <div className="o3d-toolbar" role="toolbar" aria-label="Điều khiển văn phòng">
              {!isLive && (() => {
                const curWeather = WEATHER_OPTIONS.find((w) => w.id === weather) ?? WEATHER_OPTIONS[0];
                return (
                  <>
                    {!wsActive || !wsRunning ? (
                      <button
                        type="button"
                        onClick={() => { void handleStartWorkSession(); }}
                        className="is-wide o3d-top-work"
                        title={wsActive ? 'Chạy một phiên làm việc mới với bài toán mới từ AI & kho tài liệu' : 'Đánh thức đội Agent đứng dậy làm việc & trao đổi thật bằng AI'}
                      >
                        <Play size={14} />
                        <span>{wsActive ? 'Phiên mới' : 'Làm việc'}</span>
                      </button>
                    ) : null}
                    {wsActive && (
                      <button
                        type="button"
                        onClick={handleSleepOffice}
                        className="is-wide o3d-top-sleep"
                        title="Dừng phiên và cho cả đội Agent quay về bàn ngủ"
                      >
                        <Moon size={14} />
                        <span>Cho nghỉ</span>
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={handleToggleScope}
                      className={`is-wide o3d-top-scope${viewScope === 'campus' ? ' is-on' : ''}`}
                      aria-pressed={viewScope === 'campus'}
                      title={viewScope === 'inside' ? 'Bấm để ra ngoài xem toàn cảnh Đại học Duy Tân' : 'Bấm để quay lại bên trong Văn phòng Agent'}
                    >
                      {viewScope === 'inside' ? <Compass size={15} /> : <Building2 size={15} />}
                      <span>{viewScope === 'inside' ? 'Ra ngoài trường' : 'Trong văn phòng'}</span>
                    </button>
                    <button
                      type="button"
                      onClick={handleCycleWeather}
                      className="is-wide o3d-top-weather"
                      title={`Thời tiết hiện tại: ${curWeather.label}. Bấm để đổi thời tiết`}
                      aria-label={`Đổi thời tiết (hiện tại: ${curWeather.label})`}
                    >
                      <WeatherLogo mode={weather} />
                      <span>{curWeather.label}</span>
                    </button>
                    <span className="o3d-sep" aria-hidden />
                  </>
                );
              })()}
              {isLive && (
                <>
                  <button type="button" onClick={handleToggleTempo} className="is-wide" aria-pressed={tempo === 'easy'}
                    title={tempo === 'realtime' ? 'Thời gian thật: bám sát sự kiện, trao việc bằng gói bay. Bấm để chuyển sang Dễ theo dõi' : 'Dễ theo dõi: mỗi bước giữ lâu hơn, robot tự đi đưa hồ sơ. Bấm để chuyển sang Thời gian thật'}>
                    <span>{tempo === 'realtime' ? 'Thời gian thật' : 'Dễ theo dõi'}</span>
                  </button>
                  <button type="button" onClick={handleCycleSpeed} title="Tốc độ phát (1× / 2× / 4×)" className="is-mono">{speedMultiplier}×</button>
                  <button type="button" onClick={handleReplay} title="Diễn lại lượt này"><RotateCcw size={15} /></button>
                </>
              )}
              <label title="Chất lượng hình. Tự động: tự hạ khi máy chạy không mượt">
                <span className="sr-only">Chất lượng hình</span>
                <select value={quality.mode} onChange={(e) => handleSetQuality(e.target.value as QualityMode)}>
                  <option value="auto">Hình: Tự động ({QUALITY_LABEL[quality.level]})</option>
                  <option value="high">Hình: Cao</option>
                  <option value="medium">Hình: Vừa</option>
                  <option value="low">Hình: Thấp</option>
                </select>
              </label>
              <span className="o3d-sep" aria-hidden />
              {hasInteractiveFeed && !isNarrow && !feedOpen && (
                <button
                  type="button"
                  onClick={toggleFeedOpen}
                  aria-pressed={feedOpen}
                  className="is-wide"
                  title="Mở khung trò chuyện đầy đủ của đội Agent"
                >
                  <MessageSquareText size={15} />
                  <span>Hội thoại{chatMessages.length > 0 ? ` (${chatMessages.length})` : ''}</span>
                </button>
              )}
              <button type="button" onClick={() => { setRosterOpen((v) => !v); setSelectedAgentId(null); }} aria-pressed={rosterOpen} className={`is-wide${rosterOpen ? ' is-on' : ''}`} title="Giới thiệu các Agent">
                <Users size={15} /><span>Đội Agent</span>
              </button>
            </div>
          </header>

          {/* Collapsible Agent Roster & Inspector Card */}
          <AgentGuidePanel
            rosterOpen={rosterOpen}
            selectedAgentId={selectedAgentId}
            agents={telemetry?.agents ?? null}
            onSelect={handleGuideSelect}
            onCloseCard={() => setSelectedAgentId(null)}
            onCloseRoster={() => setRosterOpen(false)}
          />

          {/* Vùng chân sân khấu 3D: các bong bóng hội thoại mờ nổi tự nhiên (không đóng khung) */}
          <div className="o3d-bottom-dock">
            {showLiveStack && (
              <OfficeLiveBubbles
                messages={chatMessages}
                activeWorkers={chatActiveWorkers}
                leadActor={chatLeadActor}
                activeWorkLabel={chatActiveWork}
                finished={chatFinished}
                onFocusAgent={handleGuideSelect}
                onOpenChat={() => (isNarrow ? setNarrowTab('chat') : toggleFeedOpen())}
              />
            )}

            {isLive && liveState && (liveState.metrics.agents > 0 || liveState.edges.length > 0) && (
              <div className="o3d-trace-bar" role="status" aria-label="Tóm tắt luồng điều phối">
                {liveState.metrics.route && (
                  <span className={`o3d-trace-chip ${liveState.metrics.route === 'simple' ? 'is-simple' : 'is-complex'}`}>
                    {liveState.metrics.route === 'simple' ? 'Luồng đơn giản' : 'Luồng phức tạp'}
                  </span>
                )}
                <span className="o3d-trace-chip">{liveState.metrics.agents} Agent</span>
                {liveState.metrics.tasks !== null && (
                  <span className="o3d-trace-chip">
                    {liveState.metrics.tasks} việc{liveState.metrics.removed ? ` (−${liveState.metrics.removed} trùng)` : ''}
                  </span>
                )}
                {liveState.metrics.chunks !== null && (
                  <span className="o3d-trace-chip">RAG {liveState.metrics.chunks} đoạn</span>
                )}
                {liveState.metrics.checked !== null && (
                  <span className="o3d-trace-chip">
                    QC {liveState.metrics.checked} ý{liveState.metrics.revisions > 0 ? ` · sửa ${liveState.metrics.revisions}` : ''}
                  </span>
                )}
                {liveState.metrics.flows > 0 && (
                  <span className="o3d-trace-chip">{liveState.metrics.flows} luồng</span>
                )}
                {liveState.finished && (
                  <button type="button" className="o3d-trace-replay" onClick={handleReplay} title="Phát lại toàn bộ luồng điều phối của câu hỏi này">
                    <RotateCcw size={12} /><span>Xem lại</span>
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Chế độ Màn Rộng: Khung chat đầy đủ bên phải */}
        {showSideChat && (
          <OfficeChatFeed
            title="Nhóm điều phối C27"
            question={chatQuestion}
            mode={isLive ? source!.kind : 'live'}
            variant="floating-side"
            messages={chatMessages}
            activeAgents={chatActiveAgents}
            activeWorkers={chatActiveWorkers}
            leadActor={chatLeadActor}
            activeWorkLabel={chatActiveWork}
            waitingSec={isLive ? (liveState?.waitingSec ?? null) : null}
            finished={chatFinished}
            failed={isLive ? Boolean(liveState?.failed) : wsFailed}
            onFocusAgent={handleGuideSelect}
            onClose={toggleFeedOpen}
          />
        )}

        {/* Chế độ Khung Hẹp khi chọn tab Hội thoại */}
        {showFullTabChat && (
          <OfficeChatFeed
            title="Nhóm điều phối C27"
            question={chatQuestion}
            mode={isLive ? source!.kind : 'live'}
            variant="full-tab"
            messages={chatMessages}
            activeAgents={chatActiveAgents}
            activeWorkers={chatActiveWorkers}
            leadActor={chatLeadActor}
            activeWorkLabel={chatActiveWork}
            waitingSec={isLive ? (liveState?.waitingSec ?? null) : null}
            finished={chatFinished}
            failed={isLive ? Boolean(liveState?.failed) : wsFailed}
            onFocusAgent={handleGuideSelect}
          />
        )}
      </div>
    </div>
  );
}
