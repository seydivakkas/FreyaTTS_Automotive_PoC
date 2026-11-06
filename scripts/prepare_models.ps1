$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& "$PSScriptRoot/ensure_ollama.ps1"
ollama pull qwen2.5:7b
if ($LASTEXITCODE) { throw 'Ollama modeli indirilemedi' }
& .venv/Scripts/python -c "import asyncio; from backend.models import models; asyncio.run(models.load()); print('Modeller hazır')"
if ($LASTEXITCODE) { throw 'Ses modelleri hazırlanamadı' }
