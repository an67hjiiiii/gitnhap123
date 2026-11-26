import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import {
  ACTION_LABELS_VI,
  AGENT_PROFILES,
  ALL_AGENT_IDS,
  ANALYST_EASEL_SPOT,
  CABINET_SPOT,
  HUDDLE_CENTER,
  RECEPTION_SPOT,
  WHITEBOARD_SPOT,
  computeStudioWalkPath,
} from '../agents';
import type {
  ActivityStage,
  AgentId,
  AgentRuntimeState,
  CameraPresetId,
  CarryItemKind,
  ComplexityScenario,
  RobotAction,
  Studio3DController,
  StudioTelemetrySnapshot,
  WeatherMode,
} from '../types';
import type { FlowEdge, FlowKind, LiveMetrics } from '../liveDirector';
import type { CampusEnvironmentInstance } from './dtuCampusEnvironment';
import {
  createFlowGraph3D,
  type FlowGraph3DInstance,
  type FlowLogItem,
  type ProjectedFlowBadge,
} from './flowGraph';
import { createStudioMaterials, type StudioMaterialLibrary } from './materials';
import {
  buildStudioArchitecture,
  type StudioArchitectureInstance,
} from './officeArchitecture';
import {
  buildBeanRobotCharacter,
  getOfficeFloorY,
  type BeanRobotInstance,
} from './robotCharacter';
import { createStudioTextures, type StudioTextureSet, type WallStepState } from './textures';
import {
  createWeatherSystem,
  type WeatherSystemInstance,
} from './weatherSystem';


export type QualityLevel = 'high' | 'medium' | 'low';
export type QualityMode = 'auto' | QualityLevel;
export type HardwareTier = 'discrete' | 'integrated' | 'software';
const QUALITY: Record<QualityLevel, { maxDpr: number; shadowSize: number }> = {
  high: { maxDpr: 1.5, shadowSize: 1024 },
  medium: { maxDpr: 1.2, shadowSize: 512 },
  low: { maxDpr: 0.9, shadowSize: 0 },
};
export type LiveSpot = 'whiteboard' | 'board_review' | 'reception' | 'cabinet' | 'easel';
const LIVE_SPOTS: Record<LiveSpot, { pos: [number, number]; yaw: number }> = {
  whiteboard: { pos: [WHITEBOARD_SPOT[0], WHITEBOARD_SPOT[1]], yaw: Math.PI },
  // Reviewer đứng cạnh Orchestrator ở bảng trắng để soát kế hoạch (không chồng lên nhau)
  board_review: { pos: [WHITEBOARD_SPOT[0] + 1.35, WHITEBOARD_SPOT[1] + 0.35], yaw: Math.PI - 0.35 },
  reception: { pos: [RECEPTION_SPOT[0], RECEPTION_SPOT[1]], yaw: 0 },
  cabinet: { pos: [CABINET_SPOT[0], CABINET_SPOT[1]], yaw: Math.PI },
  easel: { pos: [ANALYST_EASEL_SPOT[0], ANALYST_EASEL_SPOT[1]], yaw: Math.PI },
};
export interface LiveEffects {
  requestArrived: boolean; cabinetOpen: boolean; whiteboardCards: number;
  analystChartActive: boolean; qcApproved: boolean; finalReportReady: boolean;
}
const NO_EFFECTS: LiveEffects = {
  requestArrived: false, cabinetOpen: false, whiteboardCards: 0, analystChartActive: false, qcApproved: false, finalReportReady: false,
};
const IDLE_FRAME_MS = 1000 / 12;   // đứng yên: 12 khung/giây đủ cho nhịp thở, zzz
const LOW_ACTIVE_FRAME_MS = 1000 / 24; // máy GPU mềm / mức thấp: giữ nhịp mượt 24 FPS không nghẽn CPU
const AUTO_DOWNGRADE_FPS = 24;     // chỉ hạ Cao -> Vừa khi thực sự tụt sâu < 24 FPS liên tục 2 chu kỳ
const AUTO_LOW_FPS = 16;           // chỉ hạ Vừa -> Thấp khi thực sự giật nặng < 16 FPS liên tục 2 chu kỳ
const AUTO_UPGRADE_FPS = 48;       // máy rảnh trở lại >= 48 FPS liên tục 2 chu kỳ -> tự phục hồi lên Cao
const AUTO_WARMUP_MS = 6000;       // bỏ qua 6 giây đầu khởi tạo/đổi cảnh để tránh tụt chất lượng oan
const AUTO_SAMPLE_SPAN_MS = 2500;

export interface ProjectedAgentAnchor {
  id: AgentId;
  x: number;
  y: number;
  visible: boolean;
  isAwake: boolean;
  isLead: boolean;
  action: RobotAction;
  actionText: string;
  carrying: CarryItemKind;
}

export interface StudioEngineCallbacks {
  onTelemetry: (snapshot: StudioTelemetrySnapshot) => void;
  onSelectAgent: (id: AgentId | null) => void;
  onAnchorsUpdated?: (anchors: ProjectedAgentAnchor[]) => void;
  /** chỉ vị trí đổi (robot đi, camera xoay): giao diện dời nhãn trực tiếp, không vẽ lại React mỗi khung */
  onAnchorsMoved?: (anchors: ProjectedAgentAnchor[]) => void;
  /** khung hình đầu đã vẽ: giao diện tắt lớp "Đang dựng văn phòng" */
  onFirstFrame?: () => void;
  /** nhãn ngắn của các luồng trao đổi đang chạy giữa các Agent */
  onFlowBadgesUpdated?: (badges: ProjectedFlowBadge[]) => void;
  /** chỉ vị trí nhãn luồng đổi khi lăn chuột / xoay camera: dời trực tiếp DOM transform, 0 React re-render */
  onFlowBadgesMoved?: (badges: ProjectedFlowBadge[]) => void;
  /** nhật ký trao đổi gần nhất giữa các Agent (Ai ➔ Ai · nội dung) */
  onFlowLogsUpdated?: (logs: FlowLogItem[]) => void;
}

interface AgentMover {
  waypoints: Array<[number, number]>;
  waypointIdx: number;
  finalYaw: number;
  finalAction: RobotAction;
  finalSeated: boolean;
  onArrive?: () => void;
}

interface HandoffRoute {
  from: AgentId;
  to: AgentId;
  item: CarryItemKind;
  phase: 'going' | 'passing' | 'returning';
  pauseTimer: number;
  returnPos: [number, number];
  returnYaw: number;
  returnAction: RobotAction;
  returnSeated: boolean;
  onArrive?: () => void;
}

const CAMERA_PRESETS: Record<
  'overview' | 'huddle' | 'core_studio' | 'specialist_row' | 'rag_analyst' | 'city_exterior' | 'campus_sports' | 'campus_gate' | 'campus_gdqp',
  { pos: [number, number, number]; target: [number, number, number] }
> = {
  overview: { pos: [0, 11.2, 14.3], target: [0, 0.55, 0.15] },
  huddle: { pos: [0, 7.6, 8.2], target: [0, 0.7, 0.65] },
  core_studio: { pos: [0, 7.6, 5.8], target: [0, 0.9, -2.7] },
  specialist_row: { pos: [0, 6.8, 11.6], target: [0, 0.55, 4.35] },
  rag_analyst: { pos: [-1.6, 6.4, 4.8], target: [-5.5, 0.75, -2.3] },
  city_exterior: { pos: [-42, 34, 68], target: [8, -10, -22] },
  campus_sports: { pos: [74, 12, 6], target: [44, -13, -22] },
  campus_gate: { pos: [-1, -4.5, 54], target: [-7.5, -11.6, 27.6] },
  campus_gdqp: { pos: [-44, -4.2, 6], target: [-72, -11.8, -5.5] },
};

/** Vòm phản chiếu studio mềm (không có đèn trần hình vuông gây đốm trắng trên kính đen OLED của Robot V12). */
function buildSoftStudioEnvScene(): { envScene: THREE.Scene; tex: THREE.CanvasTexture; geo: THREE.SphereGeometry; mat: THREE.MeshBasicMaterial } {
  const envScene = new THREE.Scene();
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 256;
  const ctx = c.getContext('2d')!;
  const g = ctx.createLinearGradient(0, 0, 0, 256);
  g.addColorStop(0.0, '#fff9ef');
  g.addColorStop(0.28, '#dcd3c5');
  g.addColorStop(0.55, '#687382');
  g.addColorStop(0.78, '#38302a');
  g.addColorStop(1.0, '#181514');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 256);

  const wg = ctx.createRadialGradient(350, 76, 8, 350, 76, 56);
  wg.addColorStop(0, 'rgba(255,254,248,0.96)');
  wg.addColorStop(0.5, 'rgba(255,248,234,0.42)');
  wg.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = wg;
  ctx.fillRect(285, 14, 130, 126);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.mapping = THREE.EquirectangularReflectionMapping;
  const geo = new THREE.SphereGeometry(12, 28, 18);
  const mat = new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide });
  envScene.add(new THREE.Mesh(geo, mat));
  return { envScene, tex, geo, mat };
}

function detectHardwareTier(gl: WebGLRenderingContext | WebGL2RenderingContext): HardwareTier {
  try {
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    const rendererStr = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '') : '';
    if (/SwiftShader|llvmpipe|Software|Mesa OffScreen|Microsoft Basic Render/i.test(rendererStr)) {
      return 'software';
    }
    const isDiscreteGpu = /(?:NVIDIA|GeForce|RTX|GTX|Quadro|Radeon\s+RX|Radeon\s+Pro|Apple\s+M[1-9]|Arc\s+A\d)/i.test(rendererStr);
    if (isDiscreteGpu) return 'discrete';
    const isWeakIntegratedGpu = /(?:Intel.*(?:HD|UHD)|Mali|Adreno|PowerVR)/i.test(rendererStr);
    const cores = typeof navigator !== 'undefined' ? (navigator.hardwareConcurrency || 8) : 8;
    const memGb = typeof navigator !== 'undefined' ? ((navigator as unknown as { deviceMemory?: number }).deviceMemory || 8) : 8;
    if (cores <= 4 || memGb <= 4 || (isWeakIntegratedGpu && cores < 8)) {
      return 'integrated';
    }
    return 'discrete';
  } catch {
    return 'discrete';
  }
}

export class Office3DEngine implements Studio3DController {
  private container: HTMLElement;
  private callbacks: StudioEngineCallbacks;
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private pmremGenerator: THREE.PMREMGenerator | null = null;
  private envRT: THREE.WebGLRenderTarget | null = null;
  private envInitHandle: number | null = null;
  private textures: StudioTextureSet;
  private materials: StudioMaterialLibrary;
  private architecture: StudioArchitectureInstance;
  private cityEnv: CampusEnvironmentInstance | null = null;
  private campusLoadPromise: Promise<void> | null = null;
  private campusIdleHandle: number | null = null;
  private lastNightGlow = 0.05;
  private maxAniso = 1;
  private weatherSystem: WeatherSystemInstance;
  private robots: Record<AgentId, BeanRobotInstance>;

  private hardwareTier: HardwareTier;
  private isSoftwareGl: boolean;
  private isLowEndHw: boolean;
  private gl: WebGLRenderingContext | WebGL2RenderingContext;
  private raycaster = new THREE.Raycaster();
  private pointerNdc = new THREE.Vector2(-99, -99);
  private hoveredAgent: AgentId | null = null;
  private selectedAgent: AgentId | null = null;
  private pointerDownPos = { x: 0, y: 0 };
  private viewportWidth = 1;
  private viewportHeight = 1;
  private pageRootEl: HTMLElement | null = null;
  private baseDpr = 1.5;

  private cameraGoalPos = new THREE.Vector3(...CAMERA_PRESETS.overview.pos);
  private cameraGoalTarget = new THREE.Vector3(...CAMERA_PRESETS.overview.target);
  private cameraLerpActive = false;
  private followLeadAgent = false;
  private exteriorReveal = 0;
  private interiorHidden = false;
  private anchorsHiddenForCity = false;
  private userInteractingUntil = 0;
  private isPointerDragging = false;
  private prevCamDist = 14.7;
  private readonly studioHomeTarget = new THREE.Vector3(...CAMERA_PRESETS.overview.target);
  /** khung hẹp/dựng đứng (bảng văn phòng cạnh ô chat): lùi camera, mở góc nhìn để vẫn thấy cả phòng */
  private viewFit = 1;
  private lastPreset: CameraPresetId = 'overview';

  private currentScenario: ComplexityScenario | null = null;
  private currentStageIndex = 0;
  private stageElapsedSec = 0;
  private totalElapsedSec = 0;
  private stageHandoffTriggered = false;
  private isCompleted = false;
  private isPaused = false;
  private speedMultiplier = 1;
  private awakeSet = new Set<AgentId>();
  private leadActor: AgentId | null = null;
  private agentStates: Record<AgentId, AgentRuntimeState>;
  private movers: Partial<Record<AgentId, AgentMover>> = {};
  // nhiều robot có thể cùng đi trao hồ sơ (việc con song song): mỗi robot một tuyến
  private handoffs = new Map<AgentId, HandoffRoute>();
  // chế độ Thời gian thật (chế độ trực tiếp): đi nhanh hơn; lệnh mới tới khi robot còn đang đi thì nhảy tới đích cũ trước
  private liveTempo: 'realtime' | 'easy' = 'easy';

  private routeRibbonMesh: THREE.Mesh;
  private routeRibbonMat: THREE.MeshBasicMaterial;
  private flowGraph: FlowGraph3DInstance;
  private settlingFast = false;
  private wallMetrics: LiveMetrics | null = null;
  private lastFlowBadgeSig = '';
  private lastFlowBadgeContentSig = '';
  private lastFlowLogSig = '';

  private tempVec3 = new THREE.Vector3();
  private projectedAnchors: ProjectedAgentAnchor[] = [];

  private rafId: number | null = null;
  private disposed = false;
  private lastTime = 0;
  private elapsedTotal = 0;
  private telemetryThrottle = 0;
  private resizeObserver: ResizeObserver;
  // Đợt 2 (23/11): vẽ thưa khi đứng yên, dừng khi khuất, chất lượng tự chọn theo FPS
  private hemiLight!: THREE.HemisphereLight;
  private sunKey!: THREE.DirectionalLight;
  private activeUntil = 0;
  private lastRenderAt = 0;
  private onScreen = true;
  private intersection: IntersectionObserver | null = null;
  private frameIndex = 0;
  private lastAnchorSig = '';
  private lastAnchorPosSig = '';
  private wallSteps: { label: string; state: WallStepState }[] = [];
  private liveWall: { tierLabel: string; requestTitle: string; stepText: string; progressPct: number } | null = null;
  private liveEffects: LiveEffects = { ...NO_EFFECTS };
  private quality: QualityLevel = 'high';
  private qualityMode: QualityMode = 'auto';
  private fpsSampleStart = 0;
  private fpsSampleFrames = 0;
  private lowFpsStreak = 0;
  private highFpsStreak = 0;
  private lastQualityChange = 0;
  private lastSampleAt = 0;
  private wallDirty = false;
  private lastWallSyncAt = 0;
  private shadowDirty = true;
  private telemetryDirty = false;
  private resizeRafId: number | null = null;

  constructor(container: HTMLElement, callbacks: StudioEngineCallbacks) {
    this.container = container;
    this.callbacks = callbacks;
    const mark = (k: string) => { this.perf.build[k] = Math.round(performance.now() - t0); };
    const t0 = performance.now();

    const width = Math.max(container.clientWidth, 1);
    const height = Math.max(container.clientHeight, 1);
    this.viewportWidth = width;
    this.viewportHeight = height;
    this.pageRootEl = container.closest('.office3d-page') as HTMLElement | null;

    // Tạo duy nhất 1 WebGL context (không tạo context probe thừa gây đơ ~150ms khi bấm mở trang!)
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: 'high-performance',
      alpha: false,
    });
    this.gl = this.renderer.getContext();
    this.hardwareTier = detectHardwareTier(this.gl);
    this.isSoftwareGl = this.hardwareTier === 'software';
    this.isLowEndHw = this.hardwareTier !== 'discrete';
    if (this.pageRootEl) {
      this.pageRootEl.dataset.hw = this.hardwareTier;
    }

    this.baseDpr = Math.min(window.devicePixelRatio || 1, this.isSoftwareGl ? 0.7 : this.isLowEndHw ? 1.2 : 1.5);
    this.renderer.setPixelRatio(this.baseDpr);
    this.renderer.setSize(width, height);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.02;
    this.renderer.shadowMap.enabled = !this.isSoftwareGl;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.domElement.style.display = 'block';
    this.renderer.domElement.style.width = '100%';
    this.renderer.domElement.style.height = '100%';
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xe6dfd3);
    this.scene.fog = new THREE.FogExp2(0xe6dfd3, 0.0064);

    // Wide far plane (680m) so zooming out to orbit DTU Hòa Khánh Nam, Stadium & Đà Nẵng mountains stays crisp!
    this.camera = new THREE.PerspectiveCamera(40, width / height, 0.5, 680);
    this.camera.position.set(...CAMERA_PRESETS.overview.pos);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(...CAMERA_PRESETS.overview.target);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.085;
    this.controls.zoomSpeed = 1.55;
    this.controls.rotateSpeed = 0.9;
    this.controls.maxPolarAngle = Math.PI * 0.465;
    this.controls.minPolarAngle = Math.PI * 0.12;
    this.controls.minDistance = 4.2;
    this.controls.maxDistance = 175;
    this.controls.addEventListener('start', () => {
      this.cameraLerpActive = false;
      this.isPointerDragging = true;
      this.userInteractingUntil = performance.now() + 500;
      this.markActive(1500);
    });
    this.controls.addEventListener('end', () => {
      this.isPointerDragging = false;
      this.userInteractingUntil = performance.now() + 350;
    });

    mark('renderer');
    // Nạp PMREM RoomEnvironment trì hoãn sau khung hình đầu tiên để cắt ~180ms đơ main thread lúc bấm mở trang!
    this.scene.environmentIntensity = 0.62;

    // Realistic Architectural Lighting Rig controlled dynamically by WeatherSystem
    const hemi = new THREE.HemisphereLight(0xfff9ee, 0xbba890, 1.15);
    this.scene.add(hemi);
    this.hemiLight = hemi;

    const sunKey = new THREE.DirectionalLight(0xffefd6, 2.1);
    sunKey.position.set(16, 28, 18);
    sunKey.castShadow = !this.isSoftwareGl;
    if (sunKey.castShadow) {
      sunKey.shadow.mapSize.set(1024, 1024);
      sunKey.shadow.camera.left = -16;
      sunKey.shadow.camera.right = 16;
      sunKey.shadow.camera.top = 15;
      sunKey.shadow.camera.bottom = -15;
      sunKey.shadow.camera.near = 4;
      sunKey.shadow.camera.far = 78;
      sunKey.shadow.bias = -0.00045;
      sunKey.shadow.normalBias = 0.022;
    }
    this.scene.add(sunKey);
    this.sunKey = sunKey;

    const coolBounce = new THREE.DirectionalLight(0xc7e0ff, 0.5);
    coolBounce.position.set(-16, 18, -14);
    this.scene.add(coolBounce);

    mark('env');
    const maxAniso = this.isSoftwareGl
      ? 1
      : this.isLowEndHw
        ? Math.min(4, this.renderer.capabilities.getMaxAnisotropy())
        : this.renderer.capabilities.getMaxAnisotropy();
    this.maxAniso = maxAniso;
    this.textures = createStudioTextures(maxAniso);
    this.materials = createStudioMaterials(this.textures, this.isSoftwareGl);
    mark('textures');
    this.architecture = buildStudioArchitecture(this.materials, this.textures);
    mark('architecture');
    this.scene.add(this.architecture.group);

    // Khung cảnh 360° ĐH Duy Tân – Hòa Khánh Nam: tải & dựng trì hoãn (lazy) sau frame đầu tiên để chuyển trang 0ms lag!
    mark('city');

    // Real-time City-Scale 3D Weather & Time-of-Day System (Sunny / Sunset / Night / Storm!)
    this.weatherSystem = createWeatherSystem({
      scene: this.scene,
      renderer: this.renderer,
      hemiLight: hemi,
      keyLight: sunKey,
      fillLight: coolBounce,
      onWarmLampUpdate: (intensity) => this.architecture.setAtmosphereLight(intensity),
      onCityNightGlow: (intensity) => {
        this.lastNightGlow = intensity;
        this.cityEnv?.setNightGlow(intensity);
      },
    });
    this.scene.add(this.weatherSystem.group);

    this.robots = {} as Record<AgentId, BeanRobotInstance>;
    this.agentStates = {} as Record<AgentId, AgentRuntimeState>;

    for (const id of ALL_AGENT_IDS) {
      const robot = buildBeanRobotCharacter(id, this.materials);
      this.robots[id] = robot;
      this.scene.add(robot.root);
      this.agentStates[id] = {
        id,
        isAwake: false,
        action: 'sleeping',
        actionText: 'Zzz',
        carrying: 'none',
      };
    }

    mark('robots');
    this.routeRibbonMat = new THREE.MeshBasicMaterial({
      color: 0x059669,
      transparent: true,
      opacity: 0.82,
    });
    this.routeRibbonMesh = new THREE.Mesh(new THREE.BufferGeometry(), this.routeRibbonMat);
    this.routeRibbonMesh.visible = false;
    this.scene.add(this.routeRibbonMesh);

    this.flowGraph = createFlowGraph3D();
    this.scene.add(this.flowGraph.group);

    this.raycaster.layers.set(1);

    this.renderer.domElement.addEventListener('pointermove', this.handlePointerMove);
    this.renderer.domElement.addEventListener('pointerdown', this.handlePointerDown);
    this.renderer.domElement.addEventListener('pointerup', this.handlePointerUp);
    this.renderer.domElement.addEventListener('wheel', this.handleWheel, { passive: true });

    this.resizeObserver = new ResizeObserver(() => this.scheduleResize());
    this.resizeObserver.observe(container);
    this.controls.addEventListener('change', () => this.markActive(1200));
    if (typeof IntersectionObserver !== 'undefined') {
      this.intersection = new IntersectionObserver(([entry]) => {
        const was = this.onScreen;
        this.onScreen = entry.isIntersecting;
        if (this.onScreen && !was && this.rafId === null) {
          this.lastTime = performance.now();
          this.markActive();
          this.scheduleNextFrame();
        }
      });
      this.intersection.observe(container);
    }
    document.addEventListener('visibilitychange', this.handleVisibilityChange);
    this.renderer.shadowMap.autoUpdate = false;
    // Tự tối ưu theo phần cứng: GPU rời mạnh giữ Tự động (Cao) sắc nét 100%; laptop cấu hình thấp/iGPU tự vào Vừa mượt mà ngay từ giây đầu; Software GL vào Thấp.
    this.applyQuality(this.isSoftwareGl ? 'low' : this.isLowEndHw ? 'medium' : 'high');

    this.resetToSleep();
    if (import.meta.env.DEV) (window as unknown as { __office3d?: Office3DEngine }).__office3d = this;
    this.applyViewFit();
    this.camera.updateProjectionMatrix();
    this.overviewGoal(this.camera.position, this.controls.target);
    this.cameraGoalPos.copy(this.camera.position);
    this.cameraGoalTarget.copy(this.controls.target);
    mark('done');
    // không dùng renderer.compileAsync: đo 23/11 không giảm khung đầu, và trên GPU AMD/Direct3D chương trình shader bị
    // xóa khi đang biên dịch dở (GL_INVALID_VALUE glGetProgramiv) làm sàn, bàn, robot không được vẽ
    this.lastTime = performance.now();
    this.scheduleNextFrame();
  }

  private handleVisibilityChange = (): void => {
    if (this.disposed) return;
    if (!document.hidden && this.onScreen && this.rafId === null) {
      this.lastTime = performance.now();
      this.markActive(1200);
      this.scheduleNextFrame();
    }
  };

  /** Tải & dựng khuôn viên ĐH Duy Tân trì hoãn (chỉ 1 lần): không chặn khung đầu khi chuyển sang tab Văn phòng. */
  private ensureCampusLoaded(): void {
    if (this.cityEnv || this.campusLoadPromise || this.disposed) return;
    this.campusLoadPromise = import('./dtuCampusEnvironment')
      .then(({ buildDtuCampusEnvironment }) => {
        if (this.disposed || this.cityEnv) return;
        const t0 = performance.now();
        const campus = buildDtuCampusEnvironment(this.maxAniso, this.isLowEndHw || this.quality === 'low');
        campus.setNightGlow(this.lastNightGlow);
        campus.group.visible = this.exteriorReveal > 0.015;
        this.scene.add(campus.group);
        this.cityEnv = campus;
        this.perf.build.dtuCampus = Math.round(performance.now() - t0);
        // Nạp dần texture của khuôn viên lên GPU khi rảnh (2 texture/frame) để lần đầu lăn chuột ra không bị khựng upload VRAM!
        const texQueue: THREE.Texture[] = [];
        const seen = new Set<string>();
        campus.group.traverse((obj) => {
          const mat = (obj as THREE.Mesh).material;
          if (!mat) return;
          const list = Array.isArray(mat) ? mat : [mat];
          for (const m of list) {
            const std = m as THREE.MeshStandardMaterial;
            for (const t of [std.map, std.bumpMap, std.emissiveMap]) {
              if (t && !seen.has(t.uuid)) {
                seen.add(t.uuid);
                texQueue.push(t);
              }
            }
          }
        });
        let qi = 0;
        const pumpTextures = () => {
          if (this.disposed || qi >= texQueue.length) return;
          const end = Math.min(qi + 2, texQueue.length);
          for (; qi < end; qi++) {
            this.renderer.initTexture(texQueue[qi]);
          }
          if (qi < texQueue.length) requestAnimationFrame(pumpTextures);
        };
        if (texQueue.length > 0) requestAnimationFrame(pumpTextures);
        if (this.exteriorReveal > 0.015) this.markActive(1000);
      })
      .catch(() => {
        this.campusLoadPromise = null;
      });
  }

  /** Nạp trước khuôn viên ĐH Duy Tân lúc rảnh trên trang Văn phòng Agent toàn màn hình để lăn chuột ra ngoài 0ms khựng! */
  private scheduleCampusPreload(): void {
    if (this.cityEnv || this.campusLoadPromise || this.campusIdleHandle !== null || this.disposed) return;
    if (this.isSoftwareGl || this.viewportWidth < 820) return;
    const w = window as unknown as { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number };
    const start = () => {
      this.campusIdleHandle = null;
      if (this.disposed || this.cityEnv) return;
      this.ensureCampusLoaded();
    };
    if (typeof w.requestIdleCallback === 'function') {
      this.campusIdleHandle = w.requestIdleCallback(start, { timeout: 2200 });
    } else {
      this.campusIdleHandle = window.setTimeout(start, 1100);
    }
  }

  private scheduleEnvInit(): void {
    if (this.envRT || this.envInitHandle !== null || this.disposed) return;
    if (this.quality === 'low' || this.isSoftwareGl) return;
    const run = () => {
      this.envInitHandle = null;
      if (this.disposed || this.envRT) return;
      this.pmremGenerator = new THREE.PMREMGenerator(this.renderer);
      const { envScene, tex, geo, mat } = buildSoftStudioEnvScene();
      this.envRT = this.pmremGenerator.fromScene(envScene, 0.03);
      tex.dispose();
      geo.dispose();
      mat.dispose();
      if (this.quality !== 'low') {
        this.scene.environment = this.envRT.texture;
        this.hemiLight.intensity = 0.96;
      }
    };
    this.envInitHandle = window.setTimeout(run, 180);
  }

  /** Đánh dấu có chuyển động để vẽ đủ khung trong `ms` tới. */
  public markActive(ms = 2500): void {
    this.activeUntil = Math.max(this.activeUntil, performance.now() + ms);
  }

  private isActive(now: number): boolean {
    const running = !!this.currentScenario && !this.isCompleted && !this.isPaused;
    return running || now < this.activeUntil || this.cameraLerpActive || this.followLeadAgent
      || this.handoffs.size > 0 || this.flowGraph.hasActiveTraffic() || Object.keys(this.movers).length > 0
      || (this.exteriorReveal > 0.001 && this.exteriorReveal < 0.999);
  }

  public getQuality(): { mode: QualityMode; level: QualityLevel } {
    return { mode: this.qualityMode, level: this.quality };
  }

  public setQualityMode(mode: QualityMode): void {
    this.qualityMode = mode;
    this.lowFpsStreak = 0;
    this.highFpsStreak = 0;
    if (mode !== 'auto') this.applyQuality(mode);
    else if (!this.isSoftwareGl && this.quality !== 'high') this.applyQuality('high');
    this.fpsSampleFrames = 0;
    this.markActive();
  }

  private applyQuality(level: QualityLevel): void {
    this.quality = level;
    this.lastQualityChange = performance.now();
    const dpr = window.devicePixelRatio || 1;
    const cap = level === 'low' && this.isSoftwareGl ? 0.65 : QUALITY[level].maxDpr;
    this.baseDpr = Math.min(dpr, cap);
    this.renderer.setPixelRatio(this.baseDpr);
    // Mức thấp: tắt IBL environment map PBR (rất nặng trên GPU mềm/iGPU yếu) và bù nhẹ ánh sáng bầu trời;
    // mức Trung bình/Cao giữ nguyên 100% ánh sáng môi trường PBR gốc.
    const wantEnv = level !== 'low';
    if (wantEnv && !this.envRT && this.perf.frames > 0) this.scheduleEnvInit();
    const nextEnv = wantEnv ? (this.envRT?.texture ?? null) : null;
    if (this.scene.environment !== nextEnv) {
      this.scene.environment = nextEnv;
      this.hemiLight.intensity = nextEnv ? 0.96 : 1.2;
    }
    const shadows = QUALITY[level].shadowSize > 0 && !this.isSoftwareGl;
    if (shadows !== this.renderer.shadowMap.enabled) {
      this.renderer.shadowMap.enabled = shadows;
      this.sunKey.castShadow = shadows;
      // đổi bật/tắt bóng phải biên dịch lại shader của vật liệu
      this.scene.traverse((o) => {
        const m = (o as THREE.Mesh).material;
        if (m) (Array.isArray(m) ? m : [m]).forEach((x) => { x.needsUpdate = true; });
      });
    }
    if (shadows && this.sunKey.shadow.mapSize.x !== QUALITY[level].shadowSize) {
      this.sunKey.shadow.mapSize.set(QUALITY[level].shadowSize, QUALITY[level].shadowSize);
      this.sunKey.shadow.map?.dispose();
      this.sunKey.shadow.map = null as unknown as THREE.WebGLRenderTarget;
    }
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.shadowDirty = true;
    this.renderer.shadowMap.needsUpdate = true;
    this.handleResize();
  }

  /**
   * Tự động điều chỉnh chất lượng theo FPS thực tế (mặc định Tự động Cao):
   * - Bỏ qua 6s đầu khởi tạo / đổi cảnh và bỏ qua khung bị gián đoạn bởi React/chuyển tab (> 120ms).
   * - Chỉ hạ 1 bậc khi FPS thực sự tụt sâu liên tục 2 chu kỳ đo liền nhau (~5s).
   * - Tự phục hồi mượt từ Vừa -> Cao khi máy chạy êm >= 48 FPS liên tục 2 chu kỳ.
   */
  private sampleFps(now: number): void {
    if (this.qualityMode !== 'auto' || this.isSoftwareGl || now - this.lastQualityChange < AUTO_WARMUP_MS) return;
    if (this.fpsSampleFrames > 0 && now - this.lastSampleAt > 120) {
      this.fpsSampleFrames = 0;
      return;
    }
    this.lastSampleAt = now;
    if (this.fpsSampleFrames === 0) this.fpsSampleStart = now;
    this.fpsSampleFrames++;
    const span = now - this.fpsSampleStart;
    if (span < AUTO_SAMPLE_SPAN_MS) return;
    const fps = (this.fpsSampleFrames - 1) / (span / 1000);
    this.fpsSampleFrames = 0;

    if (this.quality === 'high') {
      if (fps < AUTO_DOWNGRADE_FPS) {
        this.lowFpsStreak++;
        if (this.lowFpsStreak >= 2) {
          this.lowFpsStreak = 0;
          this.applyQuality('medium');
        }
      } else {
        this.lowFpsStreak = 0;
      }
      return;
    }

    if (this.quality === 'medium') {
      if (fps < AUTO_LOW_FPS) {
        this.lowFpsStreak++;
        this.highFpsStreak = 0;
        if (this.lowFpsStreak >= 2) {
          this.lowFpsStreak = 0;
          this.applyQuality('low');
        }
      } else if (fps >= AUTO_UPGRADE_FPS) {
        this.highFpsStreak++;
        this.lowFpsStreak = 0;
        if (this.highFpsStreak >= 2) {
          this.highFpsStreak = 0;
          this.applyQuality('high');
        }
      } else {
        this.lowFpsStreak = 0;
        this.highFpsStreak = 0;
      }
    }
  }

  // =========================================================================
  // PUBLIC CONTROLLER API (Studio3DController)
  // =========================================================================

  public runScenario(scenario: ComplexityScenario): void {
    this.markActive();
    this.settlingFast = false;
    this.currentScenario = scenario;
    this.currentStageIndex = 0;
    this.stageElapsedSec = 0;
    this.totalElapsedSec = 0;
    this.stageHandoffTriggered = false;
    this.isCompleted = false;
    this.isPaused = false;
    this.handoffs.clear();
    this.routeRibbonMesh.visible = false;
    this.clearPackets();
    this.movers = {};

    const nextAwake = new Set<AgentId>(scenario.awakeAgents);
    this.awakeSet = nextAwake;
    this.architecture.setAwakeAgents(nextAwake);

    for (const id of ALL_AGENT_IDS) {
      if (!nextAwake.has(id)) {
        this.sendAgentToSleep(id);
      } else {
        this.agentStates[id].isAwake = true;
      }
    }

    if (scenario.stages.length > 0) {
      this.applyStage(scenario.stages[0]);
    }
    this.syncMissionWall();
    this.emitTelemetry();
  }

  public jumpToStage(stageIndex: number): void {
    this.markActive();
    this.settlingFast = false;
    const scenario = this.currentScenario;
    if (!scenario || stageIndex < 0 || stageIndex >= scenario.stages.length) return;

    const wasTrace = this.showFlowHistory;
    this.currentStageIndex = stageIndex;
    this.isCompleted = false;
    this.handoffs.clear();
    this.routeRibbonMesh.visible = false;
    this.clearPackets();
    this.movers = {};

    // Nạp lại các cạnh lịch sử của những bước đã đi qua (0 .. stageIndex-1) ở trạng thái ẩn,
    // để khi người dùng bật "Sơ đồ luồng" luôn thấy đủ toàn bộ lộ trình dù bấm tua tới/lùi!
    const historyEdges: FlowEdge[] = [];
    let elapsedBefore = 0;
    for (let i = 0; i < stageIndex; i++) {
      const st = scenario.stages[i];
      elapsedBefore += st.durationSec;
      if (st.dispatchTargets) {
        const kind: FlowKind =
          st.dispatchTargets.from === 'rag'
            ? 'rag'
            : st.dispatchTargets.from === 'reviewer'
              ? 'approve'
              : 'dispatch';
        for (const to of st.dispatchTargets.toList) {
          historyEdges.push({ from: st.dispatchTargets.from, to, kind, count: 1, label: st.dispatchTargets.label });
        }
      } else if (st.handoff) {
        const kind: FlowKind =
          st.handoff.from === 'rag'
            ? 'rag'
            : st.handoff.from === 'reviewer'
              ? 'approve'
              : st.handoff.to === 'integrator' || st.handoff.to === 'reviewer'
                ? 'result'
                : 'dispatch';
        historyEdges.push({ from: st.handoff.from, to: st.handoff.to, kind, count: 1, label: st.handoff.label });
      }
    }
    if (historyEdges.length > 0) {
      this.flowGraph.syncEdges(historyEdges, (id) => this.robots[id]?.position ?? null, this.elapsedTotal);
    }
    if (wasTrace) this.flowGraph.setTraceMode(true);

    this.totalElapsedSec = elapsedBefore;
    this.applyStage(scenario.stages[stageIndex]);
    this.syncMissionWall();
    this.emitTelemetry();
  }

  public setPaused(paused: boolean): void {
    this.markActive();
    this.isPaused = paused;
    this.emitTelemetry();
  }

  public setWeather(mode: WeatherMode): void {
    this.markActive();
    this.weatherSystem.setMode(mode);
    if (this.renderer.shadowMap.enabled) this.renderer.shadowMap.needsUpdate = true;
    this.emitTelemetry();
  }

  public wakeAgents(ids: AgentId[]): void {
    this.markActive();
    this.settlingFast = false;
    for (const id of ids) {
      this.awakeSet.add(id);
      const profile = AGENT_PROFILES[id];
      this.agentStates[id] = {
        id,
        isAwake: true,
        action: 'waking_up',
        actionText: ACTION_LABELS_VI.waking_up,
        carrying: 'none',
      };
      this.moveAgentTo(id, profile.workPos, profile.workFacingYaw, 'waking_up', profile.workSeated);
    }
    this.architecture.setAwakeAgents(this.awakeSet);
    this.wallDirty = true;
    this.shadowDirty = true;
    this.telemetryDirty = true;
  }

  public putAgentsToSleep(ids: AgentId[]): void {
    this.markActive();
    for (const id of ids) {
      this.awakeSet.delete(id);
      this.sendAgentToSleep(id);
    }
    this.architecture.setAwakeAgents(this.awakeSet);
    this.wallDirty = true;
    this.shadowDirty = true;
    this.telemetryDirty = true;
  }

  /** Đánh thức các Agent được chọn, cho đứng dậy đi ra quây quần quanh Bàn tròn giữa văn phòng (huddle) để họp phản biện. */
  public gatherAtHuddle(ids: AgentId[], speakingId?: AgentId | null, statusText?: string): void {
    this.markActive();
    this.settlingFast = false;
    const unique = Array.from(new Set(ids));
    const total = Math.max(1, unique.length);
    const radius = 1.62;
    unique.forEach((id, idx) => {
      this.awakeSet.add(id);
      const angle = (idx / total) * Math.PI * 2 - Math.PI * 0.35;
      const hx = HUDDLE_CENTER[0] + Math.cos(angle) * radius;
      const hz = HUDDLE_CENTER[1] + Math.sin(angle) * radius;
      const yaw = Math.atan2(HUDDLE_CENTER[0] - hx, HUDDLE_CENTER[1] - hz);
      const isSpeaker = speakingId === id;
      const action: RobotAction = isSpeaker ? 'brainstorming' : 'thinking';
      const label = isSpeaker
        ? (statusText || 'Đang phát biểu tại bàn tròn')
        : 'Đang lắng nghe & chuẩn bị phản biện';
      this.agentStates[id] = {
        id,
        isAwake: true,
        action,
        actionText: label,
        carrying: 'none',
      };
      this.robots[id]?.setCarryItem('none');
      this.moveAgentTo(id, [hx, hz], yaw, action, false);
    });
    this.architecture.setAwakeAgents(this.awakeSet);
    this.wallDirty = true;
    this.shadowDirty = true;
    this.telemetryDirty = true;
  }

  public setAgentAction(
    agentId: AgentId,
    action: RobotAction,
    actionText?: string,
    carryItem?: CarryItemKind,
    spot?: LiveSpot,
  ): void {
    this.markActive();
    const profile = AGENT_PROFILES[agentId];
    const robot = this.robots[agentId];
    if (!robot) return;

    if (action === 'sleeping') {
      this.awakeSet.delete(agentId);
      this.sendAgentToSleep(agentId);
      this.architecture.setAwakeAgents(this.awakeSet);
      this.wallDirty = true;
      this.shadowDirty = true;
      this.telemetryDirty = true;
      return;
    }

    this.awakeSet.add(agentId);
    this.architecture.setAwakeAgents(this.awakeSet);
    this.agentStates[agentId] = {
      id: agentId,
      isAwake: true,
      action,
      actionText: actionText || ACTION_LABELS_VI[action],
      carrying: carryItem ?? this.agentStates[agentId].carrying,
    };
    if (carryItem !== undefined) {
      robot.setCarryItem(carryItem);
    }
    const pose = spot ? LIVE_SPOTS[spot] : null;
    if (pose) this.moveAgentTo(agentId, pose.pos, pose.yaw, action, false);
    else this.moveAgentTo(agentId, profile.workPos, profile.workFacingYaw, action, profile.workSeated);
    this.wallDirty = true;
    this.shadowDirty = true;
    this.telemetryDirty = true;
  }

  public walkAndHandoff(
    from: AgentId,
    to: AgentId,
    item: CarryItemKind,
    label?: string,
    onArrive?: () => void,
  ): void {
    this.markActive();
    const fromRobot = this.robots[from];
    const toRobot = this.robots[to];
    if (!fromRobot || !toRobot) return;

    this.awakeSet.add(from);
    this.awakeSet.add(to);
    this.architecture.setAwakeAgents(this.awakeSet);

    const fromProfile = AGENT_PROFILES[from];
    const toProfile = AGENT_PROFILES[to];

    const startPos: [number, number] = [fromRobot.position.x, fromRobot.position.z];
    const toPos: [number, number] = [toRobot.position.x, toRobot.position.z];

    const dirZ = toPos[1] > 2.2 ? -1 : 1;
    const meetPos: [number, number] = [toPos[0], toPos[1] + dirZ * 0.95];
    const meetYaw = Math.atan2(toPos[0] - meetPos[0], toPos[1] - meetPos[1]);

    const waypoints = computeStudioWalkPath(
      startPos,
      meetPos,
      fromProfile.corridorEntry,
      toProfile.corridorEntry,
    );

    fromRobot.setCarryItem(item);
    this.agentStates[from] = {
      id: from,
      isAwake: true,
      action: 'walking',
      actionText: label || `Mang hồ sơ sang ${toProfile.shortName}`,
      carrying: item,
    };

    const curvePts = [
      new THREE.Vector3(startPos[0], getOfficeFloorY(startPos[1]) + 0.055, startPos[1]),
      ...waypoints.map(([wx, wz]) => new THREE.Vector3(wx, getOfficeFloorY(wz) + 0.055, wz)),
    ];
    if (curvePts.length >= 2) {
      const curve = new THREE.CatmullRomCurve3(curvePts, false, 'catmullrom', 0.15);
      this.routeRibbonMesh.geometry.dispose();
      this.routeRibbonMesh.geometry = new THREE.TubeGeometry(curve, 36, 0.055, 8, false);
      this.routeRibbonMat.color.setHex(fromProfile.accentNumber);
      this.routeRibbonMesh.visible = true;
    }

    this.handoffs.set(from, {
      from,
      to,
      item,
      phase: 'going',
      pauseTimer: 0,
      returnPos: [fromProfile.workPos[0], fromProfile.workPos[1]],
      returnYaw: fromProfile.workFacingYaw,
      returnAction: fromProfile.workSeated ? 'working_computer' : 'idle',
      returnSeated: fromProfile.workSeated,
      onArrive,
    });

    this.movers[from] = {
      waypoints,
      waypointIdx: 0,
      finalYaw: meetYaw,
      finalAction: 'handing_over',
      finalSeated: false,
      onArrive: () => {
        const h = this.handoffs.get(from);
        if (!h) return;
        h.phase = 'passing';
        h.pauseTimer = this.liveTempo === 'realtime' ? 0.3 : 0.72;
        this.agentStates[from].action = 'handing_over';
        this.agentStates[from].actionText = `Bàn giao hồ sơ cho ${toProfile.shortName}`;

        this.agentStates[to].action = 'receiving';
        this.agentStates[to].actionText = `Nhận hồ sơ từ ${fromProfile.shortName}`;
        this.robots[to].setPoseTarget(
          toRobot.position.x,
          toRobot.position.z,
          Math.atan2(meetPos[0] - toPos[0], meetPos[1] - toPos[1]),
          'receiving',
          false,
          toProfile.workSeated,
        );
        this.emitTelemetry();
      },
    };
    this.emitTelemetry();
  }

  /**
   * Chế độ trực tiếp (Đợt 6): đặt Agent đang dẫn việc, hiệu ứng phòng, bảng tường và gói hồ sơ bay theo sự kiện thật.
   * Gọi khi không chạy kịch bản minh họa.
   */
  public setLiveScene(opts: {
    lead?: AgentId | null;
    effects?: Partial<LiveEffects>;
    dispatch?: { from: AgentId; toList: AgentId[] };
    flow?: { kind: FlowKind; label: string };
    wall?: { tierLabel: string; requestTitle: string; stepText: string; progressPct: number };
  }): void {
    this.markActive();
    this.currentScenario = null;
    this.settlingFast = false;
    if (opts.lead !== undefined) {
      this.leadActor = opts.lead;
      this.architecture.setLeadHighlight(opts.lead);
      for (const id of ALL_AGENT_IDS) {
        this.robots[id].setHighlighted(this.hoveredAgent === id, this.selectedAgent === id, id === this.leadActor);
      }
    }
    if (opts.effects) {
      this.liveEffects = { ...this.liveEffects, ...opts.effects };
      this.architecture.setEffects(this.liveEffects);
    }
    if (opts.dispatch) {
      const kind: FlowKind =
        opts.flow?.kind ??
        (opts.dispatch.from === 'rag'
          ? 'rag'
          : opts.dispatch.from === 'reviewer'
            ? 'revise'
            : opts.dispatch.toList[0] === 'integrator' && opts.dispatch.from !== 'orchestrator'
              ? 'result'
              : 'dispatch');
      this.spawnDispatchPackets(opts.dispatch.from, opts.dispatch.toList, kind, opts.flow?.label ?? '');
    }
    if (opts.wall) this.liveWall = opts.wall;
    this.wallDirty = true;
    this.shadowDirty = true;
    this.telemetryDirty = true;
  }

  /** Đặt thẳng mọi robot đang đi bộ tới đúng vị trí cuối cùng, bảo đảm 0 robot còn di chuyển thừa sau khi lượt chạy kết thúc. */
  private snapAllMoversToFinal(): void {
    for (const id of ALL_AGENT_IDS) {
      const m = this.movers[id];
      if (!m) continue;
      delete this.movers[id];
      const robot = this.robots[id];
      const last = m.waypoints[m.waypoints.length - 1];
      if (robot && last) {
        robot.position.x = last[0];
        robot.position.z = last[1];
        robot.setPoseTarget(last[0], last[1], m.finalYaw, m.finalAction, false, m.finalSeated);
      }
    }
  }

  /** Chốt nhanh đồng bộ khi backend đã trả kết quả: hủy lập tức mọi chuyến đi trao hồ sơ & mover đang dở, tắt sạch sợi dây 3D thừa và đưa robot phụ về nghỉ. */
  public settle(): void {
    this.markActive(1500);
    this.settlingFast = true;
    this.flowGraph.fastSettle();
    this.routeRibbonMesh.visible = false;
    // Hủy sạch mọi chuyến đi bộ trao hồ sơ đang dở (tránh cảnh Integrator gửi câu trả lời xong mà RAG vẫn đang đi đưa tài liệu!)
    const pendingHandoffs = [...this.handoffs.values()];
    this.handoffs.clear();
    for (const h of pendingHandoffs) {
      delete this.movers[h.from];
      this.robots[h.from]?.setCarryItem('none');
      if (this.agentStates[h.from]) this.agentStates[h.from].carrying = 'none';
      h.onArrive?.();
    }
    // Chốt thẳng toàn bộ movers vừa được tạo (kể cả putAgentsToSleep gọi trước settle) về đích cuối — 0 robot đi lết sau khi xong!
    this.snapAllMoversToFinal();
    // Đóng tủ RAG & tắt biểu đồ phụ nếu đang bật
    this.liveEffects = { ...this.liveEffects, cabinetOpen: false, analystChartActive: false };
    this.architecture.setEffects(this.liveEffects);
    // Bật biểu cảm hài lòng (cười híp squint V12) cho Integrator & các Agent vừa hoàn thành
    for (const id of this.awakeSet) {
      this.robots[id]?.triggerReaction?.('happy', id === 'integrator' ? 2.2 : 1.4);
    }
    this.emitFlowLogs();
    this.emitTelemetry();
  }

  /** Phục vụ kiểm thử tự động xác nhận 0 robot còn di chuyển thừa sau settle(). */
  public getPendingMotionCount(): { movers: number; handoffs: number } {
    return { movers: Object.keys(this.movers).length, handoffs: this.handoffs.size };
  }

  private showFlowHistory = false;

  /** Bật/tắt chế độ xem lại toàn bộ sơ đồ sợi dây lịch sử của lượt chạy (mặc định tắt để cảnh 3D thoáng sạch). */
  public setShowFlowHistory(show: boolean): void {
    this.showFlowHistory = show;
    this.flowGraph.setTraceMode(show);
    this.markActive(1800);
  }

  /** Đồng bộ đồ thị luồng 3D từ LiveState.edges (lưu sẵn để bật khi người dùng xem Sơ đồ luồng, không tự giăng dây thừa khi xong). */
  public syncFlowEdges(edges: FlowEdge[], _finished = false): void {
    this.flowGraph.syncEdges(edges, (id) => this.robots[id]?.position ?? null, this.elapsedTotal);
    this.emitFlowLogs();
    this.markActive(1000);
  }

  /** V10: đồng bộ 1:1 danh sách Agent đang thực sự làm việc — tắt ngay luồng nối của Agent đã xong việc, giữ nhiều luồng khi chạy song song. */
  public syncActiveWorkers(activeWorkers: AgentId[], finished = false): void {
    this.flowGraph.syncActiveWorkers(new Set(activeWorkers), finished, this.elapsedTotal);
    this.emitFlowLogs();
    this.markActive(1000);
  }

  /** Đưa các chỉ số điều phối thật (số việc, khử trùng lặp, sóng song song, đoạn RAG, QC) lên bảng tường. */
  public setWallMetrics(metrics: LiveMetrics | null): void {
    this.wallMetrics = metrics;
    this.wallDirty = true;
    this.markActive(600);
  }

  public setFollowLeadAgent(follow: boolean): void {
    this.markActive();
    this.followLeadAgent = follow;
  }

  public setCameraPreset(preset: CameraPresetId): void {
    this.markActive();
    this.followLeadAgent = false;
    if (
      preset === 'overview' ||
      preset === 'huddle' ||
      preset === 'core_studio' ||
      preset === 'specialist_row' ||
      preset === 'rag_analyst' ||
      preset === 'city_exterior' ||
      preset === 'campus_sports' ||
      preset === 'campus_gate' ||
      preset === 'campus_gdqp'
    ) {
      this.lastPreset = preset;
      if (
        preset === 'city_exterior' ||
        preset === 'campus_sports' ||
        preset === 'campus_gate' ||
        preset === 'campus_gdqp'
      ) {
        this.ensureCampusLoaded();
      }
      const cfg = CAMERA_PRESETS[preset];
      if (preset === 'overview') this.overviewGoal(this.cameraGoalPos, this.cameraGoalTarget);
      else {
        this.cameraGoalPos.set(...cfg.pos);
        this.cameraGoalTarget.set(...cfg.target);
      }
      this.cameraLerpActive = true;
      return;
    }

    const robot = this.robots[preset];
    if (robot) {
      this.lastPreset = preset;
      const rx = robot.position.x;
      const rz = robot.position.z;
      this.cameraGoalTarget.set(rx, 0.8, rz);
      this.cameraGoalPos.set(rx + 1.6, 4.0, rz + 4.3);
      this.cameraLerpActive = true;
    }
  }

  /** Nhịp diễn của chế độ trực tiếp/xem lại: 'realtime' bám sát sự kiện (đi nhanh, nhảy khi bị cắt ngang), 'easy' như cũ. */
  public setLiveTempo(tempo: 'realtime' | 'easy'): void {
    this.liveTempo = tempo;
  }

  public setSpeed(multiplier: number): void {
    this.markActive();
    this.speedMultiplier = Math.max(0.5, Math.min(6, multiplier));
  }

  public resetToSleep(): void {
    this.markActive();
    this.currentScenario = null;
    this.liveWall = null;
    this.wallMetrics = null;
    this.settlingFast = false;
    this.liveEffects = { ...NO_EFFECTS };
    this.currentStageIndex = 0;
    this.stageElapsedSec = 0;
    this.totalElapsedSec = 0;
    this.isCompleted = false;
    this.isPaused = false;
    this.handoffs.clear();
    this.routeRibbonMesh.visible = false;
    this.clearPackets();
    this.movers = {};
    this.leadActor = null;
    this.awakeSet.clear();
    this.architecture.setAwakeAgents(this.awakeSet);
    this.architecture.setLeadHighlight(null);
    this.architecture.setEffects({
      requestArrived: false,
      cabinetOpen: false,
      whiteboardCards: 0,
      analystChartActive: false,
      qcApproved: false,
      finalReportReady: false,
    });

    for (const id of ALL_AGENT_IDS) {
      this.sendAgentToSleep(id);
      this.robots[id].setHighlighted(false, false, false);
    }
    this.syncMissionWall();
    this.emitTelemetry();
  }

  public dispose(): void {
    this.disposed = true;
    this.intersection?.disconnect();
    document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    if (this.envInitHandle !== null) {
      window.clearTimeout(this.envInitHandle);
      this.envInitHandle = null;
    }
    if (this.campusIdleHandle !== null) {
      const w = window as unknown as { cancelIdleCallback?: (id: number) => void };
      if (typeof w.cancelIdleCallback === 'function') w.cancelIdleCallback(this.campusIdleHandle);
      else window.clearTimeout(this.campusIdleHandle);
      this.campusIdleHandle = null;
    }
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.resizeRafId !== null) {
      cancelAnimationFrame(this.resizeRafId);
      this.resizeRafId = null;
    }
    this.resizeObserver.disconnect();
    this.renderer.domElement.removeEventListener('pointermove', this.handlePointerMove);
    this.renderer.domElement.removeEventListener('pointerdown', this.handlePointerDown);
    this.renderer.domElement.removeEventListener('pointerup', this.handlePointerUp);
    this.renderer.domElement.removeEventListener('wheel', this.handleWheel);
    this.controls.dispose();

    this.flowGraph.dispose();
    this.routeRibbonMesh.geometry.dispose();
    this.routeRibbonMat.dispose();
    for (const id of ALL_AGENT_IDS) {
      this.robots[id].dispose();
    }
    this.weatherSystem.dispose();
    this.cityEnv?.dispose();
    this.architecture.dispose();
    this.materials.dispose();
    this.textures.dispose();
    this.envRT?.dispose();
    this.pmremGenerator?.dispose();
    this.renderer.dispose();
    if (this.renderer.domElement.parentElement === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
  }

  // =========================================================================
  // INTERNAL STAGE, DISPATCH PACKETS & MOVEMENT CHOREOGRAPHY
  // =========================================================================

  private clearPackets(): void {
    this.flowGraph.clear();
    if (this.lastFlowBadgeSig) {
      this.lastFlowBadgeSig = '';
      this.callbacks.onFlowBadgesUpdated?.([]);
    }
    this.emitFlowLogs();
  }

  private emitFlowLogs(): void {
    if (!this.callbacks.onFlowLogsUpdated) return;
    const logs = this.flowGraph.getRecentLogs(4);
    const sig = logs.map((l) => `${l.id}:${l.label}:${+l.active}`).join('|');
    if (sig !== this.lastFlowLogSig) {
      this.lastFlowLogSig = sig;
      this.callbacks.onFlowLogsUpdated(logs);
    }
  }

  private spawnDispatchPackets(
    fromId: AgentId,
    toIds: AgentId[],
    kind: FlowKind = 'dispatch',
    label = '',
  ): void {
    const fromRobot = this.robots[fromId];
    if (!fromRobot) return;
    for (let i = 0; i < toIds.length; i++) {
      const toId = toIds[i];
      const target = this.robots[toId];
      if (!target || toId === fromId) continue;
      this.flowGraph.emitFlow(
        fromId,
        toId,
        fromRobot.position,
        target.position,
        kind,
        label,
        this.elapsedTotal,
      );
      // Tương tác tự nhiên: Agent gửi và Agent nhận xoay đầu nhìn về nhau khi trao đổi
      fromRobot.lookAtWorld?.(target.position.x, target.position.z, 1.1);
      target.lookAtWorld?.(fromRobot.position.x, fromRobot.position.z, 1.3);
    }
    this.emitFlowLogs();
    this.markActive(3800);
  }

  private sendAgentToSleep(id: AgentId): void {
    const profile = AGENT_PROFILES[id];
    const robot = this.robots[id];
    robot.setCarryItem('none');
    this.agentStates[id] = {
      id,
      isAwake: false,
      action: 'sleeping',
      actionText: 'Zzz',
      carrying: 'none',
    };
    this.moveAgentTo(
      id,
      profile.sleepPos,
      profile.sleepFacingYaw,
      'sleeping',
      profile.sleepSeated,
    );
  }

  private moveAgentTo(
    id: AgentId,
    destPos: [number, number],
    destYaw: number,
    finalAction: RobotAction,
    finalSeated: boolean,
  ): void {
    const robot = this.robots[id];
    const profile = AGENT_PROFILES[id];
    if (this.handoffs.has(id) && this.handoffs.get(id)!.phase !== 'returning') {
      this.handoffs.delete(id);  // bị gọi đi việc khác (ngủ, lượt mới) giữa đường: bỏ tuyến trao, không treo
      robot.setCarryItem('none');
      if (this.handoffs.size === 0) this.routeRibbonMesh.visible = false;
    }
    const old = this.movers[id];
    if (this.liveTempo === 'realtime' && old) {
      // bước trước quá ngắn, robot chưa tới nơi: đặt thẳng tới đích cũ để cảnh không trễ sau sự kiện
      const last = old.waypoints[old.waypoints.length - 1];
      if (last) { robot.position.x = last[0]; robot.position.z = last[1]; robot.setPoseTarget(last[0], last[1], old.finalYaw, old.finalAction, false, old.finalSeated); }
      delete this.movers[id];
    }
    const curX = robot.position.x;
    const curZ = robot.position.z;
    const dist = Math.hypot(destPos[0] - curX, destPos[1] - curZ);

    if (this.settlingFast || dist < 0.35) {
      delete this.movers[id];
      if (this.settlingFast) {
        robot.position.x = destPos[0];
        robot.position.z = destPos[1];
      }
      robot.setPoseTarget(destPos[0], destPos[1], destYaw, finalAction, false, finalSeated);
      return;
    }

    const destCorridorEntry: [number, number] =
      destPos[1] > 2.5 ? [destPos[0], 2.85] : [destPos[0], 1.0];
    const waypoints = computeStudioWalkPath(
      [curX, curZ],
      destPos,
      profile.corridorEntry,
      destCorridorEntry,
    );

    this.movers[id] = {
      waypoints,
      waypointIdx: 0,
      finalYaw: destYaw,
      finalAction,
      finalSeated,
    };
  }

  private applyStage(stage: ActivityStage): void {
    this.stageElapsedSec = 0;
    this.stageHandoffTriggered = false;
    this.leadActor = stage.leadActor;
    this.architecture.setLeadHighlight(stage.leadActor);
    this.architecture.setEffects({
      requestArrived: Boolean(stage.effects?.requestArrived),
      cabinetOpen: Boolean(stage.effects?.cabinetOpen),
      whiteboardCards: stage.effects?.whiteboardCards ?? 0,
      analystChartActive: Boolean(stage.effects?.analystChartActive),
      qcApproved: Boolean(stage.effects?.qcApproved),
      finalReportReady: Boolean(stage.effects?.finalReportReady),
    });

    for (const id of ALL_AGENT_IDS) {
      this.robots[id].setHighlighted(
        this.hoveredAgent === id,
        this.selectedAgent === id,
        id === this.leadActor,
      );
    }

    if (stage.dispatchTargets) {
      const dKind: FlowKind =
        stage.dispatchTargets.from === 'rag'
          ? 'rag'
          : stage.dispatchTargets.from === 'reviewer'
            ? 'approve'
            : 'dispatch';
      this.spawnDispatchPackets(
        stage.dispatchTargets.from,
        stage.dispatchTargets.toList,
        dKind,
        stage.dispatchTargets.label,
      );
    } else if (stage.handoff) {
      const hKind: FlowKind =
        stage.handoff.from === 'rag'
          ? 'rag'
          : stage.handoff.from === 'reviewer'
            ? 'approve'
            : stage.handoff.to === 'integrator' || stage.handoff.to === 'reviewer'
              ? 'result'
              : 'dispatch';
      this.spawnDispatchPackets(
        stage.handoff.from,
        [stage.handoff.to],
        hKind,
        stage.handoff.label,
      );
    }

    const huddleAgents = stage.agentDirectives
      .filter((d) => d.targetSpot === 'huddle')
      .map((d) => d.agentId);

    for (const directive of stage.agentDirectives) {
      const id = directive.agentId;
      const profile = AGENT_PROFILES[id];
      const robot = this.robots[id];
      const isSleeping = directive.action === 'sleeping';

      this.agentStates[id] = {
        id,
        isAwake: !isSleeping,
        action: directive.action,
        actionText: isSleeping ? 'Zzz' : directive.actionText,
        carrying: directive.carryItem ?? 'none',
      };
      robot.setCarryItem(directive.carryItem ?? 'none');

      if (isSleeping) {
        this.moveAgentTo(
          id,
          profile.sleepPos,
          profile.sleepFacingYaw,
          'sleeping',
          profile.sleepSeated,
        );
        continue;
      }

      let targetPos: [number, number] = profile.workPos;
      let targetYaw = profile.workFacingYaw;
      let seated = profile.workSeated;

      if (directive.targetSpot === 'whiteboard') {
        targetPos = [WHITEBOARD_SPOT[0], WHITEBOARD_SPOT[1]];
        targetYaw = Math.PI;
        seated = false;
      } else if (directive.targetSpot === 'reception') {
        targetPos = [RECEPTION_SPOT[0], RECEPTION_SPOT[1]];
        targetYaw = 0;
        seated = false;
      } else if (directive.targetSpot === 'cabinet') {
        targetPos = [CABINET_SPOT[0], CABINET_SPOT[1]];
        targetYaw = Math.PI;
        seated = false;
      } else if (directive.targetSpot === 'easel') {
        targetPos = [ANALYST_EASEL_SPOT[0], ANALYST_EASEL_SPOT[1]];
        targetYaw = Math.PI;
        seated = false;
      } else if (directive.targetSpot === 'huddle') {
        const idx = Math.max(0, huddleAgents.indexOf(id));
        const total = Math.max(1, huddleAgents.length);
        const angle = (idx / total) * Math.PI * 2 - Math.PI * 0.35;
        const radius = 1.48;
        const hx = HUDDLE_CENTER[0] + Math.cos(angle) * radius;
        const hz = HUDDLE_CENTER[1] + Math.sin(angle) * radius;
        targetPos = [hx, hz];
        targetYaw = Math.atan2(HUDDLE_CENTER[0] - hx, HUDDLE_CENTER[1] - hz);
        seated = false;
      } else if (directive.targetSpot && directive.targetSpot !== 'home') {
        const other = AGENT_PROFILES[directive.targetSpot];
        if (other) {
          targetPos = [
            other.workPos[0],
            other.workPos[1] + (other.workPos[1] > 2.2 ? -0.95 : 0.95),
          ];
          targetYaw = Math.atan2(
            other.workPos[0] - targetPos[0],
            other.workPos[1] - targetPos[1],
          );
          seated = false;
        }
      }

      this.moveAgentTo(id, targetPos, targetYaw, directive.action, seated);
    }

    this.syncMissionWall();
    this.emitTelemetry();
  }

  private syncMissionWall(): void {
    const scenario = this.currentScenario;
    const stage = scenario?.stages[this.currentStageIndex];
    const awakeIds: AgentId[] = [];
    for (const id of ALL_AGENT_IDS) {
      if (this.agentStates[id].isAwake) awakeIds.push(id);
    }
    const awakeCount = awakeIds.length;
    const pct =
      scenario && scenario.targetDurationSec > 0
        ? (this.totalElapsedSec / scenario.targetDurationSec) * 100
        : 0;

    if (!scenario && this.liveWall) {
      this.textures.updateMissionWall({
        ...this.liveWall,
        awakeCount,
        sleepingCount: ALL_AGENT_IDS.length - awakeCount,
        awakeIds,
        steps: this.wallSteps,
        metrics: this.wallMetrics,
      });
      return;
    }
    const steps = scenario?.stages.map((st, idx) => ({
      label: st.stepLabel,
      state: (this.isCompleted || idx < this.currentStageIndex ? 'done' : idx === this.currentStageIndex ? 'now' : 'todo') as WallStepState,
    }));
    this.textures.updateMissionWall({
      tierLabel: scenario?.tierLabelVi ?? 'Chế độ nghỉ',
      requestTitle: scenario?.requestTitle ?? 'Đang chờ tiếp nhận câu hỏi mới...',
      stepText: this.isCompleted
        ? 'Hoàn tất bàn giao quyển báo cáo cuối cùng'
        : stage?.headline ?? 'Chọn mức độ khó ở thanh điều khiển bên dưới',
      progressPct: this.isCompleted ? 100 : pct,
      awakeCount,
      sleepingCount: ALL_AGENT_IDS.length - awakeCount,
      awakeIds,
      steps,
    });
  }

  /** Lượt thật (trực tiếp / xem lại): danh sách bước chiếu lên TV văn phòng. */
  public setWallSteps(steps: { label: string; state: WallStepState }[]): void {
    this.wallSteps = steps;
    this.syncMissionWall();
    this.markActive(600);
  }

  private updateScenario(dt: number): void {
    const scenario = this.currentScenario;
    if (!scenario || this.isCompleted || this.isPaused) return;

    const scaledDt = dt * this.speedMultiplier;
    this.stageElapsedSec += scaledDt;
    this.totalElapsedSec = Math.min(
      scenario.targetDurationSec,
      this.totalElapsedSec + scaledDt,
    );

    const stage = scenario.stages[this.currentStageIndex];
    if (!stage) return;

    if (
      stage.handoff &&
      !this.stageHandoffTriggered &&
      this.stageElapsedSec >= stage.durationSec * 0.42
    ) {
      this.stageHandoffTriggered = true;
      const hKind: FlowKind =
        stage.handoff.from === 'rag'
          ? 'rag'
          : stage.handoff.from === 'reviewer'
            ? 'approve'
            : stage.handoff.to === 'integrator'
              ? 'result'
              : 'dispatch';
      this.spawnDispatchPackets(stage.handoff.from, [stage.handoff.to], hKind, stage.handoff.label);
      this.walkAndHandoff(
        stage.handoff.from,
        stage.handoff.to,
        stage.handoff.item,
        stage.handoff.label,
      );
    }

    if (this.stageElapsedSec >= stage.durationSec) {
      if (this.currentStageIndex + 1 < scenario.stages.length) {
        this.currentStageIndex += 1;
        this.applyStage(scenario.stages[this.currentStageIndex]);
      } else {
        this.isCompleted = true;
        this.totalElapsedSec = scenario.targetDurationSec;
        this.routeRibbonMesh.visible = false;
        this.handoffs.clear();
        this.snapAllMoversToFinal();
        this.flowGraph.fastSettle();
        this.leadActor = 'integrator';
        this.architecture.setLeadHighlight('integrator');
        for (const id of scenario.awakeAgents) {
          this.agentStates[id].action = 'completed';
          this.agentStates[id].actionText =
            id === 'integrator' ? 'Đã bàn giao báo cáo hoàn chỉnh' : 'Hoàn thành nhiệm vụ';
          this.robots[id]?.triggerReaction?.('happy', id === 'integrator' ? 2.4 : 1.6);
        }
        this.emitFlowLogs();
        this.syncMissionWall();
        this.emitTelemetry();
      }
    }
  }

  private updatePackets(dt: number): void {
    this.flowGraph.update(dt, this.elapsedTotal, this.speedMultiplier, (from, to, kind) => {
      // Phản ứng biểu cảm & tương tác thực tế khi gói hồ sơ tới đích
      const fromPos = this.robots[from]?.position;
      if (fromPos) {
        this.robots[to]?.lookAtWorld?.(fromPos.x, fromPos.z, 1.0);
      }
      if (kind === 'revise' || kind === 'fail') {
        this.robots[to]?.triggerReaction?.('worried', 2.0);
      } else if (kind === 'approve') {
        this.robots[to]?.triggerReaction?.('happy', 1.7);
      }
      this.emitFlowLogs();
    });
  }

  private updateMoversAndHandoff(dt: number): void {
    const settleBoost = this.settlingFast ? 4.2 : 1;
    const walkSpeed =
      4.2 *
      Math.min(2.6, Math.max(1, this.speedMultiplier * 0.85)) *
      (this.liveTempo === 'realtime' ? 1.8 : 1) *
      settleBoost;

    for (const h of [...this.handoffs.values()]) {
      if (h.phase !== 'passing') continue;
      h.pauseTimer -= dt * Math.max(1, this.speedMultiplier * 0.75);
      if (h.pauseTimer <= 0) {
        this.robots[h.from].setCarryItem('none');
        this.robots[h.to].setCarryItem(h.item);
        this.agentStates[h.from].carrying = 'none';
        this.agentStates[h.to].carrying = h.item;
        if (this.handoffs.size === 1) this.routeRibbonMesh.visible = false;
        h.phase = 'returning';
        this.handoffs.delete(h.from);
        this.moveAgentTo(h.from, h.returnPos, h.returnYaw, h.returnAction, h.returnSeated);
        h.onArrive?.();  // sau khi đặt đường về: lệnh của chế độ trực tiếp (nếu có) được ưu tiên
        this.emitTelemetry();
      }
    }

    for (const id of ALL_AGENT_IDS) {
      const mover = this.movers[id];
      if (!mover) continue;

      const robot = this.robots[id];
      const wp = mover.waypoints[mover.waypointIdx];
      if (!wp) {
        delete this.movers[id];
        continue;
      }

      const dx = wp[0] - robot.position.x;
      const dz = wp[1] - robot.position.z;
      const dist = Math.hypot(dx, dz);

      if (dist <= walkSpeed * dt + 0.06) {
        robot.setPoseTarget(wp[0], wp[1], mover.finalYaw, 'walking', true, false);
        mover.waypointIdx += 1;
        if (mover.waypointIdx >= mover.waypoints.length) {
          const { finalYaw, finalAction, finalSeated, onArrive } = mover;
          delete this.movers[id];
          robot.setPoseTarget(wp[0], wp[1], finalYaw, finalAction, false, finalSeated);
          onArrive?.();
        }
      } else {
        const step = (walkSpeed * dt) / dist;
        const nx = robot.position.x + dx * step;
        const nz = robot.position.z + dz * step;
        const yaw = Math.atan2(dx, dz);
        robot.setPoseTarget(nx, nz, yaw, 'walking', true, false);
      }
    }
  }

  private updateCamera(dt: number): void {
    if (this.followLeadAgent && this.leadActor) {
      const robot = this.robots[this.leadActor];
      if (robot) {
        this.cameraGoalTarget.set(robot.position.x, 0.8, robot.position.z);
        this.cameraGoalPos.set(robot.position.x + 2.0, 5.2, robot.position.z + 5.5);
        this.controls.target.lerp(this.cameraGoalTarget, 1 - Math.exp(-4.2 * dt));
        this.camera.position.lerp(this.cameraGoalPos, 1 - Math.exp(-3.4 * dt));
      }
    } else if (this.cameraLerpActive) {
      const alpha = 1 - Math.exp(-5.5 * dt);
      this.camera.position.lerp(this.cameraGoalPos, alpha);
      this.controls.target.lerp(this.cameraGoalTarget, alpha);
      if (
        this.camera.position.distanceTo(this.cameraGoalPos) < 0.06 &&
        this.controls.target.distanceTo(this.cameraGoalTarget) < 0.06
      ) {
        this.cameraLerpActive = false;
      }
    } else {
      const isLandmarkPreset =
        this.lastPreset === 'campus_sports' ||
        this.lastPreset === 'campus_gate' ||
        this.lastPreset === 'campus_gdqp';
      // Giữ tâm xoay trên mặt sân khuôn viên ĐH Duy Tân (điểm mốc cận cảnh cho phép tâm thấp gần mặt đường -12.5m)
      const minTargetY = isLandmarkPreset ? -12.5 : -9.0;
      if (this.controls.target.y < minTargetY) {
        this.controls.target.y = minTargetY;
      }
      const curDist = this.camera.position.distanceTo(this.controls.target);
      // Tăng độ nhạy con lăn khi ở ngoài không gian rộng ĐH Duy Tân, giữ êm đằm khi ở trong phòng
      this.controls.zoomSpeed = curDist > 34 ? 1.85 : 1.45;
      const isZoomingIn = curDist < this.prevCamDist - 0.015;
      const t = this.controls.target;
      const targetOutsideOffice =
        Math.abs(t.x) > 6.5 || t.y < -0.15 || t.y > 2.4 || Math.abs(t.z) > 5.5;

      // Giữ nguyên hành vi lăn chuột như cũ khi từ toàn cảnh zoom về Văn phòng Agent;
      // nhưng khi người dùng đang xem điểm mốc cụ thể ngoài trường (Khu thể thao / Cổng / GDQP&AN), KHÔNG tự kéo tâm về Nhà G!
      if (!isLandmarkPreset && !this.isPointerDragging && ((curDist < 54 && targetOutsideOffice) || (isZoomingIn && curDist < 54 && this.exteriorReveal > 0.02))) {
        const homeWeight = THREE.MathUtils.clamp((54.0 - curDist) / 20.0, 0.05, 1.0);
        const recenterAlpha = 1 - Math.exp(-(2.4 + homeWeight * 9.5) * dt);
        this.controls.target.lerp(this.studioHomeTarget, recenterAlpha);
        if (this.camera.position.y < 4.5 && curDist > 18) {
          this.camera.position.y = THREE.MathUtils.damp(
            this.camera.position.y,
            5.2 + homeWeight * 2.2,
            4.5,
            dt,
          );
        }
      }
      this.prevCamDist = curDist;
    }
    this.controls.update();
  }

  private emitProjectedAnchors(): void {
    if (!this.callbacks.onAnchorsUpdated) return;
    // Dùng kích thước đã cache từ ResizeObserver: loại 100% forced synchronous layout reflow mỗi khung hình khi lăn chuột!
    const w = this.viewportWidth;
    const h = this.viewportHeight;
    if (w <= 0 || h <= 0) return;

    const hideForCityView = this.exteriorReveal > 0.22;
    if (hideForCityView && this.lastFlowBadgeSig) {
      this.lastFlowBadgeSig = '';
      this.lastFlowBadgeContentSig = '';
      this.callbacks.onFlowBadgesUpdated?.([]);
    }
    if (hideForCityView && this.anchorsHiddenForCity) return;
    this.anchorsHiddenForCity = hideForCityView;

    this.projectedAnchors.length = 0;
    for (const id of ALL_AGENT_IDS) {
      const robot = this.robots[id];
      const state = this.agentStates[id];
      robot.getLabelAnchorWorld(this.tempVec3);
      this.tempVec3.project(this.camera);

      const visible =
        !hideForCityView &&
        this.tempVec3.z >= -1 &&
        this.tempVec3.z <= 1 &&
        this.tempVec3.x >= -1.04 &&
        this.tempVec3.x <= 1.04 &&
        this.tempVec3.y >= -1.04 &&
        this.tempVec3.y <= 1.04;

      this.projectedAnchors.push({
        id,
        x: (this.tempVec3.x * 0.5 + 0.5) * w,
        y: (-this.tempVec3.y * 0.5 + 0.5) * h,
        visible,
        isAwake: state.isAwake,
        isLead: this.leadActor === id,
        action: state.action,
        actionText: state.actionText,
        carrying: state.carrying,
      });
    }
    // chỉ báo React khi nhãn đổi nội dung/trạng thái; khi lăn chuột/xoay camera chỉ dời trực tiếp DOM transform
    const sig = this.projectedAnchors.map((p) => `${+p.visible}${+p.isAwake}${+p.isLead}${p.actionText}`).join('|');
    const posSig = this.projectedAnchors.map((p) => `${Math.round(p.x)},${Math.round(p.y)}`).join('|');
    if (sig !== this.lastAnchorSig || posSig !== this.lastAnchorPosSig) {
      const contentChanged = sig !== this.lastAnchorSig || !this.callbacks.onAnchorsMoved;
      this.lastAnchorSig = sig;
      this.lastAnchorPosSig = posSig;
      if (contentChanged) this.callbacks.onAnchorsUpdated([...this.projectedAnchors]);
      else this.callbacks.onAnchorsMoved?.(this.projectedAnchors);
    }

    // Nhãn đường nối ngắn gọn (tối đa 3 luồng đang nóng; tách đường đi DOM transform riêng để lăn chuột 0 React re-render!)
    if (this.callbacks.onFlowBadgesUpdated) {
      const badges = hideForCityView
        ? []
        : this.flowGraph.projectBadges(this.camera, w, h, this.elapsedTotal);
      const contentSig = badges.map((b) => `${b.key}:${b.label}:${+b.active}`).join('|');
      const posBadgeSig = badges.map((b) => `${Math.round(b.x)},${Math.round(b.y)}`).join('|');
      if (contentSig !== this.lastFlowBadgeContentSig || posBadgeSig !== this.lastFlowBadgeSig) {
        const badgesContentChanged = contentSig !== this.lastFlowBadgeContentSig || !this.callbacks.onFlowBadgesMoved;
        this.lastFlowBadgeContentSig = contentSig;
        this.lastFlowBadgeSig = posBadgeSig;
        if (badgesContentChanged) this.callbacks.onFlowBadgesUpdated(badges);
        else this.callbacks.onFlowBadgesMoved?.(badges);
      }
    }
  }

  private emitTelemetry(): void {
    const scenario = this.currentScenario;
    const stage = scenario?.stages[this.currentStageIndex];

    let awakeCount = 0;
    for (const id of ALL_AGENT_IDS) {
      if (this.agentStates[id].isAwake) awakeCount += 1;
    }

    const agentsClone = {} as Record<AgentId, AgentRuntimeState>;
    for (const id of ALL_AGENT_IDS) {
      agentsClone[id] = { ...this.agentStates[id] };
    }

    this.callbacks.onTelemetry({
      scenarioId: scenario?.id ?? null,
      tier: scenario?.tier ?? null,
      tierLabelVi: scenario?.tierLabelVi ?? 'Chế độ nghỉ chờ lệnh',
      requestTitle: scenario?.requestTitle ?? 'Tất cả Agent đang ngủ chờ yêu cầu mới',
      elapsedSec: this.totalElapsedSec,
      totalDurationSec: scenario?.targetDurationSec ?? 0,
      stageIndex: this.currentStageIndex,
      totalStages: scenario?.stages.length ?? 0,
      stagesSummary:
        scenario?.stages.map((st) => ({
          id: st.id,
          stepLabel: st.stepLabel,
          headline: st.headline,
          leadActor: st.leadActor,
        })) ?? [],
      headline: this.isCompleted
        ? 'Hoàn tất quy trình & đã bàn giao quyển báo cáo'
        : stage?.headline ?? 'Văn phòng AI sẵn sàng',
      detail: this.isCompleted
        ? 'Tất cả Agent tham gia đã hoàn thành. Bấm từng bước ở trên để xem lại hoặc chọn kịch bản khác.'
        : stage?.detail ?? 'Chọn một kịch bản độ khó ở thanh điều khiển phía dưới.',
      leadActor: this.leadActor,
      awakeCount,
      sleepingCount: ALL_AGENT_IDS.length - awakeCount,
      isCompleted: this.isCompleted,
      isPaused: this.isPaused,
      weather: this.weatherSystem.getMode(),
      agents: agentsClone,
    });
  }

  private updatePointerNdc(e: PointerEvent): void {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointerNdc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointerNdc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
  }

  private pickAgent(): AgentId | null {
    this.raycaster.setFromCamera(this.pointerNdc, this.camera);
    const targets: THREE.Object3D[] = [
      ...ALL_AGENT_IDS.map((id) => this.robots[id].collider),
      ...this.architecture.stationColliders,
    ];
    const hits = this.raycaster.intersectObjects(targets, false);
    if (hits.length > 0) {
      return (hits[0].object.userData.agentId as AgentId) ?? null;
    }
    return null;
  }

  private handlePointerMove = (e: PointerEvent): void => {
    // Bỏ qua raycast khi đang kéo xoay camera hoặc đang quan sát toàn cảnh ĐH Duy Tân bên ngoài
    if (this.exteriorReveal > 0.35 || e.buttons !== 0) {
      if (this.hoveredAgent !== null) {
        this.hoveredAgent = null;
        this.renderer.domElement.style.cursor = 'grab';
        for (const id of ALL_AGENT_IDS) {
          this.robots[id].setHighlighted(false, this.selectedAgent === id, this.leadActor === id);
        }
      }
      return;
    }
    this.updatePointerNdc(e);
    const hit = this.pickAgent();
    if (hit !== this.hoveredAgent) {
      this.hoveredAgent = hit;
      this.renderer.domElement.style.cursor = hit ? 'pointer' : 'grab';
      for (const id of ALL_AGENT_IDS) {
        this.robots[id].setHighlighted(
          this.hoveredAgent === id,
          this.selectedAgent === id,
          this.leadActor === id,
        );
      }
    }
  };

  private handleWheel = (): void => {
    this.userInteractingUntil = performance.now() + 450;
    this.markActive(1500);
  };

  private handlePointerDown = (e: PointerEvent): void => {
    this.userInteractingUntil = performance.now() + 500;
    this.markActive();
    this.pointerDownPos = { x: e.clientX, y: e.clientY };
  };

  private handlePointerUp = (e: PointerEvent): void => {
    const moved = Math.hypot(e.clientX - this.pointerDownPos.x, e.clientY - this.pointerDownPos.y);
    if (moved > 6) return;
    this.updatePointerNdc(e);
    const hit = this.pickAgent();
    this.selectedAgent = hit;
    for (const id of ALL_AGENT_IDS) {
      this.robots[id].setHighlighted(
        this.hoveredAgent === id,
        this.selectedAgent === id,
        this.leadActor === id,
      );
    }
    this.callbacks.onSelectAgent(hit);
    if (hit) {
      this.setCameraPreset(hit);
    }
  };

  private scheduleResize(): void {
    if (this.disposed || this.resizeRafId !== null) return;
    this.resizeRafId = requestAnimationFrame(() => {
      this.resizeRafId = null;
      this.handleResize();
    });
  }

  private handleResize(): void {
    if (this.disposed) return;
    const width = Math.max(this.container.clientWidth, 1);
    const height = Math.max(this.container.clientHeight, 1);
    this.viewportWidth = width;
    this.viewportHeight = height;
    this.camera.aspect = width / height;
    const before = this.viewFit;
    this.applyViewFit();
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
    // đang ở toàn cảnh mà tỉ lệ khung đổi (mở bảng cạnh ô chat, kéo rộng hẹp): bay lại toàn cảnh cho vừa khung mới
    if (this.lastPreset === 'overview' && Math.abs(before - this.viewFit) > 0.02 && width > 1 && height > 1) this.setCameraPreset('overview');
    // Khi quay lại tab Văn phòng Agent (từ hidden=true -> false): đánh thức vòng lặp vẽ tức thì, không trễ khung nào
    if (width > 1 && height > 1 && this.container.offsetParent !== null && !document.hidden && this.rafId === null) {
      this.onScreen = true;
      this.lastTime = performance.now();
      this.markActive(1200);
      this.scheduleNextFrame();
    }
  }

  /** Mở góc nhìn dọc khi khung hẹp và tính hệ số lùi camera để chiều ngang cả phòng vẫn vừa khung.
   *  Mốc: toàn cảnh gốc dựng cho khung 16:10 (góc nhìn dọc 40°) thấy đủ 11 bàn. */
  private applyViewFit(): void {
    const aspect = this.camera.aspect;
    const fov = aspect >= 1.3 ? 40 : Math.min(60, 40 + (1.3 - aspect) * 30);
    this.camera.fov = fov;
    // nửa góc ngang của toàn cảnh gốc; khung hẹp chừa thêm 6% lề để hai dãy bàn ngoài cùng không sát mép
    const needTan = Math.tan(THREE.MathUtils.degToRad(20)) * 1.6 * (aspect >= 1.3 ? 1 : 1.06);
    const haveTan = Math.tan(THREE.MathUtils.degToRad(fov / 2)) * aspect;
    this.viewFit = Math.max(1, needTan / haveTan);
  }

  /** Vị trí toàn cảnh theo khung hiện tại: khung dựng đứng nhìn từ cao hơn (dùng chiều dọc) và lùi xa theo viewFit. */
  private overviewGoal(pos: THREE.Vector3, target: THREE.Vector3): void {
    const cfg = CAMERA_PRESETS.overview;
    target.set(...cfg.target);
    const k = THREE.MathUtils.clamp((1.3 - this.camera.aspect) / 0.7, 0, 1);
    const dir = new THREE.Vector3(cfg.pos[0] - cfg.target[0], cfg.pos[1] - cfg.target[1], cfg.pos[2] - cfg.target[2]);
    const len = dir.length();
    dir.normalize().lerp(new THREE.Vector3(0, 0.83, 0.56), k).normalize();
    pos.copy(target).addScaledVector(dir, len * this.viewFit);
  }

  private scheduleNextFrame(): void {
    if (this.disposed) return;
    this.rafId = requestAnimationFrame(this.tick);
  }

  private afterSoftwareDraw(): void {
    if (this.disposed) return;
    const gl2 = this.gl as WebGL2RenderingContext;
    if (typeof gl2.fenceSync === 'function') {
      const sync = gl2.fenceSync(gl2.SYNC_GPU_COMMANDS_COMPLETE, 0);
      if (sync) {
        gl2.flush();
        const started = performance.now();
        const poll = () => {
          if (this.disposed) {
            gl2.deleteSync(sync);
            return;
          }
          const status = gl2.clientWaitSync(sync, 0, 0);
          if (status === gl2.TIMEOUT_EXPIRED && performance.now() - started < 250) {
            this.rafId = requestAnimationFrame(poll);
            return;
          }
          gl2.deleteSync(sync);
          this.scheduleNextFrame();
        };
        this.rafId = requestAnimationFrame(poll);
        return;
      }
    }
    this.scheduleNextFrame();
  }

  /** Số đo hiệu năng (khung đã vẽ, thời gian CPU mỗi khung); đọc qua window.__office3d khi chạy dev. */
  public perf = { frames: 0, workMs: 0, maxWorkMs: 0, build: {} as Record<string, number> };

  private tick = (now: number): void => {
    if (this.disposed) return;
    if (!this.onScreen || document.hidden || this.container.offsetParent === null) {
      this.rafId = null;
      return; // khuất màn hình hoặc chuyển sang tab khác: dừng hẳn WebGL, không tốn CPU/GPU
    }
    const active = this.isActive(now);
    const minFrameMs = !active ? IDLE_FRAME_MS : (this.isSoftwareGl && this.quality === 'low' ? LOW_ACTIVE_FRAME_MS : 0);
    if (minFrameMs > 0 && now - this.lastRenderAt < minFrameMs) { this.scheduleNextFrame(); return; }
    this.lastRenderAt = now;
    this.frameIndex++;
    const interacting = this.isPointerDragging || now < this.userInteractingUntil;
    const hasMovingRobots = this.handoffs.size > 0 || Object.keys(this.movers).length > 0;
    // Tối ưu GPU: chỉ cập nhật ShadowMap khi có robot đang bước đi (mỗi 4 frame) hoặc cảnh vừa đổi trạng thái (shadowDirty).
    // Khi robot ngồi/đứng tại bàn không đi lại: giữ nguyên ShadowMap đã nướng, cắt ~40% tải GPU trong Không gian làm việc!
    if (
      this.renderer.shadowMap.enabled &&
      !this.interiorHidden &&
      !interacting &&
      this.exteriorReveal < 0.05 &&
      (this.shadowDirty || (hasMovingRobots && this.frameIndex % 4 === 0))
    ) {
      this.renderer.shadowMap.needsUpdate = true;
      this.shadowDirty = false;
    }
    if (active) this.sampleFps(now); else this.fpsSampleFrames = 0;
    const workStart = performance.now();

    const rawDt = (now - this.lastTime) / 1000;
    this.lastTime = now;
    const dt = Math.min(Math.max(rawDt, 0.001), 0.08);
    this.elapsedTotal += dt;

    this.updateScenario(dt);
    this.updatePackets(dt);
    this.updateMoversAndHandoff(dt);

    // Gom cập nhật màn hình TV 2D (tối đa 4 lần/giây) — tránh vẽ lại Canvas 2048px liên tục khi nhiều sự kiện tới cùng lúc
    if (this.wallDirty && now - this.lastWallSyncAt >= 240) {
      this.wallDirty = false;
      this.lastWallSyncAt = now;
      this.syncMissionWall();
    }

    if (!this.interiorHidden) {
      this.architecture.update(dt, this.elapsedTotal);
      for (const id of ALL_AGENT_IDS) {
        this.robots[id].update(dt, this.elapsedTotal);
      }
    }

    this.updateCamera(dt);

    // Chuyển cảnh mượt Văn phòng Agent (tầng thượng Nhà G) <-> Toàn cảnh 360° ĐH Duy Tân.
    // Khi đang nhắm vào điểm mốc ngoài trường (target nằm ngoài phòng), luôn giữ cảnh ngoài trời 100% kể cả khi zoom cận cảnh!
    const camDist = this.camera.position.distanceTo(this.controls.target);
    const revealStart = 34.0 * this.viewFit;
    const isTargetOutsideOffice =
      Math.abs(this.controls.target.x) > 15 ||
      Math.abs(this.controls.target.z) > 15 ||
      this.controls.target.y < -3.5;
    if (!this.cityEnv && (isTargetOutsideOffice || camDist > revealStart - 8.0)) this.ensureCampusLoaded();
    const targetReveal = isTargetOutsideOffice
      ? 1
      : THREE.MathUtils.clamp((camDist - revealStart) / 20.0, 0, 1);
    this.exteriorReveal = THREE.MathUtils.damp(this.exteriorReveal, targetReveal, 6.5, dt);

    // Khi mái Nhà G đã đóng kín 100% (exteriorReveal >= 0.96), ẩn toàn bộ nội thất + 11 robot bên trong để giảm ~200 draw calls!
    const shouldHideInterior = this.exteriorReveal >= 0.96 && Boolean(this.cityEnv);
    if (shouldHideInterior !== this.interiorHidden) {
      this.interiorHidden = shouldHideInterior;
      this.architecture.group.visible = !shouldHideInterior;
      for (const id of ALL_AGENT_IDS) {
        this.robots[id].root.visible = !shouldHideInterior;
      }
      this.flowGraph.group.visible = !shouldHideInterior;
      if (shouldHideInterior) {
        this.routeRibbonMesh.visible = false;
      } else if (this.handoffs.size > 0) {
        this.routeRibbonMesh.visible = true;
      }
      // Không vẽ lại ShadowMap ngay giữa nhịp lăn chuột; đánh dấu bẩn để cập nhật 1 lần khi dừng tương tác!
      if (this.renderer.shadowMap.enabled) this.shadowDirty = true;
    }

    this.weatherSystem.setExteriorReveal(this.exteriorReveal);
    this.weatherSystem.update(dt, this.elapsedTotal);
    if (!this.interiorHidden) {
      this.architecture.setExteriorReveal(
        this.exteriorReveal,
        this.weatherSystem.getDisplayBgColor(),
      );
    }
    if (this.cityEnv) {
      if (this.exteriorReveal > 0.015) {
        const skipVehicles = (interacting || this.isLowEndHw) && this.frameIndex % 2 === 1;
        this.cityEnv.update(dt, this.elapsedTotal, this.exteriorReveal, skipVehicles);
      } else if (this.cityEnv.group.visible) {
        this.cityEnv.group.visible = false;
      }
    }

    this.renderer.render(this.scene, this.camera);
    if (this.perf.frames === 0) {
      this.callbacks.onFirstFrame?.();
      this.scheduleEnvInit();
      this.scheduleCampusPreload();
    }
    this.emitProjectedAnchors();
    const work = performance.now() - workStart;
    this.perf.frames++; this.perf.workMs += work; this.perf.maxWorkMs = Math.max(this.perf.maxWorkMs, work);

    if (this.telemetryDirty && !interacting) {
      this.telemetryDirty = false;
      this.emitTelemetry();
    } else if (this.currentScenario && !this.isCompleted && !this.isPaused && !interacting) {
      this.telemetryThrottle += dt;
      if (this.telemetryThrottle >= 0.35) {
        this.telemetryThrottle = 0;
        this.wallDirty = true;
        this.emitTelemetry();
      }
    }

    if (this.isSoftwareGl) {
      this.afterSoftwareDraw();
    } else {
      this.scheduleNextFrame();
    }
  };
}
