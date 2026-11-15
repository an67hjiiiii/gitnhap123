# Tắt OrchestrIQ Studio: dừng tiến trình đang nghe ở cổng backend (8000) và giao diện (4173, 5173).
# Ollama và PostgreSQL (Docker) để nguyên vì máy có thể dùng cho việc khác; thêm -All để tắt cả hai.
# -DryRun: chỉ liệt kê tiến trình sẽ bị dừng, không dừng gì.
# Dùng: nhấp đúp TAT_ORCHESTRIQ.cmd, hoặc: powershell -ExecutionPolicy Bypass -File scripts/dev/stop-all.ps1 [-All] [-DryRun]
param([switch]$All, [switch]$DryRun)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot/_common.ps1"
$ports = @(8000, 4173, 5173) + $(if ($All) { @(11434) } else { @() })
foreach ($port in $ports) {
  $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($procId in $pids) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $p) { continue }
    if ($DryRun) { Write-Host "Sẽ dừng $($p.ProcessName) (PID $procId) ở cổng $port"; continue }
    Write-Host "Dừng $($p.ProcessName) (PID $procId) ở cổng $port"; Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  }
}
if ($DryRun) { Write-Host 'Chạy thử: chưa dừng gì.'; exit 0 }
if ($All -and (Get-Command docker -ErrorAction SilentlyContinue)) {
  Push-Location (Join-Path $script:Root 'docker'); docker compose stop 2>&1 | Out-Host; Pop-Location
}
Write-Host 'Đã tắt OrchestrIQ Studio.' -ForegroundColor Green
