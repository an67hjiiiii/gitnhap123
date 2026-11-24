import './office3d.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Pause, Play, RotateCcw, SkipForward, Users } from 'lucide-react';
import { AgentOrchestratorCanvas } from './AgentOrchestratorCanvas';
import { ControlDock } from './ControlDock';
import { AgentGuidePanel } from './AgentGuidePanel';
import { LiveDirector, LivePacer, replayPlan, type LiveState, type LiveTempo } from './liveDirector';

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
import { COMPLEXITY_SCENARIOS } from './agents';
import type {
  AgentId,
  CameraPresetId,
  ComplexityScenario,
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

export default function OfficeView({ source, onLiveState }: { source?: OfficeSource; onLiveState?: (s: LiveState) => void } = {}) {
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
  const activeScenarioRef = useRef<ComplexityScenario>(COMPLEXITY_SCENARIOS[2]);

  const [telemetry, setTelemetry] = useState<StudioTelemetrySnapshot | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<AgentId | null>(null);
  // bảng chọn Agent đóng sẵn để không che cảnh; bấm một Agent (trong cảnh hoặc bảng chọn) chỉ hiện thẻ của Agent đó
  const [rosterOpen, setRosterOpen] = useState(false);
  const handleSelectAgent = useCallback((id: AgentId | null) => {
    setSelectedAgentId(id);
    if (id) setRosterOpen(false);
  }, []);
  const handleGuideSelect = useCallback((id: AgentId) => {
    setSelectedAgentId(id);
    setRosterOpen(false);
    setFollowLead(false);
    controllerRef.current?.setCameraPreset(id);
  }, []);
  const [speedMultiplier, setSpeedMultiplier] = useState(1);
  const [followLead, setFollowLead] = useState(false);
  const [showLabels, setShowLabels] = useState(true);
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

  const handleRunScenario = useCallback((scenario: ComplexityScenario) => {
    activeScenarioRef.current = scenario;
    controllerRef.current?.runScenario(scenario);
  }, []);

  const handleEngineReady = useCallback((controller: Studio3DController) => {
    controllerRef.current = controller;
    setEngineReady(true);
    // minh họa: chạy sẵn kịch bản Vừa; trực tiếp/xem lại: chờ sự kiện thật
    if (!isLive) controller.runScenario(COMPLEXITY_SCENARIOS[2]);
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

  const handleToggleFollow = useCallback((follow: boolean) => {
    setFollowLead(follow);
    controllerRef.current?.setFollowLeadAgent(follow);
  }, []);

  const handleSetCameraPreset = useCallback((preset: CameraPresetId) => {
    setFollowLead(false);
    controllerRef.current?.setCameraPreset(preset);
  }, []);

  const handleSetWeather = useCallback((mode: WeatherMode) => {
    setWeather(mode);
    controllerRef.current?.setWeather(mode);
  }, []);

  const handleReplay = useCallback(() => {
    if (source) setReplayKey((k) => k + 1);
    else controllerRef.current?.runScenario(activeScenarioRef.current);
  }, [source]);

  const handleTogglePause = useCallback(() => {
    if (!telemetry) return;
    controllerRef.current?.setPaused(!telemetry.isPaused);
  }, [telemetry]);

  // lượt thật: các bước chiếu lên TV văn phòng (kịch bản minh họa thì máy dựng cảnh tự vẽ)
  useEffect(() => {
    if (!engineReady || !liveState) return;
    controllerRef.current?.setWallSteps(liveState.steps.map((st) => ({ label: st.label, state: st.state })));
  }, [engineReady, liveState?.steps]);

  const handleNextStep = useCallback(() => {
    if (!telemetry || telemetry.totalStages === 0) return;
    const nextIdx = Math.min(telemetry.totalStages - 1, telemetry.stageIndex + 1);
    controllerRef.current?.jumpToStage(nextIdx);
  }, [telemetry]);

  const handleJumpToStage = useCallback((idx: number) => {
    controllerRef.current?.jumpToStage(idx);
  }, []);

  const handleResetToSleep = useCallback(() => {
    controllerRef.current?.resetToSleep();
  }, []);

  useEffect(() => {
    controllerRef.current?.setSpeed(speedMultiplier);
  }, [speedMultiplier]);


  return (
    <div
      className={`office3d-page relative overflow-hidden text-stone-900 select-none transition-colors duration-700 ${WEATHER_BG_CLASS[weather]}`}
    >
      {/* Full-viewport Architectural 3D AI Office with Eilik Companion Robots */}
      <AgentOrchestratorCanvas
        showLabels={showLabels}
        selectedAgentId={selectedAgentId}
        onEngineReady={handleEngineReady}
        onTelemetry={setTelemetry}
        onSelectAgent={handleSelectAgent}
      />

      {/* Thanh trên gọn: một dòng trạng thái; các bước và tiến độ chiếu lên TV văn phòng để không che cảnh */}
      <header className="o3d-top">
        <div className="o3d-status-pill">
          <span className="o3d-status-title">Văn phòng Agent</span>
          {isLive
            ? <span className={`o3d-mode ${source!.kind === 'live' ? 'is-live' : 'is-replay'}`} title={source!.kind === 'live' ? 'Theo sự kiện thật của câu hỏi đang chạy' : 'Diễn lại theo mốc thời gian đã lưu'}>{source!.kind === 'live' ? 'Trực tiếp' : 'Xem lại'}</span>
            : <span className="o3d-mode is-demo" title="Kịch bản dựng sẵn để giới thiệu cách chia việc, chưa phải lượt chạy thật">Minh họa</span>}
          <span className="o3d-headline" aria-live="polite" title={isLive ? liveState?.question : telemetry?.requestTitle}>
            {isLive
              ? (liveState?.headline ?? (source!.kind === 'live' ? 'Chưa có câu hỏi nào đang chạy' : 'Đang dựng văn phòng…'))
              : (telemetry?.headline ?? 'Đang dựng văn phòng…')}
          </span>
          {isLive && liveState?.waitingSec != null && !liveState.finished && <span className="o3d-wait" aria-hidden="true" title="Không có sự kiện mới: mô hình đang suy nghĩ hoặc đang viết">chờ mô hình {liveState.waitingSec} giây</span>}
          {isLive && liveState?.finished && <span className={`o3d-done ${liveState.failed ? 'is-fail' : ''}`}>{liveState.failed ? 'Không hoàn thành' : 'Đã xong'}</span>}
        </div>

        <div className="o3d-toolbar" role="toolbar" aria-label="Điều khiển văn phòng">
          {!isLive && (
            <button type="button" onClick={handleTogglePause} title={telemetry?.isPaused ? 'Tiếp tục' : 'Tạm dừng để quan sát'}>
              {telemetry?.isPaused ? <Play size={15} /> : <Pause size={15} />}
            </button>
          )}
          {!isLive && <button type="button" onClick={handleNextStep} title="Sang bước tiếp theo"><SkipForward size={15} /></button>}
          {isLive && <button type="button" onClick={handleToggleTempo} className="is-wide" aria-pressed={tempo === 'easy'}
            title={tempo === 'realtime' ? 'Thời gian thật: bám sát sự kiện, trao việc bằng gói bay. Bấm để chuyển sang Dễ theo dõi' : 'Dễ theo dõi: mỗi bước giữ lâu hơn, robot tự đi đưa hồ sơ. Bấm để chuyển sang Thời gian thật'}>
            <span>{tempo === 'realtime' ? 'Thời gian thật' : 'Dễ theo dõi'}</span></button>}
          <button type="button" onClick={handleCycleSpeed} title="Tốc độ phát (1× / 2× / 4×)" className="is-mono">{speedMultiplier}×</button>
          <button type="button" onClick={handleReplay} title={isLive ? 'Diễn lại lượt này' : 'Phát lại kịch bản'}><RotateCcw size={15} /></button>
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
          <button type="button" onClick={() => { setRosterOpen((v) => !v); setSelectedAgentId(null); }} aria-pressed={rosterOpen} className={`is-wide${rosterOpen ? ' is-on' : ''}`} title="Giới thiệu các Agent">
            <Users size={15} /><span>Đội Agent</span>
          </button>
        </div>
      </header>

      {/* Collapsible Bottom Control Dock */}
      <AgentGuidePanel
        rosterOpen={rosterOpen}
        selectedAgentId={selectedAgentId}
        agents={telemetry?.agents ?? null}
        onSelect={handleGuideSelect}
        onCloseCard={() => setSelectedAgentId(null)}
        onCloseRoster={() => setRosterOpen(false)}
      />

      {!isLive && <ControlDock
        activeScenarioId={telemetry?.scenarioId ?? null}
        speedMultiplier={speedMultiplier}
        followLead={followLead}
        showLabels={showLabels}
        weather={weather}
        selectedAgentId={selectedAgentId}
        onRunScenario={handleRunScenario}
        onSetCameraPreset={handleSetCameraPreset}
        onSetSpeed={handleSetSpeed}
        onToggleFollow={handleToggleFollow}
        onToggleLabels={setShowLabels}
        onSetWeather={handleSetWeather}
        onResetToSleep={handleResetToSleep}
      />}
    </div>
  );
}
