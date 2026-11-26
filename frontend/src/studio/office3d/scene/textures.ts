import * as THREE from 'three';
import type { LiveMetrics } from '../liveDirector';
import type { AgentId } from '../types';

export type WallStepState = 'done' | 'now' | 'todo' | 'fail';

export interface MissionWallOpts {
  tierLabel: string;
  requestTitle: string;
  stepText: string;
  progressPct: number;
  awakeCount: number;
  sleepingCount: number;
  /** Danh sách ID các Agent đang thức để đánh sáng trực tiếp trên Bản Đồ Kích Hoạt 11 Agent */
  awakeIds?: AgentId[];
  /** Các bước của lượt (kịch bản hoặc lượt thật) */
  steps?: { label: string; state: WallStepState }[];
  /** Số đo thực tế từ backend (lượt Trực tiếp / Xem lại); null/undefined khi chưa chạy */
  metrics?: LiveMetrics | null;
}

export interface StudioTextureSet {
  oakPlankFloorMap: THREE.CanvasTexture;
  woodBumpMap: THREE.CanvasTexture;
  oakDeskMap: THREE.CanvasTexture;
  darkSlateStoneMap: THREE.CanvasTexture;
  travertineStoneMap: THREE.CanvasTexture;
  hubMapTex: THREE.CanvasTexture;
  wovenRugBlueMap: THREE.CanvasTexture;
  wovenRugSandMap: THREE.CanvasTexture;
  fabricBumpMap: THREE.CanvasTexture;
  plasterBumpMap: THREE.CanvasTexture;
  planningBoardMap: THREE.CanvasTexture;
  draftingPaperMap: THREE.CanvasTexture;
  easelChartMap: THREE.CanvasTexture;
  missionWallMap: THREE.CanvasTexture;
  updateMissionWall: (opts: MissionWallOpts) => void;
  screenCodeMap: THREE.CanvasTexture;
  screenBusinessMap: THREE.CanvasTexture;
  screenMarketingMap: THREE.CanvasTexture;
  screenHrMap: THREE.CanvasTexture;
  screenFinanceMap: THREE.CanvasTexture;
  screenEducationMap: THREE.CanvasTexture;
  screenUltrawideMap: THREE.CanvasTexture;
  screenSleepMap: THREE.CanvasTexture;
  zzzSpriteMap: THREE.CanvasTexture;
  contactShadowMap: THREE.CanvasTexture;
  dispose: () => void;
}

function makeCanvas(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return [c, c.getContext('2d')!];
}

function createWovenRugTexture(
  baseHex: string,
  weaveHex: string,
  borderHex: string,
): THREE.CanvasTexture {
  const [c, ctx] = makeCanvas(512, 512);
  ctx.fillStyle = baseHex;
  ctx.fillRect(0, 0, 512, 512);
  ctx.fillStyle = weaveHex;
  for (let y = 0; y < 512; y += 4) {
    ctx.globalAlpha = y % 8 === 0 ? 0.28 : 0.12;
    ctx.fillRect(0, y, 512, 2);
  }
  for (let x = 0; x < 512; x += 6) {
    ctx.globalAlpha = x % 12 === 0 ? 0.18 : 0.08;
    ctx.fillRect(x, 0, 2, 512);
  }
  ctx.globalAlpha = 1;
  ctx.strokeStyle = borderHex;
  ctx.lineWidth = 18;
  ctx.strokeRect(18, 18, 476, 476);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function createSpecialistScreenTexture(
  accent: string,
  title: string,
  kind: 'code' | 'business' | 'marketing' | 'hr' | 'finance' | 'education' | 'ultrawide',
): THREE.CanvasTexture {
  const [c, ctx] = makeCanvas(512, 320);

  const bgGrad = ctx.createLinearGradient(0, 0, 512, 320);
  bgGrad.addColorStop(0, '#0a1426');
  bgGrad.addColorStop(1, '#132643');
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, 512, 320);

  ctx.fillStyle = 'rgba(255,255,255,0.08)';
  ctx.fillRect(0, 0, 512, 40);
  ctx.fillStyle = accent;
  ctx.beginPath();
  ctx.arc(22, 20, 7, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#e2f1ff';
  ctx.font = 'bold 18px sans-serif';
  ctx.fillText(title, 40, 26);

  if (kind === 'code') {
    const widths = [180, 240, 140, 290, 210, 160, 260, 190];
    widths.forEach((w, i) => {
      ctx.fillStyle = i % 3 === 0 ? '#38bdf8' : i % 2 === 0 ? '#a78bfa' : '#34d399';
      ctx.fillRect(28 + (i % 3) * 18, 62 + i * 28, w, 12);
    });
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 3;
    ctx.strokeRect(365, 68, 118, 72);
    ctx.strokeRect(365, 174, 118, 72);
    ctx.beginPath();
    ctx.moveTo(424, 140);
    ctx.lineTo(424, 174);
    ctx.stroke();
  } else if (kind === 'marketing') {
    const widths = [340, 260, 190, 125];
    const colors = ['#fb923c', '#f97316', '#ea580c', '#c2410c'];
    widths.forEach((w, i) => {
      ctx.fillStyle = colors[i];
      ctx.fillRect(256 - w / 2, 62 + i * 58, w, 42);
    });
  } else if (kind === 'finance') {
    const bars = [110, 145, 130, 185, 205, 238];
    bars.forEach((h, i) => {
      ctx.fillStyle = i === 2 ? '#f43f5e' : '#10b981';
      ctx.fillRect(42 + i * 74, 285 - h, 42, h);
    });
    ctx.strokeStyle = '#fde047';
    ctx.lineWidth = 4;
    ctx.beginPath();
    bars.forEach((h, i) => {
      const px = 63 + i * 74;
      const py = 272 - h;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
  } else if (kind === 'hr') {
    for (let i = 0; i < 3; i++) {
      const y = 58 + i * 80;
      ctx.fillStyle = 'rgba(255,255,255,0.09)';
      ctx.fillRect(26, y, 460, 66);
      ctx.fillStyle = accent;
      ctx.beginPath();
      ctx.arc(60, y + 33, 18, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(94, y + 18, 180, 12);
      ctx.fillStyle = '#94a3b8';
      ctx.fillRect(94, y + 38, 130, 10);
      ctx.fillStyle = '#34d399';
      ctx.fillRect(340, y + 24, 120 - i * 16, 16);
    }
  } else if (kind === 'ultrawide') {
    for (let col = 0; col < 3; col++) {
      const bx = 20 + col * 160;
      ctx.fillStyle = 'rgba(30, 41, 59, 0.9)';
      ctx.fillRect(bx, 56, 148, 240);
      ctx.fillStyle = col === 1 ? '#a855f7' : '#38bdf8';
      ctx.fillRect(bx + 12, 72, 92, 12);
      for (let r = 0; r < 6; r++) {
        ctx.fillStyle = 'rgba(226, 232, 240, 0.55)';
        ctx.fillRect(bx + 12, 102 + r * 28, 118 - (r % 2) * 24, 10);
      }
    }
  } else {
    for (let cIdx = 0; cIdx < 3; cIdx++) {
      ctx.fillStyle = 'rgba(255,255,255,0.08)';
      ctx.fillRect(24 + cIdx * 158, 58, 144, 234);
      ctx.fillStyle = accent;
      ctx.fillRect(36 + cIdx * 158, 74, 90, 12);
      for (let r = 0; r < 4; r++) {
        ctx.fillStyle = 'rgba(226,241,255,0.65)';
        ctx.fillRect(36 + cIdx * 158, 108 + r * 42, 118, 26);
      }
    }
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const TOPOLOGY_ORDER: AgentId[] = [
  'orchestrator',
  'rag',
  'analyst',
  'reviewer',
  'integrator',
  'software',
  'business',
  'marketing',
  'hr',
  'finance',
  'education',
];

const TOPOLOGY_COLORS = [
  '#f59e0b',
  '#10b981',
  '#3b82f6',
  '#f43f5e',
  '#a855f7',
  '#0ea5e9',
  '#14b8a6',
  '#fb923c',
  '#f472b6',
  '#22c55e',
  '#818cf8',
];

export function createStudioTextures(maxAnisotropy: number): StudioTextureSet {
  const allTextures: THREE.CanvasTexture[] = [];
  const reg = (t: THREE.CanvasTexture): THREE.CanvasTexture => {
    allTextures.push(t);
    return t;
  };

  // 1. Sàn Gỗ Sồi Mật Ong Sâu (Rich Honey Oak — tương phản sâu làm bật Trục Đá Sáng & 11 Robot trắng sứ!)
  const [floorC, fctx] = makeCanvas(1024, 1024);
  const [bumpC, bctx] = makeCanvas(1024, 1024);
  fctx.fillStyle = '#a87c51';
  fctx.fillRect(0, 0, 1024, 1024);
  bctx.fillStyle = '#848484';
  bctx.fillRect(0, 0, 1024, 1024);

  const plankH = 64;
  const plankPalette = ['#ac8055', '#9f7348', '#b5895e', '#966a41', '#a67a4f', '#af8358'];
  for (let row = 0; row < 1024 / plankH; row++) {
    const y = row * plankH;
    const offset = (row * 211) % 340;
    for (let col = -1; col < 4; col++) {
      const x = col * 340 + offset - 340;
      fctx.fillStyle = plankPalette[(row * 7 + col + 20) % plankPalette.length];
      fctx.fillRect(x, y, 338, plankH - 2);

      for (let g = 0; g < 8; g++) {
        const gy = y + 6 + g * 7.0;
        fctx.strokeStyle =
          g % 2 === 0 ? 'rgba(54, 30, 12, 0.16)' : 'rgba(255, 224, 184, 0.09)';
        fctx.lineWidth = g % 3 === 0 ? 1.8 : 1.1;
        fctx.beginPath();
        fctx.moveTo(x + 2, gy);
        fctx.bezierCurveTo(
          x + 112,
          gy + Math.sin(row + g) * 2.4,
          x + 228,
          gy - Math.cos(col + g) * 2.4,
          x + 336,
          gy,
        );
        fctx.stroke();

        bctx.strokeStyle = g % 2 === 0 ? '#707070' : '#929292';
        bctx.lineWidth = 1.2;
        bctx.beginPath();
        bctx.moveTo(x + 2, gy);
        bctx.lineTo(x + 336, gy);
        bctx.stroke();
      }

      fctx.strokeStyle = 'rgba(46, 25, 10, 0.40)';
      fctx.lineWidth = 2.0;
      fctx.strokeRect(x + 0.5, y + 0.5, 339, plankH - 1);

      bctx.strokeStyle = '#2c2c2c';
      bctx.lineWidth = 2.4;
      bctx.strokeRect(x + 0.5, y + 0.5, 339, plankH - 1);
    }
  }
  const oakPlankFloorMap = reg(new THREE.CanvasTexture(floorC));
  oakPlankFloorMap.colorSpace = THREE.SRGBColorSpace;
  oakPlankFloorMap.wrapS = THREE.RepeatWrapping;
  oakPlankFloorMap.wrapT = THREE.RepeatWrapping;
  oakPlankFloorMap.repeat.set(3.8, 3.0);
  oakPlankFloorMap.anisotropy = maxAnisotropy;

  const woodBumpMap = reg(new THREE.CanvasTexture(bumpC));
  woodBumpMap.wrapS = THREE.RepeatWrapping;
  woodBumpMap.wrapT = THREE.RepeatWrapping;
  woodBumpMap.repeat.set(3.8, 3.0);

  // 2. Mặt bàn gỗ óc chó nâu trầm sang trọng
  const [deskC, dctx] = makeCanvas(512, 512);
  dctx.fillStyle = '#563720';
  dctx.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 84; i++) {
    dctx.strokeStyle =
      i % 2 === 0 ? 'rgba(24, 12, 4, 0.30)' : 'rgba(166, 118, 78, 0.14)';
    dctx.lineWidth = 1.8 + (i % 3);
    const y = (i / 84) * 512;
    dctx.beginPath();
    dctx.moveTo(0, y);
    dctx.bezierCurveTo(170, y + Math.sin(i * 0.7) * 5, 340, y - Math.cos(i * 0.6) * 5, 512, y);
    dctx.stroke();
  }
  const oakDeskMap = reg(new THREE.CanvasTexture(deskC));
  oakDeskMap.colorSpace = THREE.SRGBColorSpace;
  oakDeskMap.anisotropy = maxAnisotropy;

  // 3. Đá Xám Than Kiến Trúc cho Bục Chỉ Huy (+0.28m)
  const [dsC, dsctx] = makeCanvas(512, 512);
  dsctx.fillStyle = '#363f4d';
  dsctx.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 80; i++) {
    const y = (i / 80) * 512;
    dsctx.strokeStyle = i % 2 === 0 ? 'rgba(18, 24, 34, 0.22)' : 'rgba(148, 163, 184, 0.08)';
    dsctx.lineWidth = 2 + (i % 3);
    dsctx.beginPath();
    dsctx.moveTo(0, y);
    dsctx.bezierCurveTo(170, y + Math.sin(i * 0.4) * 6, 340, y - Math.cos(i * 0.5) * 6, 512, y);
    dsctx.stroke();
  }
  dsctx.strokeStyle = 'rgba(15, 23, 42, 0.46)';
  dsctx.lineWidth = 2.5;
  for (let i = 0; i <= 512; i += 128) {
    dsctx.beginPath();
    dsctx.moveTo(i, 0);
    dsctx.lineTo(i, 512);
    dsctx.stroke();
    dsctx.beginPath();
    dsctx.moveTo(0, i);
    dsctx.lineTo(512, i);
    dsctx.stroke();
  }
  const darkSlateStoneMap = reg(new THREE.CanvasTexture(dsC));
  darkSlateStoneMap.colorSpace = THREE.SRGBColorSpace;
  darkSlateStoneMap.wrapS = THREE.RepeatWrapping;
  darkSlateStoneMap.wrapT = THREE.RepeatWrapping;
  darkSlateStoneMap.repeat.set(4.5, 1.3);
  darkSlateStoneMap.anisotropy = maxAnisotropy;

  // 4. Đá Sáng Travertine cho Trục Lối Đi Chính & Sảnh Hội Ý Trung Tâm
  const [trC, trctx] = makeCanvas(512, 512);
  trctx.fillStyle = '#e3dcd0';
  trctx.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 95; i++) {
    const y = (i / 95) * 512;
    trctx.strokeStyle = i % 2 === 0 ? 'rgba(130, 118, 102, 0.14)' : 'rgba(255, 250, 242, 0.24)';
    trctx.lineWidth = 2 + (i % 3);
    trctx.beginPath();
    trctx.moveTo(0, y);
    trctx.bezierCurveTo(170, y + Math.sin(i * 0.5) * 5, 340, y - Math.cos(i * 0.4) * 5, 512, y);
    trctx.stroke();
  }
  trctx.strokeStyle = 'rgba(110, 98, 82, 0.22)';
  trctx.lineWidth = 2;
  for (let i = 0; i <= 512; i += 128) {
    trctx.beginPath();
    trctx.moveTo(i, 0);
    trctx.lineTo(i, 512);
    trctx.stroke();
    trctx.beginPath();
    trctx.moveTo(0, i);
    trctx.lineTo(512, i);
    trctx.stroke();
  }
  const travertineStoneMap = reg(new THREE.CanvasTexture(trC));
  travertineStoneMap.colorSpace = THREE.SRGBColorSpace;
  travertineStoneMap.wrapS = THREE.RepeatWrapping;
  travertineStoneMap.wrapT = THREE.RepeatWrapping;
  travertineStoneMap.repeat.set(2, 2);
  travertineStoneMap.anisotropy = maxAnisotropy;

  // 5. Bản Đồ Mạng 11 Agent C27 lõi kính phát sáng trên Bàn Hội Ý Trung Tâm
  const [hmC, hmctx] = makeCanvas(512, 512);
  const hrg = hmctx.createRadialGradient(256, 256, 12, 256, 256, 256);
  hrg.addColorStop(0, '#182b49');
  hrg.addColorStop(0.75, '#0e1b30');
  hrg.addColorStop(1, '#08101e');
  hmctx.fillStyle = hrg;
  hmctx.fillRect(0, 0, 512, 512);
  hmctx.strokeStyle = 'rgba(251, 191, 36, 0.42)';
  hmctx.lineWidth = 2.5;
  [76, 140, 204].forEach((r) => {
    hmctx.beginPath();
    hmctx.arc(256, 256, r, 0, Math.PI * 2);
    hmctx.stroke();
  });
  for (let i = 0; i < 11; i++) {
    const a = (i / 11) * Math.PI * 2 - Math.PI / 2;
    const r = i < 5 ? 140 : 204;
    const x = 256 + Math.cos(a) * r;
    const y = 256 + Math.sin(a) * r;
    hmctx.strokeStyle = 'rgba(148, 163, 184, 0.30)';
    hmctx.lineWidth = 2.2;
    hmctx.beginPath();
    hmctx.moveTo(256, 256);
    hmctx.lineTo(x, y);
    hmctx.stroke();
    hmctx.fillStyle = TOPOLOGY_COLORS[i];
    hmctx.beginPath();
    hmctx.arc(x, y, 11, 0, Math.PI * 2);
    hmctx.fill();
  }
  hmctx.fillStyle = '#fbbf24';
  hmctx.beginPath();
  hmctx.arc(256, 256, 28, 0, Math.PI * 2);
  hmctx.fill();
  hmctx.fillStyle = '#0f172a';
  hmctx.font = '800 18px "Segoe UI", sans-serif';
  hmctx.textAlign = 'center';
  hmctx.fillText('C27', 256, 263);
  const hubMapTex = reg(new THREE.CanvasTexture(hmC));
  hubMapTex.colorSpace = THREE.SRGBColorSpace;
  hubMapTex.anisotropy = maxAnisotropy;

  // 6. Thảm nỉ xám đá trầm có độ tương phản đẹp cho khu Data Analyst & Reviewer
  const wovenRugBlueMap = reg(createWovenRugTexture('#3a4554', '#2d3745', '#64748b'));
  const wovenRugSandMap = reg(createWovenRugTexture('#3d4654', '#313a47', '#94a3b8'));

  const [fbC, fbctx] = makeCanvas(256, 256);
  fbctx.fillStyle = '#808080';
  fbctx.fillRect(0, 0, 256, 256);
  for (let y = 0; y < 256; y += 4) {
    fbctx.fillStyle = y % 8 === 0 ? '#9c9c9c' : '#646464';
    fbctx.fillRect(0, y, 256, 2);
  }
  const fabricBumpMap = reg(new THREE.CanvasTexture(fbC));
  fabricBumpMap.wrapS = THREE.RepeatWrapping;
  fabricBumpMap.wrapT = THREE.RepeatWrapping;
  fabricBumpMap.repeat.set(6, 6);

  const [plC, plctx] = makeCanvas(256, 256);
  plctx.fillStyle = '#808080';
  plctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 3600; i++) {
    const shade = 110 + ((i * 53) % 38);
    plctx.fillStyle = `rgb(${shade},${shade},${shade})`;
    plctx.fillRect((i * 37) % 256, (i * 89) % 256, 2, 2);
  }
  const plasterBumpMap = reg(new THREE.CanvasTexture(plC));
  plasterBumpMap.wrapS = THREE.RepeatWrapping;
  plasterBumpMap.wrapT = THREE.RepeatWrapping;
  plasterBumpMap.repeat.set(5, 3);

  // 7. Bảng lập kế hoạch kính nhỏ cạnh bục
  const [wbC, wctx] = makeCanvas(1024, 512);
  wctx.fillStyle = '#0f172a';
  wctx.fillRect(0, 0, 1024, 512);
  wctx.fillStyle = '#e2e8f0';
  wctx.font = '800 32px sans-serif';
  wctx.fillText('LẬP KẾ HOẠCH & PHÂN RÃ · C1SE.27', 44, 68);
  const flowColors = ['#f59e0b', '#10b981', '#38bdf8', '#f43f5e', '#a855f7'];
  const flowNames = ['Định tuyến', 'RAG riêng', 'Chuyên gia', 'Cổng QC', 'Tổng hợp'];
  flowColors.forEach((col, i) => {
    const bx = 46 + i * 190;
    wctx.fillStyle = 'rgba(30, 41, 59, 0.9)';
    wctx.beginPath();
    wctx.roundRect(bx, 110, 160, 82, 14);
    wctx.fill();
    wctx.strokeStyle = col;
    wctx.lineWidth = 3.5;
    wctx.stroke();
    wctx.fillStyle = '#f8fafc';
    wctx.font = '700 22px sans-serif';
    wctx.fillText(flowNames[i], bx + 20, 158);
  });
  const planningBoardMap = reg(new THREE.CanvasTexture(wbC));
  planningBoardMap.colorSpace = THREE.SRGBColorSpace;
  planningBoardMap.anisotropy = maxAnisotropy;

  // 8. Bản vẽ Data Analyst & Giá biểu đồ 3 chân
  const [dpC, dpctx] = makeCanvas(512, 512);
  dpctx.fillStyle = '#faf6ec';
  dpctx.fillRect(0, 0, 512, 512);
  dpctx.strokeStyle = '#bfdbfe';
  dpctx.lineWidth = 1.5;
  for (let i = 24; i < 490; i += 24) {
    dpctx.beginPath();
    dpctx.moveTo(i, 24);
    dpctx.lineTo(i, 488);
    dpctx.stroke();
    dpctx.beginPath();
    dpctx.moveTo(24, i);
    dpctx.lineTo(488, i);
    dpctx.stroke();
  }
  dpctx.strokeStyle = '#1d4ed8';
  dpctx.lineWidth = 5;
  dpctx.beginPath();
  dpctx.moveTo(48, 220);
  dpctx.lineTo(110, 170);
  dpctx.lineTo(175, 185);
  dpctx.lineTo(240, 110);
  dpctx.lineTo(310, 82);
  dpctx.stroke();
  const draftingPaperMap = reg(new THREE.CanvasTexture(dpC));
  draftingPaperMap.colorSpace = THREE.SRGBColorSpace;

  const [eaC, eactx] = makeCanvas(512, 640);
  eactx.fillStyle = '#fbfaf7';
  eactx.fillRect(0, 0, 512, 640);
  eactx.fillStyle = '#1e3a8a';
  eactx.fillRect(0, 0, 512, 76);
  eactx.fillStyle = '#ffffff';
  eactx.font = 'bold 30px sans-serif';
  eactx.fillText('BIỂU ĐỒ SỐ LIỆU · KPI', 36, 49);
  const cols = ['#93c5fd', '#60a5fa', '#3b82f6', '#2563eb', '#1d4ed8'];
  const vals = [120, 175, 155, 235, 290];
  vals.forEach((v, i) => {
    eactx.fillStyle = cols[i];
    eactx.fillRect(54 + i * 84, 460 - v, 54, v);
  });
  eactx.strokeStyle = '#ef4444';
  eactx.lineWidth = 7;
  eactx.beginPath();
  vals.forEach((v, i) => {
    const x = 81 + i * 84;
    const y = 440 - v;
    if (i === 0) eactx.moveTo(x, y);
    else eactx.lineTo(x, y);
  });
  eactx.stroke();
  eactx.fillStyle = '#1e293b';
  eactx.font = 'bold 24px monospace';
  eactx.fillText('KPI · PHÂN TÍCH ĐA CHIỀU', 54, 548);
  const easelChartMap = reg(new THREE.CanvasTexture(eaC));
  easelChartMap.colorSpace = THREE.SRGBColorSpace;

  // =========================================================================
  // 9. MÀN HÌNH LỚN TRUNG TÂM 2K (2048x768) — ĐỌC RÕ NGAY TỪ GÓC TOÀN CẢNH!
  // Hiển thị: Câu hỏi hiện tại · 4 Thẻ Giai Đoạn Lớn · Thanh Tiến Độ + Số Liệu Thật · Bản Đồ Kích Hoạt 11 Agent
  // =========================================================================
  const WALL_W = 2048;
  const WALL_H = 768;
  const [mwC, mwctx] = makeCanvas(WALL_W, WALL_H);
  const missionWallMap = reg(new THREE.CanvasTexture(mwC));
  missionWallMap.colorSpace = THREE.SRGBColorSpace;
  missionWallMap.anisotropy = maxAnisotropy;

  const fit = (text: string, maxW: number) => {
    if (mwctx.measureText(text).width <= maxW) return text;
    let t = text;
    while (t.length > 1 && mwctx.measureText(`${t}…`).width > maxW) t = t.slice(0, -1);
    return `${t}…`;
  };

  /** Gom danh sách bước thực tế về 4 cột lớn dễ nhìn từ xa trên Màn Hình Trung Tâm 2K */
  const resolveFourPillars = (opts: MissionWallOpts) => {
    const steps = opts.steps ?? [];
    const pct = Math.max(0, Math.min(100, opts.progressPct));
    const m = opts.metrics;

    const findState = (pred: (label: string) => boolean, fallbackThreshold: number): WallStepState => {
      const matched = steps.filter((s) => pred(s.label.toLowerCase()));
      if (matched.length) {
        if (matched.some((s) => s.state === 'fail')) return 'fail';
        if (matched.some((s) => s.state === 'now')) return 'now';
        if (matched.every((s) => s.state === 'done')) return 'done';
        return 'todo';
      }
      if (pct >= 100) return 'done';
      if (pct >= fallbackThreshold + 20) return 'done';
      if (pct >= fallbackThreshold) return 'now';
      return 'todo';
    };

    const s1 = findState((l) => l.includes('nhận') || l.includes('chọn') || l.includes('kế hoạch') || l.includes('hiểu') || l.includes('nguồn'), 5);
    const s2 = findState((l) => l.includes('tài liệu') || l.includes('rag'), 25);
    const s3 = findState(
      (l) =>
        l.includes('phòng') ||
        l.includes('chuyên gia') ||
        l.includes('phân tích') ||
        l.includes('thực thi') ||
        l.includes('phần mềm') ||
        l.includes('kinh doanh') ||
        l.includes('marketing') ||
        l.includes('nhân sự') ||
        l.includes('tài chính') ||
        l.includes('giáo dục') ||
        l.includes('data analyst'),
      50,
    );
    const s4 = findState(
      (l) => l.includes('đối chiếu') || l.includes('duyệt') || l.includes('tổng hợp') || l.includes('viết') || l.includes('trả lời'),
      78,
    );

    return [
      {
        num: '01',
        name: 'PHÂN RÃ',
        sub: m?.tasks != null ? `${m.tasks} việc${m.removed ? ` (−${m.removed} trùng)` : ''}` : 'Đọc & chia việc',
        col: '#f59e0b',
        state: s1,
      },
      {
        num: '02',
        name: 'RAG RIÊNG',
        sub: m?.chunks != null ? `${m.chunks} đoạn ngữ cảnh` : 'Truy xuất Qdrant',
        col: '#10b981',
        state: s2,
      },
      {
        num: '03',
        name: 'CHUYÊN GIA',
        sub:
          m?.parallel && m.parallel > 1
            ? `Song song ${m.parallel} nhánh`
            : opts.awakeCount > 0
              ? `${opts.awakeCount} Agent hoạt động`
              : 'Đang chờ giao việc',
        col: '#38bdf8',
        state: s3,
      },
      {
        num: '04',
        name: 'QC & TỔNG HỢP',
        sub:
          m?.checked != null
            ? `Soát ${m.checked} ý${m.revisions ? ` · sửa ${m.revisions}` : ''}`
            : 'Kiểm định & trả lời',
        col: '#a855f7',
        state: s4,
      },
    ];
  };

  const updateMissionWall = (opts: MissionWallOpts) => {
    const bg = mwctx.createLinearGradient(0, 0, WALL_W, WALL_H);
    bg.addColorStop(0, '#071121');
    bg.addColorStop(0.5, '#0c1c36');
    bg.addColorStop(1, '#081428');
    mwctx.fillStyle = bg;
    mwctx.fillRect(0, 0, WALL_W, WALL_H);

    // Lưới tọa độ kiến trúc rất mảnh
    mwctx.strokeStyle = 'rgba(56, 189, 248, 0.055)';
    mwctx.lineWidth = 2;
    for (let gx = 0; gx < WALL_W; gx += 64) {
      mwctx.beginPath();
      mwctx.moveTo(gx, 0);
      mwctx.lineTo(gx, WALL_H);
      mwctx.stroke();
    }
    for (let gy = 0; gy < WALL_H; gy += 64) {
      mwctx.beginPath();
      mwctx.moveTo(0, gy);
      mwctx.lineTo(WALL_W, gy);
      mwctx.stroke();
    }

    // THANH TIÊU ĐỀ LỚN
    mwctx.fillStyle = 'rgba(11, 18, 34, 0.94)';
    mwctx.fillRect(0, 0, WALL_W, 114);
    mwctx.fillStyle = '#f59e0b';
    mwctx.fillRect(0, 110, WALL_W, 5);

    mwctx.fillStyle = '#f59e0b';
    mwctx.beginPath();
    mwctx.roundRect(42, 24, 18, 64, 8);
    mwctx.fill();

    mwctx.textBaseline = 'alphabetic';
    mwctx.textAlign = 'left';
    mwctx.fillStyle = '#ffffff';
    mwctx.font = '800 44px "Segoe UI", sans-serif';
    mwctx.fillText('ĐIỀU PHỐI ĐA TÁC TỬ · C1SE.27', 80, 72);

    const routeLabel =
      opts.metrics?.route === 'simple'
        ? `CHẾ ĐỘ: ĐƠN GIẢN · ${opts.awakeCount}/11 AGENT`
        : opts.metrics?.route === 'complex'
          ? `CHẾ ĐỘ: PHỨC TẠP · ${opts.awakeCount}/11 AGENT`
          : `${opts.tierLabel.toUpperCase()} · ${opts.awakeCount}/11 AGENT`;
    const isSimple = opts.metrics?.route === 'simple';

    mwctx.fillStyle = isSimple ? 'rgba(16, 185, 129, 0.22)' : 'rgba(245, 158, 11, 0.20)';
    mwctx.beginPath();
    mwctx.roundRect(1408, 22, 598, 68, 34);
    mwctx.fill();
    mwctx.strokeStyle = isSimple ? '#34d399' : '#fbbf24';
    mwctx.lineWidth = 3.5;
    mwctx.stroke();
    mwctx.fillStyle = isSimple ? '#a7f3d0' : '#fde68a';
    mwctx.font = '800 30px "Segoe UI", sans-serif';
    mwctx.textAlign = 'center';
    mwctx.fillText(fit(routeLabel, 560), 1707, 67);
    mwctx.textAlign = 'left';

    // THANH YÊU CẦU HIỆN TẠI + DÒNG DIỄN BIẾN ĐANG XẢY RA
    mwctx.fillStyle = 'rgba(22, 34, 54, 0.85)';
    mwctx.beginPath();
    mwctx.roundRect(42, 142, 1340, 116, 18);
    mwctx.fill();
    mwctx.strokeStyle = 'rgba(56, 189, 248, 0.45)';
    mwctx.lineWidth = 3;
    mwctx.stroke();

    mwctx.fillStyle = '#38bdf8';
    mwctx.font = '800 24px "Segoe UI", sans-serif';
    mwctx.fillText('YÊU CẦU:', 70, 188);
    mwctx.fillStyle = '#ffffff';
    mwctx.font = '700 34px "Segoe UI", sans-serif';
    mwctx.fillText(fit(opts.requestTitle, 1140), 205, 190);

    mwctx.fillStyle = '#fcd34d';
    mwctx.font = '700 26px "Segoe UI", sans-serif';
    mwctx.fillText(fit(`▸ ${opts.stepText}`, 1280), 70, 238);

    // 4 THẺ GIAI ĐOẠN LỚN ĐỌC RÕ TỪ TOÀN CẢNH
    const pillars = resolveFourPillars(opts);
    pillars.forEach((st, i) => {
      const sx = 42 + i * 342;
      const sy = 286;
      const sw = 316;
      const sh = 326;
      const isNow = st.state === 'now';
      const isDone = st.state === 'done';
      const isFail = st.state === 'fail';

      mwctx.fillStyle = isNow
        ? 'rgba(14, 116, 144, 0.34)'
        : isFail
          ? 'rgba(159, 18, 57, 0.30)'
          : 'rgba(15, 23, 42, 0.88)';
      mwctx.beginPath();
      mwctx.roundRect(sx, sy, sw, sh, 22);
      mwctx.fill();
      mwctx.strokeStyle = isFail ? '#fb7185' : st.state === 'todo' ? 'rgba(148, 163, 184, 0.30)' : st.col;
      mwctx.lineWidth = isNow ? 6 : 3.5;
      mwctx.stroke();

      mwctx.fillStyle = isFail ? '#fb7185' : st.col;
      mwctx.beginPath();
      mwctx.roundRect(sx + 20, sy + 20, sw - 40, 14, 7);
      mwctx.fill();

      mwctx.fillStyle = isFail ? '#fb7185' : st.col;
      mwctx.font = '900 66px "Segoe UI", sans-serif';
      mwctx.fillText(st.num, sx + 26, sy + 112);

      mwctx.fillStyle = '#ffffff';
      mwctx.font = '800 32px "Segoe UI", sans-serif';
      mwctx.fillText(st.name, sx + 26, sy + 170);

      mwctx.fillStyle = '#cbd5e1';
      mwctx.font = '600 24px "Segoe UI", sans-serif';
      mwctx.fillText(fit(st.sub, sw - 48), sx + 26, sy + 212);

      mwctx.fillStyle = isDone
        ? 'rgba(16, 185, 129, 0.24)'
        : isNow
          ? 'rgba(56, 189, 248, 0.28)'
          : isFail
            ? 'rgba(244, 63, 94, 0.28)'
            : 'rgba(148, 163, 184, 0.14)';
      mwctx.beginPath();
      mwctx.roundRect(sx + 22, sy + 248, sw - 44, 54, 12);
      mwctx.fill();

      mwctx.fillStyle = isDone ? '#6ee7b7' : isNow ? '#7dd3fc' : isFail ? '#fda4af' : '#94a3b8';
      mwctx.font = '800 24px "Segoe UI", sans-serif';
      mwctx.textAlign = 'center';
      mwctx.fillText(
        isDone ? 'HOÀN TẤT ✓' : isNow ? 'ĐANG CHẠY ●' : isFail ? 'CẦN SỬA !' : 'CHỜ LỆNH',
        sx + sw / 2,
        sy + 284,
      );
      mwctx.textAlign = 'left';

      if (i < 3) {
        mwctx.fillStyle = isDone ? '#fbbf24' : '#475569';
        mwctx.font = '900 40px "Segoe UI", sans-serif';
        mwctx.fillText('▸', sx + sw + 2, sy + 176);
      }
    });

    // THANH TIẾN ĐỘ TỔNG DƯỚI ĐÁY
    mwctx.fillStyle = 'rgba(22, 34, 54, 0.92)';
    mwctx.beginPath();
    mwctx.roundRect(42, 642, 1340, 88, 16);
    mwctx.fill();

    const pct = Math.max(0, Math.min(100, opts.progressPct));
    mwctx.fillStyle = '#94a3b8';
    mwctx.font = '700 25px "Segoe UI", sans-serif';
    mwctx.fillText('TIẾN ĐỘ ĐIỀU PHỐI:', 72, 695);

    mwctx.fillStyle = '#1e293b';
    mwctx.beginPath();
    mwctx.roundRect(350, 668, 860, 34, 17);
    mwctx.fill();
    if (pct > 0) {
      const progGrad = mwctx.createLinearGradient(350, 0, 1210, 0);
      progGrad.addColorStop(0, '#f59e0b');
      progGrad.addColorStop(0.55, '#10b981');
      progGrad.addColorStop(1, '#38bdf8');
      mwctx.fillStyle = progGrad;
      mwctx.beginPath();
      mwctx.roundRect(350, 668, Math.max(34, (860 * pct) / 100), 34, 17);
      mwctx.fill();
    }
    mwctx.fillStyle = '#ffffff';
    mwctx.font = '800 32px "Segoe UI", sans-serif';
    mwctx.fillText(`${Math.round(pct)}%`, 1246, 698);

    // KHỐI PHẢI: BẢN ĐỒ KÍCH HOẠT 11 AGENT TRỰC QUAN
    const rx = 1418;
    const ry = 142;
    const rw = 588;
    const rh = 588;
    mwctx.fillStyle = 'rgba(15, 23, 42, 0.90)';
    mwctx.beginPath();
    mwctx.roundRect(rx, ry, rw, rh, 22);
    mwctx.fill();
    mwctx.strokeStyle = 'rgba(148, 163, 184, 0.28)';
    mwctx.lineWidth = 3;
    mwctx.stroke();

    mwctx.fillStyle = '#fde68a';
    mwctx.font = '800 28px "Segoe UI", sans-serif';
    mwctx.fillText(`BẢN ĐỒ KÍCH HOẠT (${opts.awakeCount}/11)`, rx + 32, ry + 54);

    const cx = rx + rw / 2;
    const cy = ry + 328;
    mwctx.strokeStyle = 'rgba(56, 189, 248, 0.25)';
    mwctx.lineWidth = 3;
    [110, 202].forEach((rr) => {
      mwctx.beginPath();
      mwctx.arc(cx, cy, rr, 0, Math.PI * 2);
      mwctx.stroke();
    });

    const awakeLookup = new Set<AgentId>(opts.awakeIds ?? []);
    for (let i = 0; i < TOPOLOGY_ORDER.length; i++) {
      const ang = (i / 11) * Math.PI * 2 - Math.PI / 2;
      const rr = i < 5 ? 114 : 204;
      const nx = cx + Math.cos(ang) * rr;
      const ny = cy + Math.sin(ang) * rr;
      const isAct = awakeLookup.size > 0 ? awakeLookup.has(TOPOLOGY_ORDER[i]) : i < opts.awakeCount;

      mwctx.strokeStyle = isAct ? TOPOLOGY_COLORS[i] : 'rgba(100, 116, 139, 0.24)';
      mwctx.lineWidth = isAct ? 5 : 2;
      mwctx.beginPath();
      mwctx.moveTo(cx, cy);
      mwctx.lineTo(nx, ny);
      mwctx.stroke();

      mwctx.fillStyle = isAct ? TOPOLOGY_COLORS[i] : '#334155';
      mwctx.beginPath();
      mwctx.arc(nx, ny, isAct ? 26 : 18, 0, Math.PI * 2);
      mwctx.fill();
      if (isAct) {
        mwctx.strokeStyle = '#ffffff';
        mwctx.lineWidth = 3;
        mwctx.stroke();
      }
      mwctx.fillStyle = isAct ? '#0f172a' : '#94a3b8';
      mwctx.font = isAct ? '900 22px "Segoe UI", sans-serif' : '700 18px "Segoe UI", sans-serif';
      mwctx.textAlign = 'center';
      mwctx.fillText(String(i + 1).padStart(2, '0'), nx, ny + 8);
    }

    mwctx.fillStyle = '#fbbf24';
    mwctx.beginPath();
    mwctx.arc(cx, cy, 38, 0, Math.PI * 2);
    mwctx.fill();
    mwctx.fillStyle = '#0f172a';
    mwctx.font = '900 26px "Segoe UI", sans-serif';
    mwctx.fillText('HUB', cx, cy + 9);
    mwctx.textAlign = 'left';

    missionWallMap.needsUpdate = true;
  };

  updateMissionWall({
    tierLabel: 'Sẵn sàng',
    requestTitle: 'Đang chờ tiếp nhận yêu cầu mới từ người dùng...',
    stepText: 'Đặt câu hỏi trong ô trò chuyện hoặc chọn kịch bản minh họa bên dưới',
    progressPct: 0,
    awakeCount: 0,
    sleepingCount: 11,
    awakeIds: [],
  });

  // 10. Màn hình từng phòng ban
  const screenCodeMap = reg(createSpecialistScreenTexture('#38bdf8', 'SOFTWARE · IDE & API', 'code'));
  const screenBusinessMap = reg(createSpecialistScreenTexture('#14b8a6', 'BUSINESS · STRATEGY', 'business'));
  const screenMarketingMap = reg(createSpecialistScreenTexture('#f97316', 'MARKETING · CAMPAIGN', 'marketing'));
  const screenHrMap = reg(createSpecialistScreenTexture('#ec4899', 'HR · CANDIDATES', 'hr'));
  const screenFinanceMap = reg(createSpecialistScreenTexture('#10b981', 'FINANCE · BUDGET', 'finance'));
  const screenEducationMap = reg(createSpecialistScreenTexture('#818cf8', 'RESEARCH · PAPERS', 'education'));
  const screenUltrawideMap = reg(createSpecialistScreenTexture('#a855f7', 'INTEGRATOR · SYNTHESIS', 'ultrawide'));

  const [slC, slctx] = makeCanvas(256, 160);
  slctx.fillStyle = '#0f172a';
  slctx.fillRect(0, 0, 256, 160);
  slctx.fillStyle = 'rgba(148, 163, 184, 0.28)';
  slctx.font = 'bold 28px monospace';
  slctx.textAlign = 'center';
  slctx.fillText('zzz', 128, 90);
  const screenSleepMap = reg(new THREE.CanvasTexture(slC));
  screenSleepMap.colorSpace = THREE.SRGBColorSpace;

  // 11. Zzz sprite & contact shadow
  const [zC, zctx] = makeCanvas(128, 128);
  zctx.clearRect(0, 0, 128, 128);
  zctx.fillStyle = 'rgba(255, 255, 255, 0.94)';
  zctx.beginPath();
  zctx.arc(64, 64, 42, 0, Math.PI * 2);
  zctx.fill();
  zctx.strokeStyle = '#64748b';
  zctx.lineWidth = 5;
  zctx.stroke();
  zctx.fillStyle = '#334155';
  zctx.font = 'bold 56px sans-serif';
  zctx.textAlign = 'center';
  zctx.textBaseline = 'middle';
  zctx.fillText('Z', 64, 68);
  const zzzSpriteMap = reg(new THREE.CanvasTexture(zC));
  zzzSpriteMap.colorSpace = THREE.SRGBColorSpace;

  const [shC, shctx] = makeCanvas(256, 256);
  const sGrad = shctx.createRadialGradient(128, 128, 14, 128, 128, 124);
  sGrad.addColorStop(0, 'rgba(20, 12, 6, 0.52)');
  sGrad.addColorStop(0.55, 'rgba(20, 12, 6, 0.20)');
  sGrad.addColorStop(1, 'rgba(20, 12, 6, 0)');
  shctx.fillStyle = sGrad;
  shctx.fillRect(0, 0, 256, 256);
  const contactShadowMap = reg(new THREE.CanvasTexture(shC));
  contactShadowMap.colorSpace = THREE.SRGBColorSpace;

  return {
    oakPlankFloorMap,
    woodBumpMap,
    oakDeskMap,
    darkSlateStoneMap,
    travertineStoneMap,
    hubMapTex,
    wovenRugBlueMap,
    wovenRugSandMap,
    fabricBumpMap,
    plasterBumpMap,
    planningBoardMap,
    draftingPaperMap,
    easelChartMap,
    missionWallMap,
    updateMissionWall,
    screenCodeMap,
    screenBusinessMap,
    screenMarketingMap,
    screenHrMap,
    screenFinanceMap,
    screenEducationMap,
    screenUltrawideMap,
    screenSleepMap,
    zzzSpriteMap,
    contactShadowMap,
    dispose: () => {
      allTextures.forEach((t) => t.dispose());
    },
  };
}
