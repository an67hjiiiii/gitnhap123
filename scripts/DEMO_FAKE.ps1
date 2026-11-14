$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv/Scripts/python.exe'
$demoData = Join-Path ([IO.Path]::GetTempPath()) 'cap1-ai-fake-demo'

if (-not (Test-Path $python)) {
    Push-Location $backend
    try { python -m venv .venv } finally { Pop-Location }
}
Push-Location $backend
try {
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network access or use a prepared venv.' }
} finally { Pop-Location }

$env:PROVIDER = 'fake'
$env:REVIEW_ENGINE = 'fake'
$env:APP_ENV = 'test'
$env:APP_STORAGE_BACKEND = 'file'
$env:VECTOR_BACKEND = 'disabled'
$env:APP_DATA_DIR = Join-Path $demoData 'data'
$env:RUNS_DIR = Join-Path $demoData 'runs'
$env:SESSION_COOKIE_SECURE = 'false'
New-Item -ItemType Directory -Force -Path $env:APP_DATA_DIR, $env:RUNS_DIR | Out-Null

$port = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $port) {
    Start-Process -FilePath $python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $backend
}
$base = 'http://127.0.0.1:8000'
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-RestMethod "$base/api/health" | Out-Null; $ready = $true; break }
    catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { throw 'Backend did not become ready at http://127.0.0.1:8000.' }

$email = 'demo@example.test'
$password = 'demo-pass-123'
try {
    Invoke-RestMethod -Method Post -Uri "$base/api/auth/register" -ContentType 'application/json' -Body (@{email=$email;password=$password;display_name='Demo User'} | ConvertTo-Json) | Out-Null
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw }
}
$login = Invoke-RestMethod -Method Post -Uri "$base/api/auth/login" -ContentType 'application/json' -Body (@{identifier=$email;password=$password} | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($login.access_token)" }
$existing = (Invoke-RestMethod -Uri "$base/api/sources" -Headers $headers).sources | ForEach-Object { $_.source_name }
Get-ChildItem (Join-Path $root 'demo/sample_docs') -File | ForEach-Object {
    if ($existing -notcontains $_.Name) {
        curl.exe -sS -f -H "Authorization: Bearer $($login.access_token)" -F "file=@$($_.FullName)" "$base/api/sources/file" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Upload failed: $($_.Name)" }
    }
}
$sources = (Invoke-RestMethod -Uri "$base/api/sources" -Headers $headers).sources
$sampleSource = $sources | Select-Object -First 1
if (-not $sampleSource) { throw 'No sample sources are available.' }

Write-Host "Backend: $base"
Write-Host "Open UI: $base/"
Write-Host "Demo data directory: $demoData"
Write-Host "Demo account: $email / $password"
Write-Host 'Fake provider output is deterministic demo behavior, not real model output.'
Write-Host '5-step curl walkthrough (PowerShell; paste lines in order):'
Write-Host "`$base='$base'; `$login=curl.exe -sS -X POST `$base/api/auth/login -H 'Content-Type: application/json' -d '{`"identifier`":`"$email`",`"password`":`"$password`"}' | ConvertFrom-Json; `$token=`$login.access_token"
Write-Host "1. Upload: curl.exe -sS -F 'file=@demo/sample_docs/requirements_vi.txt' -H 'Authorization: Bearer `$token' `$base/api/sources/file"
Write-Host "2. Create case: `$case=(Invoke-RestMethod -Method Post `"`$base/api/review/cases`" -Headers @{Authorization=`"Bearer `$token`"} -ContentType 'application/json' -Body (@{title='Demo review';request_text='Review the uploaded requirements';source_ids=@('$($sampleSource.source_id)')} | ConvertTo-Json)).id"
Write-Host '3. Confirm requirements with PUT /api/review/cases/{case_id}/requirements, then POST /api/review/cases/{case_id}/runs.'
Write-Host '4. Events: curl.exe -N -H "Authorization: Bearer $token" "$base/api/review/runs/{job_id}/events"'
Write-Host '5. Export: curl.exe -H "Authorization: Bearer $token" "$base/api/review/cases/{case_id}/export?format=md"'
