# Chạy toàn bộ OrchestrIQ Studio không cần VS Code (dùng cho máy khách): mở 3 cửa sổ Ollama, Backend, Giao diện,
# chờ backend trả lời /api/health rồi mở trình duyệt. Tắt: đóng 3 cửa sổ đó (hoặc chạy scripts/dev/stop-all.ps1).
# Dùng: nhấp đúp MO_ORCHESTRIQ.cmd ở thư mục gốc, hoặc: powershell -ExecutionPolicy Bypass -File scripts/dev/start-all.ps1 [-Dev]
#   -Dev: giao diện chạy bằng máy chủ phát triển (cổng 5173, tự tải lại khi sửa mã) thay cho bản build (cổng 4173).
param([switch]$Dev)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot/_common.ps1"
$root = $script:Root

if (-not (Test-Path (Join-Path $root 'backend/.venv/Scripts/python.exe'))) {
  Write-Host 'Chưa cài đặt. Chạy cài đặt lần đầu trước: powershell -ExecutionPolicy Bypass -File scripts/dev/setup.ps1' -ForegroundColor Yellow
  exit 1
}

function Open-Window([string]$title, [string]$script) {
  $cmd = "`$Host.UI.RawUI.WindowTitle = 'OrchestrIQ - $title'; & '$(Join-Path $PSScriptRoot $script)'; if (`$LASTEXITCODE) { Read-Host 'Có lỗi ở trên. Nhấn Enter để đóng' }"
  Start-Process powershell -WorkingDirectory $root -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command', $cmd | Out-Null
}
function Test-Url([string]$url) { try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; $true } catch { $false } }

if (-not (Test-Url 'http://127.0.0.1:11434/api/tags')) { Open-Window 'Ollama' 'start-ollama.ps1' } else { Write-Host 'Ollama đã chạy sẵn.' }
if (-not (Test-Url 'http://127.0.0.1:8000/api/health')) { Open-Window 'Backend' 'start-backend.ps1' } else { Write-Host 'Backend đã chạy sẵn.' }
$port = if ($Dev) { 5173 } else { 4173 }
if (-not (Test-Url "http://127.0.0.1:$port/")) { Open-Window 'Giao diện' $(if ($Dev) { 'start-frontend.ps1' } else { 'start-preview.ps1' }) } else { Write-Host 'Giao diện đã chạy sẵn.' }

# Lần đầu backend phải bật Docker Desktop và PostgreSQL nên có thể mất vài phút.
Write-Host 'Đang chờ backend sẵn sàng (lần đầu có thể mất 2-3 phút)...'
$ok = $false
for ($i = 0; $i -lt 240; $i++) {
  if ((Test-Url 'http://127.0.0.1:8000/api/health') -and (Test-Url "http://127.0.0.1:$port/")) { $ok = $true; break }
  Start-Sleep -Seconds 1
}
if (-not $ok) { Write-Host 'Chưa thấy backend hoặc giao diện trả lời sau 4 phút. Xem thông báo lỗi trong các cửa sổ OrchestrIQ vừa mở.' -ForegroundColor Yellow; exit 1 }
Write-Host "Sẵn sàng: http://127.0.0.1:$port" -ForegroundColor Green
Start-Process "http://127.0.0.1:$port/studio"
