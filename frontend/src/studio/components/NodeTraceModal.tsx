// Cửa sổ "Hành trình câu trả lời": trục 8 bước bên trái, chi tiết bước đang chọn bên phải, dựng từ dữ liệu thật của lượt chạy.
import React, { useState } from 'react';
import { AlertTriangle, ArrowRight, Check, ChevronLeft, ChevronRight, Copy, FileText, Footprints, Info, Minus, X } from 'lucide-react';
import { PipelineStep, PIPELINE_STEPS } from './ExecutionFlowGraph';
import { ModeExecutionResult } from '../types';
import { StudioModal } from './StudioModal';
import { agentName } from './WorkspaceContext';
import { Markdown } from '../utils/markdown';
import { citeLabel, inlineCites, CiteDoc } from '../utils/citations';
import { Block, RUN_STATUS, skipReason, stepState, StepState, stepView, statusTone } from '../utils/stepExplain';

interface NodeTraceModalProps {
  step: PipelineStep | null;
  isOpen: boolean;
  onClose: () => void;
  result: ModeExecutionResult | null;
  onSelectStep: (step: PipelineStep) => void;
  docs?: CiteDoc[];
}

const STATE_LABEL: Record<StepState, string> = { done: 'Đã chạy', skip: 'Bỏ qua', stop: 'Dừng tại đây', none: 'Chưa có dữ liệu' };
const role = (d: string) => (d && d !== 'general' ? agentName(d) : 'Tổng hợp');

export const NodeTraceModal: React.FC<NodeTraceModalProps> = ({ step, isOpen, onClose, result, onSelectStep, docs = [] }) => {
  const [copied, setCopied] = useState(false);
  if (!isOpen || !step) return null;

  const raw = result?.raw;
  const idx = PIPELINE_STEPS.findIndex(s => s.id === step.id);
  const prev = idx > 0 ? PIPELINE_STEPS[idx - 1] : null;
  const next = idx < PIPELINE_STEPS.length - 1 ? PIPELINE_STEPS[idx + 1] : null;
  const states = PIPELINE_STEPS.map(s => stepState(raw, s));
  const state = states[idx];
  const view = raw && state !== 'skip' ? stepView(raw, step) : null;
  const ran = states.filter(s => s === 'done' || s === 'stop').length;
  const simple = raw?.events?.some((e: any) => e.stage === 'product_request_routing' && e.classification === 'SIMPLE_PROJECT_QUESTION');
  const nextRan = PIPELINE_STEPS.slice(idx + 1).find((_, i) => states[idx + 1 + i] === 'done');
  const copyTrace = () => { navigator.clipboard.writeText(JSON.stringify(raw?.events ?? [], null, 2)); setCopied(true); setTimeout(() => setCopied(false), 2000); };

  return (
    <StudioModal
      labelId="trace-title"
      icon={<Footprints size={18} />}
      title="Hành trình câu trả lời"
      subtitle={raw ? `${ran}/8 bước đã chạy · ${simple ? 'Đường tắt cho câu hỏi đơn giản' : raw.condition === 'A' ? 'Điều kiện A: tìm một lần rồi trả lời' : 'Lập kế hoạch đầy đủ'}` : 'Chưa có lượt chạy'}
      onClose={onClose}
      actions={<>
        <button className="icon-btn" disabled={!prev} onClick={() => prev && onSelectStep(prev)} aria-label={prev ? `Bước trước: ${prev.shortTitle}` : 'Không có bước trước'}><ChevronLeft size={18} /></button>
        <button className="icon-btn" disabled={!next} onClick={() => next && onSelectStep(next)} aria-label={next ? `Bước sau: ${next.shortTitle}` : 'Không có bước sau'}><ChevronRight size={18} /></button>
      </>}
      footer={<>
        <button type="button" className="btn btn-ghost is-sm jr-copy" onClick={copyTrace} disabled={!raw} title="Sao chép bản ghi gốc dạng JSON để gửi cho người phát triển">
          {copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Đã sao chép' : 'Sao chép bản ghi kỹ thuật'}</button>
        <button className="btn btn-dark" onClick={onClose}>Đóng</button>
      </>}
    >
      <div className="jr">
        {raw?.query && <p className="jr-q"><span>Câu hỏi</span><q>{raw.query}</q>
          {raw.status && <em className={`jr-badge is-${statusTone(raw.status)}`}>{RUN_STATUS[raw.status] ?? raw.status}</em>}</p>}
        <div className="jr-grid">
          <ol className="jr-rail" aria-label="Tám bước xử lý">
            {PIPELINE_STEPS.map((s, i) => (
              <li key={s.id} className={`is-${states[i]}${s.id === step.id ? ' is-on' : ''}`}>
                <button type="button" onClick={() => onSelectStep(s)} aria-current={s.id === step.id ? 'step' : undefined}>
                  <i aria-hidden>{states[i] === 'skip' ? <Minus size={14} /> : states[i] === 'stop' ? <X size={14} /> : s.icon}</i>
                  <span><b>{s.shortTitle}</b><small>{STATE_LABEL[states[i]]}</small></span>
                </button>
              </li>
            ))}
          </ol>

          <section className="jr-detail" aria-live="polite">
            <header>
              <span className="tr-num">Bước {step.stepNumber}</span>
              <h3>{step.title}</h3>
            </header>
            {!raw ? <p className="jr-summary">Chạy một câu hỏi hoặc mở lại một lượt trong Lịch sử để xem hệ thống đã làm gì ở bước này.</p>
              : state === 'skip' ? <div className="jr-skip">
                  <p className="jr-summary">{skipReason(raw, step, PIPELINE_STEPS)}</p>
                  {nextRan && <button type="button" className="btn btn-ghost is-sm" onClick={() => onSelectStep(nextRan)}>Tới bước đã chạy tiếp theo: {nextRan.shortTitle}<ArrowRight size={14} /></button>}
                </div>
              : view && <>
                  <p className="jr-summary">{view.summary}</p>
                  {view.stats.length > 0 && <div className="jr-stats">{view.stats.map((s, i) => <div key={i}><b>{s.value.toLocaleString('vi-VN')}</b><span>{s.label}</span></div>)}</div>}
                  {view.blocks.map((b, i) => <BlockView key={i} b={b} docs={docs} />)}
                </>}
            <details className="jr-why"><summary><Info size={14} />Vì sao có bước này?</summary><p>{step.description}</p><p>{step.scientificRole}</p></details>
          </section>
        </div>
      </div>
    </StudioModal>
  );
};

function DocChips({ ids, docs }: { ids: string[]; docs: CiteDoc[] }) {
  const groups = new Map<string, string[]>();
  ids.forEach(id => { const [title, part] = citeLabel(id, docs).split(' · '); const k = part ? title : 'Tài liệu khác'; groups.set(k, [...(groups.get(k) ?? []), part ?? title]); });
  return <ul className="jr-docs">{[...groups].map(([title, parts]) => (
    <li key={title}><FileText size={15} /><b title={title}>{title}</b><span>{parts.map((p, i) => <em key={i}>{p}</em>)}</span></li>
  ))}</ul>;
}

function BlockView({ b, docs }: { b: Block; docs: CiteDoc[] }) {
  switch (b.k) {
    case 'route': return <div className="jr-block">
      <div className="jr-route">
        <div className={b.simple ? 'is-on' : ''}><b>Đường tắt</b><span>Tìm tài liệu → trả lời thẳng</span>{b.simple && <em><Check size={12} />Đã chọn</em>}</div>
        <div className={b.simple ? '' : 'is-on'}><b>Lập kế hoạch</b><span>Chia việc → kiểm tra → nhiều tác tử</span>{!b.simple && <em><Check size={12} />Đã chọn</em>}</div>
      </div>
      <p className="jr-muted">{b.domains.length ? <>Lĩnh vực nhận ra: {b.domains.map(d => <span key={d} className="jr-chip">{role(d)}</span>)}</> : 'Câu hỏi không nhắc tới lĩnh vực chuyên môn cụ thể nào.'}</p>
    </div>;
    case 'quote': return <figure className="jr-block jr-quote"><figcaption>{b.label}</figcaption><blockquote>{b.text.length > 420 ? b.text.slice(0, 420) + '…' : b.text}</blockquote></figure>;
    case 'checklist': return b.items.length ? <div className="jr-block"><h4>{b.title}</h4><ul className="jr-check">{b.items.map((it, i) => (
      <li key={i} className={it.ok === true ? 'is-ok' : it.ok === false ? 'is-bad' : ''}><i>{it.ok === true ? <Check size={13} /> : it.ok === false ? <X size={13} /> : i + 1}</i>{it.text}</li>
    ))}</ul></div> : null;
    case 'funnel': {
      const rest = Math.max(0, b.found - b.used - b.dropped), pct = (n: number) => `${b.found ? (n / b.found) * 100 : 0}%`;
      return <div className="jr-block"><h4>Từ {b.found} đoạn tìm thấy đến {b.used} đoạn được đọc</h4>
        <div className="jr-funnel" role="img" aria-label={`${b.used} đoạn được dùng, ${b.dropped} đoạn bị loại vì quá dài, ${rest} đoạn kém liên quan hơn`}>
          <span className="is-used" style={{ width: pct(b.used) }} /><span className="is-drop" style={{ width: pct(b.dropped) }} /><span style={{ width: pct(rest) }} /></div>
        <p className="jr-legend"><span className="is-used">{b.used} được dùng</span>{b.dropped > 0 && <span className="is-drop">{b.dropped} bị loại vì quá dài</span>}{rest > 0 && <span>{rest} kém liên quan hơn</span>}</p>
      </div>;
    }
    case 'docs': return <div className="jr-block"><h4>Các đoạn được chọn</h4><DocChips ids={b.ids} docs={docs} /></div>;
    case 'tasks': return <div className="jr-block"><h4>Các nhiệm vụ</h4><ul className="jr-tasks">{b.tasks.map(t => (
      <li key={t.n}><header><i>{t.n}</i><span className="jr-chip">{role(t.domain)}</span>{t.after.length > 0 && <small>sau nhiệm vụ {t.after.join(', ')}</small>}</header><p>{t.goal}</p></li>
    ))}</ul></div>;
    case 'flow': return <div className="jr-block"><h4>Thứ tự chạy</h4><p className="jr-flow">{b.order.map((n, i) => <React.Fragment key={n}>{i > 0 && <ArrowRight size={14} />}<span>Nhiệm vụ {n}</span></React.Fragment>)}</p></div>;
    case 'attempts': return <div className="jr-block"><h4>Các lần kiểm tra và sửa</h4><ol className="jr-attempts">{b.items.map((a, i) => (
      <li key={i} className={a.ok ? 'is-ok' : 'is-bad'}><i>{a.ok ? <Check size={13} /> : <X size={13} />}</i><span>{a.label}</span><small>{a.ok ? 'Đạt' : 'Chưa đạt'}</small></li>
    ))}</ol></div>;
    case 'perTask': return <div className="jr-block"><h4>Tài liệu của từng nhiệm vụ</h4><ul className="jr-pertask">{b.rows.map(r => (
      <li key={r.n}><header><i>{r.n}</i><span className="jr-chip">{role(r.domain)}</span><small>{r.used}/{r.found} đoạn{r.limit != null ? ` · trần ${r.limit.toLocaleString('vi-VN')} token` : ''}</small></header>
        <div className="jr-funnel is-thin"><span className="is-used" style={{ width: `${r.found ? (r.used / r.found) * 100 : 0}%` }} /></div>
        {r.ids.length > 0 && <DocChips ids={r.ids} docs={docs} />}</li>
    ))}</ul></div>;
    case 'answers': return <div className="jr-block"><h4>Phần trả lời</h4><ul className="jr-answers">{b.items.map((a, i) => (
      <li key={i}><header>{a.n > 0 && <i>{a.n}</i>}<span className="jr-chip">{role(a.domain)}</span><em className={`jr-badge is-${statusTone(a.status)}`}>{RUN_STATUS[a.status] ?? a.status}</em>
        <small>trích {a.cites} đoạn{a.invalid ? ` · loại ${a.invalid} trích dẫn sai` : ''}</small></header>
        <details open={b.items.length === 1}><summary>Xem nội dung</summary><div className="md"><Markdown text={inlineCites(a.answer, docs)} /></div></details></li>
    ))}</ul></div>;
    case 'note': return <p className={`jr-note is-${b.tone}`}>{b.tone === 'ok' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{b.text}</span></p>;
  }
}
