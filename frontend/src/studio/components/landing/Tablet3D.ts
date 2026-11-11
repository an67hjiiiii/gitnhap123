// Máy tính bảng 3D (Three.js) cho phần câu chuyện trên landing.
// Chỉ nạp khi phần câu chuyện được ghim (màn hình rộng, bật chuyển động); lỗi WebGL thì trả null để giữ thiết bị CSS cũ.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { PAPERS } from './PaperStory';

export interface TabletState { ry: number; rx: number; docs: number; meter: number }
export interface Tablet3D { update(s: TabletState): void; dispose(): void }

const BW = 4, BH = 2.8, BD = 0.17;          // thân máy
const SW = 3.68, SH = 2.48;                  // vùng màn hình
const CW = 1484, CH = 1000;                  // canvas vẽ màn hình (cùng tỉ lệ SW/SH)
const KIND_COLOR: Record<string, string> = { db: '#2b7de9', api: '#16a36a', sec: '#d64545', shared: '#d99a00', noise: '#94a3b8' };
const FONT = '"Be Vietnam Pro", system-ui, sans-serif';
const MONO = 'ui-monospace, Consolas, monospace';

function rr(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath(); g.roundRect(x, y, w, h, r);
}

function drawScreen(g: CanvasRenderingContext2D, docs: number, meter: number) {
  g.clearRect(0, 0, CW, CH);
  g.save(); rr(g, 0, 0, CW, CH, 30); g.clip();
  g.fillStyle = '#f5f7fa'; g.fillRect(0, 0, CW, CH);
  // Thanh tiêu đề
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, CW, 72);
  g.fillStyle = '#e4e9ef'; g.fillRect(0, 72, CW, 2);
  ['#ff5f57', '#febc2e', '#28c840'].forEach((c, i) => { g.fillStyle = c; g.beginPath(); g.arc(38 + i * 30, 36, 9, 0, Math.PI * 2); g.fill(); });
  g.fillStyle = '#5f6e7d'; g.font = `600 26px ${FONT}`; g.textBaseline = 'middle'; g.fillText('Cửa sổ ngữ cảnh · qwen3:4b', 134, 37);
  // Câu hỏi và câu trả lời đang viết
  g.fillStyle = '#0f1d2b'; rr(g, 40, 112, 800, 124, 22); g.fill();
  g.fillStyle = '#ffffff'; g.font = `700 29px ${FONT}`;
  g.fillText('Thiết kế luồng thanh toán không xử lý trùng,', 68, 155); g.fillText('có kiểm soát quyền.', 68, 197);
  g.fillStyle = '#e6f0fd'; rr(g, 40, 268, 60, 44, 12); g.fill();
  g.fillStyle = '#1d66c9'; g.font = `800 22px ${FONT}`; g.fillText('AI', 55, 291);
  g.fillStyle = '#ffffff'; g.strokeStyle = '#e3e8ee'; g.lineWidth = 2; rr(g, 114, 258, 726, 200, 20); g.fill(); g.stroke();
  [640, 560, 610, 380].forEach((w, i) => { g.fillStyle = '#e6ebf1'; rr(g, 140, 292 + i * 38, w, 15, 8); g.fill(); });
  // Danh sách tài liệu đã nạp
  g.fillStyle = '#ffffff'; rr(g, 884, 104, 560, 770, 22); g.fill(); g.stroke();
  for (let i = 0; i < 7; i++) {
    const a = Math.max(0, Math.min(1, docs - i));
    if (a <= 0) break;
    const p = PAPERS[i], y = 124 + i * 72 + (1 - a) * 18;
    g.globalAlpha = a;
    g.fillStyle = '#f5f7fa'; rr(g, 904, y, 520, 58, 12); g.fill();
    g.fillStyle = KIND_COLOR[p.kind]; rr(g, 920, y + 13, 78, 32, 8); g.fill();
    g.fillStyle = '#ffffff'; g.font = `800 18px ${FONT}`; g.textAlign = 'center'; g.fillText(p.ext, 959, y + 30); g.textAlign = 'left';
    g.fillStyle = '#3d5164'; g.font = `500 24px ${MONO}`; g.fillText(p.name, 1014, y + 30);
    g.globalAlpha = 1;
  }
  // Thanh ngữ cảnh: đầy thì chuyển đỏ
  const over = meter > 0.97;
  g.fillStyle = '#34495e'; g.font = `600 26px ${FONT}`; g.fillText('Ngữ cảnh đã dùng', 40, 932);
  g.fillStyle = '#e3e8ee'; rr(g, 290, 918, 860, 26, 13); g.fill();
  const grad = g.createLinearGradient(290, 0, 1150, 0);
  grad.addColorStop(0, over ? '#ff9a9a' : '#5fb2ff'); grad.addColorStop(1, over ? '#d63c3c' : '#1d66c9');
  g.fillStyle = grad; rr(g, 290, 918, Math.max(26, 860 * meter), 26, 13); g.fill();
  if (over) { g.fillStyle = '#d63c3c'; g.font = `800 24px ${FONT}`; g.fillText('VƯỢT GIỚI HẠN', 1180, 932); }
  g.restore();
}

function radialTexture(inner: string, size = 256) {
  const c = document.createElement('canvas'); c.width = c.height = size;
  const g = c.getContext('2d')!; const r = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  r.addColorStop(0, inner); r.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = r; g.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

// onReady: gọi sau khung hình 3D đầu tiên, lúc đó mới ẩn thiết bị CSS (tránh khoảng trống nếu chưa kịp vẽ).
export function mountTablet3D(host: HTMLElement, initial: TabletState, onReady?: () => void): Tablet3D | null {
  const canvas = document.createElement('canvas');
  canvas.className = 'v4-gl';
  let renderer: THREE.WebGLRenderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' }); }
  catch { return null; }
  const gl = renderer.getContext();
  const dbg = gl.getExtension('WEBGL_debug_renderer_info');
  const gpu = String(dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
  if (/swiftshader|llvmpipe|software|basic render/i.test(gpu)) { renderer.dispose(); return null; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  host.appendChild(canvas);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = env;
  scene.add(new THREE.AmbientLight(0xffffff, 0.25));
  const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(3, 5, 6); scene.add(key);

  const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 100);
  const rig = new THREE.Group(); scene.add(rig);     // xoay theo cuộn
  const idle = new THREE.Group(); rig.add(idle);     // trôi nhẹ + nghiêng theo con trỏ

  const bodyMat = new THREE.MeshPhysicalMaterial({ color: 0x1b2633, metalness: 0.8, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.15, emissive: 0xd63c3c, emissiveIntensity: 0 });
  const body = new THREE.Mesh(new RoundedBoxGeometry(BW, BH, BD, 6, 0.17), bodyMat);
  const bezelMat = new THREE.MeshPhysicalMaterial({ color: 0x05080c, roughness: 0.1, metalness: 0, clearcoat: 1 });
  const bezel = new THREE.Mesh(new RoundedBoxGeometry(BW - 0.09, BH - 0.09, 0.012, 4, 0.006), bezelMat);
  bezel.position.z = BD / 2 + 0.002;
  const cam = new THREE.Mesh(new THREE.CircleGeometry(0.022, 20), new THREE.MeshBasicMaterial({ color: 0x1c2733 }));
  cam.position.set(0, BH / 2 - 0.1, BD / 2 + 0.009);

  const sc = document.createElement('canvas'); sc.width = CW; sc.height = CH;
  const g = sc.getContext('2d')!;
  const screenTex = new THREE.CanvasTexture(sc);
  screenTex.colorSpace = THREE.SRGBColorSpace;
  screenTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(SW, SH), new THREE.MeshBasicMaterial({ map: screenTex, transparent: true, toneMapped: false }));
  screen.position.z = BD / 2 + 0.0095;
  // Vệt phản chiếu chéo trên kính
  const gc = document.createElement('canvas'); gc.width = 512; gc.height = 346;
  const gg = gc.getContext('2d')!; const lg = gg.createLinearGradient(0, 0, 512, 346);
  lg.addColorStop(0, 'rgba(255,255,255,0.35)'); lg.addColorStop(0.32, 'rgba(255,255,255,0)'); lg.addColorStop(0.75, 'rgba(255,255,255,0)'); lg.addColorStop(1, 'rgba(255,255,255,0.12)');
  gg.fillStyle = lg; gg.fillRect(0, 0, 512, 346);
  const glareTex = new THREE.CanvasTexture(gc);
  const glare = new THREE.Mesh(new THREE.PlaneGeometry(SW, SH), new THREE.MeshBasicMaterial({ map: glareTex, transparent: true, depthWrite: false, toneMapped: false, opacity: 0.55 }));
  glare.position.z = BD / 2 + 0.011;
  idle.add(body, bezel, cam, screen, glare);

  // Bóng mềm dưới sàn (không xoay theo máy)
  const shadowTex = radialTexture('rgba(15,29,43,0.42)');
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(4.8, 1.25), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = -BH / 2 - 0.3;
  scene.add(shadow);

  let state = { ...initial };
  let drawn = '';
  const redraw = () => {
    const k = `${Math.round(state.docs * 24)}|${Math.round(state.meter * 300)}`;
    if (k === drawn) return;
    drawn = k; drawScreen(g, state.docs, state.meter); screenTex.needsUpdate = true;
  };
  document.fonts?.ready.then(() => { drawn = ''; request(); }).catch(() => undefined);

  const fit = () => {
    const w = host.clientWidth || 1, h = host.clientHeight || 1;
    canvas.style.width = ''; canvas.style.height = '';
    const cw = canvas.clientWidth || w, ch = canvas.clientHeight || h;
    renderer.setSize(cw, ch, false);
    camera.aspect = cw / ch;
    const t = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const dist = Math.max((BH * 1.55) / t, (BW * 1.32) / (t * camera.aspect));
    camera.position.set(0, 0.35, dist); camera.lookAt(0, -0.05, 0);
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(() => { fit(); request(); }); ro.observe(host); fit();

  // Con trỏ: nghiêng nhẹ về phía chuột (nội suy vài khung rồi dừng)
  let px = 0, py = 0;
  const onMove = (e: PointerEvent) => { px = e.clientX / window.innerWidth - 0.5; py = e.clientY / window.innerHeight - 0.5; request(); };
  window.addEventListener('pointermove', onMove, { passive: true });

  let visible = true, raf = 0;
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) request(); }, { threshold: 0 });
  io.observe(host);
  function request() { if (!raf && visible && !document.hidden) raf = requestAnimationFrame(frame); }
  // Tự kiểm: khi cuộn liên tục mà khung hình thường xuyên > 40 ms (< 25 fps) thì bỏ 3D, quay về thiết bị CSS.
  let lastTs = 0, slow = 0, seen = 0;
  function frame(ts: number) {
    raf = 0;
    const gap = ts - lastTs; lastTs = ts;
    if (gap > 0 && gap < 250) { seen++; if (gap > 40) slow++; }
    if (seen >= 40) { if (slow / seen > 0.5) { api.dispose(); host.classList.remove('is-3d'); return; } seen = slow = 0; }
    rig.rotation.y = THREE.MathUtils.degToRad(state.ry);
    rig.rotation.x = THREE.MathUtils.degToRad(state.rx);
    const dy = px * 0.16 - idle.rotation.y, dx = py * 0.1 - idle.rotation.x;
    idle.rotation.y += dy * 0.12; idle.rotation.x += dx * 0.12;
    bodyMat.emissiveIntensity = state.meter > 0.97 ? 0.22 : 0;
    redraw();
    renderer.render(scene, camera);
    if (onReady) { onReady(); onReady = undefined; }
    if (Math.abs(dy) > 0.0015 || Math.abs(dx) > 0.0015) request();
  }
  const onVis = () => request();
  document.addEventListener('visibilitychange', onVis);
  redraw(); request();

  const api: Tablet3D = {
    update(s) { state = { ...s }; request(); },
    dispose() {
      cancelAnimationFrame(raf); raf = 0; visible = false;
      ro.disconnect(); io.disconnect();
      window.removeEventListener('pointermove', onMove);
      document.removeEventListener('visibilitychange', onVis);
      scene.traverse(o => {
        const m = o as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
        const mat = m.material as THREE.Material | undefined;
        if (mat) mat.dispose();
      });
      [screenTex, glareTex, shadowTex, env].forEach(t => t.dispose());
      pmrem.dispose(); renderer.dispose(); canvas.remove();
    },
  };
  return api;
}
