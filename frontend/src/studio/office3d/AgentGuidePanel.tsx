// Đội Agent (23/11, làm lại theo góp ý): bấm một Agent chỉ hiện thẻ của riêng Agent đó; nút "Đội Agent" mở bảng chọn gọn.
// Bấm thẻ trong bảng chọn hoặc robot/nhãn trong cảnh: camera bay tới bàn Agent và thẻ của Agent đó mở ra.
import { ArrowDownLeft, ArrowUpRight, Check, ChevronLeft, ChevronRight, Lightbulb, TriangleAlert, X } from 'lucide-react';
import { AGENT_PROFILES, CORE_AGENT_IDS, SPECIALIST_AGENT_IDS } from './agents';
import { AGENT_GUIDE, STATUS_LABEL } from './agentGuide';
import type { AgentId, AgentRuntimeState } from './types';

const ORDER: AgentId[] = [...CORE_AGENT_IDS, ...SPECIALIST_AGENT_IDS];

interface Props {
  rosterOpen: boolean;
  selectedAgentId: AgentId | null;
  agents: Partial<Record<AgentId, AgentRuntimeState>> | null;
  onSelect: (id: AgentId) => void;
  onCloseCard: () => void;
  onCloseRoster: () => void;
}

export function AgentGuidePanel({ rosterOpen, selectedAgentId, agents, onSelect, onCloseCard, onCloseRoster }: Props) {
  if (selectedAgentId) return <AgentCard id={selectedAgentId} live={agents?.[selectedAgentId] ?? null} onSelect={onSelect} onClose={onCloseCard} />;
  if (!rosterOpen) return null;

  const chip = (id: AgentId) => {
    const p = AGENT_PROFILES[id];
    const awake = agents?.[id]?.isAwake;
    return (
      <li key={id}>
        <button type="button" className="o3d-roster-item" style={{ ['--o3d-accent' as string]: p.accentHex }} onClick={() => onSelect(id)}>
          <span className="o3d-avatar is-sm" aria-hidden>{p.code}</span>
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
    <aside className="o3d-panel o3d-roster" aria-label="Chọn Agent">
      <header className="o3d-roster-head">
        <div>
          <h2>Đội Agent</h2>
          <p>11 Agent. Chọn một Agent để xem vai trò và việc cụ thể.</p>
        </div>
        <button type="button" className="o3d-icon-btn" onClick={onCloseRoster} aria-label="Đóng bảng chọn Agent"><X size={16} /></button>
      </header>
      <div className="o3d-roster-body">
        <h3>Lõi điều phối · làm ở mọi câu hỏi</h3>
        <ul>{CORE_AGENT_IDS.map(chip)}</ul>
        <h3>Chuyên gia ngành · chỉ thức khi cần</h3>
        <ul>{SPECIALIST_AGENT_IDS.map(chip)}</ul>
      </div>
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
        <span className="o3d-avatar" aria-hidden>{p.code}</span>
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
