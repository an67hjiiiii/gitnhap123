# Fake provider demo quickstart

On Windows with Python 3.12, run this once from the repository root:

```powershell
powershell -File scripts\DEMO_FAKE.ps1
```

The script creates `backend\.venv` if needed and installs only packages listed in the existing `backend\requirements.txt`. Installation needs package access to PyPI on a clean machine; if the network is unavailable, prepare the venv with those requirements before running the script. No Ollama or PostgreSQL service is used. The backend uses file storage under the operating system temporary directory (`cap1-ai-fake-demo`), never the repository `data` or `runs` directories. The launcher registers/logs in a local demo account and uploads the original sample files once. The demo account credentials are printed by the script.

`PROVIDER=fake` and `REVIEW_ENGINE=fake` mean answers/findings are deterministic fake-provider demo output, not real model output. Vector indexing is disabled and retrieval uses the lexical backend.

## API walkthrough

Use PowerShell's `Invoke-RestMethod` or `curl.exe`. First obtain a bearer token (the launcher already logs in and uploads samples):

```powershell
$base = 'http://127.0.0.1:8000'
$login = Invoke-RestMethod -Method Post "$base/api/auth/login" -ContentType 'application/json' -Body '{"identifier":"demo@example.test","password":"demo-pass-123"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

1. Upload a document: `curl.exe -F "file=@demo/sample_docs/requirements_vi.txt" -H "Authorization: Bearer $($login.access_token)" "$base/api/sources/file"`
2. Create a review case: `POST $base/api/review/cases` with `title`, `request_text`, and uploaded `source_ids` from `GET $base/api/sources`.
3. Add confirmed requirements with `PUT /api/review/cases/{case_id}/requirements` and then start with `POST /api/review/cases/{case_id}/runs`.
4. Read job status at `GET /api/review/runs/{job_id}` and events at `GET /api/review/runs/{job_id}/events`.
5. Export Markdown with `GET /api/review/cases/{case_id}/export?format=md`.

The complete API schema is available at `http://127.0.0.1:8000/docs`.
