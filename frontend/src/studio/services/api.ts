// Lớp gọi API của Studio, nối vào backend CAP1 (/api/*, phiên đăng nhập bằng cookie).
// Giữ tên hàm cũ để các màn hình Studio không phải đổi; chức năng CAP1 chưa có thì báo rõ, không giả lập.
import {
  AnalyzeResponse, ChunkInfo, DatabaseOverviewResponse, DbDiagnosticResponse, DocumentInfo, ExecutionMode,
  ExperimentConfig, HealthResponse, LLMContentionSimulateResponse, ModeExecutionResult, RetrievalTestRequest,
  RetrievalTestResponse, RunDetail, SecurityAuditResponse, TableDataResponse, TelemetryRecord, User, Workspace,
} from '../types';
import { adaptRun, Cap1Run, MODE_TO_CONDITION, modeOf } from './adapt';

const API = '/api';
// CAP1 không có "không gian làm việc": mỗi người có một kho riêng. Studio dùng một không gian ảo cố định.
export const VIRTUAL_WORKSPACE_ID = 1;
export const NOT_SUPPORTED = 'Chức năng này chưa có trong backend CAP1.';

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json', ...(init.headers || {}) } : init.headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === 'string' ? body.detail : Array.isArray(body?.detail) ? body.detail.map((d: any) => d.msg).join('; ') : '';
    throw new Error(detail || `Lỗi máy chủ (HTTP ${res.status})`);
  }
  return res.json();
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

// ---------------- Không gian làm việc (ảo)
export async function getWorkspaces(): Promise<Workspace[]> {
  return [{ id: VIRTUAL_WORKSPACE_ID, name: 'Kho tài liệu của tôi', created_at: '', documents_count: 0, runs_count: 0 }];
}
export async function createWorkspace(_name: string, _description: string): Promise<Workspace> {
  throw new Error(NOT_SUPPORTED);
}

// ---------------- Cấu hình: CAP1 cấu hình bằng biến môi trường, chỉ đọc (định danh bằng config_hash)
export async function getRuntimeConfig(): Promise<Record<string, any>> {
  return call('/config');
}
export async function getConfigs(): Promise<ExperimentConfig[]> { return []; }
export async function createConfig(_c: Partial<ExperimentConfig>): Promise<ExperimentConfig> { throw new Error(NOT_SUPPORTED); }
export async function toggleConfigLock(_id: number): Promise<ExperimentConfig> { throw new Error(NOT_SUPPORTED); }

// ---------------- Điều phối
export async function analyzeQuery(query: string, mode: ExecutionMode, _topK = 4, _ws?: number, _userId?: number | string): Promise<AnalyzeResponse> {
  const results: Record<string, ModeExecutionResult> = {};
  if (mode === 'ablation_comparison') {
    const data = await post<any>('/studio/compare', { message: query, conditions: ['A', 'B', 'C'] });
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
  return (await post<any>('/studio/compare', { message, conditions })).runs;
}

// ---------------- Kho tài liệu
export async function getDocuments(_ws?: number): Promise<DocumentInfo[]> {
  const data = await call<any>('/sources');
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

export async function uploadDocument(file: File, _ws?: number): Promise<{ filename: string; chunks_created: number; status: string; message: string }> {
  const form = new FormData();
  form.append('file', file);
  const data = await call<any>('/sources/file', { method: 'POST', body: form });
  return { filename: file.name, chunks_created: data.chunks_added ?? 0, status: 'ok', message: '' };
}

const SAMPLES = ['schema_e_commerce_ledger.sql', 'api_spec_payment_gateway.md', 'security_auth_policy.md'];
export async function seedSampleDocs(_ws?: number): Promise<{ status: string; message: string }> {
  for (const name of SAMPLES) {
    const text = await fetch(`/samples/${name}`).then(r => { if (!r.ok) throw new Error(`Thiếu tài liệu mẫu ${name}`); return r.text(); });
    await post('/sources/text', { source_name: name, text });
  }
  return { status: 'ok', message: `Đã nạp ${SAMPLES.length} tài liệu mẫu.` };
}

export async function deleteDocument(docId: number | string): Promise<{ status: string; message: string }> {
  const r = await call<any>(`/studio/sources/${encodeURIComponent(String(docId))}`, { method: 'DELETE' });
  return { status: 'ok', message: `Đã xóa tài liệu và ${r.chunks_removed} đoạn.` };
}
export async function clearDocuments(_ws?: number): Promise<{ status: string; message: string }> {
  const docs = await getDocuments();
  for (const d of docs) await deleteDocument(d.id as unknown as string);
  return { status: 'ok', message: `Đã xóa ${docs.length} tài liệu.` };
}

export async function testRetrieval(req: RetrievalTestRequest): Promise<RetrievalTestResponse> {
  const data = await post<any>('/studio/retrieval-test', { query: req.query, top_k: req.top_k });
  return {
    query: data.query, top_k: data.top_k, domain_filter: null, latency_ms: data.latency_ms, total_indexed_chunks: data.total_chunks,
    results: data.results.map((h: any) => ({
      chunk_id: h.chunk_id, score: h.score, similarity_percentage: Math.round(h.score * 1000) / 10, text: h.text,
      source_file: h.source_name, file_type: (h.source_name.split('.').pop() || '').toLowerCase(), domain_tags: [],
    })),
  };
}

// ---------------- Lịch sử, nhật ký
export async function getTelemetry(_ws?: number): Promise<TelemetryRecord[]> {
  const list = await call<any[]>('/runs');
  const details = await Promise.all(list.map(r => call<Cap1Run>(`/runs/${encodeURIComponent(r.run_id)}`).catch(() => null)));
  return list.map((r, i) => {
    const m = details[i]?.metrics || {};
    return {
      id: r.run_id, created_at: r.created_at, project_name: 'CAP1', user_query: r.query || '',
      execution_mode: r.condition, status: r.status,
      latency_ms: m.latency_ms ?? null, total_tokens: m.input_tokens != null ? m.input_tokens + (m.output_tokens || 0) : null,
      tokens_saved: null, token_saving_ratio: null, cpu_percent: null, ram_usage_mb: m.peak_rss_mb ?? null, ram_delta_mb: null,
      task_coverage: null, retrieved_chunks_count: m.retrieved_chunks ?? 0, record_source: 'cap1_run', measurement_status: r.status,
    } as unknown as TelemetryRecord;
  });
}

export async function getRunDetail(runId: number | string): Promise<RunDetail> {
  const run = await call<Cap1Run>(`/runs/${encodeURIComponent(String(runId))}`);
  return { id: run.run_id, created_at: run.created_at, user_query: run.query, execution_mode: run.condition, result: adaptRun(run) } as unknown as RunDetail;
}

export async function getHealth(_ws?: number): Promise<HealthResponse> {
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

export async function getTableData(tableName: string, limit = 50, offset = 0, _search?: string): Promise<TableDataResponse> {
  const data = await call<any>(`/studio/admin/table/${encodeURIComponent(tableName)}?limit=${limit}&offset=${offset}`);
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

export const listConversations = () => call<Conversation[]>('/conversations');
export const getConversation = (id: string) => call<Conversation & { messages: ConversationMessage[] }>(`/conversations/${encodeURIComponent(id)}`);
export const getRawRun = (id: string) => call<Cap1Run>(`/runs/${encodeURIComponent(id)}`);
export const getChunk = (id: string) => call<{ chunk_id: string; source_name: string; text: string }>(`/chunks/${encodeURIComponent(id)}`);

export async function sendChat(message: string, conversationId: string | null): Promise<Cap1Run> {
  return post<Cap1Run>('/chat', { message, conversation_id: conversationId ?? undefined, product_mode: true });
}

// Phân tích sâu trong cùng cuộc trò chuyện (điều kiện A/B/C, không dùng chế độ sản phẩm).
export async function sendAnalysis(message: string, condition: string, conversationId: string | null): Promise<Cap1Run> {
  return post<Cap1Run>('/chat', { message, condition, conversation_id: conversationId ?? undefined });
}
