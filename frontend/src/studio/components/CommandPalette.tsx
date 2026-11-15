// Bảng lệnh nhanh (Ctrl/⌘ + K): gõ để đến một trang, mở cuộc trò chuyện gần đây hoặc chạy thao tác; điều khiển bằng bàn phím.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { CornerDownLeft, Search } from 'lucide-react';

export interface Command { id: string; label: string; group: string; hint?: string; Icon?: React.ComponentType<{ size?: number }>; run: () => void }

const fold = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase();

export function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Command[] }) {
  const [q, setQ] = useState('');
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => { if (open) { setQ(''); setIdx(0); setTimeout(() => inputRef.current?.focus(), 10); } }, [open]);
  const shown = useMemo(() => {
    const words = fold(q).split(/\s+/).filter(Boolean);
    return commands.filter(c => { const t = fold(`${c.label} ${c.group} ${c.hint ?? ''}`); return words.every(w => t.includes(w)); }).slice(0, 40);
  }, [q, commands]);
  useEffect(() => { setIdx(0); }, [q]);
  useEffect(() => { listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }); }, [idx]);
  if (!open) return null;
  const pick = (c?: Command) => { if (!c) return; onClose(); c.run(); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(shown.length - 1, i + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(shown[idx]); }
    else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  };
  let lastGroup = '';
  return (
    <div className="cmdk-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="cmdk" role="dialog" aria-modal="true" aria-label="Lệnh nhanh" onKeyDown={onKey}>
        <label className="cmdk-input"><Search size={18} />
          <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm trang, cuộc trò chuyện hoặc thao tác…" aria-label="Tìm lệnh"
            role="combobox" aria-expanded="true" aria-controls="cmdk-list" aria-activedescendant={shown[idx] ? `cmdk-${shown[idx].id}` : undefined} />
          <kbd>Esc</kbd>
        </label>
        <ul className="cmdk-list" id="cmdk-list" role="listbox" ref={listRef}>
          {shown.length === 0 && <li className="cmdk-empty">Không thấy lệnh nào khớp “{q}”.</li>}
          {shown.map((c, i) => {
            const head = c.group !== lastGroup ? (lastGroup = c.group) : null;
            return <React.Fragment key={c.id}>
              {head && <li className="cmdk-group" role="presentation">{head}</li>}
              <li id={`cmdk-${c.id}`} role="option" aria-selected={i === idx} className={i === idx ? 'is-on' : ''} onMouseMove={() => setIdx(i)} onClick={() => pick(c)}>
                {c.Icon ? <c.Icon size={16} /> : <span className="cmdk-dot" />}<span className="cmdk-label">{c.label}</span>{c.hint && <small>{c.hint}</small>}
                {i === idx && <CornerDownLeft size={14} className="cmdk-enter" />}
              </li>
            </React.Fragment>;
          })}
        </ul>
        <footer className="cmdk-foot"><span><kbd>↑</kbd><kbd>↓</kbd> chọn</span><span><kbd>Enter</kbd> mở</span><span><kbd>Ctrl</kbd><kbd>K</kbd> bật/tắt</span></footer>
      </div>
    </div>
  );
}
