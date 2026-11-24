import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
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
import {
  buildCityEnvironment,
  type CityEnvironmentInstance,
} from './cityEnvironment';
import { createStudioMaterials, type StudioMaterialLibrary } from './materials';
import {
  buildStudioArchitecture,
  type StudioArchitectureInstance,
} from './officeArchitecture';
import {
  buildBeanRobotCharacter,
  type BeanRobotInstance,
} from './robotCharacter';
import { createStudioTextures, type StudioTextureSet, type WallStepState } from './textures';
import {
  createWeatherSystem,
  type WeatherSystemInstance,
} from './weatherSystem';


export type QualityLevel = 'high' | 'medium' | 'low';
export type QualityMode = 'auto' | QualityLevel;
const QUALITY: Record<QualityLevel, { maxDpr: number; shadowSize: number }> = {
  high: { maxDpr: 1.5, shadowSize: 2048 },
  medium: { maxDpr: 1.25, shadowSize: 1024 },
  low: { maxDpr: 1, shadowSize: 0 },
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
const AUTO_DOWNGRADE_FPS = 40;

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

interface FlyingPacket {
  mesh: THREE.Mesh;
  curve: THREE.QuadraticBezierCurve3;
  progress: number;
  speed: number;
}

const CAMERA_PRESETS: Record<
  'overview' | 'core_studio' | 'specialist_row' | 'rag_analyst' | 'city_exterior',
  { pos: [number, number, number]; target: [number, number, number] }
> = {
  overview: { pos: [0, 9.6, 11.8], target: [0, 0.45, 0.25] },
  core_studio: { pos: [0, 7.8, 6.2], target: [0, 0.65, -2.5] },
  specialist_row: { pos: [0, 6.8, 11.4], target: [0, 0.55, 4.35] },
  rag_analyst: { pos: [-1.8, 6.6, 5.0], target: [-5.5, 0.7, -2.3] },
  city_exterior: { pos: [38, 18, 52], target: [0, -7.5, 0] },
};

function detectSoftwareWebGL(gl: WebGLRenderingContext | WebGL2RenderingContext): boolean {
  try {
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    if (!ext) return false;
    const rendererStr = String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '');
    return /SwiftShader|llvmpipe|Software|Mesa OffScreen|Microsoft Basic Render/i.test(
      rendererStr,
    );
  } catch {
    return false;
  }
}

export class Office3DEngine implements Studio3DController {
  private container: HTMLElement;
  private callbacks: StudioEngineCallbacks;
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private pmremGenerator: THREE.PMREMGenerator;
  private envRT: THREE.WebGLRenderTarget;
  private textures: StudioTextureSet;
  private materials: StudioMaterialLibrary;
  private architecture: StudioArchitectureInstance;
  private cityEnv: CityEnvironmentInstance;
  private weatherSystem: WeatherSystemInstance;
  private robots: Record<AgentId, BeanRobotInstance>;

  private isSoftwareGl: boolean;
  private gl: WebGLRenderingContext | WebGL2RenderingContext;
  private raycaster = new THREE.Raycaster();
  private pointerNdc = new THREE.Vector2(-99, -99);
  private hoveredAgent: AgentId | null = null;
  private selectedAgent: AgentId | null = null;
  private pointerDownPos = { x: 0, y: 0 };

  private cameraGoalPos = new THREE.Vector3(...CAMERA_PRESETS.overview.pos);
  private cameraGoalTarget = new THREE.Vector3(...CAMERA_PRESETS.overview.target);
  private cameraLerpActive = false;
  private followLeadAgent = false;
  private exteriorReveal = 0;
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
  private packetGroup = new THREE.Group();
  private packetGeo: THREE.BoxGeometry;
  private activePackets: FlyingPacket[] = [];

  private tempVec3 = new THREE.Vector3();
  private projectedAnchors: ProjectedAgentAnchor[] = [];

  private rafId: number | null = null;
  private disposed = false;
  private lastTime = 0;
  private elapsedTotal = 0;
  private telemetryThrottle = 0;
  private resizeObserver: ResizeObserver;
  // Đợt 2 (23/11): vẽ thưa khi đứng yên, dừng khi khuất, chất lượng tự chọn theo FPS
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
  private lastQualityChange = 0;
  private lastSampleAt = 0;

  constructor(container: HTMLElement, callbacks: StudioEngineCallbacks) {
    this.container = container;
    this.callbacks = callbacks;
    const mark = (k: string) => { this.perf.build[k] = Math.round(performance.now() - t0); };
    const t0 = performance.now();

    const width = Math.max(container.clientWidth, 1);
    const height = Math.max(container.clientHeight, 1);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: 'high-performance',
      alpha: false,
    });
    this.gl = this.renderer.getContext();
    this.isSoftwareGl = detectSoftwareWebGL(this.gl);

    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, this.isSoftwareGl ? 1.25 : 2));
    this.renderer.setSize(width, height);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.02;
    this.renderer.shadowMap.enabled = !this.isSoftwareGl;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.style.display = 'block';
    this.renderer.domElement.style.width = '100%';
    this.renderer.domElement.style.height = '100%';
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xe6dfd3);
    this.scene.fog = new THREE.FogExp2(0xe6dfd3, 0.0064);

    // Wide far plane (480m) so zooming out to orbit the HQ skyscraper & 360° city stays crisp!
    this.camera = new THREE.PerspectiveCamera(40, width / height, 0.5, 480);
    this.camera.position.set(...CAMERA_PRESETS.overview.pos);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(...CAMERA_PRESETS.overview.target);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.zoomSpeed = 1.25;
    this.controls.maxPolarAngle = Math.PI * 0.485;
    this.controls.minPolarAngle = Math.PI * 0.12;
    this.controls.minDistance = 4.2;
    this.controls.maxDistance = 108;
    this.controls.addEventListener('start', () => {
      this.cameraLerpActive = false;
    });

    mark('renderer');
    this.pmremGenerator = new THREE.PMREMGenerator(this.renderer);
    this.envRT = this.pmremGenerator.fromScene(new RoomEnvironment(), 0.04);
    this.scene.environment = this.envRT.texture;
    this.scene.environmentIntensity = 0.62;

    // Realistic Architectural Lighting Rig controlled dynamically by WeatherSystem
    const hemi = new THREE.HemisphereLight(0xfff9ee, 0xbba890, 0.96);
    this.scene.add(hemi);

    const sunKey = new THREE.DirectionalLight(0xffefd6, 2.1);
    sunKey.position.set(16, 28, 18);
    sunKey.castShadow = !this.isSoftwareGl;
    if (sunKey.castShadow) {
      sunKey.shadow.mapSize.set(2048, 2048);
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
    const maxAniso = this.renderer.capabilities.getMaxAnisotropy();
    this.textures = createStudioTextures(maxAniso);
    this.materials = createStudioMaterials(this.textures, this.isSoftwareGl);
    mark('textures');
    this.architecture = buildStudioArchitecture(this.materials, this.textures);
    mark('architecture');
    this.scene.add(this.architecture.group);

    // Multi-Story AI HQ Tower + 360° Living 3D Cityscape (revealed when zooming out with mouse wheel!)
    this.cityEnv = buildCityEnvironment(maxAniso);
    this.scene.add(this.cityEnv.group);
    mark('city');

    // Real-time City-Scale 3D Weather & Time-of-Day System (Sunny / Sunset / Night / Storm!)
    this.weatherSystem = createWeatherSystem({
      scene: this.scene,
      renderer: this.renderer,
      hemiLight: hemi,
      keyLight: sunKey,
      fillLight: coolBounce,
      onWarmLampUpdate: (intensity) => this.architecture.setAtmosphereLight(intensity),
      onCityNightGlow: (intensity) => this.cityEnv.setNightGlow(intensity),
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

    this.packetGeo = new THREE.BoxGeometry(0.24, 0.09, 0.18);
    this.scene.add(this.packetGroup);

    this.raycaster.layers.set(1);

    this.renderer.domElement.addEventListener('pointermove', this.handlePointerMove);
    this.renderer.domElement.addEventListener('pointerdown', this.handlePointerDown);
    this.renderer.domElement.addEventListener('pointerup', this.handlePointerUp);

    this.resizeObserver = new ResizeObserver(() => this.handleResize());
    this.resizeObserver.observe(container);
    this.controls.addEventListener('change', () => this.markActive(1200));
    if (typeof IntersectionObserver !== 'undefined') {
      this.intersection = new IntersectionObserver(([entry]) => {
        const was = this.onScreen;
        this.onScreen = entry.isIntersecting;
        if (this.onScreen && !was && this.rafId === null) { this.lastTime = performance.now(); this.markActive(); this.scheduleNextFrame(); }
      });
      this.intersection.observe(container);
    }
    this.renderer.shadowMap.autoUpdate = false;
    const smallScreen = Math.min(window.innerWidth, window.innerHeight) < 700 || window.matchMedia?.('(pointer: coarse)').matches;
    this.applyQuality(this.isSoftwareGl ? 'low' : smallScreen ? 'medium' : 'high');

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

  /** Đánh dấu có chuyển động để vẽ đủ khung trong `ms` tới. */
  public markActive(ms = 2500): void {
    this.activeUntil = Math.max(this.activeUntil, performance.now() + ms);
  }

  private isActive(now: number): boolean {
    const running = !!this.currentScenario && !this.isCompleted && !this.isPaused;
    return running || now < this.activeUntil || this.cameraLerpActive || this.followLeadAgent
      || this.handoffs.size > 0 || this.activePackets.length > 0 || Object.keys(this.movers).length > 0
      || (this.exteriorReveal > 0.001 && this.exteriorReveal < 0.999);
  }

  public getQuality(): { mode: QualityMode; level: QualityLevel } {
    return { mode: this.qualityMode, level: this.quality };
  }

  public setQualityMode(mode: QualityMode): void {
    this.qualityMode = mode;
    if (mode !== 'auto') this.applyQuality(mode);
    this.fpsSampleFrames = 0;
    this.markActive();
  }

  private applyQuality(level: QualityLevel): void {
    this.quality = level;
    this.lastQualityChange = performance.now();
    const dpr = window.devicePixelRatio || 1;
    this.renderer.setPixelRatio(Math.min(dpr, QUALITY[level].maxDpr));
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
    this.renderer.shadowMap.type = level === 'high' ? THREE.PCFSoftShadowMap : THREE.PCFShadowMap;
    this.renderer.shadowMap.needsUpdate = true;
    this.handleResize();
  }

  /** Tự hạ chất lượng khi FPS lúc có chuyển động thấp hơn ngưỡng trong ~2 giây. Không tự nâng lại để tránh nhấp nháy. */
  private sampleFps(now: number): void {
    if (this.qualityMode !== 'auto' || this.quality === 'low' || now - this.lastQualityChange < 3000) return;
    // khoảng trống > 200 ms là trình duyệt tạm dừng/giới hạn (tab ẩn), không phải máy chậm: bỏ mẫu
    if (this.fpsSampleFrames > 0 && now - this.lastSampleAt > 200) this.fpsSampleFrames = 0;
    this.lastSampleAt = now;
    if (this.fpsSampleFrames === 0) this.fpsSampleStart = now;
    this.fpsSampleFrames++;
    const span = now - this.fpsSampleStart;
    if (span < 2000) return;
    const fps = (this.fpsSampleFrames - 1) / (span / 1000);
    this.fpsSampleFrames = 0;
    if (fps < AUTO_DOWNGRADE_FPS) this.applyQuality(this.quality === 'high' ? 'medium' : 'low');
  }

  // =========================================================================
  // PUBLIC CONTROLLER API (Studio3DController)
  // =========================================================================

  public runScenario(scenario: ComplexityScenario): void {
    this.markActive();
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
    const scenario = this.currentScenario;
    if (!scenario || stageIndex < 0 || stageIndex >= scenario.stages.length) return;

    this.currentStageIndex = stageIndex;
    this.isCompleted = false;
    this.handoffs.clear();
    this.routeRibbonMesh.visible = false;
    this.clearPackets();
    this.movers = {};

    let elapsedBefore = 0;
    for (let i = 0; i < stageIndex; i++) {
      elapsedBefore += scenario.stages[i].durationSec;
    }
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
    this.emitTelemetry();
  }

  public wakeAgents(ids: AgentId[]): void {
    this.markActive();
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
    this.syncMissionWall();
    this.emitTelemetry();
  }

  public putAgentsToSleep(ids: AgentId[]): void {
    this.markActive();
    for (const id of ids) {
      this.awakeSet.delete(id);
      this.sendAgentToSleep(id);
    }
    this.architecture.setAwakeAgents(this.awakeSet);
    this.syncMissionWall();
    this.emitTelemetry();
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
      this.syncMissionWall();
      this.emitTelemetry();
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
    this.syncMissionWall();
    this.emitTelemetry();
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
      new THREE.Vector3(startPos[0], 0.05, startPos[1]),
      ...waypoints.map(([wx, wz]) => new THREE.Vector3(wx, 0.05, wz)),
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
    wall?: { tierLabel: string; requestTitle: string; stepText: string; progressPct: number };
  }): void {
    this.markActive();
    this.currentScenario = null;
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
    if (opts.dispatch) this.spawnDispatchPackets(opts.dispatch.from, opts.dispatch.toList);
    if (opts.wall) this.liveWall = opts.wall;
    this.syncMissionWall();
    this.emitTelemetry();
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
      preset === 'core_studio' ||
      preset === 'specialist_row' ||
      preset === 'rag_analyst' ||
      preset === 'city_exterior'
    ) {
      this.lastPreset = preset;
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
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.resizeObserver.disconnect();
    this.renderer.domElement.removeEventListener('pointermove', this.handlePointerMove);
    this.renderer.domElement.removeEventListener('pointerdown', this.handlePointerDown);
    this.renderer.domElement.removeEventListener('pointerup', this.handlePointerUp);
    this.controls.dispose();

    this.clearPackets();
    this.packetGeo.dispose();
    this.routeRibbonMesh.geometry.dispose();
    this.routeRibbonMat.dispose();
    for (const id of ALL_AGENT_IDS) {
      this.robots[id].dispose();
    }
    this.weatherSystem.dispose();
    this.cityEnv.dispose();
    this.architecture.dispose();
    this.materials.dispose();
    this.textures.dispose();
    this.envRT.dispose();
    this.pmremGenerator.dispose();
    this.renderer.dispose();
    if (this.renderer.domElement.parentElement === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
  }

  // =========================================================================
  // INTERNAL STAGE, DISPATCH PACKETS & MOVEMENT CHOREOGRAPHY
  // =========================================================================

  private clearPackets(): void {
    for (const p of this.activePackets) {
      this.packetGroup.remove(p.mesh);
      (p.mesh.material as THREE.Material).dispose();
    }
    this.activePackets.length = 0;
  }

  private spawnDispatchPackets(fromId: AgentId, toIds: AgentId[]): void {
    this.clearPackets();
    const fromPos = this.robots[fromId].position;
    for (let i = 0; i < toIds.length; i++) {
      const target = this.robots[toIds[i]];
      if (!target) continue;
      const start = new THREE.Vector3(fromPos.x, 1.35, fromPos.z);
      const end = new THREE.Vector3(target.position.x, 1.25, target.position.z);
      const mid = start.clone().lerp(end, 0.5);
      mid.y += 1.65;

      const mat = new THREE.MeshBasicMaterial({
        color: AGENT_PROFILES[toIds[i]].accentNumber,
      });
      const mesh = new THREE.Mesh(this.packetGeo, mat);
      mesh.position.copy(start);
      this.packetGroup.add(mesh);

      this.activePackets.push({
        mesh,
        curve: new THREE.QuadraticBezierCurve3(start, mid, end),
        progress: -i * 0.14,
        speed: 0.72,
      });
    }
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

    if (dist < 0.35) {
      delete this.movers[id];
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
      this.spawnDispatchPackets(stage.dispatchTargets.from, stage.dispatchTargets.toList);
    } else {
      this.clearPackets();
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
    let awakeCount = 0;
    for (const id of ALL_AGENT_IDS) {
      if (this.agentStates[id].isAwake) awakeCount += 1;
    }
    const pct =
      scenario && scenario.targetDurationSec > 0
        ? (this.totalElapsedSec / scenario.targetDurationSec) * 100
        : 0;

    if (!scenario && this.liveWall) {
      this.textures.updateMissionWall({ ...this.liveWall, awakeCount, sleepingCount: ALL_AGENT_IDS.length - awakeCount, steps: this.wallSteps });
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
        this.clearPackets();
        this.leadActor = 'integrator';
        this.architecture.setLeadHighlight('integrator');
        for (const id of scenario.awakeAgents) {
          this.agentStates[id].action = 'completed';
          this.agentStates[id].actionText =
            id === 'integrator' ? 'Đã bàn giao báo cáo hoàn chỉnh' : 'Hoàn thành nhiệm vụ';
        }
        this.syncMissionWall();
        this.emitTelemetry();
      }
    }
  }

  private updatePackets(dt: number): void {
    if (this.activePackets.length === 0) return;
    for (let i = this.activePackets.length - 1; i >= 0; i--) {
      const p = this.activePackets[i];
      p.progress += dt * p.speed * Math.max(1, this.speedMultiplier * 0.75);
      if (p.progress < 0) {
        p.mesh.visible = false;
      } else if (p.progress >= 1) {
        this.packetGroup.remove(p.mesh);
        (p.mesh.material as THREE.Material).dispose();
        this.activePackets.splice(i, 1);
      } else {
        p.mesh.visible = true;
        p.curve.getPoint(p.progress, p.mesh.position);
        p.mesh.rotation.y += dt * 4.5;
        p.mesh.rotation.x = Math.sin(p.progress * Math.PI) * 0.45;
      }
    }
  }

  private updateMoversAndHandoff(dt: number): void {
    const walkSpeed = 4.2 * Math.min(2.6, Math.max(1, this.speedMultiplier * 0.85)) * (this.liveTempo === 'realtime' ? 1.8 : 1);

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
    }
    this.controls.update();
  }

  private emitProjectedAnchors(): void {
    if (!this.callbacks.onAnchorsUpdated) return;
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (w <= 0 || h <= 0) return;

    const hideForCityView = this.exteriorReveal > 0.35;

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
    // chỉ báo React khi nhãn đổi vị trí (làm tròn tới điểm ảnh) hoặc trạng thái; trước đây vẽ lại nhãn mọi khung
    const sig = this.projectedAnchors.map((p) => `${+p.visible}${+p.isAwake}${+p.isLead}${p.actionText}`).join('|');
    const posSig = this.projectedAnchors.map((p) => `${Math.round(p.x)},${Math.round(p.y)}`).join('|');
    if (sig === this.lastAnchorSig && posSig === this.lastAnchorPosSig) return;
    const contentChanged = sig !== this.lastAnchorSig || !this.callbacks.onAnchorsMoved;
    this.lastAnchorSig = sig;
    this.lastAnchorPosSig = posSig;
    if (contentChanged) this.callbacks.onAnchorsUpdated([...this.projectedAnchors]);
    else this.callbacks.onAnchorsMoved?.(this.projectedAnchors);
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

  private handlePointerDown = (e: PointerEvent): void => {
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

  private handleResize(): void {
    if (this.disposed) return;
    const width = Math.max(this.container.clientWidth, 1);
    const height = Math.max(this.container.clientHeight, 1);
    this.camera.aspect = width / height;
    const before = this.viewFit;
    this.applyViewFit();
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
    // đang ở toàn cảnh mà tỉ lệ khung đổi (mở bảng cạnh ô chat, kéo rộng hẹp): bay lại toàn cảnh cho vừa khung mới
    if (this.lastPreset === 'overview' && Math.abs(before - this.viewFit) > 0.02 && width > 1 && height > 1) this.setCameraPreset('overview');
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
        const poll = () => {
          if (this.disposed) {
            gl2.deleteSync(sync);
            return;
          }
          const status = gl2.clientWaitSync(sync, 0, 0);
          if (status === gl2.TIMEOUT_EXPIRED) {
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
    if (!this.onScreen) { this.rafId = null; return; } // khuất màn hình: dừng hẳn, IntersectionObserver gọi lại
    const active = this.isActive(now);
    if (!active && now - this.lastRenderAt < IDLE_FRAME_MS) { this.scheduleNextFrame(); return; }
    this.lastRenderAt = now;
    this.frameIndex++;
    // bóng đổ: cập nhật mỗi 2 khung khi có chuyển động, mỗi khung vẽ khi đứng yên (đã thưa sẵn)
    if (this.renderer.shadowMap.enabled && (!active || this.frameIndex % 2 === 0)) this.renderer.shadowMap.needsUpdate = true;
    if (active) this.sampleFps(now); else this.fpsSampleFrames = 0;
    const workStart = performance.now();

    const rawDt = (now - this.lastTime) / 1000;
    this.lastTime = now;
    const dt = Math.min(Math.max(rawDt, 0.001), 0.08);
    this.elapsedTotal += dt;

    this.updateScenario(dt);
    this.updatePackets(dt);
    this.updateMoversAndHandoff(dt);
    this.architecture.update(dt, this.elapsedTotal);

    for (const id of ALL_AGENT_IDS) {
      this.robots[id].update(dt, this.elapsedTotal);
    }

    this.updateCamera(dt);

    // Smooth Indoor-Room -> Exterior Building & 360° City transition driven by mouse wheel zoom distance!
    // Inside room (distance <= 20m): purely cozy indoor studio view (exterior city completely hidden).
    // Scroll wheel out (distance 20m -> 31m): breaks out of the penthouse to reveal the 8-story HQ Tower & City!
    const camDist = this.camera.position.distanceTo(this.controls.target);
    // khung hẹp thì toàn cảnh đã lùi xa hơn: dời ngưỡng hiện tòa nhà theo cùng hệ số để không lộ ngoại thất
    const revealStart = 20.0 * this.viewFit;
    const targetReveal = THREE.MathUtils.clamp((camDist - revealStart) / 11.0, 0, 1);
    this.exteriorReveal = THREE.MathUtils.damp(this.exteriorReveal, targetReveal, 6.5, dt);

    this.weatherSystem.setExteriorReveal(this.exteriorReveal);
    this.weatherSystem.update(dt, this.elapsedTotal);
    this.architecture.setExteriorReveal(
      this.exteriorReveal,
      this.weatherSystem.getDisplayBgColor(),
    );
    this.cityEnv.update(dt, this.elapsedTotal, this.exteriorReveal);

    this.renderer.render(this.scene, this.camera);
    if (this.perf.frames === 0) this.callbacks.onFirstFrame?.();
    this.emitProjectedAnchors();
    const work = performance.now() - workStart;
    this.perf.frames++; this.perf.workMs += work; this.perf.maxWorkMs = Math.max(this.perf.maxWorkMs, work);

    if (this.currentScenario && !this.isCompleted && !this.isPaused) {
      this.telemetryThrottle += dt;
      if (this.telemetryThrottle >= 0.35) {
        this.telemetryThrottle = 0;
        this.syncMissionWall();
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
