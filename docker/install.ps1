# Bộ cài OrchestrIQ Studio cho máy chủ Windows có Docker Desktop (đợt 10): kiểm tra phần cứng, tạo docker/.env, bật hệ thống, tải mô hình.
# Dùng (PowerShell, trong thư mục gốc dự án):
#   powershell -ExecutionPolicy Bypass -File docker/install.ps1            # cài
#   powershell -ExecutionPolicy Bypass -File docker/install.ps1 -DryRun    # chỉ kiểm tra, không đổi gì
# Không tải phần mềm nào ngoài ảnh Docker của dự án (postgres, ollama) và mô hình Ollama; Docker Desktop phải cài sẵn.
# -Project: tên dự án Docker (mặc định orchestriq); chạy thử bên cạnh bản thật thì đặt tên khác và cổng khác.
param([switch]$DryRun, [switch]$OllamaInDocker, [int]$WebPort = 8080, [string]$Project = 'orchestriq')
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

Step '1/5 Kiểm tra Docker'
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) { throw 'Chưa có Docker. Cài Docker Desktop (https://www.docker.com/products/docker-desktop) rồi chạy lại.' }
docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker chưa chạy. Mở Docker Desktop rồi chạy lại.' }
Write-Host 'Docker sẵn sàng.'

Step '2/5 Kiểm tra phần cứng và gợi ý mô hình'
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
$vramGb = 0
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) { $vramGb = [math]::Round(((& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits) | Measure-Object -Sum).Sum / 1024) }
Write-Host "RAM: $ramGb GB · CPU: $cpu luồng · GPU NVIDIA: $(if ($vramGb) { "$vramGb GB VRAM" } else { 'không có' })"
# Gợi ý thận trọng: mô hình mặc định đã được kiểm thử là qwen3:4b; mô hình lớn hơn chỉ gợi ý khi đủ VRAM và người cài đồng ý.
$model = 'qwen3:4b'
if ($ramGb -lt 8) { Write-Warning 'RAM dưới 8 GB: qwen3:4b sẽ chậm, nên dùng máy từ 16 GB RAM.' }
if ($vramGb -ge 12) {
  Write-Host 'Máy có GPU từ 12 GB VRAM: có thể dùng qwen3:8b (trả lời tốt hơn, chưa được nhóm kiểm thử như qwen3:4b).'
  if (-not $DryRun -and (Read-Host 'Dùng qwen3:8b? (c/K)') -match '^[cC]') { $model = 'qwen3:8b' }
}
Write-Host "Mô hình sẽ dùng: $model"

Step '3/5 Tạo cấu hình docker/.env'
$envFile = Join-Path $here '.env'
if (Test-Path $envFile) { Write-Host 'Đã có docker/.env, giữ nguyên.' }
elseif ($DryRun) { Write-Host '(thử) Sẽ tạo docker/.env với mật khẩu CSDL ngẫu nhiên.' }
else {
  $chars = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  $bytes = New-Object byte[] 24  # ngẫu nhiên mật mã, chạy được cả Windows PowerShell 5.1
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $pw = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
  $ollama = if ($OllamaInDocker) { 'http://ollama:11434' } else { 'http://host.docker.internal:11434' }
  @("POSTGRES_PASSWORD=$pw", "WEB_PORT=$WebPort", "OLLAMA_BASE_URL=$ollama", 'COOKIE_SECURE=false', "LOCAL_LLM_MODEL=$model") | Set-Content -Encoding utf8 $envFile
  Write-Host 'Đã tạo docker/.env (mật khẩu CSDL ngẫu nhiên, không in ra màn hình).'
}

Step '4/5 Bật hệ thống'
$compose = @('compose', '-p', $Project, '-f', (Join-Path $here 'docker-compose.server.yml')) + $(if ($OllamaInDocker) { @('--profile', 'ollama') } else { @() })
if ($DryRun) { Write-Host "(thử) docker $($compose -join ' ') up -d --build" }
else { & docker @compose up -d --build; if ($LASTEXITCODE -ne 0) { throw 'docker compose up thất bại.' } }

Step '5/5 Tải mô hình và chờ sẵn sàng'
$pull = { param($m) if ($OllamaInDocker) { & docker @compose exec -T ollama ollama pull $m } else { & ollama pull $m } }
if ($DryRun) { Write-Host "(thử) ollama pull $model ; ollama pull nomic-embed-text" }
else {
  if (-not $OllamaInDocker -and -not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw 'Chưa có Ollama trên máy chủ. Cài Ollama hoặc chạy lại với -OllamaInDocker.' }
  & $pull $model; & $pull 'nomic-embed-text'
  $url = "http://localhost:$WebPort"
  foreach ($i in 1..60) { try { if ((Invoke-WebRequest "$url/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { break } } catch { Start-Sleep 3 } }
  Write-Host "Xong. Mở $url ; tạo tài khoản đầu tiên rồi cấp quyền quản trị bằng scripts/dev/make-admin.ps1 <email>." -ForegroundColor Green
}
