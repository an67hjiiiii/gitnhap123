import { useEffect, useRef, useState } from 'react';
import { AGENT_PROFILES } from './agents';
import {
  Office3DEngine,
  type ProjectedAgentAnchor,
} from './scene/Office3DEngine';
import type {
  AgentId,
  Studio3DController,
  StudioTelemetrySnapshot,
} from './types';

interface AgentOrchestratorCanvasProps {
  showLabels: boolean;
  selectedAgentId: AgentId | null;
  onEngineReady: (controller: Studio3DController) => void;
  onTelemetry: (snapshot: StudioTelemetrySnapshot) => void;
  onSelectAgent: (id: AgentId | null) => void;
}

const place = (a: ProjectedAgentAnchor) => `translate3d(${Math.round(a.x)}px, ${Math.round(a.y)}px, 0) translate(-50%, -125%)`;

export function AgentOrchestratorCanvas({
  showLabels,
  selectedAgentId,
  onEngineReady,
  onTelemetry,
  onSelectAgent,
}: AgentOrchestratorCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<Office3DEngine | null>(null);
  const labelRefs = useRef(new Map<AgentId, HTMLButtonElement>());
  const [anchors, setAnchors] = useState<ProjectedAgentAnchor[]>([]);
  const latestPos = useRef<ProjectedAgentAnchor[]>([]);  // vị trí mới nhất (máy dựng cảnh cập nhật mỗi khung)
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const engine = new Office3DEngine(el, {
      onTelemetry,
      onSelectAgent,
      onAnchorsUpdated: (next) => { latestPos.current = next; setAnchors(next); },
      // robot đi hay camera xoay: chỉ dời nhãn đang hiện, không vẽ lại React mỗi khung
      onAnchorsMoved: (moved) => {
        latestPos.current = moved;
        for (const a of moved) {
          const node = labelRefs.current.get(a.id);
          if (node) node.style.transform = place(a);
        }
      },
      onFirstFrame: () => setReady(true),
    });
    engineRef.current = engine;
    onEngineReady(engine);

    return () => {
      engine.dispose();
      engineRef.current = null;
    };
    // Mount 3D WebGL context once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLabelClick = (id: AgentId) => {
    onSelectAgent(id);
    engineRef.current?.setCameraPreset(id);
  };

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#f3efe9]">
      <div ref={containerRef} className="h-full w-full" />

      {!ready && (
        <div className="o3d-loading" role="status">
          <span className="o3d-loading-dot" aria-hidden />
          Đang dựng văn phòng…
        </div>
      )}

      {/* Nhãn gọn: chỉ Agent đang làm và Agent đang chọn; Agent ngủ đã có chữ zzz trong cảnh nên không gắn nhãn che cảnh */}
      {showLabels && ready && (
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          {anchors.map((a) => {
            const isSelected = selectedAgentId === a.id;
            if (!a.visible || (!a.isAwake && !isSelected)) return null;
            const profile = AGENT_PROFILES[a.id];
            return (
              <button
                key={a.id}
                ref={(node) => { if (node) labelRefs.current.set(a.id, node); else labelRefs.current.delete(a.id); }}
                type="button"
                onClick={() => handleLabelClick(a.id)}
                style={{ transform: place(latestPos.current.find((p) => p.id === a.id) ?? a), ['--o3d-accent' as string]: profile.accentHex }}
                className={`o3d-tag pointer-events-auto${a.isLead ? ' is-lead' : ''}${isSelected ? ' is-selected' : ''}${a.isAwake ? '' : ' is-asleep'}`}
                title={a.isAwake ? `${profile.name}: ${a.actionText}` : `${profile.name} đang ngủ`}
              >
                <span className="o3d-tag-dot" aria-hidden />
                <span className="o3d-tag-name">{profile.shortName}</span>
                {a.isLead && <span className="o3d-tag-action">{a.actionText}</span>}
                {!a.isAwake && <span className="o3d-tag-zzz">zzz</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
