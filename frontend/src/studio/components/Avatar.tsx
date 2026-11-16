// Ảnh đại diện: hiện ảnh tải lên (data URL 256px lưu ở backend), ảnh mẫu tự vẽ ("preset:<mã>") hoặc chữ cái đầu.
// Ảnh mẫu ở avatarPresets.tsx (tự vẽ SVG, emoji, dải màu), không dùng hình có bản quyền.
import React, { useEffect, useRef, useState } from 'react';
import { Dices, ImagePlus, Trash2, UserRound } from 'lucide-react';
import { setAvatar } from '../services/api';
import { User } from '../types';
import { StudioModal } from './StudioModal';
import { PRESET_GROUPS, PRESETS } from './avatarPresets';
import '../styles/avatar.css';

/** Ảnh đại diện; `children` là chữ cái hiện khi chưa có ảnh. */
export function Avatar({ value, className = '', style, children }: { value?: string | null; className?: string; style?: React.CSSProperties; children?: React.ReactNode }) {
  const preset = value?.startsWith('preset:') ? PRESETS[value.slice(7)] : undefined;
  const img = value?.startsWith('data:image/') ? value : undefined;
  return (
    <span className={`${className}${img || preset ? ' has-img' : ''}`} style={style} aria-hidden="true">
      {img ? <img src={img} alt="" /> : preset ? preset.node : children}
    </span>
  );
}

// cắt vuông giữa ảnh, thu về 256px; WebP nếu trình duyệt hỗ trợ, nếu không thì JPEG
async function squareThumb(file: File): Promise<string> {
  const bmp = await createImageBitmap(file);
  const side = Math.min(bmp.width, bmp.height);
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, 256, 256);
  ctx.drawImage(bmp, (bmp.width - side) / 2, (bmp.height - side) / 2, side, side, 0, 0, 256, 256);
  bmp.close();
  const webp = canvas.toDataURL('image/webp', 0.86);
  return webp.startsWith('data:image/webp') ? webp : canvas.toDataURL('image/jpeg', 0.86);
}

export function AvatarDialog({ user, onClose, onSaved }: { user: User; onClose: () => void; onSaved: (u: User) => void }) {
  const [pick, setPick] = useState<string | null>(user.avatar ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  // mở hộp thì cuộn tới ảnh đang dùng; chọn ngẫu nhiên thì cuộn tới ảnh vừa chọn
  // chỉ cuộn bên trong danh sách (scrollIntoView sẽ kéo cả hộp thoại theo trên điện thoại)
  const reveal = (instant = false) => requestAnimationFrame(() => {
    const list = listRef.current, tile = list?.querySelector<HTMLElement>('.av-tile[aria-pressed="true"]');
    if (!list || !tile) return;
    const top = tile.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop - list.clientHeight / 2 + tile.offsetHeight / 2;
    const still = instant || matchMedia('(prefers-reduced-motion: reduce)').matches;
    list.scrollTo({ top, behavior: still ? 'auto' : 'smooth' });
  });
  useEffect(() => { reveal(true); }, []);
  const fileRef = useRef<HTMLInputElement>(null);
  const initialChar = user.full_name.charAt(0);

  const onFile = async (file?: File) => {
    if (!file) return;
    setError('');
    if (!file.type.startsWith('image/') || file.type === 'image/svg+xml') { setError('Chọn tệp ảnh PNG, JPEG, WebP hoặc GIF.'); return; }
    if (file.size > 15 * 1024 * 1024) { setError('Ảnh lớn quá 15 MB.'); return; }
    try { setPick(await squareThumb(file)); } catch { setError('Không đọc được ảnh này. Thử ảnh khác.'); }
  };
  const save = async () => {
    setBusy(true); setError('');
    try { onSaved(await setAvatar(pick)); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Không lưu được ảnh.'); }
    finally { setBusy(false); }
  };
  const tile = (id: string, label: string, node: React.ReactNode) => (
    <button key={id} type="button" className="av-tile" aria-pressed={pick === `preset:${id}`} title={label} aria-label={label} onClick={() => setPick(`preset:${id}`)}>{node}</button>
  );

  return (
    <StudioModal labelId="av-title" size="md" icon={<UserRound size={18} />} title="Đổi ảnh đại diện"
      subtitle="Ảnh hiện ở thanh bên và trong danh sách thành viên tổ chức." onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Hủy</button>
        <button className="btn btn-dark" disabled={busy || pick === (user.avatar ?? null)} onClick={save}>{busy ? 'Đang lưu…' : 'Lưu ảnh'}</button>
      </>}>
      <div className="av-dlg">
        <div className="av-current">
          <Avatar value={pick} className="sb-avatar av-xl">{initialChar}</Avatar>
          <div className="av-actions">
            <button type="button" className="btn btn-dark" data-autofocus onClick={() => fileRef.current?.click()}><ImagePlus size={15} />Tải ảnh lên</button>
            <button type="button" className="btn btn-ghost" disabled={!pick} onClick={() => setPick(null)}><Trash2 size={15} />Bỏ ảnh</button>
            <small>Ảnh được cắt vuông và thu nhỏ còn 256 px ngay trên máy bạn trước khi lưu.</small>
          </div>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={e => { onFile(e.target.files?.[0]); e.target.value = ''; }} />
        </div>
        {error && <div className="note is-error" role="alert">{error}</div>}
        <div className="av-head"><b>Ảnh mẫu</b><small>Lướt xuống để xem tất cả thể loại</small>
          <button type="button" className="av-dice" aria-label="Chọn ảnh mẫu ngẫu nhiên" onClick={() => {
            const all = PRESET_GROUPS.flatMap(g => g.items);
            setPick(`preset:${all[Math.floor(Math.random() * all.length)].id}`); reveal();
          }}><Dices size={15} />Ngẫu nhiên</button>
        </div>
        <div className="av-scroll" ref={listRef}>
          {PRESET_GROUPS.map(g => <section key={g.key} aria-label={g.label}>
            <p className="av-group">{g.label}<span>{g.items.length}</span></p>
            <div className="av-grid">{g.items.map(p => tile(p.id, p.label, p.node))}</div>
          </section>)}
        </div>
      </div>
    </StudioModal>
  );
}
