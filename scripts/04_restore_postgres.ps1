$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $env:DATABASE_URL) { throw 'Set DATABASE_URL to the target database before restore.' }
$dump = Join-Path $root 'data/postgres/cap1_midterm_sanitized.dump'
if (-not (Test-Path $dump)) { throw "Missing dump: $dump" }
$container = if ($env:CAP1_POSTGRES_CONTAINER) { $env:CAP1_POSTGRES_CONTAINER } else { 'cap1-ai-midterm-postgres' }
$remoteDump = '/tmp/cap1_midterm_sanitized.dump'
& docker cp $dump "${container}:$remoteDump"
if ($LASTEXITCODE -ne 0) { throw 'docker cp of sanitized dump failed.' }
& docker exec $container pg_restore --clean --if-exists --no-owner --dbname 'postgresql://cap1_ai:change-me-locally@127.0.0.1:5432/cap1_ai_midterm_multilingual' $remoteDump
if ($LASTEXITCODE -ne 0) { throw 'pg_restore inside package PostgreSQL container failed.' }
Push-Location "$root/backend"
& .venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Alembic migration failed.' }
Pop-Location

