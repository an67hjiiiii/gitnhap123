# Bật PostgreSQL (Docker), cập nhật bảng (Alembic) rồi chạy backend FastAPI ở 127.0.0.1:8000.
# Biến môi trường đặt sẵn ở đây chỉ là mặc định; đặt trước khi chạy (hoặc trong backend/.env) thì giá trị của bạn được dùng.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$defaults = [ordered]@{
  DATABASE_URL = 'postgresql+psycopg://cap1_ai:change-me-locally@127.0.0.1:55435/cap1_ai_midterm_multilingual'
  APP_STORAGE_BACKEND = 'postgres'; APP_ENV = 'development'
  PROVIDER = 'ollama'; LOCAL_LLM_MODEL = 'qwen3:4b'; IMPLEMENTATION_PROFILE = 'm2'; PRODUCT_CONDITION = 'C'
  MAX_OUTPUT_TOKENS = '700'; TASK_PLAN_MAX_OUTPUT_TOKENS = '1400'
  VECTOR_BACKEND = 'qdrant'; VECTOR_INDEX_BACKEND = 'qdrant'; VECTOR_INDEX_PATH = (Join-Path $root 'data/qdrant')
  CONTEXT_POLICY = 'adaptive_qwen'; EMBEDDING_BACKEND = 'ollama'; VECTOR_COLLECTION = 'domain_nomic'
}
foreach ($k in $defaults.Keys) { if (-not [Environment]::GetEnvironmentVariable($k)) { Set-Item "env:$k" $defaults[$k] } }

$py = Join-Path $root 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path $py)) { throw 'Chưa cài backend. Chạy task "Cài đặt lần đầu" (hoặc scripts/dev/setup.ps1) trước.' }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Chưa cài Docker Desktop.' }
docker compose -f (Join-Path $root 'docker/docker-compose.yml') up -d postgres
if ($LASTEXITCODE -ne 0) { throw 'Không bật được PostgreSQL. Hãy mở Docker Desktop rồi chạy lại.' }
Write-Host 'Chờ PostgreSQL sẵn sàng...'
for ($i = 0; $i -lt 40; $i++) { docker exec cap1-ai-midterm-postgres pg_isready -q 2>$null; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep -Seconds 1 }

Push-Location (Join-Path $root 'backend')
try {
  & $py -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw 'Cập nhật bảng (alembic upgrade head) thất bại.' }
  & $py -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
} finally { Pop-Location }
