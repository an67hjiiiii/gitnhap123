$ErrorActionPreference = 'SilentlyContinue'
foreach ($pid in @($env:CAP1_BACKEND_PID,$env:CAP1_FRONTEND_PID)) { if ($pid) { Stop-Process -Id ([int]$pid) -Force } }

