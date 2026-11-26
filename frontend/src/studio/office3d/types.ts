import type { FlowEdge, FlowKind, LiveMetrics } from './liveDirector';

export type CoreAgentId =
  | 'orchestrator'
  | 'rag'
  | 'analyst'
  | 'reviewer'
  | 'integrator';

export type SpecialistAgentId =
  | 'software'
  | 'business'
  | 'marketing'
  | 'hr'
  | 'finance'
  | 'education';

export type AgentId = CoreAgentId | SpecialistAgentId;

export type AgentAvailabilityMode = 'always' | 'optional' | 'conditional' | 'specialist';

export type ComplexityTier = 'easy' | 'fairly_easy' | 'medium' | 'hard';

export type WeatherMode = 'sunny' | 'sunset' | 'night' | 'storm';

export type RobotAction =
  | 'sleeping'
  | 'waking_up'
  | 'idle'
  | 'walking'
  | 'receiving'
  | 'planning_board'
  | 'cabinet_rag'
  | 'drafting_analysis'
  | 'working_computer'
  | 'thinking'
  | 'brainstorming'
  | 'reviewing_paper'
  | 'handing_over'
  | 'integrating'
  | 'completed';

export type CarryItemKind =
  | 'none'
  | 'request_brief'
  | 'plan_card'
  | 'rag_folder'
  | 'specialist_doc'
  | 'analytics_sheet'
  | 'approved_sheet'
  | 'final_report';

export type CameraPresetId =
  | 'overview'
  | 'huddle'
  | 'core_studio'
  | 'specialist_row'
  | 'rag_analyst'
  | 'city_exterior'
  | 'campus_sports'
  | 'campus_gate'
  | 'campus_gdqp'
  | AgentId;

export interface AgentProfile {
  id: AgentId;
  code: string;
  availability: AgentAvailabilityMode;
  availabilityLabelVi: string;
  name: string;
  shortName: string;
  titleVi: string;
  roomLabel: string;
  roomSubtitle: string;
  duties: string[];
  accentHex: string;
  accentNumber: number;
  stationCenter: [number, number];
  workPos: [number, number];
  workFacingYaw: number;
  sleepPos: [number, number];
  sleepFacingYaw: number;
  sleepSeated: boolean;
  workSeated: boolean;
  corridorEntry: [number, number];
  corridorZ: number;
}

export interface ActivityStage {
  id: string;
  stepLabel: string;
  headline: string;
  detail: string;
  durationSec: number;
  leadActor: AgentId;
  agentDirectives: Array<{
    agentId: AgentId;
    action: RobotAction;
    actionText: string;
    carryItem?: CarryItemKind;
    targetSpot?: AgentId | 'whiteboard' | 'cabinet' | 'reception' | 'easel' | 'huddle' | 'home';
  }>;
  handoff?: {
    from: AgentId;
    to: AgentId;
    item: CarryItemKind;
    label: string;
  };
  dispatchTargets?: {
    from: AgentId;
    toList: AgentId[];
    label: string;
  };
  effects?: {
    requestArrived?: boolean;
    cabinetOpen?: boolean;
    whiteboardCards?: number;
    analystChartActive?: boolean;
    qcApproved?: boolean;
    finalReportReady?: boolean;
  };
}

export interface ComplexityScenario {
  id: string;
  tier: ComplexityTier;
  tierLabelVi: string;
  durationRangeVi: string;
  targetDurationSec: number;
  userRole: string;
  requestTitle: string;
  summary: string;
  awakeAgents: AgentId[];
  stages: ActivityStage[];
}

export interface AgentRuntimeState {
  id: AgentId;
  isAwake: boolean;
  action: RobotAction;
  actionText: string;
  carrying: CarryItemKind;
}

export interface StageSummaryItem {
  id: string;
  stepLabel: string;
  headline: string;
  leadActor: AgentId;
}

export interface StudioTelemetrySnapshot {
  scenarioId: string | null;
  tier: ComplexityTier | null;
  tierLabelVi: string;
  requestTitle: string;
  elapsedSec: number;
  totalDurationSec: number;
  stageIndex: number;
  totalStages: number;
  stagesSummary: StageSummaryItem[];
  headline: string;
  detail: string;
  leadActor: AgentId | null;
  awakeCount: number;
  sleepingCount: number;
  isCompleted: boolean;
  isPaused: boolean;
  weather: WeatherMode;
  agents: Record<AgentId, AgentRuntimeState>;
}

export interface Studio3DController {
  runScenario: (scenario: ComplexityScenario) => void;
  jumpToStage: (stageIndex: number) => void;
  setPaused: (paused: boolean) => void;
  setWeather: (mode: WeatherMode) => void;
  wakeAgents: (ids: AgentId[]) => void;
  putAgentsToSleep: (ids: AgentId[]) => void;
  gatherAtHuddle?: (ids: AgentId[], speakingId?: AgentId | null, statusText?: string) => void;
  setAgentAction: (
    agentId: AgentId,
    action: RobotAction,
    actionText?: string,
    carryItem?: CarryItemKind,
    spot?: 'whiteboard' | 'board_review' | 'reception' | 'cabinet' | 'easel',
  ) => void;
  setLiveScene: (opts: {
    lead?: AgentId | null;
    effects?: Partial<{ requestArrived: boolean; cabinetOpen: boolean; whiteboardCards: number; analystChartActive: boolean; qcApproved: boolean; finalReportReady: boolean }>;
    dispatch?: { from: AgentId; toList: AgentId[] };
    flow?: { kind: FlowKind; label: string };
    wall?: { tierLabel: string; requestTitle: string; stepText: string; progressPct: number };
  }) => void;
  walkAndHandoff: (
    from: AgentId,
    to: AgentId,
    item: CarryItemKind,
    label?: string,
    onArrive?: () => void,
  ) => void;
  settle: () => void;
  setShowFlowHistory?: (show: boolean) => void;
  syncFlowEdges: (edges: FlowEdge[], finished?: boolean) => void;
  syncActiveWorkers?: (activeWorkers: AgentId[], finished?: boolean) => void;
  setWallMetrics: (metrics: LiveMetrics | null) => void;
  setFollowLeadAgent: (follow: boolean) => void;
  setCameraPreset: (preset: CameraPresetId) => void;
  setSpeed: (multiplier: number) => void;
  setLiveTempo: (tempo: 'realtime' | 'easy') => void;
  resetToSleep: () => void;
  setQualityMode: (mode: 'auto' | 'high' | 'medium' | 'low') => void;
  setWallSteps: (steps: { label: string; state: 'done' | 'now' | 'todo' | 'fail' }[]) => void;
  getQuality: () => { mode: 'auto' | 'high' | 'medium' | 'low'; level: 'high' | 'medium' | 'low' };
}
