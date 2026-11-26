// Đội Agent & Quy trình C1SE.27:
// - Bảng chọn Đội Agent: Tab 1 Đội ngũ (11), Tab 2 Quy trình & Kiến trúc 11 Agent thật.
// - Thẻ riêng của từng Agent: xem vai trò, khi nào được gọi, luồng nhận/giao và ví dụ.
import { useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, Check, ChevronLeft, ChevronRight, Layers, Lightbulb, TriangleAlert, Users, X } from 'lucide-react';
import { AGENT_PROFILES, CORE_AGENT_IDS, SPECIALIST_AGENT_IDS } from './agents';
import { AGENT_GUIDE, STATUS_LABEL } from './agentGuide';
import { AgentRobotAvatar } from './AgentRobotAvatar';
import type { AgentId, AgentRuntimeState } from './types';

const ORDER: AgentId[] = [...CORE_AGENT_IDS, ...SPECIALIST_AGENT_IDS];

const C1SE27_STAGES = [
  { num: '01', name: 'Phân rã có hỗ trợ truy xuất', en: 'Retrieval-Guided Decomposition', desc: 'Orchestrator truy xuất sơ bộ kho tri thức trước khi tách câu hỏi phức tạp thành các đầu việc nguyên tử, tránh bịa nhánh ngoài tài liệu.' },
  { num: '02', name: 'Chuẩn hóa & Khử trùng lặp', en: 'Normalization & Deduplication', desc: 'Loại bỏ các đầu việc trùng nghĩa và giữ đúng thứ tự phụ thuộc để không gọi thừa tác tử và tiết kiệm token.' },
  { num: '03', name: 'Định tuyến 11 Agent theo ngữ nghĩa', en: 'Task-Specific Agent Assignment', desc: 'Tự động chọn tối đa 3 chuyên gia phù hợp trong đội 11 Agent dựa trên độ tương đồng ngữ nghĩa + từ khóa; các Agent khác ngủ yên tiết kiệm tài nguyên.' },
  { num: '04', name: 'Phân bổ ngữ cảnh, Kiểm định & Tổng hợp', en: 'Overlap-Aware Context Allocation', desc: 'RAG Specialist cấp ngân sách ngữ cảnh riêng cho từng đầu việc; Reviewer đối chiếu bằng chứng rồi Integrator tổng hợp câu trả lời có trích dẫn.' },
];

const ARCHITECTURE_LAYERS = [
  {
    id: 'core',
    label: 'Tầng 1 · 5 Agent lõi điều phối',
    agents: [
      'Orchestrator (Điều phối & phân rã)',
      'RAG Specialist (Truy xuất & ngân sách ngữ cảnh)',
      'Data Analyst (Tính toán & đối chiếu số liệu)',
      'Reviewer (Kiểm định kế hoạch & bằng chứng)',
      'Integrator (Tổng hợp bàn giao & đa chủ đề)',
    ],
  },
  {
    id: 'specialists',
    label: 'Tầng 2 · 6 Chuyên gia ngành (chỉ thức khi cần)',
    agents: [
      'Software & IT (Phần mềm, API, CSDL, Bảo mật)',
      'Business & Strategy (Kinh doanh, Quy trình, Hợp đồng)',
      'Marketing & Growth (Thị trường, Chiến dịch, Thương hiệu)',
      'HR & People (Nhân sự, Nội quy, Phép năm, Lương thưởng)',
      'Finance & Accounting (Tài chính, Ngân sách, Hóa đơn, Thuế)',
      'Education & Research (Học vụ, Tín chỉ, Học bổng, Nghiên cứu)',
    ],
  },
];

interface Props {
  rosterOpen: boolean;
  selectedAgentId: AgentId | null;
  agents: Partial<Record<AgentId, AgentRuntimeState>> | null;
  onSelect: (id: AgentId) => void;
  onCloseCard: () => void;
  onCloseRoster: () => void;
}

export function AgentGuidePanel({ rosterOpen, selectedAgentId, agents, onSelect, onCloseCard, onCloseRoster }: Props) {
  const [panelTab, setPanelTab] = useState<'roster' | 'process'>('roster');
  if (selectedAgentId) return <AgentCard id={selectedAgentId} live={agents?.[selectedAgentId] ?? null} onSelect={onSelect} onClose={onCloseCard} />;
  if (!rosterOpen) return null;

  const chip = (id: AgentId) => {
    const p = AGENT_PROFILES[id];
    const awake = agents?.[id]?.isAwake;
    return (
      <li key={id}>
        <button type="button" className="o3d-roster-item" style={{ ['--o3d-accent' as string]: p.accentHex }} onClick={() => onSelect(id)}>
          <AgentRobotAvatar agentId={id} size={34} mood="focus" online={Boolean(awake)} />
          <span className="o3d-roster-text">
            <b>{p.shortName}</b>
            <small>{p.titleVi}</small>
          </span>
          <span className={`o3d-presence${awake ? ' is-awake' : ''}`} title={awake ? 'Đang làm việc' : 'Đang ngủ chờ việc'} />
        </button>
      </li>
    );
  };

  return (
    <aside className="o3d-panel o3d-roster" aria-label="Đội Agent và Quy trình C1SE.27">
      <header className="o3d-roster-head">
        <div>
          <h2>{panelTab === 'roster' ? 'Đội Agent' : 'Quy trình C1SE.27'}</h2>
          <p>{panelTab === 'roster' ? '11 Agent. Chọn một Agent để xem vai trò và việc cụ thể.' : '4 giai đoạn điều phối thích ứng trên đội ngũ 11 Agent.'}</p>
        </div>
        <button type="button" className="o3d-icon-btn" onClick={onCloseRoster} aria-label="Đóng bảng Đội Agent"><X size={16} /></button>
      </header>
      <div className="o3d-roster-tabs" role="tablist" aria-label="Chế độ xem đội Agent">
        <button type="button" role="tab" aria-selected={panelTab === 'roster'} className={panelTab === 'roster' ? 'is-on' : ''} onClick={() => setPanelTab('roster')}>
          <Users size={13} />Đội ngũ (11)
        </button>
        <button type="button" role="tab" aria-selected={panelTab === 'process'} className={panelTab === 'process' ? 'is-on' : ''} onClick={() => setPanelTab('process')}>
          <Layers size={13} />Quy trình & 11 Agent
        </button>
      </div>
      {panelTab === 'roster' ? (
        <div className="o3d-roster-body">
          <h3>Lõi điều phối · làm ở mọi câu hỏi</h3>
          <ul>{CORE_AGENT_IDS.map(chip)}</ul>
          <h3>Chuyên gia ngành · chỉ thức khi cần</h3>
          <ul>{SPECIALIST_AGENT_IDS.map(chip)}</ul>
        </div>
      ) : (
        <div className="o3d-roster-body o3d-process-body">
          <h3>4 giai đoạn điều phối thích ứng</h3>
          <ol className="o3d-stage-list">
            {C1SE27_STAGES.map(st => (
              <li key={st.num}>
                <span className="o3d-stage-num">{st.num}</span>
                <div>
                  <b>{st.name}</b>
                  <em>{st.en}</em>
                  <p>{st.desc}</p>
                </div>
              </li>
            ))}
          </ol>
          <h3>Kiến trúc 2 tầng · 11 Agent thật</h3>
          <ul className="o3d-pack-list">
            {ARCHITECTURE_LAYERS.map(layer => (
              <li key={layer.id}>
                <b>{layer.label}</b>
                <small>{layer.agents.join(' · ')}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}

function AgentCard({ id, live, onSelect, onClose }: { id: AgentId; live: AgentRuntimeState | null; onSelect: (id: AgentId) => void; onClose: () => void }) {
  const p = AGENT_PROFILES[id];
  const g = AGENT_GUIDE[id];
  const i = ORDER.indexOf(id);
  const prev = ORDER[(i - 1 + ORDER.length) % ORDER.length];
  const next = ORDER[(i + 1) % ORDER.length];

  return (
    <aside className="o3d-panel o3d-card" style={{ ['--o3d-accent' as string]: p.accentHex }} aria-label={`Thông tin ${p.name}`}>
      <header className="o3d-card-head">
        <AgentRobotAvatar agentId={id} size={42} mood="focus" online={Boolean(live?.isAwake)} />
        <div className="o3d-card-title">
          <h2>{p.name}</h2>
          <p>{p.titleVi}</p>
        </div>
        <button type="button" className="o3d-icon-btn" onClick={onClose} aria-label="Đóng thẻ Agent"><X size={16} /></button>
      </header>

      <div className="o3d-card-meta">
        <span className={`o3d-status is-${g.status}`}>{STATUS_LABEL[g.status]}</span>
        <span className={`o3d-now${live?.isAwake ? ' is-awake' : ''}`}>
          <span className="o3d-presence" aria-hidden />
          {live?.isAwake ? live.actionText : 'Đang ngủ chờ việc'}
        </span>
      </div>

      <div className="o3d-card-body">
        <p className="o3d-lead">{g.role}</p>

        <section>
          <h3>Khi nào được gọi</h3>
          <p>{g.when}</p>
        </section>

        <section>
          <h3>Làm gì trong hệ thống</h3>
          <ul className="o3d-checks">
            {g.does.map((d) => <li key={d}><Check size={14} aria-hidden />{d}</li>)}
          </ul>
        </section>

        <section className="o3d-flow" aria-label="Luồng công việc">
          <div><ArrowDownLeft size={14} aria-hidden /><span><b>Nhận</b>{g.from}</span></div>
          <div><ArrowUpRight size={14} aria-hidden /><span><b>Giao</b>{g.to}</span></div>
        </section>

        <section>
          <h3>Ví dụ</h3>
          <ul className="o3d-examples">
            {g.examples.map((e) => <li key={e}><Lightbulb size={14} aria-hidden />{e}</li>)}
          </ul>
        </section>

        {g.limit && <p className="o3d-limit"><TriangleAlert size={14} aria-hidden />{g.limit}</p>}
      </div>

      <footer className="o3d-card-foot">
        <button type="button" onClick={() => onSelect(prev)}><ChevronLeft size={14} aria-hidden />{AGENT_PROFILES[prev].shortName}</button>
        <span>{i + 1} / {ORDER.length}</span>
        <button type="button" onClick={() => onSelect(next)}>{AGENT_PROFILES[next].shortName}<ChevronRight size={14} aria-hidden /></button>
      </footer>
    </aside>
  );
}
