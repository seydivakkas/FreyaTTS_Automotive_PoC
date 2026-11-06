Set-Location (Split-Path $PSScriptRoot -Parent)
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
ollama list
& .venv/Scripts/python -c "import torch; print('Torch',torch.__version__,'CUDA',torch.cuda.is_available())"
try { Invoke-RestMethod 'http://127.0.0.1:8000/api/health' } catch { Write-Host 'Backend çalışmıyor' }
