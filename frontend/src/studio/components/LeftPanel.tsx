import React, { useRef, useState, useMemo } from 'react';
import { Plus, MoreHorizontal, Search, Sparkles, Zap, Trash2, Eye, FileText, Database, FileSpreadsheet, FileCode, Lock, UploadCloud } from 'lucide-react';
import { DocumentInfo, User } from '../types';
import { useDismiss } from './Header';

interface LeftPanelProps {
  documents: DocumentInfo[];
  onUpload: (file: File) => Promise<boolean | void>;
  onClear: () => Promise<void>;
  onSeedDocs: () => Promise<void>;
  onInspectDocument?: (doc: DocumentInfo) => void;
  onOpenPlayground?: () => void;
  onDeleteDocument?: (docId: number) => Promise<void>;
  isUploading: boolean;
  totalChunks: number;
  user?: User | null;
  isMobileDrawerOpen?: boolean;
  onCloseMobileDrawer?: () => void;
}

const ACCEPTED = /\.(pdf|md|markdown|sql|txt)$/i; // danh sách loại tệp hiện tại, không đổi

type Domain = 'all' | 'database' | 'api' | 'security';
const DOMAIN_LABEL: Record<Domain, string> = { all: 'Tất cả', database: 'Dữ liệu', api: 'API', security: 'Bảo mật' };

// Suy ra miền chính của tài liệu từ tên tệp và nhãn (giữ quy tắc cũ).
function domainOf(doc: DocumentInfo): Exclude<Domain, 'all'> | null {
  const fn = doc.source_file.toLowerCase();
  const tags = doc.domain_tags.map(t => t.toLowerCase());
  if (fn.includes('api')) return 'api';
  if (fn.includes('schema') || fn.includes('sql') || fn.includes('ledger') || fn.includes('db')) return 'database';
  if (fn.includes('security') || fn.includes('auth') || fn.includes('policy')) return 'security';
  if (tags.some(t => t.includes('api'))) return 'api';
  if (tags.some(t => t.includes('database') || t.includes('csdl'))) return 'database';
  if (tags.some(t => t.includes('security') || t.includes('bảo mật'))) return 'security';
  return null;
}

function FileIcon({ doc }: { doc: DocumentInfo }) {
  const ext = doc.source_file.split('.').pop()?.toLowerCase();
  const type = doc.file_type.toLowerCase();
  if (ext === 'sql' || type.includes('sql')) return <Database size={15} />;
  if (ext === 'pdf' || type.includes('pdf')) return <FileSpreadsheet size={15} />;
  if (ext === 'md' || type.includes('markdown')) return <FileText size={15} />;
  return <FileCode size={15} />;
}

// Kho tri thức hiển thị như một mục trong thanh bên.
export const LeftPanel: React.FC<LeftPanelProps> = ({
  documents, onUpload, onClear, onSeedDocs, onInspectDocument, onOpenPlayground, onDeleteDocument, isUploading, totalChunks, user,
}) => {
  // Mỗi người chỉ thấy và xóa được tài liệu của chính mình (máy chủ kiểm tra quyền sở hữu).
  const canDelete = !!user;
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [status, setStatus] = useState<{ text: string; tone: 'info' | 'ok' | 'error' } | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [domain, setDomain] = useState<Domain>('all');
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = React.useCallback(() => setMenuOpen(false), []);
  const menuRef = useDismiss(menuOpen, closeMenu);

  // Tải nhiều tệp: tối đa 2 tệp song song (Ollama không nghẽn), lỗi một tệp không dừng cả lượt.
  const processFiles = async (picked: File[]) => {
    const have = new Set(documents.map(d => d.source_file));
    const seen = new Set<string>();
    const todo: File[] = []; const skipped: string[] = []; const unsupported: string[] = [];
    for (const f of picked) {
      if (!ACCEPTED.test(f.name)) unsupported.push(f.name);
      else if (have.has(f.name) || seen.has(f.name)) skipped.push(f.name);
      else { seen.add(f.name); todo.push(f); }
    }
    const failed: string[] = []; let done = 0; let next = 0;
    const worker = async () => {
      while (next < todo.length) {
        const file = todo[next++];
        try { if ((await onUpload(file)) === false) failed.push(file.name); } catch { failed.push(file.name); }
        done += 1;
        setStatus({ text: `Đang tải ${Math.min(done + 1, todo.length)}/${todo.length}…`, tone: 'info' });
      }
    };
    if (todo.length) {
      setStatus({ text: `Đang tải 1/${todo.length}…`, tone: 'info' });
      await Promise.all([worker(), worker()]);
    }
    const parts = [`Đã tải ${todo.length - failed.length}/${todo.length}`];
    if (failed.length) parts.push(`lỗi: ${failed.join(', ')}`);
    if (skipped.length) parts.push(`bỏ qua vì đã có: ${skipped.join(', ')}`);
    if (unsupported.length) parts.push(`không hỗ trợ loại tệp: ${unsupported.join(', ')}`);
    setStatus({ text: parts.join(' · '), tone: failed.length ? 'error' : 'ok' });
    setTimeout(() => setStatus(null), failed.length || skipped.length || unsupported.length ? 8000 : 3500);
  };
  // Kéo-thả: nhận nhiều tệp và cả thư mục (nếu trình duyệt cho webkitGetAsEntry).
  const filesOf = async (dt: DataTransfer): Promise<File[]> => {
    const entries = Array.from(dt.items ?? []).map(i => (i as any).webkitGetAsEntry?.()).filter(Boolean);
    if (!entries.length) return Array.from(dt.files ?? []);
    const out: File[] = [];
    const walk = async (entry: any): Promise<void> => {
      if (entry.isFile) { out.push(await new Promise<File>((res, rej) => entry.file(res, rej))); return; }
      const reader = entry.createReader();
      for (;;) {
        const batch: any[] = await new Promise((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const child of batch) await walk(child);
      }
    };
    for (const entry of entries) await walk(entry);
    return out;
  };
  const onDrag = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true);
    else if (e.type === 'dragleave' && !e.currentTarget.contains(e.relatedTarget as Node)) setDragActive(false);
  };
  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragActive(false);
    const files = await filesOf(e.dataTransfer);
    if (files.length) await processFiles(files);
  };

  const docs = useMemo(() => documents.filter(doc =>
    (domain === 'all' || domainOf(doc) === domain || doc.domain_tags.some(t => t.toLowerCase().includes(domain))) &&
    doc.source_file.toLocaleLowerCase('vi').includes(searchTerm.trim().toLocaleLowerCase('vi'))
  ), [documents, domain, searchTerm]);

  return (
    <div className={`kb${dragActive ? ' is-drag' : ''}`} onDragEnter={onDrag} onDragOver={onDrag} onDragLeave={onDrag} onDrop={onDrop}>
      <input ref={fileInputRef} type="file" multiple accept=".pdf,.md,.markdown,.sql,.txt" hidden onChange={async e => { const picked = Array.from(e.target.files ?? []); e.target.value = ''; if (picked.length) await processFiles(picked); }} />
      <div className="kb-head">
        <span className="kb-title">Kho tri thức</span>
        <span className="kb-count" title={`${totalChunks} phân đoạn`}>{documents.length}</span>
        <button id="knowledge-upload-dropzone" className="icon-btn is-sm" onClick={() => fileInputRef.current?.click()} aria-label="Tải lên tài liệu kỹ thuật" title="Thêm tài liệu (PDF, Markdown, SQL, TXT)"><Plus size={16} /></button>
        <div className="sb-pop" ref={menuRef}>
          <button className="icon-btn is-sm" onClick={() => setMenuOpen(!menuOpen)} aria-label="Thêm thao tác với kho tri thức" aria-expanded={menuOpen} aria-haspopup="menu"><MoreHorizontal size={16} /></button>
          {menuOpen && (
            <div className="pop is-right" role="menu">
              {onOpenPlayground && <button role="menuitem" className="pop-item" onClick={() => { setMenuOpen(false); onOpenPlayground(); }}><Zap size={15} />Thử truy xuất</button>}
              <button role="menuitem" className="pop-item" onClick={() => { setMenuOpen(false); void onSeedDocs(); }}><Sparkles size={15} />Nạp tài liệu mẫu</button>
              {documents.length > 0 && (canDelete
                ? <button role="menuitem" className="pop-item is-danger" onClick={() => { setMenuOpen(false); void onClear(); }}><Trash2 size={15} />Xóa toàn bộ tài liệu</button>
                : <span className="pop-item is-off" title="Chỉ Trưởng nhóm hoặc Quản trị viên được xóa"><Lock size={15} />Xóa toàn bộ (không có quyền)</span>)}
            </div>
          )}
        </div>
      </div>

      {documents.length > 0 && <>
        <label className="kb-search"><Search size={14} /><span className="sr">Tìm trong tài liệu</span>
          <input id="knowledge-search" type="search" value={searchTerm} onChange={e => setSearchTerm(e.target.value)} placeholder="Tìm tài liệu" />
        </label>
        <div className="kb-filter" role="group" aria-label="Lọc theo chuyên môn">
          {(Object.keys(DOMAIN_LABEL) as Domain[]).map(d => <button key={d} aria-pressed={domain === d} className={domain === d ? 'is-on' : ''} onClick={() => setDomain(d)}>{DOMAIN_LABEL[d]}</button>)}
        </div>
      </>}

      {(status || isUploading) && <p className={`kb-status is-${status?.tone ?? 'info'}`} role="status">{status?.text ?? 'Đang trích xuất vector…'}</p>}

      <div className="kb-list">
        {documents.length === 0 ? (
          <button className="kb-empty" onClick={() => fileInputRef.current?.click()}>
            <UploadCloud size={20} />
            <b>Chưa có tài liệu</b>
            <span>Kéo thả tệp vào đây hoặc bấm để tải lên.</span>
            <span className="kb-empty-link" onClick={e => { e.stopPropagation(); void onSeedDocs(); }}>Dùng bộ tài liệu mẫu</span>
          </button>
        ) : docs.length === 0 ? <p className="kb-none">Không có tài liệu khớp.</p> : docs.map((doc, idx) => {
          const d = domainOf(doc);
          return (
            <div key={doc.id || idx} className="kb-row" title={doc.source_file}>
              <span className={`kb-ic is-${d ?? 'none'}`}><FileIcon doc={doc} /></span>
              <span className="kb-name">{doc.source_file}</span>
              <span className="kb-meta">{doc.status === 'processing' ? <i className="dot is-warn" title="Đang xử lý" /> : doc.status === 'failed' ? <i className="dot is-bad" title="Lỗi xử lý" /> : doc.chunks_count}</span>
              <span className="kb-acts">
                {onInspectDocument && <button onClick={() => onInspectDocument(doc)} aria-label={`Xem phân đoạn của ${doc.source_file}`} title="Xem phân đoạn"><Eye size={14} /></button>}
                {onDeleteDocument && doc.id && canDelete && (
                  <button className="is-danger" disabled={deletingId === doc.id} aria-label={`Xóa ${doc.source_file}`} title="Xóa tài liệu" onClick={async () => {
                    if (window.confirm(`Bạn có chắc muốn xóa tài liệu "${doc.source_file}" khỏi kho tri thức?`)) { setDeletingId(doc.id!); await onDeleteDocument(doc.id!); setDeletingId(null); }
                  }}><Trash2 size={14} /></button>
                )}
              </span>
            </div>
          );
        })}
      </div>
      {dragActive && <div className="kb-drop" aria-hidden="true"><UploadCloud size={22} />Thả tệp để thêm vào kho</div>}
    </div>
  );
};
