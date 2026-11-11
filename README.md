# CAP1_AI Midterm Portable Runtime

Local Product UI + FastAPI backend + PostgreSQL 16 + embedded Qdrant + Ollama qwen3:4b.
The included PostgreSQL dump is sanitized: one synthetic demo user, no private historical conversations/runs.

## Quick start

```powershell
.\scripts\SETUP_FIRST_TIME.ps1
.\scripts\START_CAP1_MIDTERM.ps1
.\scripts\VERIFY_CAP1_MIDTERM.ps1
```

Set `DATABASE_URL` to the package-owned PostgreSQL database before starting. Never commit `.env` or credentials.
