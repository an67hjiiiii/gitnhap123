<#
  RUN_WEB.ps1 - MOT LENH bat toan bo stack nhu nhom chay that: Docker (PostgreSQL) + Ollama + Backend + Frontend.
    powershell -ExecutionPolicy Bypass -File scripts\RUN_WEB.ps1 [-AdminEmail email] [-Fake]
  Goi lai scripts\dev\* cua nhom (start-ollama, start-backend gom docker compose + alembic, start-frontend, make-admin).
  Docker Desktop: script tu mo neu chua chay (nen mo truoc cho nhanh). Bien moi truong chi dat trong tien trinh nay.
  Mac dinh dung mo hinh that qwen3:4b-instruct-2507 (-Fake: provider gia). Ctrl+C dung Backend va Frontend
  (PostgreSQL va Ollama van chay; du lieu khong bi xoa).
#>
param(
    [string]$AdminEmail = 'demo@example.test',
    [string]$AdminPassword = 'demo-pass-123',
    [string]$Model = 'qwen3:4b-instruct-2507-q4_K_M',
    [switch]$Fake,
    [switch]$SkipSeed
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dev = Join-Path $root 'scripts\dev'
. (Join-Path $dev '_common.ps1')
$ErrorActionPreference = 'Stop'
$logs = Join-Path $root 'runtime-logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$base = 'http://127.0.0.1:8000'; $fe = 'http://127.0.0.1:5173'
$sw = [Diagnostics.Stopwatch]::StartNew()
function Step($m) { Write-Host ("[{0,5:N0}s] {1}" -f $sw.Elapsed.TotalSeconds, $m) }
function Stop-Tree([int]$ProcessId) { if ($ProcessId) { & taskkill.exe /T /F /PID $ProcessId 2>$null | Out-Null } }

foreach ($port in 8000, 5173) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Cong $port dang bi chiem. Dong chuong trinh dang dung cong do (vd Backend/Frontend cu) roi chay lai."
    }
}
if (-not (Test-Path (Join-Path $root 'backend\.venv\Scripts\python.exe'))) { throw 'Chua co backend\.venv. Chay scripts\dev\setup.ps1 truoc.' }
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Step 'Cai thu vien frontend (npm ci, lan dau)'
    Push-Location (Join-Path $root 'frontend'); try { npm.cmd ci --no-audit --no-fund } finally { Pop-Location }
}

$procs = @()
try {
    if (-not $Fake) {
        Step 'Bat Ollama (scripts\dev\start-ollama.ps1)'
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dev 'start-ollama.ps1') -NoWait
        if ($LASTEXITCODE -ne 0) { throw 'Ollama khong san sang. Cai/mo Ollama roi chay lai (hoac dung -Fake, khi do tra loi KHONG phai tu mo hinh that).' }
        $env:PROVIDER = 'ollama'; $env:LOCAL_LLM_MODEL = $Model
    } else {
        $env:PROVIDER = 'fake'; $env:APP_ENV = 'test'; $env:REVIEW_ENGINE = 'fake'
    }
    $env:REVIEW_RATE_RUNS_PER_MIN = '30'; $env:REVIEW_RATE_READS_PER_MIN = '600'; $env:REVIEW_RATE_STATUS_PER_MIN = '1200'
    $env:PYTHONIOENCODING = 'utf-8'
    # Cung project Docker Compose voi may Owner (thu muc worktree khac ten se tao project khac, tro nham container/volume cu).
    $env:COMPOSE_PROJECT_NAME = 'cap1_ai_studio_c1se27'

    Step 'Bat Backend (Docker PostgreSQL + alembic upgrade head + uvicorn)'
    $be = Start-Process powershell -PassThru -WindowStyle Hidden -WorkingDirectory $root `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $dev 'start-backend.ps1')) `
        -RedirectStandardOutput (Join-Path $logs 'backend.out.log') -RedirectStandardError (Join-Path $logs 'backend.err.log')
    $procs += $be
    $ready = $false
    for ($i = 0; $i -lt 240 -and -not $be.HasExited; $i++) {
        try { Invoke-RestMethod "$base/api/ready" -TimeoutSec 3 | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw "Backend khong len duoc. Xem $logs\backend.err.log va backend.out.log" }
    Step 'Backend san sang (/api/ready)'

    Step 'Bat Frontend (scripts\dev\start-frontend.ps1)'
    $fp = Start-Process powershell -PassThru -WindowStyle Hidden -WorkingDirectory $root `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $dev 'start-frontend.ps1')) `
        -RedirectStandardOutput (Join-Path $logs 'frontend.out.log') -RedirectStandardError (Join-Path $logs 'frontend.err.log')
    $procs += $fp
    $up = $false
    for ($i = 0; $i -lt 90 -and -not $fp.HasExited; $i++) {
        try { Invoke-WebRequest "$fe/" -UseBasicParsing -TimeoutSec 3 | Out-Null; $up = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $up) { throw "Frontend khong len duoc. Xem $logs\frontend.err.log" }
    Step 'Frontend san sang'

    if (-not $SkipSeed) {
        Step 'Seed: tai khoan ADMIN, 2 tai lieu mau, 1 case review'
        $jar = Join-Path $logs 'cookies.txt'; $tmp = Join-Path $logs 'req.json'
        function Send-Json($Method, $Path, $Object) {
            [IO.File]::WriteAllText($tmp, ($Object | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding $false))
            $out = & curl.exe -sS -b $jar -c $jar -X $Method -H 'Content-Type: application/json' --data-binary "@$tmp" "$base$Path" -w "`n%{http_code}"
            $lines = @($out -split "`n")
            [pscustomobject]@{ Code = [int]$lines[-1].Trim(); Body = (($lines[0..($lines.Count - 2)]) -join "`n") }
        }
        Send-Json 'POST' '/api/auth/register' @{ email = $AdminEmail; password = $AdminPassword; display_name = 'Demo' } | Out-Null
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dev 'make-admin.ps1') -Email $AdminEmail
        $login = Send-Json 'POST' '/api/auth/login' @{ identifier = $AdminEmail; password = $AdminPassword }
        if ($login.Code -ne 200) { Write-Host "Khong dang nhap duoc $AdminEmail (khac mat khau -AdminPassword?); bo qua seed tai lieu." }
        else {
            $existing = (& curl.exe -sS -b $jar "$base/api/sources" | ConvertFrom-Json).sources
            $ids = @(); if ($existing) { $ids = @($existing | ForEach-Object { $_.source_id }) }
            if ($ids.Count -lt 2) {
                foreach ($doc in Get-ChildItem (Join-Path $root 'demo\sample_docs') -File) {
                    $upl = & curl.exe -sS -b $jar -c $jar -F "file=@$($doc.FullName)" "$base/api/sources/file" | ConvertFrom-Json
                    if ($upl.source_id) { $ids += $upl.source_id }
                }
            }
            $cases = Send-Json 'GET' '/api/review/cases' @{}
            if ($ids.Count -gt 0 -and $cases.Code -eq 200 -and @($cases.Body | ConvertFrom-Json).Count -eq 0) {
                $case = Send-Json 'POST' '/api/review/cases' @{ title = 'Demo: kiem tra chinh sach'; source_ids = @($ids[0])
                    request_text = 'Mat khau phai co it nhat 12 ky tu. Tai khoan bi khoa sau 5 lan dang nhap sai. Phien het han sau 30 phut khong hoat dong.' }
                if ($case.Code -eq 201) {
                    $cid = ($case.Body | ConvertFrom-Json).id
                    $prop = Send-Json 'POST' "/api/review/cases/$cid/requirements:propose" @{}
                    if ($prop.Code -eq 200) {
                        $items = @(($prop.Body | ConvertFrom-Json) | ForEach-Object { @{ id = $_.id; text = $_.text; confirmed = $true } })
                        Send-Json 'PUT' "/api/review/cases/$cid/requirements" @{ requirements = $items } | Out-Null
                    }
                }
            }
        }
    }

    Write-Host ''
    Step "Xong. Che do: $(if ($Fake) { 'FAKE (khong phai mo hinh that)' } else { "Ollama $Model" })"
    Write-Host "Frontend : $fe/"
    Write-Host "Backend  : $base/   Tai lieu API: $base/docs"
    Write-Host "Tai khoan: $AdminEmail / $AdminPassword  (ADMIN; dang xuat roi dang nhap lai de thay trang Co so du lieu)"
    Write-Host "Log      : $logs"
    Write-Host 'Nhan Ctrl+C de dung Backend va Frontend.'
    while (-not $be.HasExited -and -not $fp.HasExited) { Start-Sleep -Seconds 2 }
    Write-Host 'Mot may chu da dung; xem log.'
}
finally {
    foreach ($p in $procs) { Stop-Tree $p.Id }
}
