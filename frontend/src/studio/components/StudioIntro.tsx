// Màn mở đầu lần đầu vào Studio trong phiên trình duyệt (bấm Mở Studio, đăng nhập xong): nền đêm có quầng sáng, Robot C27 hiện giữa màn hình như logo,
// bay về đúng chỗ logo ở thanh bên rồi một vòng tròn mở rộng từ chính chỗ đó để lộ Studio (~1,4 giây).
// Bấm hoặc nhấn phím bất kỳ để vào ngay; tắt khi chọn "Hiệu ứng: theo thiết bị" và thiết bị bật giảm chuyển động.
import React, { useEffect, useLayoutEffect, useRef } from 'react';
import gsap from 'gsap';
import { AssistantRobot } from './robot/AssistantRobot';
import { motionAllowed } from '../utils/motion';

const INTRO_KEY = 'oq-intro-played';
const ARM_KEY = 'oq-intro-arm';

/** Gọi khi người dùng chủ động vào Studio (bấm Mở Studio, đăng nhập, đăng ký): lần vào đó chạy màn mở đầu. */
export function armIntro() {
  try { sessionStorage.setItem(ARM_KEY, '1'); } catch { /* chặn lưu trữ: bỏ qua */ }
}

export function shouldPlayIntro() {
  // chạy khi vừa bấm Mở Studio / đăng nhập, hoặc lần đầu mở /studio trong phiên; tải lại trang không chạy lại.
  // 22/11: trước đây chỉ chạy một lần mỗi tab nên đăng nhập lại, bấm Mở Studio lần sau không thấy màn mở đầu nữa.
  try {
    const armed = sessionStorage.getItem(ARM_KEY), played = sessionStorage.getItem(INTRO_KEY);
    sessionStorage.removeItem(ARM_KEY); sessionStorage.setItem(INTRO_KEY, '1');
    if (!armed && played) return false;
  } catch { /* chặn lưu trữ: vẫn chạy như cũ */ }
  return motionAllowed();
}

/** Thời điểm màn mở đầu xong (để số đếm lên bắt đầu đúng lúc lộ trang). */
export const introEndsAt = { t: 0 };

export function StudioIntro({ name, onDone }: { name?: string; onDone: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const tl = useRef<gsap.core.Timeline | null>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    introEndsAt.t = performance.now() + 1450;
    const ctx = gsap.context(() => {
      const q = gsap.utils.selector(el);
      const W = window.innerWidth, H = window.innerHeight;
      // điểm đích: biểu tượng logo trên thanh bên (trên điện thoại thanh bên ẩn thì về góc trên trái)
      const logo = document.querySelector('.st-app > .sb .sb-brand a > *:first-child')?.getBoundingClientRect();
      const visible = logo && logo.width > 0 && logo.left >= 0;
      const tx = visible ? logo!.left + Math.min(logo!.width, logo!.height) / 2 : 28;
      const ty = visible ? logo!.top + logo!.height / 2 : 26;
      el.style.setProperty('--cx', `${tx}px`); el.style.setProperty('--cy', `${ty}px`);
      const R = Math.hypot(Math.max(tx, W - tx), Math.max(ty, H - ty)) + 40;
      const mark = q('.sti-mark');
      const t = gsap.timeline({ onComplete: () => doneRef.current() });
      t.fromTo(q('.sti-glow'), { scale: 0.5, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.45, ease: 'power2.out' }, 0)
        .fromTo(mark, { scale: 0.4, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.4, ease: 'back.out(1.8)' }, 0.05)
        .fromTo(q('.sti-word'), { y: 10, opacity: 0 }, { y: 0, opacity: 1, duration: 0.3, ease: 'power2.out' }, 0.18)
        .to(q('.sti-word'), { opacity: 0, duration: 0.15 }, 0.48)
        // robot bay về chỗ logo, thu nhỏ bằng logo
        .to(mark, { x: tx - W / 2, y: ty - H / 2, scale: 0.3, duration: 0.42, ease: 'power3.inOut' }, 0.5)
        .to(q('.sti-glow'), { x: tx - W / 2, y: ty - H / 2, scale: 0.35, opacity: 0.8, duration: 0.42, ease: 'power3.inOut' }, 0.5)
        // vòng tròn mở rộng từ chỗ logo để lộ Studio
        .fromTo(el, { '--r': '0px' }, { '--r': `${R}px`, duration: 0.6, ease: 'power2.in' }, 0.86)
        .to([mark, q('.sti-glow')], { opacity: 0, duration: 0.2 }, 0.95);
      tl.current = t;
    }, el);
    return () => ctx.revert();
  }, []);

  useEffect(() => {
    const skip = () => tl.current?.progress(1);
    window.addEventListener('keydown', skip);
    return () => window.removeEventListener('keydown', skip);
  }, []);

  return (
    <div className="st-intro" ref={root} onClick={() => tl.current?.progress(1)} role="dialog" aria-label="Đang mở OrchestrIQ Studio">
      <div className="sti-glow" aria-hidden="true" />
      <div className="sti-mark"><AssistantRobot size={120} interactive={false} state="happy" colorConfig={{ shell: '#1d344a', trim: '#d5dde6', screen: '#8fdcff' }} /></div>
      <p className="sti-word">OrchestrIQ Studio{name ? ` · Xin chào, ${name}` : ''}</p>
    </div>
  );
}
