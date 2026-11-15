// Lớp gọi API của Studio, nối vào backend CAP1 (/api/*, phiên đăng nhập bằng cookie).
// Giữ tên hàm cũ để các màn hình Studio không phải đổi; chức năng CAP1 chưa có thì báo rõ, không giả lập.
import {
  AnalyzeResponse, ChunkInfo, DatabaseOverviewResponse, DbDiagnosticResponse, DocumentInfo, ExecutionMode,
  ExperimentConfig, HealthResponse, LLMContentionSimulateResponse, ModeExecutionResult, RetrievalTestRequest,
  RetrievalTestResponse, RunDetail, SecurityAuditResponse, TableDataResponse, TelemetryRecord, User, Workspace,
} from '../types';
import { adaptRun, Cap1Run, MODE_TO_CONDITION, modeOf } from './adapt';
import { contextOfPath, friendlyMessage } from '../../lib/errorMessage';

const API = '/api';
export const NOT_SUPPORTED = 'Chức năng này chưa có trong backend CAP1.';

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      credentials: 'same-origin',
      ...init,
      headers: init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json', ...(init.headers || {}) } : init.headers,
    });
  } catch (error) {
    const timedOut = error instanceof DOMException && (error.name === 'AbortError' || error.name === 'TimeoutError');
    const failure = new Error(friendlyMessage(timedOut ? { timeout: true } : { network: error instanceof TypeError }));
    (failure as any).detail = error instanceof Error ? error.message : '';
    throw failure;
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === 'string' ? body.detail : Array.isArray(body?.detail) ? body.detail.map((d: any) => d.msg).join('; ') : '';
    const translated = viError(detail);
    const failure = new Error(friendlyMessage({ status: res.status, detail: translated !== detail ? translated : detail, context: contextOfPath(path) }));
    (failure as any).status = res.status;
    (failure as any).detail = detail;
    throw failure;
  }
  return res.json();
}
// Thông báo lỗi của backend CAP1 phần lớn bằng tiếng Anh hoặc mã; đổi sang tiếng Việt cho người dùng.
const VI_ERRORS: Record<string, string> = {
  'Invalid email, username, or password': 'Email/tên đăng nhập hoặc mật khẩu không đúng.',
  'Login identifier is required': 'Vui lòng nhập email hoặc tên đăng nhập.',
  'Account already exists': 'Email hoặc tên đăng nhập này đã có tài khoản.',
  'email or username is required': 'Vui lòng nhập email hoặc tên đăng nhập.',
  'email is invalid': 'Email không hợp lệ.',
  'username is invalid': 'Tên đăng nhập 2–64 ký tự, chỉ gồm chữ không dấu, số, dấu chấm, gạch dưới, gạch ngang.',
  'Authentication is required': 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.',
  'message is required': 'Vui lòng nhập câu hỏi.',
  'text is empty': 'Nội dung trống.',
  'file is empty': 'Tệp rỗng, không có nội dung để nạp.',
  'Files must be no larger than 2 MB': 'Tệp vượt quá 2 MB.',
  UNSUPPORTED_DOCUMENT_TYPE: 'Định dạng chưa hỗ trợ. Dùng PDF, Markdown, TXT hoặc SQL.',
  PDF_NO_TEXT: 'PDF không có lớp chữ (bản scan) nên chưa đọc được.',
  PDF_EXTRACTION_UNAVAILABLE: 'Máy chủ chưa đọc được tệp PDF này.',
  UTF8_TEXT_REQUIRED: 'Tệp văn bản cần mã hóa UTF-8.',
  DOCUMENT_EXTRACTION_FAILED: 'Không trích xuất được nội dung tệp.',
  DERIVED_INDEX_FAILED: 'Không tạo được chỉ mục tìm kiếm. Kiểm tra Ollama đang chạy.',
  DERIVED_INDEX_UNAVAILABLE: 'Chỉ mục tìm kiếm chưa sẵn sàng. Kiểm tra Ollama đang chạy.',
  'source not found': 'Không tìm thấy tài liệu.',
  'conversation not found': 'Không tìm thấy cuộc trò chuyện.',
  'run not found': 'Không tìm thấy lượt chạy.',
  'chunk not found': 'Không tìm thấy đoạn tài liệu.',
};
function viError(detail: string): string {
  const min = detail.match(/^password must be at least (\d+) characters$/);
  return min ? `Mật khẩu cần ít nhất ${min[1]} ký tự.` : VI_ERRORS[detail] ?? detail;
}
const post = <T>(path: string, body: unknown) => call<T>(path, { method: 'POST', body: JSON.stringify(body) });

// ---------------- Đăng nhập (cookie phiên của CAP1)
function toUser(u: any): User {
  return {
    id: u.user_id, username: u.username || u.email || '', email: u.email || '',
    full_name: u.display_name || u.username || u.email || 'Người dùng',
    role: String(u.role || '').toUpperCase() === 'ADMIN' ? 'admin' : 'developer',
    created_at: u.created_at || '',
  } as unknown as User;
}

export async function login(identifier: string, password: string): Promise<{ user: User }> {
  const data = await post<any>('/auth/login', { identifier, password });
  return { user: toUser(data.user) };
}

export async function register(data: { username: string; email: string; password: string; full_name: string; role?: string }): Promise<{ user: User }> {
  await post('/auth/register', { email: data.email, username: data.username || undefined, display_name: data.full_name, password: data.password });
  return login(data.email, data.password);
}

export async function getMe(): Promise<User> {
  const data = await call<any>('/auth/session');
  if (!data.authenticated) throw new Error('Chưa đăng nhập');
  return toUser(data.user);
}

export async function logout(): Promise<void> {
  await fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'same-origin' }).catch(() => undefined);
}

// ---------------- Không gian làm việc (bảng studio_workspaces): nhóm tài liệu và cuộc trò chuyện
export type WorkspaceId = number | string;
const wsReady = (ws?: WorkspaceId) => typeof ws === 'string' && ws.startsWith('ws_');

export async function getWorkspaces(): Promise<Workspace[]> {
  const rows = await call<any[]>('/studio/workspaces');
  return rows.map(w => ({ id: w.workspace_id, name: w.name, description: w.description, created_at: w.created_at,
    documents_count: w.source_count, runs_count: w.conversation_count }));
}
export async function createWorkspace(name: string, description: string): Promise<Workspace> {
  const w = await post<any>('/studio/workspaces', { name, description });
  return { id: w.workspace_id, name: w.name, description: w.description, created_at: '', documents_count: 0, runs_count: 0 };
}
export async function renameWorkspace(id: WorkspaceId, name: string, description = ''): Promise<void> {
  await call(`/studio/workspaces/${encodeURIComponent(String(id))}`, { method: 'PATCH', body: JSON.stringify({ name, description }) });
}
export async function deleteWorkspace(id: WorkspaceId, deleteSources: boolean): Promise<{ moved_to: string; sources_deleted: number }> {
  return call(`/studio/workspaces/${encodeURIComponent(String(id))}?delete_sources=${deleteSources}`, { method: 'DELETE' });
}
export async function workspaceItems(id: WorkspaceId): Promise<{ source_ids: string[]; conversation_ids: string[] }> {
  if (!wsReady(id)) return { source_ids: [], conversation_ids: [] };
  return call(`/studio/workspaces/${encodeURIComponent(String(id))}/items`);
}
export async function assignToWorkspace(id: WorkspaceId, itemType: 'source' | 'conversation', itemId: string): Promise<void> {
  if (!wsReady(id)) return;
  await post(`/studio/workspaces/${encodeURIComponent(String(id))}/items`, { item_type: itemType, item_id: itemId });
}

// ---------------- Cấu hình: CAP1 cấu hình bằng biến môi trường, chỉ đọc (định danh bằng config_hash)
export async function getRuntimeConfig(): Promise<Record<string, any>> {
  return call('/config');
}
export async function getConfigs(): Promise<ExperimentConfig[]> { return []; }
export async function createConfig(_c: Partial<ExperimentConfig>): Promise<ExperimentConfig> { throw new Error(NOT_SUPPORTED); }
export async function toggleConfigLock(_id: number): Promise<ExperimentConfig> { throw new Error(NOT_SUPPORTED); }

// ---------------- Điều phối
export async function analyzeQuery(query: string, mode: ExecutionMode, _topK = 4, _ws?: WorkspaceId, _userId?: number | string): Promise<AnalyzeResponse> {
  const results: Record<string, ModeExecutionResult> = {};
  if (mode === 'ablation_comparison') {
    const scope = wsReady(_ws) ? (await workspaceItems(_ws!)).source_ids : undefined;
    const data = await post<any>('/studio/compare', { message: query, conditions: ['A', 'B', 'C'], source_ids: scope });
    for (const run of data.runs as Cap1Run[]) results[modeOf(run.condition)] = adaptRun(run);
  } else {
    const run = await post<Cap1Run>('/chat', { message: query, condition: MODE_TO_CONDITION[mode] });
    if (run.status === 'FAILED') throw new Error(explainFailure(run.answer));
    results[mode] = adaptRun(run);
  }
  return { project_name: 'CAP1 + C1SE.27', query, execution_timestamp: new Date().toISOString(), results };
}

// Lỗi pipeline CAP1 thường bằng tiếng Anh; thêm lời giải thích tiếng Việt, giữ nguyên thông báo gốc để tra cứu.
export function explainFailure(answer?: string): string {
  const raw = String(answer || 'Lượt chạy thất bại.');
  if (/failed verification/i.test(raw)) return `Kế hoạch chia việc không qua được bước tự kiểm tra (thiếu hoặc giao sai nghĩa vụ) nên hệ thống dừng, không trả kết quả nửa vời. Thử chia yêu cầu thành câu ngắn, cụ thể hơn, hoặc dùng cách A (Vanilla RAG). (${raw})`;
  if (/extraction failed|ConnectError|ConnectTimeout/i.test(raw)) return `Không gọi được mô hình ngôn ngữ (Ollama). Kiểm tra Ollama đang chạy. (${raw})`;
  return raw;
}

export async function compareConditions(message: string, conditions: string[]): Promise<Cap1Run[]> {
  return (await post<any>('/studio/compare', { message, conditions })).runs; // không dùng trong Studio; giữ API cho script
}

// ---------------- Kho tài liệu
export async function getDocuments(ws?: WorkspaceId): Promise<DocumentInfo[]> {
  const [data, items] = await Promise.all([call<any>('/sources'), wsReady(ws) ? workspaceItems(ws!) : Promise.resolve(null)]);
  const allow = items ? new Set(items.source_ids) : null;
  data.sources = (data.sources || []).filter((s: any) => !allow || allow.has(s.source_id));
  return (data.sources || []).map((s: any) => ({
    id: s.source_id, source_file: s.source_name, chunks_count: s.chunk_count, file_type: (s.source_name.split('.').pop() || '').toLowerCase(),
    domain_tags: [], status: String(s.status || '').toLowerCase() === 'failed' ? 'failed' : 'indexed',
  })) as unknown as DocumentInfo[];
}

export async function getDocumentChunks(docId: number | string): Promise<ChunkInfo[]> {
  const data = await call<any>(`/sources/${encodeURIComponent(String(docId))}`);
  return (data.chunks || []).map((c: any, i: number) => ({
    id: c.chunk_id, document_id: docId, chunk_index: c.index ?? i, qdrant_point_id: c.chunk_id, content: c.text,
    token_count: null, domain_tag: '',
  })) as unknown as ChunkInfo[];
}

export async function uploadDocument(file: File, ws?: WorkspaceId): Promise<{ filename: string; chunks_created: number; status: string; message: string; source_id?: string }> {
  const form = new FormData();
  form.append('file', file);
  const data = await call<any>('/sources/file', { method: 'POST', body: form });
  if (data.source_id) await assignToWorkspace(ws ?? '', 'source', data.source_id);
  return { filename: file.name, chunks_created: data.chunks_added ?? 0, status: 'ok', message: '', source_id: data.source_id };
}

// Bộ tài liệu mẫu của một cổng thanh toán giả định (PayNhanh): đủ để chạy thử mọi chức năng phân tích và bộ câu hỏi mẫu.
const SAMPLES = ['01_Dac_ta_yeu_cau_PayNhanh.md', '02_Thiet_ke_CSDL_PayNhanh.md', '03_Dac_ta_API_PayNhanh.md', '04_Chinh_sach_bao_mat_PayNhanh.md',
  '05_Quy_trinh_xu_ly_su_co_PayNhanh.md', '06_Kien_truc_va_trien_khai_PayNhanh.md', '07_So_tay_ky_su_moi_PayNhanh.md'];
export async function seedSampleDocs(ws?: WorkspaceId): Promise<{ status: string; message: string }> {
  for (const name of SAMPLES) {
    const text = await fetch(`/samples/${name}`).then(r => { if (!r.ok) throw new Error(`Thiếu tài liệu mẫu ${name}`); return r.text(); });
    const r = await post<any>('/sources/text', { source_name: name, text });
    if (r.source_id) await assignToWorkspace(ws ?? '', 'source', r.source_id);
  }
  return { status: 'ok', message: `Đã nạp ${SAMPLES.length} tài liệu mẫu.` };
}

export async function deleteDocument(docId: number | string): Promise<{ status: string; message: string }> {
  const r = await call<any>(`/studio/sources/${encodeURIComponent(String(docId))}`, { method: 'DELETE' });
  return { status: 'ok', message: `Đã xóa tài liệu và ${r.chunks_removed} đoạn.` };
}
export async function clearDocuments(ws?: WorkspaceId): Promise<{ status: string; message: string }> {
  const docs = await getDocuments(ws);
  for (const d of docs) await deleteDocument(d.id as unknown as string);
  return { status: 'ok', message: `Đã xóa ${docs.length} tài liệu.` };
}

const AGENT_DOMAIN: Record<string, string> = { DatabaseAgent: 'database', APIAgent: 'api_architecture', SecurityAgent: 'security' };
const DOMAIN_TAG: Record<string, string> = { database: 'CSDL', api_architecture: 'API', security: 'Bảo mật' };
export async function testRetrieval(req: RetrievalTestRequest): Promise<RetrievalTestResponse> {
  const scope = wsReady(req.workspace_id) ? (await workspaceItems(req.workspace_id!)).source_ids : undefined;
  const data = await post<any>('/studio/retrieval-test', { query: req.query, top_k: req.top_k, source_ids: scope, domain: req.domain_tag ? AGENT_DOMAIN[req.domain_tag] : undefined });
  return {
    query: data.query, top_k: data.top_k, domain_filter: req.domain_tag ?? null, latency_ms: data.latency_ms, total_indexed_chunks: data.total_chunks,
    results: data.results.map((h: any) => ({
      chunk_id: h.chunk_id, score: h.score, similarity_percentage: Math.round(h.score * 1000) / 10, text: h.text,
      source_file: h.source_name, file_type: (h.source_name.split('.').pop() || '').toLowerCase(), domain_tags: (h.domains || []).map((d: string) => DOMAIN_TAG[d] ?? d),
    })),
  };
}

// ---------------- Lịch sử, nhật ký
export async function getTelemetry(_ws?: WorkspaceId): Promise<TelemetryRecord[]> {
  // Danh sách lượt chạy đã kèm số đo; chỉ gọi chi tiết cho bản ghi cũ thiếu số đo.
  const list = await call<any[]>('/runs');
  const details = await Promise.all(list.map(r => r.metrics ? r : call<Cap1Run>(`/runs/${encodeURIComponent(r.run_id)}`).catch(() => null)));
  return list.map((r, i) => {
    const m = details[i]?.metrics || {};
    return {
      id: r.run_id, created_at: r.created_at, project_name: 'CAP1', user_query: r.query || '',
      execution_mode: r.condition, status: r.status,
      latency_ms: m.latency_ms ?? null, total_tokens: m.input_tokens != null ? m.input_tokens + (m.output_tokens || 0) : null,
      tokens_saved: null, token_saving_ratio: null, cpu_percent: m.cpu_percent ?? null, ram_usage_mb: m.peak_rss_mb ?? null, ram_delta_mb: null,
      task_coverage: null, retrieved_chunks_count: m.retrieved_chunks ?? 0, record_source: 'cap1_run', measurement_status: r.status,
    } as unknown as TelemetryRecord;
  });
}

export async function getRunDetail(runId: number | string): Promise<RunDetail> {
  const run = await call<Cap1Run>(`/runs/${encodeURIComponent(String(runId))}`);
  return { id: run.run_id, created_at: run.created_at, user_query: run.query, execution_mode: run.condition, result: adaptRun(run) } as unknown as RunDetail;
}

export async function getHealth(_ws?: WorkspaceId): Promise<HealthResponse> {
  const [h, model, src] = await Promise.all([
    call<any>('/health'), call<any>('/local-model/health').catch(() => ({ ok: false })), call<any>('/sources').catch(() => ({ sources: [] })),
  ]);
  return {
    status: h.ok ? 'ok' : 'error', database_type: h.storage_backend === 'postgres' ? 'PostgreSQL' : h.storage_backend,
    qdrant_status: '', qdrant_mode: '', indexed_documents_count: src.sources.length,
    total_chunks_count: src.sources.reduce((n: number, s: any) => n + (s.chunk_count || 0), 0),
    ollama_status: model.ok ? 'CONNECTED' : 'OFFLINE', ollama_model: model.configured_model || '',
    cpu_usage_percent: null as unknown as number, memory_usage_mb: null as unknown as number,
  };
}

// ---------------- Quản trị (chỉ ADMIN)
const TABLE_INFO: Record<string, [string, string]> = {
  users: ['Người dùng', 'Tài khoản và vai trò (không hiện mật khẩu)'],
  sessions: ['Phiên đăng nhập', 'Phiên cookie (không hiện token)'],
  knowledge_sources: ['Tài liệu', 'Nguồn tri thức của từng người'],
  knowledge_chunks: ['Phân đoạn', 'Mẩu tài liệu đã cắt'],
  conversations: ['Cuộc trò chuyện', 'Hội thoại nhiều lượt'],
  conversation_messages: ['Tin nhắn', 'Tin nhắn trong hội thoại'],
  runs: ['Lượt chạy', 'Kết quả và vết từng lượt điều phối'],
};

export async function getDatabaseOverview(): Promise<DatabaseOverviewResponse> {
  const data = await call<any>('/studio/admin/overview');
  return {
    database_type: 'PostgreSQL', qdrant_status: '', qdrant_points: 0,
    tables: data.tables.map((t: any) => ({ table_name: t.name, display_name: TABLE_INFO[t.name]?.[0] ?? t.name, row_count: t.row_count, description: TABLE_INFO[t.name]?.[1] ?? '' })),
  };
}

export async function getTableData(tableName: string, limit = 50, offset = 0, search = ''): Promise<TableDataResponse> {
  const data = await call<any>(`/studio/admin/table/${encodeURIComponent(tableName)}?limit=${limit}&offset=${offset}&q=${encodeURIComponent(search.trim())}`);
  return { table_name: data.name, columns: data.columns, rows: data.rows, total_count: data.total };
}

export async function getSecurityAudit(): Promise<SecurityAuditResponse> {
  const d = await call<any>('/studio/admin/security-audit');
  const c = d.checks;
  const item = (code: string, name: string, ok: boolean | null, details: string) => ({ code, name, status: ok == null ? 'CHƯA RÕ' : ok ? 'ĐẠT' : 'CẦN XEM', details, compliant: ok === true });
  return {
    project_name: 'CAP1 + C1SE.27', on_premise_compliance: false, air_gap_ready: false, network_egress_status: 'CHƯA KIỂM CHỨNG',
    audit_score: d.status, database_type: 'PostgreSQL', vector_db_mode: c.vector_index, llm_endpoint: c.llm_endpoint_loopback ? 'cục bộ (loopback)' : 'không phải loopback',
    rbac_active_roles: ['USER', 'ADMIN'], jwt_algorithm: 'Cookie phiên', security_headers_enforced: false,
    checkpoints: [
      item('LLM', 'Bộ não AI chạy trong máy', c.llm_endpoint_loopback, `Nhà cung cấp: ${c.provider}`),
      item('DB', 'Cơ sở dữ liệu trong máy', c.database_host_loopback, 'PostgreSQL'),
      item('VEC', 'Chỉ mục vector cục bộ', c.vector_index === 'qdrant' || c.vector_index === 'memory', `Chế độ: ${c.vector_index}`),
      item('EGRESS', 'Chặn kết nối ra ngoài', null, d.note),
    ],
    audit_timestamp: d.checked_at,
  };
}

export async function getDbDiagnostic(): Promise<DbDiagnosticResponse> {
  const [d, o] = await Promise.all([call<any>('/studio/admin/db-diagnostic'), call<any>('/studio/admin/overview')]);
  return {
    active_engine: 'PostgreSQL', database_url_redacted: '(ẩn)', dialect: `postgresql · alembic ${d.alembic_version}`, foreign_keys_enabled: true,
    tables_count: o.tables.length,
    tables: o.tables.map((t: any) => ({ table_name: t.name, record_count: t.row_count,
      foreign_keys_intact: !(t.name === 'knowledge_chunks' && d.orphan_chunks) && !(t.name === 'conversation_messages' && d.orphan_messages),
      schema_valid: !d.tables_missing.includes(t.name) })),
    pool_status: {},
  };
}

export async function simulateLLMContention(..._args: unknown[]): Promise<LLMContentionSimulateResponse> { throw new Error(NOT_SUPPORTED); }

// ---------------- Trò chuyện nhiều lượt (cuộc trò chuyện của CAP1, chế độ sản phẩm giống giao diện chat gốc)
export interface Conversation { conversation_id: string; title: string; created_at: string; updated_at: string }
export interface ConversationMessage { message_id: string; role: 'USER' | 'ASSISTANT' | string; content: string; created_at: string; run_id: string | null }

export async function listConversations(ws?: WorkspaceId): Promise<Conversation[]> {
  const [all, items] = await Promise.all([call<Conversation[]>('/conversations'), wsReady(ws) ? workspaceItems(ws!) : Promise.resolve(null)]);
  if (!items) return all;
  const allow = new Set(items.conversation_ids);
  return all.filter(c => allow.has(c.conversation_id));
}
export const getConversation = (id: string) => call<Conversation & { messages: ConversationMessage[] }>(`/conversations/${encodeURIComponent(id)}`);
export const getRawRun = (id: string) => call<Cap1Run>(`/runs/${encodeURIComponent(id)}`);
export const getChunk = (id: string) => call<{ chunk_id: string; source_name: string; text: string }>(`/chunks/${encodeURIComponent(id)}`);

// Mỗi câu hỏi chỉ dùng tài liệu của không gian đang mở; cuộc trò chuyện mới được gán vào không gian đó.
// only: chỉ hỏi trong các tài liệu này (ví dụ từ Hồ sơ tài liệu → Hỏi ngay), thay cho phạm vi của không gian.
async function chatInWorkspace(body: Record<string, unknown>, ws?: WorkspaceId, conversationId?: string | null, only?: string[]): Promise<Cap1Run> {
  const scope = only?.length ? only : wsReady(ws) ? (await workspaceItems(ws!)).source_ids : undefined;
  const run = await post<Cap1Run>('/chat', { ...body, conversation_id: conversationId ?? undefined, source_ids: scope });
  if (run.conversation_id && run.conversation_id !== conversationId) await assignToWorkspace(ws ?? '', 'conversation', run.conversation_id);
  return run;
}
export async function sendChat(message: string, conversationId: string | null, ws?: WorkspaceId, only?: string[]): Promise<Cap1Run> {
  return chatInWorkspace({ message, product_mode: true }, ws, conversationId, only);
}

// Phân tích sâu trong cùng cuộc trò chuyện (điều kiện A/B/C, không dùng chế độ sản phẩm).
export async function sendAnalysis(message: string, condition: string, conversationId: string | null, ws?: WorkspaceId, only?: string[]): Promise<Cap1Run> {
  return chatInWorkspace({ message, condition, reply_in_query_language: true }, ws, conversationId, only);
}

// ---------------- Truy vết yêu cầu (module phân tích, tách khỏi điều kiện A/B/C)
export type TraceStatus = 'COVERED' | 'PARTIAL' | 'MISSING';
export interface TraceRequirement { req_id: string; title: string; body: string; domains: string[]; agent: string; agent_name: string; group?: string }
export interface TraceResult {
  req_id: string; status: TraceStatus | 'ERROR'; agent: string; agent_name: string; citations: string[];
  evidence: { chunk_id: string; source_name: string; score: number }[];
  covered_points: string[]; missing_points: string[]; note: string; flags: string[];
  input_tokens: number; output_tokens: number; latency_ms: number;
}
export interface SavedReport { report_id: string; workspace_id: string | null; kind: string; title: string; created_at: string; payload?: any }

export const extractRequirements = (sourceId: string) =>
  post<{ source_id: string; source_name: string; requirements: TraceRequirement[] }>('/studio/traceability/extract', { source_id: sourceId });
export const checkRequirement = (r: TraceRequirement, sourceIds: string[], agent?: string) =>
  post<TraceResult>('/studio/traceability/check', { requirement: { req_id: r.req_id, title: r.title, body: r.body }, source_ids: sourceIds, agent });
export const getSecurityControls = () => call<{ standard: string; controls: TraceRequirement[] }>('/studio/security/controls');
export const listReports = (kind: string) => call<SavedReport[]>(`/studio/reports?kind=${encodeURIComponent(kind)}`);
export const getReport = (id: string) => call<SavedReport>(`/studio/reports/${encodeURIComponent(id)}`);
export const saveReport = (body: { kind: string; title: string; workspace_id?: string | null; payload: unknown }) => post<{ report_id: string }>('/studio/reports', body);
export const deleteReport = (id: string) => call<{ deleted: string }>(`/studio/reports/${encodeURIComponent(id)}`, { method: 'DELETE' });

// ---------------- Gói thiết kế kỹ thuật
export type DesignDomain = 'database' | 'api_architecture' | 'security';
export interface DesignPoint { id: string; text: string; domain: DesignDomain }
export interface Measured { input_tokens: number; output_tokens: number; latency_ms: number }
export interface DesignSectionResult extends Measured {
  domain: DesignDomain; agent_name: string; section: any; flags: string[]; sql?: string; openapi?: string;
  evidence: { chunk_id: string; source_name: string }[]; shared_chunks: number;
}
export interface DesignCoverage { point_id: string; status: 'COVERED' | 'PARTIAL' | 'MISSING'; sections: DesignDomain[]; note: string; flags: string[] }

export const designPoints = (request: string) => post<{ points: DesignPoint[]; flags: string[] } & Measured>('/studio/design/points', { request });
export const designSection = (request: string, domain: DesignDomain, points: DesignPoint[], sourceIds: string[], avoid: string[]) =>
  post<DesignSectionResult>('/studio/design/section', { request, domain, points, source_ids: sourceIds, avoid_chunk_ids: avoid });
export const designCoverage = (request: string, points: DesignPoint[], sections: Record<string, any>) =>
  post<{ coverage: DesignCoverage[] } & Measured>('/studio/design/coverage', { request, points, sections });

// ---------------- Phòng đánh giá thực nghiệm
export interface EvalRunResult {
  run_id: string; condition: string; status: string; answer: string; key_point_hits: boolean[]; key_point_coverage: number | null;
  metrics: Record<string, number | null>; tasks: number; model: string; config_hash: string;
}
export interface Described { n: number; mean: number | null; sd: number | null; ci95: [number, number] | null }
export interface PairedComparison { a: string; b: string; pairs: number; mean_diff: number | null; cohens_dz: number | null;
  wilcoxon: { n: number; w_plus: number; w_minus: number; p_value: number | null; method: string; rank_biserial: number | null } }
export const evalRun = (question: string, condition: string, sourceIds: string[] | null, keyPoints: string[]) =>
  post<EvalRunResult>('/studio/eval/run', { question, condition, source_ids: sourceIds, key_points: keyPoints });
export const evalStats = (scores: Record<string, (number | null)[]>, pairs: [string, string][]) =>
  post<{ conditions: Record<string, Described>; comparisons: PairedComparison[] }>('/studio/eval/stats', { scores, pairs });
export const updateReport = (id: string, payload: unknown, title?: string) =>
  call<{ report_id: string }>(`/studio/reports/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ payload, title }) });

// ---------------- Kiểm tra mâu thuẫn giữa tài liệu
export interface ConsistencyStatement { sid: string; source_id: string; source_name: string; chunk_id: string; text: string }
export interface ConsistencyPair { pair_id: string; a: ConsistencyStatement; b: ConsistencyStatement; overlap: number; reason: 'numbers_differ' | 'negation_differs'; shared_terms: string[] }
export interface ConsistencyVerdict extends Measured { verdict: 'CONTRADICTION' | 'CONSISTENT' | 'UNRELATED'; severity: 'HIGH' | 'MEDIUM' | 'LOW'; value_a?: string; value_b?: string; explanation: string; flags: string[] }
export const consistencyCandidates = (sourceIds: string[], maxPairs = 15) =>
  post<{ statements: number; pairs: ConsistencyPair[] }>('/studio/consistency/candidates', { source_ids: sourceIds, max_pairs: maxPairs });
export const consistencyJudge = (a: ConsistencyStatement, b: ConsistencyStatement) =>
  post<ConsistencyVerdict>('/studio/consistency/judge', { a: { source_name: a.source_name, text: a.text }, b: { source_name: b.source_name, text: b.text } });

// ---------------- Đèn báo độ tin cậy, phản hồi
export type GroundLevel = 'supported' | 'weak' | 'unsupported';
export interface GroundingResult {
  sentences: { text: string; level: GroundLevel; score: number; missing_numbers: string[]; chunk_id: string | null; source_name: string | null }[];
  counts: Record<GroundLevel, number>; evidence_chunks: number;
}
export const groundRun = (runId: string) => post<GroundingResult>('/studio/grounding', { run_id: runId });
export type Rating = -1 | 0 | 1;
export const sendFeedback = (runId: string, rating: Rating, note = '') => post<{ run_id: string; rating: Rating }>('/studio/feedback', { run_id: runId, rating, note });
export const listFeedback = () => call<Record<string, { rating: Rating; note: string }>>('/studio/feedback');

// ---------------- Hồ sơ tài liệu
export interface QualityIssue { level: 'high' | 'medium' | 'low'; code: string; message: string }
export interface GlossaryTerm { term: string; definition: string; origin: 'document' | 'model'; count?: number; context?: string }
export interface ProfileLocal {
  source_id: string; source_name: string;
  quality: { words: number; chunks: number; headings: number; requirement_ids: number; long_chunks: number; issues: QualityIssue[]; score: number };
  pii: { findings: { type: string; label: string; masked: string; line: number }[]; counts: Record<string, number> };
  glossary_defined: GlossaryTerm[]; glossary_pending: number;
  related: { source_id: string; source_name: string; score: number; shared_terms: string[] }[];
}
export interface ProfileSummary extends Measured { summary: string; key_points: string[]; doc_type: string; chunks_read: number; chunks_total: number }
export interface SuggestedQuestion { question: string; chunk_id: string | null }
export const profileLocal = (sourceId: string) => post<ProfileLocal>('/studio/profile/local', { source_id: sourceId });
export const profileMasked = (sourceId: string) => post<{ source_name: string; masked_text: string }>('/studio/profile/masked', { source_id: sourceId });
export const profileSummary = (sourceId: string) => post<ProfileSummary>('/studio/profile/summary', { source_id: sourceId });
export const profileQuestions = (sourceId: string) => post<{ questions: SuggestedQuestion[] } & Measured>('/studio/profile/questions', { source_id: sourceId });
export const profileGlossary = (sourceId: string) => post<{ terms: GlossaryTerm[] } & Measured>('/studio/profile/glossary', { source_id: sourceId });

export interface DocChange { type: 'added' | 'removed' | 'changed_from' | 'changed_to'; text: string; section: string }
export interface DocCompare {
  changes: DocChange[]; truncated: boolean; similarity: number; added: number; removed: number; changed: number;
  old_name: string; new_name: string; summary: ({ summary: string } & Measured) | null;
}
export const compareDocs = (oldId: string, newId: string, summarize = true) =>
  post<DocCompare>('/studio/compare-docs', { old_source_id: oldId, new_source_id: newId, summarize });

// ---------------- Tổng quan và nhật ký hoạt động
export interface Overview {
  sources: number; chunks: number; runs: number; runs_by_condition: Record<string, number>; runs_by_status: Record<string, number>;
  tokens_total: number | null; tokens_avg: number | null; latency_avg_ms: number | null;
  feedback: { up: number; down: number }; reports: Record<string, number>;
  top_documents: { source_id: string; source_name: string; citations: number }[]; cite_window: number;
  unused_documents: { source_id: string; source_name: string }[];
  topics: { term: string; count: number; previous: number }[]; daily: { date: string; runs: number }[]; window_days: number;
  // các trường dưới đây có từ bản backend 2026-11-14; backend cũ không trả về (trang Tổng quan ẩn biểu đồ tương ứng)
  daily_status?: { date: string; COMPLETE: number; PARTIAL: number; NO_EVIDENCE: number; FAILED: number; OTHER: number }[];
  heatmap?: number[][];  // 7 ngày (thứ Hai = 0) x 24 giờ, giờ máy chủ
  by_condition?: { condition: string; runs: number; complete: number; latency_avg_ms: number | null; tokens_avg: number | null }[];
  latency_p50_ms?: number | null; latency_p95_ms?: number | null;
}
export interface ActivityRow { action: string; target: string; status: number; created_at: string }
export const getOverview = () => call<Overview>('/studio/overview');
export const getActivity = (limit = 100) => call<ActivityRow[]>(`/studio/activity?limit=${limit}`);
export const getActivityPage = (page: number, size = 15, q = '') =>
  call<{ rows: ActivityRow[]; total: number; page: number; size: number; pages: number }>(`/studio/activity/page?page=${page}&size=${size}&q=${encodeURIComponent(q)}`);

// ---------------- Sơ đồ tư duy, bôi đen để hỏi, báo cáo, xuất Word, kiểm tra kho, phản hồi cho quản trị
export interface MindNode { id: string; label: string; chunk_id?: string | null; kind?: string; children: MindNode[] }
export interface MindLink { from: string; to: string; label: string }
export interface MindMap extends Partial<Measured> {
  mode: 'outline' | 'ai'; root: MindNode; links: MindLink[]; nodes: number; source_id: string; source_name: string;
  chunks_read?: number; chunks_total?: number; created_at?: string;
}
export const buildMindmap = (sourceId: string, mode: 'outline' | 'ai') => post<MindMap>('/studio/mindmap', { source_id: sourceId, mode });
export const explainSelection = (sourceName: string, selection: string, context: string) =>
  post<{ explanation: string; example: string } & Measured>('/studio/explain', { source_name: sourceName, selection, context });
export const answerReport = (runId: string) => post<{ title: string; markdown: string } & Measured>('/studio/answer-report', { run_id: runId });
export async function exportDocx(markdown: string): Promise<Blob> {
  const res = await fetch(`${API}/studio/export/docx`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ markdown }) });
  if (!res.ok) throw new Error(`Không tạo được tệp Word (HTTP ${res.status})`);
  return res.blob();
}
export interface QualityIssue { level: 'high' | 'medium' | 'low'; code: string; message: string }
export interface LibraryQuality {
  documents: number; with_issues: number;
  duplicates: { a: string; b: string; a_id: string; b_id: string; score: number }[];
  docs: { source_id: string; source_name: string; score: number; words: number; chunks: number; issues: QualityIssue[] }[];
}
export interface RelatedDoc { source_id: string; source_name: string; score: number; shared_terms: string[] }
export const relatedDocs = (sourceId: string) => post<{ related: RelatedDoc[] }>('/studio/related', { source_id: sourceId });
export const libraryQuality = () => call<LibraryQuality>('/studio/library-quality');
export interface AdminFeedbackItem { run_id: string; rating: 1 | -1; note: string; created_at: string; user: string; query: string; answer: string; status: string; condition: string }
// ---------------- Chấm mù nhiều người
export interface RatingStudy { study_id: string; title: string; code: string; created_at: string; items: number; failed: number; ratings: number; raters: number }
export interface RatingItem { item_id: string; question: string; answer: string; key_points: string[] }
export interface RatingScore { key_points: boolean[]; correct: number; complete: number; grounded: number; useful: number; fabricated: boolean; note?: string }
export interface RatingResults {
  study_id: string; title: string; code: string; raters: string[]; items: number; rated_items: number; failed_runs: number;
  conditions: Record<string, { rated_items: number; failed_runs: number; kp_coverage: Described; overall: Described; fabricated_rate: number | null; correct: number | null; complete: number | null; grounded: number | null; useful: number | null }>;
  comparisons: Record<string, Omit<PairedComparison, 'a' | 'b'>>; agreement_alpha: Record<string, number | null>; auto_vs_human_agreement: number | null;
  ratings_per_rater: Record<string, number>; notes: { condition: string; note: string }[];
}
export const createRatingStudy = (title: string, items: { run_id: string; key_points: string[] }[]) =>
  post<{ study_id: string; code: string; items: number; failed_runs: number }>('/studio/rating/studies', { title, items });
export const listRatingStudies = () => call<RatingStudy[]>('/studio/rating/studies');
export const ratingResults = (id: string) => call<RatingResults>(`/studio/rating/studies/${encodeURIComponent(id)}/results`);
export const deleteRatingStudy = (id: string) => call<{ deleted: string }>(`/studio/rating/studies/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const joinRating = (code: string) => call<{ title: string; code: string; items: RatingItem[]; mine: Record<string, RatingScore> }>(`/studio/rating/join/${encodeURIComponent(code.trim().toUpperCase())}`);
export const saveRating = (code: string, itemId: string, score: RatingScore) =>
  call<{ saved: boolean }>(`/studio/rating/join/${encodeURIComponent(code)}/${encodeURIComponent(itemId)}`, { method: 'PUT', body: JSON.stringify(score) });
export const adminFeedback = () => call<{ up: number; down: number; items: AdminFeedbackItem[] }>('/studio/admin/feedback');

// ---- Quản lý người dùng (chỉ ADMIN) ----
export interface AdminUser {
  user_id: string; email: string | null; username: string | null; display_name: string; role: 'USER' | 'ADMIN';
  status: 'ACTIVE' | 'DISABLED'; created_at: string; last_login_at: string | null;
  active_sessions: number; source_count: number; run_count: number;
}
export const listAdminUsers = (q = '') => call<{ users: AdminUser[]; total: number; admins_active: number }>(`/admin/users?q=${encodeURIComponent(q)}`);
export const createAdminUser = (body: { email?: string; username?: string; display_name?: string; role: 'USER' | 'ADMIN'; password?: string }) =>
  post<{ user: AdminUser; temporary_password: string | null }>('/admin/users', body);
export const updateAdminUser = (id: string, body: { role?: 'USER' | 'ADMIN'; status?: 'ACTIVE' | 'DISABLED'; display_name?: string }) =>
  call<{ user: AdminUser }>(`/admin/users/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) });
export const resetAdminUserPassword = (id: string) => post<{ user: AdminUser; temporary_password: string }>(`/admin/users/${encodeURIComponent(id)}/reset-password`, {});
export const revokeAdminUserSessions = (id: string) => post<{ revoked: number }>(`/admin/users/${encodeURIComponent(id)}/revoke-sessions`, {});

// ---- Soát chất lượng yêu cầu (ISO/IEC/IEEE 29148) ----
export type ReqSeverity = 'error' | 'warning' | 'info';
export interface ReqIssue {
  rule: string; label: string; characteristic: string; characteristic_label: string; severity: ReqSeverity;
  evidence: string; message: string; suggestion: string; other?: string;
}
export interface ReqQualityRow { req_id: string; title: string; text: string; issues: ReqIssue[] }
export interface ReqQualityResult {
  source_id: string; source_name: string; standard: string;
  rules: { rule: string; label: string; characteristic: string; characteristic_label: string; severity: ReqSeverity }[];
  requirements: ReqQualityRow[];
  summary: { total: number; clean: number; with_issues: number; errors: number; warnings: number; infos: number;
    by_rule: Record<string, number>; by_characteristic: Record<string, number> };
}
export interface ReqRewrite extends Measured { req_id: string; obligations: string[]; rewrites: string[]; missing: string[]; remaining: string[]; open_questions: string[]; new_numbers: string[] }
export const reviewRequirements = (sourceId: string) => post<ReqQualityResult>('/studio/req-quality', { source_id: sourceId });
export const rewriteRequirement = (reqId: string, text: string, issues: string[]) =>
  post<ReqRewrite>('/studio/req-quality/rewrite', { req_id: reqId, text, issues });

// ---------------- Bảng điều khiển quản trị (Admin Portal): số đo thật của máy chủ, nhật ký kiểm toán mọi tài khoản
type N = number | null | undefined;
export interface AdminSystem {
  measured_at: string; provider: string; embedding_backend: string;
  host: { available: boolean; cpu_percent?: number; cpu_count?: number; ram_total_bytes?: number; ram_used_bytes?: number; ram_percent?: number;
    disk?: { total_bytes: number; used_bytes: number; free_bytes: number; percent: number } | null; boot_time?: string; backend_rss_bytes?: number;
    backend_uptime_s?: number; platform?: string; python?: string };
  ollama: { base_url?: string; chat_model?: string; embed_model?: string; reachable: boolean; error?: string; chat_model_ready: boolean | null; embed_model_ready: boolean | null;
    models: { name: string; size_bytes: N; family?: string | null; parameter_size?: string | null; quantization?: string | null }[];
    loaded: { name: string; size_bytes: N; vram_bytes: N; expires_at?: string }[] | null; process_rss_mb?: N; gpu_memory_mb?: N };
  postgres: { reachable: boolean; dialect?: string; size_bytes: N; version: string | null; connections: N; alembic_version?: string | null; error?: string; counts: Record<string, N> };
  qdrant: { path: string; exists: boolean; size_bytes: N; collections: string[]; backend: string };
}
export const getAdminSystem = () => call<AdminSystem>('/admin/system');
export interface AuditRow { action: string; target: string; status: number; created_at: string; email: string | null; display_name: string | null; role: string | null }
export const getAdminAudit = (page = 1, size = 20, q = '', errors = false) =>
  call<{ rows: AuditRow[]; total: number; page: number; size: number; pages: number }>(`/admin/audit?page=${page}&size=${size}&q=${encodeURIComponent(q)}${errors ? '&errors=true' : ''}`);
