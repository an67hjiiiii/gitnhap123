import React, { useState, useEffect } from 'react';
import { Copy, Check, ChevronLeft, ChevronRight, FileCheck } from 'lucide-react';
import { metric, percent } from '../utils/measurement';
import { groupAgentResults } from '../utils/agentResults';
import { TaskPlanTrace } from './TaskPlanTrace';
import { PipelineStep, PIPELINE_STEPS } from './ExecutionFlowGraph';
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
  { role: 'DatabaseAgent', label: 'Dữ liệu', tone: 'db', fallback: 'Lược đồ CSDL', duty: 'Cấu trúc bảng, khóa và ràng buộc.' },
  { role: 'APIAgent', label: 'API', tone: 'api', fallback: 'Đặc tả API', duty: 'Endpoint, dữ liệu vào/ra, idempotency.' },
  { role: 'SecurityAgent', label: 'Bảo mật', tone: 'sec', fallback: 'Bảo mật & RBAC', duty: 'Xác thực chữ ký, phân quyền.' },
] as const;
const dash = (v: number | null | undefined, unit: string) => v == null ? 'Chưa đo' : `${v.toLocaleString('vi-VN')}${unit}`;

export const NodeTraceModal: React.FC<NodeTraceModalProps> = ({ step, isOpen, onClose, result, onSelectStep }) => {
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<Tab>('trace_data');
  useEffect(() => { setTab('trace_data'); }, [step?.id]); // mỗi bước mở lại ở thẻ dữ liệu
  if (!isOpen || !step) return null;

  const idx = PIPELINE_STEPS.findIndex(s => s.id === step.id);
  const prev = idx > 0 ? PIPELINE_STEPS[idx - 1] : null;
  const next = idx < PIPELINE_STEPS.length - 1 ? PIPELINE_STEPS[idx + 1] : null;
  const agents = AGENTS.map(a => ({ ...a, r: groupAgentResults(result?.agent_results, a.role) }));
  const copyTrace = () => {
    const text = step.stepNumber === 6 ? result?.shared_brief || '' : step.stepNumber === 8 ? result?.final_answer || '' : JSON.stringify(result || {}, null, 2);
    navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000);
  };
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
        {([['trace_data', 'Dữ liệu bước'], ['agent_subtasks', 'Đầu ra tác tử'], ['mechanism', 'Cơ sở khoa học']] as [Tab, string][]).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'is-on' : ''} onClick={() => setTab(k)}>{l}</button>
        ))}
        <button className="tabs-copy" onClick={copyTrace} disabled={!result}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Đã sao chép' : 'Sao chép'}</button>
      </div>}
      footer={<>
        <span className="mo-note">Đề tài C1SE.27 · Đại học Duy Tân</span>
        <button className="btn btn-dark" onClick={onClose}>Đóng</button>
      </>}
    >
      {tab === 'trace_data' && <div className="tr">
        <p className="tr-lead">{step.description}</p>
        {!result ? <div className="empty is-big"><FileCheck size={22} /><b>Chưa có dữ liệu lượt chạy</b><span>Bạn đang xem mô tả cơ chế. Chạy điều phối để xem thông tin API trả về cho bước này.</span></div>
          : <p className="tr-hint">Thông tin nguyên mẫu từ API, chưa phải xác nhận thực nghiệm về hiệu quả của từng bước.</p>}

        {result && n === 1 && <>
          <dl className="pg-stats is-2"><div><dt>Phân đoạn tham chiếu</dt><dd>{result.retrieved_chunks_count ?? 0}</dd></div></dl>
          <section className="tr-box"><h3>Câu truy vấn lập kế hoạch</h3><pre className="chunk-pre">{result.subtasks?.[0]?.retrieval_query || 'API chưa cung cấp câu truy vấn lập kế hoạch.'}</pre></section>
        </>}

        {result && n === 2 && <section className="tr-box"><h3>{result.subtasks?.length ?? 0} nhiệm vụ sau phân rã</h3>
          <ol className="tr-tasks">{result.subtasks?.map((st, i) => (
            <li key={i}><div className="tr-task-head"><span className="tr-id">{st.id}</span><b>{st.title}</b><em>{st.agent_role}</em></div>
              <p>{st.description}</p>{st.retrieval_query && <small>Truy vấn: {st.retrieval_query}</small>}</li>
          ))}</ol></section>}

        {result && n === 3 && <section className="tr-box"><h3>Chuẩn hóa ranh giới nhiệm vụ</h3>
          <p className="tr-sub">Chỉ gộp các nhiệm vụ trùng nội dung sau chuẩn hóa, giữ yêu cầu và phụ thuộc. Chưa đánh giá mức tiết kiệm token.</p>
          <TaskPlanTrace result={result} /></section>}

        {result && n === 4 && <div className="tr-agents">{agents.map(a => (
          <section key={a.role}><h3><i className={`dot is-${a.tone}`} />{a.label}</h3><p>{a.duty}</p></section>
        ))}</div>}

        {result && n === 5 && <section className="tr-box"><h3>{result.retrieved_chunks_count || 0} phân đoạn được phân bổ</h3>
          <p className="tr-sub">Mỗi tác tử truy xuất riêng theo nhãn chuyên môn, để chỉ nhận tài liệu đúng phần mình phụ trách.</p></section>}

        {result && n === 6 && <>
          <dl className="pg-stats is-2"><div><dt>Token giảm (cần đối chứng)</dt><dd className={result.tokens_saved == null ? 'is-muted' : ''}>{metric(result.tokens_saved, ' token')}</dd></div>
            <div><dt>Tỷ lệ chi phí ngữ cảnh</dt><dd className={result.token_saving_ratio == null ? 'is-muted' : ''}>{percent(result.token_saving_ratio, 1)}</dd></div></dl>
          <section className="tr-box"><h3>Bản tóm tắt dùng chung (Shared Brief)</h3><pre className="chunk-pre">{result.shared_brief || 'Không có nội dung dùng chung.'}</pre></section>
        </>}

        {result && n === 7 && <>
          <dl className="pg-stats is-2"><div><dt>Tổng thời gian</dt><dd>{dash(result.latency_ms, ' ms')}</dd></div><div><dt>Tổng token</dt><dd>{dash(result.total_tokens, '')}</dd></div></dl>
          <div className="tr-agents">{agents.map(a => (
            <section key={a.role}><h3><i className={`dot is-${a.tone}`} />{a.label}</h3><p><b>{dash(a.r?.latency_ms, ' ms')}</b> · {dash(a.r?.tokens_used, ' token')}</p></section>
          ))}</div>
        </>}

        {result && n === 8 && <>
          <dl className="pg-stats is-2"><div><dt>Độ bao phủ nhiệm vụ</dt><dd className={result.task_coverage == null ? 'is-muted' : ''}>{percent(result.task_coverage)}</dd></div></dl>
          <section className="tr-box"><h3>Báo cáo tổng hợp</h3><pre className="chunk-pre is-prose">{result.final_answer || 'Chưa chạy điều phối.'}</pre></section>
        </>}
      </div>}

      {tab === 'agent_subtasks' && <div className="tr">{agents.map(a => (
        <section key={a.role} className="tr-box">
          <div className="tr-agent-head"><h3><i className={`dot is-${a.tone}`} />{a.label}<small>{a.r?.subtask_title || a.fallback}</small></h3><span>{dash(a.r?.latency_ms, ' ms')} · {dash(a.r?.tokens_used, ' token')}</span></div>
          <pre className="chunk-pre">{a.r?.content || `Chưa có dữ liệu từ tác tử ${a.label}.`}</pre>
        </section>
      ))}</div>}

      {tab === 'mechanism' && <div className="tr">
        <section className="tr-box"><h3>Vai trò trong đề tài C1SE.27</h3><p className="tr-sub">{step.scientificRole}</p></section>
        <div className="tr-agents is-2">
          <section><h3>Vanilla RAG (đối chứng 1)</h3><p>Một prompt chung, đưa toàn bộ top-K đoạn vào ngữ cảnh. Dễ bỏ sót yêu cầu khi ngữ cảnh dài.</p></section>
          <section><h3>Đa tác tử đơn giản (đối chứng 2)</h3><p>Có chia tác tử nhưng mỗi tác tử nhận lại cùng ngữ cảnh hoặc truy xuất lặp, có thể làm tăng chi phí token.</p></section>
        </div>
      </div>}
    </StudioModal>
  );
};
