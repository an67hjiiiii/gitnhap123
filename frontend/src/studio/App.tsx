import { percent } from './utils/measurement';
import './styles/studio-2026.css';
import { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { Routes, Route, Navigate, Link } from 'react-router-dom';
import { Menu } from 'lucide-react';
import { Header } from './components/Header';
import { LeftPanel } from './components/LeftPanel';
import { Workspace as WorkspaceView } from './components/Workspace';
import { ConversationHistory } from './components/ConversationHistory';
import { BenchmarkLab } from './components/BenchmarkLab';
import { DatabaseExplorer } from './components/DatabaseExplorer';
import { DocumentChunksModal } from './components/DocumentChunksModal';
import { RetrievalPlaygroundModal } from './components/RetrievalPlaygroundModal';
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
  logout
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

function DashboardWorkspace({
  user,
  onLogout
}: {
  user: User | null;
  onLogout: () => void;
}) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [telemetryLogs, setTelemetryLogs] = useState<TelemetryRecord[]>([]);
  const [mode, setMode] = useState<ExecutionMode>('proposed_adaptive');
  const [activeTab, setActiveTab] = useState<NavigationTab>('orchestration');
  const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false);
  const [toast, setToast] = useState<{ text: string; tone: 'error' | 'ok' } | null>(null);
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(t);
  }, [toast]);

  // Robot Assistant Controls
  const { setState: setRobotState, speak: robotSpeak } = useRobotAssistant();

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [currentWorkspaceId, setCurrentWorkspaceId] = useState<number | string>(0);

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

  // Nhật ký lượt chạy chỉ cần ở trang Thực nghiệm.
  const refreshTelemetry = () => getTelemetry(currentWorkspaceId).then(setTelemetryLogs).catch(() => undefined);
  useEffect(() => { if (activeTab === 'benchmarks') void refreshTelemetry(); }, [activeTab]);

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

  const handleUpload = async (file: File) => {
    setIsUploading(true);
    setRobotState('searching');
    robotSpeak(`Đang phân đoạn và lưu trữ bản sao ${file.name} vào CSDL & Vector DB...`);
    try {
      await uploadDocument(file, currentWorkspaceId);
      await refreshState();
      setRobotState('happy');
      robotSpeak(`Đã chỉ mục thành công tài liệu ${file.name}!`);
    } catch (err: any) {
      setRobotState('error');
      robotSpeak(`Lỗi tải tệp: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  const handleSeedDocs = async () => {
    setIsSeeding(true);
    setRobotState('working');
    robotSpeak('Đang tự động nạp 3 bộ tài liệu mẫu chuẩn hóa của Đồ án Tốt nghiệp C1SE.27...');
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

  const handleCreateWorkspace = async (name: string, description: string) => {
    try {
      const newWs = await createWorkspace(name, description);
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
      await clearDocuments(currentWorkspaceId);
      await refreshState();
      setRobotState('idle');
      robotSpeak('Đã làm trống cơ sở dữ liệu tri thức.');
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

  return (
    <div className="st-app">
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
        onDeleteWorkspace={handleDeleteWorkspace}
        onLogout={onLogout}
        isMobileDrawerOpen={isMobileDrawerOpen}
        onToggleMobileDrawer={() => setIsMobileDrawerOpen(prev => !prev)}
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
        />
        {user && <ConversationHistory conversations={conversations} activeId={activeConversationId}
          onOpen={id => { setActiveConversationId(id); setActiveTab('orchestration'); setIsMobileDrawerOpen(false); }}
          onNew={() => { setActiveConversationId(null); setActiveTab('orchestration'); setIsMobileDrawerOpen(false); }} />}
      </Header>

      <div className="st-main">
        <div className="st-mobilebar">
          <button className="icon-btn" onClick={() => setIsMobileDrawerOpen(true)} aria-label="Mở thanh bên" aria-expanded={isMobileDrawerOpen}><Menu size={20} /></button>
          <b>{activeTab === 'orchestration' ? 'Không gian làm việc' : activeTab === 'benchmarks' ? 'Thực nghiệm' : 'Cơ sở dữ liệu'}</b>
        </div>
        {!currentWorkspaceId && <div className="st-banner is-info">Bạn chưa chọn không gian làm việc. <button onClick={() => { const name = window.prompt('Tên không gian làm việc mới'); if (name?.trim()) void handleCreateWorkspace(name.trim(), ''); }}>Tạo không gian đầu tiên</button></div>}
        {!user && (
          <div className="st-banner is-warn">
            <span><b>Chế độ khách:</b> đăng nhập để lưu lượt chạy và quản lý tài liệu.</span>
            <Link to="/login">Đăng nhập</Link>
          </div>
        )}
        {activeTab === 'orchestration' && <WorkspaceView workspaceId={currentWorkspaceId} conversationId={activeConversationId} onConversation={setActiveConversationId} onChanged={refreshConversations} userName={user?.full_name}
          docCount={documents.length} chunkCount={documents.reduce((n, d) => n + (d.chunks_count || 0), 0)} modelOk={health?.ollama_status === 'CONNECTED'}
          workspaceName={workspaces.find(w => w.id === currentWorkspaceId)?.name} recent={conversations}
          onSeed={handleSeedDocs} onUploadFile={handleUpload} onOpenPlayground={() => handleOpenPlayground()} />}
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
      <Route path="/studio" element={sessionLoading ? <div role="status" className="page-loading">Đang xác thực phiên làm việc…</div> : user ? <DashboardWorkspace key={user.id} user={user} onLogout={handleLogout} /> : <Navigate to="/login" replace />} />
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
