# Chạy giao diện (Vite) ở http://127.0.0.1:5173, chuyển /api sang backend 127.0.0.1:8000.
$ErrorActionPreference = 'Continue'  # lỗi thật được bắt qua $LASTEXITCODE và throw
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location (Join-Path $root 'frontend')
try {
  if (-not (Test-Path node_modules)) { Write-Host 'Cài thư viện frontend (chỉ lần đầu)...'; npm.cmd ci }
  if (-not $env:API_TARGET) { $env:API_TARGET = 'http://127.0.0.1:8000' }
  npm.cmd run dev -- --host 127.0.0.1 --port 5173
} finally { Pop-Location }
