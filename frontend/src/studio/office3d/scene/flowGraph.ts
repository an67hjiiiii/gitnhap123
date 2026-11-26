import * as THREE from 'three';
import { AGENT_PROFILES } from '../agents';
import type { FlowEdge, FlowKind } from '../liveDirector';
import type { AgentId } from '../types';

export const FLOW_COLORS: Record<FlowKind, number> = {
  dispatch: 0xd97706, // Vàng hổ phách: Orchestrator giao việc / phân rã
  rag: 0x0891b2,      // Xanh ngọc lam (Cyan): RAG cấp tài liệu riêng biệt (tách biệt hẳn Finance xanh lá!)
  result: 0x2563eb,   // Xanh lam: Chuyên gia nộp kết quả phân tích
  fail: 0xdc2626,     // Đỏ hồng lựu: Thiếu bằng chứng / lỗi
  revise: 0xea580c,   // Cam san hô: Reviewer trả bài yêu cầu chỉnh sửa
  approve: 0x15803d,  // Xanh lá rừng: Đạt kiểm định QC -> gửi Integrator
};

export const FLOW_HEX: Record<FlowKind, string> = {
  dispatch: '#d97706',
  rag: '#0891b2',
  result: '#2563eb',
  fail: '#dc2626',
  revise: '#ea580c',
  approve: '#15803d',
};

const COMPACT_AGENT_NAME: Partial<Record<AgentId, string>> = {
  orchestrator: 'Orchestrator',
  rag: 'RAG',
  analyst: 'Analyst',
  reviewer: 'Reviewer',
  integrator: 'Integrator',
};

function compactName(id: AgentId): string {
  return COMPACT_AGENT_NAME[id] ?? AGENT_PROFILES[id]?.shortName ?? id;
}

export const FLOW_KIND_LABELS_VI: Record<FlowKind, string> = {
  dispatch: 'Giao việc',
  rag: 'Cấp RAG',
  result: 'Nộp kết quả',
  fail: 'Thiếu dữ liệu',
  revise: 'Trả sửa QC',
  approve: 'Duyệt đạt QC',
};

export interface ProjectedFlowBadge {
  key: string;
  from: AgentId;
  to: AgentId;
  routeText: string;
  label: string;
  kind: FlowKind;
  colorHex: string;
  x: number;
  y: number;
  active: boolean;
}

export interface FlowLogItem {
  id: string;
  from: AgentId;
  to: AgentId;
  fromName: string;
  toName: string;
  kind: FlowKind;
  colorHex: string;
  label: string;
  active: boolean;
}

interface ArcSlot {
  inUse: boolean;
  key: string;
  from: AgentId;
  to: AgentId;
  kind: FlowKind;
  label: string;
  emittedAt: number;
  curve: THREE.QuadraticBezierCurve3;
  midPoint: THREE.Vector3;
  coreMesh: THREE.Mesh;
  coreMat: THREE.MeshBasicMaterial;
  glowMesh: THREE.Mesh;
  glowMat: THREE.MeshBasicMaterial;
  packetGroup: THREE.Group;
  packetCoverMat: THREE.MeshStandardMaterial;
  ring: THREE.Mesh;
  ringMat: THREE.MeshBasicMaterial;
  packetProgress: number; // 0..1 khi đang bay, >1 khi đã tới đích
  packetSpeed: number;
  activeUntil: number;
  ringPulse: number; // 0..1 vòng sóng nở ra dưới chân người nhận
  flowPhase: number;
  arrivedSignaled: boolean;
}

const MAX_SLOTS = 16;
const ARC_SEGMENTS = 28;
const RADIAL_SEGS = 6;
const ARROWS_PER_ARC = 4;

export interface FlowGraph3DInstance {
  group: THREE.Group;
  emitFlow: (
    from: AgentId,
    to: AgentId,
    fromPos: THREE.Vector3,
    toPos: THREE.Vector3,
    kind: FlowKind,
    label: string,
    nowSec: number,
  ) => void;
  syncEdges: (
    edges: FlowEdge[],
    getPos: (id: AgentId) => THREE.Vector3 | null,
    nowSec: number,
  ) => void;
  /** V10: chỉ giữ luồng nối cho các Agent đang còn làm việc (giữ nhiều luồng khi chạy song song, tắt ngay khi xong). */
  syncActiveWorkers: (activeWorkers: Set<AgentId>, finished: boolean, nowSec: number) => void;
  setTraceMode: (trace: boolean) => void;
  fastSettle: () => void;
  clear: () => void;
  hasActiveTraffic: () => boolean;
  getRecentLogs: (limit?: number) => FlowLogItem[];
  update: (
    dt: number,
    nowSec: number,
    speedMultiplier: number,
    onArrive?: (from: AgentId, to: AgentId, kind: FlowKind) => void,
  ) => void;
  projectBadges: (
    camera: THREE.Camera,
    width: number,
    height: number,
    nowSec: number,
  ) => ProjectedFlowBadge[];
  dispose: () => void;
}

/** Tạo BufferGeometry dạng ống 6 cạnh cấp phát sẵn (cập nhật đỉnh trực tiếp, 0 GC trong runtime). */
function createPooledTubeGeometry(): THREE.BufferGeometry {
  const ringVerts = RADIAL_SEGS + 1;
  const vertCount = (ARC_SEGMENTS + 1) * ringVerts;
  const positions = new Float32Array(vertCount * 3);
  const indices: number[] = [];

  for (let s = 0; s < ARC_SEGMENTS; s++) {
    for (let r = 0; r < RADIAL_SEGS; r++) {
      const a = s * ringVerts + r;
      const b = (s + 1) * ringVerts + r;
      const c = (s + 1) * ringVerts + (r + 1);
      const d = s * ringVerts + (r + 1);
      indices.push(a, b, d, b, c, d);
    }
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setIndex(indices);
  return geo;
}

/**
 * Hệ thống Luồng Hoạt Động & Giao Tiếp 3D (Object-Pooled, 0 cấp phát bộ nhớ trong tick):
 * - Thay đường kẻ 1px bằng Dải Ống Ánh Sáng 3D có bề dày thực (lõi đậm + hào quang mềm).
 * - Chuỗi Mũi Tên Nón 3D xoay theo tiếp tuyến đường cong (1 InstancedMesh = 1 draw call) chỉ rõ ai gửi -> ai nhận.
 * - Gói Hồ Sơ 3D (bìa màu vai trò + ruột giấy trắng + kẹp) bay dọc cung & bật vòng sóng dưới chân Agent đích.
 * - Tự đồng bộ cao độ Bục Chỉ Huy (+0.28m) và sàn chính (0m).
 */
export function createFlowGraph3D(): FlowGraph3DInstance {
  const group = new THREE.Group();
  group.name = 'OrchestrationFlowGraph3D';

  const slots: ArcSlot[] = [];

  // Shared geometries cho Gói Hồ Sơ 3D & Vòng Sóng
  const folderCoverGeo = new THREE.BoxGeometry(0.30, 0.065, 0.23);
  const folderPaperGeo = new THREE.BoxGeometry(0.26, 0.078, 0.19);
  const folderTabGeo = new THREE.BoxGeometry(0.11, 0.025, 0.05);
  const paperWhiteMat = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    emissive: 0xffffff,
    emissiveIntensity: 0.35,
    roughness: 0.4,
  });

  const ringGeo = new THREE.RingGeometry(0.34, 0.56, 30);
  ringGeo.rotateX(-Math.PI / 2);

  // 1 InstancedMesh duy nhất cho toàn bộ Mũi Tên Nón 3D chỉ hướng trên tất cả các cung (= 1 draw call!)
  const totalArrows = MAX_SLOTS * ARROWS_PER_ARC;
  const arrowGeo = new THREE.ConeGeometry(0.088, 0.24, 8);
  const arrowMat = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.96,
  });
  const arrowInst = new THREE.InstancedMesh(arrowGeo, arrowMat, totalArrows);
  arrowInst.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  arrowInst.frustumCulled = false;
  group.add(arrowInst);

  const dummy = new THREE.Object3D();
  const upAxis = new THREE.Vector3(0, 1, 0);
  const fallbackSide = new THREE.Vector3(1, 0, 0);
  const tempPt = new THREE.Vector3();
  const tempTan = new THREE.Vector3();
  const tempNorm = new THREE.Vector3();
  const tempBino = new THREE.Vector3();
  const tempQuat = new THREE.Quaternion();
  const tempCol = new THREE.Color();
  const projVec = new THREE.Vector3();
  const zeroMat = new THREE.Matrix4().makeScale(0, 0, 0);

  for (let i = 0; i < totalArrows; i++) {
    arrowInst.setMatrixAt(i, zeroMat);
    arrowInst.setColorAt(i, tempCol.setHex(0xffffff));
  }
  arrowInst.instanceMatrix.needsUpdate = true;
  if (arrowInst.instanceColor) arrowInst.instanceColor.needsUpdate = true;

  for (let i = 0; i < MAX_SLOTS; i++) {
    const coreGeo = createPooledTubeGeometry();
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xf59e0b,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    });
    const coreMesh = new THREE.Mesh(coreGeo, coreMat);
    coreMesh.visible = false;
    coreMesh.frustumCulled = false;
    coreMesh.renderOrder = 4;
    group.add(coreMesh);

    const glowGeo = createPooledTubeGeometry();
    const glowMat = new THREE.MeshBasicMaterial({
      color: 0xf59e0b,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    });
    const glowMesh = new THREE.Mesh(glowGeo, glowMat);
    glowMesh.visible = false;
    glowMesh.frustumCulled = false;
    glowMesh.renderOrder = 3;
    group.add(glowMesh);

    // Gói hồ sơ 3D sắc nét (bìa màu + ruột trắng nổi bật + tai nhãn)
    const packetGroup = new THREE.Group();
    const packetCoverMat = new THREE.MeshStandardMaterial({
      color: 0xf59e0b,
      emissive: 0xf59e0b,
      emissiveIntensity: 0.55,
      roughness: 0.32,
      metalness: 0.12,
    });
    const coverMesh = new THREE.Mesh(folderCoverGeo, packetCoverMat);
    const paperMesh = new THREE.Mesh(folderPaperGeo, paperWhiteMat);
    paperMesh.position.set(0.012, 0.008, 0);
    const tabMesh = new THREE.Mesh(folderTabGeo, packetCoverMat);
    tabMesh.position.set(-0.07, 0.036, -0.11);
    packetGroup.add(coverMesh, paperMesh, tabMesh);
    packetGroup.visible = false;
    group.add(packetGroup);

    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xf59e0b,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.visible = false;
    ring.renderOrder = 2;
    group.add(ring);

    slots.push({
      inUse: false,
      key: '',
      from: 'orchestrator',
      to: 'integrator',
      kind: 'dispatch',
      label: '',
      emittedAt: 0,
      curve: new THREE.QuadraticBezierCurve3(
        new THREE.Vector3(),
        new THREE.Vector3(),
        new THREE.Vector3(),
      ),
      midPoint: new THREE.Vector3(),
      coreMesh,
      coreMat,
      glowMesh,
      glowMat,
      packetGroup,
      packetCoverMat,
      ring,
      ringMat,
      packetProgress: 2,
      packetSpeed: 1.15,
      activeUntil: 0,
      ringPulse: 2,
      flowPhase: i * 0.19,
      arrivedSignaled: true,
    });
  }

  let traceMode = false;
  let settlingFast = false;

  /** Ghi lại lưới ống 6 cạnh dọc theo đường cong Bezier vào BufferGeometry có sẵn. */
  function writeTubeMesh(
    mesh: THREE.Mesh,
    curve: THREE.QuadraticBezierCurve3,
    radius: number,
  ): void {
    const attr = mesh.geometry.getAttribute('position') as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const ringVerts = RADIAL_SEGS + 1;

    for (let s = 0; s <= ARC_SEGMENTS; s++) {
      const u = s / ARC_SEGMENTS;
      curve.getPoint(u, tempPt);
      curve.getTangent(u, tempTan).normalize();

      // Tạo hệ trục vuông góc ổn định quanh tiếp tuyến
      if (Math.abs(tempTan.dot(upAxis)) > 0.96) {
        tempNorm.crossVectors(tempTan, fallbackSide).normalize();
      } else {
        tempNorm.crossVectors(tempTan, upAxis).normalize();
      }
      tempBino.crossVectors(tempTan, tempNorm).normalize();

      // Thuôn nhẹ hai đầu ống để neo vào tay/bàn gọn gàng
      const endTaper = 0.68 + 0.32 * Math.sin(u * Math.PI);
      const rNow = radius * endTaper;

      for (let r = 0; r <= RADIAL_SEGS; r++) {
        const theta = (r / RADIAL_SEGS) * Math.PI * 2;
        const cosT = Math.cos(theta) * rNow;
        const sinT = Math.sin(theta) * rNow;
        const idx = (s * ringVerts + r) * 3;
        arr[idx] = tempPt.x + tempNorm.x * cosT + tempBino.x * sinT;
        arr[idx + 1] = tempPt.y + tempNorm.y * cosT + tempBino.y * sinT;
        arr[idx + 2] = tempPt.z + tempNorm.z * cosT + tempBino.z * sinT;
      }
    }
    attr.needsUpdate = true;
  }

  function writeCurve(
    slot: ArcSlot,
    fromPos: THREE.Vector3,
    toPos: THREE.Vector3,
    kind: FlowKind,
    indexOffset: number,
  ): void {
    const start = slot.curve.v0;
    const mid = slot.curve.v1;
    const end = slot.curve.v2;

    // Neo ở tầm ngực/mặt bàn (cộng tự động theo cao độ Bục Chỉ Huy +0.28m hoặc sàn 0m)
    const fromBaseY = fromPos.y;
    const toBaseY = toPos.y;
    start.set(fromPos.x, fromBaseY + 1.02, fromPos.z);
    end.set(toPos.x, toBaseY + 0.98, toPos.z);

    const dx = end.x - start.x;
    const dz = end.z - start.z;
    const dist = Math.hypot(dx, dz);

    // Tách ngang các luồng đi ngược chiều nhau (vd. Reviewer <-> Specialist hoặc RAG -> Specialist)
    const perpX = dist > 0.01 ? -dz / dist : 0;
    const perpZ = dist > 0.01 ? dx / dist : 0;
    const lateral =
      (kind === 'revise' ? 0.65 : kind === 'rag' ? -0.44 : kind === 'result' ? 0.38 : 0.16) +
      ((indexOffset % 3) - 1) * 0.14;
    const arcLift =
      Math.min(2.65, Math.max(1.18, dist * 0.25)) +
      (kind === 'revise' ? 0.52 : kind === 'approve' ? 0.26 : 0);

    mid.set(
      (start.x + end.x) * 0.5 + perpX * lateral,
      Math.max(start.y, end.y) + arcLift,
      (start.z + end.z) * 0.5 + perpZ * lateral,
    );

    slot.curve.getPoint(0.5, slot.midPoint);

    writeTubeMesh(slot.coreMesh, slot.curve, 0.032);
    writeTubeMesh(slot.glowMesh, slot.curve, 0.072);

    slot.ring.position.set(toPos.x, toBaseY + 0.045, toPos.z);
  }

  function acquireSlot(key: string): ArcSlot {
    const existing = slots.find((s) => s.inUse && s.key === key);
    if (existing) return existing;
    const free = slots.find((s) => !s.inUse);
    if (free) return free;
    let oldest = slots[0];
    for (const s of slots) {
      if (s.activeUntil < oldest.activeUntil) oldest = s;
    }
    return oldest;
  }

  function applyColor(slot: ArcSlot, kind: FlowKind): void {
    const hex = FLOW_COLORS[kind];
    slot.coreMat.color.setHex(hex);
    slot.glowMat.color.setHex(hex);
    slot.packetCoverMat.color.setHex(hex);
    slot.packetCoverMat.emissive.setHex(hex);
    slot.ringMat.color.setHex(hex);
  }

  function emitFlow(
    from: AgentId,
    to: AgentId,
    fromPos: THREE.Vector3,
    toPos: THREE.Vector3,
    kind: FlowKind,
    label: string,
    nowSec: number,
  ): void {
    if (from === to) return;
    traceMode = false;
    settlingFast = false;
    const key = `${from}>${to}:${kind}`;
    const slot = acquireSlot(key);
    const slotIdx = slots.indexOf(slot);

    slot.inUse = true;
    slot.key = key;
    slot.from = from;
    slot.to = to;
    slot.kind = kind;
    slot.label = label || FLOW_KIND_LABELS_VI[kind];
    slot.emittedAt = nowSec;
    slot.packetProgress = 0;
    slot.packetSpeed = kind === 'revise' ? 1.15 : 1.42;
    slot.activeUntil = nowSec + 2.35;
    slot.arrivedSignaled = false;
    slot.coreMesh.visible = true;
    slot.glowMesh.visible = true;
    slot.packetGroup.visible = true;

    applyColor(slot, kind);
    writeCurve(slot, fromPos, toPos, kind, slotIdx);
  }

  function syncEdges(
    edges: FlowEdge[],
    getPos: (id: AgentId) => THREE.Vector3 | null,
    nowSec: number,
  ): void {
    for (const e of edges) {
      const key = `${e.from}>${e.to}:${e.kind}`;
      if (slots.some((s) => s.inUse && s.key === key)) continue;
      const fp = getPos(e.from);
      const tp = getPos(e.to);
      if (!fp || !tp) continue;
      const slot = acquireSlot(key);
      const slotIdx = slots.indexOf(slot);
      slot.inUse = true;
      slot.key = key;
      slot.from = e.from;
      slot.to = e.to;
      slot.kind = e.kind;
      slot.label = e.label || FLOW_KIND_LABELS_VI[e.kind];
      slot.emittedAt = nowSec - 0.5;
      slot.packetProgress = 2;
      slot.arrivedSignaled = true;
      slot.activeUntil = nowSec - 1;
      slot.coreMesh.visible = traceMode;
      slot.glowMesh.visible = traceMode;
      slot.packetGroup.visible = false;
      applyColor(slot, e.kind);
      writeCurve(slot, fp, tp, e.kind, slotIdx);
    }
  }

  function setTraceMode(trace: boolean): void {
    traceMode = trace;
    for (const slot of slots) {
      if (!slot.inUse) continue;
      if (trace) {
        slot.coreMat.opacity = Math.max(slot.coreMat.opacity, 0.62);
        slot.glowMat.opacity = Math.max(slot.glowMat.opacity, 0.18);
        slot.coreMesh.visible = true;
        slot.glowMesh.visible = true;
      }
    }
  }

  function syncActiveWorkers(activeWorkers: Set<AgentId>, finished: boolean, nowSec: number): void {
    if (finished || activeWorkers.size === 0) {
      fastSettle();
      return;
    }
    const isParallel = activeWorkers.size > 1;
    for (const slot of slots) {
      if (!slot.inUse) continue;
      // Luồng phục vụ Agent nào đang làm việc (đích 'to' đang làm, hoặc đang giao kết quả từ 'from' tới 'integrator') mới được giữ sáng!
      const recipientWorking = activeWorkers.has(slot.to);
      const senderWorking = activeWorkers.has(slot.from);
      const isResultToIntegrator =
        (slot.kind === 'result' || slot.kind === 'approve' || slot.kind === 'fail') &&
        slot.to === 'integrator' &&
        activeWorkers.has('integrator');
      const keepAlive = recipientWorking || (isParallel && senderWorking) || isResultToIntegrator;

      if (!keepAlive) {
        // Agent liên quan đã xong việc -> tắt ngay luồng nối của nó (không để dây thừa treo lơ lửng!)
        slot.activeUntil = 0;
        if (slot.packetProgress < 1) slot.packetSpeed = 5.5;
      } else if (isParallel && recipientWorking) {
        // Nhiều Agent đang làm việc song song cùng lúc -> giữ sáng nhẹ các luồng song song tới khi từng Agent xong việc
        slot.activeUntil = Math.max(slot.activeUntil, nowSec + 1.8);
      }
    }
  }

  function fastSettle(): void {
    settlingFast = true;
    traceMode = false; // Mặc định tắt sạch dây khi câu trả lời đã gửi (chỉ bật lại nếu người dùng chọn "Sơ đồ luồng")
    for (const slot of slots) {
      if (!slot.inUse) continue;
      slot.activeUntil = 0;
      if (slot.packetProgress < 1) {
        slot.packetSpeed = 6.0; // chốt gọn gói đang bay trong <= 0.16s rồi tắt mượt!
      }
    }
  }

  function clear(): void {
    traceMode = false;
    settlingFast = false;
    for (let i = 0; i < slots.length; i++) {
      const s = slots[i];
      s.inUse = false;
      s.key = '';
      s.coreMesh.visible = false;
      s.glowMesh.visible = false;
      s.packetGroup.visible = false;
      s.ring.visible = false;
      s.packetProgress = 2;
      s.ringPulse = 2;
      s.arrivedSignaled = true;
    }
    for (let i = 0; i < totalArrows; i++) {
      arrowInst.setMatrixAt(i, zeroMat);
    }
    arrowInst.instanceMatrix.needsUpdate = true;
  }

  function hasActiveTraffic(): boolean {
    for (const s of slots) {
      if (!s.inUse) continue;
      if (s.packetProgress < 1 || s.ringPulse < 1) return true;
    }
    return false;
  }

  function getRecentLogs(limit = 4): FlowLogItem[] {
    return slots
      .filter((s) => s.inUse)
      .sort((a, b) => b.emittedAt - a.emittedAt)
      .slice(0, limit)
      .map((s) => ({
        id: s.key,
        from: s.from,
        to: s.to,
        fromName: compactName(s.from),
        toName: compactName(s.to),
        kind: s.kind,
        colorHex: FLOW_HEX[s.kind],
        label: s.label,
        active: s.packetProgress < 1,
      }));
  }

  function update(
    dt: number,
    nowSec: number,
    speedMultiplier: number,
    onArrive?: (from: AgentId, to: AgentId, kind: FlowKind) => void,
  ): void {
    const speedFactor = settlingFast ? 1.0 : Math.min(2.5, Math.max(1, speedMultiplier * 0.85));
    let anyArrowVisible = false;

    for (let i = 0; i < slots.length; i++) {
      const s = slots[i];
      if (!s.inUse) {
        for (let p = 0; p < ARROWS_PER_ARC; p++) {
          arrowInst.setMatrixAt(i * ARROWS_PER_ARC + p, zeroMat);
        }
        continue;
      }

      const isHot = nowSec < s.activeUntil || s.packetProgress < 1;
      // Chỉ hiện dây khi 2 Agent ĐANG thực sự trao đổi (hoặc khi người dùng chủ động bật chế độ Sơ đồ luồng lịch sử)
      const targetCoreOp = isHot ? 0.94 : traceMode ? 0.62 : 0;
      const targetGlowOp = isHot ? 0.28 : traceMode ? 0.16 : 0;

      s.coreMat.opacity = THREE.MathUtils.lerp(s.coreMat.opacity, targetCoreOp, Math.min(1, dt * (isHot ? 10 : 7)));
      s.glowMat.opacity = THREE.MathUtils.lerp(s.glowMat.opacity, targetGlowOp, Math.min(1, dt * (isHot ? 10 : 7)));
      s.coreMesh.visible = s.coreMat.opacity > 0.025;
      s.glowMesh.visible = s.glowMat.opacity > 0.015;

      // 1. Gói Hồ Sơ 3D bay dọc cung, xoay mượt theo tiếp tuyến đường cong
      if (s.packetProgress < 1) {
        s.packetProgress += dt * s.packetSpeed * speedFactor;
        if (s.packetProgress >= 1) {
          s.packetGroup.visible = false;
          s.ringPulse = 0;
          s.ring.visible = true;
          if (!s.arrivedSignaled) {
            s.arrivedSignaled = true;
            onArrive?.(s.from, s.to, s.kind);
          }
        } else {
          s.packetGroup.visible = true;
          s.curve.getPoint(s.packetProgress, s.packetGroup.position);
          s.curve.getTangent(s.packetProgress, tempTan).normalize();
          s.packetGroup.rotation.set(
            -Math.asin(THREE.MathUtils.clamp(tempTan.y, -0.9, 0.9)) * 0.7,
            Math.atan2(tempTan.x, tempTan.z),
            Math.sin(s.packetProgress * Math.PI) * 0.2,
          );
          const sc = 0.92 + Math.sin(s.packetProgress * Math.PI) * 0.32;
          s.packetGroup.scale.setScalar(sc);
        }
      } else {
        s.packetGroup.visible = false;
      }

      // 2. Vòng sóng tiếp nhận dưới chân Agent đích
      if (s.ringPulse < 1) {
        s.ringPulse += dt * (settlingFast ? 3.2 : 1.45);
        if (s.ringPulse >= 1) {
          s.ring.visible = false;
        } else {
          s.ring.visible = true;
          const ease = 1 - Math.pow(1 - s.ringPulse, 2);
          s.ring.scale.setScalar(0.85 + ease * 1.55);
          s.ringMat.opacity = (1 - ease) * 0.8;
        }
      } else {
        s.ring.visible = false;
      }

      // 3. Chuỗi Mũi Tên Nón 3D chạy theo tiếp tuyến đường cong chỉ rõ hướng Từ -> Tới (tắt sạch khi dây đã ẩn!)
      s.flowPhase = (s.flowPhase + dt * (isHot ? 0.68 : 0.24) * speedFactor) % 1;
      const arrowCount = isHot ? ARROWS_PER_ARC : traceMode ? 2 : 0;
      tempCol.setHex(FLOW_COLORS[s.kind]);

      for (let p = 0; p < ARROWS_PER_ARC; p++) {
        const instIdx = i * ARROWS_PER_ARC + p;
        if (p < arrowCount) {
          const u = (s.flowPhase + p / arrowCount) % 1;
          s.curve.getPoint(u, tempPt);
          s.curve.getTangent(u, tempTan).normalize();
          const edgeFade = Math.sin(u * Math.PI);
          const sc = (isHot ? 1.08 : 0.72) * (0.45 + edgeFade * 0.7);
          dummy.position.copy(tempPt);
          tempQuat.setFromUnitVectors(upAxis, tempTan);
          dummy.quaternion.copy(tempQuat);
          dummy.scale.set(sc, sc * 1.15, sc);
          dummy.updateMatrix();
          arrowInst.setMatrixAt(instIdx, dummy.matrix);
          arrowInst.setColorAt(instIdx, tempCol);
          anyArrowVisible = true;
        } else {
          arrowInst.setMatrixAt(instIdx, zeroMat);
        }
      }
    }

    arrowInst.visible = anyArrowVisible;
    arrowInst.instanceMatrix.needsUpdate = true;
    if (arrowInst.instanceColor) arrowInst.instanceColor.needsUpdate = true;
  }

  function projectBadges(
    camera: THREE.Camera,
    width: number,
    height: number,
    nowSec: number,
  ): ProjectedFlowBadge[] {
    // Hiển thị tối đa 3 nhãn đường truyền rõ ràng "Từ ➔ Đến · Nội dung" của các luồng đang nóng
    const hot = slots
      .filter((s) => s.inUse && s.label && (nowSec < s.activeUntil || s.packetProgress < 1))
      .sort((a, b) => b.activeUntil - a.activeUntil);

    const out: ProjectedFlowBadge[] = [];
    const seenKeys = new Set<string>();
    for (const s of hot) {
      if (out.length >= 3) break;
      if (seenKeys.has(s.key)) continue;
      projVec.copy(s.midPoint);
      projVec.y += 0.28;
      projVec.project(camera);
      if (projVec.z > 1) continue;
      const x = Math.round((projVec.x * 0.5 + 0.5) * width);
      const y = Math.round((-projVec.y * 0.5 + 0.5) * height);
      if (x < 70 || x > width - 70 || y < 64 || y > height - 64) continue;
      if (out.some((o) => Math.abs(o.x - x) < 185 && Math.abs(o.y - y) < 36)) continue;
      seenKeys.add(s.key);
      const fromName = compactName(s.from);
      const toName = compactName(s.to);
      out.push({
        key: s.key,
        from: s.from,
        to: s.to,
        routeText: `${fromName} ➔ ${toName}`,
        label: s.label,
        kind: s.kind,
        colorHex: FLOW_HEX[s.kind],
        x,
        y,
        active: s.packetProgress < 1,
      });
    }
    return out;
  }

  function dispose(): void {
    clear();
    for (const s of slots) {
      s.coreMesh.geometry.dispose();
      s.coreMat.dispose();
      s.glowMesh.geometry.dispose();
      s.glowMat.dispose();
      s.packetCoverMat.dispose();
      s.ringMat.dispose();
    }
    folderCoverGeo.dispose();
    folderPaperGeo.dispose();
    folderTabGeo.dispose();
    paperWhiteMat.dispose();
    ringGeo.dispose();
    arrowGeo.dispose();
    arrowMat.dispose();
  }

  return {
    group,
    emitFlow,
    syncEdges,
    syncActiveWorkers,
    setTraceMode,
    fastSettle,
    clear,
    hasActiveTraffic,
    getRecentLogs,
    update,
    projectBadges,
    dispose,
  };
}
