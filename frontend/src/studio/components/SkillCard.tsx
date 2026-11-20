// Thẻ kết quả kỹ năng trong ô chat (đợt 4, bản làm thử): kỹ năng do bộ định tuyến chọn hoặc người dùng gọi bằng "/".
// Kết luận tổng do luật cố định ở backend suy ra; thẻ chỉ hiển thị, mọi căn cứ bấm được vào đoạn gốc.
import React from 'react';
import { AlertTriangle, ArrowUpRight, CheckCircle2, CircleHelp, ClipboardCheck, FileClock, Gavel, GitCompareArrows, ListOrdered, UserCheck, XCircle } from 'lucide-react';
import { CHANGE_LABEL, changeTone } from '../utils/compareText';
import type { SkillKey, SkillOutput } from '../services/api';

const ICON: Record<SkillKey, React.ElementType> = {
  conditions: ClipboardCheck, procedure: ListOrdered, approver: UserCheck, contract_review: Gavel, validity: FileClock, compare: GitCompareArrows,
};
const OVERALL: Record<string, { text: string; tone: string }> = {
  ELIGIBLE: { text: 'Đủ điều kiện', tone: 'ok' },
  NOT_ELIGIBLE: { text: 'Không đủ điều kiện', tone: 'bad' },
  INSUFFICIENT_INFO: { text: 'Thiếu dữ kiện để kết luận', tone: 'warn' },
  NO_RULE: { text: 'Không thấy quy định phù hợp', tone: 'warn' },
  UNRESOLVED: { text: 'Chưa xác định', tone: 'warn' },
};
const VERDICT: Record<string, { text: string; tone: string; I: React.ElementType }> = {
  MET: { text: 'Đạt', tone: 'ok', I: CheckCircle2 }, NOT_MET: { text: 'Không đạt', tone: 'bad', I: XCircle }, UNKNOWN: { text: 'Chưa rõ', tone: 'warn', I: CircleHelp },
};
const RISK: Record<string, { text: string; tone: string }> = { HIGH: { text: 'Cao', tone: 'bad' }, MEDIUM: { text: 'Trung bình', tone: 'warn' }, LOW: { text: 'Thấp', tone: 'ok' } };
const VALIDITY: Record<string, { text: string; tone: string }> = {
  IN_FORCE: { text: 'Còn hiệu lực', tone: 'ok' }, REPLACED: { text: 'Đã bị thay thế', tone: 'bad' }, NOT_YET: { text: 'Chưa có hiệu lực', tone: 'warn' }, UNKNOWN: { text: 'Chưa xác định', tone: 'warn' },
};

type Props = { label: string; reason?: string; out: SkillOutput; citeLabel: (id: string) => string; onCite: (id: string) => void };

export const SkillCard: React.FC<Props> = ({ label, reason, out, citeLabel, onCite }) => {
  const I = ICON[out.skill];
  const cite = (id?: string | null) => id ? <button type="button" className="skc-cite" onClick={() => onCite(id)} title={`Xem đoạn gốc (${id})`}>{citeLabel(id)}</button> : <span className="skc-none">không có căn cứ</span>;
  const d: any = out.data;
  const measured = d.latency_ms ? `${(d.input_tokens + d.output_tokens).toLocaleString('vi-VN')} token · ${(d.latency_ms / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây` : null;

  let body: React.ReactNode = null;
  if (out.skill === 'conditions') {
    const o = OVERALL[out.data.overall] ?? OVERALL.UNRESOLVED;
    body = <>
      <p className={`skc-verdict is-${o.tone}`}>{o.text}</p>
      {out.data.conditions.length > 0 && <ul className="skc-rows">{out.data.conditions.map((c, i) => {
        const v = VERDICT[c.verdict] ?? VERDICT.UNKNOWN;
        return <li key={i}><span className={`skc-badge is-${v.tone}`}><v.I size={13} />{v.text}</span>
          <div><b>{c.condition}</b>{c.case_fact && <small>Dữ kiện: {c.case_fact}</small>}{c.reason && <small>{c.reason}</small>}</div>{cite(c.citation)}</li>;
      })}</ul>}
    </>;
  } else if (out.skill === 'procedure') {
    body = <>
      {out.data.steps.length === 0 && <p className="skc-verdict is-warn">Không thấy các bước trong tài liệu.</p>}
      <ol className="skc-steps">{out.data.steps.map(s => <li key={s.order}><div><b>{s.action}</b>
        <small>{[s.actor && `Người làm: ${s.actor}`, s.deadline && `Thời hạn: ${s.deadline}`, s.outputs && `Kết quả: ${s.outputs}`].filter(Boolean).join(' · ')}</small></div>{cite(s.citation)}</li>)}</ol>
      {out.data.documents.length > 0 && <div className="skc-docs"><b>Giấy tờ cần có</b><ul>{out.data.documents.map((x, i) => <li key={i}>{x.name} {cite(x.citation)}</li>)}</ul></div>}
    </>;
  } else if (out.skill === 'approver') {
    body = out.data.approver
      ? <><p className="skc-verdict is-ok">Người duyệt: {out.data.approver}</p>{out.data.rule && <p className="skc-rule">{out.data.rule} {cite(out.data.citation)}</p>}</>
      : <p className="skc-verdict is-warn">Không thấy quy định cấp duyệt cho yêu cầu này.</p>;
  } else if (out.skill === 'contract_review') {
    body = <>
      {!out.data.looks_like_contract && <p className="skc-warn"><AlertTriangle size={14} />Tài liệu đã chọn có vẻ không phải hợp đồng.</p>}
      {out.data.risks.length === 0 ? <p className="skc-verdict is-ok">Không thấy điều khoản rủi ro rõ ràng.</p>
        : <ul className="skc-rows">{out.data.risks.map((r, i) => {
          const t = RISK[r.level] ?? RISK.MEDIUM;
          return <li key={i}><span className={`skc-badge is-${t.tone}`}>{t.text}</span><div><q>{r.quote}</q><small>{r.reason}</small></div>{cite(r.citation)}</li>;
        })}</ul>}
    </>;
  } else if (out.skill === 'validity') {
    body = <ul className="skc-rows">{out.data.documents.map(x => {
      const t = VALIDITY[x.status] ?? VALIDITY.UNKNOWN;
      return <li key={x.source_id}><span className={`skc-badge is-${t.tone}`}>{t.text}</span>
        <div><b>{x.number || x.source_name}</b><small>{[x.effective && `Hiệu lực từ ${x.effective}`, x.replaces.length > 0 && `Thay thế ${x.replaces.join(', ')}`, x.status_note].filter(Boolean).join(' · ')}</small></div></li>;
    })}</ul>;
  } else if (out.skill === 'compare') {
    // tóm tắt chỉ từ các mục đã đối chiếu bằng mã; bảng đầy đủ ở trang So sánh phiên bản
    const changed = out.data.items.filter(it => it.change !== 'UNCHANGED');
    body = <>
      <p className="skc-rule"><b>{out.data.old.source_name}</b> → <b>{out.data.new.source_name}</b></p>
      <p className="skc-chips">{(['ADDED', 'MODIFIED', 'MOVED_MODIFIED', 'MOVED', 'REMOVED', 'UNCHANGED'] as const).filter(k => out.data.counts[k]).map(k =>
        <span key={k} className={`skc-badge is-${changeTone(k)}`}>{CHANGE_LABEL[k]} {out.data.counts[k]}</span>)}</p>
      {changed.length === 0 ? <p className="skc-verdict is-ok">Hai bản giống nhau ở mọi mục.</p>
        : <ul className="skc-rows">{changed.slice(0, 6).map((it, i) => <li key={i}><span className={`skc-badge is-${changeTone(it.change)}`}>{CHANGE_LABEL[it.change]}</span>
          <div><b>{(it.new ?? it.old)!.key}{(it.new ?? it.old)!.title ? `. ${(it.new ?? it.old)!.title}` : ''}</b>
            <small>{it.clauses?.length ? it.clauses.map(c => `Khoản ${c.clause}: ${c.change === 'ADDED' ? 'thêm' : c.change === 'REMOVED' ? 'bỏ' : 'sửa'}`).join(' · ')
              : it.change === 'MOVED' || it.change === 'MOVED_MODIFIED' ? `Từ ${it.old!.key} sang ${it.new!.key}` : it.numbers_changed?.length ? `Số thay đổi: ${it.numbers_changed.join(', ')}` : ''}</small></div></li>)}</ul>}
      {changed.length > 6 && <p className="skc-rule">Còn {changed.length - 6} mục thay đổi khác.</p>}
      <button type="button" className="btn btn-dark is-sm skc-open" onClick={() => window.dispatchEvent(new CustomEvent('oq-open-compare', { detail: { old: out.data.old.source_id, new: out.data.new.source_id } }))}>
        <ArrowUpRight size={14} />Mở bảng chi tiết</button>
    </>;
  }

  return (
    <article className="skc" aria-label={`Kết quả kỹ năng ${label}`}>
      <header><span className="skc-ico"><I size={16} /></span><div><b>{label}</b>{reason && <small>{reason}</small>}</div></header>
      {d.note && /[àáảãạăâđèéẻẽẹêìíỉĩịòóỏõọôơùúủũụưỳýỷỹỵ]/i.test(d.note) && <p className="skc-note">{d.note}</p>}  {/* ghi chú mô hình viết tiếng Anh thì ẩn */}
      {body}
      <footer>{out.skill === 'compare' || out.skill === 'validity' ? 'Kết quả do mã đối chiếu, không gọi mô hình; người có thẩm quyền xác nhận trước khi dùng.' : 'Kết luận tổng do luật cố định suy ra, mô hình chỉ đọc và trích; người có thẩm quyền quyết định cuối cùng.'}{measured && <span>{measured}</span>}</footer>
    </article>
  );
};
