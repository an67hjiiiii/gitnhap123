// Gợn sóng + bong bóng bung ra từ chỗ nhấn khi mở khung chat (24/11). Kiểu dáng ở styles/composer-2026.css.
export function burstBubbles(x: number, y: number, count = 14) {
  const add = (cls: string, css: string, life: number) => {
    const el = document.createElement('span');
    el.className = cls; el.setAttribute('aria-hidden', 'true'); el.style.cssText = css;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), life);
  };
  add('ui-ripple', `left:${x}px;top:${y}px`, 800);
  for (let i = 0; i < count; i++) {
    const s = 6 + Math.random() * 16, a = Math.random() * Math.PI * 2, d = 60 + Math.random() * 120;
    add('ui-bub', `width:${s}px;height:${s}px;left:${x - s / 2}px;top:${y - s / 2}px;--dx:${Math.cos(a) * d}px;--dy:${Math.sin(a) * d - 40}px;animation-delay:${Math.random() * 80}ms`, 1100);
  }
}
