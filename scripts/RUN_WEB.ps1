<#
  RUN_WEB.ps1 - one command: backend + frontend (Vite dev) + demo data, for manual testing.
    powershell -File scripts\RUN_WEB.ps1            real local model (Ollama, Qwen3-4B Instruct-2507)
    powershell -File scripts\RUN_WEB.ps1 -Fake      fake provider (no Ollama; answers are NOT real model output)
  Environment variables are set for this process tree only. Storage is file based in a temp folder
  (-DataDir), so the Owner PostgreSQL / Qdrant / data folders are never touched. Ctrl+C stops both servers.
  The frontend code is not modified: Vite already proxies /api to $env:API_TARGET.
#>
param(
    [switch]$Fake,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [string]$Python = '',
    [string]$Model = 'qwen3:4b-instruct-2507-q4_K_M',
    [string]$DataDir = '',
    [switch]$SkipSeed,
    [string]$DatabaseUrl = ''   # optional scratch PostgreSQL (enables Studio workspaces/admin); never use the Owner dev DB
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$mode = if ($Fake) { 'fake' } else { 'real' }
if (-not $DataDir) { $DataDir = Join-Path ([IO.Path]::GetTempPath()) "cap1-web-$mode" }
$logs = Join-Path $DataDir 'logs'
New-Item -ItemType Directory -Force -Path $DataDir, $logs | Out-Null

function Test-PortBusy([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}
function Stop-Tree([int]$ProcessId) {
    if ($ProcessId) { & taskkill.exe /T /F /PID $ProcessId 2>$null | Out-Null }
}

# ---- checks -------------------------------------------------------------------------------------
if (-not $Python) {
    foreach ($candidate in @((Join-Path $backend '.venv\Scripts\python.exe'), (Join-Path $root '.venv\Scripts\python.exe'))) {
        if (Test-Path $candidate) { $Python = $candidate; break }
    }
}
if (-not $Python -or -not (Test-Path $Python)) {
    throw "Chua co Python venv cho backend. Chay scripts\SETUP_BACKEND.ps1 hoac truyen -Python <duong dan python.exe> (can cac goi trong backend\requirements.txt)."
}
foreach ($port in @($BackendPort, $FrontendPort)) {
    if (Test-PortBusy $port) { throw "Cong $port dang bi chiem. Dong chuong trinh dang dung cong do hoac doi cong bang -BackendPort/-FrontendPort." }
}
if (-not $Fake) {
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Out-Null }
    catch { throw "Ollama chua chay tai 127.0.0.1:11434. Mo Ollama roi chay lai, hoac dung -Fake de demo bang provider gia." }
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host 'Chua co frontend\node_modules, chay npm ci (can mang, mot lan)...'
    Push-Location $frontend
    try { & npm.cmd ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw 'npm ci that bai' } }
    catch { throw "Khong cai duoc node_modules: $($_.Exception.Message). Can Node 20+ va mang; sau do chay: cd frontend; npm ci" }
    finally { Pop-Location }
}

# ---- backend environment (this process tree only) -------------------------------------------------
$env:APP_STORAGE_BACKEND = 'file'
if ($DatabaseUrl) { $env:APP_STORAGE_BACKEND = 'postgres'; $env:DATABASE_URL = $DatabaseUrl }
$env:VECTOR_BACKEND = 'disabled'
$env:APP_DATA_DIR = Join-Path $DataDir 'data'
$env:RUNS_DIR = Join-Path $DataDir 'runs'
$env:SESSION_COOKIE_SECURE = 'false'
$env:IMPLEMENTATION_PROFILE = 'dev'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHON_DOTENV_DISABLED = '1'
if ($Fake) {
    $env:PROVIDER = 'fake'; $env:APP_ENV = 'test'; $env:REVIEW_ENGINE = 'fake'
} else {
    $env:PROVIDER = 'ollama'; $env:LOCAL_LLM_MODEL = $Model; $env:APP_ENV = 'development'
    Remove-Item Env:\REVIEW_ENGINE -ErrorAction SilentlyContinue
}
$env:REVIEW_RATE_RUNS_PER_MIN = '30'; $env:REVIEW_RATE_READS_PER_MIN = '600'; $env:REVIEW_RATE_STATUS_PER_MIN = '1200'
New-Item -ItemType Directory -Force -Path $env:APP_DATA_DIR, $env:RUNS_DIR | Out-Null
$env:API_TARGET = "http://127.0.0.1:$BackendPort"

$be = $null; $fe = $null
try {
    if ($DatabaseUrl) {
        Push-Location $backend
        try { & $Python -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade head that bai' } } finally { Pop-Location }
    }
    $be = Start-Process -FilePath $Python -PassThru -WindowStyle Hidden -WorkingDirectory $backend `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") `
        -RedirectStandardOutput (Join-Path $logs 'backend.out.log') -RedirectStandardError (Join-Path $logs 'backend.err.log')
    $base = "http://127.0.0.1:$BackendPort"
    $ready = $false
    for ($i = 0; $i -lt 60 -and -not $be.HasExited; $i++) {
        try { Invoke-RestMethod "$base/api/health" -TimeoutSec 3 | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw "Backend khong len duoc. Xem $logs\backend.err.log" }

    $fe = Start-Process -FilePath 'cmd.exe' -PassThru -WindowStyle Hidden -WorkingDirectory $frontend `
        -ArgumentList @('/c', 'npm.cmd', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', "$FrontendPort", '--strictPort') `
        -RedirectStandardOutput (Join-Path $logs 'frontend.out.log') -RedirectStandardError (Join-Path $logs 'frontend.err.log')
    $feUp = $false
    for ($i = 0; $i -lt 60 -and -not $fe.HasExited; $i++) {
        try { Invoke-WebRequest "http://127.0.0.1:$FrontendPort/" -UseBasicParsing -TimeoutSec 3 | Out-Null; $feUp = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $feUp) { throw "Frontend khong len duoc. Xem $logs\frontend.err.log" }

    # ---- seed demo data ---------------------------------------------------------------------------
    $email = 'demo@example.test'; $password = 'demo-pass-123'
    if (-not $SkipSeed) {
        $jar = Join-Path $DataDir 'cookies.txt'
        function Send-Json($Method, $Path, $Object) {
            $file = Join-Path $DataDir 'req.json'
            [IO.File]::WriteAllText($file, ($Object | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding $false))
            $out = & curl.exe -sS -b $jar -c $jar -X $Method -H 'Content-Type: application/json' --data-binary "@$file" "$base$Path" -w "`n%{http_code}"
            $lines = @($out -split "`n"); $code = $lines[-1].Trim()
            return [pscustomobject]@{ Code = [int]$code; Body = (($lines[0..($lines.Count - 2)]) -join "`n") }
        }
        $reg = Send-Json 'POST' '/api/auth/register' @{ email = $email; password = $password; display_name = 'Demo' }
        $login = Send-Json 'POST' '/api/auth/login' @{ identifier = $email; password = $password }
        if ($login.Code -ne 200) { throw "Dang nhap demo that bai ($($login.Code)): $($login.Body)" }
        $sourceIds = @()
        foreach ($doc in Get-ChildItem (Join-Path $root 'demo\sample_docs') -File) {
            $up = & curl.exe -sS -b $jar -c $jar -F "file=@$($doc.FullName)" "$base/api/sources/file" | ConvertFrom-Json
            if ($up.source_id) { $sourceIds += $up.source_id }
        }
        if ($sourceIds.Count -gt 0) {
            $case = Send-Json 'POST' '/api/review/cases' @{
                title = 'Demo: kiem tra chinh sach'; source_ids = @($sourceIds[0])
                request_text = 'Mat khau phai co it nhat 12 ky tu. Tai khoan bi khoa sau 5 lan dang nhap sai. Phien het han sau 30 phut khong hoat dong.'
            }
            if ($case.Code -eq 201) {
                $caseId = ($case.Body | ConvertFrom-Json).id
                $prop = Send-Json 'POST' "/api/review/cases/$caseId/requirements:propose" @{}
                if ($prop.Code -eq 200) {
                    $items = @(($prop.Body | ConvertFrom-Json) | ForEach-Object { @{ id = $_.id; text = $_.text; confirmed = $true } })
                    Send-Json 'PUT' "/api/review/cases/$caseId/requirements" @{ requirements = $items } | Out-Null
                }
            }
        }
    }

    Write-Host ''
    Write-Host "Che do: $mode$(if ($Fake) { ' (provider gia, cau tra loi KHONG phai tu mo hinh that)' } else { " (Ollama, $Model)" })"
    Write-Host "Frontend : http://127.0.0.1:$FrontendPort/"
    Write-Host "Backend  : $base/   (tai lieu API: $base/docs)"
    Write-Host "Tai khoan demo: $email / $password"
    Write-Host "Du lieu  : $DataDir   Log: $logs"
    Write-Host 'Nhan Ctrl+C de dung ca hai.'
    while (-not $be.HasExited -and -not $fe.HasExited) { Start-Sleep -Seconds 2 }
    Write-Host 'Mot trong hai may chu da dung; xem log.'
}
finally {
    if ($fe) { Stop-Tree $fe.Id }
    if ($be) { Stop-Tree $be.Id }
}
