# Cài đặt lần đầu: thư viện backend (venv), thư viện frontend, PostgreSQL (Docker), bảng dữ liệu, mô hình Ollama.
$ErrorActionPreference = 'Continue'  # lỗi thật được bắt qua $LASTEXITCODE và throw
. "$PSScriptRoot/_common.ps1"
$root = $script:Root
$ollama = Find-Ollama
if (-not $ollama) { throw 'Không tìm thấy Ollama. Cài từ https://ollama.com/download, hoặc đặt biến OLLAMA_EXE trỏ tới ollama.exe.' }
Set-OllamaModelsDir $ollama
foreach ($cmd in 'python', 'node', 'npm', 'docker') {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "Thiếu $cmd. Xem mục 'Cần cài trước' trong docs/HUONG_DAN_CHAY_DU_AN.md." }
}
& (Join-Path $root 'scripts/SETUP_BACKEND.ps1')
& (Join-Path $root 'scripts/SETUP_FRONTEND.ps1')
$pgPort = Start-ProjectPostgres
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = Get-DefaultDatabaseUrl $pgPort }
Push-Location (Join-Path $root 'backend'); & .venv/Scripts/python.exe -m alembic upgrade head; $ok = $LASTEXITCODE; Pop-Location
if ($ok -ne 0) { throw 'Cập nhật bảng (alembic upgrade head) thất bại.' }
& (Join-Path $PSScriptRoot 'start-ollama.ps1') -NoWait  # bật Ollama nếu cần và tải mô hình còn thiếu
New-Item -ItemType Directory -Force (Join-Path $root 'data/qdrant') | Out-Null
Write-Host ''
Write-Host 'Xong. Từ giờ chỉ cần Ctrl+Shift+B trong VS Code để chạy toàn bộ dự án.'
