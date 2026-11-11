import React, { useEffect, useState } from 'react';
import { Copy, Check, ChevronLeft, ChevronRight, FileCheck } from 'lucide-react';
import { groupAgentResults } from '../utils/agentResults';
import { PipelineStep, PIPELINE_STEPS, STAGE_LABEL, stepEvents } from './ExecutionFlowGraph';
import { ModeExecutionResult } from '../types';
import { StudioModal } from './StudioModal';

interface NodeTraceModalProps {
  step: PipelineStep | null;
  isOpen: boolean;
  onClose: () => void;
  result: ModeExecutionResult | null;
  onSelectStep: (step: PipelineStep) => void;
}

type Tab = 'trace_data' | 'agent_subtasks' | 'mechanism';
const AGENTS = [
  { role: 'DatabaseAgent', label: 'Dữ liệu', tone: 'db' },
  { role: 'APIAgent', label: 'API', tone: 'api' },
  { role: 'SecurityAgent', label: 'Bảo mật', tone: 'sec' },
] as const;

// Tóm tắt một sự kiện CAP1 thành vài dòng dễ đọc; dữ liệu đầy đủ nằm ở phần "Dữ liệu gốc".
function summarize(e: any): [string, string][] {
  const out: [string, string][] = [];
  const list = (v: any[], f: (x: any) => string) => v.slice(0, 8).map(f).join('\n') + (v.length > 8 ? `\n… và ${v.length - 8} mục nữa` : '');
  if (Array.isArray(e.obligations) && e.obligations.length) out.push(['Nghĩa vụ', list(e.obligations, o => `${o.obligation_id}: ${o.description}`)]);
  if (Array.isArray(e.concerns) && e.concerns.length) out.push(['Mối quan tâm', list(e.concerns, c => `${c.concern_id} (${c.domain}): ${c.description}`)]);
  if (Array.isArray(e.tasks) && e.tasks.length) out.push(['Nhiệm vụ', list(e.tasks, t => `${t.task_id} [${t.domain}] ${t.goal}`)]);
  if (Array.isArray(e.execution_order)) out.push(['Thứ tự thực thi', e.execution_order.join(' → ')]);
  if ('valid' in e) out.push(['Hợp lệ', e.valid ? 'Có' : 'Không']);
  if (Array.isArray(e.errors) && e.errors.length) out.push(['Lỗi', list(e.errors, x => String(x))]);
  if (e.reason) out.push(['Lý do', String(e.reason)]);
  if (e.task_id) out.push(['Nhiệm vụ', String(e.task_id)]);
  if (Array.isArray(e.selected)) out.push(['Đoạn được giao', `${e.selected.length}${Array.isArray(e.candidates) ? ` / ${e.candidates.length} ứng viên` : ''}`]);
  if (Array.isArray(e.dropped) && e.dropped.length) out.push(['Đoạn bị loại', list(e.dropped, d => `${d.chunk_id}: ${d.reason}${d.tokens ? ` (${d.tokens} token)` : ''}`)]);
  if (e.limits) out.push(['Trần token theo nhiệm vụ', Object.entries(e.limits).map(([k, v]) => `${k}: ${v} (cần ${e.needs?.[k] ?? '?'})`).join('\n')]);
  if (e.result) out.push(['Kết quả', `${e.result.status} · ${String(e.result.answer || '').slice(0, 300)}`]);
  if (e.status && !e.result) out.push(['Trạng thái', String(e.status)]);
  if (e.error) out.push(['Lỗi', String(e.error)]);
  return out;
}

export const NodeTraceModal: React.FC<NodeTraceModalProps> = ({ step, isOpen, onClose, result, onSelectStep }) => {
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<Tab>('trace_data');
  useEffect(() => { setTab('trace_data'); }, [step?.id]); // mỗi bước mở lại ở thẻ dữ liệu
  if (!isOpen || !step) return null;

  const idx = PIPELINE_STEPS.findIndex(s => s.id === step.id);
  const prev = idx > 0 ? PIPELINE_STEPS[idx - 1] : null;
  const next = idx < PIPELINE_STEPS.length - 1 ? PIPELINE_STEPS[idx + 1] : null;
  const events = stepEvents(result?.raw, step);
  const agents = AGENTS.map(a => ({ ...a, r: groupAgentResults(result?.agent_results, a.role) }));
  const copyTrace = () => { navigator.clipboard.writeText(JSON.stringify(events, null, 2)); setCopied(true); setTimeout(() => setCopied(false), 2000); };
  const n = step.stepNumber;

  return (
    <StudioModal
      labelId="trace-title"
      icon={step.icon}
      title={<><span className="tr-num">Bước {n}</span>{step.title}</>}
      subtitle={step.tag}
      onClose={onClose}
      actions={<>
        <button className="icon-btn" disabled={!prev} onClick={() => prev && onSelectStep(prev)} aria-label={prev ? `Bước trước: ${prev.shortTitle}` : 'Không có bước trước'}><ChevronLeft size={18} /></button>
        <button className="icon-btn" disabled={!next} onClick={() => next && onSelectStep(next)} aria-label={next ? `Bước sau: ${next.shortTitle}` : 'Không có bước sau'}><ChevronRight size={18} /></button>
      </>}
      toolbar={<div className="tabs is-flush" role="tablist" aria-label="Nội dung bước">
        {([['trace_data', 'Dữ liệu bước'], ['agent_subtasks', 'Đầu ra tác tử'], ['mechanism', 'Vai trò nghiên cứu']] as [Tab, string][]).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'is-on' : ''} onClick={() => setTab(k)}>{l}</button>
        ))}
        <button className="tabs-copy" onClick={copyTrace} disabled={!events.length}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Đã sao chép' : 'Sao chép'}</button>
      </div>}
      footer={<>
        <span className="mo-note">Dữ liệu lấy nguyên từ bản ghi lượt chạy của backend CAP1.</span>
        <button className="btn btn-dark" onClick={onClose}>Đóng</button>
      </>}
    >
      {tab === 'trace_data' && <div className="tr">
        <p className="tr-lead">{step.description}</p>
        {!result ? <div className="empty is-big"><FileCheck size={22} /><b>Chưa có dữ liệu lượt chạy</b><span>Chạy một yêu cầu hoặc mở lại một lượt trong Lịch sử để xem dữ liệu thật của bước này.</span></div>
          : events.length === 0 ? <div className="empty is-big"><FileCheck size={22} /><b>Bước này không diễn ra trong lượt chạy</b><span>Điều kiện {result.raw?.condition ?? ''} không dùng bước này, hoặc lượt chạy đã dừng trước đó.</span></div>
          : events.map((e, i) => (
            <section key={i} className="tr-box">
              <h3>{STAGE_LABEL[e.stage] ?? e.stage}{e.phase ? ` · ${e.phase}` : ''}</h3>
              <dl className="tr-kv">{summarize(e).map(([k, v], j) => <div key={j}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
              <details><summary>Dữ liệu gốc</summary><pre className="chunk-pre">{JSON.stringify(e, null, 2)}</pre></details>
            </section>
          ))}
      </div>}

      {tab === 'agent_subtasks' && <div className="tr">{agents.map(a => (
        <section key={a.role} className="tr-box">
          <div className="tr-agent-head"><h3><i className={`dot is-${a.tone}`} />{a.label}<small>{a.r?.subtask_title || ''}</small></h3><span>Token theo tác tử: Chưa đo</span></div>
          <pre className="chunk-pre">{a.r?.content || `Lượt chạy này không có nhiệm vụ cho tác tử ${a.label}.`}</pre>
        </section>
      ))}</div>}

      {tab === 'mechanism' && <div className="tr">
        <section className="tr-box"><h3>Vai trò trong nghiên cứu</h3><p className="tr-sub">{step.scientificRole}</p></section>
        <div className="tr-agents is-2">
          <section><h3>Điều kiện A · Vanilla RAG</h3><p>Một lượt truy xuất, một lần sinh; không lập kế hoạch, không chia việc.</p></section>
          <section><h3>Điều kiện B · Multi-Agent cơ bản</h3><p>Có chia việc nhưng tắt lập kế hoạch có kiểm tra, chuẩn hóa và tối ưu ngữ cảnh.</p></section>
          <section><h3>Điều kiện C · Đầy đủ</h3><p>Bật lập kế hoạch (P), chuẩn hóa (N) và tối ưu ngữ cảnh (O).</p></section>
          <section><h3>C-P, C-N, C-O</h3><p>Bản C bỏ đi đúng một thành phần, để đo đóng góp riêng của từng thành phần.</p></section>
        </div>
      </div>}
    </StudioModal>
  );
};
