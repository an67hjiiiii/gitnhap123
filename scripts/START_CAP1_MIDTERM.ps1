$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $env:DATABASE_URL) { throw 'Set DATABASE_URL before starting.' }
& "$PSScriptRoot/06_check_ollama.ps1"
$env:APP_STORAGE_BACKEND='postgres'; $env:VECTOR_BACKEND='qdrant'; $env:VECTOR_INDEX_PATH=(Join-Path $root 'data/qdrant')
$env:PROVIDER='ollama'; $env:LOCAL_LLM_MODEL='qwen3:4b'; $env:IMPLEMENTATION_PROFILE='m1'; $env:PRODUCT_CONDITION='C'; $env:MAX_OUTPUT_TOKENS='700'; $env:TASK_PLAN_MAX_OUTPUT_TOKENS='1400'
$backend = Start-Process python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory (Join-Path $root 'backend') -PassThru
$frontend = Start-Process npm.cmd -ArgumentList 'run','dev','--','--host','127.0.0.1','--port','5176' -WorkingDirectory (Join-Path $root 'frontend') -PassThru
@{backend_pid=$backend.Id;frontend_pid=$frontend.Id;backend_url='http://127.0.0.1:8000';frontend_url='http://127.0.0.1:5176';task_plan_max_output_tokens=1400} | ConvertTo-Json

