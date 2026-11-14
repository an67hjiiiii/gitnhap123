# Hàm dùng chung cho các script trong scripts/dev (được nạp bằng dấu chấm: . "$PSScriptRoot/_common.ps1").
$script:Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# PowerShell 5.1 coi mọi dòng chương trình ghi ra stderr (log của docker, alembic, uvicorn) là lỗi dừng hẳn;
# để 'Continue' và tự kiểm tra $LASTEXITCODE.
$ErrorActionPreference = 'Continue'

# .runtime có thể là liên kết (junction) tới thư mục khác; Ollama cần đường dẫn thật mới đọc được mô hình.
function Get-RuntimeDir {
  $rt = Join-Path $script:Root '.runtime'
  if (-not (Test-Path $rt)) { return $null }
  $it = Get-Item $rt -Force
  if ($it.LinkType -and $it.Target) { return @($it.Target)[0] }
  return $rt
}

# Tìm ollama.exe: biến OLLAMA_EXE, PATH, nơi cài mặc định, hoặc bản di động trong .runtime/ollama của dự án.
function Find-Ollama {
  $candidates = @(
    $env:OLLAMA_EXE,
    (Get-Command ollama -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
    (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
    (Join-Path $env:ProgramFiles 'Ollama\ollama.exe'),
    $(if ($rt = Get-RuntimeDir) { Join-Path $rt 'ollama\ollama.exe' })
  )
  foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path } }
  return $null
}

# Bản Ollama di động để mô hình trong .runtime/models; dùng thư mục đó nếu có và chưa đặt OLLAMA_MODELS.
function Set-OllamaModelsDir([string]$exe) {
  $rt = Get-RuntimeDir
  if (-not $rt -or $env:OLLAMA_MODELS) { return }
  $models = Join-Path $rt 'models'
  if ($exe -like (Join-Path $rt '*') -and (Test-Path $models)) { $env:OLLAMA_MODELS = $models }
}

function Test-DockerEngine { cmd /c 'docker info >nul 2>&1'; return ($LASTEXITCODE -eq 0) }

# Docker Desktop chưa chạy thì tự mở và chờ tối đa ~2 phút.
function Start-DockerEngine {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Chưa cài Docker Desktop (https://www.docker.com/products/docker-desktop/).' }
  if (Test-DockerEngine) { return }
  $app = @((Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')) |
    Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $app) { throw 'Docker chưa chạy và không tìm thấy Docker Desktop để mở. Hãy mở Docker Desktop rồi chạy lại.' }
  Write-Host 'Đang mở Docker Desktop, chờ khởi động (có thể mất 1-2 phút)...'
  Start-Process $app
  for ($i = 0; $i -lt 120; $i++) { Start-Sleep -Seconds 1; if (Test-DockerEngine) { Write-Host 'Docker đã sẵn sàng.'; return } }
  throw 'Docker Desktop chưa sẵn sàng sau 2 phút. Đợi Docker Desktop báo "Engine running" rồi chạy lại.'
}

# Cổng PostgreSQL trên máy: mặc định 55435. Windows (Hyper-V/WSL) đôi khi giữ chỗ cả dải cổng chứa 55435
# (xem: netsh interface ipv4 show excludedportrange protocol=tcp); khi đó tự chọn cổng khác còn dùng được.
function Test-PortReserved([int]$port) {
  foreach ($line in (netsh interface ipv4 show excludedportrange protocol=tcp)) {
    if ($line -match '^\s*(\d+)\s+(\d+)') { if ($port -ge [int]$Matches[1] -and $port -le [int]$Matches[2]) { return $true } }
  }
  return $false
}
function Get-PgPort {
  if ($env:CAP1_PG_PORT) { return [int]$env:CAP1_PG_PORT }
  # Container đã chạy thì dùng đúng cổng nó đang mở.
  $mapped = (cmd /c 'docker port cap1-ai-midterm-postgres 5432/tcp 2>nul') | Select-Object -First 1
  if ($mapped -match ':(\d+)\s*$') { return [int]$Matches[1] }
  foreach ($p in 55435, 54329, 5433, 15432, 25432) {
    $busy = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if (-not (Test-PortReserved $p) -and -not $busy) { return $p }
  }
  throw 'Không tìm được cổng trống cho PostgreSQL. Đặt biến CAP1_PG_PORT rồi chạy lại.'
}
function Get-DefaultDatabaseUrl([int]$port) { "postgresql+psycopg://cap1_ai:change-me-locally@127.0.0.1:$port/cap1_ai_midterm_multilingual" }

# Bật container PostgreSQL của dự án và chờ nhận kết nối. Trả về cổng đang dùng.
function Start-ProjectPostgres {
  Start-DockerEngine
  $port = Get-PgPort
  if ($port -ne 55435) { Write-Host "Cổng 55435 bị Windows chặn, PostgreSQL dùng cổng $port." }
  $env:CAP1_PG_PORT = "$port"
  $compose = Join-Path $script:Root 'docker/docker-compose.yml'
  # Chạy qua cmd để dòng tiến trình của docker (ghi ra stderr) không bị PowerShell tô đỏ như lỗi; Out-Host để không lẫn vào giá trị trả về.
  cmd /c "docker compose -f `"$compose`" up -d postgres 2>&1" | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'Không bật được PostgreSQL (docker compose up thất bại).' }
  Write-Host 'Chờ PostgreSQL sẵn sàng...'
  for ($i = 0; $i -lt 60; $i++) { cmd /c 'docker exec cap1-ai-midterm-postgres pg_isready -q >nul 2>&1'; if ($LASTEXITCODE -eq 0) { return $port }; Start-Sleep -Seconds 1 }
  throw 'PostgreSQL chưa sẵn sàng sau 60 giây.'
}
