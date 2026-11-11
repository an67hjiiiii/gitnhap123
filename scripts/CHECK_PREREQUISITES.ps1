$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Write-Host "CAP1 root: $root"
foreach ($cmd in @('python','npm','docker','ollama')) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Write-Error "Missing prerequisite: $cmd" }
  else { Write-Host "$cmd: OK" }
}
docker version
Write-Host 'Prerequisites OK'

