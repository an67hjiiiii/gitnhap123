# Bật Ollama (nếu chưa chạy) và bảo đảm có 2 mô hình dự án cần: qwen3:4b (sinh) và nomic-embed-text (embedding).
$ErrorActionPreference = 'Stop'
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw 'Chưa cài Ollama (https://ollama.com/download) hoặc ollama chưa có trong PATH.' }
function Test-Ollama { try { Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null; $true } catch { $false } }

$proc = $null
if (Test-Ollama) { Write-Host 'Ollama đã chạy sẵn ở 127.0.0.1:11434.' }
else {
  $env:OLLAMA_HOST = '127.0.0.1:11434'
  if (-not $env:OLLAMA_CONTEXT_LENGTH) { $env:OLLAMA_CONTEXT_LENGTH = '4096' }
  $proc = Start-Process ollama -ArgumentList 'serve' -NoNewWindow -PassThru
  for ($i = 0; $i -lt 30 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 1 }
  if (-not (Test-Ollama)) { throw 'Ollama không khởi động được.' }
}
$have = (ollama list) -join "`n"
foreach ($m in 'qwen3:4b', 'nomic-embed-text') {
  if ($have -notmatch [regex]::Escape($m)) { Write-Host "Đang tải mô hình $m (chỉ lần đầu)..."; ollama pull $m }
}
Write-Host 'Ollama sẵn sàng: qwen3:4b, nomic-embed-text.'
# Giữ terminal mở khi chính task này bật Ollama, để đóng terminal là tắt Ollama.
if ($proc) { Wait-Process -Id $proc.Id }
