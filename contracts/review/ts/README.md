# Review TypeScript client

Dependency-free browser client for the checked-in Review API snapshot. Copy `review-types.ts` and `review-client.ts` into the frontend and create a client with `new ReviewClient("http://localhost:8020", "review-mock-token")` while using the local mock.

Run the mock from `backend` with `python scripts/run_review_mock.py`. It listens on `http://localhost:8020`, permits the frontend origin `http://localhost:5173`, and prints its fixed development bearer token at startup. The mock uses only the in-memory review repository and a deterministic fake engine.

`subscribeEvents(jobId, callback, { lastEventId, signal })` reads server-sent events using `fetch`, allowing the bearer token and resume header to be sent. `exportCase` returns the markdown body and content type.
