$ErrorActionPreference = 'Stop'
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw 'Ollama is missing from PATH.' }
try { Invoke-RestMethod http://127.0.0.1:11434/api/tags | Out-Null } catch { Start-Process ollama -ArgumentList 'serve' -WindowStyle Hidden; Start-Sleep -Seconds 3 }
ollama list
if (-not (ollama list | Select-String 'qwen3:4b')) { ollama pull qwen3:4b }

