$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $env:DATABASE_URL) { throw 'Set DATABASE_URL to the target database before restore.' }
$dump = Join-Path $root 'data/postgres/cap1_midterm_sanitized.dump'
if (-not (Test-Path $dump)) { throw "Missing dump: $dump" }
pg_restore --clean --if-exists --no-owner --dbname $env:DATABASE_URL $dump
Push-Location "$root/backend"
alembic upgrade head
Pop-Location

