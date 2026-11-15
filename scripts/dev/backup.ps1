# Sao lưu toàn bộ dữ liệu của OrchestrIQ Studio vào backups/OrchestrIQ-backup-<thời điểm>.zip:
#   - db.dump : cơ sở dữ liệu PostgreSQL (tài khoản, tài liệu, lượt hỏi, báo cáo, đợt chấm...), định dạng pg_dump -Fc
#   - qdrant/ : chỉ mục vector (data/qdrant)
#   - manifest.json : thời điểm, commit mã nguồn, phiên bản bảng (alembic) để biết bản sao lưu thuộc bản phần mềm nào
# Sao lưu đủ thì backend phải tắt trước (Qdrant chỉ cho một tiến trình mở thư mục chỉ mục).
# -DatabaseOnly: chỉ sao lưu CSDL, làm được khi backend đang chạy (pg_dump chụp nhất quán), hợp cho sao lưu định kỳ.
# Không in mật khẩu hay nội dung CSDL.
# Bản máy chủ Docker (docker-compose.server.yml): -Container orchestriq-postgres-1 -Database orchestriq -User orchestriq -BackendPort 0 -DatabaseOnly
# Dùng: powershell -ExecutionPolicy Bypass -File scripts/dev/backup.ps1 [-Out <thư mục>] [-DatabaseOnly]
param([string]$Out, [switch]$DatabaseOnly,
  [string]$Container = 'cap1-ai-midterm-postgres', [string]$Database = 'cap1_ai_midterm_multilingual', [string]$User = 'cap1_ai',
  [int]$BackendPort = 8000)  # 0: không kiểm tra backend trên máy này
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot/_common.ps1"
$root = $script:Root
$container = $Container; $db = $Database; $user = $User

if (-not $DatabaseOnly -and $BackendPort -and (Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)) {
  Write-Host 'Backend đang chạy. Tắt trước (nhấp đúp TAT_ORCHESTRIQ.cmd) rồi sao lưu lại, hoặc thêm -DatabaseOnly để chỉ sao lưu CSDL.' -ForegroundColor Yellow
  exit 1
}
# container CSDL của bản máy tính thì tự bật; container khác (máy chủ, thử nghiệm) phải đang chạy sẵn
if ($Container -eq 'cap1-ai-midterm-postgres') { [void](Start-ProjectPostgres) }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $Out) { $Out = Join-Path $root 'backups' }
New-Item -ItemType Directory -Force $Out | Out-Null
$work = Join-Path $Out ("OrchestrIQ-backup-$stamp" + $(if ($DatabaseOnly) { '-csdl' } else { '' }))
New-Item -ItemType Directory -Force $work | Out-Null
try {
  Write-Host '1/3 Xuất cơ sở dữ liệu...'
  # ghi trong container rồi chép ra: đường ống stdout của PowerShell 5.1 làm hỏng dữ liệu nhị phân
  cmd /c "docker exec $container pg_dump -U $user -d $db -Fc -f /tmp/orchestriq.dump 2>&1" | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'pg_dump thất bại.' }
  cmd /c "docker cp ${container}:/tmp/orchestriq.dump `"$work\db.dump`" 2>&1" | Out-Null
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$work\db.dump")) { throw 'Không chép được tệp CSDL ra khỏi container.' }
  cmd /c "docker exec $container rm -f /tmp/orchestriq.dump" | Out-Null
  $rev = (cmd /c "docker exec $container psql -U $user -d $db -tAc `"select version_num from alembic_version`" 2>nul") | Select-Object -First 1

  Write-Host '2/3 Chép chỉ mục vector...'
  $qd = if ($env:VECTOR_INDEX_PATH) { $env:VECTOR_INDEX_PATH } else { Join-Path $root 'data/qdrant' }
  if (-not $DatabaseOnly -and (Test-Path $qd)) { Copy-Item $qd (Join-Path $work 'qdrant') -Recurse -Exclude '.lock' }

  [ordered]@{
    created_at = (Get-Date).ToString('o')
    commit = (git -C $root rev-parse --short HEAD 2>$null)
    alembic_revision = "$rev".Trim()
    database_bytes = (Get-Item "$work\db.dump").Length
    has_vector_index = (Test-Path (Join-Path $work 'qdrant'))
  } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $work 'manifest.json')

  Write-Host '3/3 Nén...'
  $zip = "$work.zip"
  Compress-Archive -Path (Join-Path $work '*') -DestinationPath $zip
  $hash = (Get-FileHash $zip -Algorithm SHA256).Hash
  "$hash  $(Split-Path $zip -Leaf)" | Set-Content -Encoding ASCII "$zip.sha256"
  Write-Host "Đã sao lưu: $zip" -ForegroundColor Green
} finally {
  if (Test-Path $work) { Remove-Item $work -Recurse -Force }
}
