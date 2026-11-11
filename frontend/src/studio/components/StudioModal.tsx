import React, { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

interface StudioModalProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  onClose: () => void;
  footer?: React.ReactNode;
  toolbar?: React.ReactNode;
  actions?: React.ReactNode;
  size?: 'md' | 'lg';
  labelId: string;
  children: React.ReactNode;
}

// Khung cửa sổ dùng chung: giữ focus bên trong, Esc để đóng, bấm nền để đóng, trả focus khi đóng.
export function StudioModal({ title, subtitle, icon, onClose, footer, toolbar, actions, size = 'lg', labelId, children }: StudioModalProps) {
  const box = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus() ?? box.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { closeRef.current(); return; }
      if (e.key !== 'Tab' || !box.current) return;
      const items = [...box.current.querySelectorAll<HTMLElement>('button:not(:disabled), input, textarea, select, a[href], [tabindex="0"]')];
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('keydown', onKey); opener?.focus(); };
  }, []);
  return (
    <div className="mo-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={box} className={`mo-box is-${size}`} role="dialog" aria-modal="true" aria-labelledby={labelId} tabIndex={-1}>
        <header className="mo-head">
          {icon && <span className="mo-icon">{icon}</span>}
          <div className="mo-titles"><h2 id={labelId}>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
          {actions}<button className="icon-btn" onClick={onClose} aria-label="Đóng cửa sổ"><X size={18} /></button>
        </header>
        {toolbar && <div className="mo-toolbar">{toolbar}</div>}
        <div className="mo-body">{children}</div>
        {footer && <footer className="mo-foot">{footer}</footer>}
      </div>
    </div>
  );
}
