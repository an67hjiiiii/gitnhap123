# Cài đặt lần đầu: thư viện backend (venv), thư viện frontend, PostgreSQL (Docker), bảng dữ liệu, mô hình Ollama.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
foreach ($cmd in 'python', 'node', 'npm', 'docker', 'ollama') {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "Thiếu $cmd. Xem mục 'Cần cài trước' trong docs/HUONG_DAN_CHAY_DU_AN.md." }
}
& (Join-Path $root 'scripts/SETUP_BACKEND.ps1')
& (Join-Path $root 'scripts/SETUP_FRONTEND.ps1')
docker compose -f (Join-Path $root 'docker/docker-compose.yml') up -d postgres
if ($LASTEXITCODE -ne 0) { throw 'Không bật được PostgreSQL. Hãy mở Docker Desktop rồi chạy lại.' }
for ($i = 0; $i -lt 40; $i++) { docker exec cap1-ai-midterm-postgres pg_isready -q 2>$null; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep -Seconds 1 }
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = 'postgresql+psycopg://cap1_ai:change-me-locally@127.0.0.1:55435/cap1_ai_midterm_multilingual' }
Push-Location (Join-Path $root 'backend'); & .venv/Scripts/python.exe -m alembic upgrade head; $ok = $LASTEXITCODE; Pop-Location
if ($ok -ne 0) { throw 'Cập nhật bảng (alembic upgrade head) thất bại.' }
foreach ($m in 'qwen3:4b', 'nomic-embed-text') { ollama pull $m }
New-Item -ItemType Directory -Force (Join-Path $root 'data/qdrant') | Out-Null
Write-Host ''
Write-Host 'Xong. Từ giờ chỉ cần Ctrl+Shift+B trong VS Code để chạy toàn bộ dự án.'
