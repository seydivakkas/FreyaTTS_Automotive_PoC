# Paneli yalnızca örnek veriyle (data/demo) başlatır; işletim verisine erişmez.
# Önce örnek veriyi yüklemek için: .venv\Scripts\python scripts\seed_demo_telemetry.py
$env:DEMO_MODE = '1'
& "$PSScriptRoot/start.ps1"
