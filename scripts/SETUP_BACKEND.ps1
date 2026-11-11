$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root/backend"
if (-not (Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
& .venv/Scripts/python.exe -m pip install -r requirements.txt
Pop-Location

