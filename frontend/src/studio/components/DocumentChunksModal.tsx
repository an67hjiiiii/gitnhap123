import { FileIcon } from './FileIcon';
import React, { useState, useEffect, useMemo } from 'react';
import { FileText, Database, FileSpreadsheet, FileCode, Copy, Check, Search, Zap, AlertCircle } from 'lucide-react';
import { DocumentInfo, ChunkInfo } from '../types';
import { getDocumentChunks } from '../services/api';
import { StudioModal } from './StudioModal';

interface DocumentChunksModalProps {
  document: DocumentInfo | null;
  isOpen: boolean;
  onClose: () => void;
  onOpenPlaygroundWithQuery?: (query: string) => void;
}

const domainOf = (tag: string) => {
  const t = tag.toLowerCase();
  if (t.includes('database') || t.includes('csdl')) return { key: 'db', label: 'Dữ liệu' };
  if (t.includes('api')) return { key: 'api', label: 'API' };
  if (t.includes('security') || t.includes('bảo mật')) return { key: 'sec', label: 'Bảo mật' };
  return { key: 'none', label: tag || 'Chung' };
};

export const DocumentChunksModal: React.FC<DocumentChunksModalProps> = ({ document, isOpen, onClose, onOpenPlaygroundWithQuery }) => {
  const [chunks, setChunks] = useState<ChunkInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [copiedId, setCopiedId] = useState<number | null>(null);

  useEffect(() => {
    if (!isOpen || !document?.id) { setChunks([]); setError(null); setQuery(''); return; }
    let active = true;
    setLoading(true); setError(null);
    getDocumentChunks(document.id).then(d => { if (active) setChunks(d); }).catch((err: any) => { if (active) setError(err.message || 'Không thể tải danh sách phân đoạn'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [isOpen, document]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? chunks.filter(c => c.content.toLowerCase().includes(q) || c.qdrant_point_id.toLowerCase().includes(q) || c.domain_tag.toLowerCase().includes(q)) : chunks;
  }, [chunks, query]);
  const totalTokens = useMemo(() => chunks.reduce((a, c) => a + (c.token_count || 0), 0), [chunks]);

  if (!isOpen || !document) return null;
  const ext = document.source_file.split('.').pop()?.toLowerCase();
  const copy = (text: string, id: number) => { navigator.clipboard.writeText(text); setCopiedId(id); setTimeout(() => setCopiedId(null), 2000); };

  return (
    <StudioModal
      labelId="chunks-title"
      icon={<FileIcon name={document.source_file} size={20} />}
      title={document.source_file}
      subtitle={<>{document.file_type}{document.file_size_kb ? ` · ${document.file_size_kb} KB` : ''} · {chunks.length} phân đoạn · {chunks.some(c => c.token_count != null) ? `~${totalTokens.toLocaleString('vi-VN')} token` : 'chưa đếm token'}</>}
      onClose={onClose}
      toolbar={<>
        <label className="search is-grow"><Search size={14} /><span className="sr">Tìm trong phân đoạn</span><input data-autofocus type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Tìm nội dung, mã vector hoặc nhãn" /></label>
        <span className="mo-count">{shown.length} / {chunks.length}</span>
      </>}
      footer={<>
        <span className="mo-note">Phân đoạn được lưu trong CSDL và Qdrant, dùng khi truy xuất theo nhiệm vụ.</span>
        {onOpenPlaygroundWithQuery && <button className="btn btn-ghost" onClick={() => { onClose(); onOpenPlaygroundWithQuery(document.source_file); }}><Zap size={15} />Thử truy xuất tệp này</button>}
        <button className="btn btn-dark" onClick={onClose}>Đóng</button>
      </>}
    >
      {loading ? <p className="muted-line is-center"><span className="spin is-dark" />Đang tải phân đoạn…</p>
        : error ? <div className="note is-error"><AlertCircle size={16} /><span>{error}</span></div>
        : shown.length === 0 ? <div className="empty">Không có phân đoạn phù hợp.</div>
        : <div className="chunk-list">{shown.map(c => {
          const tags = c.domain_tag.split(/[;|]\s*/).filter(Boolean).map(domainOf);
          return (
            <article key={c.id} className="chunk">
              <div className="chunk-head">
                <b>Đoạn {c.chunk_index + 1}</b>
                {(tags.length ? tags : [domainOf('')]).map(d => <span key={d.label} className="chunk-tag"><i className={`dot is-${d.key}`} />{d.label}</span>)}
                <span className="chunk-meta" title={c.qdrant_point_id}>{c.token_count == null ? `${c.content.length.toLocaleString('vi-VN')} ký tự` : `${c.token_count} token`} · {c.qdrant_point_id.slice(-8)}</span>
                <button className="chunk-copy" onClick={() => copy(c.content, c.id)} aria-label={`Sao chép đoạn ${c.chunk_index + 1}`}>{copiedId === c.id ? <><Check size={14} />Đã chép</> : <><Copy size={14} />Chép</>}</button>
              </div>
              <pre className="chunk-pre">{c.content}</pre>
            </article>
          );
        })}</div>}
    </StudioModal>
  );
};
