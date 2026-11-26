import * as THREE from 'three';
import { AGENT_PROFILES } from '../agents';
import type { AgentId, CarryItemKind, RobotAction } from '../types';
import type { StudioMaterialLibrary } from './materials';

export interface BeanRobotInstance {
  id: AgentId;
  root: THREE.Group;
  collider: THREE.Mesh;
  position: THREE.Vector3;
  action: RobotAction;
  carryItem: CarryItemKind;
  setHighlighted: (hovered: boolean, selected: boolean, isLead?: boolean) => void;
  setCarryItem: (kind: CarryItemKind) => void;
  setPoseTarget: (
    x: number,
    z: number,
    yaw: number,
    action: RobotAction,
    isMoving?: boolean,
    seated?: boolean,
  ) => void;
  lookAtWorld?: (worldX: number, worldZ: number, durationSec?: number) => void;
  triggerReaction?: (kind: 'happy' | 'worried' | 'excited', durationSec?: number) => void;
  getLabelAnchorWorld: (out: THREE.Vector3) => THREE.Vector3;
  update: (dt: number, elapsed: number) => void;
  dispose: () => void;
}

/**
 * 6 biểu cảm chuẩn đã duyệt trên Mẫu Agent V12:
 * - cat: Thân thiện / Sẵn sàng (mắt tròn mí chéo + miệng mèo ω)
 * - focused: Quyết tâm tập trung (mắt xếch sắc nét)
 * - squint: Cười híp hài lòng (mắt cong dịu dễ thương)
 * - sleep: Ngủ / Nghỉ tiết kiệm (mắt nhắm cong + miệng o + zZ)
 * - thinking: Suy nghĩ / Phân rã (mắt 1 lớn 1 nhỏ nheo + 3 chấm suy nghĩ)
 * - alert: Cảnh báo / Soát lỗi QC (mắt nhíu sắc + miệng zig-zag + dấu chấm than !)
 */
type V12Mood = 'cat' | 'focused' | 'squint' | 'sleep' | 'thinking' | 'alert';

const ITEM_COLOR_MAP: Record<CarryItemKind, number> = {
  none: 0xffffff,
  request_brief: 0xd97706,
  plan_card: 0x3730a3,
  rag_folder: 0x0891b2,
  specialist_doc: 0xea580c,
  analytics_sheet: 0x2563eb,
  approved_sheet: 0x15803d,
  final_report: 0x7c3aed,
};

const OLED_EYE_COLOR: Record<AgentId, string> = {
  orchestrator: '#fbbf24',
  rag: '#22d3ee',
  analyst: '#60a5fa',
  reviewer: '#fb7185',
  integrator: '#c084fc',
  software: '#818cf8',
  business: '#fdba74',
  marketing: '#fb923c',
  hr: '#f472b6',
  finance: '#4ade80',
  education: '#e879f9',
};

const HEAD_R = 0.285;
const HEAD_SCALE: [number, number, number] = [1.04, 0.98, 0.95];

/** Chiều cao sàn tại vị trí z (khớp Bục Chỉ Huy nâng cao +0.28m của Command Atrium V3, vuốt mượt qua bậc thang). */
export function getOfficeFloorY(z: number): number {
  if (z <= -2.72) return 0.28;
  if (z >= -2.18) return 0;
  const t = (-2.18 - z) / (-2.18 - -2.72);
  return 0.28 * Math.max(0, Math.min(1, t));
}

function shortestAngleDelta(current: number, target: number): number {
  let diff = (target - current + Math.PI) % (Math.PI * 2);
  if (diff < 0) diff += Math.PI * 2;
  return diff - Math.PI;
}

/** Thân trứng cân đối đầy đặn chuẩn Mẫu V12 (~82% bề ngang đầu). */
function createV12TorsoGeo(): THREE.LatheGeometry {
  const pts = [
    new THREE.Vector2(0.0, 0.0),
    new THREE.Vector2(0.105, 0.016),
    new THREE.Vector2(0.184, 0.074),
    new THREE.Vector2(0.23, 0.165),
    new THREE.Vector2(0.244, 0.27),
    new THREE.Vector2(0.236, 0.372),
    new THREE.Vector2(0.208, 0.452),
    new THREE.Vector2(0.164, 0.506),
    new THREE.Vector2(0.118, 0.532),
    new THREE.Vector2(0.0, 0.538),
  ];
  const g = new THREE.LatheGeometry(pts, 44, Math.PI, Math.PI * 2);
  g.computeVertexNormals();
  return g;
}

/** Mặt kính đen Squircle cong siêu mịn khớp khít đầu cầu V12. */
function createV12VisorGeo(): THREE.BufferGeometry {
  const segX = 36;
  const segY = 30;
  const pos: number[] = [];
  const norm: number[] = [];
  const uvs: number[] = [];
  const idx: number[] = [];
  const rVisor = HEAD_R + 0.0028;

  for (let iy = 0; iy <= segY; iy++) {
    const v = iy / segY;
    const ny = (v - 0.5) * 2;
    for (let ix = 0; ix <= segX; ix++) {
      const u = ix / segX;
      const nx = (u - 0.5) * 2;
      const pwr = 2.65;
      const ax = Math.abs(nx);
      const ay = Math.abs(ny);
      const rp = Math.pow(ax, pwr) + Math.pow(ay, pwr);
      const rm = Math.max(ax, ay);
      const sc = rp > 1e-6 ? rm / Math.pow(rp, 1 / pwr) : 1;
      const sx = nx * sc * 0.818;
      const sy = ny * sc * 0.738 - 0.038;
      const sz = Math.sqrt(Math.max(0.03, 1 - sx * sx - sy * sy));
      const len = Math.hypot(sx, sy, sz);
      const dx = sx / len;
      const dy = sy / len;
      const dz = sz / len;
      pos.push(dx * rVisor, dy * rVisor, dz * rVisor);
      norm.push(dx, dy, dz);
      uvs.push(u, v);
    }
  }
  for (let iy = 0; iy < segY; iy++) {
    for (let ix = 0; ix < segX; ix++) {
      const a = iy * (segX + 1) + ix;
      const b = a + 1;
      const c = a + (segX + 1);
      const d = c + 1;
      idx.push(a, b, d, a, d, c);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(norm, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  g.setIndex(idx);
  return g;
}

/** Cánh tay cánh dẹt vuốt nhọn mềm 2 mặt chuẩn Eilik/EVA (V12 đã chốt, xoay linh hoạt từ khớp vai). */
function createV12WingArmGeo(side: -1 | 1): THREE.BufferGeometry {
  const pts = [
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(side * 0.062, -0.058, 0.008),
    new THREE.Vector3(side * 0.076, -0.175, 0.018),
    new THREE.Vector3(side * 0.044, -0.315, 0.032),
  ];
  const curve = new THREE.CatmullRomCurve3(pts);
  const segLen = 28;
  const segRad = 22;
  const pos: number[] = [];
  const uvs: number[] = [];
  const idx: number[] = [];
  const zAxis = new THREE.Vector3(0, 0, 1);
  let prevOut: THREE.Vector3 | null = null;
  let flipWinding = false;

  for (let i = 0; i <= segLen; i++) {
    const t = i / segLen;
    const p = curve.getPointAt(t);
    const tan = curve.getTangentAt(t).normalize();
    const bladeAxis = zAxis.clone().addScaledVector(tan, -zAxis.dot(tan)).normalize();
    const outAxis = new THREE.Vector3().crossVectors(bladeAxis, tan).normalize();
    if (prevOut === null) {
      if (outAxis.x * side < 0) outAxis.negate();
      flipWinding = new THREE.Vector3().crossVectors(outAxis, bladeAxis).dot(tan) < 0;
    } else if (prevOut.dot(outAxis) < 0) {
      outAxis.negate();
    }
    prevOut = outAxis.clone();

    const bladeProfile = Math.sin(Math.pow(t, 0.74) * Math.PI);
    const thickProfile = Math.pow(Math.max(0.0001, 1 - t * 0.72), 0.65);
    let tipCap = 1.0;
    if (t > 0.86) tipCap = Math.pow(Math.max(0.0001, (1 - t) / 0.14), 0.56);
    else if (t < 0.09) tipCap = Math.sqrt(Math.max(0.0001, 1 - Math.pow(1 - t / 0.09, 2)));

    const rThick = Math.max(0.0008, 0.043 * (0.52 + 0.5 * thickProfile) * tipCap);
    const rBlade = Math.max(0.0008, 0.066 * (0.34 + 0.72 * bladeProfile) * tipCap);

    for (let j = 0; j <= segRad; j++) {
      const a = (j / segRad) * Math.PI * 2;
      const ca = Math.cos(a);
      const sa = Math.sin(a);
      pos.push(
        p.x + outAxis.x * (ca * rThick) + bladeAxis.x * (sa * rBlade),
        p.y + outAxis.y * (ca * rThick) + bladeAxis.y * (sa * rBlade),
        p.z + outAxis.z * (ca * rThick) + bladeAxis.z * (sa * rBlade),
      );
      uvs.push(ca * 0.5 + 0.5, t);
    }
  }
  for (let i = 0; i < segLen; i++) {
    for (let j = 0; j < segRad; j++) {
      const a = i * (segRad + 1) + j;
      const b = a + 1;
      const c = a + (segRad + 1);
      const d = c + 1;
      if (!flipWinding) idx.push(a, b, d, a, d, c);
      else idx.push(a, d, b, a, c, d);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/** Tai mảnh đặc kín bo tròn áp sát má đầu chuẩn V12. */
function createV12EarGeo(side: -1 | 1): { outer: THREE.BufferGeometry; inner: THREE.BufferGeometry } {
  const outerShape = new THREE.Shape();
  outerShape.moveTo(0, 0.082);
  outerShape.quadraticCurveTo(side * 0.054, 0.074, side * 0.054, 0);
  outerShape.quadraticCurveTo(side * 0.054, -0.074, 0, -0.082);
  outerShape.closePath();
  const outer = new THREE.ExtrudeGeometry(outerShape, {
    depth: 0.028,
    bevelEnabled: true,
    bevelThickness: 0.009,
    bevelSize: 0.008,
    bevelSegments: 4,
    curveSegments: 16,
  });
  outer.center();

  const innerShape = new THREE.Shape();
  innerShape.moveTo(0, 0.06);
  innerShape.quadraticCurveTo(side * 0.036, 0.054, side * 0.036, 0);
  innerShape.quadraticCurveTo(side * 0.036, -0.054, 0, -0.06);
  innerShape.closePath();
  const inner = new THREE.ExtrudeGeometry(innerShape, {
    depth: 0.033,
    bevelEnabled: false,
    curveSegments: 14,
  });
  inner.center();

  return { outer, inner };
}

function createV12TorsoTexture(accentHex: string, code: string): THREE.CanvasTexture {
  const w = 512;
  const h = 512;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = '#f5f4f0';
  ctx.fillRect(0, 0, w, h);

  // Vòng cổ màu nhấn ôm êm dưới cằm
  ctx.fillStyle = accentHex;
  ctx.fillRect(0, 0, w, 68);

  // Yếm giọt nước mềm chính giữa ngực (không viền gắt)
  ctx.beginPath();
  ctx.moveTo(176, 60);
  ctx.bezierCurveTo(213, 90, 226, 138, 232, 220);
  ctx.arc(256, 222, 24, Math.PI, 0, true);
  ctx.bezierCurveTo(286, 138, 299, 90, 336, 60);
  ctx.closePath();
  ctx.fill();

  // Chấm mic mảnh giữa bụng
  ctx.fillStyle = 'rgba(71, 85, 105, 0.52)';
  ctx.beginPath();
  ctx.arc(256, 270, 2.8, 0, Math.PI * 2);
  ctx.fill();

  // Mã nhận diện nhỏ thanh lịch C27·XX
  ctx.fillStyle = 'rgba(71, 85, 105, 0.80)';
  ctx.font = '700 16px "Segoe UI", sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(`C27·${code}`, 292, 174);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

function createV12TwoToneArmTexture(accentHex: string): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 128;
  c.height = 32;
  const ctx = c.getContext('2d')!;
  const g = ctx.createLinearGradient(0, 0, 128, 0);
  g.addColorStop(0.0, accentHex);
  g.addColorStop(0.45, accentHex);
  g.addColorStop(0.55, '#f5f4f0');
  g.addColorStop(1.0, '#f5f4f0');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 32);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/**
 * Bộ 6 biểu cảm OLED V12 sắc nét trên nền kính đen sâu (512×512) + tự động chớp mắt:
 * 1. cat: Mắt tròn mí chéo + miệng mèo ω (thân thiện / giao tiếp / sẵn sàng)
 * 2. focused: Mắt xếch sắc nét (tập trung gõ máy, chạy RAG, phân tích)
 * 3. squint: Mắt cười híp dịu (hoàn thành, đạt QC, hài lòng)
 * 4. sleep: Mắt nhắm cong + miệng o nhỏ + zZ (ngủ tiết kiệm tài nguyên)
 * 5. thinking: Mắt 1 lớn 1 nhỏ nheo liếc lên + 3 chấm suy nghĩ (đang phân rã / chờ LLM)
 * 6. alert: Mắt nhíu cảnh báo + miệng zig-zag + chấm than vàng ! (Reviewer trả bài / lỗi QC)
 */
function createV12OledFace(eyeHex: string): {
  texture: THREE.CanvasTexture;
  draw: (mood: V12Mood, blink: boolean, lookX: number) => void;
} {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext('2d')!;
  const texture = new THREE.CanvasTexture(c);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;

  const draw = (mood: V12Mood, blink: boolean, lookX: number) => {
    ctx.fillStyle = '#030508';
    ctx.fillRect(0, 0, 512, 512);

    const ox = lookX * 14;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    if (mood === 'sleep') {
      ctx.strokeStyle = '#94b8d8';
      ctx.fillStyle = '#94b8d8';
      ctx.shadowColor = '#60a5fa';
      ctx.shadowBlur = 5;
      ctx.lineWidth = 14;
      ctx.beginPath();
      ctx.arc(164, 248, 54, 0.14 * Math.PI, 0.86 * Math.PI, false);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(348, 248, 54, 0.14 * Math.PI, 0.86 * Math.PI, false);
      ctx.stroke();
      ctx.lineWidth = 9;
      ctx.beginPath();
      ctx.ellipse(256, 326, 13, 11, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.font = '800 40px "Segoe UI", sans-serif';
      ctx.fillText('z', 372, 184);
      ctx.font = '800 26px "Segoe UI", sans-serif';
      ctx.fillText('z', 402, 156);
    } else if (blink) {
      // Nhịp chớp mắt tự nhiên (~160ms)
      ctx.strokeStyle = mood === 'cat' ? '#cfe4f7' : eyeHex;
      ctx.shadowColor = eyeHex;
      ctx.shadowBlur = 6;
      ctx.lineWidth = 14;
      ctx.beginPath();
      ctx.moveTo(106 + ox, 256);
      ctx.quadraticCurveTo(164 + ox, 272, 222 + ox, 256);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(290 + ox, 256);
      ctx.quadraticCurveTo(348 + ox, 272, 406 + ox, 256);
      ctx.stroke();
    } else if (mood === 'cat') {
      ctx.fillStyle = '#cfe4f7';
      ctx.shadowColor = '#93c5fd';
      ctx.shadowBlur = 6;
      ctx.beginPath();
      ctx.ellipse(163 + ox, 244, 67, 67, 0, 0, Math.PI * 2);
      ctx.ellipse(349 + ox, 244, 67, 67, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = '#030508';
      ctx.lineWidth = 8;
      ctx.beginPath();
      ctx.moveTo(94 + ox, 222);
      ctx.lineTo(233 + ox, 267);
      ctx.moveTo(418 + ox, 222);
      ctx.lineTo(279 + ox, 267);
      ctx.stroke();
      ctx.strokeStyle = '#cfe4f7';
      ctx.shadowBlur = 5;
      ctx.lineWidth = 11;
      ctx.beginPath();
      ctx.arc(233 + ox, 318, 22, 0.12 * Math.PI, 0.9 * Math.PI, false);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(279 + ox, 318, 22, 0.1 * Math.PI, 0.88 * Math.PI, false);
      ctx.stroke();
    } else if (mood === 'focused') {
      ctx.fillStyle = eyeHex;
      ctx.shadowColor = eyeHex;
      ctx.shadowBlur = 7;
      const drawEye = (side: -1 | 1) => {
        ctx.save();
        ctx.translate(256 + ox + side * 95, 260);
        ctx.beginPath();
        ctx.moveTo(side * 82, -56);
        ctx.quadraticCurveTo(side * 20, -15, -side * 67, -10);
        ctx.quadraticCurveTo(-side * 81, 53, -side * 8, 67);
        ctx.quadraticCurveTo(side * 81, 71, side * 82, -56);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      };
      drawEye(-1);
      drawEye(1);
    } else if (mood === 'squint') {
      ctx.fillStyle = eyeHex;
      ctx.shadowColor = eyeHex;
      ctx.shadowBlur = 7;
      const drawHalf = (cx: number, cy: number, tilt: number) => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(tilt);
        ctx.beginPath();
        ctx.ellipse(0, 8, 76, 50, 0, Math.PI, Math.PI * 2, false);
        ctx.quadraticCurveTo(76, 21, 0, 13);
        ctx.quadraticCurveTo(-76, 21, -76, 8);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      };
      drawHalf(159 + ox, 261, -0.09);
      drawHalf(353 + ox, 261, 0.09);
    } else if (mood === 'thinking') {
      ctx.fillStyle = '#7dd3fc';
      ctx.strokeStyle = '#7dd3fc';
      ctx.shadowColor = '#38bdf8';
      ctx.shadowBlur = 6;
      ctx.beginPath();
      ctx.ellipse(171 + ox, 231, 61, 64, -0.06, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(353 + ox, 240, 59, 46, 0.08, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#030508';
      ctx.fillRect(287 + ox, 188, 132, 26);
      ctx.strokeStyle = '#7dd3fc';
      ctx.shadowBlur = 5;
      ctx.lineWidth = 11;
      ctx.beginPath();
      ctx.moveTo(229 + ox, 326);
      ctx.quadraticCurveTo(258 + ox, 314, 287 + ox, 326);
      ctx.stroke();
      ctx.fillStyle = '#bae6fd';
      [346, 371, 396].forEach((cx, i) => {
        ctx.beginPath();
        ctx.arc(cx + ox * 0.5, 168 - i * 4, 6.5 + i, 0, Math.PI * 2);
        ctx.fill();
      });
    } else if (mood === 'alert') {
      ctx.fillStyle = '#fb7185';
      ctx.strokeStyle = '#fb7185';
      ctx.shadowColor = '#f43f5e';
      ctx.shadowBlur = 8;
      const drawAlertEye = (side: -1 | 1) => {
        ctx.save();
        ctx.translate(256 + ox + side * 94, 252);
        ctx.beginPath();
        ctx.moveTo(side * 75, -49);
        ctx.quadraticCurveTo(side * 12, -22, -side * 62, -5);
        ctx.quadraticCurveTo(-side * 70, 44, -side * 6, 56);
        ctx.quadraticCurveTo(side * 72, 57, side * 75, -49);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      };
      drawAlertEye(-1);
      drawAlertEye(1);
      ctx.lineWidth = 11;
      ctx.beginPath();
      ctx.moveTo(209 + ox, 334);
      ctx.lineTo(232 + ox, 321);
      ctx.lineTo(256 + ox, 334);
      ctx.lineTo(280 + ox, 321);
      ctx.lineTo(303 + ox, 334);
      ctx.stroke();
      ctx.fillStyle = '#fbbf24';
      ctx.shadowColor = '#f59e0b';
      ctx.beginPath();
      ctx.roundRect(248, 133, 16, 46, 8);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(256, 196, 9, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.restore();
    texture.needsUpdate = true;
  };

  draw('sleep', false, 0);
  return { texture, draw };
}

/**
 * Mẫu Nhân vật Agent 3D V12 (đã chốt):
 * - Đầu cầu tròn đều tách gọn bằng khe cổ thanh lịch, tai mảnh ôm má, kính cong bóng gương sạch.
 * - Thân trứng đầy đặn cân xứng (~82% bề ngang đầu) với yếm cổ giọt nước theo màu riêng của 11 Agent.
 * - Đôi tay cánh dẹt vuốt nhọn mềm 2 mặt (trắng sứ ngoài / màu nhấn trong) chuẩn Eilik & EVA.
 * - Trọn bộ 6 biểu cảm OLED V12 + tự động chớp mắt + quay đầu nhìn đối tác + phản ứng tức thì.
 */
export function buildBeanRobotCharacter(
  id: AgentId,
  materials: StudioMaterialLibrary,
): BeanRobotInstance {
  const profile = AGENT_PROFILES[id];
  const geometries: THREE.BufferGeometry[] = [];
  const extraMats: THREE.Material[] = [];
  const extraTex: THREE.Texture[] = [];

  const trackGeo = <T extends THREE.BufferGeometry>(g: T): T => {
    geometries.push(g);
    return g;
  };
  const trackMat = <T extends THREE.Material>(m: T): T => {
    extraMats.push(m);
    return m;
  };

  const shellMat = materials.eilikCeramicShell;
  const accentMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: profile.accentNumber,
      roughness: 0.54,
      metalness: 0.0,
    }),
  );
  const earInnerMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x1e2422,
      roughness: 0.85,
      metalness: 0.0,
    }),
  );
  const neckMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x22252b,
      roughness: 0.78,
      metalness: 0.08,
    }),
  );

  const torsoTex = createV12TorsoTexture(profile.accentHex, profile.code);
  extraTex.push(torsoTex);
  const torsoMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: torsoTex,
      roughness: 0.6,
      metalness: 0.0,
    }),
  );

  const armTex = createV12TwoToneArmTexture(profile.accentHex);
  extraTex.push(armTex);
  const armMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: armTex,
      roughness: 0.56,
      metalness: 0.0,
    }),
  );

  const eyeHex = OLED_EYE_COLOR[id] ?? '#38bdf8';
  const oledFace = createV12OledFace(eyeHex);
  extraTex.push(oledFace.texture);
  const visorMat = trackMat(
    new THREE.MeshPhysicalMaterial({
      map: oledFace.texture,
      emissiveMap: oledFace.texture,
      emissive: new THREE.Color(0xffffff),
      emissiveIntensity: 0.92,
      roughness: 0.06,
      metalness: 0.04,
      clearcoat: 1.0,
      clearcoatRoughness: 0.04,
      envMapIntensity: 0.48,
    }),
  );

  const root = new THREE.Group();
  root.name = `eilik_v12_robot_${id}`;
  const startFloorY = getOfficeFloorY(profile.sleepPos[1]);
  root.position.set(profile.sleepPos[0], startFloorY, profile.sleepPos[1]);
  root.rotation.y = profile.sleepFacingYaw;
  root.scale.setScalar(1.12);

  // Bóng tiếp đất mềm dưới chân
  const shadow = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(0.84, 0.84)),
    materials.contactShadow,
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = 0.014;
  root.add(shadow);

  // Vòng radar vai trò dưới sàn (2 vòng đồng tâm khi đang hoạt động/dẫn dắt!)
  const ringMat = trackMat(
    new THREE.MeshBasicMaterial({
      color: profile.accentNumber,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  const floorRing = new THREE.Mesh(trackGeo(new THREE.RingGeometry(0.36, 0.49, 36)), ringMat);
  floorRing.rotation.x = -Math.PI / 2;
  floorRing.position.y = 0.022;
  root.add(floorRing);

  const outerRingMat = trackMat(
    new THREE.MeshBasicMaterial({
      color: profile.accentNumber,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  const outerRing = new THREE.Mesh(trackGeo(new THREE.RingGeometry(0.52, 0.62, 36)), outerRingMat);
  outerRing.rotation.x = -Math.PI / 2;
  outerRing.position.y = 0.02;
  root.add(outerRing);

  // =========================================================================
  // THÂN TRỨNG CÂN ĐỐI V12 + KHE CỔ THANH LỊCH
  // =========================================================================
  const bodyPivot = new THREE.Group();
  bodyPivot.position.y = profile.sleepSeated ? 0.42 : 0.02;
  root.add(bodyPivot);

  const torsoPivot = new THREE.Group();
  bodyPivot.add(torsoPivot);

  const torsoMesh = new THREE.Mesh(trackGeo(createV12TorsoGeo()), torsoMat);
  torsoMesh.castShadow = true;
  torsoMesh.receiveShadow = true;
  torsoPivot.add(torsoMesh);

  const neck = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.114, 0.126, 0.032, 24)), neckMat);
  neck.position.y = 0.534;
  torsoPivot.add(neck);

  // =========================================================================
  // ĐÔI TAY CÁNH DẸT VUỐT NHỌN MỀM V12 (XOAY LINH HOẠT THEO HÀNH ĐỘNG!)
  // =========================================================================
  const leftArm = new THREE.Group();
  leftArm.position.set(-0.205, 0.432, 0.008);
  const leftArmMesh = new THREE.Mesh(trackGeo(createV12WingArmGeo(-1)), armMat);
  leftArmMesh.castShadow = true;
  leftArmMesh.receiveShadow = true;
  leftArm.add(leftArmMesh);
  torsoPivot.add(leftArm);

  const rightArm = new THREE.Group();
  rightArm.position.set(0.205, 0.432, 0.008);
  const rightArmMesh = new THREE.Mesh(trackGeo(createV12WingArmGeo(1)), armMat);
  rightArmMesh.castShadow = true;
  rightArmMesh.receiveShadow = true;
  rightArm.add(rightArmMesh);
  torsoPivot.add(rightArm);

  // Đạo cụ cầm tay gọn nhẹ cho từng vai trò khi làm việc
  const leftPropRoot = new THREE.Group();
  leftPropRoot.position.set(-0.04, -0.28, 0.05);
  leftArm.add(leftPropRoot);

  const rightPropRoot = new THREE.Group();
  rightPropRoot.position.set(0.04, -0.28, 0.05);
  rightArm.add(rightPropRoot);

  const penMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: id === 'reviewer' ? 0xdc1e3c : id === 'analyst' ? 0x1d4ed8 : 0x334155,
      roughness: 0.35,
      metalness: 0.2,
    }),
  );
  const paperWhiteMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xfcfbf8, roughness: 0.85 }),
  );

  if (id === 'orchestrator') {
    const baton = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.01, 0.014, 0.32, 10)),
      materials.brassAccent,
    );
    baton.rotation.x = Math.PI * 0.44;
    baton.position.set(0, -0.02, 0.12);
    rightPropRoot.add(baton);
  } else if (id === 'analyst') {
    const pen = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.01, 0.007, 0.2, 10)), penMat);
    pen.rotation.x = Math.PI * 0.4;
    pen.position.set(0, -0.02, 0.08);
    rightPropRoot.add(pen);
  } else if (id === 'reviewer') {
    const clip = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.18, 0.24, 0.018)),
      trackMat(new THREE.MeshStandardMaterial({ color: 0xdc1e3c, roughness: 0.5 })),
    );
    clip.rotation.x = -0.45;
    leftPropRoot.add(clip);
    const sheet = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.14, 0.19, 0.022)), paperWhiteMat);
    sheet.rotation.x = -0.45;
    leftPropRoot.add(sheet);
    const pen = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.01, 0.007, 0.2, 10)), penMat);
    pen.rotation.x = Math.PI * 0.4;
    pen.position.set(0, -0.02, 0.08);
    rightPropRoot.add(pen);
  }

  // =========================================================================
  // ĐẦU TRÒN V12 + TAI MẢNH + MẶT KÍNH BÓNG GƯƠNG 6 BIỂU CẢM
  // =========================================================================
  const headPivot = new THREE.Group();
  headPivot.position.y = 0.822;
  torsoPivot.add(headPivot);

  const cranium = new THREE.Mesh(trackGeo(new THREE.SphereGeometry(HEAD_R, 42, 32)), shellMat);
  cranium.scale.set(...HEAD_SCALE);
  cranium.castShadow = true;
  cranium.receiveShadow = true;
  headPivot.add(cranium);

  const crownCap = new THREE.Mesh(
    trackGeo(new THREE.SphereGeometry(HEAD_R + 0.0022, 32, 14, 0, Math.PI * 2, 0, 0.35)),
    accentMat,
  );
  crownCap.scale.set(...HEAD_SCALE);
  headPivot.add(crownCap);

  ([-1, 1] as const).forEach((side) => {
    const earGeos = createV12EarGeo(side);
    const earGroup = new THREE.Group();
    earGroup.position.set(side * (HEAD_R * HEAD_SCALE[0] - 0.01), -0.004, -0.014);
    const outerMesh = new THREE.Mesh(trackGeo(earGeos.outer), shellMat);
    outerMesh.castShadow = true;
    earGroup.add(outerMesh);
    const innerMesh = new THREE.Mesh(trackGeo(earGeos.inner), earInnerMat);
    innerMesh.position.set(-side * 0.004, 0, 0.009);
    earGroup.add(innerMesh);
    headPivot.add(earGroup);
  });

  const visor = new THREE.Mesh(trackGeo(createV12VisorGeo()), visorMat);
  visor.scale.set(...HEAD_SCALE);
  headPivot.add(visor);

  // Tập hồ sơ mang theo khi đi bàn giao
  const carryGroup = new THREE.Group();
  carryGroup.position.set(0, 0.28, 0.34);
  carryGroup.visible = false;
  torsoPivot.add(carryGroup);

  const carryMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x009e73, roughness: 0.45, metalness: 0.05 }),
  );
  const folderBottom = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.28, 0.044, 0.2)), carryMat);
  folderBottom.castShadow = true;
  carryGroup.add(folderBottom);
  const paperMid = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.24, 0.038, 0.17)), paperWhiteMat);
  paperMid.position.y = 0.032;
  carryGroup.add(paperMid);
  const folderTop = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.26, 0.034, 0.18)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0xe07a00, roughness: 0.48 })),
  );
  folderTop.position.set(0.02, 0.064, -0.01);
  folderTop.rotation.y = 0.14;
  carryGroup.add(folderTop);

  // Hạt Zzz nhẹ khi ngủ
  const zzzGroup = new THREE.Group();
  zzzGroup.position.set(0, 1.12, 0.14);
  zzzGroup.visible = false;
  root.add(zzzGroup);

  const zSprites: THREE.Sprite[] = [];
  for (let i = 0; i < 3; i++) {
    const spMat = trackMat(materials.zzzSpriteMat.clone());
    const sp = new THREE.Sprite(spMat);
    sp.scale.setScalar(0.18 + i * 0.045);
    zzzGroup.add(sp);
    zSprites.push(sp);
  }

  // Layer-1 Click Collider
  const collider = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.42, 0.42, 1.38, 10)),
    trackMat(new THREE.MeshBasicMaterial({ visible: false })),
  );
  collider.position.y = 0.69;
  collider.userData.agentId = id;
  collider.layers.set(1);
  root.add(collider);

  // Runtime state
  let currentAction: RobotAction = 'sleeping';
  let currentCarry: CarryItemKind = 'none';
  let targetX = profile.sleepPos[0];
  let targetZ = profile.sleepPos[1];
  let targetYaw = profile.sleepFacingYaw;
  let isMovingFlag = false;
  let isSeatedFlag = profile.sleepSeated;
  let glideCycle = 0;
  let hovered = false;
  let selected = false;
  let isLeadFlag = false;
  let lastFaceKey = '';
  let faceTimer = 0;
  const phaseSeed = (parseInt(profile.code, 10) || 1) * 1.37;

  let lookAtTarget: { x: number; z: number } | null = null;
  let lookAtRemaining = 0;
  let reactionMood: V12Mood | null = null;
  let reactionRemaining = 0;

  const resolveMood = (action: RobotAction): V12Mood => {
    if (reactionMood && reactionRemaining > 0 && action !== 'sleeping') return reactionMood;
    if (action === 'sleeping') return 'sleep';
    if (action === 'waking_up' || action === 'completed') return 'squint';
    if (action === 'thinking') return 'thinking';
    if (
      action === 'working_computer' ||
      action === 'drafting_analysis' ||
      action === 'cabinet_rag' ||
      action === 'reviewing_paper' ||
      action === 'integrating'
    ) {
      return 'focused';
    }
    return 'cat';
  };

  const setCarryItem = (kind: CarryItemKind) => {
    currentCarry = kind;
    carryGroup.visible = kind !== 'none' && currentAction !== 'sleeping';
    if (kind !== 'none') carryMat.color.setHex(ITEM_COLOR_MAP[kind]);
  };

  return {
    id,
    root,
    collider,
    position: root.position,
    get action() {
      return currentAction;
    },
    get carryItem() {
      return currentCarry;
    },
    setHighlighted: (h, s, lead = false) => {
      hovered = h;
      selected = s;
      isLeadFlag = lead;
    },
    setCarryItem,
    setPoseTarget: (x, z, yaw, action, isMoving = false, seated = false) => {
      targetX = x;
      targetZ = z;
      targetYaw = yaw;
      currentAction = action;
      isMovingFlag = isMoving;
      isSeatedFlag = seated;
    },
    lookAtWorld: (worldX: number, worldZ: number, durationSec = 1.0) => {
      lookAtTarget = { x: worldX, z: worldZ };
      lookAtRemaining = Math.max(lookAtRemaining, durationSec);
    },
    triggerReaction: (kind, durationSec = 1.8) => {
      reactionMood = kind === 'worried' ? 'alert' : 'squint';
      reactionRemaining = Math.max(reactionRemaining, durationSec);
      lastFaceKey = '';
    },
    getLabelAnchorWorld: (out: THREE.Vector3) => {
      const floorY = getOfficeFloorY(root.position.z);
      const topY = floorY + (currentAction === 'sleeping' ? 1.44 : isSeatedFlag ? 1.72 : 1.48);
      return out.set(root.position.x, topY, root.position.z);
    },
    update: (dt, elapsed) => {
      root.position.x = THREE.MathUtils.damp(root.position.x, targetX, 11, dt);
      root.position.z = THREE.MathUtils.damp(root.position.z, targetZ, 11, dt);
      const floorY = getOfficeFloorY(root.position.z);
      root.position.y = THREE.MathUtils.damp(root.position.y, floorY, 12, dt);

      const yawDelta = shortestAngleDelta(root.rotation.y, targetYaw);
      root.rotation.y += yawDelta * (1 - Math.exp(-9 * dt));

      if (lookAtRemaining > 0) {
        lookAtRemaining = Math.max(0, lookAtRemaining - dt);
        if (lookAtRemaining === 0) lookAtTarget = null;
      }
      if (reactionRemaining > 0) {
        reactionRemaining = Math.max(0, reactionRemaining - dt);
        if (reactionRemaining === 0) reactionMood = null;
      }

      const isSleeping = currentAction === 'sleeping';
      const carrying = currentCarry !== 'none' && !isSleeping;
      const isActive = !isSleeping && currentAction !== 'idle' && currentAction !== 'completed';

      const showRoleProps = !isSleeping && !carrying && isActive;
      leftPropRoot.visible = showRoleProps;
      rightPropRoot.visible = showRoleProps;
      carryGroup.visible =
        carrying &&
        (isMovingFlag || currentAction === 'handing_over' || currentAction === 'cabinet_rag');

      // V10: Bỏ toàn bộ động tác thừa — khi rảnh (idle) hoặc đã xong việc (completed), robot giữ nguyên vị trí tĩnh ngay ngắn!
      let bodyY = isSeatedFlag ? 0.42 : 0.02;
      let bodyZOffset = 0;
      let torsoX = 0;
      let torsoZ = 0;
      let lArmX = carrying ? -0.92 : -0.06;
      let rArmX = carrying ? -0.92 : -0.06;
      let lArmZ = carrying ? 0.18 : 0.04;
      let rArmZ = carrying ? -0.18 : -0.04;
      let headY = 0;
      let headX = 0;
      let headZ = 0;

      if (isSleeping) {
        const breath = Math.sin(elapsed * 1.2 + phaseSeed);
        bodyY = (isSeatedFlag ? 0.39 : 0.02) + breath * 0.004;
        bodyZOffset = isSeatedFlag ? 0.12 : 0.04;
        torsoX = 0.24;
        torsoZ = 0.03;
        headX = 0.18;
        headZ = -0.12;
        headY = 0.04;
        lArmX = -0.22;
        rArmX = -0.22;
        lArmZ = 0.04;
        rArmZ = -0.04;
      } else if (currentAction === 'waking_up' || currentAction === 'completed' || currentAction === 'idle') {
        // V10: Xong việc / sẵn sàng / vừa thức — ngồi hoặc đứng ngay ngắn đúng vị trí gốc, tuyệt đối KHÔNG vẫy tay, KHÔNG nhún nhảy, KHÔNG lắc đầu thừa!
        bodyY = isSeatedFlag ? 0.42 : 0.02;
        torsoX = 0;
        torsoZ = 0;
        lArmX = -0.06;
        rArmX = -0.06;
        lArmZ = 0.04;
        rArmZ = -0.04;
        headX = 0;
        headY = 0;
        headZ = 0;
      } else if (isMovingFlag || currentAction === 'walking') {
        glideCycle += dt * 11.5;
        const waddle = Math.sin(glideCycle);
        const scootBounce = Math.abs(Math.cos(glideCycle)) * 0.022;
        bodyY = 0.02 + scootBounce;
        torsoX = 0.12;
        torsoZ = waddle * 0.06;
        headZ = -waddle * 0.03;
        headX = -0.03;
        headY = 0;
        if (carrying) {
          lArmX = -0.94;
          rArmX = -0.94;
          lArmZ = 0.16;
          rArmZ = -0.16;
        } else {
          lArmX = -0.18 - waddle * 0.22;
          rArmX = -0.18 + waddle * 0.22;
          lArmZ = 0.18;
          rArmZ = -0.18;
        }
      } else if (currentAction === 'planning_board') {
        rArmX = -1.65 + Math.sin(elapsed * 3.2) * 0.12;
        rArmZ = -0.24;
        lArmX = -0.58;
        lArmZ = 0.16;
        headY = Math.sin(elapsed * 1.6) * 0.1;
        headX = -0.08;
      } else if (currentAction === 'cabinet_rag') {
        const pull = Math.sin(elapsed * 3.8);
        rArmX = -1.02 + pull * 0.14;
        lArmX = -0.96 - pull * 0.12;
        torsoX = 0.08;
        headY = Math.sin(elapsed * 1.8) * 0.1;
        headX = 0.03;
      } else if (currentAction === 'drafting_analysis') {
        torsoX = 0.09;
        rArmX = -1.04 + Math.sin(elapsed * 7.5) * 0.08;
        rArmZ = -0.16;
        lArmX = -0.92;
        lArmZ = 0.16;
        headX = 0.12;
        headY = Math.sin(elapsed * 1.6) * 0.08;
      } else if (currentAction === 'reviewing_paper') {
        lArmX = -1.0;
        lArmZ = 0.2;
        const check = Math.sin(elapsed * 4.5);
        rArmX = check > 0.2 ? -1.18 : -0.94;
        rArmZ = -0.18;
        headX = 0.11;
        headY = Math.sin(elapsed * 1.5) * 0.08;
      } else if (currentAction === 'working_computer' || currentAction === 'integrating') {
        torsoX = 0.07;
        const tapL = Math.sin(elapsed * 10 + phaseSeed);
        const tapR = Math.cos(elapsed * 10 + phaseSeed);
        lArmX = -1.04 + tapL * 0.08;
        rArmX = -1.04 + tapR * 0.08;
        lArmZ = 0.12;
        rArmZ = -0.12;
        headX = 0.05;
        headY = Math.sin(elapsed * 1.4 + phaseSeed) * 0.06;
      } else if (currentAction === 'thinking') {
        rArmX = -1.28;
        rArmZ = 0.16;
        lArmX = -0.14;
        headZ = 0.06 * Math.sin(elapsed * 1.2 + phaseSeed);
        headX = -0.04;
        headY = 0;
      } else if (currentAction === 'brainstorming') {
        const talk = Math.sin(elapsed * 3.6 + phaseSeed);
        rArmX = -1.1 + talk * 0.14;
        rArmZ = -0.24;
        lArmX = -0.78 - talk * 0.1;
        lArmZ = 0.22;
        headY = Math.sin(elapsed * 1.8 + phaseSeed) * 0.12;
      } else if (currentAction === 'handing_over' || currentAction === 'receiving') {
        lArmX = -0.96;
        rArmX = -0.96;
        lArmZ = 0.12;
        rArmZ = -0.12;
        torsoX = 0.05;
        headX = 0.04;
      }

      if (isActive && lookAtTarget && lookAtRemaining > 0) {
        const desiredWorldYaw = Math.atan2(
          lookAtTarget.x - root.position.x,
          lookAtTarget.z - root.position.z,
        );
        const relYaw = shortestAngleDelta(root.rotation.y, desiredWorldYaw);
        headY = THREE.MathUtils.clamp(relYaw, -0.58, 0.58);
        headX = -0.03;
      }

      bodyPivot.position.y = THREE.MathUtils.damp(bodyPivot.position.y, bodyY, 9.5, dt);
      bodyPivot.position.z = THREE.MathUtils.damp(bodyPivot.position.z, bodyZOffset, 9.5, dt);
      torsoPivot.rotation.x = THREE.MathUtils.damp(torsoPivot.rotation.x, torsoX, 9, dt);
      torsoPivot.rotation.z = THREE.MathUtils.damp(torsoPivot.rotation.z, torsoZ, 9.5, dt);
      leftArm.rotation.x = THREE.MathUtils.damp(leftArm.rotation.x, lArmX, 10, dt);
      rightArm.rotation.x = THREE.MathUtils.damp(rightArm.rotation.x, rArmX, 10, dt);
      leftArm.rotation.z = THREE.MathUtils.damp(leftArm.rotation.z, lArmZ, 10, dt);
      rightArm.rotation.z = THREE.MathUtils.damp(rightArm.rotation.z, rArmZ, 10, dt);
      headPivot.rotation.y = THREE.MathUtils.damp(headPivot.rotation.y, headY, 9, dt);
      headPivot.rotation.x = THREE.MathUtils.damp(headPivot.rotation.x, headX, 9, dt);
      headPivot.rotation.z = THREE.MathUtils.damp(headPivot.rotation.z, headZ, 9, dt);

      // Cập nhật biểu cảm V12 (~12fps) + chớp mắt tự nhiên
      faceTimer += dt;
      if (faceTimer >= 0.085) {
        faceTimer = 0;
        const mood = resolveMood(currentAction);
        const blink = !isSleeping && mood !== 'alert' && (elapsed + phaseSeed) % 4.3 > 4.14;
        const lookStep = isActive ? Math.round(Math.sin(elapsed * 1.1 + phaseSeed) * 2) / 2 : 0;
        const key = `${mood}_${blink ? 1 : 0}_${lookStep}`;
        if (key !== lastFaceKey) {
          lastFaceKey = key;
          oledFace.draw(mood, blink, lookStep);
          visorMat.emissiveIntensity = mood === 'sleep' ? 0.68 : 0.94;
        }
      }

      zzzGroup.visible = isSleeping;
      if (isSleeping) {
        zSprites.forEach((sp, i) => {
          const cycle = (elapsed * 0.45 + phaseSeed + i * 0.33) % 1;
          sp.position.set(
            Math.sin(cycle * Math.PI * 2 + i) * 0.1 + i * 0.07,
            cycle * 0.62,
            0.12,
          );
          const sc = (0.13 + cycle * 0.11) * (1 - cycle * 0.25);
          sp.scale.setScalar(sc);
          sp.material.opacity = Math.sin(cycle * Math.PI) * 0.88;
        });
      }

      // V10: Vòng radar sàn CHỈ sáng cho Agent đang thực sự làm việc (xong việc/ngủ tắt sạch, tránh nhấp nháy thừa!)
      const glideGlow = isMovingFlag ? 0.72 : 0;
      const leadPulse = isLeadFlag && isActive ? 0.76 + Math.sin(elapsed * 3.6) * 0.14 : 0;
      const targetRing = Math.max(
        glideGlow,
        isLeadFlag && isActive ? leadPulse : selected ? 0.85 : isActive ? 0.46 : hovered ? 0.36 : 0,
      );
      ringMat.opacity = THREE.MathUtils.damp(ringMat.opacity, targetRing, 9, dt);
      outerRingMat.opacity = THREE.MathUtils.damp(
        outerRingMat.opacity,
        isActive ? targetRing * 0.3 : 0,
        8,
        dt,
      );
      const ringScale = isMovingFlag
        ? 0.96 + Math.sin(elapsed * 10) * 0.05
        : isLeadFlag && isActive
          ? 1.04 + Math.sin(elapsed * 3.6) * 0.05
          : 1.0;
      floorRing.scale.setScalar(THREE.MathUtils.damp(floorRing.scale.x, ringScale, 8, dt));
      outerRing.scale.setScalar(
        THREE.MathUtils.damp(outerRing.scale.x, isActive ? 1.02 + Math.sin(elapsed * 3.0 + phaseSeed) * 0.05 : 1.0, 7, dt),
      );
    },
    dispose: () => {
      extraTex.forEach((t) => t.dispose());
      geometries.forEach((g) => g.dispose());
      extraMats.forEach((m) => m.dispose());
    },
  };
}
