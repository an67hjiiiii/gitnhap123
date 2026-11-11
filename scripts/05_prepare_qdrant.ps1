$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$q = Join-Path $root 'data/qdrant'
if (-not (Test-Path $q)) { New-Item -ItemType Directory -Force $q | Out-Null }
Write-Host "Using packaged embedded Qdrant path: $q"
Write-Host 'PostgreSQL remains authoritative; Qdrant is derived/rebuildable.'

