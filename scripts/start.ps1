$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& "$PSScriptRoot/ensure_ollama.ps1"
& .venv/Scripts/python -m alembic upgrade head
if ($LASTEXITCODE) { throw 'Migration başarısız' }
& .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
