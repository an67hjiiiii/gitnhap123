// Trang Chất lượng yêu cầu: soát từng yêu cầu (FR, NFR, UC...) theo các đặc tính của ISO/IEC/IEEE 29148 bằng luật xác định
// (cùng tài liệu luôn cho cùng kết quả, chỉ rõ cụm chữ vi phạm). Nút "Đề xuất viết lại" mới gọi mô hình cục bộ; mô hình bị cấm
// tự đặt con số, chỗ thiếu số để [cần xác định: ...], và số nào mô hình tự thêm được tô đỏ để người dùng soát.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, Download, Highlighter, Info, LayoutGrid, Layers, ListChecks, Save, Sparkles, SpellCheck, XCircle } from 'lucide-react';
import { ProfilePreview, useProfileMotion } from './profile/ProfileParts';
import './profile/profile.css';
import './profile/tools.css';
import {
  getReport, ReqIssue, ReqQualityResult, ReqQualityRow, ReqRewrite, reviewRequirements, rewriteRequirement, canSaveReports, saveReport,
} from '../services/api';
import { baseName, csvCell, Doc, docId, download, EmptyState, SavedReportsSelect, ToolHeader, useAnalysisData } from './analysis/shared';

const REQ_DOC = /yeu.?cau|requirement|srs|dac.?ta/i;
const SEV: Record<ReqIssue['severity'], { label: string; Icon: typeof Info; cls: string }> = {
  error: { label: 'Lỗi', Icon: XCircle, cls: 'is-bad' },
  warning: { label: 'Cảnh báo', Icon: AlertTriangle, cls: 'is-warn' },
  info: { label: 'Lưu ý', Icon: Info, cls: 'is-info' },
};
type Filter = 'all' | 'problems' | 'clean';

/** Tô cụm chữ vi phạm ngay trong nội dung yêu cầu. */
function Highlight({ text, marks }: { text: string; marks: string[] }) {
  const words = marks.filter(m => m && m.length <= 60 && text.toLowerCase().includes(m.toLowerCase()));
  if (!words.length) return <>{text}</>;
  const re = new RegExp(`(${words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
  return <>{text.split(re).map((part, i) => (i % 2 ? <mark key={i} className="rq-mark">{part}</mark> : <React.Fragment key={i}>{part}</React.Fragment>))}</>;
}

export function ReqQualityView({ workspaceId, docs }: { workspaceId: number | string; docs: Doc[] }) {
  const { allDocs, saved, refreshSaved } = useAnalysisData('req_quality');
  const pickable = allDocs.length ? allDocs : docs;
  const [sourceId, setSourceId] = useState('');
  const [result, setResult] = useState<ReqQualityResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [filter, setFilter] = useState<Filter>('problems');
  const [rule, setRule] = useState('');
  const [rewrites, setRewrites] = useState<Record<string, ReqRewrite | 'loading' | string>>({});

  useEffect(() => {
    if (sourceId || !pickable.length) return;
    setSourceId(docId(pickable.find(d => REQ_DOC.test(d.source_file)) ?? pickable[0]));
  }, [pickable]);

  const run = async () => {
    if (!sourceId) return;
    setBusy(true); setError(''); setNotice(''); setRewrites({}); setRule('');
    try { const r = await reviewRequirements(sourceId); setResult(r); setFilter(r.requirements.some(x => x.issues.length) ? 'problems' : 'all'); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const load = async (id: string) => {
    try { const r = await getReport(id); setResult(r.payload.result); setRewrites(r.payload.rewrites || {}); setNotice(`Đã mở báo cáo "${r.title}".`); } catch (e: any) { setError(e.message); }
  };
  const save = async () => {
    if (!result) return;
    const done = Object.fromEntries(Object.entries(rewrites).filter(([, v]) => typeof v === 'object'));
    try {
      if (canSaveReports()) await saveReport({ kind: 'req_quality', title: `Chất lượng yêu cầu · ${baseName(result.source_name)}`, workspace_id: String(workspaceId),
        payload: { result, rewrites: done } });
      setNotice('Đã lưu báo cáo.'); void refreshSaved();
    } catch (e: any) { setError(e.message); }
  };
  const exportCsv = () => {
    if (!result) return;
    const rows = [['Mã', 'Tiêu đề', 'Mức', 'Vấn đề', 'Đặc tính (29148)', 'Cụm chữ', 'Gợi ý sửa'].map(csvCell).join(',')];
    for (const r of result.requirements) {
      if (!r.issues.length) rows.push([r.req_id, r.title, 'Đạt', '', '', '', ''].map(csvCell).join(','));
      for (const i of r.issues) rows.push([r.req_id, r.title, SEV[i.severity].label, i.label, i.characteristic_label, i.evidence, i.suggestion].map(csvCell).join(','));
    }
    download(`chat-luong-yeu-cau-${baseName(result.source_name)}.csv`, '﻿' + rows.join('\n'), 'text/csv;charset=utf-8');
  };
  const suggest = async (r: ReqQualityRow) => {
    setRewrites(m => ({ ...m, [r.req_id]: 'loading' }));
    try {
      // chỉ gửi phần nội dung: dòng đầu là tiêu đề, không phải nghĩa vụ cần viết lại
      const body = r.text.includes('\n') ? r.text.slice(r.text.indexOf('\n') + 1) : r.text;
      const out = await rewriteRequirement(r.req_id, body.trim() || r.text, r.issues.map(i => `${i.label}: ${i.evidence}`));
      setRewrites(m => ({ ...m, [r.req_id]: out }));
    } catch (e: any) { setRewrites(m => ({ ...m, [r.req_id]: e.message })); }
  };

  const shown = useMemo(() => (result?.requirements ?? []).filter(r => {
    const problems = r.issues.some(i => i.severity !== 'info');
    if (filter === 'problems' && !r.issues.length) return false;
    if (filter === 'clean' && problems) return false;
    return !rule || r.issues.some(i => i.rule === rule);
  }), [result, filter, rule]);

  const s = result?.summary;
  const chars = useMemo(() => {
    if (!result) return [];
    const labels = Object.fromEntries(result.rules.map(r => [r.characteristic, r.characteristic_label]));
    return Object.entries(result.summary.by_characteristic).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ k, label: labels[k] ?? k, n }));
  }, [result]);
  const maxChar = Math.max(1, ...chars.map(c => c.n));
  const [sel, setSel] = useState('');
  const current = shown.some(r => r.req_id === sel) ? sel : shown[0]?.req_id;
  const pfRef = useRef<HTMLDivElement>(null);
  useProfileMotion(pfRef, `${result?.source_name ?? 'none'}|${s?.total ?? 0}`, '.wb-in');
  

  return (
    <main className="pg tl tone-trace">
      <div className="pg-col tv-col">
        <ToolHeader Icon={SpellCheck} title="Chất lượng yêu cầu"
          desc="Soát từng yêu cầu theo các đặc tính của ISO/IEC/IEEE 29148: rõ nghĩa, kiểm chứng được, đơn nhất, đầy đủ, không trùng. Kết quả chỉ ra đúng cụm chữ có vấn đề và cách sửa; có thể nhờ mô hình đề xuất cách viết lại."
          right={<SavedReportsSelect saved={saved} onLoad={load} disabled={busy} />} />
        {error && <p className="note is-error" role="alert">{error}</p>}
        {notice && <p className="note" role="status">{notice}</p>}

        <div className="wb" ref={pfRef}>
          <section className="wb-bar wb-in">
            <div className="wb-slot">
              <span className="wb-k">Tài liệu đặc tả</span>
              {pickable.length === 0 ? <b className="wb-v">Chưa có tài liệu</b> :
                <label className="wb-select"><span className="sr">Tài liệu đặc tả</span>
                  <select value={sourceId} onChange={e => setSourceId(e.target.value)} disabled={busy}>
                    {pickable.map(d => <option key={docId(d)} value={docId(d)}>{d.source_file.replace(/\.[^.]+$/, '').replace(/_/g, ' ')}</option>)}
                  </select><ChevronDown size={16} aria-hidden="true" /></label>}
            </div>
            <div className="wb-slot">
              <span className="wb-k">Chuẩn soát</span>
              <b className="wb-v">ISO/IEC/IEEE 29148<small>chạy tại máy, có ngay</small></b>
            </div>
            <div className="wb-go">
              {result && <button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />CSV</button>}
              {result && <button className="btn btn-ghost" onClick={save}><Save size={15} />Lưu</button>}
              <button className="btn btn-dark" onClick={run} disabled={busy || !sourceId}>{busy ? <span className="spin" /> : <SpellCheck size={15} />}{result ? 'Soát lại' : 'Soát chất lượng'}</button>
            </div>
            {result && s && s.total > 0 && <div className="lt-status" role="status">
              <span className="is-ok"><CheckCircle2 size={15} /><b>{s.clean}</b>/{s.total} yêu cầu đạt</span>
              <span className={s.errors ? 'is-bad' : ''}><XCircle size={15} /><b>{s.errors}</b> lỗi</span>
              <span className={s.warnings ? 'is-warn' : ''}><AlertTriangle size={15} /><b>{s.warnings}</b> cảnh báo</span>
              <span><Info size={15} /><b>{s.infos}</b> lưu ý</span>
              <span className="lt-bar" aria-hidden="true"><i className="is-ok" style={{ flexGrow: s.clean }} /><i className="is-warn" style={{ flexGrow: result.requirements.filter(r => !r.issues.some(x => x.severity === 'error') && r.issues.some(x => x.severity === 'warning')).length }} /><i className="is-bad" style={{ flexGrow: result.requirements.filter(r => r.issues.some(x => x.severity === 'error')).length }} /></span>
            </div>}
          </section>
        </div>

        {!result && !busy && pickable.length > 0 && <ProfilePreview title="Kết quả soát sẽ có" text="Bấm Soát chất lượng: kết quả có ngay vì bộ soát chạy tại máy theo luật cố định, cùng tài liệu luôn cho cùng kết quả."
          items={[[LayoutGrid, 'Bản đồ chất lượng', 'Mỗi yêu cầu một ô, tô theo mức vấn đề'], [Highlighter, 'Chỉ đúng cụm chữ', 'Từ mơ hồ, thiếu số đo, còn TBD được tô'], [Layers, 'Theo đặc tính 29148', 'Rõ nghĩa, kiểm chứng được, đơn nhất…'],
            [Sparkles, 'Đề xuất viết lại', 'Mô hình viết lại, không tự đặt con số'], [Download, 'Xuất CSV', 'Gửi cho người viết tài liệu'], [Save, 'Lưu báo cáo', 'Mở lại để so sau khi sửa']]} />}

        {result && s && (s.total === 0 ? <EmptyState Icon={ListChecks} title="Không tìm thấy yêu cầu có mã" text="Bộ soát nhận các dòng bắt đầu bằng mã như FR-01, NFR-02, UC-03, BR-04 (ở tiêu đề, gạch đầu dòng hoặc ô đầu của bảng)." /> : <>

          {chars.length > 0 && <section className="dz-card">
            <header><h3><Layers size={16} />Vấn đề theo đặc tính</h3><span className="is-muted">bấm để lọc</span></header>
            <ul className="rq-chars">{chars.map(c => {
              const rules = result.rules.filter(r => r.characteristic === c.k && result.summary.by_rule[r.rule]);
              return <li key={c.k}><span className="rq-char">{c.label}</span><i style={{ width: `${(c.n / maxChar) * 100}%` }} /><b>{c.n}</b>
                <span className="rq-rules">{rules.map(r => <button key={r.rule} className={`chip${rule === r.rule ? ' is-on' : ''}`} onClick={() => { setRule(rule === r.rule ? '' : r.rule); setFilter('all'); }}>{r.label} · {result.summary.by_rule[r.rule]}</button>)}</span></li>;
            })}</ul>
          </section>}

          <section className="dz-card">
            <header><h3><ListChecks size={16} />Từng yêu cầu</h3>
              <span className="rq-tools">
                <span className="tv-seg" role="tablist" aria-label="Lọc yêu cầu">
                  {([['problems', 'Có vấn đề'], ['clean', 'Đạt'], ['all', 'Tất cả']] as [Filter, string][]).map(([k, l]) =>
                    <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? 'is-on' : ''} onClick={() => setFilter(k)}>{l}</button>)}
                </span>
              </span>
            </header>
            {rule && <p className="is-muted">Đang lọc: {result.rules.find(r => r.rule === rule)?.label} · <button className="dp-link" onClick={() => setRule('')}>bỏ lọc</button></p>}
            {!shown.length ? <p className="is-muted">Không có yêu cầu nào trong mục này.</p> :
              <div className="lt">
              <nav className="lt-nav" aria-label="Danh sách yêu cầu">{shown.map(r => {
                const w = r.issues.some(x => x.severity === 'error') ? 'bad' : r.issues.some(x => x.severity === 'warning') ? 'warn' : r.issues.length ? 'muted' : 'ok';
                return <button key={r.req_id} type="button" className={`lt-row is-${w}${r.req_id === current ? ' is-on' : ''}`} onClick={() => setSel(r.req_id)} aria-current={r.req_id === current ? 'true' : undefined}>
                  <i /><b>{r.req_id}</b><span>{r.title}</span>{r.issues.length > 0 && <em>{r.issues.length}</em>}
                </button>;
              })}</nav>
              <ol className="rq-list lt-detail">{shown.filter(r => r.req_id === current).map(r => {
                const rw = rewrites[r.req_id];
                const worst = r.issues.some(i => i.severity === 'error') ? 'error' : r.issues.some(i => i.severity === 'warning') ? 'warning' : r.issues.length ? 'info' : null;
                return <li key={r.req_id} id={`rq-${r.req_id}`} className={`rq-item${worst ? ` is-${worst}` : ' is-clean'}`}>
                  <div className="rq-head"><b className="rq-id">{r.req_id}</b><span className="rq-title">{r.title}</span>
                    {worst ? <span className={`kb-status ${worst === 'error' ? 'is-error' : worst === 'warning' ? 'is-warn' : 'is-info'}`}>{r.issues.length} vấn đề</span>
                      : <span className="kb-status is-ok"><CheckCircle2 size={12} /> Đạt</span>}</div>
                  <p className="rq-text"><Highlight text={(r.text.replace(/^.*\n/, '') || r.text).replace(/^\s*(?:[-*+]|\|)\s*/gm, '').replace(/\s*\|\s*$/gm, '')} marks={r.issues.map(i => i.evidence)} /></p>
                  {r.issues.length > 0 && <ul className="rq-issues">{r.issues.map((i, k) => {
                    const S = SEV[i.severity];
                    return <li key={k} className={S.cls}><S.Icon size={14} aria-label={S.label} />
                      <div><b>{i.label}</b>{i.rule !== 'compound' && i.rule !== 'long' && <> · <q>{i.evidence}</q></>}<span className="rq-char-tag">{i.characteristic_label}</span>
                        <p>{i.message} <em>{i.suggestion}</em></p></div></li>;
                  })}</ul>}
                  {r.issues.some(i => i.severity !== 'info') && <div className="rq-rw">
                    {rw === undefined && <button className="btn btn-ghost is-sm" onClick={() => suggest(r)}><Sparkles size={14} />Đề xuất viết lại</button>}
                    {rw === 'loading' && <p className="is-muted"><span className="spin" /> Mô hình đang viết lại…</p>}
                    {typeof rw === 'string' && rw !== 'loading' && <p className="note is-error">{rw} <button className="dp-link" onClick={() => suggest(r)}>Thử lại</button></p>}
                    {typeof rw === 'object' && <div className="rq-suggest">
                      <p className="rq-suggest-k"><Sparkles size={13} /> Đề xuất của mô hình (cần người soát lại)</p>
                      <ul>{rw.rewrites.map((t, k) => <li key={k}><Highlight text={t} marks={rw.new_numbers} /></li>)}</ul>
                      {rw.missing?.length > 0 && <p className="note is-error">Mô hình chưa viết lại: {rw.missing.join('; ')}.</p>}
                      {rw.remaining?.length > 0 && <p className="note">Soát lại bản viết lại bằng cùng bộ luật, vẫn còn: {rw.remaining.join('; ')}.</p>}
                      {rw.new_numbers.length > 0 && <p className="note is-error">Mô hình đã thêm con số không có trong bản gốc: {rw.new_numbers.join(', ')}. Kiểm tra lại trước khi dùng.</p>}
                      {rw.open_questions.length > 0 && <><p className="rq-suggest-k">Tác giả cần quyết định</p><ul>{rw.open_questions.map((q, k) => <li key={k}>{q}</li>)}</ul></>}
                    </div>}
                  </div>}
                </li>;
              })}</ol>
              </div>}
          </section>
        </>)}
      </div>
    </main>
  );
}
