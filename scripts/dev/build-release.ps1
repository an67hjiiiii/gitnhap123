# Đóng gói bản phát hành: chạy test, build giao diện, gom mã nguồn cần thiết vào release/<tên>.zip kèm SHA-256.
# Không đóng gói: môi trường ảo, node_modules, dữ liệu người dùng (data/qdrant, CSDL), tệp .env, thư mục cài đặt riêng (.claude, .codex...).
# Dùng: powershell -ExecutionPolicy Bypass -File scripts/dev/build-release.ps1 [-SkipTests]
param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$commit = (git -C $root rev-parse --short HEAD 2>$null)
# còn thay đổi chưa commit thì thêm "-chua-commit": mã commit trong tên không mô tả đúng nội dung gói
$dirty = $commit -and (git -C $root status --porcelain 2>$null)
$name = "OrchestrIQ-Studio-$stamp" + $(if ($commit) { "-$commit" } else { '' }) + $(if ($dirty) { '-chua-commit' } else { '' })
$out = Join-Path $root "release/$name"

if (-not $SkipTests) {
  Write-Host '1/4 Test backend...'
  Push-Location (Join-Path $root 'backend'); & .venv/Scripts/python.exe -m pytest tests -q; $ok = $LASTEXITCODE; Pop-Location
  if ($ok -ne 0) { throw 'Test backend chưa đạt; không đóng gói.' }
}
Write-Host '2/4 Kiểm tra kiểu và build giao diện...'
Push-Location (Join-Path $root 'frontend')
try {
  if (-not (Test-Path node_modules)) { npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci thất bại.' } }
  npx.cmd tsc -b; if ($LASTEXITCODE -ne 0) { throw 'Kiểm tra kiểu TypeScript chưa đạt.' }
  npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Build giao diện thất bại.' }
} finally { Pop-Location }

Write-Host '3/4 Lập danh mục giấy phép và gom tệp...'
& (Join-Path $root 'backend/.venv/Scripts/python.exe') -X utf8 (Join-Path $root 'scripts/dev/licenses.py')
if ($LASTEXITCODE -ne 0) { throw 'Lập danh mục giấy phép thất bại.' }
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force $out | Out-Null
$skipDirs = @('.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache')
function Copy-Tree([string]$rel) {
  $src = Join-Path $root $rel
  if (-not (Test-Path $src)) { return }
  Get-ChildItem $src -Recurse -File -Force | Where-Object {
    $parts = $_.FullName.Substring($root.Length + 1).Split([IO.Path]::DirectorySeparatorChar)
    -not ($parts | Where-Object { $skipDirs -contains $_ }) -and $_.Name -notlike '.env*' -and $_.Extension -notin '.pyc', '.log', '.sqlite', '.db'
  } | ForEach-Object {
    $dest = Join-Path $out $_.FullName.Substring($root.Length + 1)
    New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
    Copy-Item $_.FullName $dest
  }
}
foreach ($rel in 'backend', 'frontend', 'scripts', 'docker', 'MO_ORCHESTRIQ.cmd', 'TAT_ORCHESTRIQ.cmd', 'THIRD_PARTY_LICENSES.md', '.vscode/tasks.json', 'docs/HUONG_DAN_CHAY_DU_AN.md', 'docs/HUONG_DAN_SU_DUNG.md', 'docs/C1SE27_INTEGRATION_VI.md', 'README.md') {
  $src = Join-Path $root $rel
  if (Test-Path $src -PathType Leaf) { $dest = Join-Path $out $rel; New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null; Copy-Item $src $dest } else { Copy-Tree $rel }
}
New-Item -ItemType Directory -Force (Join-Path $out 'data/qdrant') | Out-Null  # chỉ mục trống; dữ liệu khách tự tạo
@"
OrchestrIQ Studio $stamp$(if ($commit) { " (commit $commit$(if ($dirty) { ', có thay đổi chưa commit' }))" })
Cài đặt lần đầu : powershell -ExecutionPolicy Bypass -File scripts/dev/setup.ps1
Chạy hằng ngày  : nhấp đúp MO_ORCHESTRIQ.cmd (tự mở trình duyệt); tắt: TAT_ORCHESTRIQ.cmd. Lập trình viên: VS Code, Ctrl+Shift+B
Kiểm tra nhanh  : powershell -ExecutionPolicy Bypass -File scripts/dev/smoke-test.ps1
Sao lưu dữ liệu : scripts/dev/backup.ps1 (khôi phục: scripts/dev/restore.ps1 -From <tệp zip>)
Máy chủ (Docker): docker/docker-compose.server.yml, xem mục 6 trong docs/HUONG_DAN_CHAY_DU_AN.md
Giấy phép       : THIRD_PARTY_LICENSES.md
Hướng dẫn       : docs/HUONG_DAN_CHAY_DU_AN.md, docs/HUONG_DAN_SU_DUNG.md
"@ | Set-Content -Encoding UTF8 (Join-Path $out 'CAI_DAT.txt')

Write-Host '4/4 Nén và tính SHA-256...'
$zip = "$out.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $out '*') -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
"$hash  $name.zip" | Set-Content -Encoding ASCII "$zip.sha256"
Remove-Item $out -Recurse -Force
Write-Host "Xong: $zip"
Write-Host "SHA-256: $hash"
