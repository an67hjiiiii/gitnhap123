// Cột ngữ cảnh bên phải của Không gian làm việc (Đợt 2, mục 7): tab "Nguồn & Tài liệu" (trích dẫn đang xem, phạm vi hỏi,
// kỹ năng đề xuất, quản lý kho) và tab "Quá trình xử lý" (bước thật, tác tử, token, thời gian). Điện thoại: ngăn kéo từ dưới lên.
import React, { useEffect, useMemo, useState } from 'react';
import { BookOpen, Check, Clock, Cpu, FileText, FolderCog, Layers, ListChecks, Maximize2, Sparkles, Users, X } from 'lucide-react';
import { DOC_TYPES, DocValidity, documentValidity, SKILL_LIST, SkillKey } from '../services/api';
import { highlightParts, keyTerms, suggestSkills, traceOf } from '../utils/workspaceAssist';

export type CtxTab = 'sources' | 'process';
type Doc = { id?: number | string; source_file: string; chunks_count: number; doc_type?: string | null };
const AGENT_VI: Record<string, string> = { conditions: 'Điều kiện', procedure: 'Quy trình', terms: 'Điều khoản', figures: 'Số liệu', general: 'Tổng hợp' };

interface Props {
  tab: CtxTab;
  onTab: (t: CtxTab) => void;
  docs: Doc[];
  /** tài liệu được chọn để trả lời; rỗng = cả không gian */
  picked: string[];
  onPick: (ids: string[]) => void;
  chunk: { id: string; source?: string; sourceId?: string; text?: string; error?: string } | null;
  question?: string;
  onCloseChunk: () => void;
  onOpenFull?: (sourceId: string, name?: string) => void;
  run?: Parameters<typeof traceOf>[0];
  live?: { steps: string[]; elapsed: number } | null;
  draft: string;
  onUseSkill: (k: SkillKey) => void;
  manage?: React.ReactNode;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export const WorkspaceContext: React.FC<Props> = ({ tab, onTab, docs, picked, onPick, chunk, question = '', onCloseChunk, onOpenFull, run, live, draft, onUseSkill, manage, mobileOpen, onMobileClose }) => {
  const ids = useMemo(() => docs.map(d => String(d.id ?? '')).filter(Boolean), [docs]);
  // nhãn bản cũ/mới: luật đọc số hiệu và "thay thế" trong văn bản (không gọi mô hình)
  const [validity, setValidity] = useState<Record<string, DocValidity>>({});
  useEffect(() => {
    if (!ids.length) { setValidity({}); return; }
    let alive = true;
    documentValidity(ids.slice(0, 40)).then(r => alive && setValidity(Object.fromEntries(r.documents.map(d => [d.source_id, d])))).catch(() => alive && setValidity({}));
    return () => { alive = false; };
  }, [ids.join(',')]);
  const all = picked.length === 0;
  const toggle = (id: string) => onPick(all ? ids.filter(x => x !== id) : picked.includes(id) ? picked.filter(x => x !== id) : [...picked, id].length === ids.length ? [] : [...picked, id]);
  const scopeTypes = docs.filter(d => all || picked.includes(String(d.id))).map(d => d.doc_type);
  const skills = suggestSkills(scopeTypes, draft);
  const trace = traceOf(run);
  const terms = useMemo(() => keyTerms(question), [question]);

  return (
    <>
      {mobileOpen && <div className="wc-scrim" onClick={onMobileClose} />}
      <aside className={`wc${mobileOpen ? ' is-open' : ''}`} aria-label="Ngữ cảnh câu trả lời">
        <div className="wc-grab" aria-hidden="true" />
        <div className="wc-tabs" role="tablist" aria-label="Ngữ cảnh">
          <button role="tab" aria-selected={tab === 'sources'} className={tab === 'sources' ? 'is-on' : ''} onClick={() => onTab('sources')}><BookOpen size={15} />Nguồn & Tài liệu</button>
          <button role="tab" aria-selected={tab === 'process'} className={tab === 'process' ? 'is-on' : ''} onClick={() => onTab('process')}><ListChecks size={15} />Quá trình xử lý{live && <i className="wc-live" aria-label="đang chạy" />}</button>
          <button className="wc-x" onClick={onMobileClose} aria-label="Đóng ngữ cảnh"><X size={18} /></button>
        </div>

        <div className="wc-body" role="tabpanel">
          {tab === 'sources' ? <>
            {chunk && <section className="wc-card wc-cite" aria-label="Trích dẫn đang xem">
              <header><span className="wc-ico"><BookOpen size={15} /></span><span className="wc-h"><small>Trích dẫn đang xem</small><b title={chunk.source}>{chunk.source || chunk.id}</b></span>
                <button className="tb-btn" onClick={onCloseChunk} aria-label="Đóng trích dẫn"><X size={16} /></button></header>
              {chunk.error ? <p className="note is-error">{chunk.error}</p> : chunk.text == null ? <p className="muted-line"><span className="spin is-dark" />Đang tải đoạn…</p>
                : <p className="wc-quote">{highlightParts(chunk.text, terms).map((p, i) => p.hit ? <mark key={i}>{p.t}</mark> : <React.Fragment key={i}>{p.t}</React.Fragment>)}</p>}
              {chunk.sourceId && onOpenFull && <button className="btn btn-ghost is-sm" onClick={() => onOpenFull(chunk.sourceId!, chunk.source)}><Maximize2 size={14} />Xem toàn văn</button>}
            </section>}

            <section className="wc-card" aria-label="Phạm vi hỏi">
              <header><span className="wc-ico"><Layers size={15} /></span><span className="wc-h"><small>Phạm vi hỏi</small><b>{all ? `Cả không gian · ${docs.length} tài liệu` : `${picked.length}/${docs.length} tài liệu được chọn`}</b></span>
                {!all && <button className="dp-link" onClick={() => onPick([])}>Chọn tất cả</button>}</header>
              {docs.length === 0 ? <p className="wc-empty">Chưa có tài liệu. Tải lên ở mục bên dưới hoặc nạp bộ mẫu.</p> :
                <ul className="wc-docs">{docs.map(d => {
                  const id = String(d.id ?? ''), on = all || picked.includes(id), v = validity[id];
                  return <li key={id}><label className={on ? 'is-on' : ''}>
                    <input type="checkbox" checked={on} onChange={() => toggle(id)} />
                    <span className="wc-check" aria-hidden="true">{on && <Check size={11} strokeWidth={3.2} />}</span>
                    <FileText size={14} className="wc-file" />
                    <span className="wc-doc"><b title={d.source_file}>{d.source_file}</b>
                      <small>{d.chunks_count} đoạn{d.doc_type ? ` · ${DOC_TYPES[d.doc_type] ?? d.doc_type}` : ''}</small></span>
                    {v?.status === 'REPLACED' && <em className="wc-ver is-old" title={v.status_note}>Bản cũ</em>}
                    {v && v.replaces.length > 0 && v.status !== 'REPLACED' && <em className="wc-ver is-new" title={`Thay thế ${v.replaces.join(', ')}`}>Bản mới</em>}
                  </label></li>;
                })}</ul>}
            </section>

            {skills.length > 0 && <section className="wc-card" aria-label="Kỹ năng đề xuất">
              <header><span className="wc-ico is-violet"><Sparkles size={15} /></span><span className="wc-h"><small>Kỹ năng đề xuất</small><b>Hợp với tài liệu đang chọn</b></span></header>
              <div className="wc-skills">{skills.map(s => <button key={s.key} type="button" onClick={() => onUseSkill(s.key)}>
                <b>{SKILL_LIST.find(k => k.key === s.key)?.label}</b><small>{s.why}</small></button>)}</div>
            </section>}

            {manage && <details className="wc-card wc-manage">
              <summary><span className="wc-ico"><FolderCog size={15} /></span><span className="wc-h"><small>Kho tài liệu</small><b>Thêm và quản lý tài liệu</b></span></summary>
              {manage}
            </details>}
          </> : <>
            {live && <section className="wc-card is-live" aria-live="polite">
              <header><span className="wc-ico"><Clock size={15} /></span><span className="wc-h"><small>Đang xử lý</small><b>{live.elapsed} giây</b></span></header>
              {live.steps.length === 0 ? <p className="wc-empty">Đã gửi yêu cầu, chờ máy chủ báo bước đầu tiên…</p>
                : <ol className="wc-steps">{live.steps.map((s, i) => <li key={i} className={i === live.steps.length - 1 ? 'is-now' : ''}>{s}</li>)}</ol>}
            </section>}
            {trace ? <section className="wc-card">
              <header><span className="wc-ico"><ListChecks size={15} /></span><span className="wc-h"><small>Lượt trả lời gần nhất</small><b>{trace.steps.length} bước ghi nhận</b></span></header>
              <dl className="wc-metrics">
                <div><dt><Clock size={13} />Thời gian</dt><dd>{trace.ms == null ? 'Chưa đo' : `${(trace.ms / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây`}</dd></div>
                <div><dt><Cpu size={13} />Token</dt><dd>{trace.tokens == null ? 'Chưa đo' : trace.tokens.toLocaleString('vi-VN')}</dd></div>
                <div><dt><Users size={13} />Nhiệm vụ</dt><dd>{trace.tasks}</dd></div>
              </dl>
              {trace.agents.length > 0 && <p className="wc-agents">{trace.agents.map(a => <span key={a}>{AGENT_VI[a] ?? a.replace('Agent', '')}</span>)}</p>}
              {trace.steps.length > 0 ? <ol className="wc-steps is-done">{trace.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
                : <p className="wc-empty">Lượt này không ghi sự kiện tiến trình (ví dụ thẻ kỹ năng).</p>}
            </section> : !live && <p className="wc-empty wc-pad">Chưa có lượt trả lời nào trong cuộc trò chuyện này. Gửi câu hỏi để xem các bước hệ thống đã làm.</p>}
          </>}
        </div>
      </aside>
    </>
  );
};
