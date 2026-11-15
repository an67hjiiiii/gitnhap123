import React, { useState, useEffect } from 'react';
import { RefreshCw, Search, ShieldCheck, Stethoscope, Database, CheckCircle2, AlertTriangle, AlertCircle, ThumbsUp } from 'lucide-react';
import { DatabaseOverviewResponse, TableDataResponse, SecurityAuditResponse, DbDiagnosticResponse } from '../types';
import { getDatabaseOverview, getTableData, getSecurityAudit, getDbDiagnostic } from '../services/api';
import { StudioModal } from './StudioModal';
import { AdminFeedbackModal } from './AdminFeedbackModal';
import { ToolHeader } from './analysis/shared';
import './profile/tools.css';

const TABLE_LABEL: Record<string, string> = {
  users: 'Người dùng', sessions: 'Phiên đăng nhập', knowledge_sources: 'Tài liệu', knowledge_chunks: 'Phân đoạn',
  conversations: 'Cuộc trò chuyện', conversation_messages: 'Tin nhắn', runs: 'Lượt chạy',
};
const errText = (err: any, fallback: string) => err?.message || fallback;

export const DatabaseExplorer: React.FC = () => {
  const [overview, setOverview] = useState<DatabaseOverviewResponse | null>(null);
  const [selectedTable, setSelectedTable] = useState('runs');
  const [tableData, setTableData] = useState<TableDataResponse | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoadingTable, setIsLoadingTable] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // NFR01: bộ tham số tái lập

  const [securityOpen, setSecurityOpen] = useState(false);
  const [securityAudit, setSecurityAudit] = useState<SecurityAuditResponse | null>(null);
  const [isLoadingSecurity, setIsLoadingSecurity] = useState(false);
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);
  const [dbDiagnostic, setDbDiagnostic] = useState<DbDiagnosticResponse | null>(null);
  const [isLoadingDiagnostic, setIsLoadingDiagnostic] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);

  const openSecurity = async () => {
    setSecurityOpen(true); setIsLoadingSecurity(true); setModalError(null);
    try { setSecurityAudit(await getSecurityAudit()); } catch (err) { setModalError(errText(err, 'Không tải được kết quả kiểm tra bảo mật.')); } finally { setIsLoadingSecurity(false); }
  };
  const openDiagnostic = async () => {
    setDiagnosticOpen(true); setIsLoadingDiagnostic(true); setModalError(null);
    try { setDbDiagnostic(await getDbDiagnostic()); } catch (err) { setModalError(errText(err, 'Không tải được kết quả chẩn đoán.')); } finally { setIsLoadingDiagnostic(false); }
  };

  const fetchOverview = async () => {
    setIsRefreshing(true); setLoadError(null);
    try {
      setOverview(await getDatabaseOverview());
    } catch (err) { setLoadError(errText(err, 'Không tải được tổng quan CSDL.')); } finally { setIsRefreshing(false); }
  };
  const fetchTable = async (name: string, query = '') => {
    setIsLoadingTable(true);
    try { setTableData(await getTableData(name, 50, 0, query)); } catch (err) { setTableData(null); setLoadError(errText(err, `Không tải được bảng ${name}.`)); } finally { setIsLoadingTable(false); }
  };

  useEffect(() => { fetchOverview(); }, []);
  useEffect(() => { if (selectedTable) fetchTable(selectedTable, searchQuery); }, [selectedTable]);

  const cell = (col: string, val: any) => {
    const s = typeof val === 'object' && val !== null ? JSON.stringify(val) : String(val ?? '');
    if (col === 'id') return <b>#{s}</b>;
    if (val == null || s === '') return <span className="is-muted">trống</span>;
    if (col.includes('role') || col.includes('status')) return <span className="cell-pill">{s}</span>;
    return s.length > 60 ? `${s.slice(0, 60)}…` : s;
  };
  const closeModal = (set: (v: boolean) => void) => () => { set(false); setModalError(null); };

  return (
    <div className="pg tl tone-overview db-page">
      <div className="pg-col tv-col">
        <ToolHeader Icon={Database} title="Cơ sở dữ liệu"
          desc={`${overview ? `${overview.tables.length} bảng PostgreSQL. ` : ''}Xem dữ liệu từng bảng (không hiện mật khẩu, token), phản hồi người dùng, kiểm tra cấu hình bảo mật và chẩn đoán cấu trúc CSDL.`}
          right={<button className="btn btn-ghost" onClick={() => { fetchOverview(); fetchTable(selectedTable, searchQuery); }} disabled={isRefreshing}><RefreshCw size={15} className={isRefreshing ? 'is-spinning' : ''} />Làm mới</button>} />

        {loadError && <div className="note is-error"><AlertCircle size={16} /><span>{loadError}</span></div>}

        <div className="db-tools">
          <button onClick={() => setFeedbackOpen(true)}><ThumbsUp size={18} /><b>Phản hồi người dùng</b><span>Câu trả lời được chấm 👍/👎 và góp ý</span></button>
          <button onClick={openSecurity}><ShieldCheck size={18} /><b>Kiểm tra bảo mật</b><span>Rà soát cấu hình chạy cục bộ (NFR06)</span></button>
          <button onClick={openDiagnostic}><Stethoscope size={18} /><b>Chẩn đoán CSDL</b><span>Khóa ngoại và cấu trúc bảng</span></button>
        </div>

        <section className="db-sec">
          <h2>Bảng dữ liệu</h2>
          <div className="db-tables" role="tablist" aria-label="Chọn bảng">
            {overview ? overview.tables.map(t => (
              <button key={t.table_name} role="tab" aria-selected={selectedTable === t.table_name} className={selectedTable === t.table_name ? 'is-on' : ''} onClick={() => setSelectedTable(t.table_name)} title={t.description || t.display_name}>
                <span>{TABLE_LABEL[t.table_name] || t.display_name.split('(')[0]}</span><b>{t.row_count.toLocaleString('vi-VN')}</b><code>{t.table_name}</code>
              </button>
            )) : <p className="muted-line"><span className="spin is-dark" />Đang tải danh sách bảng…</p>}
          </div>
        </section>

        <section className="db-sec">
          <div className="row-head">
            <h2>{TABLE_LABEL[selectedTable] || selectedTable} <small>{tableData ? `${tableData.total_count.toLocaleString('vi-VN')} bản ghi` : ''}</small></h2>
            <form onSubmit={e => { e.preventDefault(); fetchTable(selectedTable, searchQuery); }} className="db-search">
              <label className="search"><Search size={14} /><span className="sr">Tìm trong bảng</span><input type="search" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder={`Tìm trong ${selectedTable}`} /></label>
              <button type="submit" className="btn btn-ghost">Lọc</button>
            </form>
          </div>
          {isLoadingTable ? <p className="muted-line is-center"><span className="spin is-dark" />Đang tải dữ liệu…</p>
            : !tableData || tableData.rows.length === 0 ? <div className="empty">Không có bản ghi nào trong bảng <code>{selectedTable}</code>.</div>
            : <div className="tbl is-data"><table>
              <thead><tr>{tableData.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{tableData.rows.map((row, i) => <tr key={i}>{tableData.columns.map(c => {
                const v = row[c]; return <td key={c} title={typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '')}>{cell(c, v)}</td>;
              })}</tr>)}</tbody>
            </table></div>}
          {tableData && tableData.total_count > tableData.rows.length && <p className="footnote">Đang hiện {tableData.rows.length} bản ghi đầu tiên.</p>}
        </section>

      </div>

      {feedbackOpen && <AdminFeedbackModal onClose={() => setFeedbackOpen(false)} />}
      {securityOpen && <StudioModal labelId="sec-title" size="md" icon={<ShieldCheck size={18} />} title="Kiểm tra bảo mật cục bộ" subtitle={securityAudit ? `Kết quả: ${securityAudit.audit_score}` : 'Rà soát cấu hình chạy cục bộ (NFR06)'} onClose={closeModal(setSecurityOpen)}
        footer={<><span className="mo-note">{securityAudit ? `Thời điểm kiểm tra: ${securityAudit.audit_timestamp}` : ''}</span><button className="btn btn-dark" onClick={closeModal(setSecurityOpen)}>Đóng</button></>}>
        {isLoadingSecurity ? <p className="muted-line is-center"><span className="spin is-dark" />Đang rà soát…</p>
          : modalError ? <div className="note is-error"><AlertCircle size={16} /><span>{modalError}</span></div>
          : securityAudit ? <>
            <dl className="pg-stats">
              <div><dt>Kết nối ra ngoài</dt><dd>{securityAudit.network_egress_status}</dd></div>
              <div><dt>Mô hình ngôn ngữ</dt><dd title={securityAudit.llm_endpoint}>{securityAudit.llm_endpoint.replace(/^https?:\/\//, '')}</dd></div>
              <div><dt>Kho vector</dt><dd>{securityAudit.vector_db_mode}</dd></div>
              <div><dt>Vai trò RBAC</dt><dd>{securityAudit.rbac_active_roles.length}</dd></div>
            </dl>
            <ul className="audit">{securityAudit.checkpoints.map(cp => (
              <li key={cp.code} className={cp.compliant ? 'is-ok' : 'is-warn'}>
                {cp.compliant ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                <div><b>{cp.code} · {cp.name}</b><p>{cp.details}</p></div><span className="cell-pill">{cp.status}</span>
              </li>
            ))}</ul>
            <p className="footnote">Tự kiểm tra, không phải chứng nhận bảo mật.</p>
          </> : <div className="empty">Không có dữ liệu kiểm tra.</div>}
      </StudioModal>}

      {diagnosticOpen && <StudioModal labelId="diag-title" size="md" icon={<Database size={18} />} title="Chẩn đoán CSDL" subtitle="Ràng buộc khóa ngoại và cấu trúc bảng" onClose={closeModal(setDiagnosticOpen)}
        footer={<><span className="mo-note" /><button className="btn btn-dark" onClick={closeModal(setDiagnosticOpen)}>Đóng</button></>}>
        {isLoadingDiagnostic ? <p className="muted-line is-center"><span className="spin is-dark" />Đang kiểm tra các bảng…</p>
          : modalError ? <div className="note is-error"><AlertCircle size={16} /><span>{modalError}</span></div>
          : dbDiagnostic ? <>
            <dl className="pg-stats is-3">
              <div><dt>Cơ sở dữ liệu</dt><dd>{dbDiagnostic.active_engine} ({dbDiagnostic.dialect})</dd></div>
              <div><dt>Khóa ngoại</dt><dd>{dbDiagnostic.foreign_keys_enabled ? 'Đang bật' : 'Chưa bật'}</dd></div>
              <div><dt>Số bảng</dt><dd>{dbDiagnostic.tables_count}</dd></div>
            </dl>
            <div className="tbl"><table>
              <thead><tr><th>Bảng</th><th className="is-right">Bản ghi</th><th>Khóa ngoại</th><th>Cấu trúc</th></tr></thead>
              <tbody>{dbDiagnostic.tables.map(t => <tr key={t.table_name}>
                <td><b>{TABLE_LABEL[t.table_name] || t.table_name}</b><small>{t.table_name}</small></td>
                <td className="is-right">{t.record_count}</td>
                <td className={t.foreign_keys_intact ? 'is-ok' : 'is-bad'}>{t.foreign_keys_intact ? 'Toàn vẹn' : 'Có lỗi'}</td>
                <td className={t.schema_valid ? 'is-ok' : 'is-bad'}>{t.schema_valid ? 'Hợp lệ' : 'Sai lệch'}</td>
              </tr>)}</tbody>
            </table></div>
          </> : null}
      </StudioModal>}

    </div>
  );
};
