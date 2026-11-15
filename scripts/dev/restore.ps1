# Khôi phục dữ liệu OrchestrIQ Studio từ một tệp sao lưu do backup.ps1 tạo.
# An toàn: trước khi ghi đè, tự sao lưu dữ liệu hiện tại; chỉ mục vector cũ được đổi tên (data/qdrant.truoc-khoi-phuc-<thời điểm>), không xóa.
# Backend phải tắt trước. Sau khi khôi phục, lần chạy backend kế tiếp tự cập nhật bảng (alembic upgrade head) nếu bản sao lưu cũ hơn mã.
# Dùng: powershell -ExecutionPolicy Bypass -File scripts/dev/restore.ps1 -From backups/OrchestrIQ-backup-....zip [-Yes]
# -DatabaseOnly: chỉ khôi phục CSDL (bản máy chủ Docker: thêm -Container orchestriq-postgres-1 -Database orchestriq -User orchestriq -BackendPort 0).
param([Parameter(Mandatory = $true)][string]$From, [switch]$Yes, [switch]$DatabaseOnly,
  [string]$Container = 'cap1-ai-midterm-postgres', [string]$Database = 'cap1_ai_midterm_multilingual', [string]$User = 'cap1_ai',
  [int]$BackendPort = 8000)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot/_common.ps1"
$root = $script:Root
$container = $Container; $db = $Database; $user = $User

if (-not (Test-Path $From)) { throw "Không thấy tệp sao lưu: $From" }
if ($BackendPort -and (Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)) {
  Write-Host 'Backend đang chạy. Tắt trước (nhấp đúp TAT_ORCHESTRIQ.cmd) rồi khôi phục lại.' -ForegroundColor Yellow
  exit 1
}
$sha = "$From.sha256"
if (Test-Path $sha) {
  $want = ((Get-Content $sha -Raw) -split '\s+')[0]
  if ((Get-FileHash $From -Algorithm SHA256).Hash -ne $want) { throw 'Tệp sao lưu không khớp mã SHA-256 (có thể bị hỏng hoặc bị sửa). Dừng lại.' }
}

$work = Join-Path ([IO.Path]::GetTempPath()) ("orchestriq-restore-" + [guid]::NewGuid().ToString('N'))
Expand-Archive $From -DestinationPath $work
try {
  if (-not (Test-Path "$work\db.dump")) { throw 'Tệp sao lưu thiếu db.dump.' }
  $m = Get-Content "$work\manifest.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
  Write-Host "Bản sao lưu: $($m.created_at)  commit $($m.commit)  bảng $($m.alembic_revision)"
  if (-not $Yes) {
    $ans = Read-Host 'Dữ liệu hiện tại sẽ được thay bằng bản sao lưu này (dữ liệu hiện tại được tự sao lưu trước). Gõ CO để tiếp tục'
    if ($ans -ne 'CO') { Write-Host 'Đã hủy, không thay đổi gì.'; exit 0 }
  }

  Write-Host '1/3 Tự sao lưu dữ liệu hiện tại...'
  & "$PSScriptRoot/backup.ps1" -Container $Container -Database $Database -User $User -BackendPort $BackendPort -DatabaseOnly:$DatabaseOnly
  if ($LASTEXITCODE) { throw 'Không sao lưu được dữ liệu hiện tại; dừng để tránh mất dữ liệu.' }

  Write-Host '2/3 Khôi phục cơ sở dữ liệu...'
  cmd /c "docker cp `"$work\db.dump`" ${container}:/tmp/orchestriq.dump 2>&1" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Không chép được tệp CSDL vào container.' }
  # --clean --if-exists: xóa bảng hiện có rồi tạo lại từ bản sao lưu; --single-transaction: lỗi giữa chừng thì không đổi gì
  cmd /c "docker exec $container pg_restore -U $user -d $db --clean --if-exists --no-owner --single-transaction /tmp/orchestriq.dump 2>&1" | Out-Host
  $rc = $LASTEXITCODE
  cmd /c "docker exec $container rm -f /tmp/orchestriq.dump" | Out-Null
  if ($rc -ne 0) { throw 'pg_restore thất bại; CSDL giữ nguyên như trước (giao dịch đã hủy).' }

  Write-Host '3/3 Khôi phục chỉ mục vector...'
  $qd = if ($env:VECTOR_INDEX_PATH) { $env:VECTOR_INDEX_PATH } else { Join-Path $root 'data/qdrant' }
  if (-not $DatabaseOnly -and (Test-Path "$work\qdrant")) {
    if (Test-Path $qd) { Rename-Item $qd ("$(Split-Path $qd -Leaf).truoc-khoi-phuc-" + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
    Copy-Item "$work\qdrant" $qd -Recurse
  }
  Write-Host 'Đã khôi phục. Chạy lại OrchestrIQ (MO_ORCHESTRIQ.cmd) để dùng.' -ForegroundColor Green
} finally {
  Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
