# Review API frontend integration

Base path: `/api/review`. The API uses the session established by `/api/auth/login`.
Send its `access_token` on review requests as `Authorization: Bearer <token>`.
The review API is owner scoped; an unavailable or another user's resource is returned as 404.

## Ordered flow

1. `POST /cases` with `title`, `request_text`, and optional `source_ids`; retain response `id`.
2. `POST /cases/{case_id}/requirements:propose` to get proposed requirements.
3. `PUT /cases/{case_id}/requirements` with `{ "requirements": [...] }`. Send each requirement's `id`, `text`, and `confirmed: true` after user confirmation.
   `GET /cases/{case_id}/requirements/{requirement_id}/suggestions` may return prior-decision suggestions for a requirement; display them as context and do not treat them as confirmation or a decision.
4. `POST /cases/{case_id}/runs` (optional `{ "budget": {...} }`); retain response `id` as the job ID.
5. `GET /runs/{job_id}/events` to consume the event stream.
6. Read results from `GET /cases/{case_id}` or `/cases/{case_id}/inspector`.
7. `PUT /findings/{finding_id}/decision` with `ACCEPT`, `REJECT`, or `EDIT`; `EDIT` accepts `edited_text`.
8. `GET /cases/{case_id}/export?format=md` for a Markdown export.

## Server-sent events

The events endpoint streams `text/event-stream`. Send `Last-Event-ID: <last seq>` when
reconnecting; the server resumes after that sequence. Event blocks carry `id`, `event`,
and JSON `data`. Current event names include `route.decided`, `task.started`, `task.done`,
`finding.created`, `budget.skipped`, `pipeline.trace`, `verdict.conflict`,
`verdict.answer_inconsistent`, `verdict.slots_missing`, `task.failed`, `error`,
`job.started`, `job.resumed`, `job.done`, `job.failed`, and `job.cancelled`. Map event
names through `labels.vi.json`'s `events`; treat unknown names as forward-compatible.
`route.decided.data.reasons` contains `{code, params}` objects. Verdict events carry a
stable `code` and structured `params`.

## Values

- Case status: `DRAFT`, `CONFIRMING`, `READY`, `RUNNING`, `PARTIAL`, `COMPLETE`, `FAILED`.
- Job state: `QUEUED`, `RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`, `CANCELLED`.
- Finding verdict: `SATISFIED`, `PARTIAL`, `NOT_FOUND`, `DEVIATES`, `UNDETERMINED`, `SKIPPED_BUDGET`.
- Decision: `NONE`, `ACCEPT`, `REJECT`, `EDIT`. Confidence: `L0` through `L3`.
- Requirement origin: `AI_PROPOSED` or `USER`.

`POST /cases` supports `kind: "requirement_review"` (default) and `kind: "spec_change"`.
For `spec_change`, provide both `old_source_id` and `new_source_id`; they must belong to
the current user. The response retains these IDs. The default kind ignores these optional fields.

## Errors

Error responses use `{ "code": string, "message": string, "details": ... }` where
`details` may be absent. Map codes through `labels.vi.json`; show `what` and `todo`,
never the server `message`, and use fallback text for unknown codes.

| Code | Meaning / frontend action |
| --- | --- |
| `AUTHENTICATION_REQUIRED` | Sign in again; request returned 401. |
| `CASE_NOT_FOUND` | Resource is absent or not visible to this user; return to case list. |
| `RUN_NOT_FOUND` | Run is absent or not associated with the requested case; refresh run state. |
| `SOURCE_NOT_FOUND` | Selected source is unavailable to this user; ask them to choose an available source. |
| `REQUIREMENTS_UNCONFIRMED` | Confirm requirements before starting a run. |
| `CASE_RUNNING` | Wait for the active run before editing or starting another. |
| `RUN_BUDGET_EXCEEDED` | Adjust the run budget. |
| `VALIDATION_ERROR` | Correct request fields using the returned message/details. |
| `REVIEW_ENGINE_UNAVAILABLE` | Run service is unavailable; allow retry. |
| `DERIVED_INDEX_UNAVAILABLE` | Review could not access its derived index; show failure and allow retry. |
| `FINDING_NOT_FOUND` | Finding is absent; refresh the latest results. |
| `INTERNAL_ERROR` | A system error occurred; allow retry. |
| `RATE_LIMITED` | Wait for the `Retry-After` seconds before retrying. |

## Retry and idempotency

No idempotency key is defined in this contract. A retry of case creation or run creation
can create another resource/job; check the case list or run state before retrying after
an uncertain response. Use `Last-Event-ID` to resume SSE without replaying earlier events.
The API rejects edits while a case has an active run with `CASE_RUNNING`.
Limits default to 2 run starts/minute and 60 other review requests/minute per user.
Polling `GET /runs/{id}` counts toward the latter; prefer SSE.

## Limits

`request_text` is limited to 20,000 characters and requirement text, including edited
text, to 2,000 characters by default. A case accepts at most 100 requirements. Configure
these with `REVIEW_MAX_REQUEST_CHARS`, `REVIEW_MAX_REQUIREMENT_CHARS`, and
`REVIEW_MAX_REQUIREMENTS_PER_CASE`. Run budgets are capped by `REVIEW_MAX_REQUIREMENTS`
(100) and `REVIEW_MAX_SECONDS` (3600); `REVIEW_MAX_TOKENS` and
`REVIEW_MAX_MODEL_CALLS` have no ceiling unless configured. When capped, returned job
budgets show the effective values.

The per-user limits default to 2 run starts and 60 other review requests per minute,
configured with `REVIEW_RATE_RUNS_PER_MIN` and `REVIEW_RATE_READS_PER_MIN`. Set either
to `0` to disable it. A limited request returns HTTP 429 with code `RATE_LIMITED`;
wait at least the number of seconds in the `Retry-After` response header before retrying.
