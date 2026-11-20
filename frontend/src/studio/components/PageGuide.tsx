// Robot C27 đi theo người dùng qua từng trang (không cần bấm). Trang gốc là Không gian làm việc, nơi robot đứng to ở đầu trang.
//   - Bấm sang trang nằm DƯỚI trên thanh bên: robot thu nhỏ, rơi xuống khỏi màn hình rồi rơi từ trên vào trang mới và đáp
//     xuống chỗ trống; trang mới trượt lên cùng lúc (StudioMotion), như máy quay đi xuống theo robot.
//   - Bấm trang nằm TRÊN: ngược lại, robot bật lên khỏi màn hình rồi bật từ dưới lên vào trang mới.
//   - Bấm lại Không gian làm việc: robot bật lên về đúng chỗ cũ và phóng to bằng robot của trang gốc, rồi trao lại cho robot đó.
// Chỗ đáp là chỗ trống không che thẻ, nút hay chữ; bong bóng suy nghĩ tự hiện một câu ngắn nói trang này để làm gì.
// Khi dữ liệu tải xong, mở kết quả hay cuộn trang làm robot che nội dung, robot tự nhảy sang chỗ trống khác.
// Khi tắt chuyển động robot đứng thẳng ở chỗ trống, không nhảy.
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import gsap from 'gsap';
import { AssistantRobot } from './robot/AssistantRobot';
import { NavigationTab } from '../types';
import { motionAllowed } from '../utils/motion';
import { navDirection } from '../utils/navOrder';

const SAY: Partial<Record<NavigationTab, string>> = {
  overview: 'Xem nhanh hệ thống đang chạy tốt tới đâu.',
  documents: 'Đọc hiểu một tài liệu chỉ trong vài phút.',
  toolkit: 'Chọn kỹ năng theo ngành, mở là chạy trên tài liệu của bạn.',
  compare: 'Chọn bản cũ và bản mới, mình chỉ ra Điều nào đổi.',
  library: 'Tài liệu của bạn: tải lên, phân loại, mở hồ sơ.',
  results: 'Mở lại kết quả đã lưu và việc cần xem xét.',
  consistency: 'Tìm chỗ các tài liệu đang nói ngược nhau.',
  evaluation: 'So A, B, C trên cùng một bộ câu hỏi.',
  benchmarks: 'Đặt ba cách trả lời cạnh nhau để so.',
  rating: 'Nhờ người khác chấm mù các câu trả lời.',
  users: 'Cấp, khóa tài khoản và phân quyền nhân viên.',
  organization: 'Tạo tổ chức (công ty, trường, bệnh viện, nhóm), mời đồng nghiệp, phân cấp và đặt mức mật tài liệu.',
  db_explorer: 'Xem dữ liệu và sức khỏe của hệ thống.',
};

const HOME: NavigationTab = 'orchestration';
const HOME_BOT = '.st-main .ws-bot';   // robot to ở đầu trang Không gian làm việc
// cỡ robot (px): 64 trên máy tính, 40 trên điện thoại (vừa thanh trên cùng).
// shortcut: biến dùng chung cả mô-đun, đặt lại mỗi lần vẽ; nếu có hai robot cùng lúc thì chuyển thành tham số.
let BOT = 64;
const BUBBLE = { w: 236, h: 66 }; // cỡ ước lượng của bong bóng
const SAY_MS = 5200;              // bong bóng hiện bao lâu
const CELL = 20;                  // độ mịn của bản đồ chỗ trống (px)
const ROBOT_COLORS = { shell: '#1d344a', trim: '#d5dde6', screen: '#8fdcff' }; // hằng số: object mới mỗi lần vẽ sẽ làm robot khởi động lại vòng vẽ
// thẻ luôn tính là nội dung; ngoài ra khối nào có nền, viền, đổ bóng hay chữ trực tiếp cũng tính
const SOLID = 'button,a,input,select,textarea,h1,h2,h3,h4,p,li,label,table,img,svg,canvas,summary';
const CONTROL = 'button,a[href],input,select,textarea,[role="button"]';
type Pt = { x: number; y: number };
type Side = 'left' | 'right';
type Vert = 'up' | 'down' | 'mid';
type Spot = Pt & { side: Side; vert: Vert };
type Box = { x: number; y: number; w: number; h: number };

/** Khung bong bóng khi robot đứng ở (x,y): phía trên, phía dưới, hoặc ngang hàng bên cạnh robot (`mid`). */
function bubbleRect(x: number, y: number, side: Side, vert: Vert): Box {
  if (vert === 'mid') return { x: side === 'left' ? x - 22 - BUBBLE.w : x + BOT + 22, y: y + BOT / 2 - BUBBLE.h / 2, w: BUBBLE.w, h: BUBBLE.h };
  return { x: side === 'left' ? x + BOT * 0.4 - BUBBLE.w : x + BOT * 0.6, y: vert === 'up' ? y - BUBBLE.h - 14 : y + BOT + 14, w: BUBBLE.w, h: BUBBLE.h };
}

/** Khối có tự vẽ ra thứ gì không (nền, viền, bóng, chữ trực tiếp) hay chỉ là khung trong suốt bao các khối khác. */
function paints(n: Element): boolean {
  if (n.matches(SOLID)) return true;
  if (n.classList.contains('st-topbar')) return false; // nền thanh trên cùng (điện thoại): chỗ trống bên phải được dùng
  const cs = getComputedStyle(n);
  if (cs.visibility === 'hidden' || cs.display === 'none') return false;
  if (!/(transparent|,\s*0\))$/.test(cs.backgroundColor) || cs.backgroundImage !== 'none' || cs.boxShadow !== 'none'
    || parseFloat(cs.borderTopWidth) + parseFloat(cs.borderLeftWidth) > 0) return true;
  return [...n.childNodes].some(t => t.nodeType === 3 && !!t.textContent?.trim());
}

/** Bản đồ "chỗ nào có nội dung" của vùng trang, trả về hàm đếm số ô bị che.
 *  Đi theo cây DOM và tô khung của từng khối có vẽ ra thứ gì (không đi vào bên trong khối đó), bỏ qua phần nằm ngoài màn hình
 *  hay ngoài khung cuộn. Cho cùng kết quả với cách dò từng điểm bằng elementFromPoint nhưng nhanh hơn nhiều lần
 *  (cách cũ ~2.600 lần dò mỗi lượt, chiếm 110-150 ms ngay lúc chuyển trang). */
function scan() {
  const host = document.querySelector('.st-main');
  if (!host) return null;
  // vùng trang không gồm thanh trên cùng (khung mới 20/11): robot không đậu đè lên tên trang và các nút
  const r0 = host.getBoundingClientRect();
  const tb = host.querySelector('.st-topbar')?.getBoundingClientRect();
  const top = tb && window.innerWidth >= 640 ? Math.max(r0.top, tb.bottom + 6) : r0.top;
  const main = { left: r0.left, right: r0.right, width: r0.width, top, bottom: r0.bottom };
  const bottom = Math.min(main.bottom, window.innerHeight);
  const cols = Math.max(1, Math.ceil(main.width / CELL));
  const rows = Math.max(1, Math.ceil((bottom - main.top) / CELL));
  const grid = new Uint8Array(rows * cols);
  // tô các ô có tâm nằm trong khung
  // v: trọng số ô (chữ, khung = 1; nút, ô nhập = 10) để khi buộc phải che thì robot che chữ chứ không che nút
  const paint = (x0: number, y0: number, x1: number, y1: number, v = 1) => {
    const c0 = Math.max(0, Math.ceil((x0 - main.left) / CELL - 0.5)), c1 = Math.min(cols - 1, Math.floor((x1 - main.left) / CELL - 0.5));
    const r0 = Math.max(0, Math.ceil((y0 - main.top) / CELL - 0.5)), r1 = Math.min(rows - 1, Math.floor((y1 - main.top) / CELL - 0.5));
    for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) if (grid[r * cols + c] < v) grid[r * cols + c] = v;
  };
  type Clip = { l: number; t: number; r: number; b: number };
  // trang mới đang trượt vào (StudioMotion dịch dọc vài chục px): trừ phần dịch đó để đo đúng vị trí trang khi dừng hẳn
  const view = host.querySelector(':scope > .pg, :scope > .mn, :scope > .st-legacy');
  const tf = view ? getComputedStyle(view).transform : 'none';
  const viewDy = tf && tf !== 'none' ? new DOMMatrixReadOnly(tf).m42 : 0;
  const walk = (el: Element, clip: Clip, dy: number) => {
    for (const child of el.children) {
      if (child.classList.contains('pgd')) continue;
      const d = child === view ? viewDy : dy;
      const rc = child.getBoundingClientRect();
      const top = rc.top - d, bot = rc.bottom - d;
      const l = Math.max(rc.left, clip.l), t = Math.max(top, clip.t), r = Math.min(rc.right, clip.r), b = Math.min(bot, clip.b);
      if (rc.width && rc.height && (l >= r || t >= b)) continue; // nằm ngoài vùng nhìn thấy
      if (rc.width && rc.height && paints(child)) {
        // nút, liên kết, ô nhập: nới nửa ô mỗi phía để robot không chồng lên mép (ô chỉ tính theo tâm)
        const ctl = child.matches(CONTROL);
        const pad = ctl ? CELL / 2 : 0;
        paint(l - pad, t - pad, r + pad, b + pad, ctl ? 10 : 1);
        // thẻ có nền chứa nút/ô nhập: tô cả các điều khiển bên trong với trọng số cao (không đi vào thẻ thì bỏ sót chúng)
        if (!ctl) for (const inner of child.querySelectorAll(CONTROL)) {
          const ir = inner.getBoundingClientRect();
          if (ir.width && ir.height) paint(ir.left - CELL / 2, ir.top - d - CELL / 2, ir.right + CELL / 2, ir.bottom - d + CELL / 2, 10);
        }
        continue;
      }
      const ov = rc.width && rc.height ? getComputedStyle(child).overflow : 'visible';
      walk(child, ov === 'visible' ? clip : { l, t, r, b }, d);
    }
  };
  walk(host, { l: main.left, t: main.top, r: main.right, b: bottom }, 0);
  // bảng cộng dồn 2 chiều: đếm số ô có nội dung trong một khung bất kỳ chỉ với 4 phép tra
  const W = cols + 1;
  const S = new Int32Array((rows + 1) * W);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++)
    S[(r + 1) * W + c + 1] = grid[r * cols + c] + S[r * W + c + 1] + S[(r + 1) * W + c] - S[r * W + c];
  const cc = (v: number) => Math.min(cols, Math.max(0, v));
  const cr = (v: number) => Math.min(rows, Math.max(0, v));
  const area = (bx: Box) => {
    // chỉ tính các ô có tâm nằm trong khung (làm tròn), tránh nới khung rộng thêm gần một ô mỗi phía
    const c0 = cc(Math.round((bx.x - main.left) / CELL)), c1 = cc(Math.round((bx.x + bx.w - main.left) / CELL));
    const r0 = cr(Math.round((bx.y - main.top) / CELL)), r1 = cr(Math.round((bx.y + bx.h - main.top) / CELL));
    return S[r1 * W + c1] - S[r0 * W + c1] - S[r1 * W + c0] + S[r0 * W + c0];
  };
  // cả khung robot (khung nhận cú bấm, kể cả góc trong suốt) để không chặn góc nút bên cạnh
  const robot = (s: Spot) => area({ x: s.x, y: s.y, w: BOT, h: BOT });
  const cost = (s: Spot) => robot(s) + area(bubbleRect(s.x, s.y, s.side, s.vert));
  // không có chỗ trống hoàn toàn (màn hình hẹp): robot đứng lâu nên tránh che là chính, bong bóng chỉ hiện vài giây
  // mỗi ô robot che phạt 5000 (> ngưỡng 2000 của recheck) để che dù một ô nút cũng làm robot dời đi
  const rank = (s: Spot) => { const all = cost(s); return all === 0 ? 0 : 100000 + robot(s) * 5000 + (all - robot(s)) * 20; };
  if (import.meta.env.DEV) dbgGrid = { grid, cols, rows };
  return { main, bottom, cost, rank };
}
// chỉ khi chạy dev: bài kiểm thử đọc bản đồ chỗ trống (# = có nội dung)
let dbgGrid: { grid: Uint8Array; cols: number; rows: number } | null = null;
if (import.meta.env.DEV && typeof window !== 'undefined') {
  (window as unknown as { __pgdMap?: () => string }).__pgdMap = () => {
    const pgd = document.querySelector<HTMLElement>('.pgd');
    if (pgd) pgd.style.display = 'none';
    scan();
    if (pgd) pgd.style.display = '';
    if (!dbgGrid) return '';
    const { grid, cols, rows } = dbgGrid;
    return Array.from({ length: rows }, (_, r) => Array.from(grid.subarray(r * cols, r * cols + cols), v => (v ? '#' : '.')).join('')).join('\n');
  };
}
type ScanMap = NonNullable<ReturnType<typeof scan>>;

/** Tìm chỗ trống trong vùng trang: không che gì (hoặc che ít nhất), rồi ưu tiên gần mép phải. */
function findSpot({ main, bottom, rank }: ScanMap): Spot & { score: number } {
  let best: Spot & { score: number } = { x: main.right - BOT - 24, y: bottom - BOT - 24, side: 'left', vert: 'up', score: Infinity };
  for (let y = main.top + 10; y <= bottom - BOT - 10; y += CELL) {
    for (let x = main.left + 10; x <= main.right - BOT - 10; x += CELL) {
      const side: Side = x + BOT / 2 > main.left + main.width / 2 ? 'left' : 'right';
      for (const vert of ['mid', 'up', 'down'] as Vert[]) {
        const r = bubbleRect(x, y, side, vert);
        if (r.x < main.left + 8 || r.x + r.w > main.right - 8 || r.y < main.top + 6 || r.y + r.h > bottom - 6) continue;
        const s = { x, y, side, vert };
        const score = rank(s) + (main.right - x) * 0.3 + (bottom - y) * 0.05;
        if (score < best.score) best = { ...s, score };
      }
    }
  }
  return best;
}

/** Điện thoại: trang kín hết chiều ngang nên robot đậu cố định ở đầu phải thanh trên cùng; bong bóng hiện bên dưới vài giây rồi ẩn. */
function dockSpot(): Spot | null {
  if (window.innerWidth >= 640) {
    // máy tính (20/11): đứng cố định góc dưới phải vùng trang như trợ lý nổi; tìm chỗ trống giữa nội dung hay đậu chồng
    // lên nút ở đầu trang. Bong bóng hiện ngang bên trái robot.
    const host = document.querySelector('.st-main')?.getBoundingClientRect();
    if (!host) return null;
    return { x: host.right - BOT - 18, y: Math.min(host.bottom, window.innerHeight) - BOT - 18, side: 'left', vert: 'mid' };
  }
  const bar = document.querySelector('.st-topbar')?.getBoundingClientRect();
  if (!bar || !bar.height) return null;
  // đậu ngay bên trái cụm nút (không che ảnh đại diện); CSS chừa sẵn chỗ ở cuối tên trang
  const acts = document.querySelector('.st-topbar .tb-actions')?.getBoundingClientRect();
  return { x: (acts?.left ?? bar.right) - BOT - 4, y: bar.top + (bar.height - BOT) / 2, side: 'left', vert: 'down' };
}

/** Vị trí và cỡ của robot to ở trang gốc (đo lúc trang gốc còn hiện). */
type Home = Pt & { s: number };
function homeRect(): Home | null {
  const r = document.querySelector(HOME_BOT)?.getBoundingClientRect();
  return r && r.width ? { x: r.left, y: r.top, s: r.width / BOT } : null;
}

function useTyping(text: string, run: boolean) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    if (!run) return;
    const id = window.setInterval(() => setN(v => { if (v + 2 >= text.length) { window.clearInterval(id); return text.length; } return v + 2; }), 28);
    return () => window.clearInterval(id);
  }, [text, run]);
  return text.slice(0, n);
}

export function PageGuide({ page }: { page: NavigationTab }) {
  BOT = typeof window !== 'undefined' && window.innerWidth < 640 ? 40 : 64;
  const say = SAY[page];
  const wrap = useRef<HTMLDivElement>(null);
  const pos = useRef<Pt | null>(null);
  const prevPage = useRef<NavigationTab | null>(null);
  const home = useRef<Home | null>(null);
  const [side, setSide] = useState<Side>('left');
  const [vert, setVert] = useState<Vert>('up');
  const [talk, setTalk] = useState(false);
  const [moving, setMoving] = useState(false);
  const timer = useRef(0);
  const typed = useTyping(say ?? '', talk);

  const speak = () => { window.clearTimeout(timer.current); setTalk(true); timer.current = window.setTimeout(() => setTalk(false), SAY_MS); };

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const from = prevPage.current;
    prevPage.current = page;
    window.clearTimeout(timer.current);
    setTalk(false);
    let ctx: gsap.Context | null = null;
    let cur: Spot | null = null;
    let busy = true; // đang nhảy thì không dò lại
    const cleanups: (() => void)[] = [];
    const host = document.querySelector('.st-main');
    const root = document.documentElement;
    const motion = motionAllowed();
    // chụp bản đồ lúc robot tạm gỡ khỏi trang (display:none; visibility không đủ vì bên trong robot tự đặt visible)
    const look = () => { el.style.display = 'none'; const m = scan(); el.style.display = ''; return m; };
    const place = (s: Spot) => { cur = s; setSide(s.side); setVert(s.vert); pos.current = { x: s.x, y: s.y }; };
    const squash = (bot: Element | null, at: number, tl: gsap.core.Timeline) => tl
      .to(bot, { scaleY: 0.78, scaleX: 1.16, duration: 0.07, transformOrigin: '50% 100%' }, at)
      .to(bot, { scaleY: 1, scaleX: 1, duration: 0.32, ease: 'elastic.out(1.2,0.4)' }, at + 0.07);

    // ---------------- Trở về trang gốc: bật lên về chỗ cũ, phóng to bằng robot của trang gốc rồi trao lại
    if (page === HOME) {
      const target = homeRect();
      // ghi lại vị trí robot trang gốc ngay trước khi người dùng rời trang (nhấn chuột / phím) để lần sau xuất phát đúng chỗ
      const remember = () => { const h = homeRect(); if (h) home.current = h; };
      remember();
      document.addEventListener('pointerdown', remember, true);
      document.addEventListener('keydown', remember, true);
      cleanups.push(() => { document.removeEventListener('pointerdown', remember, true); document.removeEventListener('keydown', remember, true); });
      if (!from || !target || !pos.current || !motion) {
        gsap.set(el, { opacity: 0 });
        root.removeAttribute('data-bot-flying');
        return () => cleanups.forEach(f => f());
      }
      root.setAttribute('data-bot-flying', '');  // ẩn robot trang gốc trong lúc robot nhỏ bay về
      setMoving(true);
      const start = pos.current;
      ctx = gsap.context(() => {
        const bot = el.querySelector('.pgd-bot');
        const tl = gsap.timeline({
          onComplete: () => { root.removeAttribute('data-bot-flying'); gsap.set(el, { opacity: 0 }); setMoving(false); },
        });
        gsap.set(el, { x: start.x, y: start.y, scale: 1, opacity: 1, transformOrigin: '0 0' });
        // bật lên khỏi mép trên
        // cùng nhịp với các trang khác: rời màn hình trong ~0,2 giây, về đúng chỗ cũ ở ~0,52 giây khi trang gốc vừa trượt xong
        tl.to(bot, { scaleY: 0.84, scaleX: 1.1, duration: 0.05, transformOrigin: '50% 100%' }, 0)
          .to(bot, { scaleY: 1.12, scaleX: 0.92, duration: 0.08 }, 0.05)
          .to(el, { y: -BOT * 1.5, duration: 0.15, ease: 'power2.in' }, 0.05)
          // từ dưới bật lên đúng chỗ cũ, lớn dần bằng robot trang gốc
          .set(el, { x: target.x, y: window.innerHeight + 12, scale: Math.max(1, target.s * 0.7) }, 0.2)
          .to(el, { y: target.y, scale: target.s, duration: 0.32, ease: 'power3.out' }, 0.2)
          .to(bot, { scaleY: 1, scaleX: 1, duration: 0.24, ease: 'power2.out' }, 0.2);
      }, el);
      return () => {
        cleanups.forEach(f => f());
        ctx?.kill(); // kill thay revert: giữ bộ nhớ đệm transform của GSAP, lần sau khỏi đọc lại kiểu CSS (buộc tính lại kiểu cả trang)
        root.removeAttribute('data-bot-flying');
        gsap.set(el, { opacity: 0 });
        setMoving(false);
      };
    }

    // ---------------- Sang một trang công cụ: rời chỗ cũ theo hướng, vào trang mới từ phía ngược lại, đáp xuống chỗ trống
    const dir = navDirection(from, page);
    // chỗ xuất phát: robot to ở trang gốc (vừa ghi lại) nếu đi từ trang gốc, không thì chỗ robot đang đứng
    const leavingHome = from === HOME && home.current;
    const startPt: Home = leavingHome ? home.current! : pos.current ? { ...pos.current, s: 1 } : { x: window.innerWidth - BOT - 24, y: -BOT * 2, s: 1 };
    // chỗ đáp được chọn lúc robot bắt đầu vào trang mới (sau khi rời màn hình ~0,3-0,4 giây), không phải ngay lúc bấm:
    // khi đó trang mới đã dựng xong nội dung (React bổ sung qua effect và dữ liệu tải về), nên đáp một lần là đúng chỗ
    const pick = () => { const m = look(); const s = dockSpot() ?? (m ? findSpot(m) : null); if (s) place(s); return s; };
    // trang còn biểu tượng đang tải (.spin) thì robot chờ ngoài màn hình tới khi tải xong (tối đa 0,9 giây) rồi mới vào
    let waitId = 0;
    const whenReady = (go: () => void, t0 = performance.now()) => {
      if (document.querySelector('.st-main > :not(.pgd) .spin') && performance.now() - t0 < 900) waitId = window.setTimeout(() => whenReady(go, t0), 80);
      else go();
    };
    cleanups.push(() => window.clearTimeout(waitId));

    // nội dung trang đổi (dữ liệu tải xong, mở kết quả, cuộn): nếu robot hay bong bóng đang che thì nhảy sang chỗ trống
    const hop = (a: Pt, b: Pt, dur: number, lift: number) => {
      const bot = el.querySelector('.pgd-bot');
      return gsap.timeline()
        .to(el, { x: b.x, duration: dur, ease: 'power1.inOut' }, 0)
        .to(el, { y: Math.min(a.y, b.y) - lift, duration: dur * 0.5, ease: 'power2.out' }, 0)
        .to(el, { y: b.y, duration: dur * 0.5, ease: 'power2.in' }, dur * 0.5)
        .to(bot, { rotate: b.x >= a.x ? 12 : -12, duration: dur * 0.5 }, 0)
        .to(bot, { rotate: 0, duration: dur * 0.5 }, dur * 0.5)
        .to(bot, { scaleY: 0.8, scaleX: 1.15, duration: 0.07, transformOrigin: '50% 100%' }, dur)
        .to(bot, { scaleY: 1, scaleX: 1, duration: 0.3, ease: 'elastic.out(1.2,0.4)' }, dur + 0.07);
    };
    let idle = 0;
    const recheck = () => {
      if (busy || !cur || dockSpot()) return;
      const m = look();
      if (!m || m.cost(cur) === 0) return;
      const best = findSpot(m);
      if (best.score >= m.rank(cur) - 2000) return;
      const a = pos.current ?? best;
      place(best);
      if (!motion || !ctx) { gsap.set(el, { x: best.x, y: best.y }); return; }
      busy = true;
      ctx.add(() => { hop(a, best, 0.45, 50).eventCallback('onComplete', () => { busy = false; }); });
    };
    const later = () => { window.clearTimeout(idle); idle = window.setTimeout(recheck, 300); };
    const mo = new MutationObserver(list => {
      if (list.some(m => !(m.target instanceof Element ? m.target : m.target.parentElement)?.closest('.pgd'))) later();
    });
    const watch = () => {
      busy = false;
      if (host) mo.observe(host, { childList: true, subtree: true });
      document.addEventListener('scroll', later, true);
      window.addEventListener('resize', later);
      later();
    };
    cleanups.push(() => {
      window.clearTimeout(idle);
      mo.disconnect();
      document.removeEventListener('scroll', later, true);
      window.removeEventListener('resize', later);
    });

    if (!motion) {
      const spot = pick();
      if (spot) gsap.set(el, { x: spot.x, y: spot.y, scale: 1, opacity: 1 });
      speak(); watch();
      return () => cleanups.forEach(f => f());
    }

    setMoving(true);
    ctx = gsap.context(() => {
      const bot = el.querySelector('.pgd-bot');
      const H = window.innerHeight;
      const down = dir === 'down';
      gsap.set(el, { x: startPt.x, y: startPt.y, scale: startPt.s, opacity: 1, transformOrigin: '0 0' });
      gsap.set(bot, { rotate: 0, scaleX: 1, scaleY: 1 });
      const tl = gsap.timeline();
      const done = () => { setMoving(false); speak(); watch(); };
      // Nhịp khớp với trang mới trượt vào (0,42 giây, StudioMotion): robot rời màn hình trong ~0,2 giây trong lúc trang
      // bắt đầu trượt, rồi vào trang mới và đáp ở ~0,5 giây, đúng lúc trang vừa dừng; khi rơi kéo dài thân, chạm đất thì nhún.
      const enterAt = 0.2;
      if (down) {
        // nhún rồi rơi thẳng xuống khỏi mép dưới (thu nhỏ về cỡ thường nếu đang to ở trang gốc)
        tl.to(bot, { scaleY: 0.86, scaleX: 1.08, duration: 0.05, transformOrigin: '50% 100%' }, 0)
          .to(bot, { scaleY: 1.12, scaleX: 0.92, duration: 0.08 }, 0.05)
          .to(el, { y: H + 12, scale: 1, duration: enterAt - 0.05, ease: 'power2.in' }, 0.05)
          // rơi từ mép trên của trang mới xuống chỗ trống, nhún khi chạm đất
          .call(() => whenReady(() => {
            const spot = pick();
            if (!spot) { done(); return; }
            ctx?.add(() => {
              const enter = gsap.timeline({ onComplete: done })
                .set(el, { x: spot.x, y: -BOT * 1.3 }, 0)
                .to(el, { y: spot.y, duration: 0.3, ease: 'power2.in' }, 0)
                .to(bot, { scaleY: 1, scaleX: 1, duration: 0.12 }, 0.18);
              squash(bot, 0.3, enter);
            });
          }), [], enterAt);
      } else {
        // nhún rồi bật thẳng lên khỏi mép trên
        tl.to(bot, { scaleY: 0.84, scaleX: 1.1, duration: 0.05, transformOrigin: '50% 100%' }, 0)
          .to(bot, { scaleY: 1.12, scaleX: 0.92, duration: 0.08 }, 0.05)
          .to(el, { y: -BOT * 1.5, scale: 1, duration: enterAt - 0.05, ease: 'power2.in' }, 0.05)
          // bật từ mép dưới của trang mới lên chỗ trống, chậm dần như ở đỉnh cú nhảy rồi đáp nhẹ
          .call(() => whenReady(() => {
            const spot = pick();
            if (!spot) { done(); return; }
            ctx?.add(() => {
              const enter = gsap.timeline({ onComplete: done })
                .set(el, { x: spot.x, y: H + 12 }, 0)
                .to(el, { y: spot.y - 12, duration: 0.26, ease: 'power3.out' }, 0)
                .to(bot, { scaleY: 1, scaleX: 1, duration: 0.18 }, 0.02)
                .to(el, { y: spot.y, duration: 0.09, ease: 'power2.in' }, 0.26);
              squash(bot, 0.35, enter);
            });
          }), [], enterAt);
      }
    }, el);
    return () => {
      cleanups.forEach(f => f());
      ctx?.kill(); // xem ghi chú ở trên
      if (pos.current) gsap.set(el, { x: pos.current.x, y: pos.current.y, scale: 1, opacity: 1 });
      setMoving(false);
    };
  }, [page, say]);

  useEffect(() => () => { window.clearTimeout(timer.current); document.documentElement.removeAttribute('data-bot-flying'); }, []);

  return (
    <div className={`pgd is-${side} is-${vert}${moving ? ' is-moving' : ''}${page === HOME ? ' is-home' : ''}`} ref={wrap} style={{ width: BOT, height: BOT }}>
      {talk && say && <div className="pgd-say" role="status" aria-live="polite">
        <span>{typed}</span>
        <i className="pgd-tail is-1" aria-hidden="true" /><i className="pgd-tail is-2" aria-hidden="true" />
      </div>}
      <button type="button" className="pgd-bot" onClick={() => (talk ? setTalk(false) : speak())} aria-label={say ? `C27: ${say}` : 'Trợ lý C27'} title={say} tabIndex={page === HOME ? -1 : 0} aria-hidden={page === HOME}>
        {/* ở trang gốc robot nhỏ ẩn đi (robot to của trang gốc thay chỗ): ngừng vẽ canvas để đỡ tốn khung hình, chỉ vẽ khi đang bay */}
        {(page !== HOME || moving) && <AssistantRobot size={BOT} interactive={false} state={talk ? 'speaking' : moving ? 'happy' : 'idle'} colorConfig={ROBOT_COLORS} />}
      </button>
    </div>
  );
}
