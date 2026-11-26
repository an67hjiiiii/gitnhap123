import { useEffect, useRef, useState } from 'react';
import { AGENT_PROFILES } from './agents';
import {
  Office3DEngine,
  type ProjectedAgentAnchor,
} from './scene/Office3DEngine';
import type { FlowLogItem, ProjectedFlowBadge } from './scene/flowGraph';
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
  onFlowLogsUpdated?: (logs: FlowLogItem[]) => void;
}

const place = (a: ProjectedAgentAnchor) => `translate3d(${Math.round(a.x)}px, ${Math.round(a.y)}px, 0) translate(-50%, -125%)`;

export function AgentOrchestratorCanvas({
  showLabels,
  selectedAgentId,
  onEngineReady,
  onTelemetry,
  onSelectAgent,
  onFlowLogsUpdated,
}: AgentOrchestratorCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<Office3DEngine | null>(null);
  const labelRefs = useRef(new Map<AgentId, HTMLButtonElement>());
  const flowBadgeRefs = useRef(new Map<string, HTMLDivElement>());
  const [anchors, setAnchors] = useState<ProjectedAgentAnchor[]>([]);
  const [flowBadges, setFlowBadges] = useState<ProjectedFlowBadge[]>([]);
  const latestPos = useRef<ProjectedAgentAnchor[]>([]);  // vị trí mới nhất (máy dựng cảnh cập nhật mỗi khung)
  const latestBadgePos = useRef<ProjectedFlowBadge[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Nhường 1 nhịp paint trình duyệt trước khi khởi tạo WebGL để thao tác bấm chuyển tab phản hồi 0ms, không bị đơ nhịp!
    let cancelled = false;
    let rafId = 0;
    let timerId = 0;
    rafId = requestAnimationFrame(() => {
      timerId = window.setTimeout(() => {
        if (cancelled) return;
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
          onFlowBadgesUpdated: (badges) => { latestBadgePos.current = badges; setFlowBadges(badges); },
          // lăn chuột / xoay camera: dời nhãn đường nối trực tiếp qua DOM transform, 0 React re-render!
          onFlowBadgesMoved: (moved) => {
            latestBadgePos.current = moved;
            for (const b of moved) {
              const node = flowBadgeRefs.current.get(b.key);
              if (node) node.style.transform = `translate3d(${Math.round(b.x)}px, ${Math.round(b.y)}px, 0) translate(-50%, -50%)`;
            }
          },
          onFlowLogsUpdated,
        });
        engineRef.current = engine;
        onEngineReady(engine);
      }, 0);
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafId);
      window.clearTimeout(timerId);
      engineRef.current?.dispose();
      engineRef.current = null;
    };
    // Mount 3D WebGL context once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLabelClick = (id: AgentId) => {
    onSelectAgent(id);
    engineRef.current?.setCameraPreset(id);
  };

  // Khi con trỏ chuột vô tình chạm vào nút nhãn Agent nổi lúc đang lăn chuột zoom, chuyển tiếp sự kiện wheel xuống canvas
  // để OrbitControls nhận đầy đủ — không bao giờ bị đứng lăn chuột giữa chừng!
  const forwardWheelToCanvas = (e: React.WheelEvent) => {
    const canvas = containerRef.current?.querySelector('canvas');
    if (!canvas) return;
    canvas.dispatchEvent(new WheelEvent('wheel', {
      deltaX: e.deltaX,
      deltaY: e.deltaY,
      deltaZ: e.deltaZ,
      deltaMode: e.deltaMode,
      clientX: e.clientX,
      clientY: e.clientY,
      ctrlKey: e.ctrlKey,
      shiftKey: e.shiftKey,
      altKey: e.altKey,
      metaKey: e.metaKey,
      bubbles: false,
      cancelable: true,
    }));
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
                onWheel={forwardWheelToCanvas}
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
          {flowBadges.map((b) => {
            const cur = latestBadgePos.current.find((p) => p.key === b.key) ?? b;
            return (
              <div
                key={b.key}
                ref={(node) => { if (node) flowBadgeRefs.current.set(b.key, node); else flowBadgeRefs.current.delete(b.key); }}
                className={`o3d-flow-badge${b.active ? ' is-active' : ''}`}
                style={{
                  transform: `translate3d(${Math.round(cur.x)}px, ${Math.round(cur.y)}px, 0) translate(-50%, -50%)`,
                  ['--flow-color' as string]: b.colorHex,
                }}
              >
                <span className="o3d-flow-dot" aria-hidden />
                <span className="o3d-flow-route">{b.routeText}</span>
                <span className="o3d-flow-sep" aria-hidden>·</span>
                <span className="o3d-flow-text">{b.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
