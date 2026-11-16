import React, { useRef, useState, useMemo } from 'react';
import { Plus, MoreHorizontal, Search, Sparkles, Zap, Trash2, Eye, FileText, Database, FileSpreadsheet, FileCode, Lock, UploadCloud } from 'lucide-react';
import { DocumentInfo, User } from '../types';
import { useDismiss } from './Header';
import { ClassBadge } from './OrgView';
import { CLASS_HINT, CLASS_LABEL, Classification, MemberLevel, SETTABLE } from '../services/api';

interface LeftPanelProps {
  documents: DocumentInfo[];
  onUpload: (file: File, publish?: { classification: Classification }) => Promise<void>;
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
  /** cấp bậc trong không gian tổ chức đang mở; có thì phải chọn mức mật trước khi tải */
  orgLevel?: MemberLevel;
}

type Domain = 'all' | 'database' | 'api' | 'security';
const DOMAIN_LABEL: Record<Domain, string> = { all: 'Tất cả', database: 'Dữ liệu', api: 'API', security: 'Bảo mật' };

// Suy ra miền chính của tài liệu từ tên tệp và nhãn (giữ quy tắc cũ).
function domainOf(doc: DocumentInfo): Exclude<Domain, 'all'> | null {
  // Bỏ dấu và dấu nối để tên tiếng Việt ("Thiết kế CSDL", "chinh_sach_bao_mat") cũng nhận ra được.
  const fn = ' ' + doc.source_file.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/gi, 'd').toLowerCase().replace(/[^a-z0-9]+/g, ' ') + ' ';
  const tags = doc.domain_tags.map(t => t.toLowerCase());
  if (/ (api|endpoint|webhook) /.test(fn)) return 'api';
  if (/ (schema|sql|ledger|db|database|csdl)| co so du lieu /.test(fn)) return 'database';
  if (/ (security|auth|policy)| bao mat | phan quyen | xac thuc /.test(fn)) return 'security';
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
  documents, onUpload, onClear, onSeedDocs, onInspectDocument, onOpenPlayground, onDeleteDocument, isUploading, totalChunks, user, orgLevel,
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
  // mức mật chọn TRƯỚC khi tải: tài liệu Mật không bao giờ hiện cho phòng ban dù một khoảnh khắc
  const levels = orgLevel ? SETTABLE[orgLevel] : [];
  const [level, setLevel] = useState<Classification>(orgLevel === 'EXECUTIVE' ? 'COMPANY' : 'DEPARTMENT');
  // đổi không gian (cấp bậc khác) thì về mặc định an toàn: Ban giám đốc thường không thuộc phòng nên mặc định Toàn công ty
  React.useEffect(() => { if (orgLevel) setLevel(orgLevel === 'EXECUTIVE' ? 'COMPANY' : 'DEPARTMENT'); }, [orgLevel]);

  const processFile = async (file: File) => {
    try {
      setStatus({ text: `Đang phân đoạn ${file.name}…`, tone: 'info' });
      await onUpload(file, orgLevel ? { classification: level } : undefined);
      setStatus({ text: `Đã thêm ${file.name}`, tone: 'ok' });
      setTimeout(() => setStatus(null), 3000);
    } catch (err: any) {
      setStatus({ text: `Lỗi: ${err.message}`, tone: 'error' });
      setTimeout(() => setStatus(null), 4000);
    }
  };
  const onDrag = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true);
    else if (e.type === 'dragleave' && !e.currentTarget.contains(e.relatedTarget as Node)) setDragActive(false);
  };
  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragActive(false);
    if (e.dataTransfer.files?.[0]) await processFile(e.dataTransfer.files[0]);
  };

  const docs = useMemo(() => documents.filter(doc =>
    (domain === 'all' || domainOf(doc) === domain || doc.domain_tags.some(t => t.toLowerCase().includes(domain))) &&
    doc.source_file.toLocaleLowerCase('vi').includes(searchTerm.trim().toLocaleLowerCase('vi'))
  ), [documents, domain, searchTerm]);

  return (
    <div className={`kb${dragActive ? ' is-drag' : ''}`} onDragEnter={onDrag} onDragOver={onDrag} onDragLeave={onDrag} onDrop={onDrop}>
      <input ref={fileInputRef} type="file" accept=".pdf,.md,.markdown,.sql,.txt" hidden onChange={async e => { if (e.target.files?.[0]) await processFile(e.target.files[0]); e.target.value = ''; }} />
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

      {orgLevel && <label className="og-upload-level"><span>Mức mật khi tải lên</span>
        <select value={level} onChange={e => setLevel(e.target.value as Classification)} aria-label="Mức mật khi tải lên">
          {levels.map(c => <option key={c} value={c}>{CLASS_LABEL[c]}: {CLASS_HINT[c]}</option>)}</select></label>}

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
          <div className="kb-empty-c">
            <span className="kb-empty-ico"><UploadCloud size={16} /></span>
            <span className="kb-empty-t"><b>Chưa có tài liệu</b>
              <span><button type="button" onClick={() => fileInputRef.current?.click()}>Tải lên</button> · <button type="button" onClick={() => void onSeedDocs()}>Dùng bộ mẫu</button></span></span>
          </div>
        ) : docs.length === 0 ? <p className="kb-none">Không có tài liệu khớp.</p> : docs.map((doc, idx) => {
          const d = domainOf(doc);
          return (
            <div key={doc.id || idx} className="kb-row" title={doc.owner ? `${doc.source_file}\nTải lên bởi: ${doc.mine ? 'bạn' : doc.owner}` : doc.source_file}>
              <span className={`kb-ic is-${d ?? 'none'}`}><FileIcon doc={doc} /></span>
              <span className="kb-name">{doc.source_file}</span>
              {doc.classification && <ClassBadge value={doc.classification} />}
              <span className="kb-meta">{doc.status === 'processing' ? <i className="dot is-warn" title="Đang xử lý" /> : doc.status === 'failed' ? <i className="dot is-bad" title="Lỗi xử lý" /> : doc.chunks_count}</span>
              <span className="kb-acts">
                {onInspectDocument && <button onClick={() => onInspectDocument(doc)} aria-label={`Xem phân đoạn của ${doc.source_file}`} title="Xem phân đoạn"><Eye size={14} /></button>}
                {onDeleteDocument && doc.id && canDelete && doc.can_delete !== false && (
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
