$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$health = Invoke-RestMethod http://127.0.0.1:8000/api/health
if (-not $health.ok -or $health.storage_backend -ne 'postgres') { throw 'Backend health/storage check failed.' }
$model = Invoke-RestMethod http://127.0.0.1:8000/api/local-model/health
if (-not $model.ok) { throw 'Ollama health check failed.' }
if (-not (Test-Path (Join-Path $root 'data/qdrant'))) { throw 'Qdrant path missing.' }
Write-Host 'CAP1 Midterm runtime verified.'
$health | ConvertTo-Json

