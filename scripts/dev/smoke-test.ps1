# Kiểm tra nhanh sau khi cài đặt hoặc trước buổi trình diễn: backend, CSDL, Ollama và mô hình, giao diện, API phân tích.
# Dùng: powershell -ExecutionPolicy Bypass -File scripts/dev/smoke-test.ps1   (thêm -Frontend http://127.0.0.1:4173 khi chạy bản preview)
param([string]$Backend = 'http://127.0.0.1:8000', [string]$Frontend = 'http://127.0.0.1:5173', [string]$Ollama = 'http://127.0.0.1:11434')
$ErrorActionPreference = 'Stop'
$failed = 0
function Check([string]$name, [scriptblock]$test) {
  try { $detail = & $test; Write-Host ("[ĐẠT]  {0}  {1}" -f $name, $detail) -ForegroundColor Green }
  catch { $script:failed++; Write-Host ("[LỖI]  {0}  {1}" -f $name, $_.Exception.Message) -ForegroundColor Red }
}

Check 'Backend /api/health' {
  $h = Invoke-RestMethod "$Backend/api/health" -TimeoutSec 10
  if (-not $h.ok) { throw 'health trả ok=false' }
  "lưu trữ=$($h.storage_backend), điều kiện=$($h.allowed_conditions -join ',')"
}
Check 'Ollama và mô hình' {
  $tags = (Invoke-RestMethod "$Ollama/api/tags" -TimeoutSec 10).models.name
  foreach ($m in 'qwen3:4b', 'nomic-embed-text') { if (-not ($tags | Where-Object { $_ -like "$m*" })) { throw "thiếu mô hình $m (chạy scripts/dev/start-ollama.ps1)" } }
  'qwen3:4b, nomic-embed-text'
}
Check 'Mô hình cục bộ trả lời được' {
  $r = Invoke-RestMethod "$Backend/api/local-model/health" -TimeoutSec 60
  ($r | ConvertTo-Json -Compress -Depth 3).Substring(0, [Math]::Min(120, ($r | ConvertTo-Json -Compress -Depth 3).Length))
}
Check 'Giao diện' {
  $page = Invoke-WebRequest $Frontend -UseBasicParsing -TimeoutSec 10
  if ($page.StatusCode -ne 200) { throw "HTTP $($page.StatusCode)" }
  "HTTP 200 tại $Frontend"
}
Check 'API phân tích yêu cầu đăng nhập' {
  try { Invoke-RestMethod "$Backend/api/studio/security/controls" -TimeoutSec 10 | Out-Null; throw 'API trả dữ liệu khi chưa đăng nhập' }
  catch [System.Net.WebException] { if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw "mong đợi 401, nhận $($_.Exception.Response.StatusCode.value__)" } }
  catch { if ($_.Exception.Message -like '*401*') { return '401 khi chưa đăng nhập (đúng)' } else { throw } }
  '401 khi chưa đăng nhập (đúng)'
}

Write-Host ''
if ($failed) { Write-Host "$failed mục lỗi. Xem docs/HUONG_DAN_CHAY_DU_AN.md mục Xử lý sự cố." -ForegroundColor Red; exit 1 }
Write-Host 'Tất cả đạt. Hệ thống sẵn sàng.' -ForegroundColor Green
