// Việc cần làm (đợt 6, mục 2b): chỉ hiện khi đang mở một tổ chức. Việc qua tay nhiều người: thông báo, lời mời,
// yêu cầu tham gia chờ duyệt. Đơn từ và duyệt theo cấp thuộc đợt 10, chưa có; trang nói rõ, không giả lập.
import React, { useEffect, useState } from 'react';
import { BellRing, CheckCheck, ClipboardList, FileClock, RefreshCw } from 'lucide-react';
import { getNotifications, markNotificationsRead, OrgNotification } from '../services/api';
import { ToolHeader } from './analysis/shared';
import '../styles/pages-2b.css';


export const TasksView: React.FC<{ spaceId: string; spaceName?: string; onOpenOrg: () => void; noteText: (n: OrgNotification) => string }> = ({ spaceId, spaceName, onOpenOrg, noteText }) => {
  const [items, setItems] = useState<OrgNotification[] | null>(null);
  const [error, setError] = useState('');
  const load = () => { setError(''); getNotifications().then(r => setItems(r.items.filter(n => !n.space_id || n.space_id === spaceId))).catch(e => setError(e.message)); };
  useEffect(load, [spaceId]);
  const unread = (items ?? []).filter(n => !n.read);
  const readAll = async () => { await markNotificationsRead(unread.map(n => n.notification_id)); load(); };

  return (
    <main className="pg tl tone-overview tsk">
      <div className="pg-col">
        <ToolHeader Icon={ClipboardList} title="Việc cần làm" desc={`Việc qua tay nhiều người trong ${spaceName ?? 'tổ chức'}: thông báo, lời mời, yêu cầu chờ duyệt.`}
          right={<button className="btn btn-ghost" onClick={load}><RefreshCw size={15} />Tải lại</button>} />
        <div className="tsk-cols">
          <section className="dz-card tsk-card">
            <header><h3><BellRing size={16} />Thông báo {unread.length > 0 && <span className="og-count is-alert">{unread.length}</span>}</h3>
              {unread.length > 0 && <button className="btn btn-ghost is-sm" onClick={readAll}><CheckCheck size={14} />Đánh dấu đã đọc</button>}</header>
            {error && <p className="note is-error" role="alert">{error}</p>}
            {items && items.length === 0 && <p className="lib-empty">Không có việc nào đang chờ.</p>}
            {items && items.length > 0 && <ul className="tsk-list">{items.map(n => <li key={n.notification_id} className={n.read ? '' : 'is-new'}>
              <b>{noteText(n)}</b><time>{new Date(n.created_at).toLocaleString('vi-VN')}</time>
            </li>)}</ul>}
            <button className="btn btn-ghost is-sm tsk-org" onClick={onOpenOrg}>Duyệt thành viên ở trang Tổ chức</button>
          </section>
          <section className="dz-card tsk-card tsk-soon">
            <header><h3><FileClock size={16} />Đơn từ và duyệt theo cấp</h3></header>
            <p>Tạo đơn, kiểm điều kiện theo quy định, chuyển đúng cấp duyệt và lưu lịch sử duyệt. Chức năng này thuộc đợt 10 của lộ trình, <b>chưa có</b>.</p>
            <p>Hiện có thể kiểm điều kiện và tìm cấp duyệt ngay trong ô chat: gõ “/” rồi chọn “Kiểm tra điều kiện” hoặc “Ai duyệt”.</p>
          </section>
        </div>
      </div>
    </main>
  );
};
