import React, { useState } from 'react';
import { Search, Zap, Copy, Check, AlertCircle } from 'lucide-react';
import { RetrievalTestResponse } from '../types';
import { testRetrieval } from '../services/api';
import { StudioModal } from './StudioModal';

interface RetrievalPlaygroundModalProps {
  isOpen: boolean;
  onClose: () => void;
  workspaceId: number | string;
  initialQuery?: string;
  onSearchingState?: (isSearching: boolean, query?: string, resultSummary?: string) => void;
}

const SAMPLE_PROMPTS = [
  { title: 'Kiến trúc & bảo mật hệ thống', query: 'Cơ chế xác thực, phân quyền truy cập và thiết kế API, cơ sở dữ liệu', domain: 'software' },
  { title: 'Quy chế nhân sự & nghỉ phép', query: 'Điều kiện nghỉ phép năm, giờ làm thêm và chế độ phúc lợi nhân viên', domain: 'hr' },
  { title: 'Ngân sách & chi phí', query: 'Quy định thanh toán, tạm ứng, công tác phí và kiểm soát ngân sách', domain: 'finance' },
  { title: 'Quy chế học vụ & tín chỉ', query: 'Điều kiện xét học bổng, cảnh báo học tập và chuẩn đầu ra tốt nghiệp', domain: 'education' },
];
const DOMAINS = [
  { id: 'all', label: 'Tất cả', dot: '' },
  { id: 'software', label: 'Phần mềm', dot: 'api' },
  { id: 'business', label: 'Kinh doanh', dot: 'db' },
  { id: 'marketing', label: 'Marketing', dot: 'sec' },
  { id: 'hr', label: 'Nhân sự', dot: 'db' },
  { id: 'finance', label: 'Tài chính', dot: 'api' },
  { id: 'education', label: 'Giáo dục', dot: 'sec' },
  { id: 'analyst', label: 'Số liệu', dot: 'db' },
];
const tagDot = (t: string) => /phần mềm|cntt|api|tài chính/i.test(t) ? 'api' : /kinh doanh|nhân sự|số liệu|csdl/i.test(t) ? 'db' : /marketing|giáo dục|bảo mật/i.test(t) ? 'sec' : 'none';

export const RetrievalPlaygroundModal: React.FC<RetrievalPlaygroundModalProps> = ({ isOpen, onClose, workspaceId, initialQuery = '', onSearchingState }) => {
  const [query, setQuery] = useState(initialQuery);
  const [topK, setTopK] = useState(4);
  const [domain, setDomain] = useState('all');
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<RetrievalTestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  React.useEffect(() => { if (initialQuery) setQuery(initialQuery); }, [initialQuery]);
  if (!isOpen) return null;

  const run = async (overrideQuery?: string, overrideDomain?: string, overrideK?: number) => {
    const q = (overrideQuery || query).trim();
    if (!q) { setError('Vui lòng nhập câu truy vấn thử nghiệm.'); return; }
    setIsLoading(true); setError(null); onSearchingState?.(true, q);
    try {
      const dom = overrideDomain !== undefined ? overrideDomain : domain;
      const res = await testRetrieval({ query: q, top_k: overrideK ?? topK, workspace_id: workspaceId, domain_tag: dom === 'all' ? undefined : dom });
      setResult(res);
      const maxSim = res.results.length > 0 ? res.results[0].similarity_percentage : 0;
      onSearchingState?.(false, q, `Đã tìm thấy ${res.results.length} phân đoạn (khớp cao nhất ${maxSim}%) trong ${res.latency_ms} ms.`);
    } catch (err: any) {
      setError(err.message || 'Thử nghiệm truy xuất Qdrant thất bại');
      onSearchingState?.(false, q);
    } finally { setIsLoading(false); }
  };
  const copy = (text: string, id: string) => { navigator.clipboard.writeText(text); setCopiedId(id); setTimeout(() => setCopiedId(null), 2000); };

  return (
    <StudioModal
      labelId="playground-title"
      icon={<Zap size={18} />}
      title="Thử truy xuất"
      subtitle="Xem hệ thống sẽ lấy những đoạn tài liệu nào cho một câu hỏi, trước khi giao cho các tác tử."
      onClose={onClose}
      toolbar={<div className="pg-form">
        <form className="pg-query" onSubmit={e => { e.preventDefault(); if (!isLoading) run(); }}>
          <Search size={16} />
          <label className="sr" htmlFor="playground-query">Câu truy vấn thử nghiệm</label>
          <input id="playground-query" data-autofocus value={query} onChange={e => setQuery(e.target.value)} placeholder="Nhập câu hỏi, tên bảng, hàm hoặc yêu cầu kỹ thuật…" />
          <button type="submit" className="btn btn-dark" disabled={isLoading || !query.trim()}>{isLoading ? <><span className="spin" />Đang tìm</> : 'Truy xuất'}</button>
        </form>
        <div className="pg-opts">
          <div className="chips"><span className="pg-label">Gợi ý</span>{SAMPLE_PROMPTS.map(p => (
            <button key={p.title} type="button" className="chip" onClick={() => { setQuery(p.query); setDomain(p.domain); run(p.query, p.domain); }}>{p.title}</button>
          ))}</div>
          <div className="pg-opt"><span className="pg-label">Số đoạn</span><div className="seg" role="group" aria-label="Số phân đoạn lấy về">{[2, 3, 4, 6, 8].map(k => (
            <button key={k} type="button" className={topK === k ? 'is-on' : ''} aria-pressed={topK === k} onClick={() => { setTopK(k); if (result) void run(undefined, undefined, k); }}>{k}</button>
          ))}</div></div>
          <div className="pg-opt"><span className="pg-label">Chuyên môn</span><div className="seg" role="group" aria-label="Lọc theo chuyên môn">{DOMAINS.map(d => (
            <button key={d.id} type="button" className={domain === d.id ? 'is-on' : ''} aria-pressed={domain === d.id} onClick={() => { setDomain(d.id); if (result) void run(undefined, d.id); }}>{d.dot && <i className={`dot is-${d.dot}`} />}{d.label}</button>
          ))}</div></div>
        </div>
      </div>}
      footer={<>
        <span className="mo-note">Độ tương đồng cosine đo trực tiếp từ Qdrant cho lượt tìm này.</span>
        <button className="btn btn-dark" onClick={onClose}>Đóng</button>
      </>}
    >
      {error && <div className="note is-error"><AlertCircle size={16} /><span>{error}</span></div>}
      {result && !isLoading && (
        <dl className="pg-stats">
          <div><dt>Thời gian tìm</dt><dd>{result.latency_ms} ms</dd></div>
          <div><dt>Khớp cao nhất</dt><dd>{result.results.length ? `${result.results[0].similarity_percentage}%` : 'Không có'}</dd></div>
          <div><dt>Đoạn lấy về</dt><dd>{result.results.length} / {result.top_k}</dd></div>
          <div><dt>Tổng đoạn trong kho</dt><dd>{result.total_indexed_chunks}</dd></div>
        </dl>
      )}
      {isLoading ? <p className="muted-line is-center"><span className="spin is-dark" />Đang so khớp với kho vector…</p>
        : !result ? <div className="empty is-big"><Search size={22} /><b>Sẵn sàng thử truy xuất</b><span>Nhập câu hỏi hoặc chọn một gợi ý để xem những đoạn tài liệu được lấy ra.</span></div>
        : result.results.length === 0 ? <div className="empty is-big"><AlertCircle size={22} /><b>Không có đoạn nào phù hợp</b><span>Thử bỏ bộ lọc chuyên môn hoặc đổi câu hỏi.</span></div>
        : <ol className="hits">{result.results.map((hit, i) => {
          const id = hit.chunk_id || String(i);
          const tone = hit.similarity_percentage >= 70 ? 'hi' : hit.similarity_percentage >= 40 ? 'mid' : 'lo';
          return (
            <li key={id} className="hit">
              <div className="hit-head">
                <span className="hit-rank">{i + 1}</span>
                <div className="hit-src"><b title={hit.source_file}>{hit.source_file}</b>
                  <span className="hit-tags">{hit.domain_tags.map(t => <span key={t} className="chunk-tag"><i className={`dot is-${tagDot(t)}`} />{t}</span>)}</span>
                </div>
                <div className={`hit-score is-${tone}`} title={`Cosine ${hit.score}`}><b>{hit.similarity_percentage}%</b><span><i style={{ width: `${Math.min(100, Math.max(4, hit.similarity_percentage))}%` }} /></span></div>
                <button className="chunk-copy" onClick={() => copy(hit.text, id)} aria-label={`Sao chép kết quả ${i + 1}`}>{copiedId === id ? <><Check size={14} />Đã chép</> : <><Copy size={14} />Chép</>}</button>
              </div>
              <pre className="chunk-pre">{hit.text}</pre>
            </li>
          );
        })}</ol>}
    </StudioModal>
  );
};
