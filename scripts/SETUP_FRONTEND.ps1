$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root/frontend"
npm.cmd ci
Pop-Location

