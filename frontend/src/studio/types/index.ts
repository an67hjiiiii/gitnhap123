export interface User {
  id: number;
  username: string;
  email: string;
  full_name: string;
  avatar?: string | null;
  role: 'developer' | 'tech_lead' | 'researcher' | 'admin' | string;
  created_at: string;
}

export interface Workspace {
  id: number | string;
  name: string;
  description?: string;
  owner_id?: number;
  created_at: string;
  documents_count: number;
  runs_count: number;
  /** personal = thư mục cá nhân (studio_workspaces); org = không gian tổ chức (mã sp_) */
  kind?: 'personal' | 'org';
  level?: 'STAFF' | 'MANAGER' | 'EXECUTIVE';
  is_owner?: boolean;
  /** mẫu tổ chức và tên gọi tự đặt (chỉ hiển thị), xem orgTerms trong services/api */
  preset?: string | null;
  /** số đơn vị (phòng, khoa, tổ); 1 = chế độ một đơn vị */
  unit_count?: number;
  labels?: { org?: string; unit?: string; STAFF?: string; MANAGER?: string; EXECUTIVE?: string } | null;
  /** lĩnh vực cho trợ lý AI (xem DOMAIN_PACKS); thiếu = Phần mềm */
  domain_pack?: string;
}

export interface ExperimentConfig {
  id: number;
  name: string;
  llm_model: string;
  temperature: number;
  top_k: number;
  chunk_size: number;
  chunk_overlap: number;
  dedup_threshold: number;
  is_locked: boolean;
  created_at: string;
}

export interface TableOverviewItem {
  table_name: string;
  display_name: string;
  row_count: number;
  description: string;
}

export interface DatabaseOverviewResponse {
  database_type: string;
  qdrant_status: string;
  qdrant_points: number;
  tables: TableOverviewItem[];
}

export interface TableDataResponse {
  table_name: string;
  columns: string[];
  rows: Record<string, any>[];
  total_count: number;
}

export interface SubTask {
  id: string;
  agent_role: 'DatabaseAgent' | 'APIAgent' | 'SecurityAgent' | string;
  title: string;
  description: string;
  retrieval_query: string;
  status: 'pending' | 'processing' | 'running' | 'completed' | 'failed' | 'blocked' | 'cancelled';
  requirement_ids?: string[];
  depends_on?: string[];
  evidence_ids?: string[];
  source_task_ids?: string[];
  assignment_reason?: string;
  assigned_context_count: number;
  output?: string;
}

export interface ContextChunk {
  id: string;
  text: string;
  source_file: string;
  file_type: string;
  domain_tags: string[];
  similarity_score: number;
  is_shared?: boolean;
}

export interface AgentResult {
  task_id?: string;
  agent_role: string;
  subtask_title: string;
  latency_ms: number;
  tokens_used: number;
  content: string;
  relevant_chunks: ContextChunk[];
}

export interface BriefVerification {
  compressed: boolean;
  dropped_sentences: number;
  total_sentences?: number;
  method: string;
  verification: { ok: boolean; issues: { type: string; chunk_id: string }[] };
  evidence: { missing_evidence: string[]; task_coverage: number | null; conflict_check: string };
}

export interface ModeExecutionResult {
  planning_trace?: {
    requirements?: {id: string; text: string}[];
    planning_evidence?: ContextChunk[];
    execution_order?: string[];
    aliases?: Record<string, string>;
    raw_tasks?: unknown[];
  };
  execution_trace?: {task_id: string; status: string; depends_on: string[]; elapsed_ms: number}[];
  mode: 'vanilla_rag' | 'naive_multi_agent' | 'proposed_adaptive';
  mode_display_name: string;
  latency_ms: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  tokens_saved: number | null;
  token_saving_ratio: number | null;
  cpu_percent: number;
  ram_usage_mb: number;
  ram_delta_mb: number;
  task_coverage: number | null;
  subtasks: SubTask[];
  shared_brief?: string;
  brief_verification?: BriefVerification | null;
  agent_results: AgentResult[];
  final_answer: string;
  retrieved_chunks_count: number;
  /** Bản ghi run gốc của CAP1 (events, tasks, provenance) để hiển thị đúng từng bước. */
  raw?: Record<string, any>;
}

export interface AnalyzeResponse {
  project_name: string;
  query: string;
  execution_timestamp: string;
  results: Record<string, ModeExecutionResult>;
}

export interface DocumentInfo {
  id?: number;
  source_file: string;
  chunks_count: number;
  file_type: string;
  domain_tags: string[];
  file_size_kb?: number;
  status?: 'indexed' | 'processing' | 'failed' | string;
  created_at?: string;
  workspace_id?: number;
  doc_type?: string | null;  // loại tài liệu hệ thống tự nhận (sửa được), khóa trong DOC_TYPES
  // chỉ có ở tài liệu thuộc không gian tổ chức
  classification?: 'PRIVATE' | 'COMPANY' | 'DEPARTMENT' | 'RESTRICTED' | 'SECRET';
  department_id?: string | null;
  owner?: string;
  mine?: boolean;
  can_delete?: boolean;
}

export interface ChunkInfo {
  id: number;
  document_id: number;
  chunk_index: number;
  qdrant_point_id: string;
  content: string;
  token_count: number;
  domain_tag: string;
  created_at?: string;
}

export interface RetrievalResultItem {
  chunk_id: string;
  score: number;
  similarity_percentage: number;
  text: string;
  source_file: string;
  file_type: string;
  domain_tags: string[];
}

export interface RetrievalTestRequest {
  query: string;
  top_k: number;
  workspace_id?: number | string;
  domain_tag?: string;
}

export interface RetrievalTestResponse {
  query: string;
  top_k: number;
  domain_filter?: string | null;
  latency_ms: number;
  total_indexed_chunks: number;
  results: RetrievalResultItem[];
}

export interface TelemetryRecord {
  record_source?: string;
  measurement_status?: string;
  id: number;
  created_at: string;
  project_name: string;
  user_query: string;
  execution_mode: string;
  latency_ms: number | null;
  total_tokens: number | null;
  tokens_saved: number | null;
  token_saving_ratio: number | null;
  cpu_percent: number | null;
  ram_usage_mb: number | null;
  ram_delta_mb: number | null;
  task_coverage: number | null;
  retrieved_chunks_count: number;
}

export interface RunDetail {
  id: number;
  created_at: string;
  user_query: string;
  execution_mode: string;
  result: ModeExecutionResult;
}

export interface HealthResponse {
  status: string;
  database_type: string;
  qdrant_status: string;
  qdrant_mode: string;
  indexed_documents_count: number;
  total_chunks_count: number;
  ollama_status: string;
  ollama_model: string;
  cpu_usage_percent: number;
  memory_usage_mb: number;
}

export type ExecutionMode = 'proposed_adaptive' | 'naive_multi_agent' | 'vanilla_rag' | 'ablation_comparison';
export type NavigationTab = 'orchestration' | 'chat' | 'overview' | 'documents' | 'toolkit' | 'consistency' | 'evaluation' | 'benchmarks' | 'rating' | 'users' | 'db_explorer' | 'organization'
  | 'library' | 'results' | 'tasks' | 'settings' | 'compare' | 'notifications' | 'office' | 'guide';  // đợt 6+: bố cục gọn, gom Phòng thí nghiệm & Hướng dẫn nhanh

// Phase 6: Security Audit & Diagnostics Types
export interface SecurityCheckpointItem {
  code: string;
  name: string;
  status: string;
  details: string;
  compliant: boolean;
}

export interface SecurityAuditResponse {
  project_name: string;
  on_premise_compliance: boolean;
  air_gap_ready: boolean;
  network_egress_status: string;
  audit_score: string;
  database_type: string;
  vector_db_mode: string;
  llm_endpoint: string;
  rbac_active_roles: string[];
  jwt_algorithm: string;
  security_headers_enforced: boolean;
  checkpoints: SecurityCheckpointItem[];
  audit_timestamp: string;
}

export interface TableDiagnosticItem {
  table_name: string;
  record_count: number;
  foreign_keys_intact: boolean;
  schema_valid: boolean;
}

export interface DbDiagnosticResponse {
  active_engine: string;
  database_url_redacted: string;
  dialect: string;
  foreign_keys_enabled: boolean;
  tables_count: number;
  tables: TableDiagnosticItem[];
  pool_status: Record<string, any>;
}

export interface LLMContentionSimulateResponse {
  test_query: string;
  circuit_breaker_triggered: boolean;
  circuit_state: string;
  fallback_activated: boolean;
  recovery_latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  result_preview: string;
  resilience_status: string;
}
