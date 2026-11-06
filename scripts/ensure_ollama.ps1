$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$endpoint=$env:OLLAMA_URL
if (!$endpoint -and (Test-Path '.env')) {
  $line=Get-Content '.env' | Where-Object { $_ -match '^OLLAMA_URL=' } | Select-Object -First 1
  if ($line) { $endpoint=$line.Substring(11).Trim() }
}
if (!$endpoint) { $endpoint='http://127.0.0.1:11434' }
try { $null=Invoke-RestMethod ($endpoint+'/api/tags') -TimeoutSec 2; return } catch {}
$uri=[Uri]$endpoint
if ($uri.Host -notin @('localhost','127.0.0.1','::1') -or $uri.Port -ne 11434) { throw 'Yapılandırılmış Ollama adresi erişilemiyor; otomatik başlatma yalnızca yerel 11434 portunda desteklenir.' }
$executable=(Get-Command ollama -ErrorAction Stop).Source
$env:OLLAMA_NO_CLOUD='1'
$null=Start-Process -FilePath $executable -ArgumentList 'serve' -WindowStyle Hidden -PassThru
for ($attempt=0;$attempt -lt 20;$attempt++) {
  Start-Sleep -Milliseconds 500
  try { $null=Invoke-RestMethod ($endpoint+'/api/tags') -TimeoutSec 1; Write-Host 'Yerel Ollama hazır.'; return } catch {}
}
throw 'Ollama başlatıldı ancak hazır duruma gelmedi.'
