// Nền ánh sáng và lớp chuyển động của Studio: vào trang theo hướng (GSAP), ánh đèn theo con trỏ trên thẻ, cuộn mượt (Lenis).
// Tôn trọng "giảm chuyển động": khi bật thì không chạy vào trang, không cuộn mượt; nội dung luôn hiện dù script lỗi.
import React, { useEffect } from 'react';
import gsap from 'gsap';
import Lenis from 'lenis';
import { introEndsAt } from './StudioIntro';
import { motionAllowed } from '../utils/motion';
import { navDirection } from '../utils/navOrder';

// Chỉ khi chạy dev: cho phép bài kiểm thử làm chậm GSAP để chụp từng khung hình (window.__gsapSlow = 0.1).
if (import.meta.env.DEV && typeof window !== 'undefined') {
  const slow = (window as unknown as { __gsapSlow?: number }).__gsapSlow;
  if (slow) gsap.globalTimeline.timeScale(slow);
}

export function StudioBackdrop() {
  return <div className="st-aurora" aria-hidden="true"><i /><i /><i /></div>;
}

const reduced = () => !motionAllowed();

/** Gắn một lần ở App; chạy lại hiệu ứng vào trang mỗi khi đổi trang. */
export function useStudioMotion(page: string, ready = true) {
  // ánh đèn theo con trỏ: đặt --mx/--my trên thẻ đang được trỏ
  useEffect(() => {
    let raf = 0;
    const onMove = (e: PointerEvent) => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const card = (e.target as Element | null)?.closest?.('.dz-card, .dp-kpis > div') as HTMLElement | null;
        if (!card) return;
        const r = card.getBoundingClientRect();
        card.style.setProperty('--mx', `${e.clientX - r.left}px`);
        card.style.setProperty('--my', `${e.clientY - r.top}px`);
      });
    };
    document.addEventListener('pointermove', onMove, { passive: true });
    return () => { document.removeEventListener('pointermove', onMove); cancelAnimationFrame(raf); };
  }, []);

  const prev = React.useRef<string | null>(null);
  // useLayoutEffect: đặt trạng thái đầu của trang mới trước khi trình duyệt vẽ khung hình đầu, nên không chớp
  React.useLayoutEffect(() => {
    if (!ready) return;
    const from = prev.current;
    prev.current = page;
    if (reduced()) return;
    let lenis: Lenis | null = null;
    let tick: ((t: number) => void) | null = null;
    const scroller = document.querySelector<HTMLElement>('.st-main .pg, .st-main .mn');
    const view = document.querySelector<HTMLElement>('.st-main > .pg, .st-main > .mn, .st-main > .st-legacy');
    // Cả trang trượt vào cùng lúc theo hướng robot nhảy: trang nằm dưới trên thanh bên thì nội dung đi lên (như cuộn xuống),
    // trang nằm trên thì đi xuống. Chỉ dùng transform + opacity (GPU), không filter: blur trên cả trang, vì làm mờ một khối
    // chứa nhiều mặt kính backdrop-filter buộc trình duyệt vẽ lại toàn trang ở mỗi khung hình (nguyên nhân giật cũ).
    // Chạy bằng Web Animations API thay cho GSAP: trình duyệt tự nội suy trên luồng vẽ, không phải đọc kiểu CSS hiện có của
    // khối trang (GSAP đọc getComputedStyle khi bắt đầu, ~30 ms ngay lúc chuyển trang). Cùng thời lượng, cùng đường cong power3.out.
    const tween = view && from !== null && typeof view.animate === 'function'
      ? view.animate([
          { transform: `translateY(${navDirection(from, page) === 'down' ? 56 : -56}px)`, opacity: 0 },
          { transform: 'translateY(0)', opacity: 1 },
        ], { duration: 420, easing: 'cubic-bezier(0.215, 0.61, 0.355, 1)' })
      : null;
    // chế độ quay chậm khi kiểm thử (chỉ bản dev): cùng tốc độ với GSAP để robot và trang vẫn khớp nhịp
    if (tween && import.meta.env.DEV) {
      const slow = (window as unknown as { __gsapSlow?: number }).__gsapSlow;
      if (slow) tween.playbackRate = slow;
    }
    // cuộn mượt bắt đầu sau khi trang đã vào chỗ, để không tranh khung hình với hiệu ứng vào trang
    const id = window.setTimeout(() => {
      if (scroller?.firstElementChild) {
        lenis = new Lenis({ wrapper: scroller, content: scroller.firstElementChild as HTMLElement, lerp: 0.12, smoothWheel: true, allowNestedScroll: true });
        tick = (t: number) => lenis?.raf(t * 1000);
        gsap.ticker.add(tick);
      }
    }, 120);
    return () => {
      window.clearTimeout(id);
      tween?.finish();
      if (tick) gsap.ticker.remove(tick);
      lenis?.destroy();
    };
  }, [page, ready]);
}

/** Số đếm lên khi xuất hiện (chỉ trang trí phần hiển thị; giá trị thật là `value`). */
export function CountUp({ value, format }: { value: number; format?: (n: number) => string }) {
  const ref = React.useRef<HTMLSpanElement>(null);
  const fmt = format ?? ((n: number) => Math.round(n).toLocaleString('vi-VN'));
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduced() || !Number.isFinite(value)) { el.textContent = fmt(value); return; }
    const obj = { n: 0 };
    const delay = Math.max(0, (introEndsAt.t - performance.now()) / 1000);
    el.textContent = fmt(0);
    const tw = gsap.to(obj, { n: value, duration: 1.2, delay, ease: 'power2.out', onUpdate: () => { el.textContent = fmt(obj.n); }, onComplete: () => { el.textContent = fmt(value); } });
    return () => { tw.kill(); el.textContent = fmt(value); };
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return <span ref={ref}>{fmt(value)}</span>;
}
