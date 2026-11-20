import { motionAllowed } from './utils/motion';
import { flushSync } from 'react-dom';
import { percent } from './utils/measurement';
import './styles/studio-2026.css';
import '@fontsource-variable/inter-tight';
import './styles/studio-glass.css';
import './styles/studio-system.css';
import { StudioBackdrop, useStudioMotion } from './components/StudioMotion';
import { Command, CommandPalette } from './components/CommandPalette';
import { shouldPlayIntro, StudioIntro } from './components/StudioIntro';
import { PageGuide } from './components/PageGuide';
import gsap from 'gsap';
import { Users, BarChart3, ClipboardCheck, Database, EyeOff, FileSearch, FlaskConical, GitCompareArrows, MessageSquarePlus, MessagesSquare, Sparkles } from 'lucide-react';
import { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { Routes, Route, Navigate, Link } from 'react-router-dom';
import { Menu, Wrench } from 'lucide-react';
import { Header } from './components/Header';
import { LeftPanel } from './components/LeftPanel';
import { Workspace as WorkspaceView } from './components/Workspace';
import { ConversationHistory } from './components/ConversationHistory';
import { BenchmarkLab } from './components/BenchmarkLab';
import { DatabaseExplorer } from './components/DatabaseExplorer';
import { DocumentChunksModal } from './components/DocumentChunksModal';
import { RetrievalPlaygroundModal } from './components/RetrievalPlaygroundModal';
import { ToolkitView } from './components/ToolkitView';
import { EvaluationView } from './components/EvaluationView';
import { BlindRatingView } from './components/BlindRatingView';
import { UsersAdminView } from './components/UsersAdminView';
import { AdminPortal } from './components/admin/AdminPortal';
import { ConsistencyView } from './components/ConsistencyView';
import { DocumentProfileView } from './components/DocumentProfileView';
import { OverviewView } from './components/OverviewView';
import { OrgView } from './components/OrgView';
import { LibraryView } from './components/LibraryView';
import { SavedResultsView } from './components/SavedResultsView';
import { TasksView } from './components/TasksView';
import { SettingsView } from './components/SettingsView';
import { orgNoteText } from './components/Header';
const LandingPage = lazy(() => import('./pages/LandingPage').then(module => ({default: module.LandingPage}))); 
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { ForgotPasswordPage } from './pages/ForgotPasswordPage';
import { RobotProvider, useRobotAssistant } from './components/robot/RobotContext';
import { 
  analyzeQuery, 
  getDocuments, 
  uploadDocument, 
  seedSampleDocs, 
  clearDocuments, 
  deleteDocument,
  getTelemetry, 
  listConversations,
  deleteWorkspace,
  Conversation,
  getHealth,
  getWorkspaces,
  createWorkspace,
  getMe,
  logout,
  libraryQuality,
  setOrgScope,
  setDomainPack,
  packLabel,
  renameWorkspace,
  updateSpace,
  DomainPack,
  isOrgId,
  joinSpace,
  Classification,
  orgTerms,
} from './services/api';
import { 
  DocumentInfo, 
  TelemetryRecord, 
  HealthResponse, 
  ExecutionMode, 
  ModeExecutionResult,
  NavigationTab,
  User,
  Workspace
} from './types';
// Tên trang trên thanh trên cùng (điện thoại). Đợt 6: bố cục 7 trang (mục 2b).
const PAGE_TITLE: Record<string, string> = {
  orchestration: 'Không gian làm việc', library: 'Thư viện tài liệu', results: 'Kết quả đã lưu', tasks: 'Việc cần làm',
  organization: 'Tổ chức', overview: 'Tổng quan', settings: 'Cài đặt', documents: 'Hồ sơ tài liệu', consistency: 'Kiểm tra mâu thuẫn',
  toolkit: 'Bộ công cụ theo ngành', evaluation: 'Phòng đánh giá', benchmarks: 'Thực nghiệm', rating: 'Chấm mù', users: 'Người dùng',
};

function DashboardWorkspace({
  user,
  onLogout,
  onUserChange
}: {
  user: User | null;
  onLogout: () => void;
  onUserChange: (u: User) => void;
}) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [telemetryLogs, setTelemetryLogs] = useState<TelemetryRecord[]>([]);
  const [mode, setMode] = useState<ExecutionMode>('proposed_adaptive');
  const [activeTab, setActiveTab] = useState<NavigationTab>('orchestration');
  const [portal, setPortal] = useState<'research' | 'admin'>(() => { try { return localStorage.getItem('orchestriq-portal') === 'admin' ? 'admin' : 'research'; } catch { return 'research'; } });
  const adminMode = user?.role === 'admin' && portal === 'admin';
  const switchPortal = (p: 'research' | 'admin') => { setPortal(p); try { localStorage.setItem('orchestriq-portal', p); } catch { /* chế độ riêng tư */ } };
  const [prefill, setPrefill] = useState<{ text: string; key: number; sourceId?: string; sourceName?: string } | null>(null);
  const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false);
  const [toast, setToast] = useState<{ text: string; tone: 'error' | 'ok' | 'warn' } | null>(null);
  const [freshDoc, setFreshDoc] = useState<{ id: string; name: string } | null>(null);
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(t);
  }, [toast]);

  // Robot Assistant Controls
  const { setState: setRobotState, speak: robotSpeak } = useRobotAssistant();

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  // nhớ không gian vừa dùng (tiện ích riêng của trình duyệt); không còn quyền thì refreshState tự về không gian đầu tiên
  const wsKey = `orchestriq-ws-${user?.id ?? ''}`;
  const [currentWorkspaceId, setCurrentWorkspaceId] = useState<number | string>(() => { try { return localStorage.getItem(wsKey) || 0; } catch { return 0; } });
  useEffect(() => { try { if (currentWorkspaceId) localStorage.setItem(wsKey, String(currentWorkspaceId)); } catch { /* chế độ riêng tư */ } }, [currentWorkspaceId]);

  // Analysis & Ingestion States
  const [resultsMap, setResultsMap] = useState<Record<string, ModeExecutionResult>>({});
  const [isAblationRunning, setIsAblationRunning] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const refreshConversations = () => { if (user && currentWorkspaceId) listConversations(currentWorkspaceId).then(setConversations).catch(() => undefined); };
  const [isUploading, setIsUploading] = useState(false);
  const [isSeeding, setIsSeeding] = useState(false);

  // Knowledge Base Modals State (Phase 3)
  const [selectedDocForInspection, setSelectedDocForInspection] = useState<DocumentInfo | null>(null);
  const [isChunksModalOpen, setIsChunksModalOpen] = useState(false);
  const [isPlaygroundModalOpen, setIsPlaygroundModalOpen] = useState(false);
  const [playgroundInitialQuery, setPlaygroundInitialQuery] = useState('');

  setOrgScope(currentWorkspaceId);
  const currentWs = workspaces.find(w => w.id === currentWorkspaceId);
  const [profileSource, setProfileSource] = useState('');  // Thư viện → Hồ sơ tài liệu của đúng tài liệu
  // Việc cần làm chỉ có trong tổ chức: đổi sang không gian cá nhân thì về Không gian làm việc
  useEffect(() => { if (activeTab === 'tasks' && currentWs && currentWs.kind !== 'org') setActiveTab('orchestration'); }, [activeTab, currentWs]);
  const inOrg = isOrgId(currentWorkspaceId);
  setDomainPack(currentWs?.domain_pack);
  // thiếu lĩnh vực (dữ liệu cũ) = Phần mềm; quyết định bộ lọc kho tài liệu và nội dung trang Bộ công cụ
  const isSoftware = (currentWs?.domain_pack ?? 'software') === 'software';

  const refreshSequence = useRef(0);
  const selectedWorkspace = useRef(currentWorkspaceId);
  selectedWorkspace.current = currentWorkspaceId;
  const refreshState = async () => {
    const sequence = ++refreshSequence.current;
    try {
      const wsList = await getWorkspaces();
      if (sequence !== refreshSequence.current) return;
      setWorkspaces(wsList);
      if (!wsList.some(ws => ws.id === currentWorkspaceId)) {
        setCurrentWorkspaceId(wsList[0]?.id ?? 0);
        return;
      }
      const [h, docs] = await Promise.all([getHealth(currentWorkspaceId), getDocuments(currentWorkspaceId)]);
      if (sequence !== refreshSequence.current || selectedWorkspace.current !== currentWorkspaceId) return;
      setHealth(h); setDocuments(docs);
    } catch (err) {
      console.error('Không tải được trạng thái workspace:', err);
    }
  };

  useEffect(() => {
    setDocuments([]); setTelemetryLogs([]); setResultsMap({}); setHealth(null); setConversations([]);
    refreshConversations();
    setSelectedDocForInspection(null); setIsChunksModalOpen(false); setIsPlaygroundModalOpen(false);
    refreshState();
    const interval = setInterval(refreshState, 15000);
    return () => { clearInterval(interval); refreshSequence.current++; };
  }, [currentWorkspaceId]);

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get('join');
    if (!token) return;
    window.history.replaceState(null, '', window.location.pathname);
    joinSpace(token).then(r => { setToast({ text: `Đã gửi yêu cầu vào "${r.space_name}". Bạn vào được sau khi được duyệt.`, tone: 'ok' }); setActiveTab('organization'); })
      .catch(e => setToast({ text: e.message, tone: 'error' }));
  }, []);

  // Nhật ký lượt chạy chỉ cần ở trang Thực nghiệm.
  const refreshTelemetry = () => getTelemetry(currentWorkspaceId).then(setTelemetryLogs).catch(() => undefined);
  useEffect(() => { if (activeTab === 'benchmarks') void refreshTelemetry(); }, [activeTab]);
  const [intro, setIntro] = useState(shouldPlayIntro);
  useStudioMotion(activeTab, !intro);
  const endIntro = () => {
    setIntro(false);
    if (!!motionAllowed())
      gsap.fromTo('.st-app > .sb', { x: -36, opacity: 0 }, { x: 0, opacity: 1, duration: 0.7, ease: 'power3.out', clearProps: 'transform,opacity' });
  };
  const [paletteOpen, setPaletteOpen] = useState(false);
  // chế độ sáng/tối: tiện ích riêng của người xem, lưu trong trình duyệt (lỗi thì về sáng)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => { try { return localStorage.getItem('studio-theme') === 'dark' ? 'dark' : 'light'; } catch { return 'light'; } });
  // đổi sáng/tối: giao diện mới lan ra thành vòng tròn từ đúng chỗ bấm (View Transitions API); trình duyệt không hỗ trợ thì đổi ngay
  const changeTheme = (t: 'light' | 'dark', at?: { x: number; y: number }) => {
    const apply = () => { flushSync(() => setTheme(t)); try { localStorage.setItem('studio-theme', t); } catch { /* bỏ qua */ } };
    const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
    // trang đang ẩn (tab nền): không có khung hình để chạy hiệu ứng, đổi ngay để giao diện không kẹt
    if (t === theme || !doc.startViewTransition || !motionAllowed() || document.visibilityState !== 'visible') { apply(); return; }
    const x = at?.x ?? window.innerWidth - 40, y = at?.y ?? window.innerHeight - 40;
    const r = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    const vt = doc.startViewTransition(apply);
    vt.ready.then(() => document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
      { duration: 700, easing: 'cubic-bezier(.16,1,.3,1)', pseudoElement: '::view-transition-new(root)' } as KeyframeAnimationOptions,
    )).catch(() => { /* bỏ qua */ });
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen(o => !o); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Execution Handlers
  const handleRunAblation = async (query: string) => {
    setIsAblationRunning(true);
    setRobotState('working');
    robotSpeak('Đang chạy lần lượt ba phương pháp đối chứng trên mô hình cục bộ...');
    try {
      const response = await analyzeQuery(
        query, 
        'ablation_comparison', 
        4, 
        currentWorkspaceId, 
        user?.id
      );
      if (selectedWorkspace.current !== currentWorkspaceId) return;
      setResultsMap(response.results);
      const updatedTelem = await getTelemetry(currentWorkspaceId).catch(() => []);
      if (selectedWorkspace.current !== currentWorkspaceId) return;
      setTelemetryLogs(updatedTelem);
      setRobotState('completed');
      robotSpeak('Đã hoàn tất đo lường thực nghiệm đối chứng 3 baseline!');
    } catch (err: any) {
      setRobotState('error');
      robotSpeak(`Lỗi thực nghiệm đối chứng: ${err.message}`);
      setToast({ text: `Lỗi thực nghiệm đối chứng: ${err.message}`, tone: 'error' });
    } finally {
      setIsAblationRunning(false);
    }
  };

  const handleUpload = async (file: File, publish?: { classification: Classification; department_id?: string | null }) => {
    setIsUploading(true);
    setRobotState('searching');
    robotSpeak(`Đang phân đoạn và lưu trữ bản sao ${file.name} vào CSDL & Vector DB...`);
    try {
      const up = await uploadDocument(file, currentWorkspaceId, publish);
      await refreshState();
      setRobotState('happy');
      robotSpeak(`Đã chỉ mục thành công tài liệu ${file.name}!`);
      if (up.source_id) {
        const id = up.source_id;
        setFreshDoc({ id, name: file.name });
        // Kiểm tra chất lượng ngay sau khi nạp: báo tài liệu trùng, quá ngắn, không đọc được chữ, lỗi mã hóa.
        libraryQuality().then(q => {
          const bad = q.docs.find(d => d.source_id === id)?.issues.filter(i => i.level !== 'low') || [];
          if (bad.length) setToast({ text: `${file.name}: ${bad.map(i => i.message).join(' ')}`, tone: 'warn' });
        }).catch(() => {});
      }
    } catch (err: any) {
      setRobotState('error');
      robotSpeak(`Lỗi tải tệp: ${err.message}`);
      throw err; // để nơi gọi hiện lỗi, không báo "Đã thêm" khi máy chủ từ chối
    } finally {
      setIsUploading(false);
    }
  };

  const handleSeedDocs = async () => {
    setIsSeeding(true);
    setRobotState('working');
    robotSpeak('Đang nạp bộ tài liệu mẫu...');
    try {
      await seedSampleDocs(currentWorkspaceId);
      await refreshState();
      setRobotState('happy');
      robotSpeak('Đã nạp xong bộ tài liệu mẫu! Hãy chạy thử yêu cầu kiến trúc.');
    } catch (err: any) {
      setRobotState('error');
      robotSpeak(`Lỗi nạp mẫu: ${err.message}`);
    } finally {
      setIsSeeding(false);
    }
  };

  const handleChangeDomainPack = async (pack: DomainPack) => {
    if (!currentWs) return;
    if (isOrgId(currentWs.id)) await updateSpace(currentWs.id, { domain_pack: pack });
    else await renameWorkspace(currentWs.id, currentWs.name, currentWs.description ?? '', pack);
    setWorkspaces(prev => prev.map(w => w.id === currentWs.id ? { ...w, domain_pack: pack } : w));
  };

  const handleCreateWorkspace = async (name: string, description: string, pack: DomainPack = 'general') => {
    try {
      const newWs = await createWorkspace(name, description, pack);
      setWorkspaces(prev => [...prev, newWs]);
      setCurrentWorkspaceId(newWs.id);
      setActiveConversationId(null);
      setRobotState('happy');
      robotSpeak(`Đã khởi tạo thành công không gian làm việc mới: "${name}"!`);
    } catch (err: any) {
      setRobotState('error');
      robotSpeak(`Lỗi tạo dự án: ${err.message}`);
      throw err;
    }
  };

  const handleDeleteWorkspace = async (wsId: number | string, deleteSources: boolean) => {
    try {
      const target = workspaces.find(w => w.id === wsId);
      const r = await deleteWorkspace(wsId, deleteSources);
      setWorkspaces(prev => prev.filter(w => w.id !== wsId));
      if (currentWorkspaceId === wsId) { setCurrentWorkspaceId(r.moved_to); setActiveConversationId(null); }
      setToast({ text: `Đã xóa không gian "${target?.name ?? ''}"${deleteSources ? ` và ${r.sources_deleted} tài liệu` : ''}.`, tone: 'ok' });
      void refreshState();
    } catch (err: any) {
      setToast({ text: err.message, tone: 'error' });
    }
  };

  // mở một không gian tổ chức (hoặc '' = quay về thư mục cá nhân đầu tiên) sau khi danh sách đã làm mới
  const openSpace = async (id: string) => {
    const list = await getWorkspaces().catch(() => workspaces);
    setWorkspaces(list);
    const next = id || list.find(w => w.kind !== 'org')?.id || list[0]?.id || 0;
    setCurrentWorkspaceId(next); setActiveConversationId(null);
  };

  const handleWorkspaceChange = (wsId: number | string) => {
    setCurrentWorkspaceId(wsId);
    setActiveConversationId(null);
    const targetWs = workspaces.find(w => w.id === wsId);
    setRobotState('searching');
    robotSpeak(`Đã chuyển sang dự án: "${targetWs?.name || 'mới'}". Đang tải kho tài liệu...`);
  };


  const handleClearDocs = async () => {
    if (window.confirm('Bạn có chắc chắn muốn xóa toàn bộ tài liệu trong workspace hiện tại?')) {
      setRobotState('working');
      robotSpeak('Đang xóa tài liệu và vector thuộc workspace hiện tại...');
      try {
        await clearDocuments(currentWorkspaceId);
        setRobotState('idle');
        robotSpeak('Đã làm trống cơ sở dữ liệu tri thức.');
      } catch (err: any) {
        setRobotState('error');
        setToast({ text: `Lỗi xóa tài liệu: ${err.message}`, tone: 'error' });
      }
      await refreshState();
    }
  };

  // Phase 3 Knowledge Base Handlers
  const handleInspectDocument = (doc: DocumentInfo) => {
    setSelectedDocForInspection(doc);
    setIsChunksModalOpen(true);
    setRobotState('searching');
    robotSpeak(`Đang mở bảng soi chi tiết các phân đoạn Chunks của tài liệu "${doc.source_file}"...`);
  };

  const handleOpenPlayground = (initQuery?: string) => {
    setPlaygroundInitialQuery(initQuery || '');
    setIsPlaygroundModalOpen(true);
    setRobotState('thinking');
    robotSpeak('Đã mở Phòng thử nghiệm truy xuất vector (Retrieval Playground). Hãy nhập câu hỏi thử nghiệm.');
  };

  const handleDeleteSingleDoc = async (docId: number) => {
    setRobotState('working');
    robotSpeak('Đang xóa tài liệu và các điểm vector liên quan trong Qdrant...');
    try {
      await deleteDocument(docId);
      await refreshState();
      setRobotState('idle');
      robotSpeak('Đã xóa tài liệu thành công khỏi kho tri thức.');
    } catch (err: any) {
      setRobotState('error');
      robotSpeak(`Lỗi xóa tài liệu: ${err.message}`);
      setToast({ text: `Lỗi xóa tài liệu: ${err.message}`, tone: 'error' });
    }
  };

  const handleSearchingState = (isSearching: boolean, query?: string, resultSummary?: string) => {
    if (isSearching) {
      setRobotState('retrieving');
      robotSpeak(`Đang tính toán ma trận Cosine Similarity trong Qdrant cho truy vấn: "${query}"...`);
    } else {
      setRobotState('completed');
      robotSpeak(resultSummary || 'Đã hoàn thành kiểm tra truy xuất vector.');
    }
  };

  // Admin Portal: quản trị viên chuyển sang giao diện quản trị riêng (không robot, không chat); lựa chọn được nhớ.
  if (adminMode && user) return (
    <div className="st-app is-admin" data-theme={theme} data-motion={motionAllowed() ? 'full' : 'reduced'}>
      <AdminPortal user={user} theme={theme} onThemeChange={changeTheme} onLogout={onLogout} onExit={() => switchPortal('research')} />
      {toast && <div className={`st-toast is-${toast.tone}`} role="alert"><span>{toast.text}</span><button onClick={() => setToast(null)} aria-label="Đóng thông báo">×</button></div>}
    </div>
  );

  return (
    <div className="st-app" data-theme={theme} data-motion={motionAllowed() ? 'full' : 'reduced'}>
      <StudioBackdrop />
      {intro && user && <StudioIntro name={user.full_name?.trim().split(/\s+/).slice(-1)[0]} onDone={endIntro} />}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={[
        ...([
          ['orchestration', 'Không gian làm việc', MessagesSquare], ['library', 'Thư viện tài liệu', FileSearch], ['results', 'Kết quả đã lưu', FileSearch],
          ...(currentWs?.kind === 'org' ? [['tasks', 'Việc cần làm', ClipboardCheck]] : []), ['organization', 'Tổ chức', Users], ['overview', 'Tổng quan', BarChart3],
          ['settings', 'Cài đặt', Wrench], ['documents', 'Hồ sơ tài liệu', FileSearch], ['consistency', 'Kiểm tra mâu thuẫn', GitCompareArrows],
          ['toolkit', 'Bộ công cụ theo ngành', Wrench],
          ['evaluation', 'Phòng đánh giá', ClipboardCheck], ['benchmarks', 'Thực nghiệm', FlaskConical],
          ['rating', 'Chấm mù', EyeOff], ...(user?.role === 'admin' ? [['users', 'Người dùng', Users], ['db_explorer', 'Cơ sở dữ liệu', Database]] : []),
        ] as [NavigationTab, string, Command['Icon']][]).map(([id, label, Icon]) => ({ id: `go-${id}`, label, group: 'Đi đến', Icon, run: () => setActiveTab(id) })),
        { id: 'new-chat', label: 'Cuộc trò chuyện mới', group: 'Thao tác', Icon: MessageSquarePlus, run: () => { setActiveConversationId(null); setActiveTab('orchestration'); } },
        { id: 'seed', label: 'Nạp bộ tài liệu mẫu PayNhanh', group: 'Thao tác', Icon: Sparkles, run: () => { void handleSeedDocs(); } },
        ...conversations.slice(0, 12).map(c => ({ id: `conv-${c.conversation_id}`, label: c.title || 'Không tên', group: 'Cuộc trò chuyện gần đây', Icon: MessagesSquare,
          run: () => { setActiveConversationId(c.conversation_id); setActiveTab('orchestration'); } })),
      ]} />
      <Header
        health={health}
        onSeedDocs={handleSeedDocs}
        isSeeding={isSeeding}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        user={user}
        workspaces={workspaces}
        currentWorkspaceId={currentWorkspaceId}
        onWorkspaceChange={handleWorkspaceChange}
        onCreateWorkspace={handleCreateWorkspace}
        onChangeDomainPack={handleChangeDomainPack}
        onDeleteWorkspace={handleDeleteWorkspace}
        onLogout={onLogout}
        onUserChange={onUserChange}
        isMobileDrawerOpen={isMobileDrawerOpen}
        onToggleMobileDrawer={() => setIsMobileDrawerOpen(prev => !prev)}
        onOpenPalette={() => { setIsMobileDrawerOpen(false); setPaletteOpen(true); }}
        theme={theme}
        onThemeChange={changeTheme}
        onOpenAdmin={user?.role === 'admin' ? () => switchPortal('admin') : undefined}
        onOrgChanged={() => { void refreshState(); }}
      >
        <LeftPanel
          documents={documents}
          onUpload={handleUpload}
          onClear={handleClearDocs}
          onSeedDocs={handleSeedDocs}
          onInspectDocument={handleInspectDocument}
          onOpenPlayground={() => handleOpenPlayground()}
          onDeleteDocument={handleDeleteSingleDoc}
          isUploading={isUploading}
          totalChunks={documents.reduce((n, d) => n + (d.chunks_count || 0), 0)}
          user={user}
          orgLevel={inOrg ? currentWs?.level : undefined}
          terms={inOrg ? orgTerms(currentWs) : undefined}
          softwareFilter={isSoftware}
          spaceId={inOrg ? String(currentWorkspaceId) : undefined}
        />
        {user && <ConversationHistory conversations={conversations} activeId={activeConversationId}
          onOpen={id => { setActiveConversationId(id); setActiveTab('orchestration'); setIsMobileDrawerOpen(false); }}
          onNew={() => { setActiveConversationId(null); setActiveTab('orchestration'); setIsMobileDrawerOpen(false); }}
          onChanged={refreshConversations} />}
      </Header>

      <div className="st-main">
        {!intro && <PageGuide page={activeTab} />}
        <div className="st-mobilebar">
          <button className="icon-btn" onClick={() => setIsMobileDrawerOpen(true)} aria-label="Mở thanh bên" aria-expanded={isMobileDrawerOpen}><Menu size={20} /></button>
          <b>{PAGE_TITLE[activeTab] ?? 'Cơ sở dữ liệu'}</b>
        </div>
        {!currentWorkspaceId && <div className="st-banner is-info">Bạn chưa chọn không gian làm việc. <button onClick={() => { const name = window.prompt('Tên không gian làm việc mới'); if (name?.trim()) void handleCreateWorkspace(name.trim(), ''); }}>Tạo không gian đầu tiên</button></div>}
        {inOrg && currentWs && <div className="st-banner is-info og-banner"><span><b>{currentWs.name}</b>{currentWs.level ? ` · ${orgTerms(currentWs).level[currentWs.level]}` : ''}: AI và các công cụ chỉ dùng tài liệu bạn được phép xem trong tổ chức này.</span>
          {activeTab !== 'organization' && <button onClick={() => setActiveTab('organization')}>Quản lý tổ chức</button>}</div>}
        {!user && (
          <div className="st-banner is-warn">
            <span><b>Chế độ khách:</b> đăng nhập để lưu lượt chạy và quản lý tài liệu.</span>
            <Link to="/login">Đăng nhập</Link>
          </div>
        )}
        {activeTab === 'orchestration' && <WorkspaceView workspaceId={currentWorkspaceId} conversationId={activeConversationId} onConversation={setActiveConversationId} onChanged={refreshConversations} userName={user?.full_name}
          docCount={documents.length} chunkCount={documents.reduce((n, d) => n + (d.chunks_count || 0), 0)} modelOk={health?.ollama_status === 'CONNECTED'}
          workspaceName={workspaces.find(w => w.id === currentWorkspaceId)?.name} recent={conversations}
          onSeed={handleSeedDocs} onUploadFile={handleUpload} docs={documents} prefill={prefill} freshDoc={freshDoc} onOpenToolkit={() => setActiveTab('toolkit')} />}
        {activeTab === 'organization' && <OrgView workspaceId={currentWorkspaceId} docs={documents} onOpenSpace={id => { void openSpace(id); }} onChanged={refreshState} onAsk={() => setActiveTab('orchestration')} />}
        {activeTab === 'overview' && <OverviewView health={health} userName={user?.full_name} />}
        {activeTab === 'documents' && <DocumentProfileView key={`doc-${currentWorkspaceId}-${profileSource}`} docs={documents} initialSourceId={profileSource || undefined}
          onAsk={(q, sourceId, sourceName) => { setActiveConversationId(null); setPrefill({ text: q, key: Date.now(), sourceId, sourceName }); setActiveTab('orchestration'); }} />}
        {activeTab === 'library' && <LibraryView docs={documents} onUploadFile={async f => { await handleUpload(f); }}
          onOpenProfile={id => { setProfileSource(id); setActiveTab('documents'); }} onOpenConsistency={() => setActiveTab('consistency')}
          onAsk={(sourceId, name) => { setActiveConversationId(null); setPrefill({ text: `Nội dung chính của tài liệu ${name} là gì?`, key: Date.now(), sourceId, sourceName: name }); setActiveTab('orchestration'); }} />}
        {activeTab === 'results' && <SavedResultsView onOpen={(tab, r) => {
          // hồ sơ, sơ đồ tư duy: tên báo cáo là tên tệp → mở đúng tài liệu đó; công cụ khác tự nạp bản đã lưu
          const doc = (r.kind === 'doc_profile' || r.kind === 'mindmap') ? documents.find(d => d.source_file === r.title) : undefined;
          if (doc) setProfileSource(String(doc.id));
          setActiveTab(tab);
        }} onGo={setActiveTab} />}
        {activeTab === 'tasks' && currentWs?.kind === 'org' && <TasksView spaceId={String(currentWorkspaceId)} spaceName={currentWs.name}
          noteText={n => orgNoteText(n, orgTerms(currentWs))} onOpenOrg={() => setActiveTab('organization')}
          docIds={documents.map(d => String(d.id))} levelName={{ MANAGER: orgTerms(currentWs).level.MANAGER, EXECUTIVE: orgTerms(currentWs).level.EXECUTIVE }} />}
        {activeTab === 'settings' && user && <SettingsView user={user} theme={theme} onThemeChange={t => changeTheme(t)}
          onChangeAvatar={() => window.dispatchEvent(new Event('oq-open-avatar'))} onOpenLibrary={() => setActiveTab('library')} onChanged={refreshState} health={health} docCount={documents.length} />}
        {activeTab === 'toolkit' && <ToolkitView key={`tk-${currentWorkspaceId}-${currentWs?.domain_pack ?? 'software'}`} pack={currentWs?.domain_pack} workspaceId={currentWorkspaceId} docs={documents} />}
        {activeTab === 'consistency' && <ConsistencyView key={`cons-${currentWorkspaceId}`} workspaceId={currentWorkspaceId} docs={documents} />}
        {activeTab === 'rating' && <BlindRatingView />}
        {activeTab === 'users' && user?.role === 'admin' && <UsersAdminView currentUserId={String(user.id)} />}
        {activeTab === 'evaluation' && <EvaluationView key={`eval-${currentWorkspaceId}`} docs={documents} />}
        {activeTab === 'benchmarks' && <div className="st-legacy"><BenchmarkLab resultsMap={resultsMap} telemetryLogs={telemetryLogs} onRefreshTelemetry={refreshTelemetry} onRunAblation={handleRunAblation} isAblationRunning={isAblationRunning} /></div>}
        {activeTab === 'db_explorer' && user?.role === 'admin' && <div className="st-legacy"><DatabaseExplorer /></div>}
      </div>

      {/* Phase 3 Modals: Chunks Inspection & Retrieval Playground */}
      <DocumentChunksModal
        document={selectedDocForInspection}
        isOpen={isChunksModalOpen}
        onClose={() => {
          setIsChunksModalOpen(false);
          setSelectedDocForInspection(null);
        }}
        onOpenPlaygroundWithQuery={(sourceFile) => {
          handleOpenPlayground(`Truy vấn ngữ cảnh liên quan đến tài liệu: ${sourceFile}`);
        }}
      />

      {toast && <div className={`st-toast is-${toast.tone}`} role="alert"><span>{toast.text}</span><button onClick={() => setToast(null)} aria-label="Đóng thông báo">×</button></div>}

      <RetrievalPlaygroundModal
        isOpen={isPlaygroundModalOpen}
        onClose={() => setIsPlaygroundModalOpen(false)}
        workspaceId={currentWorkspaceId}
        initialQuery={playgroundInitialQuery}
        onSearchingState={handleSearchingState}
      />
    </div>
  );
}

function AppContent() {
  const { setState: setRobotState, speak: robotSpeak } = useRobotAssistant();

  const [user, setUser] = useState<User | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  useEffect(() => {
    let active = true;
    getMe().then(value => { if (active) setUser(value); }).catch(() => {
      logout(); if (active) setUser(null);
    }).finally(() => { if (active) setSessionLoading(false); });
    return () => { active = false; };
  }, []);
  // Cookie phiên dùng chung cho mọi tab: đăng nhập tài khoản khác ở tab khác thì tab này đang hiện người cũ
  // nhưng máy chủ đã trả dữ liệu của người mới. Quay lại tab mà phiên đã đổi thì tải lại để khớp đúng người.
  const userRef = useRef(user);
  userRef.current = user;
  useEffect(() => {
    const check = () => {
      if (document.hidden) return;
      getMe().then(me => { if (userRef.current && String(me.id) !== String(userRef.current.id)) window.location.reload(); })
        // đã đăng xuất ở tab khác thì tải lại (về trang đăng nhập); lỗi mạng thì bỏ qua, không tải lại liên tục
        .catch(e => { if (userRef.current && e?.message === 'Chưa đăng nhập') window.location.reload(); });
    };
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);
    return () => { window.removeEventListener('focus', check); document.removeEventListener('visibilitychange', check); };
  }, []);

  const handleLoginSuccess = (loggedUser: User) => {
    setUser(loggedUser);
    setRobotState('happy');
    robotSpeak(`Xin chào ${loggedUser.full_name}! Chạm vào khung bên dưới để bắt đầu nhé.`);
  };

  const handleLogout = () => {
    logout();
    setUser(null);
    setRobotState('idle');
    robotSpeak('Đã đăng xuất tài khoản. Bạn có thể đăng nhập lại bất kỳ lúc nào.');
  };

  return (
    <Routes>
      <Route path="/" element={<Suspense fallback={<div className="page-loading" role="status">Đang mở không gian C27…</div>}><LandingPage /></Suspense>} />
      <Route path="/studio" element={sessionLoading ? <div role="status" className="page-loading">Đang xác thực phiên làm việc…</div> : user ? <DashboardWorkspace key={user.id} user={user} onLogout={handleLogout} onUserChange={setUser} /> : <Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage onLoginSuccess={handleLoginSuccess} />} />
      <Route path="/register" element={<RegisterPage onRegisterSuccess={handleLoginSuccess} />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <RobotProvider>
      <AppContent />
    </RobotProvider>
  );
}

export default App;
