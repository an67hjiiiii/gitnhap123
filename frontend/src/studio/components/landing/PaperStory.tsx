import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Database, Code2, Shield, FileText } from 'lucide-react';

// Cảnh "Chồng tài liệu" của landing. Mọi hình là minh họa cơ chế đã có trong mã, không phải số đo.
const TONES = ['db', 'api', 'sec'] as const;
const AGENT = { db: { Icon: Database, label: 'Dữ liệu' }, api: { Icon: Code2, label: 'API' }, sec: { Icon: Shield, label: 'Bảo mật' } };

export const PAPER_CHAPTERS: { tag: string; title: ReactNode; body: string }[] = [
  { tag: 'Thói quen', title: <>Ta tin câu trả lời của AI vì nó <i>trôi chảy</i>.</>, body: 'Dồn cả kho tài liệu vào một cửa sổ ngữ cảnh, mô hình vẫn viết ra một đoạn mạch lạc, đầy thuật ngữ.' },
  { tag: 'Rủi ro', title: <>Nhưng trôi chảy chưa chắc <i>có căn cứ</i>.</>, body: 'Phần trùng bị lặp, phần thừa chen vào, phần cần thiết rơi ra ngoài giới hạn ngữ cảnh. Không ai biết câu nào lấy từ đâu.' },
  { tag: 'Cách khác', title: <>OrchestrIQ chia tài liệu cho <i>đúng chuyên gia</i>.</>, body: 'Kế hoạch được kiểm tra trước khi giao việc. Mỗi tác tử chỉ nhận tài liệu của nhiệm vụ mình, với ngân sách token chia theo nhu cầu.' },
  { tag: 'Dấu vết', title: <>Mỗi kết quả giữ lại <i>sợi dây</i> về nguồn.</>, body: 'Kế hoạch, đoạn tài liệu đã cấp cho từng tác tử và mọi lần gọi mô hình đều được lưu để bạn tự kiểm tra.' },
];
// kind: tone của tài liệu; noise = không liên quan; shared = phần chung. Tên file là ví dụ.
type Kind = 'db' | 'api' | 'sec' | 'shared' | 'noise';
const NAMES: Record<Kind, string[]> = {
  db: ['luoc-do-giao-dich.sql', 'bang-payments.sql', 'khoa-idempotency.sql', 'chi-muc.sql'],
  api: ['dac-ta-thanh-toan.md', 'webhook-api.md'],
  sec: ['chinh-sach-bao-mat.md', 'phan-quyen-rbac.md', 'chu-ky-hmac.md', 'token-jwt.md'],
  shared: ['rang-buoc-chung.md', 'yeu-cau-goc.md'],
  noise: ['bien-ban-hop.pdf', 'ke-hoach-marketing.pdf', 'slide-gioi-thieu.pdf', 'faq-khach-hang.pdf'],
};
const KINDS: Kind[] = ['db', 'noise', 'api', 'shared', 'sec', 'db', 'noise', 'sec', 'shared', 'db', 'noise', 'sec', 'api', 'noise', 'sec', 'db'];
const seen: Partial<Record<Kind, number>> = {};
export const PAPERS = KINDS.map(kind => { const n = seen[kind] ?? 0; seen[kind] = n + 1; const name = NAMES[kind][n]; return { kind, name, ext: name.split('.').pop()!.toUpperCase() }; });

// Một câu trả lời xuyên suốt câu chuyện: chương 1 tự gõ ra, chương 2 bị gắn cờ không rõ nguồn,
// chương 4 hiện lại kèm tệp nguồn. Nội dung là ví dụ minh họa, không phải kết quả chạy thật.
const ANSWER = [
  { k: 'db', text: 'Lưu khóa chống lặp trong bảng giao dịch.', short: 'Khóa chống lặp giao dịch', src: 'luoc-do-giao-dich.sql' },
  { k: 'api', text: 'Endpoint trả lại kết quả cũ khi yêu cầu bị gửi lặp.', short: 'Trả kết quả cũ khi gửi lặp', src: 'dac-ta-thanh-toan.md' },
  { k: 'sec', text: 'Kiểm tra chữ ký HMAC trước khi nhận webhook.', short: 'Kiểm tra chữ ký HMAC', src: 'chinh-sach-bao-mat.md' },
] as const;
// Ba tài liệu được trích (chỉ số trong PAPERS) theo thứ tự câu trả lời: Dữ liệu, API, Bảo mật.
const CITED: Record<number, number> = { 0: 0, 2: 1, 4: 2 };

// Tiến độ chuyển nền sáng → tối, do timeline GSAP của trang điều khiển (0..1).
export const storyFx = { dark: 0 };

// Shader nền: vùng tối loang ra từ tờ kế hoạch như mực trong nước, mép loang phát sáng và gợn theo nhiễu.
const FRAG = `precision highp float;
uniform vec2 uRes; uniform vec2 uC; uniform float uP; uniform float uT;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h(i), h(i + vec2(1, 0)), f.x), mix(h(i + vec2(0, 1)), h(i + vec2(1, 1)), f.x), f.y); }
float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++){ v += a * n(p); p = p * 2.03 + 7.1; a *= 0.5; } return v; }
void main(){
  vec2 uv = gl_FragCoord.xy / uRes;
  vec2 p = (gl_FragCoord.xy - uC) / uRes.y;
  vec2 w = vec2(fbm(p * 1.6 + uT * 0.04), fbm(p * 1.6 - uT * 0.05 + 3.3));
  float e = length(p) - uP * 2.0 + (fbm(p * 2.4 + w * 1.4) - 0.5) * 0.55 + (n(p * 9.0 + uT * 0.3) - 0.5) * 0.05;
  float inside = smoothstep(0.012, -0.012, e);
  float rim = exp(-abs(e) * 30.0) * (1.0 - smoothstep(0.86, 1.0, uP));
  float spark = step(0.985, h(floor(gl_FragCoord.xy / 3.0) + floor(uT * 6.0))) * exp(-abs(e) * 12.0) * (1.0 - smoothstep(0.86, 1.0, uP));
  vec3 deep = mix(vec3(0.05, 0.30, 0.56), vec3(0.016, 0.055, 0.11), smoothstep(0.0, 1.0, length((uv - vec2(0.68, 0.52)) * vec2(1.5, 1.0))));
  deep += vec3(0.25, 0.6, 1.0) * 0.06 * smoothstep(0.55, 0.85, fbm(p * 3.0 + w + uT * 0.06));
  vec2 g = abs(fract(gl_FragCoord.xy / 56.0) - 0.5);
  deep += vec3(0.5, 0.8, 1.0) * 0.035 * step(0.48, max(g.x, g.y));
  vec3 col = deep + vec3(0.72, 0.92, 1.0) * (rim * 1.25 + spark);
  float a = clamp(max(inside, rim * 0.95 + spark), 0.0, 1.0);
  gl_FragColor = vec4(col * a, a);
}`;

function makeLiquid(gc: HTMLCanvasElement) {
  const gl = gc.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false });
  if (!gl) return null;
  const sh = (type: number, src: string) => { const o = gl.createShader(type)!; gl.shaderSource(o, src); gl.compileShader(o); return gl.getShaderParameter(o, gl.COMPILE_STATUS) ? o : null; };
  const vs = sh(gl.VERTEX_SHADER, 'attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }'), fs = sh(gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return null;
  const prog = gl.createProgram()!; gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'a'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const u = (k: string) => gl.getUniformLocation(prog, k);
  const uRes = u('uRes'), uC = u('uC'), uP = u('uP'), uT = u('uT');
  let blank = false;
  return (p: number, t: number, cx: number, cy: number) => {
    gl.viewport(0, 0, gc.width, gc.height);
    if (p <= 0.001) { if (!blank) { gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); blank = true; } return; }
    blank = false;
    gl.uniform2f(uRes, gc.width, gc.height); gl.uniform2f(uC, cx, gc.height - cy); gl.uniform1f(uP, p); gl.uniform1f(uT, t / 1000);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
}

// Hai lớp canvas cho cảnh câu chuyện: nền loang (WebGL) và lớp 2D vẽ sao, hạt chảy vào ba khay (chương 3),
// dây sáng nối từng câu trả lời với đoạn trích trong tài liệu nguồn (chương 4). Chỉ vẽ khi cảnh đang hiện.
export function StorySky() {
  const ref = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current, gc = glRef.current, ctx = cv?.getContext('2d'), sec = cv?.closest<HTMLElement>('.v4-paper');
    if (!cv || !gc || !ctx || !sec) return;
    const liquid = makeLiquid(gc);
    if (liquid) sec.classList.add('has-gl');
    let w = 0, h = 0, dpr = 1, raf = 0, on = false, tick = 0;
    const stars = Array.from({ length: 150 }, (_, i) => ({ x: ((i * 73) % 997) / 997, y: ((i * 151) % 991) / 991, r: 0.4 + ((i * 37) % 10) / 9, s: 0.3 + ((i * 17) % 10) / 12 }));
    const parts = Array.from({ length: 96 }, (_, i) => ({ t: (i * 0.137) % 1, k: i % 3, sp: 0.0028 + ((i * 29) % 10) / 3800, j: ((i * 41) % 21) - 10 }));
    const COL = ['90,162,255', '62,210,154', '255,122,122'];
    const size = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2); w = cv.clientWidth; h = cv.clientHeight;
      cv.width = w * dpr; cv.height = h * dpr;
      // Shader nền là nhiễu mềm: vẽ ở 1x là đủ nét, đỡ ~1,5 lần số điểm ảnh trên màn hình mật độ cao.
      const gd = Math.min(dpr, 1); gc.width = w * gd; gc.height = h * gd;
    };
    const frame = (time: number) => {
      raf = 0;
      const ch = Number(sec.dataset.ch || 0), dk = storyFx.dark;
      // Chữ đổi sang màu sáng ngay khi nền loang phủ quá nửa, không đợi sang chương mới.
      sec.classList.toggle('is-night', dk > 0.45);
      const b = cv.getBoundingClientRect();
      // Khi nền đã tối hẳn, phần bên trong chỉ gợn rất chậm: vẽ lại shader cách một khung hình là đủ mượt.
      if (liquid && (dk < 0.999 || (tick++ & 1) === 0)) {
        const st = sec.querySelector('.v4-paper-stage')?.getBoundingClientRect(), gd = gc.width / Math.max(w, 1);
        liquid(dk, time, st ? (st.left - b.left + st.width * 0.5) * gd : gc.width * 0.7, st ? (st.top - b.top + st.height * 0.24) * gd : gc.height * 0.3);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      if (dk > 0.02) for (const s of stars) {
        ctx.fillStyle = `rgba(190,225,255,${(dk * dk * (0.15 + 0.3 * (0.5 + 0.5 * Math.sin(time / 900 * s.s + s.x * 40)))).toFixed(3)})`;
        ctx.beginPath(); ctx.arc(s.x * w, (s.y * h + time * s.s * 0.006) % h, s.r, 0, 7); ctx.fill();
      }
      if (ch === 2) {
        const nr = sec.querySelector('.v4-note')?.getBoundingClientRect(), trays = [...sec.querySelectorAll('.v4-tray')].map(e => e.getBoundingClientRect());
        if (nr) {
          const nx = nr.left - b.left + nr.width / 2, ny = nr.top - b.top + nr.height / 2;
          for (const p of parts) {
            p.t = (p.t + p.sp) % 1;
            const tr = trays[p.k]; if (!tr) continue;
            const ex = tr.left - b.left + tr.width / 2 + p.j * 3, ey = tr.top - b.top + tr.height * 0.4, cx = (nx + ex) / 2, cy = Math.min(ny, ey) - 30, u = 1 - p.t;
            const x = u * u * nx + 2 * u * p.t * cx + p.t * p.t * ex, y = u * u * ny + 2 * u * p.t * cy + p.t * p.t * ey;
            ctx.fillStyle = `rgba(${COL[p.k]},${Math.sin(p.t * Math.PI).toFixed(2)})`;
            ctx.beginPath(); ctx.arc(x, y, 2.6, 0, 7); ctx.fill();
          }
        }
      }
      if (ch === 3) {
        // Chương 4: quả cầu lưới quanh bản tổng hợp, ba vệ tinh nguồn bay trên quỹ đạo, vòng nhật ký bên dưới.
        const rep = sec.querySelector<HTMLElement>('.v4-report'), stg = sec.querySelector<HTMLElement>('.v4-paper-stage'), orbs = [...sec.querySelectorAll<HTMLElement>('.v4-orb')];
        const fade = rep ? Number(getComputedStyle(rep).opacity) : 0;
        if (rep && stg && fade > 0.01) {
          const rr = rep.getBoundingClientRect(), sr = stg.getBoundingClientRect(), t = time / 1000;
          const cx = rr.left - b.left + rr.width / 2, cy = rr.top - b.top + rr.height / 2, R = Math.min(sr.width, sr.height) * 0.4;
          ctx.save(); ctx.globalAlpha = fade;
          const glow = ctx.createRadialGradient(cx, cy, R * 0.15, cx, cy, R * 1.3);
          glow.addColorStop(0, 'rgba(64,160,255,.26)'); glow.addColorStop(0.7, 'rgba(64,160,255,.07)'); glow.addColorStop(1, 'rgba(64,160,255,0)');
          ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(cx, cy, R * 1.3, 0, 7); ctx.fill();
          ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(127,211,255,.32)';
          ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.stroke();
          ctx.strokeStyle = 'rgba(127,211,255,.16)';
          for (let k = 0; k < 7; k++) { const ph = (k / 7) * Math.PI + t * 0.22; ctx.beginPath(); ctx.ellipse(cx, cy, Math.abs(Math.cos(ph)) * R, R, 0, 0, 7); ctx.stroke(); }
          for (let k = 1; k < 6; k++) { const la = (k / 6 - 0.5) * Math.PI, rx = Math.cos(la) * R; ctx.beginPath(); ctx.ellipse(cx, cy + Math.sin(la) * R, rx, rx * 0.2, 0, 0, 7); ctx.stroke(); }
          const ry = cy + R * 1.1, rx2 = R * 1.4, ry2 = R * 0.26;
          ctx.strokeStyle = 'rgba(127,211,255,.3)'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.ellipse(cx, ry, rx2, ry2, 0, 0, 7); ctx.stroke();
          ctx.lineWidth = 5; ctx.lineCap = 'butt';
          for (let k = 0; k < 28; k++) { const a0 = (k / 28) * Math.PI * 2 + t * 0.18; ctx.strokeStyle = `rgba(127,211,255,${Math.sin(a0) > 0 ? 0.55 : 0.18})`; ctx.beginPath(); ctx.ellipse(cx, ry, rx2, ry2, 0, a0, a0 + 0.09); ctx.stroke(); }
          const ORBIT = [[-0.34, 1.2, 0.34], [0.3, 1.32, 0.27], [0.05, 1.46, 0.21]];
          orbs.forEach((el, i) => {
            const [tilt, sc, sp] = ORBIT[i] ?? ORBIT[0];
            const orx = R * sc, ory = R * sc * 0.4, th = t * sp + i * 2.1;
            ctx.save(); ctx.translate(cx, cy); ctx.rotate(tilt);
            ctx.strokeStyle = `rgba(${COL[i]},.5)`; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.ellipse(0, 0, orx, ory, 0, 0, 7); ctx.stroke();
            ctx.restore();
            const ox = Math.cos(th) * orx, oy = Math.sin(th) * ory;
            const x = cx + ox * Math.cos(tilt) - oy * Math.sin(tilt), y = cy + ox * Math.sin(tilt) + oy * Math.cos(tilt), d = 0.5 + 0.5 * Math.sin(th);
            const g = ctx.createRadialGradient(x, y, 0, x, y, 26); g.addColorStop(0, `rgba(${COL[i]},.85)`); g.addColorStop(1, `rgba(${COL[i]},0)`);
            ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 26, 0, 7); ctx.fill();
            // Nửa dưới quỹ đạo ở phía trước bản tổng hợp, nửa trên ở phía sau.
            el.style.transform = `translate(${(x - (sr.left - b.left)).toFixed(1)}px,${(y - (sr.top - b.top)).toFixed(1)}px) translate(-50%,-50%) scale(${(0.84 + 0.16 * d).toFixed(3)})`;
            el.style.opacity = (fade * (0.5 + 0.5 * d)).toFixed(2);
            el.style.zIndex = d > 0.5 ? '4' : '1';
          });
          ctx.restore();
        } else orbs.forEach(el => { el.style.opacity = '0'; });
      }
      if (on) raf = requestAnimationFrame(frame);
    };
    size();
    const ro = new ResizeObserver(size); ro.observe(cv);
    const io = new IntersectionObserver(([e]) => { on = e.isIntersecting; if (on && !raf) raf = requestAnimationFrame(frame); });
    io.observe(sec);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); sec.classList.remove('has-gl'); };
  }, []);
  return <><canvas ref={glRef} className="v4-sky v4-liquid" aria-hidden="true"/><canvas ref={ref} className="v4-sky" aria-hidden="true"/></>;
}

export function PaperStage() {
  return <div className="v4-paper-stage" aria-hidden="true">
    <div className="v4-device-wrap">
      <div className="v4-device">
        <div className="v4-screen">
          <div className="v4-scr-bar"><i/><i/><i/><span>Cửa sổ ngữ cảnh · qwen3:4b</span></div>
          <div className="v4-scr-main">
            <div className="v4-scr-chat">
              <p className="v4-scr-user">Thiết kế luồng thanh toán không xử lý trùng, có kiểm soát quyền.</p>
              <div className="v4-scr-ai"><b>AI</b><span>{ANSWER.map(a => <em key={a.src} className="v4-ans-line">{a.text}<small className="v4-flag">Không rõ nguồn</small></em>)}</span></div>
            </div>
            <ul className="v4-scr-docs">{PAPERS.slice(0, 7).map(p => <li key={p.name} className={`is-${p.kind}`}><b>{p.ext}</b>{p.name}</li>)}</ul>
          </div>
          <div className="v4-meter"><span>Ngữ cảnh đã dùng</span><b><i/></b><em>Vượt giới hạn</em></div>
        </div>
        <div className="v4-glare"/>
      </div>
      <div className="v4-floor"/>
    </div>
    {/* Độ dài thanh ngân sách chỉ minh họa việc chia theo nhu cầu, không phải số đo. */}
    {TONES.map((t, i) => { const { Icon, label } = AGENT[t]; return <div key={t} className={`v4-tray is-${t}`}><span className="v4-tray-head"><Icon size={15}/>{label}</span><span className="v4-budget-label">Ngân sách token</span><b className="v4-budget"><i style={{ width: `${[62, 40, 82][i]}%` }}/></b></div>; })}
    <div className="v4-alert"><b>!</b>Không câu nào chỉ ra được nguồn</div>
    <div className="v4-note"><i/>Kế hoạch đã kiểm tra<small>3 nhiệm vụ · đủ nghĩa vụ</small></div>
    <div className="v4-report"><div className="v4-report-head"><FileText size={18}/><div><strong>Bản thiết kế tổng hợp</strong><span>Dữ liệu · API · Bảo mật</span></div><em>Đã đối chiếu</em></div>
      <ul>{ANSWER.map(a => <li key={a.src} className={`is-${a.k}`}>{a.short}</li>)}</ul></div>
    {ANSWER.map(a => { const { Icon, label } = AGENT[a.k]; return <span key={a.src} className={`v4-orb is-${a.k}`}><i><Icon size={14}/></i><span><b>{label}</b>{a.src}</span></span>; })}
    <p className="v4-ring-cap">Nhật ký lượt chạy · lưu cả lần lỗi</p>
    {PAPERS.map((p, i) => <div key={i} className={`v4-sheet is-${p.kind}${i in CITED ? ' is-cited' : ''}`}><b>{p.ext}</b><span>{p.name}</span></div>)}
  </div>;
}
