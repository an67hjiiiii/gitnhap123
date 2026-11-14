/** Types for the Review API contract snapshot. */
export type CaseKind = "requirement_review" | "spec_change";
export type CaseStatus = "DRAFT" | "CONFIRMING" | "READY" | "RUNNING" | "PARTIAL" | "COMPLETE" | "FAILED";
export type Verdict = "SATISFIED" | "PARTIAL" | "NOT_FOUND" | "DEVIATES" | "UNDETERMINED" | "SKIPPED_BUDGET";
export type Decision = "NONE" | "ACCEPT" | "REJECT" | "EDIT";
export type DecisionInputReview = "ACCEPT" | "REJECT" | "EDIT";
export type JobState = "QUEUED" | "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "CANCELLED";
export type Confidence = "L0" | "L1" | "L2" | "L3";
export type RequirementOrigin = "AI_PROPOSED" | "USER";

export interface CaseInput { title: string; request_text: string; source_ids?: string[]; kind?: CaseKind; old_source_id?: string | null; new_source_id?: string | null }
export interface DecisionInput { review: DecisionInputReview; edited_text?: string | null }
export interface ErrorBody { code: string; message: string; details?: Record<string, unknown> | null }
export interface RequirementInput { text: string; id?: string | null; confirmed?: boolean }
export interface RequirementsInput { requirements: RequirementInput[] }
export interface RunInput { budget?: Record<string, unknown> | null }

export interface ReviewCase { id: string; owner_user_id: string; title: string; status: CaseStatus; source_ids: string[]; kind: CaseKind; old_source_id: string | null; new_source_id: string | null; request_text: string; created_at: string; updated_at: string }
export interface Requirement { id: string; case_id: string; text: string; origin: RequirementOrigin; confirmed: boolean; order: number }
export interface Evidence { evidence_id: string; source_id: string; locator: string; excerpt: string }
export interface Finding { id: string; case_id: string; requirement_id: string; verdict: Verdict; evidence: Evidence[]; review: Decision; edited_text: string | null; confidence: Confidence }
export interface ReviewCaseDetail extends ReviewCase { requirements: Requirement[]; findings: Finding[] }
export interface ReviewJob { id: string; case_id: string; state: JobState; seq: number; budget: Record<string, unknown> | null; started_at: string | null; finished_at: string | null }
export interface InspectorEvent { seq: number; type: string; ts: string; data: Record<string, unknown> }
export interface InspectorRequirement { id: string; text: string; confirmed: boolean; origin: RequirementOrigin; finding: { verdict: Verdict; confidence: Confidence; review: Decision; edited_text: string | null } | null; evidence: Array<{ source_id: string | null; locator: string | null; excerpt: string | null }> }
export interface Inspector { case: Pick<ReviewCase, "id" | "title" | "status" | "kind" | "old_source_id" | "new_source_id" | "source_ids" | "created_at" | "updated_at">; requirements: InspectorRequirement[]; run: (Omit<ReviewJob, "case_id" | "budget" | "seq"> & { seq: { last: number; count: number }; route_decision: Record<string, unknown> | null }) | null; events: InspectorEvent[]; budget: { given: Record<string, unknown> | null; skipped_requirement_ids: string[] } }
export interface ReviewEvent<T = unknown> { id: number; event: string; data: T }
export interface RouteDecidedEvent { route: string; reasons: string[]; budget_hint: Record<string, unknown> }
export interface FindingCreatedEvent extends Finding {}
export interface ExportResult { body: string; contentType: string }
export interface SuggestionOutput { entry_id: string; similarity: number; prior_verdict: string; prior_decision: "ACCEPT" | "REJECT" | "EDIT"; edited_text: string | null; note: string }
