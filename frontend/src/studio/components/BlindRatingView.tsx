// Chấm mù: người chấm (tài khoản khác người tạo) nhập mã, chấm từng câu trả lời mà không biết do cách nào tạo ra.
// Người tạo đợt lấy câu trả lời từ một lượt đánh giá đã lưu, gửi mã cho người chấm, rồi xem thống kê khi có điểm.
import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, BarChart3, Check, Copy, Download, EyeOff, ListChecks, LogIn, Plus, RefreshCw, Scale, StickyNote, Trash2, Users } from 'lucide-react';
import {
  createRatingStudy, deleteRatingStudy, getReport, joinRating, listRatingStudies, listReports, RatingItem, RatingResults,
  ratingResults, RatingScore, RatingStudy, saveRating, SavedReport,
} from '../services/api';
import { Markdown } from '../utils/markdown';
import { csvCell, download, EmptyState, ToolHeader } from './analysis/shared';
import './profile/tools.css';

const CRITERIA: [keyof Omit<RatingScore, 'key_points' | 'fabricated' | 'note'>, string, string][] = [
  ['correct', 'Đúng', 'Thông tin khớp tài liệu, không sai sự thật'],
  ['complete', 'Đủ ý', 'Trả lời hết các phần của yêu cầu'],
  ['grounded', 'Có căn cứ', 'Dựa vào tài liệu, có dẫn nguồn đúng chỗ'],
  ['useful', 'Hữu ích', 'Dùng được ngay cho công việc'],
];
const COND: Record<string, string> = { A: 'A · Vanilla RAG', B: 'B · Multi-Agent cơ bản', C: 'C · Đề xuất', 'C-P': 'C-P', 'C-N': 'C-N', 'C-O': 'C-O' };
const num = (v: number | null | undefined, d = 2) => (v == null ? '—' : v.toLocaleString('vi-VN', { maximumFractionDigits: d }));
const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`);
const empty = (n: number): RatingScore => ({ key_points: Array(n).fill(false), correct: 0, complete: 0, grounded: 0, useful: 0, fabricated: false, note: '' });

export const BlindRatingView: React.FC = () => {
  const [code, setCode] = useState('');
  const [session, setSession] = useState<{ title: string; code: string; items: RatingItem[]; mine: Record<string, RatingScore> } | null>(null);
  const [studies, setStudies] = useState<RatingStudy[]>([]);
  const [results, setResults] = useState<RatingResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => listRatingStudies().then(setStudies).catch(e => setError(e.message));
  useEffect(() => { void refresh(); }, []);

  const join = async () => {
    setBusy(true); setError(null);
    try { setSession(await joinRating(code)); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const openResults = async (id: string) => { setError(null); try { setResults(await ratingResults(id)); } catch (e: any) { setError(e.message); } };

  if (session) return <Rater session={session} onExit={() => setSession(null)} />;
  if (results) return <Results data={results} onBack={() => setResults(null)} onRefresh={() => openResults(results.study_id)} />;

  return (
    <main className="pg tl tone-evaluation">
      <div className="pg-col tv-col">
        <ToolHeader Icon={EyeOff} title="Chấm mù" desc="Người chấm độc lập đánh giá câu trả lời mà không biết câu đó do cách nào (A, B hay C) tạo ra. Hệ thống tự tính điểm theo từng cách, so sánh có kiểm định thống kê và độ đồng thuận giữa người chấm." />
        {error && <p className="note is-error" role="alert">{error}</p>}
        <div className="dz-grid">
          <section className="dz-card">
            <header><h3><LogIn size={16} />Tham gia chấm</h3></header>
            <p className="is-muted">Nhập mã do người tạo đợt gửi. Bạn sẽ thấy câu hỏi, câu trả lời và các ý cần có, không thấy tên phương pháp.</p>
            <form className="br-join" onSubmit={e => { e.preventDefault(); void join(); }}>
              <input value={code} onChange={e => setCode(e.target.value.toUpperCase())} maxLength={12} placeholder="Mã đợt chấm, ví dụ K7P2QX" aria-label="Mã đợt chấm" />
              <button className="btn btn-dark" disabled={code.trim().length < 4 || busy}>{busy ? <span className="spin" /> : <ArrowRight size={15} />}Bắt đầu chấm</button>
            </form>
          </section>
          <CreateStudy onCreated={refresh} />
        </div>
        <section className="dz-card">
          <header><h3><ListChecks size={16} />Đợt chấm của tôi</h3><button className="btn btn-ghost is-sm" onClick={refresh}><RefreshCw size={14} />Làm mới</button></header>
          {studies.length === 0 ? <EmptyState Icon={EyeOff} title="Chưa có đợt chấm" text="Tạo đợt từ một lượt đánh giá đã lưu ở Phòng đánh giá, rồi gửi mã cho ít nhất hai người chấm." /> :
            <div className="tbl tv-table"><table><thead><tr><th>Đợt</th><th>Mã</th><th>Câu trả lời</th><th>Người chấm</th><th>Lượt chấm</th><th></th></tr></thead><tbody>
              {studies.map(s => <tr key={s.study_id}>
                <td><b>{s.title}</b><small className="dp-ctx">{new Date(s.created_at).toLocaleString('vi-VN')}{s.failed ? ` · ${s.failed} lượt thất bại không đưa vào chấm` : ''}</small></td>
                <td><CodeChip code={s.code} /></td><td>{s.items}</td><td>{s.raters}</td>
                <td>{s.ratings}/{s.items * Math.max(1, s.raters)}</td>
                <td className="br-acts"><button className="btn btn-dark is-sm" onClick={() => openResults(s.study_id)}><BarChart3 size={14} />Kết quả</button>
                  <button className="icon-btn is-sm" aria-label={`Xóa đợt ${s.title}`} onClick={async () => { if (confirm(`Xóa đợt "${s.title}" và mọi điểm đã chấm?`)) { await deleteRatingStudy(s.study_id).catch(e => setError(e.message)); void refresh(); } }}><Trash2 size={15} /></button></td>
              </tr>)}
            </tbody></table></div>}
        </section>
      </div>
    </main>
  );
};

function CodeChip({ code }: { code: string }) {
  const [ok, setOk] = useState(false);
  return <button type="button" className="br-code" onClick={() => { void navigator.clipboard.writeText(code); setOk(true); setTimeout(() => setOk(false), 1500); }} title="Sao chép mã">
    {code}{ok ? <Check size={13} /> : <Copy size={13} />}</button>;
}

// Tạo đợt từ lượt đánh giá đã lưu (Phòng đánh giá): mỗi câu trả lời kèm các ý chính của câu hỏi.
function CreateStudy({ onCreated }: { onCreated: () => void }) {
  const [saved, setSaved] = useState<SavedReport[]>([]);
  const [pick, setPick] = useState('');
  const [title, setTitle] = useState('');
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { listReports('evaluation').then(setSaved).catch(() => setSaved([])); }, []);
  const create = async () => {
    setBusy(true); setMsg(null);
    try {
      const st = (await getReport(pick)).payload;
      const points = Object.fromEntries((st.set?.questions || []).map((q: any) => [q.id, q.points || []]));
      const items = Object.values(st.items || {}).filter((it: any) => it.run_id).map((it: any) => ({ run_id: it.run_id, key_points: points[it.qid] || [] }));
      if (!items.length) throw new Error('Lượt đánh giá này chưa có câu trả lời nào.');
      const r = await createRatingStudy(title.trim() || saved.find(s => s.report_id === pick)?.title || 'Đợt chấm', items);
      setMsg({ ok: true, text: `Đã tạo đợt với ${r.items} câu trả lời${r.failed_runs ? ` (${r.failed_runs} lượt thất bại tính điểm thấp nhất, không cần chấm)` : ''}. Gửi mã ${r.code} cho người chấm.` });
      onCreated();
    } catch (e: any) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  };
  return <section className="dz-card">
    <header><h3><Plus size={16} />Tạo đợt chấm</h3></header>
    <label className="tv-field"><span>Lấy câu trả lời từ lượt đánh giá đã lưu</span>
      <select value={pick} onChange={e => setPick(e.target.value)}>
        <option value="">{saved.length ? 'Chọn lượt đánh giá…' : 'Chưa có lượt đánh giá đã lưu'}</option>
        {saved.map(s => <option key={s.report_id} value={s.report_id}>{s.title}</option>)}
      </select></label>
    <label className="tv-field"><span>Tên đợt (không bắt buộc)</span><input value={title} onChange={e => setTitle(e.target.value)} maxLength={200} placeholder="Ví dụ: Chấm mù A/B/C tháng 11" /></label>
    <button className="btn btn-dark" disabled={!pick || busy} onClick={create}>{busy ? <span className="spin" /> : <Plus size={15} />}Tạo đợt và lấy mã</button>
    {msg && <p className={`note ${msg.ok ? 'is-ok' : 'is-error'}`}>{msg.text}</p>}
    <p className="tl-note">Thứ tự câu trả lời được xáo riêng cho từng người chấm. Người tạo đợt không chấm được đợt của mình.</p>
  </section>;
}

function Rater({ session, onExit }: { session: { title: string; code: string; items: RatingItem[]; mine: Record<string, RatingScore> }; onExit: () => void }) {
  const [mine, setMine] = useState(session.mine);
  const [idx, setIdx] = useState(() => Math.max(0, session.items.findIndex(it => !session.mine[it.item_id])));
  const item = session.items[idx];
  const [draft, setDraft] = useState<RatingScore>(() => session.mine[item?.item_id] ?? empty(item?.key_points.length ?? 0));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (item) setDraft(mine[item.item_id] ?? empty(item.key_points.length)); setError(null); }, [idx]); // eslint-disable-line react-hooks/exhaustive-deps
  const done = Object.keys(mine).length;
  const complete = CRITERIA.every(([k]) => draft[k] >= 1);
  const save = async (next: number) => {
    if (!complete) { setError('Chọn điểm 1–5 cho cả bốn tiêu chí.'); return; }
    setSaving(true); setError(null);
    try { await saveRating(session.code, item.item_id, draft); setMine(m => ({ ...m, [item.item_id]: draft })); if (next < session.items.length) setIdx(next); }
    catch (e: any) { setError(e.message); } finally { setSaving(false); }
  };
  if (!item) return null;
  return (
    <main className="pg tl tone-evaluation">
      <div className="pg-col tv-col">
        <div className="br-top">
          <button className="btn btn-ghost is-sm" onClick={onExit}><ArrowLeft size={14} />Thoát</button>
          <b>{session.title}</b>
          <span className="is-muted">Đã chấm {done}/{session.items.length}</span>
        </div>
        <div className="br-bar" aria-hidden="true"><i style={{ width: `${(done / session.items.length) * 100}%` }} /></div>
        <section className="dz-card br-item">
          <header><h3>Câu {idx + 1}/{session.items.length}</h3>{mine[item.item_id] && <span className="cht-status is-complete">Đã chấm</span>}</header>
          <p className="br-q">{item.question}</p>
          <div className="md br-a"><Markdown text={item.answer} /></div>
        </section>
        <section className="dz-card br-form">
          {item.key_points.length > 0 && <fieldset><legend>Câu trả lời có nêu đúng các ý sau không?</legend>
            {item.key_points.map((kp, i) => <label key={i} className="br-kp"><input type="checkbox" checked={draft.key_points[i] || false}
              onChange={e => setDraft(d => ({ ...d, key_points: d.key_points.map((x, j) => (j === i ? e.target.checked : x)) }))} />{kp}</label>)}
            <small className="is-muted">Tính là có khi câu trả lời nêu đúng ý, kể cả bằng lời khác.</small></fieldset>}
          {CRITERIA.map(([k, label, hint]) => <div key={k} className="br-crit">
            <div><b>{label}</b><small>{hint}</small></div>
            <div className="tv-seg" role="radiogroup" aria-label={label}>
              {[1, 2, 3, 4, 5].map(v => <button key={v} type="button" role="radio" aria-checked={draft[k] === v} className={draft[k] === v ? 'is-on' : ''} onClick={() => setDraft(d => ({ ...d, [k]: v }))}>{v}</button>)}
            </div>
          </div>)}
          <label className="br-kp"><input type="checkbox" checked={draft.fabricated} onChange={e => setDraft(d => ({ ...d, fabricated: e.target.checked }))} />Có thông tin sai hoặc không có trong tài liệu (bịa)</label>
          <label className="tv-field"><span>Ghi chú (không bắt buộc)</span><textarea rows={2} value={draft.note || ''} maxLength={1000} onChange={e => setDraft(d => ({ ...d, note: e.target.value }))} /></label>
          {error && <p className="note is-error" role="alert">{error}</p>}
          <div className="br-nav">
            <button className="btn btn-ghost" disabled={idx === 0} onClick={() => setIdx(idx - 1)}><ArrowLeft size={15} />Câu trước</button>
            <button className="btn btn-dark" disabled={saving} onClick={() => save(idx + 1)}>{saving ? <span className="spin" /> : <Check size={15} />}{idx + 1 < session.items.length ? 'Lưu và sang câu tiếp' : 'Lưu'}</button>
          </div>
          {done === session.items.length && <p className="note is-ok">Bạn đã chấm xong toàn bộ. Cảm ơn! Có thể quay lại sửa điểm bất kỳ lúc nào.</p>}
        </section>
      </div>
    </main>
  );
}

function Results({ data, onBack, onRefresh }: { data: RatingResults; onBack: () => void; onRefresh: () => void }) {
  const conds = Object.keys(data.conditions).sort();
  const cmps = useMemo(() => Object.entries(data.comparisons).filter(([k]) => k.endsWith('_overall') || k.endsWith('_kp_coverage')), [data]);
  const exportCsv = () => download(`cham-mu_${data.code}.csv`, ['Điều kiện,Mục đã chấm,Lượt thất bại,Độ phủ ý chính,Điểm tổng (1-5),Đúng,Đủ ý,Có căn cứ,Hữu ích,Tỷ lệ có thông tin bịa',
    ...conds.map(c => { const t = data.conditions[c]; return [c, t.rated_items, t.failed_runs, t.kp_coverage.mean, t.overall.mean, t.correct, t.complete, t.grounded, t.useful, t.fabricated_rate].map(csvCell).join(','); })].join('\n'), 'text/csv');
  return (
    <main className="pg tl tone-evaluation">
      <div className="pg-col tv-col">
        <div className="br-top"><button className="btn btn-ghost is-sm" onClick={onBack}><ArrowLeft size={14} />Danh sách đợt</button><b>{data.title}</b><CodeChip code={data.code} />
          <span className="br-acts"><button className="btn btn-ghost is-sm" onClick={onRefresh}><RefreshCw size={14} />Làm mới</button><button className="btn btn-ghost is-sm" onClick={exportCsv}><Download size={14} />CSV</button></span></div>
        <div className="dp-kpis is-4">
          <div><b>{data.raters.length}</b><span>người chấm</span></div>
          <div><b>{data.rated_items}/{data.items}</b><span>câu trả lời đã có điểm</span></div>
          <div className={data.agreement_alpha.correct == null ? '' : data.agreement_alpha.correct >= 0.667 ? 'is-ok' : 'is-mid'}><b>{num(data.agreement_alpha.correct)}</b><span>đồng thuận (alpha, tiêu chí Đúng)</span></div>
          <div><b>{pct(data.auto_vs_human_agreement)}</b><span>máy chấm ý chính khớp người</span></div>
        </div>
        {data.raters.length < 2 && <p className="note is-warn">Cần ít nhất 2 người chấm độc lập để tính độ đồng thuận và để kết quả đủ tin cậy.</p>}
        {data.rated_items === 0 ? <EmptyState Icon={BarChart3} title="Chưa có điểm" text={`Gửi mã ${data.code} cho người chấm. Kết quả hiện ở đây khi có điểm.`} /> : <>
          <section className="dz-card"><header><h3><BarChart3 size={16} />Điểm theo cách trả lời</h3></header>
            <div className="tbl tv-table"><table><thead><tr><th>Cách</th><th>Đã chấm</th><th>Thất bại</th><th>Độ phủ ý chính</th><th>Điểm tổng (1–5)</th><th>Đúng</th><th>Đủ ý</th><th>Có căn cứ</th><th>Hữu ích</th><th>Có thông tin bịa</th></tr></thead><tbody>
              {conds.map(c => { const t = data.conditions[c]; return <tr key={c}><td><b>{COND[c] ?? c}</b></td><td>{t.rated_items}</td><td>{t.failed_runs}</td>
                <td>{pct(t.kp_coverage.mean)}{t.kp_coverage.ci95 ? <small className="dp-ctx">[{pct(t.kp_coverage.ci95[0])}–{pct(t.kp_coverage.ci95[1])}]</small> : null}</td>
                <td>{num(t.overall.mean)}</td><td>{num(t.correct)}</td><td>{num(t.complete)}</td><td>{num(t.grounded)}</td><td>{num(t.useful)}</td><td>{pct(t.fabricated_rate)}</td></tr>; })}
            </tbody></table></div>
            <p className="tl-note">Điểm của một câu trả lời là trung bình các người chấm. Lượt thất bại không đưa cho người chấm; khi so sánh được tính độ phủ 0 và điểm tổng 1.</p>
          </section>
          {cmps.length > 0 && <section className="dz-card"><header><h3><Scale size={16} />C so với các cách khác (cặp theo câu hỏi)</h3></header>
            <div className="tbl tv-table"><table><thead><tr><th>So sánh</th><th>Chỉ số</th><th>Số cặp</th><th>Chênh lệch TB</th><th>p (Wilcoxon)</th><th>Cohen dz</th></tr></thead><tbody>
              {cmps.map(([k, r]) => { const m = k.match(/^C_vs_(.+)_(overall|kp_coverage)$/)!; return <tr key={k}><td>C – {m[1]}</td><td>{m[2] === 'overall' ? 'Điểm tổng' : 'Độ phủ ý chính'}</td><td>{r.pairs}</td>
                <td>{r.mean_diff == null ? '—' : m[2] === 'overall' ? num(r.mean_diff) : `${num(r.mean_diff * 100, 1)} điểm %`}</td><td>{r.wilcoxon.p_value == null ? '—' : num(r.wilcoxon.p_value, 3)}</td><td>{num(r.cohens_dz)}</td></tr>; })}
            </tbody></table></div>
            <p className="tl-note">p &lt; 0,05 mới coi là khác biệt có ý nghĩa; nhiều phép so sánh cùng lúc nên hiệu chỉnh (ví dụ Holm) trước khi kết luận.</p>
          </section>}
          <section className="dz-card"><header><h3><Users size={16} />Độ đồng thuận giữa người chấm (Krippendorff alpha)</h3></header>
            <div className="ov-chips">{Object.entries(data.agreement_alpha).map(([k, v]) => <span key={k}>{CRITERIA.find(c => c[0] === k)?.[1] ?? 'Độ phủ ý chính'}<b>{num(v)}</b></span>)}</div>
            <p className="tl-note">Từ 0,8 trở lên: tin cậy; 0,667–0,8: tạm chấp nhận; dưới 0,667: người chấm hiểu tiêu chí khác nhau, nên thống nhất lại cách chấm.</p>
          </section>
          {data.notes.length > 0 && <section className="dz-card"><header><h3><StickyNote size={16} />Ghi chú của người chấm</h3></header>
            <ul className="br-notes">{data.notes.map((n, i) => <li key={i}><span className="chip">{COND[n.condition] ?? n.condition}</span>{n.note}</li>)}</ul></section>}
        </>}
      </div>
    </main>
  );
}
