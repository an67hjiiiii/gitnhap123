$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'CHECK_PREREQUISITES.ps1')
docker compose -f (Join-Path $root 'docker/docker-compose.yml') up -d postgres
& (Join-Path $PSScriptRoot 'SETUP_BACKEND.ps1')
& (Join-Path $PSScriptRoot 'SETUP_FRONTEND.ps1')
Write-Host 'Set DATABASE_URL, then run 04_restore_postgres.ps1 if the database is empty.'
