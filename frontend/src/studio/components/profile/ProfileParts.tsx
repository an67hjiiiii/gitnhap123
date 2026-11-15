// Thành phần trực quan của trang Hồ sơ tài liệu: bìa tài liệu, vòng điểm chất lượng, ô số đo, phần xem trước khi chưa lập hồ sơ.
import React, { useLayoutEffect, useRef } from 'react';
import gsap from 'gsap';
import { BookMarked, FileText, Gauge, Link2, MessageCircleQuestion, ShieldCheck } from 'lucide-react';
import { motionAllowed } from '../../utils/motion';

type IconType = React.ComponentType<{ size?: number; strokeWidth?: number }>;
const nf = (n: number) => n.toLocaleString('vi-VN');

/** Bìa tài liệu: chồng trang giấy có nhãn loại tệp, thay cho biểu tượng chung chung. */
export function DocCover({ ext }: { ext: string }) {
  return (
    <div className="pf-cover" aria-hidden="true">
      <span className="pf-sheet is-3" /><span className="pf-sheet is-2" />
      <span className="pf-sheet is-1"><i /><i /><i /><i /><i /><b>{(ext || 'doc').toUpperCase()}</b></span>
    </div>
  );
}

/** Vòng điểm chất lượng (0-100). null = chưa đo. */
export function QualityRing({ score, label = 'Chất lượng nội dung', suffix = '/100', word: wordIn }: { score: number | null; label?: string; suffix?: string; word?: string }) {
  const ref = useRef<SVGCircleElement>(null);
  const num = useRef<HTMLElement>(null);
  const R = 54, C = 2 * Math.PI * R;
  const tone = score == null ? 'none' : score >= 80 ? 'ok' : score >= 50 ? 'mid' : 'bad';
  const word = wordIn ?? (score == null ? 'Chưa đo' : score >= 80 ? 'Tốt' : score >= 50 ? 'Trung bình' : 'Cần sửa');
  useLayoutEffect(() => {
    if (score == null || !ref.current) return;
    const off = C * (1 - score / 100);
    if (!motionAllowed()) { ref.current.style.strokeDashoffset = String(off); return; }
    const ctx = gsap.context(() => {
      gsap.fromTo(ref.current, { strokeDashoffset: C }, { strokeDashoffset: off, duration: 1.1, ease: 'power3.out', delay: 0.15 });
      const o = { v: 0 };
      gsap.to(o, { v: score, duration: 1.1, ease: 'power3.out', delay: 0.15, onUpdate: () => { if (num.current) num.current.textContent = String(Math.round(o.v)); } });
    });
    return () => ctx.revert();
  }, [score, C]);
  return (
    <div className={`pf-ring is-${tone}`} role="img" aria-label={score == null ? `${label}: chưa đo` : `${label} ${score}${suffix === '%' ? '%' : ' trên 100'}, ${word}`}>
      <svg viewBox="0 0 132 132" aria-hidden="true">
        <defs><linearGradient id="pf-ring-g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="var(--pf-ring-a)" /><stop offset="100%" stopColor="var(--pf-ring-b)" /></linearGradient></defs>
        <circle className="pf-ring-track" cx="66" cy="66" r={R} />
        {score != null && <circle ref={ref} className="pf-ring-bar" cx="66" cy="66" r={R} strokeDasharray={C} strokeDashoffset={C * (1 - score / 100)} />}
      </svg>
      <div className="pf-ring-c"><b key={String(score)} ref={num}>{score ?? '—'}</b>{score != null && <small>{suffix}</small>}</div>
      <p className="pf-ring-l"><span>{label}</span><em>{word}</em></p>
    </div>
  );
}

/** Ô số đo: biểu tượng, số đếm lên khi hiện, nhãn, dòng phụ; bấm được thì mở mục chi tiết. */
export function Stat({ Icon, value, label, sub, tone, onClick }: { Icon: IconType; value: number; label: string; sub?: string; tone?: 'ok' | 'warn' | 'bad'; onClick?: () => void }) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag className={`pf-stat${tone ? ` is-${tone}` : ''}${onClick ? ' is-link' : ''}`} onClick={onClick} {...(onClick ? { type: 'button' } : {})}>
      <span className="pf-stat-ico"><Icon size={18} strokeWidth={2} /></span>
      <b key={value} className="pf-count" data-count={value}>{nf(value)}</b>
      <span className="pf-stat-l">{label}</span>
      {sub && <small>{sub}</small>}
    </Tag>
  );
}

/** Đếm số và cho các khối hiện lần lượt mỗi khi hồ sơ (hoặc tab) đổi. */
export function useProfileMotion(root: React.RefObject<HTMLElement | null>, key: string, sel = '.pf-in') {
  useLayoutEffect(() => {
    const el = root.current;
    if (!el || !motionAllowed()) return;
    const ctx = gsap.context(() => {
      const items = el.querySelectorAll(sel);
      if (items.length) gsap.from(items, { y: 18, opacity: 0, duration: 0.5, ease: 'power3.out', stagger: 0.06, clearProps: 'transform,opacity' });
      el.querySelectorAll<HTMLElement>('.pf-count[data-count]').forEach(n => {
        const to = Number(n.dataset.count) || 0; const o = { v: 0 };
        gsap.to(o, { v: to, duration: 0.9, ease: 'power2.out', delay: 0.1, onUpdate: () => { n.textContent = nf(Math.round(o.v)); } });
      });
    }, el);
    return () => ctx.revert();
  }, [root, key, sel]);
}

/** Tô đậm con số trong văn bản (95%, 300 ms, 180 ngày...) để mắt bắt ngay các mốc quan trọng. */
const NUM = /((?<![\p{L}\d.,:-])\d+(?:[.,:]\d+)*(?:\+)?(?:\s?(?:%|ms|giây|phút|giờ|ngày|tháng|năm|req\/s|VND|triệu|tỷ))?)/gu;
export function Marked({ text }: { text: string }) {
  const parts = text.split(NUM);
  return <>{parts.map((p, i) => (i % 2 ? <b key={i} className="pf-hl">{p}</b> : p))}</>;
}

export type PreviewItem = [IconType, string, string];
const WILL: PreviewItem[] = [
  [FileText, 'Tóm tắt và ý chính', 'Đọc hiểu tài liệu trong một phút'],
  [BookMarked, 'Thuật ngữ', 'Từ khó kèm định nghĩa'],
  [MessageCircleQuestion, 'Câu hỏi nên hỏi', 'Bấm là hỏi ngay ở Không gian làm việc'],
  [Gauge, 'Chất lượng nội dung', 'Điểm 0 đến 100 và lỗi cần sửa'],
  [ShieldCheck, 'Thông tin nhạy cảm', 'Email, số thẻ, khóa bí mật; tải bản đã che'],
  [Link2, 'Tài liệu cùng chủ đề', 'Độ trùng với các tài liệu khác'],
];
/** Chưa có hồ sơ: cho thấy hồ sơ sẽ gồm những gì, và nút lập hồ sơ ở giữa. */
export function ProfilePreview({ action, title = 'Hồ sơ sẽ có', text = 'Phần chạy tại máy xong trong vài giây; tóm tắt, câu hỏi và thuật ngữ do mô hình cục bộ viết.', items = WILL }: { action?: React.ReactNode; title?: string; text?: string; items?: [IconType, string, string][] }) {
  return (
    <section className="pf-preview pf-in">
      <div className="pf-preview-head"><h2>{title}</h2><p>{text}</p>{action}</div>
      <ul className="pf-will">{items.map(([I, t, d]) => <li key={t}><span className="pf-stat-ico"><I size={18} /></span><b>{t}</b><small>{d}</small></li>)}</ul>
    </section>
  );
}

/** Hình minh họa đầu thẻ: khối biểu tượng màu thương hiệu, kèm huy hiệu số (tùy chọn). */
export function HeroArt({ Icon, badge }: { Icon: IconType; badge?: React.ReactNode }) {
  return (
    <div className="pf-art" aria-hidden="true">
      <span className="pf-art-orb" /><span className="pf-art-core"><Icon size={34} strokeWidth={1.8} /></span>
      {badge != null && <span className="pf-art-badge">{badge}</span>}
    </div>
  );
}

export type MapTone = 'ok' | 'warn' | 'bad' | 'muted' | 'todo';
/** Bản đồ ô: mỗi mục một ô có mã, tô theo kết luận, gom theo nhóm; bấm ô để mở mục. */
export function CoverageMap({ title, Icon, groups, legend, onPick }: {
  title: string; Icon: IconType; groups: [string, { id: string; tone: MapTone; label: string }[]][];
  legend: [MapTone, string][]; onPick: (id: string) => void;
}) {
  return (
    <section className="dz-card pf-map pf-in">
      <header><h3><Icon size={16} />{title}</h3><span className="pf-legend">{legend.map(([t, l]) => <span key={t}><i className={`is-${t}`} />{l}</span>)}</span></header>
      {groups.map(([g, items]) => (
        <div key={g || '_'} className="pf-group">
          {g && <h4>{g}</h4>}
          <div className="pf-tiles">{items.map(it => <button key={it.id} type="button" className={`pf-tile is-${it.tone}`} title={it.label} aria-label={`${it.id}: ${it.label}`} onClick={() => onPick(it.id)}>{it.id}</button>)}</div>
        </div>
      ))}
    </section>
  );
}
