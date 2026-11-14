# Operations defaults

- `APP_HTTPS=1` enables the HSTS response header; otherwise HSTS is omitted.
- `SESSION_COOKIE_SECURE` defaults to `false`; set it to `true` (or `1`/`yes`) to mark the session cookie Secure.
- `CORS_ALLOW_ORIGINS` is unset by default, so CORS middleware is not enabled. Set a comma-separated list of explicit origins to enable it; `*` is ignored.
- `APP_STORAGE_BACKEND` defaults to `postgres`; readiness runs `SELECT 1` with a 2 second budget only for this backend.
- `VECTOR_BACKEND` defaults to `disabled`; readiness reuses the configured in-process vector store and does not open another embedded client.
- `PROVIDER` defaults to `fake`; Ollama readiness is checked only for Ollama provider or embedding configuration, with a 2 second timeout.
- `DB_POOL_TIMEOUT` defaults to `10` seconds. `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` are only passed when set. PostgreSQL `DB_CONNECT_TIMEOUT` defaults to `5` seconds; SQLite receives no PostgreSQL connect timeout.

`GET /api/health` now returns only `ok`, `app`, and `version`. Consumers must no longer expect `config_hash`, `source_snapshot_id`, `implementation_profile`, `allowed_conditions`, `storage_backend`, or `default_provider` there. The bundled UI reads `implementation_profile` and `allowed_conditions` from `/api/config`.

Embedded Qdrant has no request timeout.
