// Lớp gọi API của Studio, nối vào backend CAP1 (/api/*, phiên đăng nhập bằng cookie).
// Giữ tên hàm cũ để các màn hình Studio không phải đổi; chức năng CAP1 chưa có thì báo rõ, không giả lập.
import {
  AnalyzeResponse, ChunkInfo, DatabaseOverviewResponse, DbDiagnosticResponse, DocumentInfo, ExecutionMode,
  ExperimentConfig, HealthResponse, LLMContentionSimulateResponse, ModeExecutionResult, RetrievalTestRequest,
  RetrievalTestResponse, RunDetail, SecurityAuditResponse, TableDataResponse, TelemetryRecord, User, Workspace,
} from '../types';
import { adaptRun, Cap1Run, MODE_TO_CONDITION, modeOf } from './adapt';

const API = '/api';
export const NOT_SUPPORTED = 'Chức năng này chưa có trong backend CAP1.';

// Phạm vi tổ chức: khi đang mở một không gian tổ chức (mã bắt đầu "sp_"), mọi yêu cầu tự gắn ?space_id=
// để backend chỉ trả tài liệu, lượt chạy, hội thoại người dùng được phép (luật nằm ở backend app/core/access.py).
let orgScope: string | null = null;
export const isOrgId = (ws?: number | string | null): ws is string => typeof ws === 'string' && ws.startsWith('sp_');
export function setOrgScope(ws?: number | string | null) { orgScope = isOrgId(ws) ? ws : null; }

// Lĩnh vực của không gian (bộ tác tử ở backend app/research/registry.py, giữ khớp danh sách PACKS).
// Câu hỏi gửi kèm lĩnh vực của không gian đang mở; trang Thực nghiệm không gửi nên vẫn chạy bộ Phần mềm như cũ.
export const DOMAIN_PACKS = [
  { id: 'general', label: 'Tổng quát', hint: 'Mọi loại tài liệu, một chuyên viên tổng hợp' },
  { id: 'education', label: 'Giáo dục', hint: 'Học vụ, công tác sinh viên, giảng viên – nghiên cứu' },
  { id: 'legal_admin', label: 'Hành chính – Pháp lý', hint: 'Căn cứ pháp lý, thủ tục hành chính, hợp đồng' },
  { id: 'business_hr', label: 'Doanh nghiệp – Nhân sự', hint: 'Chính sách nhân sự, quy trình nội bộ, khách hàng' },
  { id: 'software', label: 'Phần mềm', hint: 'Bảo mật, cơ sở dữ liệu, API – kiến trúc' },
] as const;
export type DomainPack = typeof DOMAIN_PACKS[number]['id'];
export const packLabel = (p?: string | null) => DOMAIN_PACKS.find(d => d.id === p)?.label ?? 'Phần mềm';
let domainPack: string | null = null;
export function setDomainPack(p?: string | null) { domainPack = p ?? null; }
// Không gắn phạm vi: đăng nhập, API tổ chức (tự mang mã không gian), thư mục cá nhân, và bước tải tệp
// (tệp vào kho cá nhân trước rồi mới được nộp vào tổ chức kèm mức mật).
const UNSCOPED = /^\/(auth|org)\/|^\/studio\/workspaces|^\/sources\/(file|text)$|^\/shared-folder/;  // thư mục chung luôn nạp vào kho cá nhân
function scoped(path: string): string {
  if (!orgScope || UNSCOPED.test(path)) return path;
  return `${path}${path.includes('?') ? '&' : '?'}space_id=${encodeURIComponent(orgScope)}`;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${scoped(path)}`, {
    credentials: 'same-origin',
    ...init,
    headers: init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json', ...(init.headers || {}) } : init.headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === 'string' ? body.detail : Array.isArray(body?.detail) ? body.detail.map((d: any) => d.msg).join('; ') : '';
    throw new Error(viError(detail) || `Lỗi máy chủ (HTTP ${res.status})`);
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
  UNSUPPORTED_DOCUMENT_TYPE: 'Định dạng chưa hỗ trợ. Dùng PDF, Word (.docx), Excel (.xlsx), Markdown, TXT hoặc SQL.',
  OFFICE_EXTRACTION_FAILED: 'Không đọc được tệp Word/Excel này (tệp hỏng, trống hoặc quá lớn khi giải nén). Bản .doc/.xls cũ cần lưu lại thành .docx/.xlsx.',
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
  if (min) return `Mật khẩu cần ít nhất ${min[1]} ký tự.`;
  // OCR (đợt 10): ảnh chụp, PDF scan cần Tesseract có gói tiếng Việt trên máy chủ
  if (detail.startsWith('OCR_UNAVAILABLE')) return `Chưa nhận dạng được chữ trong ảnh/bản scan: ${detail.split(': ').slice(1).join(': ')} Quản trị cần cài Tesseract OCR kèm gói tiếng Việt.`;
  if (detail.startsWith('OCR_FAILED')) return 'Nhận dạng chữ không thành công. Thử ảnh rõ nét hơn hoặc bản scan có độ phân giải cao hơn.';
  if (detail === 'OCR_NO_TEXT') return 'Không nhận dạng được chữ nào trong ảnh/bản scan.';
  return VI_ERRORS[detail] ?? detail;
}
const post = <T>(path: string, body: unknown) => call<T>(path, { method: 'POST', body: JSON.stringify(body) });

// ---------------- Đăng nhập (cookie phiên của CAP1)
function toUser(u: any): User {
  return {
    id: u.user_id, username: u.username || u.email || '', email: u.email || '',
    full_name: u.display_name || u.username || u.email || 'Người dùng',
    role: String(u.role || '').toUpperCase() === 'ADMIN' ? 'admin' : 'developer',
    created_at: u.created_at || '',
    avatar: u.avatar ?? null,
  } as unknown as User;
}

/** Tự đổi ảnh đại diện: "preset:<mã>", data URL ảnh 256px, hoặc null để bỏ ảnh. */
export async function setAvatar(avatar: string | null): Promise<User> {
  const data = await call<any>('/auth/avatar', { method: 'PUT', body: JSON.stringify({ avatar }) });
  return toUser(data.user);
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
  const [rows, spaces] = await Promise.all([call<any[]>('/studio/workspaces'), listMySpaces().catch(() => [] as OrgSpace[])]);
  const personal: Workspace[] = rows.map(w => ({ id: w.workspace_id, name: w.name, description: w.description, created_at: w.created_at,
    documents_count: w.source_count, runs_count: w.conversation_count, kind: 'personal', domain_pack: w.domain_pack }));
  // không gian tổ chức đã được duyệt đứng sau các thư mục cá nhân trong ô chọn không gian
  return [...personal, ...spaces.filter(s => s.status === 'ACTIVE').map(s => ({
    id: s.space_id, name: s.name, description: s.description, created_at: '', documents_count: 0, runs_count: 0,
    kind: 'org' as const, level: s.level, is_owner: s.is_owner, preset: s.preset, labels: s.labels, unit_count: s.unit_count,
    domain_pack: s.domain_pack,
  }))];
}
export async function createWorkspace(name: string, description: string, domain_pack: DomainPack = 'general'): Promise<Workspace> {
  const w = await post<any>('/studio/workspaces', { name, description, domain_pack });
  return { id: w.workspace_id, name: w.name, description: w.description, created_at: '', documents_count: 0, runs_count: 0, kind: 'personal', domain_pack: w.domain_pack };
}
export async function renameWorkspace(id: WorkspaceId, name: string, description = '', domain_pack?: DomainPack): Promise<void> {
  await call(`/studio/workspaces/${encodeURIComponent(String(id))}`, { method: 'PATCH', body: JSON.stringify({ name, description, domain_pack }) });
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
  if (isOrgId(ws)) {
    const rows = await call<OrgSource[]>(`/org/spaces/${encodeURIComponent(ws)}/sources`);
    return rows.map(s => ({
      id: s.source_id, source_file: s.source_name, chunks_count: s.chunk_count, file_type: (s.source_name.split('.').pop() || '').toLowerCase(),
      domain_tags: [], status: String(s.status || '').toLowerCase() === 'failed' ? 'failed' : 'indexed',
      classification: s.classification, department_id: s.department_id, owner: s.owner, mine: s.mine, can_delete: s.can_delete,
      created_at: s.created_at ?? undefined, doc_type: s.doc_type ?? null,
    })) as unknown as DocumentInfo[];
  }
  const [data, items] = await Promise.all([call<any>('/sources'), wsReady(ws) ? workspaceItems(ws!) : Promise.resolve(null)]);
  const allow = items ? new Set(items.source_ids) : null;
  data.sources = (data.sources || []).filter((s: any) => !allow || allow.has(s.source_id));
  return (data.sources || []).map((s: any) => ({
    id: s.source_id, source_file: s.source_name, chunks_count: s.chunk_count, file_type: (s.source_name.split('.').pop() || '').toLowerCase(),
    domain_tags: [], status: String(s.status || '').toLowerCase() === 'failed' ? 'failed' : 'indexed', doc_type: s.doc_type ?? null,
  })) as unknown as DocumentInfo[];
}

// Loại tài liệu hệ thống tự nhận khi tải lên (backend ingestion/doc_type.py); người tải lên sửa được.
export const DOC_TYPES: Record<string, string> = {
  contract: 'Hợp đồng', regulation: 'Quy chế', internal_rules: 'Nội quy', transcript: 'Bảng điểm',
  legal_doc: 'Văn bản pháp quy', software_spec: 'Đặc tả phần mềm', lecture: 'Bài giảng', other: 'Khác',
};
export const setDocType = (sourceId: string, docType: string) =>
  call<{ source_id: string; doc_type: string }>(`/sources/${encodeURIComponent(sourceId)}/doc-type`, { method: 'PUT', body: JSON.stringify({ doc_type: docType }) });

export async function getDocumentChunks(docId: number | string): Promise<ChunkInfo[]> {
  const data = await call<any>(`/sources/${encodeURIComponent(String(docId))}`);
  return (data.chunks || []).map((c: any, i: number) => ({
    id: c.chunk_id, document_id: docId, chunk_index: c.index ?? i, qdrant_point_id: c.chunk_id, content: c.text,
    token_count: null, domain_tag: '',
  })) as unknown as ChunkInfo[];
}

export async function uploadDocument(file: File, ws?: WorkspaceId, publish?: { classification: Classification; department_id?: string | null }): Promise<{ filename: string; chunks_created: number; status: string; message: string; source_id?: string }> {
  const form = new FormData();
  form.append('file', file);
  const data = await call<any>('/sources/file', { method: 'POST', body: form });
  // trong không gian tổ chức: nộp ngay với mức mật đã chọn trước khi tải (tài liệu Mật không lộ dù một khoảnh khắc)
  if (data.source_id && isOrgId(ws)) await publishSource(ws, data.source_id, publish ?? { classification: 'DEPARTMENT' });
  else if (data.source_id) await assignToWorkspace(ws ?? '', 'source', data.source_id);
  return { filename: file.name, chunks_created: data.chunks_added ?? 0, status: 'ok', message: '', source_id: data.source_id };
}

// Bộ tài liệu mẫu của một cổng thanh toán giả định (PayNhanh): đủ để chạy thử mọi chức năng phân tích và bộ câu hỏi mẫu.
const SAMPLES = ['01_Dac_ta_yeu_cau_PayNhanh.md', '02_Thiet_ke_CSDL_PayNhanh.md', '03_Dac_ta_API_PayNhanh.md', '04_Chinh_sach_bao_mat_PayNhanh.md',
  '05_Quy_trinh_xu_ly_su_co_PayNhanh.md', '06_Kien_truc_va_trien_khai_PayNhanh.md', '07_So_tay_ky_su_moi_PayNhanh.md'];
export async function seedSampleDocs(ws?: WorkspaceId): Promise<{ status: string; message: string }> {
  if (isOrgId(ws)) throw new Error('Bộ tài liệu mẫu chỉ nạp vào không gian cá nhân. Tài liệu tổ chức cần chọn mức mật khi tải lên.');
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
export interface Conversation { conversation_id: string; title: string; created_at: string; updated_at: string; pinned?: boolean }
/** Đổi tên, ghim, xóa (ẩn, hoàn tác bằng hidden: false) cuộc trò chuyện của chính mình. */
export const updateConversation = (id: string, patch: { title?: string; pinned?: boolean; hidden?: boolean }) =>
  call<Conversation & { hidden: boolean }>(`/conversations/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) });
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
async function chatInWorkspace(body: Record<string, unknown>, ws?: WorkspaceId, conversationId?: string | null, only?: string[], onEvent?: (e: ChatStreamEvent) => void): Promise<Cap1Run> {
  const scope = only?.length ? only : wsReady(ws) ? (await workspaceItems(ws!)).source_ids : undefined;
  // đợt 6: ô chat sản phẩm không gửi lĩnh vực (backend dùng tác tử theo loại việc); phân tích A/B/C chọn tay vẫn gửi
  const payload = { ...body, conversation_id: conversationId ?? undefined, source_ids: scope, domain_pack: body.product_mode ? undefined : domainPack ?? undefined };
  const run = onEvent ? await postStream(payload, onEvent) : await post<Cap1Run>('/chat', payload);
  if (run.conversation_id && run.conversation_id !== conversationId) await assignToWorkspace(ws ?? '', 'conversation', run.conversation_id);
  return run;
}
export async function sendChat(message: string, conversationId: string | null, ws?: WorkspaceId, only?: string[], onEvent?: (e: ChatStreamEvent) => void, agent?: string): Promise<Cap1Run> {
  return chatInWorkspace({ message, product_mode: true, agent }, ws, conversationId, only, onEvent);
}

// Ô chat sản phẩm: /api/chat/stream gửi từng dòng JSON (bước đang làm, chữ trả lời đang viết) rồi kết quả cuối.
export type ChatStreamEvent = { type: 'progress'; stage: string; task_id?: string; classification?: string; agents?: string[] } | { type: 'answer'; text: string } | { type: 'queue'; position: number };
async function postStream(payload: Record<string, unknown>, onEvent: (e: ChatStreamEvent) => void): Promise<Cap1Run> {
  const res = await fetch(`${API}${scoped('/chat/stream')}`, {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  if (res.status === 404) return post<Cap1Run>('/chat', payload); // backend cũ chưa có stream
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    throw new Error(viError(typeof body?.detail === 'string' ? body.detail : '') || `Lỗi máy chủ (HTTP ${res.status})`);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buf += value;
    let nl: number;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
      if (!line) continue;
      const item = JSON.parse(line);
      if (item.type === 'done') return item.run as Cap1Run;
      if (item.type === 'error') throw new Error(viError(typeof item.detail === 'string' ? item.detail : '') || `Lỗi máy chủ (HTTP ${item.status})`);
      onEvent(item);
    }
    if (done) throw new Error('Kết nối bị ngắt trước khi có câu trả lời. Câu hỏi vẫn được giữ, bạn thử gửi lại nhé.');
  }
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
export interface SavedReport { report_id: string; workspace_id: string | null; kind: string; title: string; created_at: string; updated_at?: string; payload?: any }

/** coded: yêu cầu có mã FR-/NFR-…; list: dòng gạch đầu dòng/đánh số của một tài liệu danh mục. */
export const extractRequirements = (sourceId: string, mode: 'coded' | 'list' = 'coded') =>
  post<{ source_id: string; source_name: string; requirements: TraceRequirement[] }>('/studio/traceability/extract', { source_id: sourceId, mode, domain_pack: domainPack ?? undefined });
export const checkRequirement = (r: TraceRequirement, sourceIds: string[], agent?: string) =>
  post<TraceResult>('/studio/traceability/check', { requirement: { req_id: r.req_id, title: r.title, body: r.body }, source_ids: sourceIds, agent, domain_pack: domainPack ?? undefined });

// ---------------- Công cụ nghiệp vụ theo ngành (backend analysis/casework.py): kết luận tổng do luật cố định suy ra
export type ConditionVerdict = 'MET' | 'NOT_MET' | 'UNKNOWN';
export type ConditionOverall = 'ELIGIBLE' | 'NOT_ELIGIBLE' | 'INSUFFICIENT_INFO' | 'NO_RULE' | 'UNRESOLVED';
type Evidence = { chunk_id: string; source_name: string; score: number };
export interface ConditionResult {
  overall: ConditionOverall; agent: string; agent_name: string; evidence: Evidence[]; removed: number; note: string;
  conditions: { condition: string; citation: string; case_fact: string; verdict: ConditionVerdict; reason: string; flags: string[] }[];
  input_tokens: number; output_tokens: number; latency_ms: number;
}
export interface ProcedureResult {
  agent: string; agent_name: string; evidence: Evidence[]; removed: number; note: string;
  steps: { order: number; action: string; actor: string; deadline: string; outputs: string; citation: string; flags: string[] }[];
  documents: { name: string; citation: string }[];
  fees: { text: string; citation: string }[];
  input_tokens: number; output_tokens: number; latency_ms: number;
}
export const checkConditions = (question: string, caseText: string, sourceIds: string[]) =>
  post<ConditionResult>('/studio/casework/conditions', { question, case: caseText, source_ids: sourceIds, domain_pack: domainPack ?? undefined });
export const extractProcedure = (topic: string, sourceIds: string[]) =>
  post<ProcedureResult>('/studio/casework/procedure', { topic, source_ids: sourceIds, domain_pack: domainPack ?? undefined });
export const getSecurityControls = () => call<{ standard: string; controls: TraceRequirement[] }>('/studio/security/controls');
export const listReports = (kind: string) => call<SavedReport[]>(`/studio/reports?kind=${encodeURIComponent(kind)}`);
export const listAllReports = () => call<SavedReport[]>('/studio/reports');
export const getReport = (id: string) => call<SavedReport>(`/studio/reports/${encodeURIComponent(id)}`);
// Báo cáo đã lưu là của cá nhân: trong không gian tổ chức backend không lưu (tránh giữ nội dung tổ chức sau khi rời đi).
export const canSaveReports = () => !orgScope;
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
  post<ConsistencyVerdict>('/studio/consistency/judge', { a: { source_name: a.source_name, text: a.text, source_id: a.source_id }, b: { source_name: b.source_name, text: b.text, source_id: b.source_id } });

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
export async function exportDocx(markdown: string, template?: { org: string; place: string; kind: string; title: string; signer: string }): Promise<Blob> {
  const res = await fetch(`${API}${scoped('/studio/export/docx')}`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ markdown, template }) });
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

// ---------------- Không gian tổ chức (/api/org): phòng ban, thành viên, lời mời, tài liệu tổ chức, thông báo
export type Classification = 'PRIVATE' | 'COMPANY' | 'DEPARTMENT' | 'RESTRICTED' | 'SECRET';
export type MemberLevel = 'STAFF' | 'MANAGER' | 'EXECUTIVE';
export type OrgPreset = 'business' | 'school' | 'hospital' | 'government' | 'team' | 'custom';
/** tên gọi tự đặt đè lên mẫu; chỉ để hiển thị, quyền do backend quyết định theo cấp STAFF/MANAGER/EXECUTIVE */
export interface OrgLabels { org?: string; unit?: string; STAFF?: string; MANAGER?: string; EXECUTIVE?: string }
interface OrgNaming { preset?: OrgPreset | string | null; labels?: OrgLabels | null; unit_count?: number; departments?: unknown[]; domain_pack?: string }
export interface OrgSpace extends OrgNaming { space_id: string; name: string; description: string; member_count?: number | null; members_preview?: { user_id: string; display_name: string; avatar?: string | null }[]; doc_count?: number | null; level: MemberLevel; department_id: string | null; is_owner: boolean; status: 'ACTIVE' | 'PENDING' }
export interface OrgDepartment { department_id: string; name: string }
export interface OrgMember { user_id: string; display_name: string; email: string | null; avatar?: string | null; department_id: string | null; level: MemberLevel; is_owner: boolean; status: 'ACTIVE' | 'PENDING'; joined_at: string | null }
export interface OrgDetail extends OrgNaming { space_id: string; name: string; description: string; me: { level: MemberLevel; department_id: string | null; is_owner: boolean }; departments: OrgDepartment[]; members: OrgMember[] }
export interface OrgInvite { invite_id: string; kind: 'USER' | 'LINK' | 'CODE'; invitee: string | null; level: MemberLevel; department_id: string | null; expires_at: string | null; max_uses: number | null; use_count: number; revoked: boolean }
export interface MyInvite extends OrgNaming { invite_id: string; space_id: string; space_name: string; inviter: string; level: MemberLevel; department_id: string | null; expires_at: string | null }
export interface OrgSource { source_id: string; source_name: string; status: string; chunk_count: number; classification: Classification; department_id: string | null; owner: string; mine: boolean; can_delete: boolean; created_at: string | null; doc_type?: string | null }
export interface OrgShare { share_id: string; user_id: string | null; user: string | null; department_id: string | null; shared_by: string }
export interface OrgNotification { notification_id: string; kind: string; space_id: string | null; payload: Record<string, any>; read: boolean; created_at: string }

const enc = encodeURIComponent;
const send = <T>(method: string, path: string, body?: unknown) => call<T>(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export const listMySpaces = () => call<OrgSpace[]>('/org/spaces');
export const createSpace = (name: string, departments: string[], preset: OrgPreset = 'business', labels: OrgLabels | null = null, domain_pack?: DomainPack) =>
  post<{ space_id: string; name: string }>('/org/spaces', { name, departments, preset, labels, domain_pack });
export const updateSpace = (id: string, body: { name?: string; description?: string; preset?: OrgPreset; labels?: OrgLabels | null; domain_pack?: DomainPack }) =>
  send<{ preset: OrgPreset; labels: OrgLabels | null }>('PATCH', `/org/spaces/${enc(id)}`, body);
export const getSpace = (id: string) => call<OrgDetail>(`/org/spaces/${enc(id)}`);
export const createDepartment = (id: string, name: string) => post<OrgDepartment>(`/org/spaces/${enc(id)}/departments`, { name });
export const renameDepartment = (id: string, dep: string, name: string) => send<OrgDepartment>('PATCH', `/org/spaces/${enc(id)}/departments/${enc(dep)}`, { name });
export const deleteDepartment = (id: string, dep: string) => send(`DELETE`, `/org/spaces/${enc(id)}/departments/${enc(dep)}`);
export const updateMember = (id: string, user: string, body: { level: MemberLevel; department_id: string | null; is_owner: boolean }) =>
  send('PATCH', `/org/spaces/${enc(id)}/members/${enc(user)}`, body);
export const removeMember = (id: string, user: string) => send<{ handed_over_to: string | null; drafts: number }>('DELETE', `/org/spaces/${enc(id)}/members/${enc(user)}`);
export const deleteSpace = (id: string, confirm_name: string) =>
  send<{ deleted: string; sources_removed: number; members_removed: number }>('DELETE', `/org/spaces/${enc(id)}`, { confirm_name });
export const leaveSpace = (id: string) => send<{ handed_over_to: string | null; drafts: number }>('POST', `/org/spaces/${enc(id)}/leave`);
export const approveMember = (id: string, user: string, level: MemberLevel, department_id: string | null) =>
  post(`/org/spaces/${enc(id)}/members/${enc(user)}/approve`, { level, department_id });
export const inviteByEmail = (id: string, email: string, level: MemberLevel, department_id: string | null) =>
  post<{ invite_id: string }>(`/org/spaces/${enc(id)}/invites`, { kind: 'USER', email, level, department_id });
export const createJoinToken = (id: string, kind: 'LINK' | 'CODE', expires_days = 7, max_uses = 20) =>
  post<{ invite_id: string; token: string }>(`/org/spaces/${enc(id)}/invites`, { kind, expires_days, max_uses });
export const listInvites = (id: string) => call<OrgInvite[]>(`/org/spaces/${enc(id)}/invites`);
export const revokeInvite = (id: string, invite: string) => send('DELETE', `/org/spaces/${enc(id)}/invites/${enc(invite)}`);
export const myInvites = () => call<MyInvite[]>('/org/invites');
export const answerInvite = (invite: string, decision: 'accept' | 'decline') => post<{ space_id: string }>(`/org/invites/${enc(invite)}/${decision}`, {});
export const joinSpace = (token: string) => post<{ space_id: string; space_name: string; status: string }>('/org/join', { token });
export const publishSource = (id: string, source: string, body: { classification: Classification; department_id?: string | null }) =>
  post(`/org/spaces/${enc(id)}/sources/${enc(source)}/publish`, body);
export const updateSource = (id: string, source: string, body: { classification?: Classification; department_id?: string }) =>
  send('PATCH', `/org/spaces/${enc(id)}/sources/${enc(source)}`, body);
export const shareSource = (id: string, source: string, target: { user_id?: string; department_id?: string }) =>
  post<{ share_id: string }>(`/org/spaces/${enc(id)}/sources/${enc(source)}/shares`, target);
export const listShares = (id: string, source: string) => call<OrgShare[]>(`/org/spaces/${enc(id)}/sources/${enc(source)}/shares`);
export const unshare = (id: string, share: string) => send('DELETE', `/org/spaces/${enc(id)}/shares/${enc(share)}`);
export interface OrgAudience { counts: Partial<Record<Classification, number | null>>; total: number; unit_name: string | null }
export const getAudience = (id: string) => call<OrgAudience>(`/org/spaces/${enc(id)}/audience`);
export const getNotifications = () => call<{ unread: number; items: OrgNotification[] }>('/org/notifications');
export const markNotificationsRead = (ids: string[] | 'all') => post<{ marked: number }>('/org/notifications/read', ids === 'all' ? { all: true } : { ids });

// Mẫu tổ chức: cùng một luật quyền 3 cấp (thành viên / người đứng đầu đơn vị / lãnh đạo toàn tổ chức), chỉ khác tên gọi.
type Naming = Required<OrgLabels>;
const BUSINESS: Naming = { org: 'công ty', unit: 'phòng', STAFF: 'Nhân viên', MANAGER: 'Trưởng phòng', EXECUTIVE: 'Ban giám đốc' };
export const ORG_PRESETS: Record<OrgPreset, { name: string; labels: Naming }> = {
  business: { name: 'Doanh nghiệp', labels: BUSINESS },
  school: { name: 'Trường học', labels: { org: 'trường', unit: 'khoa', STAFF: 'Giảng viên', MANAGER: 'Trưởng khoa', EXECUTIVE: 'Ban giám hiệu' } },
  hospital: { name: 'Bệnh viện, phòng khám', labels: { org: 'bệnh viện', unit: 'khoa', STAFF: 'Nhân viên y tế', MANAGER: 'Trưởng khoa', EXECUTIVE: 'Ban giám đốc' } },
  government: { name: 'Cơ quan nhà nước', labels: { org: 'cơ quan', unit: 'phòng', STAFF: 'Chuyên viên', MANAGER: 'Trưởng phòng', EXECUTIVE: 'Lãnh đạo cơ quan' } },
  team: { name: 'Nhóm nhỏ, câu lạc bộ', labels: { org: 'nhóm', unit: 'tổ', STAFF: 'Thành viên', MANAGER: 'Tổ trưởng', EXECUTIVE: 'Trưởng nhóm' } },
  custom: { name: 'Tự đặt cách gọi', labels: BUSINESS },
};
export interface OrgTerms extends Naming { Unit: string; single: boolean; level: Record<MemberLevel, string>; cls: Record<Classification, string>; hint: Record<Classification, string> }
export function orgTerms(src?: OrgNaming | null): OrgTerms {
  const base = (ORG_PRESETS as Record<string, { labels: Naming }>)[src?.preset ?? ''] ?? ORG_PRESETS.business;
  const own = Object.fromEntries(Object.entries(src?.labels ?? {}).filter(([, v]) => typeof v === 'string' && v.trim()).map(([k, v]) => [k, (v as string).trim()]));
  // "Bộ môn" dùng giữa câu thành "bộ môn"; chữ viết tắt như "CLB" giữ nguyên
  const lower = (v: string) => /^\p{Lu}\p{Ll}/u.test(v) ? v.charAt(0).toLowerCase() + v.slice(1) : v;
  const merged: Naming = { ...base.labels, ...own };
  const l: Naming = { ...merged, org: lower(merged.org), unit: lower(merged.unit) };
  // chỉ một đơn vị: mọi thành viên (trừ cấp lãnh đạo chung) đều thuộc đơn vị đó nên "Nội bộ đơn vị" = "Toàn tổ chức"
  const single = (src?.departments?.length ?? src?.unit_count) === 1;
  return {
    ...l, single, Unit: l.unit.charAt(0).toUpperCase() + l.unit.slice(1),
    level: { STAFF: l.STAFF, MANAGER: l.MANAGER, EXECUTIVE: l.EXECUTIVE },
    cls: { PRIVATE: 'Riêng tư', COMPANY: `Toàn ${l.org}`, DEPARTMENT: single ? `Toàn ${l.org}` : `Nội bộ ${l.unit}`, RESTRICTED: 'Hạn chế', SECRET: 'Mật' },
    hint: {
      PRIVATE: 'Chỉ bạn xem (bản nháp)', COMPANY: 'Mọi thành viên', DEPARTMENT: single ? 'Mọi thành viên' : `Thành viên trong ${l.unit} và ${l.EXECUTIVE}`,
      RESTRICTED: single ? `${l.MANAGER} và ${l.EXECUTIVE}` : `${l.MANAGER} của ${l.unit} và ${l.EXECUTIVE}`, SECRET: `Chỉ ${l.EXECUTIVE}`,
    },
  };
}
/** Các mức mật hiện trong ô chọn. Chế độ một đơn vị: "Toàn tổ chức" và "Nội bộ đơn vị" cùng nghĩa nên chỉ hiện một
 * (giữ mức đang đặt; mặc định giữ Nội bộ vì Nhân viên không đặt được Toàn tổ chức). Backend vẫn kiểm từng mức. */
export function classChoices(t: OrgTerms, options: Classification[], current?: Classification): Classification[] {
  const list = [...new Set(current ? [current, ...options] : options)];
  if (!t.single || !list.includes('COMPANY') || !list.includes('DEPARTMENT')) return list;
  const drop: Classification = current === 'COMPANY' ? 'DEPARTMENT' : 'COMPANY';
  return list.filter(c => c !== drop);
}
const RANK: Record<Classification, number> = { PRIVATE: 0, COMPANY: 1, DEPARTMENT: 2, RESTRICTED: 3, SECRET: 4 };
/** Bản sao của can_change_classification (backend/app/core/access.py) chỉ để KHÔNG hiện mức người dùng chắc chắn bị từ chối.
 * Backend vẫn là nơi quyết định. unit = đơn vị tài liệu sẽ thuộc sau khi đổi (backend tự gắn khi tài liệu chưa có). */
export function canChangeClass(me: { level: MemberLevel; department_id: string | null }, doc: { mine: boolean; department_id: string | null; current: Classification },
  next: Classification, onlyUnit: string | null): boolean {
  if (next === doc.current) return true;
  if (!SETTABLE[me.level].includes(next)) return false;
  const bound = next === 'DEPARTMENT' || next === 'RESTRICTED';
  // backend chỉ tự gắn đơn vị khi mức mới cần đơn vị
  const unit = doc.department_id ?? (bound ? me.department_id ?? onlyUnit : null);
  if (bound && !unit) return false;
  if (me.level === 'EXECUTIVE') return true;
  if (doc.current === 'SECRET' || next === 'SECRET') return false;
  if (next === 'PRIVATE') return doc.current === 'PRIVATE' && doc.mine;
  if (me.level === 'MANAGER' && unit && unit === me.department_id) return true;
  return doc.mine && (doc.current === 'PRIVATE' || RANK[next] > RANK[doc.current]);
}
/** Câu kết quả cho thẻ chọn phạm vi: nói AI XEM ĐƯỢC thay vì tên mức. Thứ tự từ rộng đến hẹp. */
export const SCOPE_ORDER: Classification[] = ['COMPANY', 'DEPARTMENT', 'RESTRICTED', 'SECRET', 'PRIVATE'];
export function scopeTitle(t: OrgTerms, c: Classification, unitName?: string | null): string {
  const unit = unitName ? `${t.unit} ${unitName}` : `${t.unit} của bạn`;
  switch (c) {
    case 'COMPANY': return `Mọi người trong ${t.org}`;
    case 'DEPARTMENT': return t.single ? `Mọi người trong ${t.org}` : `Mọi người trong ${unit}`;
    case 'RESTRICTED': return t.single || !unitName ? `${t.MANAGER} và ${t.EXECUTIVE}` : `${t.MANAGER} ${unit} và ${t.EXECUTIVE}`;
    case 'SECRET': return `Chỉ ${t.EXECUTIVE}`;
    default: return 'Chỉ mình tôi';
  }
}
// mức mật mỗi cấp bậc được đặt (khớp SETTABLE ở backend; backend vẫn là nơi quyết định)
export const SETTABLE: Record<MemberLevel, Classification[]> = {
  STAFF: ['PRIVATE', 'DEPARTMENT', 'RESTRICTED'],
  MANAGER: ['PRIVATE', 'DEPARTMENT', 'RESTRICTED', 'COMPANY'],
  EXECUTIVE: ['PRIVATE', 'DEPARTMENT', 'RESTRICTED', 'COMPANY', 'SECRET'],
};

// ---------------- Công cụ riêng theo ngành (backend analysis/domain_tools.py). So sánh, tính toán do máy chủ làm bằng mã cố định.
const pk = () => domainPack ?? undefined;
export type Op = '>=' | '>' | '<=' | '<' | '=';
export interface Table { columns: string[]; rows: string[][]; truncated: boolean }
export interface Threshold { label: string; op: Op; value: number; unit: string; citation: string }
export interface RosterResult { results: { row: number; name: string; status: 'PASS' | 'FAIL' | 'MISSING'; checks: { label: string; value: string; state: 'pass' | 'fail' | 'missing' }[] }[]; summary: { total: number; PASS: number; FAIL: number; MISSING: number } }
interface ToolMeasured { agent: string; agent_name: string; removed?: number; input_tokens: number; output_tokens: number; latency_ms: number; evidence?: { chunk_id: string; source_name: string; score: number }[] }
export interface QuizItem { question: string; options: string[]; answer: number; explanation: string; citation: string }
export interface FaqItem { question: string; answer: string; citation: string }
export interface Article { number: string; title: string; chapter: string; source_name: string; text: string }
export interface PayRates { [key: string]: { value: number; citation: string } | null }
export interface PayRow { name: string; leave_days: number | null; leave_left: number | null; overtime_pay: number | null; overtime_hours: number; notes: string[] }
export interface ContractRisk { quote: string; level: 'HIGH' | 'MEDIUM' | 'LOW'; reason: string; citation: string }
export interface DocValidity { source_id: string; source_name: string; number: string | null; kind: string; issued: string | null; effective: string | null; replaces: string[]; references: string[]; status: 'REPLACED' | 'NOT_YET' | 'IN_FORCE' | 'UNKNOWN'; status_note: string }
export async function parseTable(file: File): Promise<Table> {
  const form = new FormData(); form.append('file', file);
  return call<Table>('/studio/tools/table', { method: 'POST', body: form });
}
export const extractThresholds = (topic: string, sourceIds: string[]) => post<ToolMeasured & { rules: Threshold[] }>('/studio/tools/thresholds', { topic, source_ids: sourceIds, domain_pack: pk() });
export const evaluateRoster = (rules: { label: string; op: Op; value: number; column: number }[], columns: string[], rows: string[][], idColumn: number | null) =>
  post<RosterResult>('/studio/tools/roster/evaluate', { rules, columns, rows, id_column: idColumn });
export const generateItems = <T extends QuizItem | FaqItem>(kind: 'quiz' | 'faq', sourceIds: string[], count: number, topic?: string) =>
  post<ToolMeasured & { items: T[] }>('/studio/tools/generate', { kind, source_ids: sourceIds.slice(0, 20), count, domain_pack: pk(), topic });
/** Số câu trong yêu cầu ("tạo 7 câu…"), mặc định 5, tối đa 10 để một lượt chạy trong thời gian chờ chấp nhận được. */
export const quizCount = (message: string) => Math.min(10, Math.max(1, Number(/(\d{1,2})\s*(câu|cau)/i.exec(message)?.[1] ?? 5)));
export const listArticles = (sourceIds: string[]) => post<{ articles: Article[] }>('/studio/tools/articles', { source_ids: sourceIds });
export const lookupArticles = (question: string, sourceIds: string[]) =>
  post<ToolMeasured & { answer: string; cited: string[]; articles: Article[]; flags: string[] }>('/studio/tools/lookup', { question, source_ids: sourceIds, domain_pack: pk() });
export const extractPayRates = (sourceIds: string[]) => post<ToolMeasured & { rates: PayRates }>('/studio/tools/pay-rates', { source_ids: sourceIds, domain_pack: pk() });
export const computePay = (rates: Record<string, number | null>, employees: Record<string, unknown>[]) => post<{ employees: PayRow[] }>('/studio/tools/pay-compute', { rates, employees });
export const findApprover = (request: string, sourceIds: string[]) =>
  post<ToolMeasured & { approver: string; rule: string; citation: string | null }>('/studio/tools/approver', { request, source_ids: sourceIds, domain_pack: pk() });
export const contractCriteria = () => call<{ criteria: TraceRequirement[] }>('/studio/tools/contract-criteria');
export const contractRisks = (sourceIds: string[]) => post<ToolMeasured & { risks: ContractRisk[]; looks_like_contract: boolean }>('/studio/tools/contract-risks', { source_ids: sourceIds, domain_pack: pk() });
// ---------------- So sánh phiên bản (Đợt 4): tách Điều/Khoản và phân loại bằng mã, không gọi mô hình
export type ChangeKind = 'ADDED' | 'MODIFIED' | 'REMOVED' | 'UNCHANGED' | 'MOVED' | 'MOVED_MODIFIED';
export interface VersionUnit { key: string; number: string; title: string; chapter: string; body: string }
export interface VersionItem { change: ChangeKind; old: VersionUnit | null; new: VersionUnit | null; similarity?: number; title_changed?: boolean;
  clauses?: { clause: string; change: 'ADDED' | 'REMOVED' | 'MODIFIED'; old?: string; new?: string }[]; numbers_changed?: string[] }
export interface VersionCompare { version: string; unit_kind: 'article' | 'heading'; old_units: number; new_units: number; counts: Record<ChangeKind, number>; items: VersionItem[];
  old: { source_id: string; source_name: string }; new: { source_id: string; source_name: string } }
export const compareVersions = (oldId: string, newId: string) => post<VersionCompare>('/studio/tools/compare', { old_source_id: oldId, new_source_id: newId });
/** Cặp bản cũ/bản mới trong các tài liệu: ưu tiên cặp có câu "thay thế <số hiệu>" (đã xác nhận); không có thì đúng hai tài liệu. */
export async function pickVersionPair(sourceIds: string[]): Promise<{ old: string; new: string; confirmed: boolean } | null> {
  const v = await documentValidity(sourceIds).catch(() => null);
  const docs = v?.documents ?? [];
  for (const d of docs) for (const n of d.replaces) {
    const old = docs.find(x => x.number === n);
    if (old) return { old: old.source_id, new: d.source_id, confirmed: true };
  }
  return sourceIds.length === 2 ? { old: sourceIds[0], new: sourceIds[1], confirmed: false } : null;
}
export const documentValidity = (sourceIds: string[]) => post<{ today: string; documents: DocValidity[] }>('/studio/tools/validity', { source_ids: sourceIds });

// ---------------- Ô chat Tự động (đợt 4, bản làm thử): chọn một kỹ năng khi câu hỏi khớp rõ, không thì để pipeline
export type SkillKey = 'conditions' | 'procedure' | 'approver' | 'contract_review' | 'validity' | 'compare' | 'quiz';
export const SKILL_LIST: { key: SkillKey; label: string; hint: string; needs?: string[] }[] = [
  { key: 'conditions', label: 'Kiểm tra điều kiện', hint: 'Một trường hợp có đủ điều kiện theo quy định không' },
  { key: 'procedure', label: 'Quy trình từng bước', hint: 'Các bước, người làm, thời hạn, giấy tờ' },
  { key: 'approver', label: 'Ai duyệt', hint: 'Cấp duyệt theo quy định cho một yêu cầu' },
  { key: 'contract_review', label: 'Rà soát hợp đồng', hint: 'Điều khoản rủi ro kèm nguyên văn', needs: ['contract'] },
  { key: 'validity', label: 'Hiệu lực văn bản', hint: 'Số hiệu, ngày hiệu lực, bị thay thế chưa', needs: ['legal_doc', 'regulation'] },
  { key: 'compare', label: 'So sánh phiên bản', hint: 'Bản mới khác bản cũ ở Điều, Khoản nào' },
  { key: 'quiz', label: 'Tạo câu hỏi trắc nghiệm', hint: '4 phương án, có đáp án, giải thích và nguồn' },
];
export type SkillRoute = { route: 'pipeline' } | { route: 'skill'; skill: SkillKey; label: string; reason: string; source_ids: string[] }
  | { route: 'clarify'; question: string; options: { agent: string; label: string }[] };  // hỏi lại khi mơ hồ (mục 3.4)
export type SkillOutput =
  | { skill: 'conditions'; data: ConditionResult }
  | { skill: 'procedure'; data: ProcedureResult }
  | { skill: 'approver'; data: Awaited<ReturnType<typeof findApprover>> }
  | { skill: 'contract_review'; data: Awaited<ReturnType<typeof contractRisks>> }
  | { skill: 'validity'; data: Awaited<ReturnType<typeof documentValidity>> }
  | { skill: 'compare'; data: VersionCompare }
  | { skill: 'quiz'; data: ToolMeasured & { items: QuizItem[] } };

/** Phạm vi tài liệu của một câu hỏi: tài liệu chọn riêng, hoặc tài liệu của không gian cá nhân đang mở (tổ chức: backend tự lọc). */
export async function chatScope(ws?: WorkspaceId, only?: string[]): Promise<string[] | undefined> {
  return only?.length ? only : wsReady(ws) ? (await workspaceItems(ws!)).source_ids : undefined;
}
export const routeSkill = (message: string, sourceIds?: string[], skill?: SkillKey) => post<SkillRoute>('/studio/route', { message, source_ids: sourceIds, skill });

export async function runSkill(skill: SkillKey, message: string, sourceIds: string[]): Promise<SkillOutput> {
  if (!sourceIds.length) throw new Error('Chưa có tài liệu phù hợp trong phạm vi hỏi cho kỹ năng này.');
  switch (skill) {
    case 'conditions': return { skill, data: await checkConditions(message, message, sourceIds) };
    case 'procedure': return { skill, data: await extractProcedure(message, sourceIds) };
    case 'approver': return { skill, data: await findApprover(message, sourceIds) };
    case 'contract_review': return { skill, data: await contractRisks(sourceIds) };
    case 'validity': return { skill, data: await documentValidity(sourceIds) };
    case 'quiz': return { skill, data: await generateItems<QuizItem>('quiz', sourceIds, quizCount(message), message) };
    case 'compare': {
      const pair = await pickVersionPair(sourceIds);
      if (!pair) throw new Error('Chọn đúng hai tài liệu (bản cũ và bản mới) trong Phạm vi hỏi ở cột phải, hoặc mở trang So sánh phiên bản.');
      return { skill, data: await compareVersions(pair.old, pair.new) };
    }
  }
}

/** Lưu câu hỏi và thẻ kết quả kỹ năng vào cuộc trò chuyện (tạo mới nếu chưa có), gán vào không gian đang mở. */
export async function saveSkillCard(conversationId: string | null, question: string, summary: string, card: { skill: string; label: string; reason: string; data: unknown }, ws?: WorkspaceId): Promise<string> {
  const r = await post<{ conversation_id: string }>('/conversations/skill-card', { conversation_id: conversationId ?? undefined, question, summary, card });
  if (r.conversation_id !== conversationId) await assignToWorkspace(ws ?? '', 'conversation', r.conversation_id);
  return r.conversation_id;
}

// Nhật ký truy cập tài liệu mức Mật (đợt 9): chỉ Ban giám đốc và chủ tổ chức xem được.
export interface SecretAccess { source_id: string; source_name: string; user: string; action: 'VIEW' | 'ASK'; at: string | null }
export const getSecretAccess = (spaceId: string) => call<SecretAccess[]>(`/org/spaces/${encodeURIComponent(spaceId)}/secret-access`);

// ---------------- Đơn từ và duyệt theo cấp (đợt 10)
export interface OrgRequest {
  request_id: string; kind: 'leave' | 'purchase' | 'other'; title: string; details: string; days: number | null;
  approver_level: 'MANAGER' | 'EXECUTIVE'; department_id: string | null; status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'WITHDRAWN';
  requester: string; mine: boolean; can_decide: boolean; check_result: Record<string, any>;
  history: { at: string; by: string; action: string; note?: string }[]; created_at: string; decided_at: string | null;
}
export const listRequests = (spaceId: string) => call<{ mine: OrgRequest[]; to_me: OrgRequest[] }>(`/org/spaces/${encodeURIComponent(spaceId)}/requests`);
export const createRequest = (spaceId: string, body: { kind: string; title: string; details: string; days: number | null; approver_level: string; check_result: Record<string, unknown> }) =>
  post<OrgRequest>(`/org/spaces/${encodeURIComponent(spaceId)}/requests`, body);
export const decideRequest = (spaceId: string, id: string, decision: 'APPROVED' | 'REJECTED', note: string) =>
  post<OrgRequest>(`/org/spaces/${encodeURIComponent(spaceId)}/requests/${encodeURIComponent(id)}/decide`, { decision, note });
export const withdrawRequest = (spaceId: string, id: string) => post<OrgRequest>(`/org/spaces/${encodeURIComponent(spaceId)}/requests/${encodeURIComponent(id)}/withdraw`, {});

// Thư mục chung trên máy chủ (đợt 10): quản trị đặt SHARED_FOLDER_PATH, người dùng đồng bộ vào kho cá nhân
export const sharedFolderStatus = () => call<{ configured: boolean; folder?: string; files?: number; skipped?: number }>('/shared-folder');
export const syncSharedFolder = () => post<{ imported: string[]; skipped: { name: string; reason: string }[] }>('/shared-folder/sync', {});
