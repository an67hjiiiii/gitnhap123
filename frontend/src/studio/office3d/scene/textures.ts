import * as THREE from 'three';

export type WallStepState = 'done' | 'now' | 'todo' | 'fail';
export interface MissionWallOpts {
  tierLabel: string;
  requestTitle: string;
  stepText: string;
  progressPct: number;
  awakeCount: number;
  sleepingCount: number;
  /** các bước của lượt (kịch bản hoặc lượt thật): chiếu lên TV thay cho khối tiến độ đè lên cảnh */
  steps?: { label: string; state: WallStepState }[];
}

export interface StudioTextureSet {
  oakPlankFloorMap: THREE.CanvasTexture;
  woodBumpMap: THREE.CanvasTexture;
  oakDeskMap: THREE.CanvasTexture;
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

  // Tactile hand-loomed herringbone/linen weave
  ctx.fillStyle = weaveHex;
  for (let y = 0; y < 512; y += 4) {
    ctx.globalAlpha = y % 8 === 0 ? 0.28 : 0.12;
    ctx.fillRect(0, y, 512, 2);
  }
  for (let x = 0; x < 512; x += 6) {
    ctx.globalAlpha = x % 12 === 0 ? 0.18 : 0.08;
    ctx.fillRect(x, 0, 2, 512);
  }
  // Organic textile speckle
  ctx.globalAlpha = 0.07;
  for (let i = 0; i < 1600; i++) {
    ctx.fillStyle = i % 2 === 0 ? '#ffffff' : '#1c1917';
    ctx.fillRect((i * 73) % 512, (i * 137) % 512, 2, 2);
  }
  ctx.globalAlpha = 1;
  ctx.strokeStyle = borderHex;
  ctx.lineWidth = 18;
  ctx.strokeRect(20, 20, 472, 472);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function createSpecialistScreenTexture(
  accent: string,
  title: string,
  kind: 'code' | 'business' | 'marketing' | 'hr' | 'finance' | 'education',
): THREE.CanvasTexture {
  const [c, ctx] = makeCanvas(512, 320);

  const bgGrad = ctx.createLinearGradient(0, 0, 512, 320);
  bgGrad.addColorStop(0, '#0b1526');
  bgGrad.addColorStop(1, '#12243f');
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
      ctx.fillStyle = i % 3 === 0 ? '#38bdf8' : i % 2 === 0 ? '#a78bfa' : '#7dd3fc';
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
  } else if (kind === 'marketing' || kind === 'finance') {
    const bars =
      kind === 'marketing'
        ? [95, 130, 175, 150, 210, 235]
        : [120, 145, 135, 185, 205, 240];
    bars.forEach((h, i) => {
      ctx.fillStyle = i === bars.length - 1 ? '#fde047' : accent;
      ctx.fillRect(36 + i * 74, 285 - h, 46, h);
    });
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 4;
    ctx.beginPath();
    bars.forEach((h, i) => {
      const px = 59 + i * 74;
      const py = 275 - h;
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

export function createStudioTextures(maxAnisotropy: number): StudioTextureSet {
  const allTextures: THREE.CanvasTexture[] = [];
  const reg = (t: THREE.CanvasTexture): THREE.CanvasTexture => {
    allTextures.push(t);
    return t;
  };

  // 1. Rich Smoked Honey-Walnut Hardwood Plank Floor + Matching Tactile Wood Bump Map!
  const [floorC, fctx] = makeCanvas(1024, 1024);
  const [bumpC, bctx] = makeCanvas(1024, 1024);
  fctx.fillStyle = '#a97b50';
  fctx.fillRect(0, 0, 1024, 1024);
  bctx.fillStyle = '#808080';
  bctx.fillRect(0, 0, 1024, 1024);

  const plankH = 64;
  // Rich natural walnut/honey oak variation (much deeper & more realistic than pale beige!)
  const plankPalette = ['#b48557', '#a7784b', '#be8f60', '#9c6e43', '#b08153', '#a37448'];
  for (let row = 0; row < 1024 / plankH; row++) {
    const y = row * plankH;
    const offset = (row % 3) * 170;
    for (let col = -1; col < 4; col++) {
      const x = col * 340 + offset;
      fctx.fillStyle = plankPalette[(row * 7 + col + 11) % plankPalette.length];
      fctx.fillRect(x, y, 338, plankH - 2);

      // Detailed natural wood grain fibers & knots
      for (let g = 0; g < 11; g++) {
        const gy = y + 4 + g * 5.5;
        fctx.strokeStyle =
          g % 2 === 0 ? 'rgba(68, 42, 20, 0.16)' : 'rgba(235, 198, 152, 0.11)';
        fctx.lineWidth = g % 3 === 0 ? 2 : 1.1;
        fctx.beginPath();
        fctx.moveTo(x + 2, gy);
        fctx.bezierCurveTo(
          x + 110,
          gy + Math.sin(row + g) * 3.5,
          x + 230,
          gy - Math.cos(col + g) * 3.5,
          x + 336,
          gy,
        );
        fctx.stroke();

        // Matching bump map ridges
        bctx.strokeStyle = g % 2 === 0 ? '#686868' : '#969696';
        bctx.lineWidth = 1.5;
        bctx.beginPath();
        bctx.moveTo(x + 2, gy);
        bctx.bezierCurveTo(
          x + 110,
          gy + Math.sin(row + g) * 3.5,
          x + 230,
          gy - Math.cos(col + g) * 3.5,
          x + 336,
          gy,
        );
        bctx.stroke();
      }

      // Deep realistic beveled plank groove
      fctx.strokeStyle = 'rgba(52, 32, 16, 0.42)';
      fctx.lineWidth = 2;
      fctx.strokeRect(x + 0.5, y + 0.5, 339, plankH - 1);

      bctx.strokeStyle = '#202020';
      bctx.lineWidth = 2.5;
      bctx.strokeRect(x + 0.5, y + 0.5, 339, plankH - 1);
    }
  }
  const oakPlankFloorMap = reg(new THREE.CanvasTexture(floorC));
  oakPlankFloorMap.colorSpace = THREE.SRGBColorSpace;
  oakPlankFloorMap.wrapS = THREE.RepeatWrapping;
  oakPlankFloorMap.wrapT = THREE.RepeatWrapping;
  oakPlankFloorMap.repeat.set(4.5, 3.6);
  oakPlankFloorMap.anisotropy = maxAnisotropy;

  const woodBumpMap = reg(new THREE.CanvasTexture(bumpC));
  woodBumpMap.wrapS = THREE.RepeatWrapping;
  woodBumpMap.wrapT = THREE.RepeatWrapping;
  woodBumpMap.repeat.set(4.5, 3.6);

  // 2. Rich Mid-Century Walnut Desk Wood Grain (512x512 — matches real wooden desk in Eilik photo!)
  const [deskC, dctx] = makeCanvas(512, 512);
  dctx.fillStyle = '#8b5e38';
  dctx.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 95; i++) {
    dctx.strokeStyle =
      i % 2 === 0 ? 'rgba(54, 32, 14, 0.22)' : 'rgba(218, 174, 126, 0.14)';
    dctx.lineWidth = 1.6 + (i % 3);
    const y = (i / 95) * 512;
    dctx.beginPath();
    dctx.moveTo(0, y);
    dctx.bezierCurveTo(170, y + Math.sin(i * 0.7) * 6, 340, y - Math.cos(i * 0.6) * 6, 512, y);
    dctx.stroke();
  }
  const oakDeskMap = reg(new THREE.CanvasTexture(deskC));
  oakDeskMap.colorSpace = THREE.SRGBColorSpace;
  oakDeskMap.anisotropy = maxAnisotropy;

  // 3. Deeper, Richer Woven Area Rugs + Fabric Bump Map (non-plasticky tactile wool!)
  const wovenRugBlueMap = reg(createWovenRugTexture('#54738f', '#38526a', '#3d5870'));
  const wovenRugSandMap = reg(createWovenRugTexture('#b9a48a', '#968066', '#8d775d'));

  const [fbC, fbctx] = makeCanvas(256, 256);
  fbctx.fillStyle = '#808080';
  fbctx.fillRect(0, 0, 256, 256);
  for (let y = 0; y < 256; y += 4) {
    fbctx.fillStyle = y % 8 === 0 ? '#9c9c9c' : '#646464';
    fbctx.fillRect(0, y, 256, 2);
  }
  for (let x = 0; x < 256; x += 4) {
    fbctx.fillStyle = x % 8 === 0 ? 'rgba(170,170,170,0.4)' : 'rgba(90,90,90,0.4)';
    fbctx.fillRect(x, 0, 2, 256);
  }
  const fabricBumpMap = reg(new THREE.CanvasTexture(fbC));
  fabricBumpMap.wrapS = THREE.RepeatWrapping;
  fabricBumpMap.wrapT = THREE.RepeatWrapping;
  fabricBumpMap.repeat.set(6, 6);

  // 4. Matte Architectural Stucco/Plaster Micro-Grain Bump Map (removes sterile plastic wall sheen!)
  const [plC, plctx] = makeCanvas(256, 256);
  plctx.fillStyle = '#808080';
  plctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 4200; i++) {
    const shade = 108 + ((i * 53) % 42);
    plctx.fillStyle = `rgb(${shade},${shade},${shade})`;
    plctx.fillRect((i * 37) % 256, (i * 89) % 256, 2, 2);
  }
  const plasterBumpMap = reg(new THREE.CanvasTexture(plC));
  plasterBumpMap.wrapS = THREE.RepeatWrapping;
  plasterBumpMap.wrapT = THREE.RepeatWrapping;
  plasterBumpMap.repeat.set(5, 3);

  // 5. Glass Planning Board Texture
  const [wbC, wctx] = makeCanvas(1024, 512);
  wctx.fillStyle = '#fbfaf7';
  wctx.fillRect(0, 0, 1024, 512);
  wctx.fillStyle = '#cbd5e1';
  for (let gx = 32; gx < 1000; gx += 32) {
    for (let gy = 32; gy < 480; gy += 32) {
      wctx.fillRect(gx, gy, 3, 3);
    }
  }
  wctx.fillStyle = '#1c1917';
  wctx.font = 'bold 34px sans-serif';
  wctx.fillText('KẾ HOẠCH & PHÂN CÔNG AI AGENT', 48, 72);
  const flowColors = ['#d97706', '#059669', '#1d4ed8', '#dc2626', '#6d28d9'];
  const flowNames = ['Nhận bài', 'Tủ RAG', 'Chuyên gia', 'Kiểm định', 'Tổng hợp'];
  flowColors.forEach((col, i) => {
    const bx = 56 + i * 188;
    wctx.fillStyle = col;
    wctx.globalAlpha = 0.16;
    wctx.fillRect(bx, 112, 152, 74);
    wctx.globalAlpha = 1;
    wctx.strokeStyle = col;
    wctx.lineWidth = 4;
    wctx.strokeRect(bx, 112, 152, 74);
    wctx.fillStyle = '#1e293b';
    wctx.font = 'bold 22px sans-serif';
    wctx.fillText(flowNames[i], bx + 20, 158);
    if (i < 4) {
      wctx.strokeStyle = '#64748b';
      wctx.beginPath();
      wctx.moveTo(bx + 152, 149);
      wctx.lineTo(bx + 186, 149);
      wctx.stroke();
    }
  });
  const planningBoardMap = reg(new THREE.CanvasTexture(wbC));
  planningBoardMap.colorSpace = THREE.SRGBColorSpace;
  planningBoardMap.anisotropy = maxAnisotropy;

  // 6. Data Analyst Drafting Paper Sheet
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
  [55, 88, 72, 118, 142].forEach((h, i) => {
    dpctx.fillStyle = i % 2 === 0 ? '#1d4ed8' : '#3b82f6';
    dpctx.fillRect(54 + i * 38, 445 - h, 24, h);
  });
  dpctx.fillStyle = '#d97706';
  dpctx.beginPath();
  dpctx.moveTo(395, 360);
  dpctx.arc(395, 360, 68, 0, Math.PI * 1.25);
  dpctx.closePath();
  dpctx.fill();
  dpctx.fillStyle = '#1d4ed8';
  dpctx.beginPath();
  dpctx.moveTo(395, 360);
  dpctx.arc(395, 360, 68, Math.PI * 1.25, Math.PI * 2);
  dpctx.closePath();
  dpctx.fill();
  const draftingPaperMap = reg(new THREE.CanvasTexture(dpC));
  draftingPaperMap.colorSpace = THREE.SRGBColorSpace;

  // 7. Standing Chart Easel Board
  const [eaC, eactx] = makeCanvas(512, 640);
  eactx.fillStyle = '#fbfaf7';
  eactx.fillRect(0, 0, 512, 640);
  eactx.fillStyle = '#1e3a8a';
  eactx.fillRect(0, 0, 512, 76);
  eactx.fillStyle = '#ffffff';
  eactx.font = 'bold 30px sans-serif';
  eactx.fillText('BIỂU ĐỒ SỐ LIỆU · KPI', 36, 49);
  const cols = ['#60a5fa', '#3b82f6', '#2563eb', '#1d4ed8', '#059669'];
  const vals = [120, 175, 155, 235, 290];
  vals.forEach((v, i) => {
    eactx.fillStyle = cols[i];
    eactx.fillRect(54 + i * 84, 460 - v, 54, v);
  });
  eactx.strokeStyle = '#d97706';
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
  eactx.fillText('ROAS +34.2%  |  CPA -18.5%', 54, 548);
  const easelChartMap = reg(new THREE.CanvasTexture(eaC));
  easelChartMap.colorSpace = THREE.SRGBColorSpace;

  // 8. Dynamic Live 3D Mission Control Wall Display
  const WALL_W = 1280;
  const WALL_H = 404; // tỉ lệ màn hình 6,35 m × 2,0 m
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
  const pill = (x: number, y: number, w: number, h: number, r: number) => {
    mwctx.beginPath();
    mwctx.roundRect(x, y, w, h, r);
  };
  const STEP_STYLE: Record<WallStepState, { bg: string; fg: string; border: string; mark: string }> = {
    done: { bg: 'rgba(16,185,129,0.16)', fg: '#a7f3d0', border: 'rgba(52,211,153,0.55)', mark: '✓' },
    now: { bg: '#f59e0b', fg: '#1c1305', border: '#fbbf24', mark: '●' },
    todo: { bg: 'rgba(148,163,184,0.08)', fg: '#94a3b8', border: 'rgba(148,163,184,0.3)', mark: '○' },
    fail: { bg: 'rgba(244,63,94,0.18)', fg: '#fecdd3', border: 'rgba(251,113,133,0.6)', mark: '!' },
  };

  const updateMissionWall = (opts: MissionWallOpts) => {
    const PAD = 48;
    const bg = mwctx.createLinearGradient(0, 0, WALL_W, WALL_H);
    bg.addColorStop(0, '#0b1220');
    bg.addColorStop(1, '#16233a');
    mwctx.fillStyle = bg;
    mwctx.fillRect(0, 0, WALL_W, WALL_H);
    mwctx.textBaseline = 'alphabetic';

    // hàng đầu: tên phòng + nhãn chế độ | số Agent thức/ngủ
    mwctx.font = '700 22px sans-serif';
    mwctx.fillStyle = '#64748b';
    mwctx.fillText('ĐIỀU PHỐI AGENT', PAD, 58);
    const tierX = PAD + mwctx.measureText('ĐIỀU PHỐI AGENT').width + 16;
    mwctx.font = '700 20px sans-serif';
    const tier = opts.tierLabel.toUpperCase();
    const tierW = mwctx.measureText(tier).width + 24;
    pill(tierX, 34, tierW, 32, 16);
    mwctx.fillStyle = 'rgba(245,158,11,0.18)';
    mwctx.fill();
    mwctx.fillStyle = '#fbbf24';
    mwctx.fillText(tier, tierX + 12, 57);
    mwctx.textAlign = 'right';
    mwctx.font = '600 22px sans-serif';
    mwctx.fillStyle = '#7dd3fc';
    mwctx.fillText(`${opts.awakeCount} đang làm · ${opts.sleepingCount} đang ngủ`, WALL_W - PAD, 58);
    mwctx.textAlign = 'left';

    // câu hỏi và bước hiện tại
    mwctx.font = '700 36px sans-serif';
    mwctx.fillStyle = '#f8fafc';
    mwctx.fillText(fit(opts.requestTitle, WALL_W - PAD * 2), PAD, 124);
    mwctx.font = '600 27px sans-serif';
    mwctx.fillStyle = '#fcd34d';
    mwctx.fillText(fit(`▸ ${opts.stepText}`, WALL_W - PAD * 2), PAD, 172);

    // các bước: tối đa 2 hàng, bước dư gộp thành "+N"
    const steps = opts.steps ?? [];
    if (steps.length) {
      mwctx.font = '600 21px sans-serif';
      let x = PAD;
      let y = 202;
      let row = 0;
      for (let i = 0; i < steps.length; i++) {
        const st = STEP_STYLE[steps[i].state];
        const text = fit(`${st.mark} ${steps[i].label}`, 300);
        const w = mwctx.measureText(text).width + 28;
        if (x + w > WALL_W - PAD) {
          row += 1;
          if (row > 1) {
            mwctx.fillStyle = '#94a3b8';
            mwctx.fillText(`+${steps.length - i}`, x, y + 28);
            break;
          }
          x = PAD;
          y += 50;
        }
        pill(x, y, w, 40, 20);
        mwctx.fillStyle = st.bg;
        mwctx.fill();
        mwctx.strokeStyle = st.border;
        mwctx.lineWidth = 2;
        mwctx.stroke();
        mwctx.fillStyle = st.fg;
        mwctx.fillText(text, x + 14, y + 28);
        x += w + 10;
      }
    }

    // thanh tiến độ mảnh ở đáy
    const barY = WALL_H - 46;
    const pct = Math.max(0, Math.min(100, opts.progressPct));
    pill(PAD, barY, WALL_W - PAD * 2 - 90, 12, 6);
    mwctx.fillStyle = 'rgba(255,255,255,0.1)';
    mwctx.fill();
    if (pct > 0) {
      const barGrad = mwctx.createLinearGradient(PAD, 0, WALL_W - PAD, 0);
      barGrad.addColorStop(0, '#f59e0b');
      barGrad.addColorStop(1, '#10b981');
      pill(PAD, barY, Math.max(12, ((WALL_W - PAD * 2 - 90) * pct) / 100), 12, 6);
      mwctx.fillStyle = barGrad;
      mwctx.fill();
    }
    mwctx.textAlign = 'right';
    mwctx.font = '700 24px sans-serif';
    mwctx.fillStyle = '#e2e8f0';
    mwctx.fillText(`${Math.round(pct)}%`, WALL_W - PAD, barY + 13);
    mwctx.textAlign = 'left';

    missionWallMap.needsUpdate = true;
  };

  updateMissionWall({
    tierLabel: 'Văn phòng AI',
    requestTitle: 'Đang chờ tiếp nhận yêu cầu...',
    stepText: 'Chọn kịch bản độ khó bên dưới để bắt đầu',
    progressPct: 0,
    awakeCount: 0,
    sleepingCount: 11,
  });

  // 9. Specialist Screens + Sleep Screen
  const screenCodeMap = reg(createSpecialistScreenTexture('#38bdf8', 'SOFTWARE · IDE & API', 'code'));
  const screenBusinessMap = reg(createSpecialistScreenTexture('#14b8a6', 'BUSINESS · STRATEGY', 'business'));
  const screenMarketingMap = reg(createSpecialistScreenTexture('#f97316', 'MARKETING · CAMPAIGN', 'marketing'));
  const screenHrMap = reg(createSpecialistScreenTexture('#ec4899', 'HR · CANDIDATES', 'hr'));
  const screenFinanceMap = reg(createSpecialistScreenTexture('#10b981', 'FINANCE · BUDGET', 'finance'));
  const screenEducationMap = reg(createSpecialistScreenTexture('#818cf8', 'RESEARCH · PAPERS', 'education'));

  const [slC, slctx] = makeCanvas(256, 160);
  slctx.fillStyle = '#141922';
  slctx.fillRect(0, 0, 256, 160);
  slctx.fillStyle = 'rgba(148, 163, 184, 0.25)';
  slctx.font = 'bold 28px monospace';
  slctx.textAlign = 'center';
  slctx.fillText('zzz', 128, 90);
  const screenSleepMap = reg(new THREE.CanvasTexture(slC));
  screenSleepMap.colorSpace = THREE.SRGBColorSpace;

  // 10. Crisp 3D Floating 'Z' Sprite Texture
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

  // 11. Deep Rich Ground Contact Shadow (gives real sculptural groundedness!)
  const [shC, shctx] = makeCanvas(256, 256);
  const sGrad = shctx.createRadialGradient(128, 128, 14, 128, 128, 124);
  sGrad.addColorStop(0, 'rgba(32, 20, 10, 0.48)');
  sGrad.addColorStop(0.55, 'rgba(32, 20, 10, 0.18)');
  sGrad.addColorStop(1, 'rgba(32, 20, 10, 0)');
  shctx.fillStyle = sGrad;
  shctx.fillRect(0, 0, 256, 256);
  const contactShadowMap = reg(new THREE.CanvasTexture(shC));
  contactShadowMap.colorSpace = THREE.SRGBColorSpace;

  return {
    oakPlankFloorMap,
    woodBumpMap,
    oakDeskMap,
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
    screenSleepMap,
    zzzSpriteMap,
    contactShadowMap,
    dispose: () => {
      allTextures.forEach((t) => t.dispose());
    },
  };
}
