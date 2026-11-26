import * as THREE from 'three';
import { mergeStaticMeshes } from './mergeStatic';
import {
  createAsphaltBumpTexture,
  createBangDaiLoanCanopyGeo,
  createContactShadowTexture,
  createCorrugatedRoofTextures,
  createFoliageCanopyTextures,
  createOrganicCanopyGeo,
  createRealisticCarGeo,
  createRealisticMotorbikeGeo,
  createVietnameseTubeHouseTextures,
  createWaterproofRoofTexture,
  createWaterTankGeo,
} from './dtuRealisticTextures';

export interface CampusEnvironmentInstance {
  group: THREE.Group;
  setNightGlow: (intensity: number) => void;
  update: (dt: number, elapsed: number, exteriorReveal: number, skipVehicles?: boolean) => void;
  dispose: () => void;
}

/**
 * Ground elevation of Trường Đại học Duy Tân – Cơ sở Hòa Khánh Nam (120 Hoàng Minh Thảo, Liên Chiểu, Đà Nẵng).
 * Our interactive 3D AI Agent Office sits on the top floor (y = 0..3.35m) inside Nhà G (Tòa nhà Kính Đen).
 */
export const CAMPUS_GROUND_Y = -13.2;

interface StreetVehicle {
  road: 'hoang_minh_thao' | 'le_hien_mai';
  t: number;
  dir: 1 | -1;
  speed: number;
  laneOffset: number;
  isBike: boolean;
  color: THREE.Color;
}

// ============================================================================
// DTU OFFICIAL "ẤN CHỈ" LOGO HELPER (Bửu Chi's Single-Stroke Open Book Seal)
// ============================================================================

function drawDtuSealEmblem(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  strokeColor: string,
  fillBorderColor?: string,
) {
  const half = size * 0.5;
  ctx.save();
  ctx.translate(cx, cy);

  if (fillBorderColor) {
    ctx.fillStyle = fillBorderColor;
    ctx.fillRect(-half, -half, size, size);
  }

  // Crisp square "Ấn chỉ" outer seal frame (matching DTU courtyard mosaic & official seal!)
  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = size * 0.095;
  ctx.lineJoin = 'miter';
  ctx.strokeRect(-half * 0.84, -half * 0.84, size * 0.84, size * 0.84);

  // Authentic interlocking "Ấn chỉ" calligraphic brushstroke seal inside square:
  // A bold diagonal-S spine + opposing curved ribbon wings forming the DTU emblem
  const s = half * 0.84;
  ctx.lineCap = 'butt';
  ctx.lineJoin = 'round';
  ctx.lineWidth = size * 0.088;

  // Sweeping S-spine dividing top-left to bottom-right
  ctx.beginPath();
  ctx.moveTo(-s * 0.92, -s * 0.34);
  ctx.bezierCurveTo(-s * 0.15, -s * 0.36, -s * 0.08, s * 0.34, s * 0.92, s * 0.32);
  ctx.stroke();

  // Interlocking vertical-arch wing (top-center curving down-left)
  ctx.beginPath();
  ctx.moveTo(s * 0.06, -s * 0.92);
  ctx.bezierCurveTo(s * 0.06, -s * 0.16, -s * 0.38, s * 0.04, -s * 0.92, s * 0.42);
  ctx.stroke();

  // Counter-balanced lower-right rising hook & upper-right seal stroke
  ctx.beginPath();
  ctx.moveTo(s * 0.92, -s * 0.38);
  ctx.bezierCurveTo(s * 0.34, -s * 0.38, s * 0.14, -s * 0.02, -s * 0.06, s * 0.92);
  ctx.stroke();

  // Inner subtle geometric accent bar on lower-left corner
  ctx.beginPath();
  ctx.moveTo(-s * 0.56, s * 0.48);
  ctx.quadraticCurveTo(-s * 0.18, s * 0.38, s * 0.48, s * 0.62);
  ctx.stroke();

  ctx.restore();
}

/**
 * Straight, symmetric pitched gable roof prism (ExtrudeGeometry) — avoids ConeGeometry scale+rotate shear!
 * Base lies at y = 0, peak at y = peakH, centered at x = 0, z = 0.
 */
function createGableRoofGeo(spanX: number, peakH: number, lengthZ: number): THREE.BufferGeometry {
  const halfX = spanX * 0.5;
  const shape = new THREE.Shape();
  shape.moveTo(-halfX, 0);
  shape.lineTo(0, peakH);
  shape.lineTo(halfX, 0);
  shape.closePath();

  const geo = new THREE.ExtrudeGeometry(shape, {
    depth: lengthZ,
    bevelEnabled: false,
    steps: 1,
  });
  geo.translate(0, 0, -lengthZ * 0.5);
  geo.computeVertexNormals();
  return geo;
}

/**
 * Carved classical semicircular Roman stone arch wall for the DTU Glass Pavilion Portico.
 */
function createArchedPorticoGeo(
  width: number,
  height: number,
  depth: number,
  archHalfW: number,
  archSpringY: number,
): THREE.BufferGeometry {
  const hw = width * 0.5;
  const shape = new THREE.Shape();
  shape.moveTo(-hw, 0);
  shape.lineTo(-hw, height);
  shape.lineTo(hw, height);
  shape.lineTo(hw, 0);
  shape.lineTo(archHalfW, 0);
  shape.lineTo(archHalfW, archSpringY);
  shape.absarc(0, archSpringY, archHalfW, 0, Math.PI, false);
  shape.lineTo(-archHalfW, 0);
  shape.closePath();

  const geo = new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: true,
    bevelThickness: 0.04,
    bevelSize: 0.04,
    bevelSegments: 2,
    curveSegments: 20,
  });
  geo.translate(0, 0, -depth * 0.5);
  geo.computeVertexNormals();
  return geo;
}

// ============================================================================
// HIGH-RESOLUTION PROCEDURAL ARCHITECTURAL & GOOGLE MAPS STREET TEXTURES
// ============================================================================

/**
 * 1. Nhà G (Black-Glass Building) 4-Story Curtain Wall Texture:
 *    Matches Photo 1, 3, 5, 6: deep obsidian reflective panes with bright interior classroom
 *    lighting on mid floors (rows of student desks visible inside!).
 */
function createHeroBlackGlassTextures(maxAniso: number): {
  colorMap: THREE.CanvasTexture;
  emissiveMap: THREE.CanvasTexture;
} {
  const w = 1024;
  const h = 1024;
  const cCol = document.createElement('canvas');
  cCol.width = w;
  cCol.height = h;
  const ctx = cCol.getContext('2d')!;

  const cEm = document.createElement('canvas');
  cEm.width = w;
  cEm.height = h;
  const eCtx = cEm.getContext('2d')!;

  // Kính rèm obsidian phản chiếu bầu trời xanh-xám sâu sang trọng (đúng Ảnh 2, 3, 8, 12!)
  const baseSky = ctx.createLinearGradient(0, 0, w * 0.4, h);
  baseSky.addColorStop(0, '#16212e');
  baseSky.addColorStop(0.45, '#0e1620');
  baseSky.addColorStop(1, '#080d14');
  ctx.fillStyle = baseSky;
  ctx.fillRect(0, 0, w, h);
  eCtx.fillStyle = '#000000';
  eCtx.fillRect(0, 0, w, h);

  const stories = 3;
  const cols = 10;
  const storyH = h / stories;
  const colW = w / cols;

  let seed = 4127;
  const rand = () => {
    seed = (seed * 48271) % 2147483647;
    return (seed - 1) / 2147483646;
  };

  for (let r = 0; r < stories; r++) {
    const y0 = r * storyH;
    // Dải kính spandrel đen bóng che sàn bê tông giữa các tầng
    ctx.fillStyle = '#070b10';
    ctx.fillRect(0, y0 + storyH * 0.78, w, storyH * 0.22);

    // Tầng 1-2 sáng liền mạch theo dãy phòng học (không loang lổ bàn cờ)
    const floorLitBias = r === 0 ? 0.82 : r === 1 ? 0.68 : 0.3;

    for (let c = 0; c < cols; c++) {
      const x0 = c * colW;
      // Gom nhóm 3-4 ô kính chung 1 phòng học để ánh sáng liền mạch chân thực như Ảnh 3 & 8
      const roomLit = ((c + r * 2) % 5 !== 4) && rand() < floorLitBias + 0.18;
      const warmGlow = r === 1 || rand() < 0.55;

      const g = ctx.createLinearGradient(x0, y0, x0, y0 + storyH * 0.78);
      if (roomLit) {
        // Ban ngày kính phản chiếu bầu trời xanh-đen sang trọng, chỉ thấy mờ chiều sâu lớp học
        g.addColorStop(0, warmGlow ? '#1f2b34' : '#1b2b38');
        g.addColorStop(0.35, warmGlow ? '#253138' : '#1e3240');
        g.addColorStop(1, '#0d151d');
      } else {
        g.addColorStop(0, '#162433');
        g.addColorStop(0.55, '#0e1722');
        g.addColorStop(1, '#080e15');
      }
      ctx.fillStyle = g;
      ctx.fillRect(x0 + 4, y0 + 5, colW - 8, storyH * 0.73);

      // Vệt phản chiếu bầu trời chéo sắc nét trên từng tấm kính cường lực
      ctx.fillStyle = 'rgba(186, 222, 250, 0.14)';
      ctx.beginPath();
      ctx.moveTo(x0 + 4, y0 + storyH * 0.42);
      ctx.lineTo(x0 + colW * 0.68, y0 + 5);
      ctx.lineTo(x0 + colW - 4, y0 + 5);
      ctx.lineTo(x0 + 4, y0 + storyH * 0.68);
      ctx.closePath();
      ctx.fill();

      if (roomLit) {
        // Dãy đèn tuýp trần thanh mảnh bên trong lớp học (ban ngày dịu nhẹ, tối bật sáng qua emissiveMap)
        ctx.fillStyle = warmGlow ? 'rgba(245, 238, 210, 0.34)' : 'rgba(214, 240, 255, 0.32)';
        ctx.fillRect(x0 + 10, y0 + 16, colW - 20, 5);
        ctx.fillRect(x0 + 14, y0 + 29, colW - 28, 3);

        // Bóng bàn ghế học viên mờ bên dưới
        ctx.fillStyle = 'rgba(24, 30, 38, 0.45)';
        ctx.fillRect(x0 + 10, y0 + storyH * 0.56, colW - 20, 14);

        eCtx.fillStyle = warmGlow ? '#ffe8aa' : '#d4f1ff';
        eCtx.fillRect(x0 + 8, y0 + 12, colW - 16, storyH * 0.54);
      }
    }

    // Khung nhôm ngang mảnh sắc nét
    ctx.fillStyle = '#3b4654';
    ctx.fillRect(0, y0, w, 4);
    ctx.fillStyle = '#252e38';
    ctx.fillRect(0, y0 + storyH * 0.78, w, 4);
  }

  for (let c = 0; c <= cols; c++) {
    const x = c * colW;
    ctx.fillStyle = '#2d3744';
    ctx.fillRect(x - 2, 0, 4, h);
  }

  const colorMap = new THREE.CanvasTexture(cCol);
  colorMap.colorSpace = THREE.SRGBColorSpace;
  colorMap.anisotropy = Math.min(8, maxAniso);

  const emissiveMap = new THREE.CanvasTexture(cEm);
  emissiveMap.colorSpace = THREE.SRGBColorSpace;
  emissiveMap.anisotropy = Math.min(8, maxAniso);

  return { colorMap, emissiveMap };
}

/**
 * 2. Nhà F (Khoa Y / MedSIM) Signature Perforated Louver Grid Facade Texture!
 *    Matches Photo 2 & Photo 4 right building: crisp white/silver perforated sun-shade metal mesh panels,
 *    horizontal terracotta-orange accent stripes per floor, and recessed dark glazing behind!
 */
function createBlockFLouverTextures(maxAniso: number): {
  colorMap: THREE.CanvasTexture;
  emissiveMap: THREE.CanvasTexture;
} {
  const w = 1024;
  const h = 1024;
  const cCol = document.createElement('canvas');
  cCol.width = w;
  cCol.height = h;
  const ctx = cCol.getContext('2d')!;

  const cEm = document.createElement('canvas');
  cEm.width = w;
  cEm.height = h;
  const eCtx = cEm.getContext('2d')!;

  ctx.fillStyle = '#e5e7eb';
  ctx.fillRect(0, 0, w, h);
  eCtx.fillStyle = '#000000';
  eCtx.fillRect(0, 0, w, h);

  const stories = 3; // 3 upper louver-wrapped stories above the 2-story glass atrium
  const bays = 8;
  const storyH = h / stories;
  const bayW = w / bays;

  let seed = 3091;
  const rand = () => {
    seed = (seed * 48271) % 2147483647;
    return (seed - 1) / 2147483646;
  };

  for (let s = 0; s < stories; s++) {
    const y0 = s * storyH;

    // Dark recessed curtain-wall glass behind the louver frame
    ctx.fillStyle = '#1f2933';
    ctx.fillRect(0, y0 + 26, w, storyH - 58);

    for (let b = 0; b < bays; b++) {
      const x0 = b * bayW;
      const lit = rand() < 0.48;
      if (lit) {
        ctx.fillStyle = '#5c5942';
        ctx.fillRect(x0 + 8, y0 + 34, bayW - 16, storyH - 80);
        eCtx.fillStyle = '#ffe5a3';
        eCtx.fillRect(x0 + 10, y0 + 38, bayW - 20, storyH - 88);
      }

      // Alternating closed/slatted silver-white metal louver screen panels (exact match to Photo 2!)
      const hasLouverScreen = (s + b) % 2 === 0 || rand() < 0.45;
      if (hasLouverScreen) {
        ctx.fillStyle = 'rgba(218, 224, 230, 0.85)';
        ctx.fillRect(x0 + 4, y0 + 26, bayW - 8, storyH * 0.62);

        // Fine horizontal louver slats
        ctx.fillStyle = '#7c8794';
        for (let ly = y0 + 30; ly < y0 + 26 + storyH * 0.62; ly += 8) {
          ctx.fillRect(x0 + 5, ly, bayW - 10, 2);
        }
      }

      // Lower vertical railing bars along the balcony strip
      ctx.fillStyle = '#d4dae0';
      for (let rx = x0 + 8; rx < x0 + bayW - 6; rx += 10) {
        ctx.fillRect(rx, y0 + storyH * 0.66, 3, storyH * 0.24);
      }

      // Vertical silver steel grid divider
      ctx.fillStyle = '#b4bdc6';
      ctx.fillRect(x0 - 3, y0, 6, storyH);
    }

    // Crisp horizontal white floor beam + ICONIC TERRACOTTA-ORANGE ACCENT STRIPE (Photo 2!)
    ctx.fillStyle = '#f3f4f6';
    ctx.fillRect(0, y0, w, 20);
    ctx.fillStyle = '#c85a32';
    ctx.fillRect(0, y0 + 20, w, 7);

    // Mask emissive on solid beams
    eCtx.fillStyle = '#000000';
    eCtx.fillRect(0, y0, w, 30);
    eCtx.fillRect(0, y0 + storyH - 36, w, 36);
  }

  const colorMap = new THREE.CanvasTexture(cCol);
  colorMap.colorSpace = THREE.SRGBColorSpace;
  colorMap.anisotropy = Math.min(8, maxAniso);

  const emissiveMap = new THREE.CanvasTexture(cEm);
  emissiveMap.colorSpace = THREE.SRGBColorSpace;
  emissiveMap.anisotropy = Math.min(8, maxAniso);

  return { colorMap, emissiveMap };
}

function createConcreteRoofTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = '#c4c9ce';
  ctx.fillRect(0, 0, 512, 512);

  let seed = 819;
  const rand = () => {
    seed = (seed * 48271) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  for (let i = 0; i < 60; i++) {
    const x = rand() * 512;
    const y = rand() * 512;
    const r = 18 + rand() * 52;
    const g = ctx.createRadialGradient(x, y, 2, x, y, r);
    const shade = rand() > 0.5 ? 'rgba(130,136,142,0.16)' : 'rgba(225,228,232,0.18)';
    g.addColorStop(0, shade);
    g.addColorStop(1, 'rgba(196,201,206,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.strokeStyle = 'rgba(105, 112, 118, 0.35)';
  ctx.lineWidth = 2;
  for (let i = 64; i < 512; i += 64) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i, 512);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, i);
    ctx.lineTo(512, i);
    ctx.stroke();
  }

  ctx.strokeStyle = 'rgba(85, 92, 98, 0.5)';
  ctx.lineWidth = 10;
  ctx.strokeRect(8, 8, 496, 496);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

/**
 * 3. Circular Red-Bordered Courtyard Plaza (Photo 3 & 5 & 6):
 *    Warm sand/cream stone paving with radial brick lines and crisp red curb edge.
 */
function createCircularPlazaMedallionTexture(maxAniso: number): THREE.CanvasTexture {
  const s = 1024;
  const c = document.createElement('canvas');
  c.width = s;
  c.height = s;
  const ctx = c.getContext('2d')!;
  const cx = s / 2;
  const cy = s / 2;

  ctx.clearRect(0, 0, s, s);

  // Raised bright crimson-red curb rim
  ctx.fillStyle = '#cf242f';
  ctx.beginPath();
  ctx.arc(cx, cy, 498, 0, Math.PI * 2);
  ctx.fill();

  // Warm sand-grey tiled floor
  ctx.fillStyle = '#e5e3de';
  ctx.beginPath();
  ctx.arc(cx, cy, 470, 0, Math.PI * 2);
  ctx.fill();

  const rings: Array<[number, string]> = [
    [432, '#d1cec7'],
    [418, '#ebe8e2'],
    [352, '#c8c4bc'],
    [336, '#e7e4de'],
    [258, '#c2beb5'],
    [244, '#eae7e1'],
  ];
  rings.forEach(([rad, col]) => {
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(cx, cy, rad, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.strokeStyle = 'rgba(130, 126, 118, 0.38)';
  ctx.lineWidth = 3;
  for (let i = 0; i < 28; i++) {
    const a = (i / 28) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * 140, cy + Math.sin(a) * 140);
    ctx.lineTo(cx + Math.cos(a) * 468, cy + Math.sin(a) * 468);
    ctx.stroke();
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

/**
 * 4. ICONIC SQUARE COURTYARD DTU SEAL MOSAIC PAVEMENT (Exact match to Photo 2 & Photo 4!):
 *    Glossy cream/tan granite square patio featuring the giant brown-gold & crimson DTU "Ấn chỉ" emblem!
 */
function createCourtyardMosaicLogoTexture(maxAniso: number): THREE.CanvasTexture {
  const s = 1024;
  const c = document.createElement('canvas');
  c.width = s;
  c.height = s;
  const ctx = c.getContext('2d')!;

  // Glossy light-amber/tan granite background
  ctx.fillStyle = '#d8cbb5';
  ctx.fillRect(0, 0, s, s);

  // Tile grid joints
  ctx.strokeStyle = 'rgba(110, 96, 78, 0.25)';
  ctx.lineWidth = 3;
  for (let i = 0; i <= s; i += 64) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i, s);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, i);
    ctx.lineTo(s, i);
    ctx.stroke();
  }

  // Outer dark charcoal & terracotta-brown border frames (exact match to Photo 2 & 4!)
  ctx.strokeStyle = '#3d3732';
  ctx.lineWidth = 22;
  ctx.strokeRect(44, 44, s - 88, s - 88);

  ctx.strokeStyle = '#8b4d38';
  ctx.lineWidth = 34;
  ctx.strokeRect(98, 98, s - 196, s - 196);

  // Inner warm golden-sand square & giant DTU "Ấn chỉ" Mosaic Emblem!
  ctx.fillStyle = '#dec08e';
  ctx.fillRect(156, 156, s - 312, s - 312);

  drawDtuSealEmblem(ctx, s / 2, s / 2, 540, '#7c3f2c');

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createDtuAcademicWindowTextures(maxAniso: number): {
  colorMap: THREE.CanvasTexture;
  emissiveMap: THREE.CanvasTexture;
} {
  const w = 1024;
  const h = 1024;
  const cCol = document.createElement('canvas');
  cCol.width = w;
  cCol.height = h;
  const ctx = cCol.getContext('2d')!;

  const cEm = document.createElement('canvas');
  cEm.width = w;
  cEm.height = h;
  const eCtx = cEm.getContext('2d')!;

  ctx.fillStyle = '#eff1f2';
  ctx.fillRect(0, 0, w, h);
  eCtx.fillStyle = '#000000';
  eCtx.fillRect(0, 0, w, h);

  const floors = 5;
  const cols = 10;
  const flH = h / floors;
  const colW = w / cols;

  let seed = 9183;
  const rand = () => {
    seed = (seed * 48271) % 2147483647;
    return (seed - 1) / 2147483646;
  };

  for (let f = 0; f < floors; f++) {
    const y0 = f * flH;
    // Ground floor (f === 4 bottom in UV) has darker grey painted facade (exact match to Photo 4!)
    const isGround = f === 4;
    ctx.fillStyle = isGround ? '#7b8087' : '#e7eaec';
    ctx.fillRect(0, y0, w, flH);

    ctx.fillStyle = 'rgba(42, 48, 56, 0.28)';
    ctx.fillRect(0, y0, w, 12);

    for (let c = 0; c < cols; c++) {
      const x0 = c * colW;
      const winX = x0 + 9;
      const winY = y0 + 18;
      const winW = colW - 18;
      const winH = flH * 0.56;

      ctx.fillStyle = '#5a3925';
      ctx.fillRect(winX, winY, winW, winH);

      const lit = rand() < 0.46;
      const paneW = (winW - 16) / 3;
      for (let p = 0; p < 3; p++) {
        const px = winX + 4 + p * (paneW + 4);
        ctx.fillStyle = lit ? '#8c693c' : '#35261d';
        ctx.fillRect(px, winY + 5, paneW, winH - 10);
        ctx.fillStyle = '#5a3925';
        ctx.fillRect(px, winY + winH * 0.36, paneW, 4);

        if (lit) {
          eCtx.fillStyle = '#ffdc8a';
          eCtx.fillRect(px + 1, winY + 6, paneW - 2, winH - 12);
        }
      }
    }
  }

  const colorMap = new THREE.CanvasTexture(cCol);
  colorMap.colorSpace = THREE.SRGBColorSpace;
  colorMap.wrapS = THREE.RepeatWrapping;
  colorMap.wrapT = THREE.ClampToEdgeWrapping;
  colorMap.anisotropy = Math.min(8, maxAniso);

  const emissiveMap = new THREE.CanvasTexture(cEm);
  emissiveMap.colorSpace = THREE.SRGBColorSpace;
  emissiveMap.wrapS = THREE.RepeatWrapping;
  emissiveMap.wrapT = THREE.ClampToEdgeWrapping;
  emissiveMap.anisotropy = Math.min(8, maxAniso);

  return { colorMap, emissiveMap };
}

function createBlockLetterTexture(
  letter: string,
  color: string,
  maxAniso: number,
): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 256;
  const ctx = c.getContext('2d')!;
  ctx.clearRect(0, 0, 256, 256);

  ctx.font = '800 185px Inter, system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = 'rgba(62, 34, 10, 0.35)';
  ctx.fillText(letter, 133, 136);
  ctx.fillStyle = color;
  ctx.fillText(letter, 128, 130);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

/**
 * 5. Official DTU Campus Gate Monument Wall (Cream Marble + Gold Lettering + Square & Round Seals, image_b4303533!)
 */
function createDtuOfficialGateSignTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 2048;
  c.height = 512;
  const ctx = c.getContext('2d')!;

  // Nền đá hoa cương kem trắng sáng tương phản cao để nhìn từ trên cao vẫn sắc nét tuyệt đối
  const bgGrad = ctx.createLinearGradient(0, 0, 0, 512);
  bgGrad.addColorStop(0, '#fbf8ef');
  bgGrad.addColorStop(0.55, '#f5efe0');
  bgGrad.addColorStop(1, '#ebe0c8');
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, 2048, 512);

  // Viền đá đỏ-nâu dày sang trọng chuẩn cổng ĐH Duy Tân
  ctx.fillStyle = '#5c1916';
  ctx.fillRect(0, 0, 2048, 34);
  ctx.fillRect(0, 0, 34, 512);
  ctx.fillRect(2014, 0, 34, 512);
  ctx.fillRect(0, 478, 2048, 34);
  ctx.strokeStyle = '#c89b32';
  ctx.lineWidth = 8;
  ctx.strokeRect(42, 42, 1964, 428);

  // Logo ấn chỉ DTU đỏ-vàng cực sắc nét bên trái
  drawDtuSealEmblem(ctx, 224, 256, 252, '#991b1b', '#fef3c7');

  // Chữ ĐẠI HỌC DUY TÂN cỡ đại, cực đậm tương phản cao (đọc rõ mồn một từ góc flycam trên cao!)
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const titleY = 186;
  const subY = 344;
  const centerX = 1024;

  ctx.lineJoin = 'round';
  ctx.font = '900 144px Inter, system-ui, sans-serif';
  ctx.fillStyle = 'rgba(42, 12, 10, 0.36)';
  ctx.fillText('ĐẠI HỌC DUY TÂN', centerX + 7, titleY + 8);
  ctx.strokeStyle = '#fef9e7';
  ctx.lineWidth = 10;
  ctx.strokeText('ĐẠI HỌC DUY TÂN', centerX, titleY);
  const titleGrad = ctx.createLinearGradient(0, titleY - 72, 0, titleY + 72);
  titleGrad.addColorStop(0, '#b91c1c');
  titleGrad.addColorStop(0.5, '#8f1616');
  titleGrad.addColorStop(1, '#5c1111');
  ctx.fillStyle = titleGrad;
  ctx.fillText('ĐẠI HỌC DUY TÂN', centerX, titleY);

  ctx.font = '800 78px Inter, system-ui, sans-serif';
  ctx.fillStyle = 'rgba(42, 18, 6, 0.28)';
  ctx.fillText('DUY TAN UNIVERSITY', centerX + 4, subY + 5);
  ctx.fillStyle = '#5c3b0e';
  ctx.fillText('DUY TAN UNIVERSITY', centerX, subY);

  // Huy hiệu tròn DTU đậm sắc nét bên phải
  ctx.save();
  ctx.translate(1820, 256);
  ctx.fillStyle = '#7f1d1d';
  const teeth = 18;
  ctx.beginPath();
  for (let i = 0; i < teeth * 2; i++) {
    const a = (i / (teeth * 2)) * Math.PI * 2;
    const r = i % 2 === 0 ? 142 : 124;
    if (i === 0) ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r);
    else ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
  }
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = '#eab308';
  ctx.lineWidth = 12;
  ctx.beginPath();
  ctx.arc(0, 0, 106, 0, Math.PI * 2);
  ctx.stroke();

  ctx.fillStyle = '#facc15';
  ctx.beginPath();
  ctx.arc(0, 0, 78, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#7f1d1d';
  ctx.font = '900 56px Inter, system-ui, sans-serif';
  ctx.fillText('DTU', 0, 5);
  ctx.restore();

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(16, Math.max(4, maxAniso));
  return tex;
}

/**
 * 5B. Bảng hiệu tường đá chính quy Trung tâm Giáo dục Quốc phòng và An ninh — 122 Hoàng Minh Thảo (ĐH TDTT Đà Nẵng)
 * Khớp ảnh chụp thực tế: nền đá kem sáng, 4 dòng chữ sắc nét (dòng 3 đỏ đô in đậm cỡ lớn).
 */
function createGdqpMonumentSignTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 2048;
  c.height = 680;
  const ctx = c.getContext('2d')!;

  // Nền đá ốp granite kem sáng mịn vân tự nhiên
  const bg = ctx.createLinearGradient(0, 0, 0, 680);
  bg.addColorStop(0, '#ddd6c7');
  bg.addColorStop(0.5, '#d4ccbc');
  bg.addColorStop(1, '#c7beac');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, 2048, 680);

  // Mạch ghép tấm đá ốp granite rất mảnh chân thực
  ctx.strokeStyle = 'rgba(110, 102, 88, 0.22)';
  ctx.lineWidth = 3;
  for (let gx = 256; gx < 2048; gx += 256) {
    ctx.beginPath();
    ctx.moveTo(gx, 0);
    ctx.lineTo(gx, 680);
    ctx.stroke();
  }
  for (let gy = 170; gy < 680; gy += 170) {
    ctx.beginPath();
    ctx.moveTo(0, gy);
    ctx.lineTo(2048, gy);
    ctx.stroke();
  }

  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const cx = 1024;

  // Dòng 1: BỘ VĂN HÓA, THỂ THAO VÀ DU LỊCH
  ctx.font = '800 54px Inter, system-ui, sans-serif';
  ctx.fillStyle = 'rgba(15, 23, 42, 0.22)';
  ctx.fillText('BỘ VĂN HÓA, THỂ THAO VÀ DU LỊCH', cx + 2, 118, 1820);
  ctx.fillStyle = '#1e293b';
  ctx.fillText('BỘ VĂN HÓA, THỂ THAO VÀ DU LỊCH', cx, 115, 1820);

  // Dòng 2: TRƯỜNG ĐẠI HỌC THỂ DỤC THỂ THAO ĐÀ NẴNG
  ctx.font = '800 62px Inter, system-ui, sans-serif';
  ctx.fillStyle = 'rgba(15, 23, 42, 0.24)';
  ctx.fillText('TRƯỜNG ĐẠI HỌC THỂ DỤC THỂ THAO ĐÀ NẴNG', cx + 2, 224, 1840);
  ctx.fillStyle = '#0f172a';
  ctx.fillText('TRƯỜNG ĐẠI HỌC THỂ DỤC THỂ THAO ĐÀ NẴNG', cx, 221, 1840);

  // Dòng 3: TRUNG TÂM GIÁO DỤC QUỐC PHÒNG VÀ AN NINH (Chữ nổi đỏ đô in đậm, có lề thoáng 2 bên không chạm trụ đá)
  ctx.font = '900 72px Inter, system-ui, sans-serif';
  ctx.fillStyle = 'rgba(55, 10, 10, 0.30)';
  ctx.fillText('TRUNG TÂM GIÁO DỤC QUỐC PHÒNG VÀ AN NINH', cx + 3, 384, 1840);
  ctx.fillStyle = '#991b1b';
  ctx.fillText('TRUNG TÂM GIÁO DỤC QUỐC PHÒNG VÀ AN NINH', cx, 380, 1840);

  // Dòng 4: 122 ĐƯỜNG HOÀNG MINH THẢO - PHƯỜNG HÒA KHÁNH NAM - QUẬN LIÊN CHIỂU - THÀNH PHỐ ĐÀ NẴNG
  ctx.font = '700 35px Inter, system-ui, sans-serif';
  ctx.fillStyle = 'rgba(15, 23, 42, 0.2)';
  ctx.fillText(
    '122 ĐƯỜNG HOÀNG MINH THẢO - PHƯỜNG HÒA KHÁNH NAM - QUẬN LIÊN CHIỂU - THÀNH PHỐ ĐÀ NẴNG',
    cx + 2,
    548,
    1860,
  );
  ctx.fillStyle = '#1e293b';
  ctx.fillText(
    '122 ĐƯỜNG HOÀNG MINH THẢO - PHƯỜNG HÒA KHÁNH NAM - QUẬN LIÊN CHIỂU - THÀNH PHỐ ĐÀ NẴNG',
    cx,
    545,
    1860,
  );

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(16, Math.max(4, maxAniso));
  return tex;
}

function createSignboardTexture(
  title: string,
  subtitle: string,
  bgColor: string,
  textColor: string,
  accentColor: string,
  maxAniso: number,
): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 1024;
  c.height = 256;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = bgColor;
  ctx.fillRect(0, 0, 1024, 256);

  ctx.strokeStyle = accentColor;
  ctx.lineWidth = 14;
  ctx.strokeRect(10, 10, 1004, 236);

  ctx.fillStyle = textColor;
  ctx.font = '900 58px Inter, system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(title, 512, 100, 940);

  ctx.fillStyle = accentColor;
  ctx.font = '800 34px Inter, system-ui, sans-serif';
  ctx.fillText(subtitle, 512, 178, 940);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(16, Math.max(4, maxAniso));
  return tex;
}

function createAsphaltTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 256;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = '#48505a';
  ctx.fillRect(0, 0, 256, 256);

  let seed = 1337;
  const rand = () => {
    seed = (seed * 48271) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  for (let i = 0; i < 2400; i++) {
    const x = rand() * 256;
    const y = rand() * 256;
    const v = 58 + Math.floor(rand() * 34);
    ctx.fillStyle = `rgb(${v},${v + 5},${v + 12})`;
    ctx.fillRect(x, y, 2, 2);
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(22, 22);
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createSidewalkBrickTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 256;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = '#c8c4bc';
  ctx.fillRect(0, 0, 256, 256);

  ctx.strokeStyle = 'rgba(92, 88, 82, 0.34)';
  ctx.lineWidth = 2;
  for (let i = 0; i <= 256; i += 32) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i, 256);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, i);
    ctx.lineTo(256, i);
    ctx.stroke();
  }
  ctx.fillStyle = '#a3564c';
  ctx.fillRect(0, 224, 256, 32);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(32, 2);
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createMiniFootballPitchTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 1024;
  c.height = 512;
  const ctx = c.getContext('2d')!;

  const stripes = 16;
  for (let i = 0; i < stripes; i++) {
    ctx.fillStyle = i % 2 === 0 ? '#2b8244' : '#359650';
    ctx.fillRect((i * 1024) / stripes, 0, 1024 / stripes + 1, 512);
  }

  ctx.strokeStyle = 'rgba(255,255,255,0.92)';
  ctx.lineWidth = 6;
  [24, 520].forEach((ox) => {
    const pw = 480;
    const py = 36;
    const ph = 440;
    ctx.strokeRect(ox, py, pw, ph);
    ctx.beginPath();
    ctx.moveTo(ox + pw / 2, py);
    ctx.lineTo(ox + pw / 2, py + ph);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(ox + pw / 2, py + ph / 2, 56, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeRect(ox, py + 130, 82, 180);
    ctx.strokeRect(ox + pw - 82, py + 130, 82, 180);
  });

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createMultiSportCourtTexture(maxAniso: number): THREE.CanvasTexture {
  // Light concrete basketball court + surrounding asphalt border (image_b08ac20a!)
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = '#d3d0c8';
  ctx.fillRect(0, 0, 512, 512);

  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 6;
  ctx.strokeRect(40, 48, 432, 416);
  ctx.beginPath();
  ctx.moveTo(256, 48);
  ctx.lineTo(256, 464);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(256, 256, 46, 0, Math.PI * 2);
  ctx.stroke();

  // 3-point arcs & keys
  ctx.strokeRect(40, 186, 86, 140);
  ctx.strokeRect(386, 186, 86, 140);
  ctx.beginPath();
  ctx.arc(62, 256, 128, -Math.PI * 0.45, Math.PI * 0.45);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(450, 256, 128, Math.PI * 0.55, Math.PI * 1.45);
  ctx.stroke();

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createTennisComplexTexture(
  surroundHex: string,
  cols: number,
  rows: number,
  maxAniso: number,
): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = surroundHex;
  ctx.fillRect(0, 0, 512, 512);

  const padX = 36;
  const padY = 38;
  const gap = 22;
  const cw = (512 - padX * 2 - gap * (cols - 1)) / cols;
  const ch = (512 - padY * 2 - gap * (rows - 1)) / rows;

  for (let r = 0; r < rows; r++) {
    for (let col = 0; col < cols; col++) {
      const x = padX + col * (cw + gap);
      const y = padY + r * (ch + gap);
      ctx.fillStyle = '#5d8469';
      ctx.fillRect(x, y, cw, ch);
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 4;
      ctx.strokeRect(x, y, cw, ch);
      ctx.beginPath();
      ctx.moveTo(x + cw * 0.5, y);
      ctx.lineTo(x + cw * 0.5, y + ch);
      ctx.stroke();
      ctx.strokeRect(x + cw * 0.2, y + ch * 0.14, cw * 0.6, ch * 0.72);
    }
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createStadiumPitchTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 1024;
  c.height = 512;
  const ctx = c.getContext('2d')!;

  const stripes = 14;
  for (let i = 0; i < stripes; i++) {
    ctx.fillStyle = i % 2 === 0 ? '#4c9c3d' : '#57ab45';
    ctx.fillRect((i * 1024) / stripes, 0, 1024 / stripes + 1, 512);
  }

  ctx.strokeStyle = 'rgba(255,255,255,0.9)';
  ctx.lineWidth = 6;
  ctx.strokeRect(46, 38, 932, 436);

  ctx.beginPath();
  ctx.moveTo(512, 38);
  ctx.lineTo(512, 474);
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(512, 256, 68, 0, Math.PI * 2);
  ctx.stroke();

  ctx.strokeRect(46, 138, 128, 236);
  ctx.strokeRect(850, 138, 128, 236);
  ctx.strokeRect(46, 192, 48, 128);
  ctx.strokeRect(930, 192, 48, 128);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createTerrainGrassTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext('2d')!;

  // Cỏ tự nhiên pha đất cát miền Trung (giảm xanh nhựa phẳng — đúng Ảnh flycam 3 & 4 quanh Sân vận động đỏ)
  ctx.fillStyle = '#607a49';
  ctx.fillRect(0, 0, 512, 512);

  let seed = 7021;
  const rand = () => {
    seed = (seed * 48271) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  for (let i = 0; i < 260; i++) {
    const x = rand() * 512;
    const y = rand() * 512;
    const r = 14 + rand() * 48;
    const g = ctx.createRadialGradient(x, y, 2, x, y, r);
    const roll = rand();
    const shade =
      roll > 0.72
        ? 'rgba(150, 140, 108, 0.24)' // mảng đất cát vàng nhạt
        : roll > 0.38
          ? 'rgba(72, 102, 52, 0.26)'
          : 'rgba(104, 126, 72, 0.24)';
    g.addColorStop(0, shade);
    g.addColorStop(1, 'rgba(96, 122, 73, 0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  for (let i = 0; i < 2800; i++) {
    const x = rand() * 512;
    const y = rand() * 512;
    ctx.fillStyle =
      rand() > 0.6
        ? 'rgba(56, 80, 40, 0.26)'
        : rand() > 0.25
          ? 'rgba(128, 146, 86, 0.22)'
          : 'rgba(162, 148, 118, 0.22)';
    ctx.fillRect(x, y, 2, 3);
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(28, 28);
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createConcreteDrillPlazaTexture(maxAniso: number): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 1024;
  c.height = 1024;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = '#aeb3b8';
  ctx.fillRect(0, 0, 1024, 1024);

  let seed = 4429;
  const rand = () => {
    seed = (seed * 48271) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  for (let i = 0; i < 180; i++) {
    const x = rand() * 1024;
    const y = rand() * 1024;
    const r = 20 + rand() * 68;
    const g = ctx.createRadialGradient(x, y, 4, x, y, r);
    const shade = rand() > 0.5 ? 'rgba(130, 136, 142, 0.16)' : 'rgba(202, 206, 210, 0.16)';
    g.addColorStop(0, shade);
    g.addColorStop(1, 'rgba(174, 179, 184, 0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  // Concrete expansion slab joints
  ctx.strokeStyle = 'rgba(84, 90, 96, 0.36)';
  ctx.lineWidth = 2;
  for (let i = 0; i <= 1024; i += 64) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i, 1024);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, i);
    ctx.lineTo(1024, i);
    ctx.stroke();
  }

  // White military drill parade formation square & lane lines
  ctx.strokeStyle = 'rgba(244, 246, 248, 0.84)';
  ctx.lineWidth = 8;
  ctx.strokeRect(180, 210, 664, 580);
  ctx.lineWidth = 5;
  for (let lx = 260; lx <= 760; lx += 84) {
    ctx.beginPath();
    ctx.moveTo(lx, 245);
    ctx.lineTo(lx, 755);
    ctx.stroke();
  }

  // Red & yellow center salute box facing the dais
  ctx.strokeStyle = 'rgba(185, 28, 28, 0.72)';
  ctx.lineWidth = 6;
  ctx.strokeRect(442, 720, 140, 62);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createDefenseBuildingTexture(maxAniso: number): THREE.CanvasTexture {
  const w = 1024;
  const h = 512;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d')!;

  ctx.fillStyle = '#ece9df';
  ctx.fillRect(0, 0, w, h);

  const stories = 2;
  const cols = 10;
  const flH = h / stories;
  const colW = w / cols;

  for (let f = 0; f < stories; f++) {
    const y0 = f * flH;
    // Recessed corridor overhang shadow
    ctx.fillStyle = 'rgba(48, 56, 52, 0.22)';
    ctx.fillRect(0, y0, w, 24);
    // Floor slab balcony trim
    ctx.fillStyle = '#d6d2c6';
    ctx.fillRect(0, y0 + flH - 22, w, 22);

    for (let col = 0; col < cols; col++) {
      const x0 = col * colW;
      // Window frame + recessed glass panes
      ctx.fillStyle = '#2d4436';
      ctx.fillRect(x0 + 16, y0 + 38, colW - 32, flH * 0.56);
      ctx.fillStyle = '#3c5261';
      ctx.fillRect(x0 + 22, y0 + 44, (colW - 50) * 0.5, flH * 0.56 - 12);
      ctx.fillRect(x0 + 28 + (colW - 50) * 0.5, y0 + 44, (colW - 50) * 0.5, flH * 0.56 - 12);
      // White vertical pier
      ctx.fillStyle = '#f2efe6';
      ctx.fillRect(x0 - 4, y0, 8, flH);
    }
  }

  // Military dark-green base wainscot
  ctx.fillStyle = '#2b593c';
  ctx.fillRect(0, h - 48, w, 48);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.anisotropy = Math.min(8, maxAniso);
  return tex;
}

function createDaNangMountainRange(): {
  mesh: THREE.Mesh;
  geo: THREE.BufferGeometry;
  mat: THREE.MeshStandardMaterial;
} {
  const segX = 110;
  const segY = 16;
  const geo = new THREE.PlaneGeometry(620, 1, segX, segY);
  const pos = geo.attributes.position as THREE.BufferAttribute;
  const colors = new Float32Array(pos.count * 3);

  const baseCol = new THREE.Color(0x567460);
  const midCol = new THREE.Color(0x3a5d52);
  const ridgeCol = new THREE.Color(0x4c6b7c); // ánh lam khí quyển nhẹ ở sống núi xa
  const quarryCol = new THREE.Color(0x8e867c); // vách đá xám-nâu đặc trưng núi Phước Tường (Ảnh 3)
  const tmpCol = new THREE.Color();

  const ridgeHeightAt = (u: number): number => {
    const peakLeft = Math.exp(-Math.pow((u + 0.34) / 0.25, 2)) * 58;
    const peakLeftSub = Math.exp(-Math.pow((u + 0.58) / 0.16, 2)) * 30;
    const peakRight = Math.exp(-Math.pow((u - 0.16) / 0.18, 2)) * 38;
    const ridgeFarRight = Math.exp(-Math.pow((u - 0.62) / 0.28, 2)) * 25;
    const micro =
      Math.sin(u * 29) * 2.2 +
      Math.cos(u * 53 + 0.7) * 1.3 +
      Math.sin(u * 13 - 0.5) * 3.0;
    return Math.max(4, peakLeft + peakLeftSub + peakRight + ridgeFarRight + micro);
  };

  for (let i = 0; i < pos.count; i++) {
    const rawX = pos.getX(i);
    const rawY = pos.getY(i);
    const u = rawX / 310;
    const t = rawY + 0.5;

    const angle = -Math.PI * 0.52 + u * Math.PI * 0.46;
    const radius = 250 - (1 - t) * 28;
    const px = Math.cos(angle) * radius - 14;
    const pz = Math.sin(angle) * radius - 16;
    const maxH = ridgeHeightAt(u);
    const py = CAMPUS_GROUND_Y - 1.5 + Math.pow(t, 0.88) * maxH;

    pos.setXYZ(i, px, py, pz);

    if (t < 0.45) {
      tmpCol.copy(baseCol).lerp(midCol, t / 0.45);
    } else {
      tmpCol.copy(midCol).lerp(ridgeCol, (t - 0.45) / 0.55);
    }
    // Mảng vách đá xám-nâu sạt lở đặc trưng sườn núi Phước Tường nhìn từ Nhà G (Ảnh 3)
    const quarryPatch =
      Math.exp(-Math.pow((u + 0.36) / 0.12, 2)) * Math.exp(-Math.pow((t - 0.34) / 0.2, 2));
    if (quarryPatch > 0.12) {
      tmpCol.lerp(quarryCol, Math.min(0.68, quarryPatch * 0.85));
    }
    colors[i * 3] = tmpCol.r;
    colors[i * 3 + 1] = tmpCol.g;
    colors[i * 3 + 2] = tmpCol.b;
  }

  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.computeVertexNormals();

  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.96,
    metalness: 0.0,
    side: THREE.DoubleSide,
  });

  const mesh = new THREE.Mesh(geo, mat);
  return { mesh, geo, mat };
}

// ============================================================================
// MAIN CAMPUS BUILDER: ĐẠI HỌC DUY TÂN 120 HOÀNG MINH THẢO – BẢN ĐỒ THU NHỎ 3D
// ============================================================================

export function buildDtuCampusEnvironment(maxAniso: number, lowQuality = false): CampusEnvironmentInstance {
  const group = new THREE.Group();
  group.name = 'dtu_hoa_khanh_nam_campus';

  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];
  const textures: THREE.Texture[] = [];

  const trackGeo = <T extends THREE.BufferGeometry>(g: T): T => {
    geometries.push(g);
    return g;
  };
  const trackMat = <T extends THREE.Material>(m: T): T => {
    materials.push(m);
    return m;
  };
  const trackTex = <T extends THREE.Texture>(t: T): T => {
    textures.push(t);
    return t;
  };

  // Textures
  const heroGlassTex = createHeroBlackGlassTextures(maxAniso);
  trackTex(heroGlassTex.colorMap);
  trackTex(heroGlassTex.emissiveMap);

  const blockFTex = createBlockFLouverTextures(maxAniso);
  trackTex(blockFTex.colorMap);
  trackTex(blockFTex.emissiveMap);

  const concreteRoofTex = trackTex(createConcreteRoofTexture(maxAniso));
  const medallionTex = trackTex(createCircularPlazaMedallionTexture(maxAniso));
  const courtyardMosaicTex = trackTex(createCourtyardMosaicLogoTexture(maxAniso));
  const academicWinTex = createDtuAcademicWindowTextures(maxAniso);
  trackTex(academicWinTex.colorMap);
  trackTex(academicWinTex.emissiveMap);

  const letterETex = trackTex(createBlockLetterTexture('E', '#e6a817', maxAniso));
  const letterDTex = trackTex(createBlockLetterTexture('D', '#d99a1e', maxAniso));
  const letterCTex = trackTex(createBlockLetterTexture('C', '#0284c7', maxAniso));
  const asphaltTex = trackTex(createAsphaltTexture(maxAniso));
  const sidewalkTex = trackTex(createSidewalkBrickTexture(maxAniso));
  const miniPitchTex = trackTex(createMiniFootballPitchTexture(maxAniso));
  const multiSportTex = trackTex(createMultiSportCourtTexture(maxAniso));
  const blueTennisTex = trackTex(createTennisComplexTexture('#4178a4', 2, 2, maxAniso));
  const redTennisTex = trackTex(createTennisComplexTexture('#9e524a', 2, 1, maxAniso));
  const stadiumPitchTex = trackTex(createStadiumPitchTexture(maxAniso));
  const terrainGrassTex = trackTex(createTerrainGrassTexture(maxAniso));
  const drillPlazaTex = trackTex(createConcreteDrillPlazaTexture(maxAniso));
  const defenseWallTex = trackTex(createDefenseBuildingTexture(maxAniso));
  const dtuOfficialGateTex = trackTex(createDtuOfficialGateSignTexture(maxAniso));
  const waterproofRoofTex = trackTex(createWaterproofRoofTexture(maxAniso, lowQuality));
  const asphaltBumpTex = trackTex(createAsphaltBumpTexture(maxAniso, lowQuality));
  const tubeHouseTex = createVietnameseTubeHouseTextures(maxAniso, lowQuality);
  trackTex(tubeHouseTex.colorMap);
  trackTex(tubeHouseTex.bumpMap);
  trackTex(tubeHouseTex.emissiveMap);
  const corrugatedRoofTex = createCorrugatedRoofTextures(maxAniso, lowQuality);
  trackTex(corrugatedRoofTex.colorMap);
  trackTex(corrugatedRoofTex.bumpMap);
  const foliageTex = createFoliageCanopyTextures(maxAniso, lowQuality);
  trackTex(foliageTex.colorMap);
  trackTex(foliageTex.bumpMap);
  const contactShadowTex = trackTex(createContactShadowTexture());

  const qpGateSignTex = trackTex(createGdqpMonumentSignTexture(maxAniso));
  const qpNoticeSignTex = trackTex(
    createSignboardTexture('KHU QUÂN SỰ', 'CẤM VÀO', '#eab308', '#991b1b', '#991b1b', maxAniso),
  );

  // Shared Materials (Realistic Architectural PBR palette — bỏ cảm giác nhựa Lego)
  const heroGlassMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: heroGlassTex.colorMap,
      emissiveMap: heroGlassTex.emissiveMap,
      emissive: new THREE.Color(0xfff0c2),
      emissiveIntensity: 0.28,
      roughness: 0.11,
      metalness: 0.7,
    }),
  );
  const blockFLouverMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: blockFTex.colorMap,
      emissiveMap: blockFTex.emissiveMap,
      emissive: new THREE.Color(0xffdfa3),
      emissiveIntensity: 0.18,
      roughness: 0.48,
      metalness: 0.32,
      bumpMap: lowQuality ? null : blockFTex.colorMap,
      bumpScale: 0.08,
    }),
  );
  const blackAluminumMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x161c24, roughness: 0.34, metalness: 0.68 }),
  );
  const plasterWhiteMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xeeefe9, roughness: 0.86, metalness: 0.02 }),
  );
  const creamStoneMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xe2cfa9, roughness: 0.82 }),
  );
  const creamPlasterMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xe3e4e2, roughness: 0.88 }),
  );
  const warmLobbyGlowMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xffd58f,
      emissive: new THREE.Color(0xffb44c),
      emissiveIntensity: 0.48,
      roughness: 0.46,
    }),
  );
  const stoneGraniteMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xd5d8dc, roughness: 0.86 }),
  );
  const darkStonePortalMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x62666c, roughness: 0.86 }),
  );
  const brownStairwellMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x634532, roughness: 0.78 }),
  );
  const emeraldRoofMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: waterproofRoofTex,
      roughness: 0.84,
      metalness: 0.04,
    }),
  );
  const solarPanelMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x1e3a8a, roughness: 0.24, metalness: 0.6 }),
  );
  const terracottaTileMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xb35644,
      map: corrugatedRoofTex.colorMap,
      bumpMap: lowQuality ? null : corrugatedRoofTex.bumpMap,
      bumpScale: 0.07,
      roughness: 0.78,
    }),
  );
  const darkSlateRoofMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x333c47,
      map: corrugatedRoofTex.colorMap,
      bumpMap: lowQuality ? null : corrugatedRoofTex.bumpMap,
      bumpScale: 0.06,
      roughness: 0.56,
      metalness: 0.34,
    }),
  );
  const academicWinMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: academicWinTex.colorMap,
      emissiveMap: academicWinTex.emissiveMap,
      emissive: new THREE.Color(0xffdc8a),
      emissiveIntensity: 0.18,
      roughness: 0.66,
      metalness: 0.12,
    }),
  );
  const defenseWallMat = trackMat(
    new THREE.MeshStandardMaterial({ map: defenseWallTex, roughness: 0.84 }),
  );
  const asphaltMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: asphaltTex,
      bumpMap: lowQuality ? null : asphaltBumpTex,
      bumpScale: 0.04,
      roughness: 0.9,
      metalness: 0.04,
    }),
  );
  const sidewalkMat = trackMat(
    new THREE.MeshStandardMaterial({ map: sidewalkTex, roughness: 0.88 }),
  );
  const roadAsphaltMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x454c56,
      bumpMap: lowQuality ? null : asphaltBumpTex,
      bumpScale: 0.05,
      roughness: 0.88,
    }),
  );
  const drillGroundMat = trackMat(
    new THREE.MeshStandardMaterial({ map: drillPlazaTex, roughness: 0.9 }),
  );
  const grassFieldMat = trackMat(
    new THREE.MeshStandardMaterial({ map: terrainGrassTex, roughness: 0.95 }),
  );
  const roadLineMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xeef2f5, roughness: 0.75 }),
  );
  const yellowLineMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xeab308, roughness: 0.75 }),
  );
  const redTrackMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xc22b36, roughness: 0.78 }),
  );
  const turquoiseBenchMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x2dd4bf, roughness: 0.55 }),
  );
  const crimsonAccentMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xb91c1c, roughness: 0.65 }),
  );
  const militaryGreenMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x2f6b47, roughness: 0.78 }),
  );
  const glassPavilionMat = trackMat(
    new THREE.MeshPhysicalMaterial({
      color: 0x22303c,
      emissive: new THREE.Color(0xffc978),
      emissiveIntensity: 0.32,
      roughness: 0.18,
      metalness: 0.25,
      transparent: true,
      opacity: 0.84,
    }),
  );

  const unitBoxGeo = trackGeo(new THREE.BoxGeometry(1, 1, 1));
  const dummy = new THREE.Object3D();
  const tmpColor = new THREE.Color();

  // =========================================================================
  // 1. GOOGLE MAPS STREET NETWORK: HOÀNG MINH THẢO · LÊ HIẾN MAI · ĐÀ SƠN · LÊ TRỌNG TẤN (KHÉP KÍN 100%, KHÔNG ĐƯỜNG CỤT!)
  // =========================================================================
  const terrainBase = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(1400, 1400)),
    grassFieldMat,
  );
  terrainBase.rotation.x = -Math.PI / 2;
  terrainBase.position.y = CAMPUS_GROUND_Y - 0.1;
  group.add(terrainBase);

  const campusYard = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(122, 0.14, 128)),
    asphaltMat,
  );
  campusYard.position.set(10, CAMPUS_GROUND_Y - 0.06, -29);
  group.add(campusYard);

  // ĐƯỜNG HOÀNG MINH THẢO (kéo xuyên 960m tới tận chân trời / sương mù — không bao giờ thấy đầu đường cụt!)
  const southRoadGroup = new THREE.Group();
  southRoadGroup.position.set(-10, CAMPUS_GROUND_Y - 0.025, 41);
  southRoadGroup.rotation.y = 0.2;
  const southRoad = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(960, 0.12, 13.5)),
    roadAsphaltMat,
  );
  southRoad.position.x = 0;
  southRoadGroup.add(southRoad);
  // Vỉa hè 2 bên Hoàng Minh Thảo kéo dài xuyên suốt, chừa đúng ngã tư Lê Hiến Mai (dx ≈ -47.1)
  [-8.6, 8.6].forEach((sz) => {
    const swWest = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(424, 0.22, 3.8)), sidewalkMat);
    swWest.position.set(-268, 0.05, sz);
    const swEast = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(518, 0.22, 3.8)), sidewalkMat);
    swEast.position.set(221, 0.05, sz);
    southRoadGroup.add(swWest, swEast);
  });
  for (let dx = -380; dx <= 380; dx += 12) {
    if (dx > -57 && dx < -37) continue;
    const dash = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(5.2, 0.03, 0.24)), yellowLineMat);
    dash.position.set(dx, 0.07, 0);
    southRoadGroup.add(dash);
  }
  [-14, -36.5, -58.5].forEach((cx) => {
    for (let cz = -5.2; cz <= 5.2; cz += 1.4) {
      const stripe = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(2.6, 0.03, 0.6)), roadLineMat);
      stripe.position.set(cx, 0.075, cz);
      southRoadGroup.add(stripe);
    }
  });
  group.add(southRoadGroup);

  // ĐƯỜNG LÊ HIẾN MAI (kéo xuyên 960m Bắc–Nam tới tận chân trời — không bị cắt cụt!)
  const westAve = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(11.4, 0.12, 960)),
    roadAsphaltMat,
  );
  westAve.position.set(-56.2, CAMPUS_GROUND_Y - 0.025, 0);
  group.add(westAve);

  for (let dz = -360; dz <= 360; dz += 11) {
    if ((dz > 39 && dz < 62) || (dz > -101 && dz < -87) || (dz > -132 && dz < -120) || (dz > -162 && dz < -150) || (dz > 68 && dz < 80) || (dz > 100 && dz < 114) || (dz > 142 && dz < 156)) {
      continue;
    }
    const dash = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.22, 0.03, 4.8)), yellowLineMat);
    dash.position.set(-56.2, CAMPUS_GROUND_Y + 0.045, dz);
    group.add(dash);
  }

  // 4-Way Intersection Asphalt Deck & North/South Crosswalks at Hoàng Minh Thảo × Lê Hiến Mai (-56.2, 50.36)
  const junctionDeck = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(14.5, 0.13, 19.2)),
    roadAsphaltMat,
  );
  junctionDeck.position.set(-56.2, CAMPUS_GROUND_Y - 0.015, 50.36);
  junctionDeck.receiveShadow = true;
  group.add(junctionDeck);
  [40.8, 59.9].forEach((cz) => {
    for (let cx = -60.2; cx <= -52.2; cx += 2.0) {
      const stripe = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(1.05, 0.03, 2.4)), roadLineMat);
      stripe.position.set(cx, CAMPUS_GROUND_Y + 0.055, cz);
      group.add(stripe);
    }
  });

  // Split West & East Lê Hiến Mai sidewalks cleanly around every intersection & entrance!
  const westSidewalkDefenseNorthFar = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 126)),
    stoneGraniteMat,
  );
  westSidewalkDefenseNorthFar.position.set(-63.5, CAMPUS_GROUND_Y + 0.04, -162.0);
  const westSidewalkDefenseNorthMid = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 71)),
    stoneGraniteMat,
  );
  westSidewalkDefenseNorthMid.position.set(-63.5, CAMPUS_GROUND_Y + 0.04, -53.5);
  const westSidewalkDefenseMidSouth = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 30)),
    stoneGraniteMat,
  );
  westSidewalkDefenseMidSouth.position.set(-63.5, CAMPUS_GROUND_Y + 0.04, 25.0);
  const westSidewalkDefenseSouth1 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 40.5)),
    stoneGraniteMat,
  );
  westSidewalkDefenseSouth1.position.set(-63.5, CAMPUS_GROUND_Y + 0.04, 80.75);
  const westSidewalkDefenseSouth2 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 84)),
    stoneGraniteMat,
  );
  westSidewalkDefenseSouth2.position.set(-63.5, CAMPUS_GROUND_Y + 0.04, 153.0);

  const westSidewalkCampusNorth = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 22)),
    stoneGraniteMat,
  );
  westSidewalkCampusNorth.position.set(-48.9, CAMPUS_GROUND_Y + 0.04, -110);
  const westSidewalkCampusFarNorth = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 90)),
    stoneGraniteMat,
  );
  westSidewalkCampusFarNorth.position.set(-48.9, CAMPUS_GROUND_Y + 0.04, -176);
  const westSidewalkCampusGateNorth = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 35)),
    stoneGraniteMat,
  );
  westSidewalkCampusGateNorth.position.set(-48.9, CAMPUS_GROUND_Y + 0.04, -71.5);
  const westSidewalkCampusMid = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 83)),
    stoneGraniteMat,
  );
  westSidewalkCampusMid.position.set(-48.9, CAMPUS_GROUND_Y + 0.04, -0.5);
  const westSidewalkCampusSouth1 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 8.5)),
    stoneGraniteMat,
  );
  westSidewalkCampusSouth1.position.set(-48.9, CAMPUS_GROUND_Y + 0.04, 64.75);
  const westSidewalkCampusSouth2 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 24.0)),
    stoneGraniteMat,
  );
  westSidewalkCampusSouth2.position.set(-48.9, CAMPUS_GROUND_Y + 0.04, 91.0);
  const westSidewalkCampusSouth3 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.2, 82.0)),
    stoneGraniteMat,
  );
  westSidewalkCampusSouth3.position.set(-48.9, CAMPUS_GROUND_Y + 0.04, 154.0);
  const gate2Apron = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(6.2, 0.13, 12.0)),
    roadAsphaltMat,
  );
  gate2Apron.position.set(-48.8, CAMPUS_GROUND_Y - 0.02, -48.0);
  gate2Apron.receiveShadow = true;
  group.add(
    westSidewalkDefenseNorthFar,
    westSidewalkDefenseNorthMid,
    westSidewalkDefenseMidSouth,
    westSidewalkDefenseSouth1,
    westSidewalkDefenseSouth2,
    westSidewalkCampusNorth,
    westSidewalkCampusFarNorth,
    westSidewalkCampusGateNorth,
    westSidewalkCampusMid,
    westSidewalkCampusSouth1,
    westSidewalkCampusSouth2,
    westSidewalkCampusSouth3,
    gate2Apron,
  );

  // Continuous Smooth Curved Asphalt Road Ribbon looping West of Lê Hiến Mai around 122 Hoàng Minh Thảo & Stadium (image_d5a88cbd!)
  const createRoadRibbonGeo = (
    pts: Array<[number, number]>,
    width: number,
    segments = 64,
  ): THREE.BufferGeometry => {
    const curve = new THREE.CatmullRomCurve3(
      pts.map(([x, z]) => new THREE.Vector3(x, 0, z)),
      false,
      'catmullrom',
      0.4,
    );
    const sampled = curve.getSpacedPoints(segments);
    const hw = width * 0.5;
    const positions: number[] = [];
    const normals: number[] = [];
    const uvs: number[] = [];
    const indices: number[] = [];

    for (let i = 0; i < sampled.length; i++) {
      const p = sampled[i];
      const tan = curve.getTangentAt(i / segments);
      tan.y = 0;
      if (tan.lengthSq() < 1e-6) tan.set(1, 0, 0);
      tan.normalize();
      const nx = -tan.z;
      const nz = tan.x;

      positions.push(p.x + nx * hw, 0, p.z + nz * hw);
      positions.push(p.x - nx * hw, 0, p.z - nz * hw);
      normals.push(0, 1, 0, 0, 1, 0);
      uvs.push(0, i / segments, 1, i / segments);

      if (i < sampled.length - 1) {
        const b = i * 2;
        indices.push(b, b + 2, b + 1, b + 2, b + 3, b + 1);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
    geo.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
    geo.setIndex(indices);
    return geo;
  };

  const defLoopRoad = new THREE.Mesh(
    trackGeo(
      createRoadRibbonGeo(
        [
          [-55.0, -14.5],
          [-76.0, -15.5],
          [-106.0, -21.0],
          [-136.0, -28.0],
          [-154.0, -44.0],
          [-155.0, -64.0],
          [-142.0, -82.0],
          [-116.0, -91.5],
          [-84.0, -94.0],
          [-55.0, -94.0],
        ],
        8.6,
        64,
      ),
    ),
    roadAsphaltMat,
  );
  defLoopRoad.position.y = CAMPUS_GROUND_Y + 0.018;
  defLoopRoad.receiveShadow = true;
  group.add(defLoopRoad);

  // Nhánh đường nội bộ rẽ thẳng từ vòng đường sân vận động vào cổng Sân điều lệnh & Khu KTX TT GDQP & AN
  const defInternalRoad1 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(7.2, 0.08, 36.0)),
    roadAsphaltMat,
  );
  defInternalRoad1.position.set(-80.0, CAMPUS_GROUND_Y - 0.015, -112.0);
  const defInternalRoad2 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(84.0, 0.08, 6.8)),
    roadAsphaltMat,
  );
  defInternalRoad2.position.set(-108.0, CAMPUS_GROUND_Y - 0.015, -129.0);
  group.add(defInternalRoad1, defInternalRoad2);

  // KHU DÂN CƯ TÂN CƯỜNG THÀNH & HÒA KHÁNH NAM — MẠNG LƯỚI ĐƯỜNG PHỐ KHÉP KÍN 100% THEO GOOGLE MAPS (0 ĐƯỜNG CỤT!)
  const addNeighborhoodStreet = (
    sx: number,
    sz: number,
    len: number,
    wid: number,
    alongZ: boolean,
  ) => {
    const road = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(alongZ ? wid : len, 0.1, alongZ ? len : wid)),
      roadAsphaltMat,
    );
    road.position.set(sx, CAMPUS_GROUND_Y - 0.038, sz);
    const sw = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(alongZ ? wid + 3.0 : len, 0.07, alongZ ? len : wid + 3.0)),
      stoneGraniteMat,
    );
    sw.position.set(sx, CAMPUS_GROUND_Y - 0.058, sz);
    const centerLine = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(alongZ ? 0.18 : len - 6, 0.02, alongZ ? len - 6 : 0.18)),
      roadLineMat,
    );
    centerLine.position.set(sx, CAMPUS_GROUND_Y + 0.016, sz);
    group.add(sw, road, centerLine);
  };
  // 1) Các trục đường bao vành đai chạy xuyên tới tận chân trời (khóa kín toàn bộ mạng đường, xóa sạch mọi đầu đường cụt!)
  addNeighborhoodStreet(0, 148, 960, 11.0, false);    // Đại lộ ngang phía Nam (xuyên từ Tây sang Đông, khóa kín toàn bộ đầu đường phía Nam!)
  addNeighborhoodStreet(0, -156, 960, 10.5, false);   // Đại lộ ngang phía Bắc (khóa kín toàn bộ đầu đường phía Bắc & nối khu GDQP!)
  addNeighborhoodStreet(184, 0, 960, 10.0, true);     // Trục dọc phía Đông ngoài cùng (xuyên 960m Bắc–Nam)
  addNeighborhoodStreet(-188, 0, 960, 11.0, true);    // Đại lộ Lê Trọng Tấn / Đà Sơn phía Tây-Nam (xuyên 960m Bắc–Nam, nối liền đại lộ đôi 122 GDQP!)

  // 2) Các tuyến Bắc–Nam nội khu KDC (nối khép kín giữa Đại lộ Bắc z=-156 và Đại lộ Nam z=148 — 0 đầu cụt!)
  addNeighborhoodStreet(42, 95, 108, 9.5, true);      // Dương Cát Lợi nối từ Hoàng Minh Thảo (z≈41) khép kín vào Đại lộ Nam (z=148)
  addNeighborhoodStreet(76, -4, 306, 8.8, true);      // Nối khép kín từ z=-156 tới z=148
  addNeighborhoodStreet(112, -4, 306, 8.5, true);     // Nối khép kín từ z=-156 tới z=148
  addNeighborhoodStreet(148, -4, 306, 8.5, true);     // Nối khép kín từ z=-156 tới z=148

  // 3) Các tuyến Đông–Tây nội khu phía Đông (nối khép kín từ Lê Hiến Mai x=-56.2 tới Trục Đông x=184 — 0 đầu cụt!)
  addNeighborhoodStreet(64, -94, 240, 9.2, false);
  addNeighborhoodStreet(64, -126, 240, 8.5, false);
  addNeighborhoodStreet(130, -52, 108, 8.0, false);   // Nối khép kín từ x=76 tới x=184
  addNeighborhoodStreet(130, -14, 108, 8.0, false);   // Nối khép kín từ x=76 tới x=184
  addNeighborhoodStreet(130, 12, 108, 8.5, false);    // Nối khép kín từ x=76 tới x=184
  addNeighborhoodStreet(64, 74, 240, 8.8, false);
  addNeighborhoodStreet(64, 108, 240, 8.5, false);

  // 4) Các tuyến nội khu Tây-Nam Hòa Khánh Nam (nối khép kín từ Đại lộ Lê Trọng Tấn x=-188 tới Lê Hiến Mai x=-56.2 & z=148!)
  addNeighborhoodStreet(-122, 106, 132, 8.5, false);
  addNeighborhoodStreet(-108, 102, 96, 8.8, true);    // Nối từ Hoàng Minh Thảo khép kín vào Đại lộ Nam z=148
  addNeighborhoodStreet(-148, 107, 86, 8.5, true);    // Nối từ Hoàng Minh Thảo khép kín vào Đại lộ Nam z=148

  // Satellite Urban Block Concrete Footprints (so housing clusters sit on paved Vietnamese urban blocks, not green grass!)
  const urbanFootprintSpecs: Array<[number, number, number, number]> = [
    [94, -110, 26, 22],
    [130, -110, 26, 22],
    [166, -110, 26, 22],
    [94, -73, 26, 30],
    [130, -73, 26, 30],
    [166, -73, 26, 30],
    [94, -33, 26, 26],
    [130, -33, 26, 26],
    [166, -33, 26, 26],
    [94, -1, 26, 16],
    [130, -1, 26, 16],
    [166, -1, 26, 16],
    [48, -0.5, 34, 13],
    [56, 56, 20, 22],
    [94, 54, 26, 28],
    [130, 54, 26, 28],
    [166, 54, 26, 28],
    [-4, 91, 78, 22],
    [59, 91, 24, 22],
    [94, 91, 26, 22],
    [130, 91, 26, 22],
    [166, 91, 26, 22],
    [18, -110, 56, 22],
    [54, -110, 24, 22],
    // South-West Urban Block Concrete Footprints across Lê Hiến Mai (fixes image_bdabf676!)
    [-84, 86, 34, 24],
    [-128, 91, 28, 16],
    [-84, 126, 34, 28],
    [-128, 126, 28, 28],
    [-4, 126, 78, 28],
    [59, 126, 24, 28],
    [94, 126, 26, 28],
    [130, 126, 26, 28],
  ];
  urbanFootprintSpecs.forEach(([bx, bz, bw, bd]) => {
    const pad = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(bw, 0.08, bd)),
      stoneGraniteMat,
    );
    pad.position.set(bx, CAMPUS_GROUND_Y - 0.07, bz);
    pad.receiveShadow = true;
    group.add(pad);
  });

  // East Campus Access Lane (alongside Nhà G & Nhà F, cleanly inside perimeter fence)
  const eastLane = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(10.5, 0.12, 102)),
    roadAsphaltMat,
  );
  eastLane.position.set(17.2, CAMPUS_GROUND_Y - 0.04, -30);
  eastLane.receiveShadow = true;
  group.add(eastLane);

  // South-East Manicured Campus Lawn inside Hoàng Minh Thảo Fence (visible in image_d5a88cbd!)
  const seGateLawn = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(19.5, 0.14, 5.2)),
    grassFieldMat,
  );
  seGateLawn.position.set(11.5, CAMPUS_GROUND_Y + 0.02, 22.0);
  seGateLawn.rotation.y = 0.2;
  seGateLawn.receiveShadow = true;
  group.add(seGateLawn);

  // Blue Da Nang Street Name Signposts at the Hoàng Minh Thảo × Lê Hiến Mai Corner!
  const addStreetSign = (sx: number, sz: number, streetName: string, rotY: number) => {
    const pole = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.06, 0.07, 3.4, 6)),
      stoneGraniteMat,
    );
    pole.position.set(sx, CAMPUS_GROUND_Y + 1.7, sz);
    const tex = trackTex(
      createSignboardTexture(streetName, 'P. HÒA KHÁNH NAM', '#1d4ed8', '#ffffff', '#93c5fd', maxAniso),
    );
    const board = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(2.8, 0.72, 0.1)),
      trackMat(new THREE.MeshBasicMaterial({ map: tex })),
    );
    board.position.set(sx, CAMPUS_GROUND_Y + 3.45, sz);
    board.rotation.y = rotY;
    group.add(pole, board);
  };
  addStreetSign(-45.5, 36.5, 'Đ. HOÀNG MINH THẢO', 0.2);
  addStreetSign(-47.5, 29.0, 'Đ. LÊ HIẾN MAI', Math.PI * 0.5);

  // =========================================================================
  // 2. NHÀ G — TÒA NHÀ KÍNH ĐEN (VIỆN ĐÀO TẠO QUỐC TẾ, Photo 1, 3, 5, 6!)
  // =========================================================================
  const heroGroup = new THREE.Group();
  group.add(heroGroup);

  const heroW = 19.8;
  const heroD = 24.4;
  const lobbyH = 3.9;
  const upperBottomY = CAMPUS_GROUND_Y + lobbyH;
  const upperMidHeight = -0.39 - upperBottomY;

  // Raised Pale-Granite Sidewalk Apron + Wide Entrance Steps along West Courtyard (Photo 3 & 5!)
  const heroApron = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(heroW + 3.6, 0.34, heroD + 3.6)),
    stoneGraniteMat,
  );
  heroApron.position.set(0, CAMPUS_GROUND_Y + 0.17, 0);
  heroApron.receiveShadow = true;
  heroGroup.add(heroApron);

  // 4 stepped concrete stairs descending West toward the Circular Red Plaza
  for (let st = 0; st < 4; st++) {
    const step = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.45, 0.12 + st * 0.08, heroD - 1.2)),
      stoneGraniteMat,
    );
    step.position.set(-heroW * 0.5 - 2.1 + st * 0.4, CAMPUS_GROUND_Y + 0.08 + st * 0.04, 0);
    heroGroup.add(step);
  }

  // Ground-floor Recessed Glazed Lobby + Warm Illuminated Golden Base (Photo 1, 5, 6!)
  const lobbyCore = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(heroW - 3.0, lobbyH, heroD - 3.0)),
    plasterWhiteMat,
  );
  lobbyCore.position.set(0, CAMPUS_GROUND_Y + lobbyH * 0.5 + 0.25, 0);
  heroGroup.add(lobbyCore);

  const lobbyStorefront = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(heroW - 2.7, lobbyH - 0.6, heroD - 2.7)),
    heroGlassMat,
  );
  lobbyStorefront.position.set(0, CAMPUS_GROUND_Y + lobbyH * 0.5 + 0.18, 0);
  heroGroup.add(lobbyStorefront);

  // Solid White Architectural Corner Wall on South-East Lobby (Photo 3 & 5!)
  const seCornerWall = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(6.8, lobbyH, 0.55)),
    plasterWhiteMat,
  );
  seCornerWall.position.set(6.2, CAMPUS_GROUND_Y + lobbyH * 0.5 + 0.2, heroD * 0.5 - 0.55);
  heroGroup.add(seCornerWall);

  // Warm Golden Architectural LED Soffit under Cantilevered Black-Glass Upper Volume (Photo 1, 5, 6!)
  const soffit = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(heroW - 0.12, 0.3, heroD - 0.12)),
    warmLobbyGlowMat,
  );
  soffit.position.set(0, upperBottomY + 0.08, 0);
  heroGroup.add(soffit);

  // Crisp White Square Concrete Colonnade Pillars
  const pillarGeo = trackGeo(new THREE.BoxGeometry(0.76, lobbyH, 0.76));
  const pillarPositions: Array<[number, number]> = [
    [-9.25, -11.4],
    [-9.25, -5.7],
    [-9.25, 0],
    [-9.25, 5.7],
    [-9.25, 11.4],
    [9.25, -11.4],
    [9.25, -5.7],
    [9.25, 0],
    [9.25, 5.7],
    [9.25, 11.4],
    [-3.1, 11.4],
    [3.1, 11.4],
    [-3.1, -11.4],
    [3.1, -11.4],
  ];
  const pillarsInst = new THREE.InstancedMesh(pillarGeo, plasterWhiteMat, pillarPositions.length);
  pillarPositions.forEach(([px, pz], i) => {
    dummy.position.set(px, CAMPUS_GROUND_Y + lobbyH * 0.5 + 0.22, pz);
    dummy.rotation.set(0, 0, 0);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    pillarsInst.setMatrixAt(i, dummy.matrix);
  });
  pillarsInst.instanceMatrix.needsUpdate = true;
  pillarsInst.castShadow = true;
  pillarsInst.receiveShadow = true;
  heroGroup.add(pillarsInst);

  // Main Lower-to-Mid Obsidian Black-Glass Curtain Volume (y = -8.7 to -0.39, cleanly below Agent Office plinth!)
  const upperGlassCore = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(heroW - 0.18, upperMidHeight, heroD - 0.18)),
    heroGlassMat,
  );
  upperGlassCore.position.set(0, upperBottomY + upperMidHeight * 0.5, 0);
  upperGlassCore.castShadow = true;
  upperGlassCore.receiveShadow = true;
  heroGroup.add(upperGlassCore);

  // Dark Anodized Aluminum Curtain-Wall Mullions (matches Photo 3's crisp dark black grid!)
  const mullionSpecs: Array<[number, number, number, number, number, number]> = [];
  [-9.18, -6.1, -3.15, -0.45].forEach((hy) => {
    mullionSpecs.push([0, hy, heroD * 0.5 + 0.04, heroW + 0.22, 0.22, 0.2]);
    mullionSpecs.push([0, hy, -heroD * 0.5 - 0.04, heroW + 0.22, 0.22, 0.2]);
    mullionSpecs.push([-heroW * 0.5 - 0.04, hy, 0, 0.2, 0.22, heroD + 0.22]);
    mullionSpecs.push([heroW * 0.5 + 0.04, hy, 0, 0.2, 0.22, heroD + 0.22]);
  });
  for (let i = 0; i <= 8; i++) {
    const mx = -heroW * 0.5 + (i / 8) * heroW;
    mullionSpecs.push([mx, upperBottomY + upperMidHeight * 0.5, heroD * 0.5 + 0.04, 0.15, upperMidHeight, 0.2]);
    mullionSpecs.push([mx, upperBottomY + upperMidHeight * 0.5, -heroD * 0.5 - 0.04, 0.15, upperMidHeight, 0.2]);
  }
  for (let i = 0; i <= 10; i++) {
    const mz = -heroD * 0.5 + (i / 10) * heroD;
    mullionSpecs.push([-heroW * 0.5 - 0.04, upperBottomY + upperMidHeight * 0.5, mz, 0.2, upperMidHeight, 0.15]);
    mullionSpecs.push([heroW * 0.5 + 0.04, upperBottomY + upperMidHeight * 0.5, mz, 0.2, upperMidHeight, 0.15]);
  }
  const mullionsInst = new THREE.InstancedMesh(unitBoxGeo, blackAluminumMat, mullionSpecs.length);
  mullionSpecs.forEach(([x, y, z, sx, sy, sz], i) => {
    dummy.position.set(x, y, z);
    dummy.rotation.set(0, 0, 0);
    dummy.scale.set(sx, sy, sz);
    dummy.updateMatrix();
    mullionsInst.setMatrixAt(i, dummy.matrix);
  });
  mullionsInst.instanceMatrix.needsUpdate = true;
  mullionsInst.computeBoundingSphere();
  heroGroup.add(mullionsInst);

  // Subtle Warm Architectural Uplight PointLight under Nhà G's Courtyard Colonnade (illuminates stairs at night!)
  const heroColonnadeLight = new THREE.PointLight(0xffb85c, 0.4, 24, 1.5);
  heroColonnadeLight.position.set(-10.8, CAMPUS_GROUND_Y + 3.2, 0);
  heroGroup.add(heroColonnadeLight);

  // =========================================================================
  // 3. TOP-FLOOR BLACK-GLASS SHELL & CONCRETE ROOFTOP (Reveals on Zoom-Out!)
  // =========================================================================
  const roofRevealGroup = new THREE.Group();
  group.add(roofRevealGroup);

  const roofGlassMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: heroGlassTex.colorMap,
      emissiveMap: heroGlassTex.emissiveMap,
      emissive: new THREE.Color(0xfff0c2),
      emissiveIntensity: 0.28,
      roughness: 0.14,
      metalness: 0.56,
      transparent: true,
      opacity: 0,
    }),
  );
  const roofMullionMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x161c24,
      roughness: 0.36,
      metalness: 0.65,
      transparent: true,
      opacity: 0,
    }),
  );
  const roofConcreteMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: concreteRoofTex,
      roughness: 0.88,
      transparent: true,
      opacity: 0,
    }),
  );
  const roofWhiteMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xf1f3f5,
      roughness: 0.8,
      transparent: true,
      opacity: 0,
    }),
  );
  const roofDarkRimMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x1e252e,
      roughness: 0.45,
      metalness: 0.5,
      transparent: true,
      opacity: 0,
    }),
  );

  const topH = 3.35;
  const sleeveWalls: Array<[number, number, number, number]> = [
    [0, heroD * 0.5 - 0.1, heroW - 0.18, 0.2],
    [0, -heroD * 0.5 + 0.1, heroW - 0.18, 0.2],
    [-heroW * 0.5 + 0.1, 0, 0.2, heroD - 0.18],
    [heroW * 0.5 - 0.1, 0, 0.2, heroD - 0.18],
  ];
  sleeveWalls.forEach(([sx, sz, sw, sd]) => {
    const p = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(sw, topH, sd)), roofGlassMat);
    p.position.set(sx, topH * 0.5, sz);
    p.renderOrder = 4;
    roofRevealGroup.add(p);
  });

  const topMullions: Array<[number, number, number, number, number, number]> = [];
  for (let i = 0; i <= 8; i++) {
    const mx = -heroW * 0.5 + (i / 8) * heroW;
    topMullions.push([mx, topH * 0.5, heroD * 0.5 + 0.04, 0.15, topH, 0.2]);
    topMullions.push([mx, topH * 0.5, -heroD * 0.5 - 0.04, 0.15, topH, 0.2]);
  }
  for (let i = 0; i <= 10; i++) {
    const mz = -heroD * 0.5 + (i / 10) * heroD;
    topMullions.push([-heroW * 0.5 - 0.04, topH * 0.5, mz, 0.2, topH, 0.15]);
    topMullions.push([heroW * 0.5 + 0.04, topH * 0.5, mz, 0.2, topH, 0.15]);
  }
  const topMullionsInst = new THREE.InstancedMesh(unitBoxGeo, roofMullionMat, topMullions.length);
  topMullions.forEach(([x, y, z, sx, sy, sz], i) => {
    dummy.position.set(x, y, z);
    dummy.rotation.set(0, 0, 0);
    dummy.scale.set(sx, sy, sz);
    dummy.updateMatrix();
    topMullionsInst.setMatrixAt(i, dummy.matrix);
  });
  topMullionsInst.instanceMatrix.needsUpdate = true;
  roofRevealGroup.add(topMullionsInst);

  const flatRoofSlab = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(heroW + 0.15, 0.34, heroD + 0.15)),
    roofConcreteMat,
  );
  flatRoofSlab.position.set(0, topH + 0.12, 0);
  roofRevealGroup.add(flatRoofSlab);

  const parapetBeams: Array<[number, number, number, number]> = [
    [0, heroD * 0.5 + 0.02, heroW + 0.32, 0.28],
    [0, -heroD * 0.5 - 0.02, heroW + 0.32, 0.28],
    [-heroW * 0.5 - 0.02, 0, 0.28, heroD + 0.32],
    [heroW * 0.5 + 0.02, 0, 0.28, heroD + 0.32],
  ];
  parapetBeams.forEach(([bx, bz, bw, bd]) => {
    const b = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(bw, 0.44, bd)), roofDarkRimMat);
    b.position.set(bx, topH + 0.42, bz);
    roofRevealGroup.add(b);
  });

  const roofPent = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(4.8, 1.85, 3.6)), roofWhiteMat);
  roofPent.position.set(-2.6, topH + 1.18, 4.4);
  roofRevealGroup.add(roofPent);

  // Large central glass skylight ("giếng trời" matching image_d5a88cbd!)
  const roofSkylight = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(6.8, 0.48, 5.2)), roofGlassMat);
  roofSkylight.position.set(0.2, topH + 0.48, -1.6);
  roofRevealGroup.add(roofSkylight);

  // Double-row AC chiller array on North-East rooftop corner (có lưới quạt tròn đen thực tế đúng Ảnh 3 & 4!)
  const chillerFanGeo = trackGeo(new THREE.CylinderGeometry(0.32, 0.32, 0.08, 10));
  for (let hx = 2.6; hx <= 8.2; hx += 1.35) {
    [-8.6, -6.4].forEach((hz) => {
      const ac = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.92, 0.62, 1.6)), roofWhiteMat);
      ac.position.set(hx, topH + 0.58, hz);
      const fan1 = new THREE.Mesh(chillerFanGeo, roofDarkRimMat);
      fan1.position.set(hx, topH + 0.91, hz - 0.38);
      const fan2 = new THREE.Mesh(chillerFanGeo, roofDarkRimMat);
      fan2.position.set(hx, topH + 0.91, hz + 0.38);
      roofRevealGroup.add(ac, fan1, fan2);
    });
  }
  // Gỡ 2 mảng chữ G / DUY TÂN UNIVERSITY dán quá to trên mặt kính Nhà G để giống 100% Ảnh 2, 3, 4, 8, 12!

  // =========================================================================
  // 4. TRỤC SÂN TRUNG TÂM GIỮA NHÀ E/D VÀ NHÀ G/F (ĐÚNG 1:1 THEO 6 ẢNH MỚI!)
  //    - Sân tròn viền đỏ + 2 bậc tròn đồng tâm + Ghế xanh ngọc + Tượng điêu khắc
  //    - Nhà kính Quán Café #1 (Mái dốc tối) + Đài phun nước nhỏ
  //    - Sân lát gạch vuông khổng lồ mang LOGO ẤN CHỈ ĐẠI HỌC DUY TÂN
  //    - Nhà Kính Cổng Vòm Đá Vàng Cổ Điển (#maeTMlaicoSdtu!)
  // =========================================================================

  // 4A. Sân Tròn Viền Đỏ & Bậc Tròn Đồng Tâm (Centerline x = -17.6, exact symmetry between Nhà E & Nhà G!)
  const plazaGroup = new THREE.Group();
  plazaGroup.position.set(-17.6, CAMPUS_GROUND_Y, 13.8);
  group.add(plazaGroup);

  const plazaBase = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(7.2, 7.4, 0.14, 40)),
    stoneGraniteMat,
  );
  plazaBase.position.y = 0.07;
  plazaBase.receiveShadow = true;
  plazaGroup.add(plazaBase);

  // Raised 3D Crimson-Red Circular Curb Border (very prominent in Photo 3 & 5!)
  const redCurbRing = new THREE.Mesh(
    trackGeo(new THREE.TorusGeometry(6.15, 0.2, 8, 48)),
    redTrackMat,
  );
  redCurbRing.rotation.x = Math.PI / 2;
  redCurbRing.position.y = 0.18;
  plazaGroup.add(redCurbRing);

  const medallionDisc = new THREE.Mesh(
    trackGeo(new THREE.CircleGeometry(6.05, 48)),
    trackMat(new THREE.MeshStandardMaterial({ map: medallionTex, roughness: 0.78 })),
  );
  medallionDisc.rotation.x = -Math.PI / 2;
  medallionDisc.position.y = 0.16;
  medallionDisc.receiveShadow = true;
  plazaGroup.add(medallionDisc);

  // Two raised central stepped stone platform discs (exact Photo 3 & 5!)
  const stepRing1 = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(3.35, 3.45, 0.2, 36)),
    stoneGraniteMat,
  );
  stepRing1.position.y = 0.25;
  const stepRing2 = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(1.95, 2.04, 0.2, 32)),
    creamStoneMat,
  );
  stepRing2.position.y = 0.44;
  plazaGroup.add(stepRing1, stepRing2);

  // Turquoise-blue sculpted student benches along North edge of Circular Plaza (Photo 3!)
  [-2.6, 2.6].forEach((bx) => {
    const bench = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(2.1, 0.52, 0.75)),
      turquoiseBenchMat,
    );
    bench.position.set(bx, 0.42, -5.6);
    plazaGroup.add(bench);
  });

  // Raised cream-stone courtyard garden beds with 2 bronze sculptures & fountain south of Mosaic Square
  const gardenWalk = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(11.4, 0.16, 12.2)),
    stoneGraniteMat,
  );
  gardenWalk.position.set(-17.6, CAMPUS_GROUND_Y + 0.08, 1.5);
  gardenWalk.receiveShadow = true;
  group.add(gardenWalk);

  // Side planter curbs along West (Nhà E) and East (Nhà G) edges of the garden walk
  [-22.6, -12.3].forEach((px) => {
    const planterCurb = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.3, 0.44, 10.6)),
      creamStoneMat,
    );
    planterCurb.position.set(px, CAMPUS_GROUND_Y + 0.24, 1.8);
    group.add(planterCurb);
  });

  // 2 dark bronze human-like sculptural pillars on East planter edge beside Nhà G stairs
  [4.4, 2.8].forEach((sz) => {
    const statue = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.18, 0.26, 2.35, 8)),
      blackAluminumMat,
    );
    statue.position.set(-12.3, CAMPUS_GROUND_Y + 1.62, sz);
    group.add(statue);
  });

  // Small ornamental stone fountain ring cleanly centered in garden zone (z = 2.6, well clear of Mosaic Square!)
  const fountainBase = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(1.1, 1.25, 0.52, 16)),
    creamStoneMat,
  );
  fountainBase.position.set(-17.6, CAMPUS_GROUND_Y + 0.34, 2.6);
  group.add(fountainBase);

  // 4B. NHÀ KÍNH CỔNG VÒM ĐÁ VÀNG CỔ ĐIỂN (#maeTMlaicoSdtu — straight symmetric gable roof + carved semicircular Roman arch!)
  const buildClassicalGlassPavilion = (px: number, pz: number) => {
    const pg = new THREE.Group();
    pg.position.set(px, CAMPUS_GROUND_Y + 0.14, pz);

    const pw = 6.8;
    const pd = 5.4;

    const base = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(pw + 0.5, 0.24, pd + 0.5)),
      stoneGraniteMat,
    );
    base.position.y = 0.12;
    base.receiveShadow = true;
    pg.add(base);

    // Cream-stone low brick wainscot perimeter (0.58m tall) matching Photo 2 & 4
    const wainscot = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(pw, 0.58, pd)),
      creamStoneMat,
    );
    wainscot.position.y = 0.52;
    pg.add(wainscot);

    // Full-height steel-framed dark glass walls with warm golden interior glow
    const glassBody = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(pw - 0.16, 2.28, pd - 0.16)),
      glassPavilionMat,
    );
    glassBody.position.y = 1.94;
    pg.add(glassBody);

    // Visible warm wooden café tables inside through the glass!
    [-1.7, 1.7].forEach((tx) => {
      const table = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(1.3, 0.78, 1.8)),
        brownStairwellMat,
      );
      table.position.set(tx, 0.72, 0.15);
      pg.add(table);
    });

    // Crisp black aluminum vertical mullions around all 4 sides
    for (let i = -2; i <= 2; i++) {
      const mx = (i / 2) * (pw * 0.48);
      [-pd * 0.49, pd * 0.49].forEach((mz) => {
        const mull = new THREE.Mesh(
          trackGeo(new THREE.BoxGeometry(0.11, 2.35, 0.11)),
          blackAluminumMat,
        );
        mull.position.set(mx, 1.95, mz);
        pg.add(mull);
      });
    }
    for (let j = -1; j <= 1; j++) {
      const mz = j * (pd * 0.36);
      [-pw * 0.49, pw * 0.49].forEach((mx) => {
        const mull = new THREE.Mesh(
          trackGeo(new THREE.BoxGeometry(0.11, 2.35, 0.11)),
          blackAluminumMat,
        );
        mull.position.set(mx, 1.95, mz);
        pg.add(mull);
      });
    }

    // STRAIGHT SYMMETRIC PITCHED DARK-ZINC GABLE ROOF (ExtrudeGeometry — zero skew/shear!)
    const gableGeo = trackGeo(createGableRoofGeo(pw + 0.85, 1.38, pd + 0.7));
    const gableRoof = new THREE.Mesh(gableGeo, darkSlateRoofMat);
    gableRoof.position.y = 3.08;
    gableRoof.castShadow = true;
    pg.add(gableRoof);

    // Standing-seam zinc roof ribs + crisp ridge cap
    for (let rx = -pw * 0.46; rx <= pw * 0.46; rx += 0.85) {
      const yOff = (1 - Math.abs(rx) / ((pw + 0.85) * 0.5)) * 1.38;
      const rib = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.06, 0.08, pd + 0.72)),
        blackAluminumMat,
      );
      rib.position.set(rx, 3.08 + yOff, 0);
      pg.add(rib);
    }
    const ridgeCap = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.22, 0.14, pd + 0.78)),
      blackAluminumMat,
    );
    ridgeCap.position.set(0, 4.46, 0);
    pg.add(ridgeCap);

    // CARVED CLASSICAL CREAM-STONE ROMAN ARCH PORTICO FACING THE MOSAIC SQUARE (+Z)
    const archWallGeo = trackGeo(createArchedPorticoGeo(3.65, 3.45, 0.56, 0.96, 1.65));
    const archWall = new THREE.Mesh(archWallGeo, creamStoneMat);
    archWall.position.set(0, 0.22, pd * 0.5 + 0.25);
    archWall.castShadow = true;
    pg.add(archWall);

    // Classical flanking pilasters + stepped cornice frieze + top pediment trim
    [-1.48, 1.48].forEach((ax) => {
      const pil = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.55, 3.48, 0.72)),
        creamStoneMat,
      );
      pil.position.set(ax, 1.96, pd * 0.5 + 0.26);
      pg.add(pil);
    });
    const cornice = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(4.05, 0.28, 0.88)),
      creamStoneMat,
    );
    cornice.position.set(0, 3.76, pd * 0.5 + 0.28);
    pg.add(cornice);

    // Dark recessed glazed arched doorway inside the carved stone arch
    const doorGlass = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.72, 2.35, 0.14)),
      glassPavilionMat,
    );
    doorGlass.position.set(0, 1.38, pd * 0.5 + 0.08);
    const doorFrame = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.1, 2.35, 0.18)),
      blackAluminumMat,
    );
    doorFrame.position.set(0, 1.38, pd * 0.5 + 0.12);
    pg.add(doorGlass, doorFrame);

    // Curved frosted glass entrance canopy projecting over the arch (Photo 2 & 4!)
    const canopyMat = trackMat(
      new THREE.MeshPhysicalMaterial({
        color: 0xcbe7f5,
        roughness: 0.18,
        metalness: 0.15,
        transparent: true,
        opacity: 0.65,
      }),
    );
    const canopy = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(1.32, 1.32, 0.08, 18, 1, false, 0, Math.PI)),
      canopyMat,
    );
    canopy.rotation.y = -Math.PI * 0.5;
    canopy.scale.set(0.62, 1, 1);
    canopy.position.set(0, 2.88, pd * 0.5 + 0.58);
    pg.add(canopy);

    group.add(pg);
  };

  buildClassicalGlassPavilion(-17.6, -16.8);

  // 4C. SÂN GẠCH VUÔNG LOGO ẤN CHỈ ĐẠI HỌC DUY TÂN (100% open & unobstructed right south of Stone-Arch Pavilion!)
  const mosaicPlaza = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(9.8, 9.8)),
    trackMat(new THREE.MeshStandardMaterial({ map: courtyardMosaicTex, roughness: 0.42 })),
  );
  mosaicPlaza.rotation.x = -Math.PI / 2;
  mosaicPlaza.position.set(-17.6, CAMPUS_GROUND_Y + 0.19, -7.2);
  mosaicPlaza.receiveShadow = true;
  group.add(mosaicPlaza);

  // Red curb edge along West lane beside Mosaic & Garden Walk (matches Photo 2 & image_43cbbac9!)
  const southWestCurb = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.28, 0.2, 19.5)),
    redTrackMat,
  );
  southWestCurb.position.set(-22.95, CAMPUS_GROUND_Y + 0.12, -2.5);
  group.add(southWestCurb);

  // 4D. KHÚC SÂN BẮC GIỮA NHÀ D VÀ NHÀ F (Nối tiếp sau Nhà Kính Cổng Vòm — Đúng ảnh image_43cbbac9!)
  const northCourtGroup = new THREE.Group();
  northCourtGroup.position.set(-17.6, CAMPUS_GROUND_Y, -31.4);
  group.add(northCourtGroup);

  const northWalk = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(11.2, 0.16, 22.6)),
    stoneGraniteMat,
  );
  northWalk.position.y = 0.08;
  northWalk.receiveShadow = true;
  northCourtGroup.add(northWalk);

  // Signature red-painted curb along the West border facing Nhà D (visible in image_43cbbac9!)
  const northRedCurb = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.28, 0.2, 22.4)),
    redTrackMat,
  );
  northRedCurb.position.set(-5.5, 0.12, 0);
  northCourtGroup.add(northRedCurb);

  // Cream-stone raised planter beds & wooden benches along West (Nhà D) and East (Nhà F) borders
  [-4.75, 4.75].forEach((px) => {
    const pBed = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.2, 0.42, 18.8)),
      creamStoneMat,
    );
    pBed.position.set(px, 0.24, 0);
    northCourtGroup.add(pBed);
  });

  [-6.2, 6.2].forEach((bz) => {
    [-3.5, 3.5].forEach((bx) => {
      const bench = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.65, 0.46, 1.8)),
        brownStairwellMat,
      );
      bench.position.set(bx, 0.34, bz);
      northCourtGroup.add(bench);
    });
  });

  // Sky-Blue Circular Water Basin & Fountain (visible behind Stone-Arch Pavilion in image_43cbbac9!)
  const waterRim = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(3.45, 3.6, 0.34, 32)),
    creamStoneMat,
  );
  waterRim.position.set(0, 0.24, 0.6);
  const waterMat = trackMat(
    new THREE.MeshPhysicalMaterial({
      color: 0x5bbbe8,
      emissive: new THREE.Color(0x1f6b99),
      emissiveIntensity: 0.14,
      roughness: 0.16,
      metalness: 0.12,
    }),
  );
  const waterDisc = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(3.05, 3.05, 0.12, 32)),
    waterMat,
  );
  waterDisc.position.set(0, 0.38, 0.6);
  const innerPedestal = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.75, 0.95, 0.72, 20)),
    stoneGraniteMat,
  );
  innerPedestal.position.set(0, 0.64, 0.6);
  const upperBowl = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(1.25, 0.7, 0.24, 20)),
    creamStoneMat,
  );
  upperBowl.position.set(0, 1.05, 0.6);
  northCourtGroup.add(waterRim, waterDisc, innerPedestal, upperBowl);

  // White minimalist garden pergola frames at both ends of the North Promenade (image_43cbbac9!)
  [-8.6, 8.2].forEach((pz) => {
    [-2.5, 2.5].forEach((px) => {
      const post = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.28, 3.1, 0.28)),
        plasterWhiteMat,
      );
      post.position.set(px, 1.65, pz);
      northCourtGroup.add(post);
    });
    const beam = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(5.6, 0.28, 0.42)),
      plasterWhiteMat,
    );
    beam.position.set(0, 3.22, pz);
    northCourtGroup.add(beam);
  });

  // Dùng chung 1 vật liệu bảng cổng ĐH Duy Tân sắc nét (gộp draw calls + nhìn rõ từ trên cao)
  const dtuGateSignMat = trackMat(new THREE.MeshBasicMaterial({ map: dtuOfficialGateTex }));

  // DTU Main Campus Gate 1 Monument Wall (Hoàng Minh Thảo — Cream Marble + Bold Crimson/Gold Letters + DTU Logo)
  const gateWallGroup = new THREE.Group();
  gateWallGroup.position.set(-7.5, CAMPUS_GROUND_Y, 27.6);
  gateWallGroup.rotation.y = 0.2;
  const gateWallBase = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(15.6, 3.35, 0.72)),
    creamStoneMat,
  );
  gateWallBase.position.y = 1.68;
  gateWallGroup.add(gateWallBase);

  const gateSignPlane = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(15.2, 3.25)),
    dtuGateSignMat,
  );
  gateSignPlane.position.set(0, 1.72, 0.56);
  gateSignPlane.rotation.x = -0.14; // Nghiêng nhẹ lên trời để đọc cực rõ từ trên cao!
  const gateSignBack = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(15.2, 3.25)),
    dtuGateSignMat,
  );
  gateSignBack.position.set(0, 1.72, -0.56);
  gateSignBack.rotation.y = Math.PI;
  gateSignBack.rotation.x = -0.14;
  gateWallGroup.add(gateSignPlane, gateSignBack);

  // Manicured green shrub hedge & granite border along the front of the DTU monument wall (image_058a75a6!)
  const hedgeCurb = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(14.6, 0.24, 1.05)),
    stoneGraniteMat,
  );
  hedgeCurb.position.set(0, 0.12, 0.8);
  const hedgeShrub = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(14.2, 0.65, 0.78)),
    militaryGreenMat,
  );
  hedgeShrub.position.set(0, 0.48, 0.8);
  gateWallGroup.add(hedgeCurb, hedgeShrub);

  // Retractable stainless-steel accordion gate extending left toward Guardhouse
  for (let gx = -12.8; gx <= -7.6; gx += 0.65) {
    const bar = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.1, 1.65, 0.22)),
      stoneGraniteMat,
    );
    bar.position.set(gx, 0.85, 0);
    gateWallGroup.add(bar);
  }
  group.add(gateWallGroup);

  // =========================================================================
  // 4B. CỔNG PHỤ ĐƯỜNG LÊ HIẾN MAI (GATE 2 XE RA VÀO GIỮA NHÀ D & NHÀ C) + HÀNG RÀO QUANH TRƯỜNG
  // =========================================================================
  const gate2Group = new THREE.Group();
  gate2Group.position.set(-47.2, CAMPUS_GROUND_Y, -48.0);

  // Two crisp white Gate 2 Entrance Pillars flanking the 11.6m vehicle driveway (z = -42.2 & -53.8)
  [-5.8, 5.8].forEach((pz) => {
    const gPillar = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.95, 3.6, 0.95)),
      plasterWhiteMat,
    );
    gPillar.position.set(0, 1.8, pz);
    gPillar.castShadow = true;
    const gCap = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.18, 0.34, 1.18)),
      terracottaTileMat,
    );
    gCap.position.set(0, 3.72, pz);
    const gCrest = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.12, 0.75, 0.75)),
      yellowLineMat,
    );
    gCrest.position.set(-0.52, 2.55, pz);
    gate2Group.add(gPillar, gCap, gCrest);
  });

  // Retractable stainless-steel gate leaf + red/white barrier arm at Gate 2 South edge
  for (let gz = 2.6; gz <= 5.2; gz += 0.52) {
    const bar = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.22, 1.62, 0.1)),
      stoneGraniteMat,
    );
    bar.position.set(0, 0.84, gz);
    gate2Group.add(bar);
  }
  const g2Barrier = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.14, 0.14, 4.8)),
    crimsonAccentMat,
  );
  g2Barrier.position.set(1.2, 1.1, 2.5);
  gate2Group.add(g2Barrier);

  // Gate 2 Guard Booth just inside South pillar (clearly north of shed2)
  const g2Booth = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(2.6, 2.5, 2.6)),
    plasterWhiteMat,
  );
  g2Booth.position.set(2.4, 1.25, 6.8);
  const g2BoothWin = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(2.68, 0.95, 2.68)),
    blackAluminumMat,
  );
  g2BoothWin.position.set(2.4, 1.65, 6.8);
  const g2BoothRoof = new THREE.Mesh(
    trackGeo(new THREE.ConeGeometry(2.4, 1.5, 4)),
    terracottaTileMat,
  );
  g2BoothRoof.position.set(2.4, 3.25, 6.8);
  g2BoothRoof.rotation.y = Math.PI * 0.25;
  gate2Group.add(g2Booth, g2BoothWin, g2BoothRoof);

  // Gate 2 DTU Monument Sign Wall (ĐẠI HỌC DUY TÂN / DUY TAN UNIVERSITY + Logo) — to rõ, nghiêng nhẹ đọc nét từ trên cao!
  const g2SignWall = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.72, 3.25, 13.4)),
    creamStoneMat,
  );
  g2SignWall.position.set(0, 1.62, -12.6);
  const g2SignStreet = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(13.0, 3.12)),
    dtuGateSignMat,
  );
  g2SignStreet.position.set(-0.56, 1.66, -12.6);
  g2SignStreet.rotation.order = 'YXZ';
  g2SignStreet.rotation.y = -Math.PI * 0.5;
  g2SignStreet.rotation.x = -0.15;
  const g2SignYard = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(13.0, 3.12)),
    dtuGateSignMat,
  );
  g2SignYard.position.set(0.56, 1.66, -12.6);
  g2SignYard.rotation.order = 'YXZ';
  g2SignYard.rotation.y = Math.PI * 0.5;
  g2SignYard.rotation.x = -0.15;
  const g2Curb = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.05, 0.24, 13.6)),
    stoneGraniteMat,
  );
  g2Curb.position.set(-0.82, 0.12, -12.6);
  const g2Hedge = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.75, 0.62, 13.2)),
    militaryGreenMat,
  );
  g2Hedge.position.set(-0.82, 0.45, -12.6);
  gate2Group.add(g2SignWall, g2SignStreet, g2SignYard, g2Curb, g2Hedge);
  group.add(gate2Group);

  // Continuous Clear Perimeter Fence Wrapping Entire DTU Campus (with only Gate 1 & Gate 2 openings!)
  const fencePostSpecs: Array<[number, number]> = [];
  const fencePicketSpecs: Array<[number, number, number]> = [];
  const addCampusFenceSegment = (x1: number, z1: number, x2: number, z2: number) => {
    const dx = x2 - x1;
    const dz = z2 - z1;
    const len = Math.hypot(dx, dz);
    if (len < 0.8) return;
    const angle = Math.atan2(-dz, dx);
    const mx = (x1 + x2) * 0.5;
    const mz = (z1 + z2) * 0.5;

    const baseWall = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(len, 0.68, 0.34)),
      plasterWhiteMat,
    );
    baseWall.position.set(mx, CAMPUS_GROUND_Y + 0.34, mz);
    baseWall.rotation.y = angle;
    baseWall.castShadow = true;
    baseWall.receiveShadow = true;

    const topRail = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(len, 0.08, 0.09)),
      blackAluminumMat,
    );
    topRail.position.set(mx, CAMPUS_GROUND_Y + 1.92, mz);
    topRail.rotation.y = angle;

    const botRail = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(len, 0.08, 0.09)),
      blackAluminumMat,
    );
    botRail.position.set(mx, CAMPUS_GROUND_Y + 0.78, mz);
    botRail.rotation.y = angle;
    group.add(baseWall, topRail, botRail);

    const postCount = Math.max(2, Math.round(len / 3.4) + 1);
    for (let i = 0; i < postCount; i++) {
      const t = i / (postCount - 1);
      fencePostSpecs.push([x1 + dx * t, z1 + dz * t]);
    }
    const picketCount = Math.floor(len / 0.48);
    for (let i = 1; i < picketCount; i++) {
      const t = i / picketCount;
      fencePicketSpecs.push([x1 + dx * t, z1 + dz * t, angle]);
    }
  };

  // South frontage (Hoàng Minh Thảo: West of Gate 1 & East of Gate 1 Monument Wall)
  addCampusFenceSegment(-47.2, 35.6, -25.8, 31.3);
  addCampusFenceSegment(-0.3, 26.2, 23.2, 21.5);
  // West frontage (Lê Hiến Mai: South of Gate 2 & North of Gate 2 Monument Wall)
  addCampusFenceSegment(-47.2, 35.6, -47.2, -42.2);
  addCampusFenceSegment(-47.2, -65.8, -47.2, -84.0);
  // North campus boundary (behind Nhà C, Nhà A, Nhà B)
  addCampusFenceSegment(-47.2, -84.0, 64.5, -84.0);
  // East campus boundary (wrapping Nhà B, Sports Complex, and East Lane)
  addCampusFenceSegment(64.5, -84.0, 64.5, -8.2);
  addCampusFenceSegment(64.5, -8.2, 23.2, -8.2);
  addCampusFenceSegment(23.2, -8.2, 23.2, 21.5);

  const fPostGeo = trackGeo(new THREE.BoxGeometry(0.38, 2.1, 0.38));
  const fPostInst = new THREE.InstancedMesh(fPostGeo, plasterWhiteMat, fencePostSpecs.length);
  fencePostSpecs.forEach(([fx, fz], i) => {
    dummy.position.set(fx, CAMPUS_GROUND_Y + 1.05, fz);
    dummy.rotation.set(0, 0, 0);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    fPostInst.setMatrixAt(i, dummy.matrix);
  });
  fPostInst.instanceMatrix.needsUpdate = true;

  const fPicketGeo = trackGeo(new THREE.BoxGeometry(0.06, 1.18, 0.06));
  const fPicketInst = new THREE.InstancedMesh(fPicketGeo, blackAluminumMat, fencePicketSpecs.length);
  fencePicketSpecs.forEach(([fx, fz, rot], i) => {
    dummy.position.set(fx, CAMPUS_GROUND_Y + 1.35, fz);
    dummy.rotation.set(0, rot, 0);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    fPicketInst.setMatrixAt(i, dummy.matrix);
  });
  fPicketInst.instanceMatrix.needsUpdate = true;
  group.add(fPostInst, fPicketInst);

  // =========================================================================
  // 5. NHÀ F (KHOA Y / MEDSIM — MẶT LƯỚI LAM BẠC + SẢNH KÍNH 2 TẦNG ĐÚNG ẢNH 2 & 4!)
  // =========================================================================
  const buildBlockF = (x: number, z: number) => {
    const w = 22.8;
    const d = 22.4;
    const atriumH = 6.2; // 2-story tall glazed atrium colonnade!
    const upperH = 9.8; // 3 upper stories wrapped in silver/white metal louver grids!
    const totalH = atriumH + upperH;

    const fg = new THREE.Group();
    fg.position.set(x, CAMPUS_GROUND_Y, z);

    const plinth = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w + 2.2, 0.4, d + 2.2)),
      stoneGraniteMat,
    );
    plinth.position.y = 0.2;
    fg.add(plinth);

    // 2-story tall dark glass atrium core
    const atriumGlass = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w - 2.6, atriumH, d - 2.6)),
      heroGlassMat,
    );
    atriumGlass.position.y = atriumH * 0.5 + 0.3;
    fg.add(atriumGlass);

    // Warm golden glow ceiling under Nhà F's 2-story colonnade (visible in Photo 1, 5, 6!)
    const fSoffit = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w - 0.15, 0.25, d - 0.15)),
      warmLobbyGlowMat,
    );
    fSoffit.position.y = atriumH + 0.25;
    fg.add(fSoffit);

    // Tall crisp white rectangular colonnade piers around 2-story lobby
    const fCols: Array<[number, number]> = [
      [-w * 0.5 + 0.5, -d * 0.5 + 0.5],
      [-w * 0.5 + 0.5, -d * 0.17],
      [-w * 0.5 + 0.5, d * 0.17],
      [-w * 0.5 + 0.5, d * 0.5 - 0.5],
      [w * 0.5 - 0.5, -d * 0.5 + 0.5],
      [w * 0.5 - 0.5, d * 0.5 - 0.5],
      [-w * 0.17, d * 0.5 - 0.5],
      [w * 0.17, d * 0.5 - 0.5],
      [-w * 0.17, -d * 0.5 + 0.5],
      [w * 0.17, -d * 0.5 + 0.5],
    ];
    const fColGeo = trackGeo(new THREE.BoxGeometry(0.75, atriumH, 0.75));
    fCols.forEach(([cx, cz]) => {
      const col = new THREE.Mesh(fColGeo, plasterWhiteMat);
      col.position.set(cx, atriumH * 0.5 + 0.3, cz);
      col.castShadow = true;
      fg.add(col);
    });

    // Upper 3-story volume wrapped in perforated louver grids + orange horizontal trim!
    const upperBox = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w, upperH, d)),
      blockFLouverMat,
    );
    upperBox.position.y = atriumH + upperH * 0.5 + 0.3;
    upperBox.castShadow = true;
    upperBox.receiveShadow = true;
    fg.add(upperBox);

    // White parapet + emerald roof + solar panels + 2 stair penthouses
    const par = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w + 0.45, 0.75, d + 0.45)),
      plasterWhiteMat,
    );
    par.position.y = totalH + 0.45;
    fg.add(par);

    const roof = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w - 0.3, 0.18, d - 0.3)),
      emeraldRoofMat,
    );
    roof.position.y = totalH + 0.78;
    fg.add(roof);

    [
      [-4.2, 2.4, 6.2, 4.4],
      [5.5, -4.5, 4.8, 3.8],
    ].forEach(([px, pz, pw, pd]) => {
      const pBody = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(pw, 2.2, pd)), plasterWhiteMat);
      pBody.position.set(px, totalH + 1.85, pz);
      const pCap = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(pw + 0.36, 0.3, pd + 0.36)),
        terracottaTileMat,
      );
      pCap.position.set(px, totalH + 3.05, pz);
      fg.add(pBody, pCap);
    });

    for (let sx = -4.5; sx <= 5.5; sx += 3.2) {
      const panel = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(2.6, 0.18, 4.4)), solarPanelMat);
      panel.position.set(sx, totalH + 1.0, -3.5);
      panel.rotation.x = 0.14;
      fg.add(panel);
    }

    // Rooftop AC condenser units on Nhà F north-east corner (image_d5a88cbd!)
    for (let ax = 2.0; ax <= 8.0; ax += 1.5) {
      const ac = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.95, 0.65, 1.3)), plasterWhiteMat);
      ac.position.set(ax, totalH + 1.12, -8.8);
      fg.add(ac);
    }

    group.add(fg);
  };

  buildBlockF(0.6, -31.8);

  // =========================================================================
  // 5B. NHÀ E, D, C (TÂY — CÓ LƯỚI CHE NẮNG NHÔ RA + CỤC NÓNG ĐIỀU HÒA + CHỮ E/D VÀNG!)
  // =========================================================================
  const buildWhiteDtuBlock = (opts: {
    x: number;
    z: number;
    w: number;
    h: number;
    d: number;
    letterTex?: THREE.CanvasTexture;
    hasCourtyardPortal?: boolean;
    hasLatticeCanopies?: boolean;
  }) => {
    const { x, z, w, h, d, letterTex, hasCourtyardPortal, hasLatticeCanopies } = opts;
    const b = new THREE.Group();
    b.position.set(x, CAMPUS_GROUND_Y, z);

    const plinth = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w + 1.4, 0.36, d + 1.4)),
      stoneGraniteMat,
    );
    plinth.position.y = 0.18;
    plinth.receiveShadow = true;
    b.add(plinth);

    const core = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w - 0.55, h, d - 0.55)),
      academicWinMat,
    );
    core.position.y = h * 0.5 + 0.2;
    core.castShadow = true;
    core.receiveShadow = true;
    b.add(core);

    const stories = 5;
    const flH = h / stories;
    for (let fl = 1; fl <= stories; fl++) {
      const slab = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(w + 0.62, 0.32, d + 0.62)),
        plasterWhiteMat,
      );
      slab.position.y = fl * flH + 0.16;
      slab.castShadow = true;
      slab.receiveShadow = true;
      b.add(slab);
    }

    // Protruding white wire-lattice sunshade awnings + AC outdoor units along East courtyard face (Photo 4!)
    if (hasLatticeCanopies) {
      for (let fl = 1; fl <= 4; fl++) {
        const canopy = new THREE.Mesh(
          trackGeo(new THREE.BoxGeometry(0.95, 0.08, d - 1.6)),
          plasterWhiteMat,
        );
        canopy.position.set(w * 0.5 + 0.42, fl * flH - 0.45, 0);
        b.add(canopy);
      }
      for (let az = -d * 0.38; az <= d * 0.38; az += 4.6) {
        for (let fl = 1; fl <= 3; fl++) {
          const acUnit = new THREE.Mesh(
            trackGeo(new THREE.BoxGeometry(0.32, 0.52, 0.72)),
            creamPlasterMat,
          );
          acUnit.position.set(w * 0.5 + 0.14, fl * flH + 0.9, az);
          b.add(acUnit);
        }
      }
    }

    const colsX = Math.max(3, Math.round(w / 3.4));
    const colsZ = Math.max(4, Math.round(d / 3.2));
    const colPositions: Array<[number, number, number, number]> = [];
    for (let i = 0; i <= colsX; i++) {
      const cx = -w * 0.5 + (i / colsX) * w;
      colPositions.push([cx, d * 0.5 - 0.02, 0.52, 0.52]);
      colPositions.push([cx, -d * 0.5 + 0.02, 0.52, 0.52]);
    }
    for (let j = 1; j < colsZ; j++) {
      const cz = -d * 0.5 + (j / colsZ) * d;
      colPositions.push([-w * 0.5 + 0.02, cz, 0.52, 0.52]);
      colPositions.push([w * 0.5 - 0.02, cz, 0.52, 0.52]);
    }
    const colsInst = new THREE.InstancedMesh(unitBoxGeo, plasterWhiteMat, colPositions.length);
    colPositions.forEach(([cx, cz, cw, cd], i) => {
      dummy.position.set(cx, h * 0.5 + 0.2, cz);
      dummy.rotation.set(0, 0, 0);
      dummy.scale.set(cw, h + 0.2, cd);
      dummy.updateMatrix();
      colsInst.setMatrixAt(i, dummy.matrix);
    });
    colsInst.instanceMatrix.needsUpdate = true;
    colsInst.castShadow = true;
    b.add(colsInst);

    if (letterTex) {
      const whiteCornerBay = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(w * 0.34, h + 0.35, 0.46)),
        plasterWhiteMat,
      );
      whiteCornerBay.position.set(w * 0.32, h * 0.5 + 0.2, d * 0.5 - 0.08);
      b.add(whiteCornerBay);

      const brownShaft = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(1.65, h + 0.1, 0.36)),
        brownStairwellMat,
      );
      brownShaft.position.set(w * 0.06, h * 0.5 + 0.2, d * 0.5 - 0.12);
      b.add(brownShaft);

      const letterMat = trackMat(new THREE.MeshBasicMaterial({ map: letterTex, transparent: true }));
      const letterPlane = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(2.3, 2.3)), letterMat);
      letterPlane.position.set(w * 0.32, h - 1.55, d * 0.5 + 0.18);
      b.add(letterPlane);

      // Also show golden letter on upper-east courtyard wall (matches Photo 4 "D" visible from courtyard!)
      const sideLetter = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(2.0, 2.0)), letterMat);
      sideLetter.position.set(w * 0.5 + 0.22, h - 1.55, d * 0.34);
      sideLetter.rotation.y = Math.PI * 0.5;
      b.add(sideLetter);

      for (let fl = 1; fl <= 4; fl++) {
        const wing = new THREE.Mesh(
          trackGeo(new THREE.BoxGeometry(1.15, 0.26, 0.72)),
          plasterWhiteMat,
        );
        wing.position.set(w * 0.5 + 0.35, fl * flH + 0.16, d * 0.5 - 0.1);
        b.add(wing);
      }
    }

    if (hasCourtyardPortal) {
      const portal = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.55, flH * 2.9, d * 0.32)),
        darkStonePortalMat,
      );
      portal.position.set(w * 0.5 - 0.06, flH * 1.45 + 0.2, 0);
      b.add(portal);
    }

    const parThick = 0.45;
    const parH = 0.85;
    const parY = h + 0.22 + parH * 0.5;
    const parWalls: Array<[number, number, number, number]> = [
      [0, d * 0.5 + 0.05, w + 0.55, parThick],
      [0, -d * 0.5 - 0.05, w + 0.55, parThick],
      [-w * 0.5 - 0.05, 0, parThick, d + 0.55],
      [w * 0.5 + 0.05, 0, parThick, d + 0.55],
    ];
    parWalls.forEach(([px, pz, pw, pd]) => {
      const pwMesh = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(pw, parH, pd)), plasterWhiteMat);
      pwMesh.position.set(px, parY, pz);
      b.add(pwMesh);
    });

    const emeraldRoof = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w - 0.25, 0.18, d - 0.25)),
      emeraldRoofMat,
    );
    emeraldRoof.position.y = h + 0.52;
    emeraldRoof.receiveShadow = true;
    b.add(emeraldRoof);

    const pBody = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(Math.min(5.2, w * 0.5), 2.25, Math.min(4.6, d * 0.22))),
      plasterWhiteMat,
    );
    pBody.position.set(0, h + 1.68, d * 0.14);
    pBody.castShadow = true;
    const pCap = new THREE.Mesh(
      trackGeo(
        new THREE.BoxGeometry(Math.min(5.2, w * 0.5) + 0.36, 0.3, Math.min(4.6, d * 0.22) + 0.36),
      ),
      terracottaTileMat,
    );
    pCap.position.set(0, h + 2.9, d * 0.14);
    b.add(pBody, pCap);

    group.add(b);
  };

  buildWhiteDtuBlock({
    x: -29.8,
    z: 3.8,
    w: 11.2,
    h: 15.4,
    d: 27.6,
    letterTex: letterETex,
    hasCourtyardPortal: true,
    hasLatticeCanopies: true,
  });

  buildWhiteDtuBlock({
    x: -29.8,
    z: -29.2,
    w: 11.2,
    h: 15.4,
    d: 25.0,
    letterTex: letterDTex,
    hasLatticeCanopies: true,
  });

  buildWhiteDtuBlock({
    x: -29.8,
    z: -68.0,
    w: 10.6,
    h: 14.8,
    d: 20.5,
    letterTex: letterCTex,
    hasLatticeCanopies: false,
  });

  // Ground-floor covered walkway linking Nhà E & Nhà D + South portico awning on Nhà E (image_d5a88cbd!)
  const edConnector = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(4.4, 3.2, 6.8)),
    plasterWhiteMat,
  );
  edConnector.position.set(-29.8, CAMPUS_GROUND_Y + 1.6, -13.35);
  const eSouthCanopy = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(6.4, 0.24, 2.4)),
    plasterWhiteMat,
  );
  eSouthCanopy.position.set(-29.8, CAMPUS_GROUND_Y + 3.4, 18.6);
  group.add(edConnector, eSouthCanopy);

  // Nhà A (3 dãy Bếp & Thực hành Du lịch nối liền cạnh Nhà C, tường hồi trắng + cầu nối + sân vườn, image_f990b422!)
  const blockARoofMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x8a7066, roughness: 0.74 }),
  );
  const blockARoofGeo = trackGeo(createGableRoofGeo(8.2, 1.45, 21.8));
  const blockAXs = [-16.6, -4.4, 7.8];
  blockAXs.forEach((hx, idx) => {
    const hall = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(8.2, 5.2, 22.0)),
      creamPlasterMat,
    );
    hall.position.set(hx, CAMPUS_GROUND_Y + 2.6, -70.0);
    hall.castShadow = true;
    hall.receiveShadow = true;
    group.add(hall);

    const sideBand = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(8.28, 1.55, 19.2)),
      academicWinMat,
    );
    sideBand.position.set(hx, CAMPUS_GROUND_Y + 3.1, -70.0);
    group.add(sideBand);

    // Crisp white South & North gable parapet walls framing the corrugated roof (exact image_f990b422!)
    [-80.95, -59.05].forEach((gz) => {
      const endParapet = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(8.6, 1.8, 0.45)),
        plasterWhiteMat,
      );
      endParapet.position.set(hx, CAMPUS_GROUND_Y + 5.75, gz);
      group.add(endParapet);
    });

    const roofPeak = new THREE.Mesh(blockARoofGeo, blockARoofMat);
    roofPeak.position.set(hx, CAMPUS_GROUND_Y + 5.2, -70.0);
    roofPeak.castShadow = true;
    group.add(roofPeak);

    const ridgeVent = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.15, 0.34, 19.8)),
      plasterWhiteMat,
    );
    ridgeVent.position.set(hx, CAMPUS_GROUND_Y + 6.72, -70.0);
    group.add(ridgeVent);

    const awning = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(8.4, 0.16, 1.8)),
      plasterWhiteMat,
    );
    awning.position.set(hx, CAMPUS_GROUND_Y + 3.3, -58.3);
    group.add(awning);

    // Elevated white sky-bridges & lush green garden courtyards between the 3 parallel halls (image_f990b422!)
    if (idx < 2) {
      const midX = (hx + blockAXs[idx + 1]) * 0.5;
      const gardenStrip = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(3.4, 0.18, 19.2)),
        grassFieldMat,
      );
      gardenStrip.position.set(midX, CAMPUS_GROUND_Y + 0.09, -70.0);
      group.add(gardenStrip);

      [-75.0, -65.0].forEach((bz) => {
        const bridge = new THREE.Mesh(
          trackGeo(new THREE.BoxGeometry(4.2, 0.55, 2.2)),
          plasterWhiteMat,
        );
        bridge.position.set(midX, CAMPUS_GROUND_Y + 3.6, bz);
        group.add(bridge);
      });
    }
  });

  // Low covered white connector linking Nhà C (-24.5) to Hall A1 (-20.7) + East covered bike shed along Hall A3 (image_f990b422!)
  const cToAConnector = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(4.2, 3.6, 5.4)),
    plasterWhiteMat,
  );
  cToAConnector.position.set(-22.6, CAMPUS_GROUND_Y + 1.8, -62.0);
  const a3EastShed = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.18, 22.0)),
    stoneGraniteMat,
  );
  a3EastShed.position.set(13.6, CAMPUS_GROUND_Y + 3.2, -70.0);
  a3EastShed.rotation.z = -0.14;
  group.add(cToAConnector, a3EastShed);

  // =========================================================================
  // 5C. NHÀ B (MÁI TÔN XANH CHỮ A CÓ NÓC THÔNG GIÓ) + CỤM SÂN BÓNG ĐÁ, BÓNG RỔ & TENNIS (image_b08ac20a!)
  // =========================================================================
  const hallBGroup = new THREE.Group();
  hallBGroup.position.set(42.5, CAMPUS_GROUND_Y, -62.0);
  const hallBBody = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(38.0, 6.2, 15.0)),
    plasterWhiteMat,
  );
  hallBBody.position.y = 3.1;
  hallBBody.castShadow = true;
  hallBBody.receiveShadow = true;
  hallBGroup.add(hallBBody);

  for (let bx = -14; bx <= 14; bx += 7.0) {
    const door = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(4.4, 3.8, 0.3)), blackAluminumMat);
    door.position.set(bx, 1.9, 7.52);
    hallBGroup.add(door);
  }
  const hallBGableGeo = trackGeo(createGableRoofGeo(16.4, 2.3, 39.2));
  const hallBRoof = new THREE.Mesh(hallBGableGeo, emeraldRoofMat);
  hallBRoof.rotation.y = Math.PI * 0.5;
  hallBRoof.position.y = 6.2;
  hallBRoof.castShadow = true;
  hallBGroup.add(hallBRoof);

  const hallBRidge = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(36.8, 0.85, 2.2)),
    emeraldRoofMat,
  );
  hallBRidge.position.y = 8.75;
  hallBGroup.add(hallBRidge);
  group.add(hallBGroup);

  // Small round fountain & garden circle west of Nhà B (visible in image_b08ac20a!)
  const bFountain = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(1.7, 1.85, 0.36, 20)),
    creamStoneMat,
  );
  bFountain.position.set(18.5, CAMPUS_GROUND_Y + 0.18, -58.5);
  group.add(bFountain);

  // 2 Artificial-Turf Mini Football Pitches right South of Nhà B
  const miniPitchMesh = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(38.0, 17.5)),
    trackMat(new THREE.MeshStandardMaterial({ map: miniPitchTex, roughness: 0.88 })),
  );
  miniPitchMesh.rotation.x = -Math.PI / 2;
  miniPitchMesh.position.set(42.5, CAMPUS_GROUND_Y + 0.08, -43.5);
  miniPitchMesh.receiveShadow = true;
  group.add(miniPitchMesh);

  const fencePoleGeo = trackGeo(new THREE.CylinderGeometry(0.08, 0.1, 4.8, 6));
  for (let fx = 23.5; fx <= 61.5; fx += 6.2) {
    [-52.3, -34.7].forEach((fz) => {
      const fp = new THREE.Mesh(fencePoleGeo, blackAluminumMat);
      fp.position.set(fx, CAMPUS_GROUND_Y + 2.4, fz);
      group.add(fp);
    });
  }
  [24.6, 41.2, 43.8, 60.4].forEach((gx) => {
    const goal = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.9, 2.1, 4.2)), roadLineMat);
    goal.position.set(gx, CAMPUS_GROUND_Y + 1.05, -43.5);
    group.add(goal);
  });

  // 4 Parallel Dark-Corrugated Bike/Spectator Sheds with Support Posts (image_b08ac20a!)
  [
    [30.5, -31.8],
    [39.5, -31.8],
    [30.5, -26.8],
    [39.5, -26.8],
  ].forEach(([sx, sz]) => {
    const shedRoof = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(7.8, 0.16, 2.4)),
      darkSlateRoofMat,
    );
    shedRoof.position.set(sx, CAMPUS_GROUND_Y + 2.85, sz);
    shedRoof.rotation.x = 0.08;
    group.add(shedRoof);

    [-3.2, 0, 3.2].forEach((ox) => {
      const post = new THREE.Mesh(
        trackGeo(new THREE.CylinderGeometry(0.06, 0.06, 2.8, 6)),
        blackAluminumMat,
      );
      post.position.set(sx + ox, CAMPUS_GROUND_Y + 1.4, sz);
      group.add(post);
    });
  });

  // 3 Stepped White Concrete Spectator Bleachers SW of Blue Tennis Complex (exact image_b08ac20a!)
  [-23.0, -21.2, -19.4].forEach((bz) => {
    const bench = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(7.6, 0.5, 0.85)),
      plasterWhiteMat,
    );
    bench.position.set(27.2, CAMPUS_GROUND_Y + 0.25, bz);
    bench.rotation.y = 0.42;
    group.add(bench);
  });

  // Light-Concrete Basketball Court East of the Sheds (image_b08ac20a!)
  const basketballMesh = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(15.0, 11.2)),
    trackMat(new THREE.MeshStandardMaterial({ map: multiSportTex, roughness: 0.86 })),
  );
  basketballMesh.rotation.x = -Math.PI / 2;
  basketballMesh.position.set(54.0, CAMPUS_GROUND_Y + 0.08, -29.2);
  basketballMesh.receiveShadow = true;
  group.add(basketballMesh);

  [47.6, 60.4].forEach((hx) => {
    const pole = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.22, 3.3, 0.22)), blackAluminumMat);
    pole.position.set(hx, CAMPUS_GROUND_Y + 1.65, -29.2);
    const board = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.12, 1.05, 1.65)), plasterWhiteMat);
    board.position.set(hx + (hx < 54 ? 0.32 : -0.32), CAMPUS_GROUND_Y + 2.95, -29.2);
    group.add(pole, board);
  });

  // 4-Court Blue-Bordered Tennis Complex (SW) + 2-Court Brick-Red Tennis Complex (SE) (image_b08ac20a!)
  const blueTennisMesh = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(21.5, 14.0)),
    trackMat(new THREE.MeshStandardMaterial({ map: blueTennisTex, roughness: 0.84 })),
  );
  blueTennisMesh.rotation.x = -Math.PI / 2;
  blueTennisMesh.position.set(34.5, CAMPUS_GROUND_Y + 0.08, -16.2);
  blueTennisMesh.receiveShadow = true;

  const redTennisMesh = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(14.5, 14.0)),
    trackMat(new THREE.MeshStandardMaterial({ map: redTennisTex, roughness: 0.84 })),
  );
  redTennisMesh.rotation.x = -Math.PI / 2;
  redTennisMesh.position.set(54.0, CAMPUS_GROUND_Y + 0.08, -16.2);
  redTennisMesh.receiveShadow = true;
  group.add(blueTennisMesh, redTennisMesh);

  // 3D Tennis Nets across all 6 Courts (4 Blue + 2 Red) + Perimeter Mesh Poles
  [
    [29.8, -19.2],
    [39.2, -19.2],
    [29.8, -13.2],
    [39.2, -13.2],
    [50.6, -16.2],
    [57.4, -16.2],
  ].forEach(([nx, nz]) => {
    const net = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.08, 0.72, nz === -16.2 ? 10.6 : 4.6)),
      roadLineMat,
    );
    net.position.set(nx, CAMPUS_GROUND_Y + 0.42, nz);
    group.add(net);
  });
  for (let tx = 24.0; tx <= 61.2; tx += 6.2) {
    [-23.2, -9.2].forEach((tz) => {
      const tp = new THREE.Mesh(fencePoleGeo, blackAluminumMat);
      tp.position.set(tx, CAMPUS_GROUND_Y + 2.1, tz);
      group.add(tp);
    });
  }

  // =========================================================================
  // 6. NHÀ XE SINH VIÊN + CHỐT BẢO VỆ MÁI ĐỎ + BÃI XE ĐÔNG ĐÚC
  // =========================================================================
  const polyRoofMat = trackMat(
    new THREE.MeshPhysicalMaterial({
      color: 0x6ba69d,
      roughness: 0.28,
      metalness: 0.15,
      transparent: true,
      opacity: 0.72,
    }),
  );

  const shedX = -43.4;
  const shed1Front = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(6.2, 0.16, 15.0)), polyRoofMat);
  shed1Front.position.set(shedX, CAMPUS_GROUND_Y + 3.4, 21.0);
  shed1Front.rotation.z = 0.05;
  group.add(shed1Front);

  for (let rz = 14.5; rz <= 27.5; rz += 2.6) {
    const rib = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(6.4, 0.18, 0.14)), blackAluminumMat);
    rib.position.set(shedX, CAMPUS_GROUND_Y + 3.35, rz);
    group.add(rib);
  }

  const shed1Back = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(6.2, 0.24, 18.0)), emeraldRoofMat);
  shed1Back.position.set(shedX, CAMPUS_GROUND_Y + 3.45, 4.5);
  shed1Back.rotation.z = 0.05;
  group.add(shed1Back);

  const shed2 = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(6.2, 0.24, 28.0)), emeraldRoofMat);
  shed2.position.set(shedX, CAMPUS_GROUND_Y + 3.45, -24.5);
  shed2.rotation.z = 0.05;
  group.add(shed2);

  const shedPostZ = [27.5, 20.5, 13.5, 6.5, -1.5, -11.5, -20.5, -29.5, -37.5];
  const shedPostsInst = new THREE.InstancedMesh(
    trackGeo(new THREE.CylinderGeometry(0.11, 0.12, 3.4, 6)),
    blackAluminumMat,
    shedPostZ.length * 2,
  );
  shedPostZ.forEach((pz, i) => {
    [-2.5, 2.5].forEach((ox, side) => {
      dummy.position.set(shedX + ox, CAMPUS_GROUND_Y + 1.7, pz);
      dummy.rotation.set(0, 0, 0);
      dummy.scale.set(1, 1, 1);
      dummy.updateMatrix();
      shedPostsInst.setMatrixAt(i * 2 + side, dummy.matrix);
    });
  });
  shedPostsInst.instanceMatrix.needsUpdate = true;
  group.add(shedPostsInst);

  const kiosk = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(5.2, 2.3, 2.4)), plasterWhiteMat);
  kiosk.position.set(-37.8, CAMPUS_GROUND_Y + 1.15, 28.2);
  const kioskRoof = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(5.8, 0.25, 2.8)), blackAluminumMat);
  kioskRoof.position.set(-37.8, CAMPUS_GROUND_Y + 2.4, 28.2);
  group.add(kiosk, kioskRoof);

  const guardGroup = new THREE.Group();
  guardGroup.position.set(-23.2, CAMPUS_GROUND_Y, 29.5);
  const gBase = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(4.8, 3.1, 4.8)), plasterWhiteMat);
  gBase.position.y = 1.55;
  gBase.castShadow = true;
  const gWin = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(4.92, 1.15, 4.92)), blackAluminumMat);
  gWin.position.y = 2.05;
  const gEave = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(5.6, 0.22, 5.6)), plasterWhiteMat);
  gEave.position.y = 3.15;
  const gRoof = new THREE.Mesh(trackGeo(new THREE.ConeGeometry(4.35, 2.35, 4)), terracottaTileMat);
  gRoof.position.y = 4.35;
  gRoof.rotation.y = Math.PI * 0.25;
  gRoof.castShadow = true;
  const barrierArm = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(5.4, 0.14, 0.14)), crimsonAccentMat);
  barrierArm.position.set(4.5, 1.1, 0);
  guardGroup.add(gBase, gWin, gEave, gRoof, barrierArm);
  group.add(guardGroup);

  // =========================================================================
  // 7. KHU ĐỐI DIỆN THEO ĐÚNG ẢNH VỆ TINH GOOGLE MAPS (step_38.png):
  //    - Đại lộ Đôi 122 Hoàng Minh Thảo chạy thẳng XUYÊN từ Lê Hiến Mai (x=-56.2) tới Đại lộ Lê Trọng Tấn (x=-188)
  //    - Cụm Trung tâm GDQP & AN · ĐH TDTT Đà Nẵng CS2 (bên Nam/Đông đại lộ đôi) + Sân tập lái xe nhiều khúc cua + Vòng xuyến oval
  //    - Sân vận động điền kinh mở nằm gọn trong vòng đường oval khép kín 360°
  // =========================================================================
  const flagRedMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xc81e1e, roughness: 0.55 }),
  );
  const defInoxMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xdbe2ea, roughness: 0.28, metalness: 0.76 }),
  );
  const defWaterTankGeo = trackGeo(createWaterTankGeo());

  // 7A. ĐẠI LỘ ĐÔI CHIA 2 LÀN CHẠY XUYÊN TỪ LÊ HIẾN MAI (x=-56.2) ĐẾN ĐẠI LỘ LÊ TRỌNG TẤN (x=-188) — KHÔNG CẮT CỤT!
  const dualAveDeck = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(134.0, 0.12, 22.0)),
    roadAsphaltMat,
  );
  dualAveDeck.position.set(-122.0, CAMPUS_GROUND_Y - 0.018, -3.5);
  group.add(dualAveDeck);

  // Vỉa hè lát đá 2 bên đại lộ đôi (chừa lối rẽ vào sân vận động & lối rẽ vào Trung tâm GDQP)
  const dualCurbSouth = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(124.0, 0.14, 2.2)),
    stoneGraniteMat,
  );
  dualCurbSouth.position.set(-124.0, CAMPUS_GROUND_Y + 0.05, 8.6);
  group.add(dualCurbSouth);

  // 3 đoạn dải phân cách cỏ viền đá thẳng tắp dọc tim Đại lộ Đôi (khớp 100% ảnh vệ tinh Google Maps!)
  [-81.0, -118.0, -155.0].forEach((mx) => {
    const mCurb = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(27.0, 0.2, 3.0)),
      stoneGraniteMat,
    );
    mCurb.position.set(mx, CAMPUS_GROUND_Y + 0.08, -3.5);
    const mGrass = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(26.2, 0.24, 2.3)),
      grassFieldMat,
    );
    mGrass.position.set(mx, CAMPUS_GROUND_Y + 0.11, -3.5);
    const mHedge = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(24.8, 0.36, 0.8)),
      militaryGreenMat,
    );
    mHedge.position.set(mx, CAMPUS_GROUND_Y + 0.3, -3.5);
    group.add(mCurb, mGrass, mHedge);
  });

  // Vạch đứt chia làn đường đôi + vạch đi bộ tại ngã rẽ Lê Hiến Mai
  for (let lx = -70; lx >= -176; lx -= 8.0) {
    [-9.2, 2.2].forEach((lz) => {
      const dash = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(3.8, 0.03, 0.18)),
        roadLineMat,
      );
      dash.position.set(lx, CAMPUS_GROUND_Y + 0.048, lz);
      group.add(dash);
    });
  }
  // Mặt sân nhựa phẳng rộng trước Cổng Trung tâm Giáo dục Quốc phòng & An ninh (không có vạch zebra chắn trước bệ đá)
  // Nhánh đường ngang nối Đại lộ Đôi xuống Khu Trung tâm GDQP & AN + Sân tập lái xe + Vòng xuyến oval + Hoàng Minh Thảo!
  const gdqpCrossRoad = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(9.5, 0.11, 76.0)),
    roadAsphaltMat,
  );
  gdqpCrossRoad.position.set(-168.0, CAMPUS_GROUND_Y - 0.02, 34.0);
  const gdqpEntryRoad = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(8.2, 0.1, 34.0)),
    roadAsphaltMat,
  );
  gdqpEntryRoad.position.set(-96.0, CAMPUS_GROUND_Y - 0.02, 22.0);
  group.add(gdqpCrossRoad, gdqpEntryRoad);

  // Vòng xuyến cỏ hình oval đặc trưng góc Đông-Nam trên vệ tinh Google Maps (x=-168, z=28)
  const rbtCurb = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(7.2, 7.6, 0.22, 20)),
    stoneGraniteMat,
  );
  rbtCurb.scale.set(1.35, 1, 0.85);
  rbtCurb.position.set(-168.0, CAMPUS_GROUND_Y + 0.09, 28.0);
  const rbtGrass = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(6.4, 6.6, 0.26, 20)),
    grassFieldMat,
  );
  rbtGrass.scale.set(1.35, 1, 0.85);
  rbtGrass.position.set(-168.0, CAMPUS_GROUND_Y + 0.11, 28.0);
  group.add(rbtCurb, rbtGrass);

  // =========================================================================
  // CỔNG TRUNG TÂM GIÁO DỤC QUỐC PHÒNG VÀ AN NINH — 122 HOÀNG MINH THẢO (ĐH TDTT ĐÀ NẴNG)
  // Dựng sát thực tế theo ảnh chụp: Bảng hiệu tường đá granite thấp + 2 trụ đá xám chia rãnh ngang,
  // chốt bảo vệ sơn trắng mái ngói đỏ 4 mái viền trắng đua rộng phía sau, cổng xếp inox chữ X 2 bên + biển vàng.
  // =========================================================================
  const qpStoneDarkMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x52575e, roughness: 0.88, metalness: 0.05 }),
  );
  const qpPillarGreyMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x8e959e, roughness: 0.84, metalness: 0.06 }),
  );
  const qpStainlessMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xe6ecf2, roughness: 0.28, metalness: 0.42 }),
  );

  const gateX = -65.2;
  const signCenterZ = -4.6;

  // 1) Bệ chân đá xám đậm giật cấp & Thân tường bảng hiệu đá kem
  const qpPlinth = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.3, 0.44, 7.8)),
    qpStoneDarkMat,
  );
  qpPlinth.position.set(gateX, CAMPUS_GROUND_Y + 0.22, signCenterZ);
  const qpPlinthLip = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.42, 0.1, 7.95)),
    qpPillarGreyMat,
  );
  qpPlinthLip.position.set(gateX, CAMPUS_GROUND_Y + 0.44, signCenterZ);

  const qpWallBody = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.62, 2.1, 6.2)),
    creamStoneMat,
  );
  qpWallBody.position.set(gateX, CAMPUS_GROUND_Y + 1.5, signCenterZ);
  const qpWallCap = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.72, 0.1, 6.32)),
    qpStoneDarkMat,
  );
  qpWallCap.position.set(gateX, CAMPUS_GROUND_Y + 2.58, signCenterZ);

  // Mặt bảng hiệu chữ 4 dòng chuẩn ảnh thật quay ra đường Lê Hiến Mai (+X)
  const qpSignMat = trackMat(new THREE.MeshBasicMaterial({ map: qpGateSignTex }));
  const qpSignFront = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(6.14, 2.04)), qpSignMat);
  qpSignFront.position.set(gateX + 0.325, CAMPUS_GROUND_Y + 1.5, signCenterZ);
  qpSignFront.rotation.y = Math.PI * 0.5;
  group.add(qpPlinth, qpPlinthLip, qpWallBody, qpWallCap, qpSignFront);

  // 2) Hai trụ đá xám chia rãnh ngang (Ashlar pillars) kẹp 2 đầu bảng hiệu + trụ mép phải
  const addRusticatedStonePillar = (px: number, pz: number, height: number, width: number) => {
    const core = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(width * 0.86, height, width * 0.86)),
      qpStoneDarkMat,
    );
    core.position.set(px, CAMPUS_GROUND_Y + height * 0.5, pz);
    group.add(core);
    const courses = Math.max(4, Math.round(height / 0.38));
    const stepH = (height - 0.16) / courses;
    for (let i = 0; i < courses; i++) {
      const block = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(width, stepH * 0.84, width)),
        qpPillarGreyMat,
      );
      block.position.set(px, CAMPUS_GROUND_Y + 0.08 + stepH * (i + 0.5), pz);
      group.add(block);
    }
    const cap = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(width + 0.16, 0.16, width + 0.16)),
      qpPillarGreyMat,
    );
    cap.position.set(px, CAMPUS_GROUND_Y + height + 0.06, pz);
    group.add(cap);
  };
  addRusticatedStonePillar(gateX, signCenterZ + 3.45, 2.95, 0.96); // Trụ trái (sát chốt bảo vệ, cao hơn bảng hiệu)
  addRusticatedStonePillar(gateX, signCenterZ - 3.45, 2.7, 0.92);  // Trụ phải bảng hiệu
  addRusticatedStonePillar(gateX - 0.1, -16.6, 2.35, 0.82);        // Trụ đá mép phải nối tường rào

  // Đoạn tường rào bên phải nối sau trụ mép phải
  const qpRightWall = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.32, 1.95, 3.6)),
    creamStoneMat,
  );
  qpRightWall.position.set(gateX - 0.1, CAMPUS_GROUND_Y + 0.98, -18.8);
  const qpRightWallCap = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.4, 0.1, 3.65)),
    qpPillarGreyMat,
  );
  qpRightWallCap.position.set(gateX - 0.1, CAMPUS_GROUND_Y + 1.98, -18.8);
  group.add(qpRightWall, qpRightWallCap);

  // 3) Chốt bảo vệ sơn trắng, mái ngói đỏ chóp 4 mái + viền diềm mái trắng đua rộng đặt ngay sau bảng hiệu (nhô cao rõ tường trắng + mái ngói như ảnh thật!)
  const defGuardGroup = new THREE.Group();
  defGuardGroup.position.set(gateX - 2.35, CAMPUS_GROUND_Y, signCenterZ + 1.85);
  const dgPad = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(3.4, 0.22, 3.4)), qpStoneDarkMat);
  dgPad.position.y = 0.11;
  const dgBase = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(2.7, 3.3, 2.7)), plasterWhiteMat);
  dgBase.position.y = 1.76;
  const dgWin = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(2.76, 1.0, 2.76)), blackAluminumMat);
  dgWin.position.y = 2.25;
  const dgLouver = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(2.78, 0.24, 1.25)), qpPillarGreyMat);
  dgLouver.position.set(0, 2.08, 0.72);
  // Viền diềm mái bê tông đua rộng nổi bật như ảnh thật
  const dgEaveBot = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(4.05, 0.2, 4.05)), qpPillarGreyMat);
  dgEaveBot.position.y = 3.44;
  const dgEaveTop = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(4.25, 0.18, 4.25)), plasterWhiteMat);
  dgEaveTop.position.y = 3.62;
  // Mái ngói đỏ chóp 4 mái
  const dgRoof = new THREE.Mesh(trackGeo(new THREE.ConeGeometry(3.02, 1.52, 4)), terracottaTileMat);
  dgRoof.position.y = 4.46;
  dgRoof.rotation.y = Math.PI * 0.25;
  defGuardGroup.add(dgPad, dgBase, dgWin, dgLouver, dgEaveBot, dgEaveTop, dgRoof);
  group.add(defGuardGroup);

  // 4) Hệ thống Cổng xếp Inox tự động (thanh đứng + thanh chéo chữ X + thanh bo đỉnh) — gộp thành 1 draw call qua mergeStaticMeshes!
  const addAccordionGate = (zStart: number, zEnd: number, gx: number) => {
    const zMin = Math.min(zStart, zEnd);
    const zMax = Math.max(zStart, zEnd);
    const span = zMax - zMin;
    const bays = Math.max(2, Math.round(span / 0.56));
    const step = span / bays;
    const h = 1.52;

    // Thanh đế & thanh bo trên đầu cổng xếp
    const botRail = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.18, 0.1, span)), qpStainlessMat);
    botRail.position.set(gx, CAMPUS_GROUND_Y + 0.08, (zMin + zMax) * 0.5);
    const topRail = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.12, 0.08, span)), qpStainlessMat);
    topRail.position.set(gx, CAMPUS_GROUND_Y + h + 0.04, (zMin + zMax) * 0.5);
    group.add(botRail, topRail);

    const diagLen = Math.hypot(step, h * 0.82);
    const diagAngle = Math.atan2(h * 0.82, step);
    for (let i = 0; i <= bays; i++) {
      const zp = zMin + i * step;
      const post = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.07, h, 0.07)), qpStainlessMat);
      post.position.set(gx, CAMPUS_GROUND_Y + h * 0.5 + 0.05, zp);
      group.add(post);
      if (i < bays) {
        const zMid = zp + step * 0.5;
        const d1 = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.045, 0.045, diagLen)), qpStainlessMat);
        d1.position.set(gx + 0.04, CAMPUS_GROUND_Y + h * 0.5 + 0.05, zMid);
        d1.rotation.x = diagAngle;
        const d2 = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.045, 0.045, diagLen)), qpStainlessMat);
        d2.position.set(gx - 0.04, CAMPUS_GROUND_Y + h * 0.5 + 0.05, zMid);
        d2.rotation.x = -diagAngle;
        group.add(d1, d2);
      }
    }
  };
  // Cánh cổng xếp bên phải bảng hiệu (nối từ trụ phải bảng hiệu đến trụ đá mép phải)
  addAccordionGate(signCenterZ - 3.95, -16.15, gateX - 0.15);
  // Cánh cổng xếp bên trái bảng hiệu (kéo ra nửa đường, chừa lối mở rộng cho xe ra vào bên trái y ảnh thật!)
  addAccordionGate(signCenterZ + 3.95, 3.2, gateX - 0.15);
  // Cụm cổng xếp đang thu gọn phía mép trái lối xe vào
  addAccordionGate(7.4, 11.4, gateX - 0.15);

  // 5) Biển báo nhỏ nền vàng chữ đỏ bên lề trái lối xe vào + 2 cột đèn cao 2 nhánh phía sau chốt bảo vệ (như ảnh thật!)
  const noticePole = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.05, 0.05, 2.1, 6)), qpPillarGreyMat);
  noticePole.position.set(gateX - 4.2, CAMPUS_GROUND_Y + 1.05, 3.6);
  const noticeBoardMat = trackMat(new THREE.MeshBasicMaterial({ map: qpNoticeSignTex }));
  const noticeBoard = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.08, 0.78, 1.05)), [
    noticeBoardMat,
    noticeBoardMat,
    qpPillarGreyMat,
    qpPillarGreyMat,
    qpPillarGreyMat,
    qpPillarGreyMat,
  ]);
  noticeBoard.position.set(gateX - 4.2, CAMPUS_GROUND_Y + 1.85, 3.6);
  group.add(noticePole, noticeBoard);

  [signCenterZ + 2.8, signCenterZ - 3.2].forEach((lz) => {
    const tallPole = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.07, 0.11, 9.6, 8)), qpPillarGreyMat);
    tallPole.position.set(gateX - 6.8, CAMPUS_GROUND_Y + 4.8, lz);
    const armL = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.06, 0.06, 1.35)), qpPillarGreyMat);
    armL.position.set(gateX - 6.8, CAMPUS_GROUND_Y + 9.45, lz + 0.62);
    armL.rotation.x = -0.22;
    const armR = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.06, 0.06, 1.35)), qpPillarGreyMat);
    armR.position.set(gateX - 6.8, CAMPUS_GROUND_Y + 9.45, lz - 0.62);
    armR.rotation.x = 0.22;
    group.add(tallPole, armL, armR);
  });

  // 7B-SOUTH: CỤM TRUNG TÂM GDQP & AN · ĐH TDTT ĐÀ NẴNG CS2 (ĐÚNG TỌA ĐỘ GHIM ĐỎ TRÊN VỆ TINH step_38.png!)
  // Nền sân bê tông khuôn viên Trung tâm GDQP & ĐH TDTT CS2 (x=-74..-132, z=12..42)
  const gdqpSouthYard = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(54.0, 0.12, 30.0)),
    stoneGraniteMat,
  );
  gdqpSouthYard.position.set(-104.0, CAMPUS_GROUND_Y + 0.02, 27.5);
  group.add(gdqpSouthYard);

  // 2 khối Giảng đường & Nhà hiệu bộ ĐH TDTT CS2 / TT GDQP & AN xếp góc chữ L ngay vị trí ghim Google Maps
  const gdqpHall1 = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(24.0, 8.8, 9.5)), defenseWallMat);
  gdqpHall1.position.set(-108.0, CAMPUS_GROUND_Y + 4.45, 36.0);
  const gdqpRoof1 = new THREE.Mesh(trackGeo(createGableRoofGeo(10.6, 1.65, 25.2)), terracottaTileMat);
  gdqpRoof1.rotation.y = Math.PI * 0.5;
  gdqpRoof1.position.set(-108.0, CAMPUS_GROUND_Y + 8.85, 36.0);

  const gdqpHall2 = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(9.2, 7.6, 20.0)), academicWinMat);
  gdqpHall2.position.set(-83.0, CAMPUS_GROUND_Y + 3.85, 26.5);
  const gdqpRoof2 = new THREE.Mesh(trackGeo(createGableRoofGeo(10.2, 1.5, 21.0)), terracottaTileMat);
  gdqpRoof2.position.set(-83.0, CAMPUS_GROUND_Y + 7.65, 26.5);
  group.add(gdqpHall1, gdqpRoof1, gdqpHall2, gdqpRoof2);

  // Cột cờ Tổ quốc nhỏ trước sân Trung tâm GDQP & ĐH TDTT CS2
  const southFlagPole = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.07, 0.11, 11.0, 6)), defInoxMat);
  southFlagPole.position.set(-106.0, CAMPUS_GROUND_Y + 5.5, 22.5);
  const southFlag = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(1.9, 1.25, 0.06)), flagRedMat);
  southFlag.position.set(-105.0, CAMPUS_GROUND_Y + 10.2, 22.5);
  group.add(southFlagPole, southFlag);

  // SÂN TẬP LÁI XE SÁT HẠCH NHIỀU KHÚC CUA (ĐẶC TRƯNG ĐỘC ĐÁO RÕ NÉT TRÊN ẢNH VỆ TINH step_38.png GÓC DƯỚI PHẢI!)
  const drivingPad = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(28.0, 0.1, 24.0)),
    stoneGraniteMat,
  );
  drivingPad.position.set(-146.0, CAMPUS_GROUND_Y + 0.02, 24.0);
  group.add(drivingPad);
  // Các làn tập lái đường hẹp, hình chữ S & ô ghép chuồng bê tông xám trên nền sân tập lái
  [
    [-146.0, 15.0, 24.0, 2.8],
    [-146.0, 33.0, 24.0, 2.8],
    [-156.5, 24.0, 2.8, 19.0],
    [-135.5, 24.0, 2.8, 19.0],
    [-146.0, 24.0, 16.0, 2.4],
    [-141.0, 19.5, 2.2, 8.0],
    [-151.0, 28.5, 2.2, 8.0],
  ].forEach(([dx, dz, dw, dd]) => {
    const lane = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(dw, 0.06, dd)),
      roadAsphaltMat,
    );
    lane.position.set(dx, CAMPUS_GROUND_Y + 0.07, dz);
    group.add(lane);
  });

  // Dãy Nhà trực ban – Phòng y tế & Lớp học lý thuyết dọc đường Lê Hiến Mai (mái ngói đỏ sóng + hàng cột hiên)
  const roadsideGroup = new THREE.Group();
  roadsideGroup.position.set(-70.2, CAMPUS_GROUND_Y, -32.2);
  roadsideGroup.rotation.y = 0.05;
  const roadsideLongHall = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(6.2, 4.0, 28.0)),
    defenseWallMat,
  );
  roadsideLongHall.position.y = 2.0;
  const roadsideLongRoof = new THREE.Mesh(
    trackGeo(createGableRoofGeo(7.6, 1.35, 29.4)),
    terracottaTileMat,
  );
  roadsideLongRoof.position.y = 4.0;
  const roadsideVeranda = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(2.2, 0.16, 28.4)),
    stoneGraniteMat,
  );
  roadsideVeranda.position.set(3.8, 0.08, 0);
  for (let ci = -3; ci <= 3; ci++) {
    const col = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.32, 3.6, 0.32)),
      plasterWhiteMat,
    );
    col.position.set(4.5, 1.88, ci * 4.2);
    roadsideGroup.add(col);
  }
  roadsideGroup.add(roadsideLongHall, roadsideLongRoof, roadsideVeranda);
  group.add(roadsideGroup);

  // =========================================================================
  // 7B. TỔ HỢP TRUNG TÂM GIÁO DỤC QUỐC PHÒNG & AN NINH — ĐH TDTT ĐÀ NẴNG CS2
  //     (Sân điều lệnh kẻ ô + Lễ đài Cột cờ Tổ quốc + Nhà Điều hành 3 tầng
  //      + Cụm KTX Quân sự Khu A & B mái ngói đỏ + Hội trường/Nhà ăn + Sân bóng chuyền)
  // =========================================================================
  const drillPlazaMat = trackMat(
    new THREE.MeshStandardMaterial({ map: drillPlazaTex, roughness: 0.88 }),
  );
  // Nền bê tông tổng thể sân điều lệnh & chào cờ trung tâm (x = -146..-64, z = -126..-98)
  const defMainPlaza = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(74.0, 0.12, 26.5)),
    drillPlazaMat,
  );
  defMainPlaza.position.set(-106.0, CAMPUS_GROUND_Y + 0.02, -112.0);
  group.add(defMainPlaza);

  // Lễ đài chào cờ + Bức tường đỏ sao vàng + Cột cờ Tổ quốc cao 14m ở đầu Tây sân điều lệnh
  const podiumBase = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(5.6, 0.65, 14.0)),
    stoneGraniteMat,
  );
  podiumBase.position.set(-127.5, CAMPUS_GROUND_Y + 0.34, -112.0);
  const podiumWall = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.48, 3.0, 12.6)),
    flagRedMat,
  );
  podiumWall.position.set(-129.8, CAMPUS_GROUND_Y + 2.0, -112.0);
  const podiumTrim = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.56, 0.24, 12.8)),
    yellowLineMat,
  );
  podiumTrim.position.set(-129.8, CAMPUS_GROUND_Y + 3.55, -112.0);
  const flagPole = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.08, 0.14, 13.5, 8)),
    defInoxMat,
  );
  flagPole.position.set(-125.4, CAMPUS_GROUND_Y + 7.1, -112.0);
  const vnFlag = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.06, 1.55, 2.4)),
    flagRedMat,
  );
  vnFlag.position.set(-125.4, CAMPUS_GROUND_Y + 12.9, -110.75);
  const vnStar = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.08, 0.56, 0.56)),
    yellowLineMat,
  );
  vnStar.position.set(-125.4, CAMPUS_GROUND_Y + 12.9, -110.75);
  group.add(podiumBase, podiumWall, podiumTrim, flagPole, vnFlag, vnStar);

  // Tòa Nhà Điều hành & Giảng đường chính Trung tâm GDQP & AN (3 tầng mặt tiền hướng ra sân điều lệnh)
  const hqGroup = new THREE.Group();
  hqGroup.position.set(-140.5, CAMPUS_GROUND_Y, -112.0);
  const hqBase = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(11.5, 0.45, 26.5)),
    stoneGraniteMat,
  );
  hqBase.position.y = 0.22;
  const hqBody = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(10.0, 10.6, 25.0)),
    defenseWallMat,
  );
  hqBody.position.y = 5.55;
  const hqRoof = new THREE.Mesh(
    trackGeo(createGableRoofGeo(11.4, 2.0, 26.4)),
    terracottaTileMat,
  );
  hqRoof.position.y = 10.85;
  // Sảnh hiên đón 2 tầng có cột vuông + mái ngói đỏ nhô ra sân chào cờ
  const hqPortico = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.2, 0.45, 9.2)),
    plasterWhiteMat,
  );
  hqPortico.position.set(6.2, 4.1, 0);
  const hqPorticoRoof = new THREE.Mesh(
    trackGeo(createGableRoofGeo(3.6, 1.2, 9.6)),
    terracottaTileMat,
  );
  hqPorticoRoof.position.set(6.2, 4.35, 0);
  [-3.8, -1.3, 1.3, 3.8].forEach((cz) => {
    const col = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.42, 4.0, 0.42)),
      plasterWhiteMat,
    );
    col.position.set(7.4, 2.1, cz);
    hqGroup.add(col);
  });
  hqGroup.add(hqBase, hqBody, hqRoof, hqPortico, hqPorticoRoof);
  group.add(hqGroup);

  // Cụm 2 Sân bóng chuyền & Bóng rổ sinh viên nội trú ngay góc Đông sân điều lệnh (dùng nền sân xanh thể thao nổi bật)
  const defSportMat = trackMat(
    new THREE.MeshStandardMaterial({ map: blueTennisTex, roughness: 0.85 }),
  );
  [-92.0, -76.5].forEach((sx) => {
    const court = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(13.5, 0.09, 20.5)),
      defSportMat,
    );
    court.position.set(sx, CAMPUS_GROUND_Y + 0.08, -111.5);
    const netLine = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(11.0, 0.9, 0.08)),
      plasterWhiteMat,
    );
    netLine.position.set(sx, CAMPUS_GROUND_Y + 1.55, -111.5);
    [-5.6, 5.6].forEach((px) => {
      const pole = new THREE.Mesh(
        trackGeo(new THREE.CylinderGeometry(0.06, 0.07, 2.2, 6)),
        blackAluminumMat,
      );
      pole.position.set(sx + px, CAMPUS_GROUND_Y + 1.1, -111.5);
      group.add(pole);
    });
    group.add(court, netLine);
  });

  // Cụm Ký túc xá Quân sự Sinh viên Khu A & Khu B (4 khối 3–4 tầng mái ngói đỏ sóng + hành lang cột + bồn nước inox)
  const buildDefenseDormBlock = (
    bx: number,
    bz: number,
    lenX: number,
    depZ: number,
    floors: number,
    rotate90 = false,
  ) => {
    const bg = new THREE.Group();
    bg.position.set(bx, CAMPUS_GROUND_Y, bz);
    if (rotate90) bg.rotation.y = Math.PI * 0.5;
    const bh = floors * 3.05;
    const plinth = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(lenX + 1.4, 0.28, depZ + 1.4)),
      stoneGraniteMat,
    );
    plinth.position.y = 0.14;
    const body = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(lenX, bh, depZ)),
      floors >= 3 ? academicWinMat : defenseWallMat,
    );
    body.position.y = bh * 0.5 + 0.2;
    const roof = new THREE.Mesh(
      trackGeo(createGableRoofGeo(depZ + 1.3, 1.85, lenX + 1.2)),
      terracottaTileMat,
    );
    roof.rotation.y = Math.PI * 0.5;
    roof.position.y = bh + 0.2;
    // Dải lan can hành lang dài chạy dọc mặt tiền mỗi tầng + hàng cột đứng
    for (let fl = 1; fl < floors; fl++) {
      const ledge = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(lenX + 0.2, 0.24, 0.9)),
        plasterWhiteMat,
      );
      ledge.position.set(0, fl * 3.05 + 0.25, depZ * 0.5 + 0.35);
      const rail = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(lenX + 0.1, 0.72, 0.08)),
        militaryGreenMat,
      );
      rail.position.set(0, fl * 3.05 + 0.68, depZ * 0.5 + 0.76);
      bg.add(ledge, rail);
    }
    const tank = new THREE.Mesh(defWaterTankGeo, defInoxMat);
    tank.position.set(lenX * 0.32, bh + 0.2, -depZ * 0.22);
    bg.add(plinth, body, roof, tank);
    group.add(bg);
  };

  // Dãy KTX Khu A & B phía Bắc (song song đường nội bộ z = -129, tạo trục khuôn viên ngay ngắn!)
  buildDefenseDormBlock(-132, -140, 26.0, 9.2, 4, false);
  buildDefenseDormBlock(-101, -140, 26.0, 9.2, 4, false);
  buildDefenseDormBlock(-72, -140, 22.0, 9.0, 3, false);
  // Hội trường lớn & Nhà ăn tập thể sinh viên + Giảng đường GDQP phía Đông-Bắc (nối sang KDC Bắc)
  buildDefenseDormBlock(-32, -138, 25.0, 9.2, 2, false);
  buildDefenseDormBlock(-3, -138, 24.0, 9.0, 2, false);
  buildDefenseDormBlock(24, -138, 22.0, 8.8, 2, false);

  // Sân tập điều lệnh & Bãi tập chiến thuật phụ + tường rào quân đội đồng bộ dọc ranh giới
  const defFenceSpecs: Array<[number, number, number, boolean]> = [
    [-112, -98.5, 62, true],
    [-147.5, -124, 52, false],
    [-64.5, -124, 52, false],
    [-28, -121, 38, true],
    [-28, -99, 38, true],
    [-47, -110, 22, false],
    [-9, -110, 22, false],
  ];
  defFenceSpecs.forEach(([fx, fz, flen, alongX]) => {
    const baseWall = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(alongX ? flen : 0.28, 0.72, alongX ? 0.28 : flen)),
      plasterWhiteMat,
    );
    baseWall.position.set(fx, CAMPUS_GROUND_Y + 0.36, fz);
    const topRail = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(alongX ? flen : 0.14, 0.58, alongX ? 0.14 : flen)),
      militaryGreenMat,
    );
    topRail.position.set(fx, CAMPUS_GROUND_Y + 1.0, fz);
    group.add(baseWall, topRail);
  });

  // Sân vận động điền kinh đỏ ĐH TDTT Đà Nẵng CS2 (nâng cấp Khán đài A + 4 cột đèn pha + hố nhảy xa)
  const stadiumGroup = new THREE.Group();
  stadiumGroup.position.set(-114, CAMPUS_GROUND_Y + 0.04, -56);
  stadiumGroup.rotation.y = 0.08;
  group.add(stadiumGroup);

  const makeOvalShape = (straightHalf: number, radius: number): THREE.Shape => {
    const sh = new THREE.Shape();
    sh.absarc(straightHalf, 0, radius, -Math.PI * 0.5, Math.PI * 0.5, false);
    sh.absarc(-straightHalf, 0, radius, Math.PI * 0.5, Math.PI * 1.5, false);
    sh.closePath();
    return sh;
  };

  const outerApronMesh = new THREE.Mesh(
    trackGeo(new THREE.ShapeGeometry(makeOvalShape(17, 16.0), 28)),
    stoneGraniteMat,
  );
  outerApronMesh.rotation.x = -Math.PI / 2;
  outerApronMesh.position.y = 0.02;
  stadiumGroup.add(outerApronMesh);

  const redTrackMesh = new THREE.Mesh(
    trackGeo(new THREE.ShapeGeometry(makeOvalShape(17, 14.4), 28)),
    redTrackMat,
  );
  redTrackMesh.rotation.x = -Math.PI / 2;
  redTrackMesh.position.y = 0.06;
  stadiumGroup.add(redTrackMesh);

  const laneOuter = makeOvalShape(17, 12.2);
  const laneHole = new THREE.Path();
  laneHole.absarc(17, 0, 11.88, -Math.PI * 0.5, Math.PI * 0.5, false);
  laneHole.absarc(-17, 0, 11.88, Math.PI * 0.5, Math.PI * 1.5, false);
  laneOuter.holes.push(laneHole);
  const laneRingMesh = new THREE.Mesh(trackGeo(new THREE.ShapeGeometry(laneOuter, 28)), roadLineMat);
  laneRingMesh.rotation.x = -Math.PI / 2;
  laneRingMesh.position.y = 0.09;
  stadiumGroup.add(laneRingMesh);

  const infieldMesh = new THREE.Mesh(
    trackGeo(new THREE.ShapeGeometry(makeOvalShape(17, 10.2), 28)),
    grassFieldMat,
  );
  infieldMesh.rotation.x = -Math.PI / 2;
  infieldMesh.position.y = 0.11;
  stadiumGroup.add(infieldMesh);

  const pitchMesh = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(33, 18.2)),
    trackMat(new THREE.MeshStandardMaterial({ map: stadiumPitchTex, roughness: 0.88 })),
  );
  pitchMesh.rotation.x = -Math.PI / 2;
  pitchMesh.position.y = 0.14;
  stadiumGroup.add(pitchMesh);

  // 2 3D white football goal frames at pitch ends (đúng sân điền kinh mở trên ảnh vệ tinh Google Maps step_38.png!)
  [-15.2, 15.2].forEach((gx) => {
    const goalCross = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.16, 0.16, 4.8)),
      roadLineMat,
    );
    goalCross.position.set(gx, 1.85, 0);
    [-2.35, 2.35].forEach((gz) => {
      const post = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.16, 1.85, 0.16)),
        roadLineMat,
      );
      post.position.set(gx, 0.92, gz);
      stadiumGroup.add(post);
    });
    stadiumGroup.add(goalCross);
  });

  // =========================================================================
  // 8. HÀNG QUÁN THỰC TẾ ĐỐI DIỆN 120 HOÀNG MINH THẢO (Google Maps Verified!)
  //    (Guitar Coffee, Coffee Bill, Tiệm Nhà Mía, Bún Cô Ba, Photocopy, Nhà sách DTU!)
  // =========================================================================
  interface StreetShopSpec {
    x: number;
    z: number;
    rotY: number;
    title: string;
    subtitle: string;
    wallColor: number;
    signBg: string;
    signAccent: string;
    awningColor: number;
    floors: number;
  }

  const streetShops: StreetShopSpec[] = [
    {
      x: -36,
      z: 61.1,
      rotY: 0.2 + Math.PI,
      title: 'PHOTOCOPY HUY LINH · IN ĐỒ ÁN',
      subtitle: '120 HOÀNG MINH THẢO · IN MÀU · ĐÓNG BÌA CỨNG',
      wallColor: 0xf0efe9,
      signBg: '#1e3a8a',
      signAccent: '#fde047',
      awningColor: 0x2a5496,
      floors: 3,
    },
    {
      x: -24,
      z: 58.6,
      rotY: 0.2 + Math.PI,
      title: 'LAND COFFEE · HOÀNG MINH THẢO',
      subtitle: 'CÀ PHÊ SINH VIÊN · TRÀ ĐÀO · WIFI HỌC NHÓM',
      wallColor: 0xe9e6df,
      signBg: '#2c2520',
      signAccent: '#f5b041',
      awningColor: 0x2c5e3b,
      floors: 3,
    },
    {
      x: -12,
      z: 56.2,
      rotY: 0.2 + Math.PI,
      title: 'CAFE MINH · GÓC LÊ HIẾN MAI',
      subtitle: 'CÀ PHÊ MUỐI · CÀ PHÊ SỮA ĐÁ · SÂN VƯỜN',
      wallColor: 0xf4eee0,
      signBg: '#5c3419',
      signAccent: '#fde68a',
      awningColor: 0x8f4e22,
      floors: 3,
    },
    {
      x: 0,
      z: 53.8,
      rotY: 0.2 + Math.PI,
      title: 'NHÃ UYÊN QUÁN · TRÀ SỮA & ĂN VẶT',
      subtitle: '86 HOÀNG MINH THẢO · TRÀ SỮA · BÁNH TRÁNG',
      wallColor: 0xf2ecec,
      signBg: '#9d244d',
      signAccent: '#ffffff',
      awningColor: 0xa63458,
      floors: 2,
    },
    {
      x: 12,
      z: 51.4,
      rotY: 0.2 + Math.PI,
      title: 'BÚN ĐẬU BÚN CHẢ HÀ NỘI & CƠM SV',
      subtitle: 'CƠM TẤM · MÌ QUẢNG · BÚN BÒ ĐÀ NẴNG',
      wallColor: 0xf3ece8,
      signBg: '#9b2c2c',
      signAccent: '#fef08a',
      awningColor: 0xb03a3a,
      floors: 2,
    },
    {
      x: 24,
      z: 49.0,
      rotY: 0.2 + Math.PI,
      title: 'HÙNG NGÀ MOTOR & TẠP HÓA TÂN CƯỜNG THÀNH',
      subtitle: 'SỬA XE SINH VIÊN · GIÁO TRÌNH · TẠP HÓA',
      wallColor: 0xeaeef2,
      signBg: '#162436',
      signAccent: '#5cc8ff',
      awningColor: 0x3b4d61,
      floors: 4,
    },
  ];

  const shopGlassMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x212f3d,
      emissive: new THREE.Color(0xffdfa8),
      emissiveIntensity: 0.38,
      roughness: 0.16,
      metalness: 0.55,
    }),
  );

  // Dùng chung vật liệu cho dãy hàng quán Hoàng Minh Thảo để mergeStaticMeshes gộp triệt để draw calls!
  const sharedShopBodyMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xf0ede6,
      map: tubeHouseTex.colorMap,
      bumpMap: lowQuality ? null : tubeHouseTex.bumpMap,
      bumpScale: 0.05,
      emissive: new THREE.Color(0xffdfa0),
      emissiveMap: tubeHouseTex.emissiveMap,
      emissiveIntensity: 0.04,
      roughness: 0.86,
    }),
  );
  const shopBodyMats: THREE.MeshStandardMaterial[] = [sharedShopBodyMat];
  const shopWaterTankGeo = trackGeo(createWaterTankGeo());
  const shopTankMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xdbe2ea, roughness: 0.28, metalness: 0.78 }),
  );
  const sharedShopRoofMats = [0x9e5042, 0x45706a, 0x5c6a78].map((col) =>
    trackMat(
      new THREE.MeshStandardMaterial({
        color: col,
        map: corrugatedRoofTex.colorMap,
        bumpMap: lowQuality ? null : corrugatedRoofTex.bumpMap,
        bumpScale: 0.08,
        roughness: 0.62,
        metalness: 0.22,
      }),
    ),
  );
  const sharedAwningMats = [0x2a5496, 0x8b3a2e, 0x2f6b56].map((col) =>
    trackMat(
      new THREE.MeshStandardMaterial({
        color: col,
        map: corrugatedRoofTex.colorMap,
        roughness: 0.78,
      }),
    ),
  );

  streetShops.forEach((sp, spIdx) => {
    const sg = new THREE.Group();
    sg.position.set(sp.x, CAMPUS_GROUND_Y, sp.z);
    sg.rotation.y = sp.rotY;

    const sw = 8.4;
    const sd = 10.0;
    const sh = sp.floors * 3.1;

    // Dùng chung sharedShopBodyMat để tất cả thân quán gộp thành 1 draw call duy nhất
    const body = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(sw, sh, sd)), sharedShopBodyMat);
    body.position.y = sh * 0.5;
    body.receiveShadow = true;
    sg.add(body);

    // Mặt tiền cửa kính quán tầng 1 có khung nhôm đen
    const sfFrame = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(sw - 0.9, 2.7, 0.28)), blackAluminumMat);
    sfFrame.position.set(0, 1.38, sd * 0.5 + 0.04);
    const sfGlass = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(sw - 1.25, 2.45, 0.3)), shopGlassMat);
    sfGlass.position.set(0, 1.35, sd * 0.5 + 0.06);
    sg.add(sfFrame, sfGlass);

    for (let fl = 2; fl <= sp.floors; fl++) {
      // Ban công tấm mỏng + lan can sắt đen gọn đẹp
      const balcSlab = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(sw - 0.6, 0.18, 0.95)),
        plasterWhiteMat,
      );
      balcSlab.position.set(0, (fl - 1) * 3.1 + 0.09, sd * 0.5 + 0.42);
      const balcRail = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(sw - 0.7, 0.72, 0.08)),
        blackAluminumMat,
      );
      balcRail.position.set(0, (fl - 1) * 3.1 + 0.52, sd * 0.5 + 0.86);
      sg.add(balcSlab, balcRail);
    }

    const sTex = trackTex(
      createSignboardTexture(sp.title, sp.subtitle, sp.signBg, '#ffffff', sp.signAccent, maxAniso),
    );
    const signBox = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(sw - 0.3, 1.32, 0.24)),
      trackMat(
        new THREE.MeshStandardMaterial({
          map: sTex,
          emissive: new THREE.Color(0xffffff),
          emissiveMap: sTex,
          emissiveIntensity: 0.32,
          roughness: 0.4,
        }),
      ),
    );
    signBox.position.set(0, 3.3, sd * 0.5 + 0.16);
    sg.add(signBox);

    // Mái hiên bạt di động gợn sóng nghiêng tự nhiên (dùng chung sharedAwningMats)
    const awning = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(sw + 0.15, 0.1, 2.45)),
      sharedAwningMats[spIdx % sharedAwningMats.length],
    );
    awning.position.set(0, 2.7, sd * 0.5 + 1.2);
    awning.rotation.x = 0.24;
    sg.add(awning);

    // Bàn ghế gỗ nhỏ vỉa hè gọn gàng (bỏ ô dù hình nón thô)
    [-2.2, 0, 2.2].forEach((ux) => {
      const table = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.75, 0.56, 0.6)),
        brownStairwellMat,
      );
      table.position.set(ux, 0.28, sd * 0.5 + 1.75);
      sg.add(table);
    });

    // Sân thượng + mái tôn sóng nghiêng / tum thang + bồn nước inox (chuẩn nhà phố Hoàng Minh Thảo)
    const parapet = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(sw + 0.2, 0.56, sd + 0.2)),
      plasterWhiteMat,
    );
    parapet.position.y = sh + 0.28;
    const pitchedSheet = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(sw - 0.15, 0.2, sd - 0.6)),
      sharedShopRoofMats[spIdx % sharedShopRoofMats.length],
    );
    pitchedSheet.position.set(0, sh + 0.96, -0.1);
    pitchedSheet.rotation.x = 0.09;

    const stairTum = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(sw * 0.36, 1.4, sd * 0.32)),
      plasterWhiteMat,
    );
    stairTum.position.set(sw * 0.18, sh + 0.85, -sd * 0.16);
    const waterTank = new THREE.Mesh(shopWaterTankGeo, shopTankMat);
    waterTank.position.set(-sw * 0.24, sh + 0.52, -sd * 0.22);

    sg.add(parapet, pitchedSheet, stairTum, waterTank);

    group.add(sg);
  });

  // =========================================================================
  // 9. KHU DÂN CƯ HÒA KHÁNH NAM & KDC TÂN CƯỜNG THÀNH XUNG QUANH
  // =========================================================================
  interface HouseSpec {
    x: number;
    z: number;
    w: number;
    h: number;
    d: number;
    wallTint: number;
    roofTint: number;
  }
  const houseSpecs: HouseSpec[] = [];
  let hSeed = 6211;
  const hRand = () => {
    hSeed = (hSeed * 48271) % 2147483647;
    return (hSeed - 1) / 2147483646;
  };
  const wallPalette = [0xf2f0ea, 0xeaece9, 0xf3eadc, 0xe5eae8, 0xede8df, 0xe8e6e2];
  // Bảng màu mái tôn thực tế Hòa Khánh Nam (đỏ gạch ngả nắng, xanh dương trầm, xám tôn, xanh rêu)
  const roofPalette = [0x9e5042, 0x45706a, 0x5c6a78, 0xa85e47, 0x4b6e87, 0x869099];

  // Urban-Block-Aligned Tube Houses ("Nhà ống" KDC Tân Cường Thành & Hòa Khánh Nam — zero street overlap!)
  const urbanHouseZones: Array<[number, number, number, number]> = [
    [84, 103, -120, -101],
    [120, 139, -120, -101],
    [156, 175, -120, -101],
    [84, 103, -87, -59],
    [120, 139, -87, -59],
    [156, 175, -87, -59],
    [84, 103, -45, -21],
    [120, 139, -45, -21],
    [156, 175, -45, -21],
    [84, 103, -7, 4],
    [120, 139, -7, 4],
    [156, 175, -7, 4],
    [30, 65, -4, 3],
    [49, 65, 42, 66],
    [84, 103, 38, 66],
    [120, 139, 38, 66],
    [156, 175, 38, 66],
    [-42, 33, 81, 101],
    [49, 65, 81, 101],
    [84, 103, 81, 101],
    [120, 139, 81, 101],
    [156, 175, 81, 101],
    [-42, 33, 114, 138],
    [49, 65, 114, 138],
    [84, 103, 114, 138],
    [120, 139, 114, 138],
    // South-West Hòa Khánh Nam Tube Houses across Lê Hiến Mai (fixes image_bdabf676!)
    [-98, -70, 74, 98],
    [-139, -116, 84, 98],
    [-98, -70, 114, 138],
    [-139, -116, 114, 138],
    [-5, 65, -120, -101],
    [44, 65, -148, -133],
    [84, 175, -148, -133],
  ];
  urbanHouseZones.forEach(([xMin, xMax, zMin, zMax]) => {
    for (let gx = xMin; gx <= xMax; gx += 7.4) {
      for (let gz = zMin; gz <= zMax; gz += 9.8) {
        if (hRand() > 0.78) continue;
        houseSpecs.push({
          x: gx + (hRand() - 0.5) * 1.1,
          z: gz + (hRand() - 0.5) * 1.1,
          w: 4.8 + hRand() * 1.6,
          h: 4.6 + hRand() * 6.8,
          d: 6.2 + hRand() * 2.4,
          wallTint: wallPalette[Math.floor(hRand() * wallPalette.length)],
          roofTint: roofPalette[Math.floor(hRand() * roofPalette.length)],
        });
      }
    }
  });

  // Nâng cấp nhà dân Hòa Khánh Nam từ hộp trắng Lego -> Nhà ống Đà Nẵng có cửa sổ, ban công, mái tôn sóng & bồn nước inox!
  const houseWallMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: tubeHouseTex.colorMap,
      bumpMap: lowQuality ? null : tubeHouseTex.bumpMap,
      bumpScale: 0.05,
      roughness: 0.86,
      emissive: new THREE.Color(0xffd78c),
      emissiveMap: tubeHouseTex.emissiveMap,
      emissiveIntensity: 0.06,
    }),
  );
  const houseRoofMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: corrugatedRoofTex.colorMap,
      bumpMap: lowQuality ? null : corrugatedRoofTex.bumpMap,
      bumpScale: 0.07,
      roughness: 0.68,
      metalness: 0.18,
    }),
  );
  const houseFlatParapetMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xe6e4de, roughness: 0.86 }),
  );
  const inoxTankMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xd8e0e8, roughness: 0.26, metalness: 0.78 }),
  );

  // Tách 2 kiểu kiến trúc thật: ~55% nhà ống mái tôn nghiêng/dốc, ~45% nhà phố mái bằng có tum + bồn nước inox
  const pitchedHouses = houseSpecs.filter((_h, idx) => idx % 9 < 5);
  const flatHouses = houseSpecs.filter((_h, idx) => idx % 9 >= 5);

  const houseRoofGeo = trackGeo(createGableRoofGeo(1.06, 0.26, 1.04));
  const waterTankGeo = trackGeo(createWaterTankGeo());

  const housesInst = new THREE.InstancedMesh(unitBoxGeo, houseWallMat, houseSpecs.length);
  const roofsInst = new THREE.InstancedMesh(houseRoofGeo, houseRoofMat, Math.max(1, pitchedHouses.length));
  const flatCapsInst = new THREE.InstancedMesh(unitBoxGeo, houseFlatParapetMat, Math.max(1, flatHouses.length));
  const flatTumsInst = new THREE.InstancedMesh(unitBoxGeo, houseFlatParapetMat, Math.max(1, flatHouses.length));
  const tanksInst = new THREE.InstancedMesh(waterTankGeo, inoxTankMat, Math.max(1, flatHouses.length));

  houseSpecs.forEach((hs, i) => {
    const yaw = (i % 4) * (Math.PI * 0.5);
    dummy.position.set(hs.x, CAMPUS_GROUND_Y + hs.h * 0.5, hs.z);
    dummy.scale.set(hs.w, hs.h, hs.d);
    dummy.rotation.set(0, yaw, 0);
    dummy.updateMatrix();
    housesInst.setMatrixAt(i, dummy.matrix);
    tmpColor.setHex(hs.wallTint);
    housesInst.setColorAt(i, tmpColor);
  });

  pitchedHouses.forEach((hs, idx) => {
    dummy.position.set(hs.x, CAMPUS_GROUND_Y + hs.h, hs.z);
    dummy.scale.set(hs.w, 2.9, hs.d);
    dummy.rotation.set(0, (idx % 2) * (Math.PI * 0.5), 0);
    dummy.updateMatrix();
    roofsInst.setMatrixAt(idx, dummy.matrix);
    tmpColor.setHex(hs.roofTint);
    roofsInst.setColorAt(idx, tmpColor);
  });

  flatHouses.forEach((hs, idx) => {
    // Mái bằng có viền lan can sân thượng + tum thang + bồn nước inox trụ bạc
    dummy.position.set(hs.x, CAMPUS_GROUND_Y + hs.h + 0.25, hs.z);
    dummy.scale.set(hs.w + 0.16, 0.5, hs.d + 0.16);
    dummy.rotation.set(0, 0, 0);
    dummy.updateMatrix();
    flatCapsInst.setMatrixAt(idx, dummy.matrix);

    dummy.position.set(hs.x - hs.w * 0.16, CAMPUS_GROUND_Y + hs.h + 1.15, hs.z - hs.d * 0.14);
    dummy.scale.set(hs.w * 0.44, 1.45, hs.d * 0.36);
    dummy.updateMatrix();
    flatTumsInst.setMatrixAt(idx, dummy.matrix);

    dummy.position.set(hs.x + hs.w * 0.22, CAMPUS_GROUND_Y + hs.h + 0.52, hs.z + hs.d * 0.18);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    tanksInst.setMatrixAt(idx, dummy.matrix);
  });

  [housesInst, roofsInst, flatCapsInst, flatTumsInst, tanksInst].forEach((inst) => {
    inst.instanceMatrix.needsUpdate = true;
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
    inst.computeBoundingSphere();
  });
  group.add(housesInst, roofsInst, flatCapsInst, flatTumsInst, tanksInst);

  // =========================================================================
  // 10. XE MÁY SINH VIÊN ĐẬU ĐÔNG ĐÚC QUANH SÂN TRƯỜNG & TRƯỚC NHÀ G, F, E
  // =========================================================================
  const bikeCoords: Array<[number, number, number]> = [];
  for (let i = 0; i < 42; i++) {
    bikeCoords.push([-36.8, -36 + i * 1.38, Math.PI * 0.44]);
    bikeCoords.push([-43.2, -32 + i * 1.42, -Math.PI * 0.44]);
  }
  for (let i = 0; i < 22; i++) {
    bikeCoords.push([-35.5 + (i % 11) * 1.15, 19.6 + Math.floor(i / 11) * 2.2, 0.15]);
  }
  // Dense parked motorbikes wrapping South & East apron of Nhà G + courtyard alley between Nhà F & Nhà G (Photo 1, 2, 5!)
  for (let i = 0; i < 24; i++) {
    bikeCoords.push([-10.2 + i * 0.98, 15.2, 0]);
    bikeCoords.push([-10.2 + i * 0.98, 17.8, 0]);
    bikeCoords.push([12.2, -11.5 + i * 1.05, Math.PI * 0.5]);
  }
  for (let i = 0; i < 20; i++) {
    bikeCoords.push([-10.5 + i * 1.05, -18.2, 0]);
    bikeCoords.push([-10.5 + i * 1.05, -15.8, Math.PI]);
  }
  // Parked student motorbikes in the wide open plaza between Nhà C/A and Nhà D/F (image_f990b422 & image_d5a88cbd!)
  for (let i = 0; i < 16; i++) {
    bikeCoords.push([-32.5 + i * 0.96, -54.2, 0.08]);
    bikeCoords.push([-32.5 + i * 0.96, -51.8, 0.08]);
  }
  for (let i = 0; i < 14; i++) {
    bikeCoords.push([-8.5 + i * 0.98, -46.2, 0.04]);
  }
  streetShops.forEach((sp) => {
    for (let k = -2; k <= 2; k++) {
      bikeCoords.push([sp.x + k * 1.2, sp.z - 6.6, sp.rotY + 0.35]);
    }
  });

  // Xe máy sinh viên tạo dáng thật (thân vát + yếm trước + tay lái + 2 bánh + yên đen)
  const bikeBodyGeo = trackGeo(createRealisticMotorbikeGeo());
  const bikeSeatGeo = trackGeo(new THREE.BoxGeometry(0.32, 0.16, 0.62));
  const bikeBodyMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.34, metalness: 0.25 }),
  );
  const bikesBodyInst = new THREE.InstancedMesh(bikeBodyGeo, bikeBodyMat, bikeCoords.length);
  const bikesTopInst = new THREE.InstancedMesh(bikeSeatGeo, blackAluminumMat, bikeCoords.length);
  const bikeColors = [0x1f2937, 0xb91c1c, 0xe5e7eb, 0x1d4ed8, 0x334155, 0x0f766e, 0x991b1b];

  bikeCoords.forEach(([bx, bz, rot], i) => {
    dummy.position.set(bx, CAMPUS_GROUND_Y + 0.42, bz);
    dummy.rotation.set(0, rot, 0);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    bikesBodyInst.setMatrixAt(i, dummy.matrix);
    tmpColor.setHex(bikeColors[i % bikeColors.length]);
    bikesBodyInst.setColorAt(i, tmpColor);

    dummy.position.set(bx, CAMPUS_GROUND_Y + 0.68, bz);
    dummy.updateMatrix();
    bikesTopInst.setMatrixAt(i, dummy.matrix);
  });
  bikesBodyInst.instanceMatrix.needsUpdate = true;
  if (bikesBodyInst.instanceColor) bikesBodyInst.instanceColor.needsUpdate = true;
  bikesTopInst.instanceMatrix.needsUpdate = true;
  bikesBodyInst.computeBoundingSphere();
  bikesTopInst.computeBoundingSphere();
  group.add(bikesBodyInst, bikesTopInst);

  // =========================================================================
  // 11. CÂY XANH & ĐÈN CHIẾU SÁNG TOÀN KHUÔN VIÊN
  // =========================================================================
  const treeCoords: Array<[number, number, number]> = [];
  for (let i = 0; i < 6; i++) {
    treeCoords.push([25.4, -5 + i * 4.4, 1.45 + (i % 3) * 0.2]);
  }
  for (let i = 0; i < 4; i++) {
    treeCoords.push([29.5 + i * 5.2, 17.5, 1.38 + (i % 2) * 0.2]);
  }
  for (let i = 0; i < 10; i++) {
    treeCoords.push([24 + i * 4.2, -5.5, 1.38 + (i % 2) * 0.2]);
    treeCoords.push([24 + i * 4.2, -74.5, 1.35]);
  }
  for (let i = 0; i < 18; i++) {
    const tx = -52 + i * 7.8;
    const tz = 32.5 - tx * 0.2;
    // Trim sidewalk trees directly in front of Main Gate 1 & DTU Monument Sign Wall so signage is 100% clear!
    if ((tx <= -28 || tx >= 4) && Math.abs(tx - 42) > 6.5 && Math.abs(tx - 76) > 6.5) {
      treeCoords.push([tx, tz, 1.42 + (i % 3) * 0.2]);
    }
    if (Math.abs(tx - 42) > 6.5 && Math.abs(tx - 76) > 6.5 && tx > -48) {
      treeCoords.push([tx, tz + 16.5, 1.25 + (i % 2) * 0.18]);
    }
  }
  for (let i = 0; i < 12; i++) {
    const wz = -56 + i * 8.2;
    // Trim East Lê Hiến Mai sidewalk trees in front of Gate 2 driveway & Monument Sign Wall!
    if (wz < -67 || wz > -40) {
      treeCoords.push([-48.8, wz, 1.15 + (i % 2) * 0.16]);
    }
    // West sidewalk trees along Lê Hiến Mai (skipping Defense asphalt apron entrance z = -18..10!)
    if (wz < -18 || (wz > 10 && wz < 38)) {
      treeCoords.push([-63.6, wz, 1.18 + (i % 2) * 0.15]);
    }
  }
  // Young ornamental courtyard trees neatly aligned along South & North promenade planter borders!
  treeCoords.push(
    [-11.4, 6.2, 0.58],
    [-11.4, 0.4, 0.58],
    [-22.4, 6.2, 0.58],
    [-22.4, 0.4, 0.58],
    [-22.4, -14.8, 0.58],
    [-11.2, -20.5, 0.58],
    // North Promenade trees flanking the Blue Water Basin between Nhà D & Nhà F (image_43cbbac9!)
    [-22.0, -24.8, 0.62],
    [-22.0, -29.2, 0.62],
    [-22.0, -33.6, 0.62],
    [-22.0, -38.0, 0.62],
    [-12.8, -24.8, 0.62],
    [-12.8, -29.2, 0.62],
    [-12.8, -33.6, 0.62],
    [-12.8, -38.0, 0.62],
    [-5.5, 20.5, 1.05],
    [-35.2, -11.5, 1.32],
    // Neat shade tree row along South apron of Block A wide parking & walkway plaza (image_f990b422!)
    [-18.0, -50.2, 0.72],
    [-12.5, -50.5, 0.72],
    [-5.0, -50.5, 0.72],
    [2.5, -50.5, 0.72],
    [9.5, -50.5, 0.72],
  );
  // Hàng cây ven đường vòng sân vận động & rặng keo lá tràm xanh rậm quanh Khu TT GDQP & AN nối chân núi Phước Tường
  for (let i = 0; i < 8; i++) {
    treeCoords.push([-136 + i * 7.2, -33.5 - i * 0.5, 0.88 + (i % 2) * 0.14]);
  }
  treeCoords.push(
    [-159, -56, 1.15],
    [-156, -72, 1.2],
    [-146, -86, 1.18],
    [-126, -96, 1.15],
    // Cây bóng mát ven sân điều lệnh & rìa KTX Khu A/B TT GDQP & AN
    [-118, -96.2, 1.05],
    [-104, -96.2, 1.08],
    [-90, -96.2, 1.05],
    [-67.5, -101, 1.0],
    [-67.5, -121, 1.05],
    [-149.5, -102, 1.15],
    [-149.5, -122, 1.18],
    [-149.5, -140, 1.25],
    // Hàng cây xanh trồng thẳng hàng dọc 3 đoạn dải phân cách cỏ giữa Đại lộ Đôi (z = -3.5, khớp Google Maps!)
    [-74.0, -3.5, 0.72],
    [-81.0, -3.5, 0.74],
    [-88.0, -3.5, 0.72],
    [-111.0, -3.5, 0.74],
    [-118.0, -3.5, 0.74],
    [-125.0, -3.5, 0.72],
    [-148.0, -3.5, 0.74],
    [-155.0, -3.5, 0.74],
    [-162.0, -3.5, 0.72],
    // Cây bóng mát quanh Cụm Trung tâm GDQP & ĐH TDTT CS2 và vòng xuyến oval (tránh mặt đường & sân tập lái)
    [-70.5, 18.0, 1.18],
    [-70.5, 34.0, 1.24],
    [-84.0, 44.5, 1.28],
    [-106.0, 46.0, 1.3],
    [-128.0, 44.5, 1.26],
    [-148.0, 42.0, 1.25],
    [-168.0, 28.0, 1.15], // Cây trung tâm bùng binh oval!
  );
  // Dải rừng cây keo lá tràm rậm rạp phía sau sân vận động & dãy KTX nối lên chân núi (đúng ảnh flycam thật!)
  for (let i = 0; i < 18; i++) {
    treeCoords.push([-168 - (i % 3) * 7.5, -158 + i * 9.0, 1.45 + (i % 3) * 0.28]);
  }
  for (let i = 0; i < 16; i++) {
    treeCoords.push([-166 + i * 11.2, -154 - (i % 2) * 6.5, 1.52 + (i % 3) * 0.25]);
  }
  // Trees lining Hoàng Minh Thảo West of Lê Hiến Mai & SW neighborhood edges
  for (let i = 0; i < 8; i++) {
    const wx = -74 - i * 11.5;
    const wz = 41 - (wx + 10) * 0.2 + 12.2;
    treeCoords.push([wx, wz, 1.28 + (i % 2) * 0.18]);
  }

  // Cây xanh hữu cơ (detail=1 kết hợp smooth normals + vân lá PBR: giữ 100% độ đẹp nhưng nhẹ gấp 4 lần tam giác!)
  const trunkGeo = trackGeo(new THREE.CylinderGeometry(0.15, 0.26, 2.8, 6));
  const trunkMat = trackMat(new THREE.MeshStandardMaterial({ color: 0x523e2e, roughness: 0.94 }));
  const lobeGeo = trackGeo(createOrganicCanopyGeo(1.48, 1));
  const bangGeo = trackGeo(createBangDaiLoanCanopyGeo());
  const foliageMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: foliageTex.colorMap,
      bumpMap: lowQuality ? null : foliageTex.bumpMap,
      bumpScale: 0.14,
      roughness: 0.9,
      metalness: 0.0,
    }),
  );
  const treeAoGeo = trackGeo(new THREE.PlaneGeometry(1, 1));
  treeAoGeo.rotateX(-Math.PI / 2);
  const treeAoMat = trackMat(
    new THREE.MeshBasicMaterial({
      map: contactShadowTex,
      transparent: true,
      depthWrite: false,
      opacity: 0.65,
    }),
  );

  // Cây non dáng tầng trong quảng trường (sc < 0.78) dùng dáng Bàng Đài Loan chuẩn Ảnh 8–11; cây lớn dùng tán hữu cơ đa chùm!
  const bangTrees = treeCoords.filter(([, , sc]) => sc < 0.78);
  const shadeTrees = treeCoords.filter(([, , sc]) => sc >= 0.78);

  const trunksInst = new THREE.InstancedMesh(trunkGeo, trunkMat, treeCoords.length);
  const canopiesInst = new THREE.InstancedMesh(lobeGeo, foliageMat, Math.max(1, shadeTrees.length * 3));
  const bangCanopiesInst = new THREE.InstancedMesh(bangGeo, foliageMat, Math.max(1, bangTrees.length));
  const treeAosInst = new THREE.InstancedMesh(treeAoGeo, treeAoMat, treeCoords.length);

  // Bảng màu xanh lá tự nhiên nhiệt đới (xanh lục đậm, xanh ô liu, xanh nắng dịu — không xanh neon nhựa)
  const foliagePalette = [0x3b6330, 0x4a7538, 0x2e5227, 0x587f3e, 0x3f6b34];
  const bangPalette = [0x5d8a3a, 0x6b9642, 0x527d35];

  treeCoords.forEach(([tx, tz, sc], i) => {
    dummy.position.set(tx, CAMPUS_GROUND_Y + 1.4 * sc, tz);
    dummy.scale.setScalar(sc);
    dummy.rotation.set(0, i * 1.1, 0);
    dummy.updateMatrix();
    trunksInst.setMatrixAt(i, dummy.matrix);

    // Đĩa bóng tiếp đất mềm dưới mỗi gốc cây
    dummy.position.set(tx, CAMPUS_GROUND_Y + 0.06, tz);
    dummy.scale.set(sc * 4.2, 1, sc * 4.2);
    dummy.rotation.set(0, 0, 0);
    dummy.updateMatrix();
    treeAosInst.setMatrixAt(i, dummy.matrix);
  });

  shadeTrees.forEach(([tx, tz, sc], i) => {
    const lobes: Array<[number, number, number, number, number]> = [
      [0, 3.65, 0, 1.2, 0.88],
      [-0.88, 3.08, 0.58, 0.9, 0.74],
      [0.86, 3.18, -0.54, 0.94, 0.78],
    ];
    lobes.forEach(([ox, oy, oz, rxz, ry], k) => {
      const idx = i * 3 + k;
      dummy.position.set(tx + ox * sc, CAMPUS_GROUND_Y + oy * sc, tz + oz * sc);
      dummy.scale.set(sc * rxz, sc * ry, sc * rxz);
      dummy.rotation.set((k - 1) * 0.14, (i + k) * 1.2, (k % 2) * 0.12);
      dummy.updateMatrix();
      canopiesInst.setMatrixAt(idx, dummy.matrix);
      tmpColor.setHex(foliagePalette[(i + k) % foliagePalette.length]);
      canopiesInst.setColorAt(idx, tmpColor);
    });
  });

  bangTrees.forEach(([tx, tz, sc], i) => {
    dummy.position.set(tx, CAMPUS_GROUND_Y + 0.25 * sc, tz);
    dummy.scale.set(sc * 1.35, sc * 1.25, sc * 1.35);
    dummy.rotation.set(0, i * 0.85, 0);
    dummy.updateMatrix();
    bangCanopiesInst.setMatrixAt(i, dummy.matrix);
    tmpColor.setHex(bangPalette[i % bangPalette.length]);
    bangCanopiesInst.setColorAt(i, tmpColor);
  });

  [trunksInst, canopiesInst, bangCanopiesInst, treeAosInst].forEach((inst) => {
    inst.instanceMatrix.needsUpdate = true;
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
    inst.computeBoundingSphere();
  });
  group.add(trunksInst, canopiesInst, bangCanopiesInst, treeAosInst);

  const lampCoords: Array<[number, number]> = [
    [-17.6, 4.5],
    [-10.2, 18.5],
    [-25.5, 22.5],
    [13.5, 16.5],
    [16.5, -14.0],
    [-38.5, 16.0],
    [-38.5, -18.0],
    [-48.6, 22.0],
    [-48.6, -24.0],
    [-12.0, 36.0],
    [14.0, 31.0],
    [22.8, -53.2],
    [62.2, -53.2],
    [22.8, -33.6],
    [62.2, -33.6],
  ];
  const lampOrbMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xfff6dc,
      emissive: new THREE.Color(0xffb84d),
      emissiveIntensity: 0.25,
      roughness: 0.28,
    }),
  );
  const lampPolesInst = new THREE.InstancedMesh(
    trackGeo(new THREE.CylinderGeometry(0.09, 0.12, 5.2, 6)),
    blackAluminumMat,
    lampCoords.length,
  );
  const lampOrbsInst = new THREE.InstancedMesh(
    trackGeo(new THREE.SphereGeometry(0.42, 8, 8)),
    lampOrbMat,
    lampCoords.length,
  );
  lampCoords.forEach(([lx, lz], i) => {
    dummy.position.set(lx, CAMPUS_GROUND_Y + 2.6, lz);
    dummy.scale.set(1, 1, 1);
    dummy.rotation.set(0, 0, 0);
    dummy.updateMatrix();
    lampPolesInst.setMatrixAt(i, dummy.matrix);

    dummy.position.set(lx, CAMPUS_GROUND_Y + 5.3, lz);
    dummy.updateMatrix();
    lampOrbsInst.setMatrixAt(i, dummy.matrix);
  });
  lampPolesInst.instanceMatrix.needsUpdate = true;
  lampOrbsInst.instanceMatrix.needsUpdate = true;
  group.add(lampPolesInst, lampOrbsInst);

  // =========================================================================
  // 12. DÃY NÚI HẢI VÂN / BÀ NÀ ĐÀ NẴNG + GIAO THÔNG ĐƯỜNG HOÀNG MINH THẢO
  // =========================================================================
  const mountains = createDaNangMountainRange();
  geometries.push(mountains.geo);
  materials.push(mountains.mat);
  group.add(mountains.mesh);

  const vehicles: StreetVehicle[] = [];
  const vehColors = [0xf8fafc, 0x1e293b, 0xdc2626, 0x2563eb, 0x64748b, 0xf59e0b];
  for (let i = 0; i < 14; i++) {
    const dir: 1 | -1 = i % 2 === 0 ? 1 : -1;
    vehicles.push({
      road: 'hoang_minh_thao',
      t: -120 + i * 18,
      dir,
      speed: 7.5 + (i % 3) * 2.2,
      laneOffset: dir * 2.8,
      isBike: i % 2 === 1,
      color: new THREE.Color(vehColors[i % vehColors.length]),
    });
  }
  for (let i = 0; i < 12; i++) {
    const dir: 1 | -1 = i % 2 === 0 ? 1 : -1;
    vehicles.push({
      road: 'le_hien_mai',
      t: -115 + i * 20,
      dir,
      speed: 8.5 + (i % 4) * 1.8,
      laneOffset: dir * 2.7,
      isBike: i % 2 === 1,
      color: new THREE.Color(vehColors[(i + 2) % vehColors.length]),
    });
  }
  // Ô tô & xe lưu thông đường Hoàng Minh Thảo / Lê Hiến Mai dùng hình khối tạo dáng thật (thân + cabin + bánh)
  const carGeo = trackGeo(createRealisticCarGeo());
  const carMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.3, metalness: 0.42 }),
  );
  const carsInst = new THREE.InstancedMesh(carGeo, carMat, vehicles.length);
  carsInst.frustumCulled = false;
  vehicles.forEach((v, i) => carsInst.setColorAt(i, v.color));
  if (carsInst.instanceColor) carsInst.instanceColor.needsUpdate = true;
  group.add(carsInst);

  // Tối ưu hiệu năng 3D không giảm chất lượng:
  // 1) sunKey shadow camera chỉ phủ vùng [-16..16] quanh tầng thượng Văn phòng Agent, nên tắt castShadow cho toàn bộ
  //    công trình ngoài trời (không mất bóng thấy được) -> cắt 100% shadow pass vô ích và giúp mergeStaticMeshes gộp
  //    triệt để mọi khối cùng vật liệu thành 1 draw call duy nhất!
  // 2) Khóa matrixAutoUpdate = false trên toàn bộ đối tượng tĩnh (trừ carsInst đang chạy) để giảm chi phí CPU mỗi frame.
  group.traverse((obj) => {
    const m = obj as THREE.Mesh;
    if (m.isMesh) {
      m.castShadow = false;
      m.receiveShadow = false;
    }
  });
  geometries.push(...mergeStaticMeshes(group, [roofRevealGroup]));
  group.updateMatrixWorld(true);
  group.traverse((obj) => {
    if (obj !== group && obj !== carsInst && obj !== roofRevealGroup && obj.parent !== roofRevealGroup) {
      obj.matrixAutoUpdate = false;
    }
  });

  group.visible = false;

  let lastRoofAlpha = -1;

  return {
    group,
    setNightGlow: (intensity: number) => {
      heroGlassMat.emissiveIntensity = 0.06 + intensity * 1.32;
      roofGlassMat.emissiveIntensity = 0.06 + intensity * 1.32;
      blockFLouverMat.emissiveIntensity = 0.08 + intensity * 0.96;
      academicWinMat.emissiveIntensity = 0.06 + intensity * 0.88;
      warmLobbyGlowMat.emissiveIntensity = 0.22 + intensity * 1.45;
      glassPavilionMat.emissiveIntensity = 0.24 + intensity * 1.18;
      shopGlassMat.emissiveIntensity = 0.25 + intensity * 1.15;
      houseWallMat.emissiveIntensity = 0.02 + intensity * 0.26;
      shopBodyMats.forEach((m) => {
        m.emissiveIntensity = 0.02 + intensity * 0.26;
      });
      lampOrbMat.emissiveIntensity = 0.22 + intensity * 2.6;
      heroColonnadeLight.intensity = 0.35 + intensity * 2.6;
    },
    update: (dt, _elapsed, exteriorReveal, skipVehicles = false) => {
      const showCampus = exteriorReveal > 0.015;
      group.visible = showCampus;
      if (!showCampus) return;

      const roofAlpha = THREE.MathUtils.clamp((exteriorReveal - 0.34) / 0.56, 0, 1);
      roofRevealGroup.visible = roofAlpha > 0.015;
      if (roofRevealGroup.visible && Math.abs(roofAlpha - lastRoofAlpha) > 0.002) {
        lastRoofAlpha = roofAlpha;
        const isSolid = roofAlpha >= 0.96;
        // Giữ cố định transparent=true (chỉ đổi opacity & depthWrite) để TUYỆT ĐỐI KHÔNG re-compile shader lúc lăn chuột!
        const setFade = (mat: THREE.MeshStandardMaterial, targetAlpha: number) => {
          mat.depthWrite = isSolid;
          mat.opacity = isSolid ? 1 : roofAlpha * targetAlpha;
        };
        setFade(roofGlassMat, 0.94);
        setFade(roofMullionMat, 0.98);
        setFade(roofConcreteMat, 0.98);
        setFade(roofWhiteMat, 0.98);
        setFade(roofDarkRimMat, 0.98);
      }

      if (skipVehicles) return;

      const angle = -0.2;
      const cosA = Math.cos(angle);
      const sinA = Math.sin(angle);
      for (let i = 0; i < vehicles.length; i++) {
        const v = vehicles[i];
        v.t += v.dir * v.speed * dt;
        if (v.t > 135) v.t = -135;
        if (v.t < -135) v.t = 135;

        const len = v.isBike ? 1.55 : 3.4;
        const hgt = v.isBike ? 0.9 : 1.05;
        const wid = v.isBike ? 0.65 : 1.65;

        if (v.road === 'hoang_minh_thao') {
          const vx = -10 + v.t * cosA - v.laneOffset * sinA;
          const vz = 41 + v.t * sinA + v.laneOffset * cosA;
          dummy.position.set(vx, CAMPUS_GROUND_Y + hgt * 0.5 + 0.05, vz);
          dummy.rotation.set(0, -angle + (v.dir > 0 ? 0 : Math.PI), 0);
          dummy.scale.set(len, hgt, wid);
        } else {
          const vx = -56.2 + v.laneOffset;
          const vz = -22 + v.t;
          dummy.position.set(vx, CAMPUS_GROUND_Y + hgt * 0.5 + 0.05, vz);
          dummy.rotation.set(0, v.dir > 0 ? Math.PI * 0.5 : -Math.PI * 0.5, 0);
          dummy.scale.set(len, hgt, wid);
        }
        dummy.updateMatrix();
        carsInst.setMatrixAt(i, dummy.matrix);
      }
      carsInst.instanceMatrix.needsUpdate = true;
    },
    dispose: () => {
      textures.forEach((t) => t.dispose());
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
    },
  };
}
