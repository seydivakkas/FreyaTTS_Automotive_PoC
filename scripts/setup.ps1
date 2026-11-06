$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
uv sync --frozen --extra models --extra test
if ($LASTEXITCODE) { throw 'Python bağımlılık kurulumu başarısız' }
if (!(Test-Path 'vendor/FreyaTTS')) { git clone https://github.com/freyavoiceai/FreyaTTS.git vendor/FreyaTTS }
git -C vendor/FreyaTTS checkout 146d36c1cb6660646be57d31339db4eed9315de3
if ($LASTEXITCODE) { throw 'FreyaTTS sabit sürümü hazırlanamadı' }
if (!(Test-Path '.env')) {
  $bytes=New-Object byte[] 24
  $rng=[System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  $password=[Convert]::ToBase64String($bytes)
  $content=(Get-Content '.env.example' -Raw).Replace('change-this-before-use',$password)
  [System.IO.File]::WriteAllText((Join-Path $PWD '.env'),$content,(New-Object System.Text.UTF8Encoding $false))
  Write-Host "Yerel admin parolası .env dosyasında oluşturuldu."
}
& .venv/Scripts/python -m alembic upgrade head
if ($LASTEXITCODE) { throw 'Veritabanı kurulamadı' }
Push-Location frontend
try { npm ci; if ($LASTEXITCODE) { throw 'npm ci başarısız' }; npm run build; if ($LASTEXITCODE) { throw 'Arayüz derlenemedi' } } finally { Pop-Location }
Write-Host 'Kurulum tamamlandı. scripts/start.ps1 ile başlatın.'
