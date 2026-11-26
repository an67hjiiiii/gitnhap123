import { useEffect, useState } from 'react';
import {
  Camera,
  ChevronDown,
  ChevronUp,
  Clock,
  CloudLightning,
  Eye,
  EyeOff,
  Gauge,
  Moon,
  Play,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Sunset,
  Users,
} from 'lucide-react';
import {
  AGENT_PROFILES,
  COMPLEXITY_META,
  COMPLEXITY_SCENARIOS,
  SPECIALIST_AGENT_IDS,
  buildCustomComplexityScenario,
} from './agents';
import type {
  AgentId,
  CameraPresetId,
  ComplexityScenario,
  ComplexityTier,
  SpecialistAgentId,
  WeatherMode,
} from './types';

interface ControlDockProps {
  activeScenarioId: string | null;
  speedMultiplier: number;
  followLead: boolean;
  showLabels: boolean;
  weather: WeatherMode;
  selectedAgentId: AgentId | null;
  onRunScenario: (scenario: ComplexityScenario) => void;
  onSetCameraPreset: (preset: CameraPresetId) => void;
  onSetSpeed: (multiplier: number) => void;
  onToggleFollow: (follow: boolean) => void;
  onToggleLabels: (show: boolean) => void;
  onSetWeather: (mode: WeatherMode) => void;
  onResetToSleep: () => void;
}

type DockTab = 'tiers' | 'custom' | 'camera';

const TIER_ORDER: ComplexityTier[] = ['easy', 'fairly_easy', 'medium', 'hard'];

export function ControlDock({
  activeScenarioId,
  speedMultiplier,
  followLead,
  showLabels,
  weather,
  selectedAgentId,
  onRunScenario,
  onSetCameraPreset,
  onSetSpeed,
  onToggleFollow,
  onToggleLabels,
  onSetWeather,
  onResetToSleep,
}: ControlDockProps) {
  const [collapsed, setCollapsed] = useState(true);
  const [activeTab, setActiveTab] = useState<DockTab>('tiers');

  const [customTier, setCustomTier] = useState<ComplexityTier>('medium');
  const [customRequest, setCustomRequest] = useState(
    'Xây dựng kế hoạch ra mắt tính năng AI mới kèm dự toán chi phí Q3',
  );
  const [selectedSpecs, setSelectedSpecs] = useState<SpecialistAgentId[]>([
    'software',
    'marketing',
    'finance',
  ]);
  const [enableAnalyst, setEnableAnalyst] = useState(true);
  const [enableReviewer, setEnableReviewer] = useState(true);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (
        e.key.toLowerCase() === 'h' &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLTextAreaElement)
      ) {
        setCollapsed((v) => !v);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const toggleSpecialist = (id: SpecialistAgentId) => {
    setSelectedSpecs((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const handleLaunchCustom = () => {
    const scenario = buildCustomComplexityScenario({
      tier: customTier,
      requestTitle:
        customRequest.trim() || 'Yêu cầu tùy chỉnh đa phòng ban trong văn phòng AI',
      specialists: selectedSpecs,
      enableAnalyst,
      enableReviewer,
    });
    onRunScenario(scenario);
  };

  const selectedProfile = selectedAgentId ? AGENT_PROFILES[selectedAgentId] : null;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-3 z-30 flex justify-center px-3 sm:bottom-4 sm:px-5">
      <div className="pointer-events-auto w-full max-w-[980px] rounded-2xl border border-stone-200/95 bg-white/95 text-stone-800 shadow-[0_14px_40px_rgba(28,25,23,0.12)]">
        {/* Compact Header Strip */}
        <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => {
                setActiveTab('tiers');
                setCollapsed(false);
              }}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                activeTab === 'tiers' && !collapsed
                  ? 'bg-stone-900 text-white'
                  : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900'
              }`}
            >
              <Clock className="h-3.5 w-3.5" />
              Độ khó & Kịch bản
            </button>

            <button
              type="button"
              onClick={() => {
                setActiveTab('custom');
                setCollapsed(false);
              }}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                activeTab === 'custom' && !collapsed
                  ? 'bg-stone-900 text-white'
                  : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900'
              }`}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              Tùy chỉnh phòng ban
            </button>

            <button
              type="button"
              onClick={() => {
                setActiveTab('camera');
                setCollapsed(false);
              }}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                activeTab === 'camera' && !collapsed
                  ? 'bg-stone-900 text-white'
                  : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900'
              }`}
            >
              <Camera className="h-3.5 w-3.5" />
              Góc nhìn & Thời tiết
            </button>
          </div>

          <div className="flex items-center gap-2.5">
            {selectedProfile && (
              <div className="hidden items-center gap-1.5 text-xs text-stone-600 md:flex">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: selectedProfile.accentHex }}
                />
                <span className="font-semibold text-stone-900">{selectedProfile.name}</span>
                <span className="text-stone-300">·</span>
                <span className="text-stone-500">{selectedProfile.roomSubtitle}</span>
              </div>
            )}

            <button
              type="button"
              onClick={() => setCollapsed((v) => !v)}
              title="Thu gọn / mở rộng bảng điều khiển (Phím H)"
              className="flex items-center gap-1 rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
            >
              {collapsed ? (
                <>
                  Mở rộng <ChevronUp className="h-3.5 w-3.5" />
                </>
              ) : (
                <>
                  Thu gọn <ChevronDown className="h-3.5 w-3.5" />
                </>
              )}
            </button>
          </div>
        </div>

        {/* Collapsible Content Body */}
        {!collapsed && (
          <div className="border-t border-stone-100 px-3.5 py-3">
            {activeTab === 'tiers' && (
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
                {COMPLEXITY_SCENARIOS.map((sc) => {
                  const meta = COMPLEXITY_META[sc.tier];
                  const isActive = activeScenarioId === sc.id;
                  const awakeCount = sc.awakeAgents.length;
                  const sleepCount = 11 - awakeCount;

                  return (
                    <button
                      key={sc.id}
                      type="button"
                      onClick={() => onRunScenario(sc)}
                      className={`group flex flex-col justify-between rounded-xl border p-2.5 text-left transition-all ${
                        isActive
                          ? 'border-stone-900 bg-stone-50 shadow-sm'
                          : 'border-stone-200/90 bg-white hover:border-stone-300 hover:bg-stone-50/70'
                      }`}
                    >
                      <div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="flex items-center gap-1.5 text-xs font-bold text-stone-900">
                            <span
                              className="h-2.5 w-2.5 rounded-full"
                              style={{ backgroundColor: meta.accent }}
                            />
                            {meta.label}
                          </span>
                          <span className="font-mono text-[11px] font-semibold tabular-nums text-stone-500">
                            {sc.durationRangeVi}
                          </span>
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-[11.5px] font-medium leading-snug text-stone-800">
                          {sc.requestTitle}
                        </p>
                      </div>

                      <div className="mt-2.5 flex items-center justify-between border-t border-stone-100 pt-2 text-[11px] text-stone-500">
                        <span className="flex items-center gap-1 font-medium">
                          <Users className="h-3 w-3 text-stone-400" />
                          {awakeCount} thức · {sleepCount} ngủ
                        </span>
                        <span className="inline-flex items-center gap-0.5 font-semibold text-stone-700 group-hover:text-stone-950">
                          <Play className="h-3 w-3" />
                          Chạy
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}

            {activeTab === 'custom' && (
              <div className="space-y-2.5">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <input
                    type="text"
                    value={customRequest}
                    onChange={(e) => setCustomRequest(e.target.value)}
                    placeholder="Nhập yêu cầu công việc để chạy mô phỏng..."
                    className="flex-1 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-900 outline-none transition-colors focus:border-stone-400 focus:bg-white"
                  />
                  <div className="flex items-center gap-1">
                    {TIER_ORDER.map((t) => {
                      const meta = COMPLEXITY_META[t];
                      const active = customTier === t;
                      return (
                        <button
                          key={t}
                          type="button"
                          onClick={() => setCustomTier(t)}
                          className={`rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition-colors ${
                            active
                              ? 'border-stone-900 bg-stone-900 text-white'
                              : 'border-stone-200 bg-white text-stone-600 hover:bg-stone-50'
                          }`}
                        >
                          {meta.label}
                        </button>
                      );
                    })}
                  </div>
                  <button
                    type="button"
                    onClick={handleLaunchCustom}
                    className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-stone-900 px-3.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-stone-800"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    Chạy ngay
                  </button>
                </div>

                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[11.5px]">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold text-stone-500">Agent linh hoạt:</span>
                    <button
                      type="button"
                      onClick={() => setEnableAnalyst((v) => !v)}
                      className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 font-medium transition-colors ${
                        enableAnalyst
                          ? 'border-blue-300 bg-blue-50 text-blue-800'
                          : 'border-stone-200 bg-stone-50 text-stone-400'
                      }`}
                    >
                      <span className="h-2 w-2 rounded-full bg-[#1d4ed8]" />
                      Data Analyst (Tùy chọn)
                    </button>
                    <button
                      type="button"
                      onClick={() => setEnableReviewer((v) => !v)}
                      className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 font-medium transition-colors ${
                        enableReviewer
                          ? 'border-red-300 bg-red-50 text-red-800'
                          : 'border-stone-200 bg-stone-50 text-stone-400'
                      }`}
                    >
                      <span className="h-2 w-2 rounded-full bg-[#dc2626]" />
                      Reviewer (Có điều kiện)
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold text-stone-500">6 Phòng chuyên ngành:</span>
                    {SPECIALIST_AGENT_IDS.map((specId) => {
                      const p = AGENT_PROFILES[specId];
                      const active = selectedSpecs.includes(specId);
                      return (
                        <button
                          key={specId}
                          type="button"
                          onClick={() => toggleSpecialist(specId)}
                          className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 font-medium transition-colors ${
                            active
                              ? 'border-stone-300 bg-white text-stone-900 shadow-2xs'
                              : 'border-stone-200 bg-stone-50 text-stone-400 hover:text-stone-600'
                          }`}
                        >
                          <span
                            className="h-2 w-2 rounded-full"
                            style={{
                              backgroundColor: p.accentHex,
                              opacity: active ? 1 : 0.35,
                            }}
                          />
                          {p.shortName}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'camera' && (
              <div className="space-y-2.5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="mr-1 text-xs font-semibold text-stone-500">Thời tiết & Ánh sáng:</span>
                    {(
                      [
                        ['sunny', 'Nắng sáng', Sun, 'border-amber-500 bg-amber-500 text-white'],
                        ['sunset', 'Hoàng hôn', Sunset, 'border-orange-600 bg-orange-600 text-white'],
                        ['night', 'Ban đêm', Moon, 'border-indigo-900 bg-indigo-900 text-amber-100'],
                        ['storm', 'Mưa sấm sét', CloudLightning, 'border-slate-800 bg-slate-800 text-sky-200'],
                      ] as const
                    ).map(([id, label, Icon, activeCls]) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => onSetWeather(id)}
                        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                          weather === id
                            ? activeCls
                            : 'border-stone-200 bg-stone-50 text-stone-700 hover:border-stone-300 hover:bg-white hover:text-stone-950'
                        }`}
                      >
                        <Icon className="h-3.5 w-3.5" />
                        {label}
                      </button>
                    ))}
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="mr-1 text-xs font-semibold text-stone-500">Góc camera:</span>
                    {(
                      [
                        ['overview', 'Trong phòng'],
                        ['core_studio', 'Khu Điều phối'],
                        ['specialist_row', '6 Phòng PC'],
                        ['rag_analyst', 'Tủ RAG & Phân tích'],
                        ['city_exterior', 'Toàn cảnh ĐH Duy Tân'],
                      ] as const
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => onSetCameraPreset(id)}
                        className="rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1.5 text-xs font-medium text-stone-700 transition-colors hover:border-stone-300 hover:bg-white hover:text-stone-950"
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-stone-100 pt-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="flex items-center gap-1 rounded-lg border border-stone-200 bg-stone-50 p-0.5">
                      <Gauge className="ml-1.5 h-3.5 w-3.5 text-stone-400" />
                      {[1, 2, 4].map((sp) => (
                        <button
                          key={sp}
                          type="button"
                          onClick={() => onSetSpeed(sp)}
                          className={`rounded-md px-2 py-1 font-mono text-xs font-semibold transition-colors ${
                            speedMultiplier === sp
                              ? 'bg-stone-900 text-white'
                              : 'text-stone-600 hover:text-stone-950'
                          }`}
                        >
                          {sp}×
                        </button>
                      ))}
                    </div>

                    <button
                      type="button"
                      onClick={() => onToggleFollow(!followLead)}
                      className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                        followLead
                          ? 'border-stone-900 bg-stone-900 text-white'
                          : 'border-stone-200 bg-white text-stone-700 hover:bg-stone-50'
                      }`}
                    >
                      Lia camera theo bước
                    </button>

                    <button
                      type="button"
                      onClick={() => onToggleLabels(!showLabels)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-xs font-medium text-stone-700 transition-colors hover:bg-stone-50"
                    >
                      {showLabels ? (
                        <>
                          <Eye className="h-3.5 w-3.5" /> Ẩn nhãn 3D
                        </>
                      ) : (
                        <>
                          <EyeOff className="h-3.5 w-3.5" /> Hiện nhãn 3D
                        </>
                      )}
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={onResetToSleep}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-xs font-medium text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900"
                  >
                    <Moon className="h-3.5 w-3.5" />
                    Cho tất cả ngủ
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
