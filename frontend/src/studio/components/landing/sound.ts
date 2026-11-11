// Âm thanh của landing, tổng hợp bằng Web Audio (không dùng file thu sẵn).
// Mặc định tắt; chỉ phát sau khi người dùng bấm nút loa (trình duyệt cũng chặn tự phát trước đó).
type Ctx = { ac: AudioContext; out: GainNode };
let ctx: Ctx | null = null;
let enabled = false;
let last: Record<string, number> = {};

const KEY = 'orchestriq-sound';
export const soundPref = () => { try { return localStorage.getItem(KEY) === 'on'; } catch { return false; } };

function audio(): Ctx | null {
  if (!enabled) return null;
  if (!ctx) {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return null;
    const ac = new AC();
    const comp = ac.createDynamicsCompressor();
    const out = ac.createGain(); out.gain.value = 0.5;
    out.connect(comp).connect(ac.destination);
    ctx = { ac, out };
    document.addEventListener('visibilitychange', () => { if (!ctx) return; document.hidden ? ctx.ac.suspend() : enabled && ctx.ac.resume(); });
  }
  if (ctx.ac.state === 'suspended') ctx.ac.resume();
  return ctx;
}

export function setSound(on: boolean) {
  enabled = on;
  try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch { /* Trình duyệt có thể chặn lưu tùy chọn. */ }
  if (!on) ctx?.ac.suspend();
}

// Tránh dồn âm khi cuộn nhanh: mỗi loại âm có khoảng nghỉ tối thiểu.
const gate = (name: string, ms: number) => { const now = performance.now(); if (now - (last[name] ?? 0) < ms) return false; last[name] = now; return true; };

function tone(c: Ctx, freq: number, at: number, dur: number, vol: number, type: OscillatorType = 'sine', glideTo?: number) {
  const o = c.ac.createOscillator(), g = c.ac.createGain();
  o.type = type; o.frequency.setValueAtTime(freq, at);
  if (glideTo) o.frequency.exponentialRampToValueAtTime(glideTo, at + dur);
  g.gain.setValueAtTime(0.0001, at);
  g.gain.exponentialRampToValueAtTime(vol, at + 0.012);
  g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  o.connect(g).connect(c.out); o.start(at); o.stop(at + dur + 0.05);
}

function noise(c: Ctx, at: number, dur: number, vol: number, filter: BiquadFilterType, f0: number, f1?: number, q = 0.8) {
  const len = Math.ceil(c.ac.sampleRate * dur), buf = c.ac.createBuffer(1, len, c.ac.sampleRate), d = buf.getChannelData(0);
  for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
  const src = c.ac.createBufferSource(), bq = c.ac.createBiquadFilter(), g = c.ac.createGain();
  src.buffer = buf; bq.type = filter; bq.Q.value = q;
  bq.frequency.setValueAtTime(f0, at); if (f1) bq.frequency.exponentialRampToValueAtTime(f1, at + dur);
  g.gain.setValueAtTime(0.0001, at); g.gain.exponentialRampToValueAtTime(vol, at + dur * 0.15); g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  src.connect(bq).connect(g).connect(c.out); src.start(at); src.stop(at + dur);
}

// Thang ngũ cung Đô trưởng: mọi nốt ghép với nhau đều êm tai.
const PENTA = [523.25, 587.33, 659.25, 783.99, 880, 1046.5, 1174.66, 1318.51];

export const sfx = {
  /** Bật âm: hai nốt đi lên. */
  on() { const c = audio(); if (!c) return; const t = c.ac.currentTime; tone(c, 659.25, t, 0.25, 0.12); tone(c, 987.77, t + 0.08, 0.35, 0.1); },
  /** Giấy rơi / lật: tiếng sột soạt ngắn, cao độ ngẫu nhiên để không lặp nhàm. */
  paper(count = 3) {
    const c = audio(); if (!c || !gate('paper', 260)) return; const t = c.ac.currentTime;
    for (let i = 0; i < count; i++) noise(c, t + i * 0.07 + Math.random() * 0.03, 0.12, 0.09, 'bandpass', 2400 + Math.random() * 2200, 1400, 1.2);
  },
  /** Quá tải: tiếng trầm "thịch" kèm rung nhẹ, không gắt. */
  overload() {
    const c = audio(); if (!c || !gate('overload', 900)) return; const t = c.ac.currentTime;
    tone(c, 110, t, 0.5, 0.22, 'sine', 70); tone(c, 116.5, t + 0.12, 0.45, 0.12, 'triangle', 74);
    noise(c, t, 0.35, 0.06, 'lowpass', 600, 200);
  },
  /** Tia quét: tiếng vút đi lên. */
  scan() { const c = audio(); if (!c || !gate('scan', 900)) return; const t = c.ac.currentTime; noise(c, t, 0.7, 0.07, 'bandpass', 500, 5000, 2.5); tone(c, 330, t, 0.7, 0.04, 'sine', 990); },
  /** Hoàn tất: hợp âm rải sáng, có tiếng ngân. */
  done() {
    const c = audio(); if (!c || !gate('done', 900)) return; const t = c.ac.currentTime;
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => { tone(c, f, t + i * 0.07, 1.1, 0.07); tone(c, f * 2, t + i * 0.07, 0.5, 0.015); });
  },
  /** Thẻ trượt lên: tiếng gió lướt mềm. */
  whoosh() { const c = audio(); if (!c || !gate('whoosh', 350)) return; noise(c, c.ac.currentTime, 0.45, 0.07, 'bandpass', 300, 1800, 1.4); },
  /** Mỗi bước trong tám bước: nốt cao dần theo thứ tự, như một giai điệu đi lên. */
  step(i: number) { const c = audio(); if (!c || !gate('step', 120)) return; const t = c.ac.currentTime; const f = PENTA[i % PENTA.length]; tone(c, f, t, 0.45, 0.09, 'triangle'); tone(c, f * 1.5, t + 0.02, 0.25, 0.025); },
  /** Cảnh tối mở ra: âm nền trầm phồng lên. */
  swell() {
    const c = audio(); if (!c || !gate('swell', 2000)) return; const t = c.ac.currentTime;
    [130.81, 196, 261.63].forEach((f, i) => { const o = c.ac.createOscillator(), g = c.ac.createGain(); o.type = 'sine'; o.frequency.value = f; g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.06 - i * 0.012, t + 0.9); g.gain.exponentialRampToValueAtTime(0.0001, t + 2.6); o.connect(g).connect(c.out); o.start(t); o.stop(t + 2.7); });
  },
  /** Sơ đồ nối: ba nốt "nối dây" đi lên rồi một nốt đích. */
  connect() {
    const c = audio(); if (!c || !gate('connect', 1500)) return; const t = c.ac.currentTime;
    [0, 2, 4].forEach((n, i) => tone(c, PENTA[n], t + i * 0.13, 0.22, 0.06, 'triangle'));
    tone(c, PENTA[5], t + 0.48, 0.7, 0.07); tone(c, PENTA[7], t + 0.5, 0.5, 0.02);
  },
  /** Nhiều thẻ cùng hiện: lấp lánh, mỗi thẻ một nốt cao ngẫu nhiên trong thang. */
  sparkle(n = 5) {
    const c = audio(); if (!c || !gate('sparkle', 1200)) return; const t = c.ac.currentTime;
    for (let i = 0; i < n; i++) { const f = PENTA[3 + Math.floor(Math.random() * 5)] * 2; tone(c, f, t + i * 0.09, 0.3, 0.025, 'sine'); }
  },
  /** Ô bento bật lên: tiếng "póp" tròn, cao dần theo thứ tự. */
  pops(n = 5) {
    const c = audio(); if (!c || !gate('pops', 1200)) return; const t = c.ac.currentTime;
    for (let i = 0; i < n; i++) tone(c, 380 + i * 70, t + i * 0.1, 0.12, 0.07, 'sine', 620 + i * 90);
  },
  /** Chữ hiện dần: vài tiếng gõ phím khẽ. */
  keys(n = 6) {
    const c = audio(); if (!c || !gate('keys', 1500)) return; const t = c.ac.currentTime;
    for (let i = 0; i < n; i++) noise(c, t + i * 0.085 + Math.random() * 0.03, 0.035, 0.05, 'highpass', 3000 + Math.random() * 1500);
  },
  /** Lời mời cuối trang: âm nền dâng lên rồi hợp âm sáng. */
  finale() {
    const c = audio(); if (!c || !gate('finale', 3000)) return; const t = c.ac.currentTime;
    noise(c, t, 0.9, 0.04, 'bandpass', 400, 3200, 1.6);
    [523.25, 783.99, 1046.5, 1567.98].forEach((f, i) => tone(c, f, t + 0.55 + i * 0.06, 1.4, 0.06 - i * 0.008));
  },
  /** Rê chuột qua nút/liên kết: tiếng chạm rất khẽ. */
  hover() { const c = audio(); if (!c || !gate('hover', 70)) return; tone(c, 2200 + Math.random() * 300, c.ac.currentTime, 0.04, 0.018, 'sine'); },
  /** Nhấp: mở hỏi đáp, chọn tab, bấm nút. */
  tick(open = true) { const c = audio(); if (!c || !gate('tick', 60)) return; const t = c.ac.currentTime; tone(c, open ? 1400 : 1000, t, 0.07, 0.07, 'triangle', open ? 1800 : 760); },
};
