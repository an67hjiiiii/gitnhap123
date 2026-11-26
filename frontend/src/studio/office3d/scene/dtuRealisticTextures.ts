/**
 * Bộ vật liệu PBR procedural & hình khối tạo dáng chân thực cho khung cảnh 3D
 * Đại học Duy Tân (120 Hoàng Minh Thảo, Hòa Khánh Nam, Liên Chiểu, Đà Nẵng).
 *
 * Thiết kế theo hướng "3D kiến trúc tươi sáng, sắc nét, đỡ nhựa/Lego" và giữ nguyên
 * tốc độ mượt: toàn bộ texture sinh 1 lần ở nền (lazy chunk), tự động giảm độ phân giải
 * trên máy không GPU rời (lowQuality) và tái sử dụng qua InstancedMesh / mergeStaticMeshes.
 */
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

function seededRand(seedInit: number): () => number {
  let s = seedInit;
  return () => {
    s = (s * 48271) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

function makeCanvas(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return [c, c.getContext('2d')!];
}

function makeTex(
  canvas: HTMLCanvasElement,
  maxAniso: number,
  srgb: boolean,
  repeatX = 1,
  repeatY = 1,
): THREE.CanvasTexture {
  const t = new THREE.CanvasTexture(canvas);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeatX, repeatY);
  t.anisotropy = Math.min(8, Math.max(1, maxAniso));
  return t;
}

/**
 * 1. Mặt tiền Nhà ống Đà Nẵng (Hòa Khánh Nam & Tân Cường Thành):
 *    Tầng 1 cửa cuốn / cửa kính sinh viên; các tầng trên cửa sổ khung nhôm kính có rèm,
 *    lan can ban công sắt thanh mảnh, cục nóng điều hòa, đường phào bê tông & vết mưa nhẹ.
 *    Kèm bumpMap nổi khối và emissiveMap đèn phòng ấm áp lúc hoàng hôn/ban đêm.
 */
export function createVietnameseTubeHouseTextures(
  maxAniso: number,
  lowQuality: boolean,
): {
  colorMap: THREE.CanvasTexture;
  bumpMap: THREE.CanvasTexture;
  emissiveMap: THREE.CanvasTexture;
} {
  const size = lowQuality ? 256 : 512;
  const [cCol, ctx] = makeCanvas(size, size);
  const [cBump, bCtx] = makeCanvas(size, size);
  const [cEm, eCtx] = makeCanvas(size, size);

  const rand = seededRand(8173);

  // Nền vữa tường trắng ngà mịn (sẽ nhân với instanceColor của từng nhà!)
  ctx.fillStyle = '#f2f0eb';
  ctx.fillRect(0, 0, size, size);
  bCtx.fillStyle = '#808080';
  bCtx.fillRect(0, 0, size, size);
  eCtx.fillStyle = '#000000';
  eCtx.fillRect(0, 0, size, size);

  // Nhiễu hạt vữa xi măng nhẹ cho hết cảm giác nhựa trơn
  const grainCount = lowQuality ? 1600 : 4200;
  for (let i = 0; i < grainCount; i++) {
    const gx = rand() * size;
    const gy = rand() * size;
    const gs = 1 + rand() * 3;
    const shade = rand() > 0.5 ? 'rgba(255,255,255,0.08)' : 'rgba(90,85,78,0.06)';
    ctx.fillStyle = shade;
    ctx.fillRect(gx, gy, gs, gs);
    bCtx.fillStyle = rand() > 0.5 ? '#888888' : '#787878';
    bCtx.fillRect(gx, gy, gs, gs);
  }

  // Vệt phong hóa nhẹ dưới chân tường & dưới mái
  const baseGrad = ctx.createLinearGradient(0, size * 0.86, 0, size);
  baseGrad.addColorStop(0, 'rgba(65, 62, 58, 0)');
  baseGrad.addColorStop(1, 'rgba(55, 52, 48, 0.22)');
  ctx.fillStyle = baseGrad;
  ctx.fillRect(0, size * 0.86, size, size * 0.14);

  const topGrad = ctx.createLinearGradient(0, 0, 0, size * 0.08);
  topGrad.addColorStop(0, 'rgba(60, 58, 55, 0.16)');
  topGrad.addColorStop(1, 'rgba(60, 58, 55, 0)');
  ctx.fillStyle = topGrad;
  ctx.fillRect(0, 0, size, size * 0.08);

  const floors = 3;
  const flH = size / floors;

  for (let f = 0; f < floors; f++) {
    const y0 = f * flH;
    const isGround = f === floors - 1;

    // Gờ bê tông phân tầng có bóng đổ mềm bên dưới
    const slabH = Math.round(flH * 0.08);
    ctx.fillStyle = '#dedad2';
    ctx.fillRect(0, y0, size, slabH);
    ctx.fillStyle = 'rgba(40,44,50,0.22)';
    ctx.fillRect(0, y0 + slabH, size, Math.round(slabH * 0.55));
    bCtx.fillStyle = '#c8c8c8';
    bCtx.fillRect(0, y0, size, slabH);

    if (isGround) {
      // Tầng trệt: cửa cuốn / cửa kính khung nhôm + cột 2 bên
      const doorX = size * 0.14;
      const doorW = size * 0.72;
      const doorY = y0 + flH * 0.22;
      const doorH = flH * 0.78;

      // Khung cửa
      ctx.fillStyle = '#525b66';
      ctx.fillRect(doorX - 4, doorY - 4, doorW + 8, doorH + 4);
      // Lá cửa cuốn khe thoáng xám bạc + ô kính nhỏ
      const gDoor = ctx.createLinearGradient(0, doorY, 0, doorY + doorH);
      gDoor.addColorStop(0, '#4a5562');
      gDoor.addColorStop(0.4, '#64707d');
      gDoor.addColorStop(1, '#39424d');
      ctx.fillStyle = gDoor;
      ctx.fillRect(doorX, doorY, doorW, doorH);
      bCtx.fillStyle = '#484848';
      bCtx.fillRect(doorX, doorY, doorW, doorH);

      // Các nan cửa cuốn ngang
      const slatStep = Math.max(4, Math.round(doorH / 16));
      for (let sy = doorY + slatStep; sy < doorY + doorH; sy += slatStep) {
        ctx.fillStyle = 'rgba(20,24,30,0.32)';
        ctx.fillRect(doorX, sy, doorW, 2);
        bCtx.fillStyle = '#2d2d2d';
        bCtx.fillRect(doorX, sy, doorW, 2);
      }

      // Ô cửa kính hắt đèn ấm phía trong tầng 1
      ctx.fillStyle = 'rgba(255, 228, 170, 0.34)';
      ctx.fillRect(doorX + doorW * 0.12, doorY + doorH * 0.14, doorW * 0.76, doorH * 0.36);
      eCtx.fillStyle = '#ffd994';
      eCtx.fillRect(doorX + doorW * 0.14, doorY + doorH * 0.16, doorW * 0.72, doorH * 0.32);
    } else {
      // Tầng 2 & 3: 2 ô cửa sổ / cửa ban công nhôm kính + lan can sắt thanh mảnh
      const cols = 2;
      const colW = size / cols;
      for (let c = 0; c < cols; c++) {
        const wx = c * colW + colW * 0.14;
        const ww = colW * 0.72;
        const wy = y0 + flH * 0.2;
        const wh = flH * 0.56;

        // Hốc cửa sổ lùi sâu (tạo bóng cạnh trên)
        ctx.fillStyle = '#6c757e';
        ctx.fillRect(wx - 4, wy - 4, ww + 8, wh + 8);
        bCtx.fillStyle = '#383838';
        bCtx.fillRect(wx, wy, ww, wh);

        const lit = rand() < 0.55;
        const wGrad = ctx.createLinearGradient(wx, wy, wx, wy + wh);
        if (lit) {
          wGrad.addColorStop(0, '#5a6875');
          wGrad.addColorStop(0.35, '#8a8268');
          wGrad.addColorStop(1, '#394452');
        } else {
          wGrad.addColorStop(0, '#2a394a');
          wGrad.addColorStop(0.5, '#3b4e63');
          wGrad.addColorStop(1, '#1e2936');
        }
        ctx.fillStyle = wGrad;
        ctx.fillRect(wx, wy, ww, wh);

        // Vệt phản chiếu chéo nhẹ trên mặt kính
        ctx.fillStyle = 'rgba(215, 236, 255, 0.16)';
        ctx.beginPath();
        ctx.moveTo(wx, wy + wh * 0.45);
        ctx.lineTo(wx + ww * 0.45, wy);
        ctx.lineTo(wx + ww * 0.72, wy);
        ctx.lineTo(wx, wy + wh * 0.72);
        ctx.closePath();
        ctx.fill();

        // Khung chia cánh cửa nhôm
        ctx.fillStyle = '#d4d8dd';
        ctx.fillRect(wx + ww * 0.5 - 2, wy, 4, wh);
        ctx.fillRect(wx, wy + wh * 0.28, ww, 3);

        if (lit) {
          eCtx.fillStyle = rand() > 0.4 ? '#ffdfa0' : '#d6f0ff';
          eCtx.fillRect(wx + 5, wy + 5, ww - 10, wh - 10);
        }
      }

      // Lan can ban công sắt ngang + dọc thanh mảnh ở nửa dưới tầng
      const railY = y0 + flH * 0.74;
      const railH = flH * 0.22;
      ctx.fillStyle = '#2d3540';
      ctx.fillRect(size * 0.08, railY, size * 0.84, 3);
      ctx.fillRect(size * 0.08, railY + railH, size * 0.84, 3);
      bCtx.fillStyle = '#b4b4b4';
      bCtx.fillRect(size * 0.08, railY, size * 0.84, 4);
      const barStep = Math.max(8, Math.round(size / 26));
      for (let bx = size * 0.1; bx < size * 0.9; bx += barStep) {
        ctx.fillRect(bx, railY, 2, railH);
      }

      // Cục nóng điều hòa nhỏ bên góc ban công
      if (f === 1) {
        const ax = size * 0.82;
        const ay = y0 + flH * 0.48;
        ctx.fillStyle = '#dfe3e8';
        ctx.fillRect(ax, ay, size * 0.11, flH * 0.22);
        ctx.fillStyle = '#525b65';
        ctx.beginPath();
        ctx.arc(ax + size * 0.04, ay + flH * 0.11, flH * 0.07, 0, Math.PI * 2);
        ctx.fill();
        bCtx.fillStyle = '#d8d8d8';
        bCtx.fillRect(ax, ay, size * 0.11, flH * 0.22);
      }
    }
  }

  return {
    colorMap: makeTex(cCol, maxAniso, true),
    bumpMap: makeTex(cBump, maxAniso, false),
    emissiveMap: makeTex(cEm, maxAniso, true),
  };
}

/**
 * 2. Mái tôn sóng miền Trung (có gân sóng, mí chồng tôn, vết nắng bụi tự nhiên).
 */
export function createCorrugatedRoofTextures(
  maxAniso: number,
  lowQuality: boolean,
): { colorMap: THREE.CanvasTexture; bumpMap: THREE.CanvasTexture } {
  const size = lowQuality ? 256 : 512;
  const [cCol, ctx] = makeCanvas(size, size);
  const [cBump, bCtx] = makeCanvas(size, size);
  const rand = seededRand(5039);

  ctx.fillStyle = '#e5e7eb';
  ctx.fillRect(0, 0, size, size);
  bCtx.fillStyle = '#808080';
  bCtx.fillRect(0, 0, size, size);

  // Sóng tôn chạy dọc đều
  const waves = 28;
  const step = size / waves;
  for (let i = 0; i < waves; i++) {
    const x = i * step;
    const g = ctx.createLinearGradient(x, 0, x + step, 0);
    g.addColorStop(0, '#c7cdd4');
    g.addColorStop(0.35, '#f2f4f7');
    g.addColorStop(0.7, '#d1d6dd');
    g.addColorStop(1, '#bcc2ca');
    ctx.fillStyle = g;
    ctx.fillRect(x, 0, step, size);

    const bg = bCtx.createLinearGradient(x, 0, x + step, 0);
    bg.addColorStop(0, '#444444');
    bg.addColorStop(0.45, '#dadada');
    bg.addColorStop(1, '#444444');
    bCtx.fillStyle = bg;
    bCtx.fillRect(x, 0, step, size);
  }

  // Đường mí chồng ngang & vết thời tiết nhẹ
  for (let row = 1; row < 4; row++) {
    const ry = Math.round((row * size) / 4);
    ctx.fillStyle = 'rgba(35,40,48,0.22)';
    ctx.fillRect(0, ry, size, 2);
    bCtx.fillStyle = '#303030';
    bCtx.fillRect(0, ry, size, 2);
  }
  for (let i = 0; i < (lowQuality ? 300 : 900); i++) {
    ctx.fillStyle = rand() > 0.5 ? 'rgba(90,75,60,0.06)' : 'rgba(255,255,255,0.06)';
    ctx.fillRect(rand() * size, rand() * size, 3 + rand() * 8, 2 + rand() * 5);
  }

  return {
    colorMap: makeTex(cCol, maxAniso, true, 1, 1),
    bumpMap: makeTex(cBump, maxAniso, false, 1, 1),
  };
}

/**
 * 3. Vân lá cây tự nhiên nhiều sắc độ sáng/tối + bumpMap xù xì (xóa cảm giác quả bóng nhựa!).
 */
export function createFoliageCanopyTextures(
  maxAniso: number,
  lowQuality: boolean,
): { colorMap: THREE.CanvasTexture; bumpMap: THREE.CanvasTexture } {
  const size = lowQuality ? 256 : 512;
  const [cCol, ctx] = makeCanvas(size, size);
  const [cBump, bCtx] = makeCanvas(size, size);
  const rand = seededRand(9923);

  ctx.fillStyle = '#aebfa0';
  ctx.fillRect(0, 0, size, size);
  bCtx.fillStyle = '#707070';
  bCtx.fillRect(0, 0, size, size);

  const count = lowQuality ? 1100 : 2800;
  for (let i = 0; i < count; i++) {
    const x = rand() * size;
    const y = rand() * size;
    const rx = 3 + rand() * (size / 36);
    const ry = 2 + rand() * (size / 50);
    const rot = rand() * Math.PI;
    const v = rand();

    // Màu trung tính sáng/tối để nhân mượt với instanceColor xanh lá từng cây
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rot);
    ctx.fillStyle =
      v > 0.72
        ? 'rgba(235, 248, 215, 0.78)'
        : v > 0.35
          ? 'rgba(176, 198, 158, 0.78)'
          : 'rgba(84, 108, 72, 0.72)';
    ctx.beginPath();
    ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    bCtx.save();
    bCtx.translate(x, y);
    bCtx.rotate(rot);
    bCtx.fillStyle = v > 0.55 ? '#c6c6c6' : '#404040';
    bCtx.beginPath();
    bCtx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
    bCtx.fill();
    bCtx.restore();
  }

  return {
    colorMap: makeTex(cCol, maxAniso, true, 2, 2),
    bumpMap: makeTex(cBump, maxAniso, false, 2, 2),
  };
}

/**
 * 4. Tán cây biến dạng đỉnh hữu cơ (organic displaced icosahedron) — hết cảm giác cầu trơn Lego!
 */
export function createOrganicCanopyGeo(radius = 1.52, detail = 1): THREE.BufferGeometry {
  const geo = new THREE.IcosahedronGeometry(radius, detail);
  const pos = geo.attributes.position as THREE.BufferAttribute;
  const v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i);
    const n =
      Math.sin(v.x * 2.7 + v.y * 1.9) * 0.14 +
      Math.cos(v.z * 3.1 - v.x * 2.1) * 0.11 +
      Math.sin(v.y * 4.3 + v.z * 2.4) * 0.08;
    // Hơi dẹt phần đáy tán để dáng tán cây nhiệt đới tự nhiên
    const flatBottom = v.y < 0 ? 0.84 : 1.0;
    v.multiplyScalar(1 + n);
    v.y *= flatBottom;
    pos.setXYZ(i, v.x, v.y, v.z);
  }
  geo.computeVertexNormals();
  return geo;
}

/**
 * 5. Tán Cây Bàng Đài Loan dáng tầng mảnh (đặc trưng sân quảng trường trước Nhà G & Nhà F ĐH Duy Tân).
 */
export function createBangDaiLoanCanopyGeo(): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  const tiers: Array<[number, number, number]> = [
    [1.35, 0.36, 2.35], // tầng lá dưới rộng
    [1.08, 0.32, 3.15], // tầng giữa
    [0.72, 0.28, 3.85], // tầng ngọn
  ];
  tiers.forEach(([r, h, y], idx) => {
    const disc = new THREE.CylinderGeometry(r * 0.72, r, h, 9, 1);
    const pos = disc.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i++) {
      const px = pos.getX(i);
      const py = pos.getY(i);
      const pz = pos.getZ(i);
      const jitter = 1 + Math.sin(px * 3.8 + idx) * 0.09 + Math.cos(pz * 3.5 - idx) * 0.09;
      pos.setXYZ(i, px * jitter, py, pz * jitter);
    }
    disc.translate(0, y, 0);
    disc.computeVertexNormals();
    parts.push(disc);
  });
  const merged = mergeGeometries(parts, false)!;
  parts.forEach((p) => p.dispose());
  return merged;
}

/**
 * 6. Nhựa đường bumpMap hạt mịn (tạo chiều sâu thật cho đường Hoàng Minh Thảo & sân trường).
 */
export function createAsphaltBumpTexture(maxAniso: number, lowQuality: boolean): THREE.CanvasTexture {
  const size = lowQuality ? 256 : 512;
  const [c, ctx] = makeCanvas(size, size);
  const rand = seededRand(4409);
  ctx.fillStyle = '#808080';
  ctx.fillRect(0, 0, size, size);
  const count = lowQuality ? 3000 : 9000;
  for (let i = 0; i < count; i++) {
    const v = 90 + Math.floor(rand() * 80);
    ctx.fillStyle = `rgb(${v},${v},${v})`;
    ctx.fillRect(rand() * size, rand() * size, 2, 2);
  }
  return makeTex(c, maxAniso, false, 12, 12);
}

/**
 * 7. Đĩa bóng râm tiếp đất mềm (Contact AO) cho gốc cây & chân công trình.
 */
export function createContactShadowTexture(): THREE.CanvasTexture {
  const [c, ctx] = makeCanvas(128, 128);
  const g = ctx.createRadialGradient(64, 64, 8, 64, 64, 62);
  g.addColorStop(0, 'rgba(18, 24, 30, 0.42)');
  g.addColorStop(0.55, 'rgba(18, 24, 30, 0.20)');
  g.addColorStop(1, 'rgba(18, 24, 30, 0.0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/**
 * 8. Hình khối Ô tô & Xe máy tạo dáng thật (gộp sẵn 1 BufferGeometry duy nhất -> 0 thêm draw calls!).
 *    - Ô tô hướng dọc trục +X (tương thích 100% với rotation hiện có trong update() giao thông).
 *    - Xe máy hướng dọc trục +Z (tương thích 100% với bikeCoords hiện có).
 */
export function createRealisticCarGeo(): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  // Thân dưới xe (dài 1.0, cao 0.46, rộng 0.96 -> sẽ scale bởi (len, hgt, wid))
  const chassis = new THREE.BoxGeometry(0.98, 0.42, 0.92);
  chassis.translate(0, -0.14, 0);
  parts.push(chassis);

  // Cabin trên thu gọn & lùi nhẹ (tạo dáng mui sedan/hatchback)
  const cabin = new THREE.BoxGeometry(0.54, 0.36, 0.78);
  cabin.translate(-0.04, 0.22, 0);
  parts.push(cabin);

  // 4 bánh xe gọn 2 bên
  const wheelOffsets: Array<[number, number]> = [
    [-0.28, -0.44],
    [-0.28, 0.44],
    [0.28, -0.44],
    [0.28, 0.44],
  ];
  wheelOffsets.forEach(([wx, wz]) => {
    const w = new THREE.BoxGeometry(0.22, 0.24, 0.12);
    w.translate(wx, -0.34, wz);
    parts.push(w);
  });

  const merged = mergeGeometries(parts, false)!;
  parts.forEach((p) => p.dispose());
  merged.computeVertexNormals();
  return merged;
}

export function createRealisticMotorbikeGeo(): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  // Thân xe vát mảnh
  const body = new THREE.BoxGeometry(0.38, 0.44, 1.16);
  body.translate(0, -0.02, -0.04);
  parts.push(body);

  // Đầu xe + yếm trước vươn cao
  const frontShield = new THREE.BoxGeometry(0.42, 0.56, 0.28);
  frontShield.rotateX(-0.18);
  frontShield.translate(0, 0.14, 0.44);
  parts.push(frontShield);

  // Tay lái ngang
  const handlebar = new THREE.BoxGeometry(0.68, 0.08, 0.09);
  handlebar.translate(0, 0.44, 0.4);
  parts.push(handlebar);

  // Bánh trước & bánh sau
  const frontW = new THREE.BoxGeometry(0.14, 0.38, 0.38);
  frontW.translate(0, -0.22, 0.56);
  const rearW = new THREE.BoxGeometry(0.16, 0.38, 0.38);
  rearW.translate(0, -0.22, -0.52);
  parts.push(frontW, rearW);

  const merged = mergeGeometries(parts, false)!;
  parts.forEach((p) => p.dispose());
  merged.computeVertexNormals();
  return merged;
}

/**
 * 9. Mái chống thấm bê tông xanh ngọc trầm rêu nhẹ (cho Nhà E, D, C, F — thay màu xanh lá Lego chói!).
 */
export function createWaterproofRoofTexture(maxAniso: number, lowQuality: boolean): THREE.CanvasTexture {
  const size = lowQuality ? 256 : 512;
  const [c, ctx] = makeCanvas(size, size);
  const rand = seededRand(7129);

  // Xanh ngọc chống thấm dịu thực tế như ảnh flycam ĐH Duy Tân
  ctx.fillStyle = '#3d8b74';
  ctx.fillRect(0, 0, size, size);

  // Khe co giãn mái bê tông
  ctx.strokeStyle = 'rgba(28, 66, 54, 0.28)';
  ctx.lineWidth = 2;
  const step = size / 6;
  for (let i = 1; i < 6; i++) {
    ctx.beginPath();
    ctx.moveTo(i * step, 0);
    ctx.lineTo(i * step, size);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, i * step);
    ctx.lineTo(size, i * step);
    ctx.stroke();
  }

  // Vệt nắng, bụi & rêu mờ tự nhiên
  for (let i = 0; i < (lowQuality ? 260 : 800); i++) {
    const x = rand() * size;
    const y = rand() * size;
    const r = 4 + rand() * 18;
    ctx.fillStyle =
      rand() > 0.5 ? 'rgba(255, 255, 240, 0.05)' : 'rgba(24, 52, 42, 0.08)';
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  return makeTex(c, maxAniso, true, 2, 2);
}

/**
 * 10. Bồn nước Inox trụ đứng trên sân thượng nhà phố Việt Nam (1 geometry gọn cho InstancedMesh).
 */
export function createWaterTankGeo(): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  const tank = new THREE.CylinderGeometry(0.42, 0.42, 1.05, 10);
  tank.translate(0, 0.72, 0);
  const stand = new THREE.CylinderGeometry(0.36, 0.44, 0.24, 6);
  stand.translate(0, 0.12, 0);
  parts.push(tank, stand);
  const merged = mergeGeometries(parts, false)!;
  parts.forEach((p) => p.dispose());
  merged.computeVertexNormals();
  return merged;
}
