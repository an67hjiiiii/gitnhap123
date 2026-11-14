import type { CaseInput, DecisionInput, ErrorBody, ExportResult, Finding, Inspector, Requirement, RequirementsInput, ReviewCase, ReviewCaseDetail, ReviewEvent, ReviewJob, RunInput } from "./review-types";

export class ReviewApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorBody["details"];
  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ReviewApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }
}

export interface SubscribeOptions { lastEventId?: number; signal?: AbortSignal }
export class ReviewClient {
  constructor(private readonly baseUrl = "", private readonly token = "") {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.token}`);
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers });
    if (!response.ok) {
      let body: ErrorBody;
      try { body = await response.json() as ErrorBody; }
      catch { body = { code: "HTTP_ERROR", message: response.statusText || "Request failed" }; }
      throw new ReviewApiError(response.status, body);
    }
    return response.json() as Promise<T>;
  }

  // Snapshot operationIds: create_case_api_review_cases_post, list_cases_api_review_cases_get.
  createCase(input: CaseInput): Promise<ReviewCase> { return this.request("/api/review/cases", { method: "POST", body: JSON.stringify(input) }); }
  listCases(): Promise<ReviewCase[]> { return this.request("/api/review/cases"); }
  // Snapshot operationId: get_case_api_review_cases__case_id__get.
  getCase(caseId: string): Promise<ReviewCaseDetail> { return this.request(`/api/review/cases/${encodeURIComponent(caseId)}`); }
  // Snapshot operationId: inspector_api_review_cases__case_id__inspector_get.
  inspector(caseId: string, run?: string): Promise<Inspector> {
    const query = run === undefined ? "" : `?run=${encodeURIComponent(run)}`;
    return this.request(`/api/review/cases/${encodeURIComponent(caseId)}/inspector${query}`);
  }
  // Snapshot operationIds: propose_api_review_cases__case_id__requirements_propose_post, replace_requirements_api_review_cases__case_id__requirements_put.
  proposeRequirements(caseId: string): Promise<Requirement[]> { return this.request(`/api/review/cases/${encodeURIComponent(caseId)}/requirements:propose`, { method: "POST" }); }
  replaceRequirements(caseId: string, input: RequirementsInput): Promise<Requirement[]> { return this.request(`/api/review/cases/${encodeURIComponent(caseId)}/requirements`, { method: "PUT", body: JSON.stringify(input) }); }
  // Snapshot operationIds: start_run_api_review_cases__case_id__runs_post, get_run_api_review_runs__job_id__get, cancel_api_review_runs__job_id__cancel_post.
  startRun(caseId: string, input: RunInput = {}): Promise<ReviewJob> { return this.request(`/api/review/cases/${encodeURIComponent(caseId)}/runs`, { method: "POST", body: JSON.stringify(input) }); }
  getRun(jobId: string): Promise<ReviewJob> { return this.request(`/api/review/runs/${encodeURIComponent(jobId)}`); }
  cancelRun(jobId: string): Promise<ReviewJob> { return this.request(`/api/review/runs/${encodeURIComponent(jobId)}:cancel`, { method: "POST" }); }
  // Snapshot operationIds: decide_api_review_findings__finding_id__decision_put, export_api_review_cases__case_id__export_get.
  decideFinding(findingId: string, input: DecisionInput): Promise<Finding> { return this.request(`/api/review/findings/${encodeURIComponent(findingId)}/decision`, { method: "PUT", body: JSON.stringify(input) }); }
  async exportCase(caseId: string, format: "md" = "md"): Promise<ExportResult> {
    const response = await fetch(`${this.baseUrl}/api/review/cases/${encodeURIComponent(caseId)}/export?format=${encodeURIComponent(format)}`, { headers: { Authorization: `Bearer ${this.token}` } });
    if (!response.ok) {
      let body: ErrorBody;
      try { body = await response.json() as ErrorBody; } catch { body = { code: "HTTP_ERROR", message: response.statusText || "Request failed" }; }
      throw new ReviewApiError(response.status, body);
    }
    return { body: await response.text(), contentType: response.headers.get("content-type") ?? "" };
  }

  async subscribeEvents(jobId: string, onEvent: (event: ReviewEvent) => void, options: SubscribeOptions = {}): Promise<void> {
    // Snapshot operationId: events_api_review_runs__job_id__events_get.
    const headers = new Headers({ Authorization: `Bearer ${this.token}`, Accept: "text/event-stream" });
    if (options.lastEventId !== undefined) headers.set("Last-Event-ID", String(options.lastEventId));
    const response = await fetch(`${this.baseUrl}/api/review/runs/${encodeURIComponent(jobId)}/events`, { headers, signal: options.signal });
    if (!response.ok) {
      let body: ErrorBody;
      try { body = await response.json() as ErrorBody; } catch { body = { code: "HTTP_ERROR", message: response.statusText || "Request failed" }; }
      throw new ReviewApiError(response.status, body);
    }
    if (!response.body) throw new Error("Streaming response body is unavailable");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let id = 0;
    let event = "message";
    let data: string[] = [];
    const dispatch = () => {
      if (data.length) onEvent({ id, event, data: JSON.parse(data.join("\n")) as unknown });
      id = 0; event = "message"; data = [];
    };
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (line === "") { dispatch(); continue; }
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        const valueText = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "id") { const parsed = Number(valueText); if (Number.isSafeInteger(parsed)) id = parsed; }
        else if (field === "event") event = valueText;
        else if (field === "data") data.push(valueText);
      }
      if (done) { if (buffer) { if (buffer.startsWith("data:")) data.push(buffer.slice(5).replace(/^ /, "")); } dispatch(); return; }
    }
  }
}
