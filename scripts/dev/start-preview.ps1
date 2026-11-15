# Chạy giao diện bằng bản build tối ưu (như khi bàn giao cho khách) ở http://127.0.0.1:4173, chuyển /api sang backend.
# Backend vẫn chạy bằng scripts/dev/start-backend.ps1 (hoặc Ctrl+Shift+B).
param([switch]$Rebuild)
$ErrorActionPreference = 'Continue'  # lỗi thật được bắt qua $LASTEXITCODE và throw
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location (Join-Path $root 'frontend')
try {
  if (-not (Test-Path node_modules)) { Write-Host 'Cài thư viện frontend (chỉ lần đầu)...'; npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci thất bại.' } }
  if ($Rebuild -or -not (Test-Path dist/index.html)) {
    Write-Host 'Build giao diện...'; npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Build giao diện thất bại.' }
  }
  if (-not $env:API_TARGET) { $env:API_TARGET = 'http://127.0.0.1:8000' }
  npm.cmd run preview -- --host 127.0.0.1 --port 4173 --strictPort
} finally { Pop-Location }
