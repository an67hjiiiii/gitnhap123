// Đợt 4 (23/11): bảng văn phòng gắn bên phải ô chat, thay lớp phủ toàn màn hình.
// Một WebGL cho ô chat: dựng lần đầu khi mở, sau đó giữ sống (ẩn khi thu gọn/đóng) để mở lại tức thì.
// File này nhẹ; three.js chỉ tải khi bảng mở lần đầu (React.lazy). Điện thoại: tấm trượt từ dưới lên.
import { lazy, Suspense, useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Bot, ChevronRight, X } from 'lucide-react';
import type { LiveEvent, LiveState } from './liveDirector';

const OfficeView = lazy(() => import('./OfficeView'));

/** seek: chỉ số sự kiện (trong danh sách có stage) để tua tới, từ dòng thời gian trong câu trả lời. */
export type OfficeSource = { kind: 'live' } | { kind: 'replay'; question: string; events: LiveEvent[]; seek?: number };
export type OfficeMode = 'open' | 'collapsed' | 'closed';

// v2 (23/11): bề rộng mặc định đổi từ 460 px sang 42% cửa sổ; khóa mới để lựa chọn cũ 460 px không giữ bảng hẹp
const PREF_KEY = 'c27.officePanel.v2';
const MIN_W = 320;
const defaultW = () => Math.max(420, Math.round(window.innerWidth * 0.42));
const maxW = () => Math.max(MIN_W, Math.min(760, Math.round(window.innerWidth * 0.5)));
const clampW = (w: number) => Math.min(maxW(), Math.max(MIN_W, Math.round(w)));

/** Lựa chọn của người xem (bề rộng, lần trước để mở/thu gọn/đóng). Bọc try/catch: trình duyệt chặn lưu trữ thì dùng mặc định. */
export function readOfficePref(): { width: number; mode: OfficeMode } {
  try {
    const v = JSON.parse(localStorage.getItem(PREF_KEY) || '{}');
    return { width: typeof v.width === 'number' ? v.width : defaultW(), mode: v.mode === 'open' || v.mode === 'collapsed' ? v.mode : 'closed' };
  } catch { return { width: defaultW(), mode: 'closed' }; }
}
function writeOfficePref(p: { width: number; mode: OfficeMode }) {
  try { localStorage.setItem(PREF_KEY, JSON.stringify(p)); } catch { /* không lưu được: lần sau dùng mặc định */ }
}

export function OfficePanel({ source, mode, onMode }: { source: OfficeSource | null; mode: OfficeMode; onMode: (m: OfficeMode) => void }) {
  const [width, setWidth] = useState(() => clampW(readOfficePref().width));
  const [live, setLive] = useState<LiveState | null>(null);
  const drag = useRef<{ x: number; w: number } | null>(null);

  // chỉ ghi khi bảng đã mở trong phiên: tải trang (chưa mở) không được ghi đè lựa chọn lần trước thành "đóng"
  const opened = !!source;
  useEffect(() => { if (opened) writeOfficePref({ width, mode }); }, [opened, width, mode]);
  useEffect(() => {
    const fit = () => setWidth((w) => clampW(w));
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);
  useEffect(() => {
    if (mode !== 'open') return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !(e.target as HTMLElement)?.closest?.('input,textarea,select')) onMode('collapsed'); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mode, onMode]);

  const onDown = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    drag.current = { x: e.clientX, w: width };
    e.currentTarget.setPointerCapture(e.pointerId);
  }, [width]);
  const onMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current) setWidth(clampW(drag.current.w + (drag.current.x - e.clientX)));  // kéo sang trái là rộng ra
  }, []);
  const onUp = useCallback(() => { drag.current = null; }, []);
  const onKeyResize = useCallback((e: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 80 : 24;
    if (e.key === 'ArrowLeft') { e.preventDefault(); setWidth((w) => clampW(w + step)); }
    if (e.key === 'ArrowRight') { e.preventDefault(); setWidth((w) => clampW(w - step)); }
  }, []);

  if (!source) return null;  // chưa mở lần nào: không tải three.js
  const status = !live ? 'Đang dựng văn phòng…' : live.finished ? (live.failed ? 'Không hoàn thành' : 'Đã xong') : live.headline;
  const busy = !!live && !live.finished && source.kind === 'live';

  return (
    <>
      <aside className="ws-office" hidden={mode !== 'open'} style={{ ['--office-w' as string]: `${width}px` }}
        // để kiểm thử tự động so văn phòng với run.events (Đợt 6): ai làm bước nào, đã xong chưa
        data-mode={source.kind} data-finished={live?.finished ? (live.failed ? 'failed' : 'ok') : undefined}
        data-steps={live?.steps.map(s => `${s.actor}:${s.key}:${s.state}`).join('|')}
        aria-label={source.kind === 'live' ? 'Văn phòng Agent: lượt đang chạy' : 'Văn phòng Agent: xem lại lượt đã chạy'}>
        <div className="ws-office-resize" role="separator" aria-orientation="vertical" aria-label="Kéo để đổi bề rộng văn phòng"
          aria-valuemin={MIN_W} aria-valuemax={maxW()} aria-valuenow={width} tabIndex={0}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} onKeyDown={onKeyResize} />
        <div className="ws-office-grip" aria-hidden="true" />
        <div className="ws-office-btns">
          <button type="button" onClick={() => onMode('collapsed')} aria-label="Thu gọn văn phòng" title="Thu gọn (Esc)"><ChevronRight size={17} /></button>
          <button type="button" onClick={() => onMode('closed')} aria-label="Đóng văn phòng" title="Đóng"><X size={17} /></button>
        </div>
        <Suspense fallback={<div className="office3d-page office3d-loading">Đang dựng văn phòng…</div>}>
          <OfficeView source={source} onLiveState={setLive} />
        </Suspense>
      </aside>
      {mode === 'collapsed' && (
        <button type="button" className={`ws-office-tab${busy ? ' is-busy' : ''}`} onClick={() => onMode('open')}
          aria-label={`Mở văn phòng Agent. ${status}`} title={status}>
          <Bot size={16} aria-hidden="true" />
          <span>{busy ? 'Agent đang làm' : 'Văn phòng'}</span>
        </button>
      )}
    </>
  );
}
