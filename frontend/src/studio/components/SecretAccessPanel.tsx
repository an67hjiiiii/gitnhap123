// Nhật ký truy cập tài liệu mức Mật (đợt 9): ai mở tài liệu hoặc hỏi AI dùng tới nó, lúc nào. Không có nội dung câu hỏi.
import React, { useEffect, useState } from 'react';
import { Eye, MessageSquareText, RefreshCw, ShieldAlert } from 'lucide-react';
import { getSecretAccess, SecretAccess } from '../services/api';

export const SecretAccessPanel: React.FC<{ spaceId: string; secretLabel: string }> = ({ spaceId, secretLabel }) => {
  const [rows, setRows] = useState<SecretAccess[] | null>(null);
  const [error, setError] = useState('');
  const load = () => { setError(''); getSecretAccess(spaceId).then(setRows).catch(e => setError(e.message)); };
  useEffect(load, [spaceId]);
  return (
    <section className="dz-card og-secret">
      <header>
        <h3><ShieldAlert size={16} />Nhật ký truy cập tài liệu {secretLabel}</h3>
        <button type="button" className="btn btn-ghost is-sm" onClick={load} aria-label="Tải lại nhật ký"><RefreshCw size={14} /></button>
      </header>
      <p className="og-hint">Ghi lại ai mở tài liệu hoặc hỏi AI có dùng tới tài liệu mức {secretLabel}, không ghi nội dung câu hỏi. Chỉ cấp cao nhất và chủ tổ chức xem được.</p>
      {error && <p className="note is-error" role="alert">{error}</p>}
      {rows && rows.length === 0 && <p className="og-hint">Chưa có lượt truy cập nào.</p>}
      {rows && rows.length > 0 && <ul className="og-secret-list">{rows.map((r, i) => (
        <li key={i}>
          <span className={`og-secret-act is-${r.action.toLowerCase()}`}>{r.action === 'VIEW' ? <><Eye size={13} />Mở xem</> : <><MessageSquareText size={13} />AI đọc khi trả lời</>}</span>
          <b>{r.user || 'Không rõ'}</b><span className="og-secret-doc">{r.source_name}</span>
          <time>{r.at ? new Date(r.at).toLocaleString('vi-VN') : ''}</time>
        </li>))}</ul>}
    </section>
  );
};
