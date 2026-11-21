@echo off
:: =====================================================================
:: ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
:: Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
:: =====================================================================
chcp 65001 >nul
title FreyaTTS Otomotiv Sesli Asistan - Sunucu

cd /d "%~dp0"

echo =====================================================================
echo           FREYATTS OTOMOTIV SESLI ASISTAN (POC)
echo =====================================================================
echo.

set "DEMO_MODE_ARG="
set "DEV_MODE_ARG="
for %%A in (%*) do (
    if /i "%%~A"=="--demo" set "DEMO_MODE_ARG=1"
    if /i "%%~A"=="--dev" set "DEV_MODE_ARG=1"
)

if defined DEMO_MODE_ARG (
    set DEMO_MODE=1
    echo [DEMO MODU] Ornek veriler gosterilir, gercek olcum degildir. Veri klasoru: data\demo
    echo.
)

if not exist ".venv\Scripts\python.exe" (
    echo [HATA] Sanal ortam ^(.venv^) bulunamadi!
    echo Lutfen once kurulumu tamamlayin.
    pause
    exit /b 1
)

echo [*] Yerel Ollama servisi kontrol ediliyor...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensure_ollama.ps1

echo [*] Veritabani semasi guncelleniyor (Alembic)...
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
    echo.
    echo [HATA] Veritabani sema guncellemesi (Alembic) basarisiz oldu!
    echo Tarayici baslatilmadi. Lutfen hata kayitlarini inceleyin.
    pause
    exit /b 1
)

if not exist "frontend\dist\index.html" (
    echo [*] Frontend paketi derleniyor...
    call npm run build --prefix frontend
    if errorlevel 1 (
        echo.
        echo [HATA] Frontend derlemesi (npm run build) basarisiz oldu!
        echo Tarayici baslatilmadi. Lutfen derleme hatalarini duzeltin.
        pause
        exit /b 1
    )
)

if defined DEV_MODE_ARG (
    echo [*] [DEV MODU] Yonetici parolasi panoya kopyalaniyor...
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if "%%a"=="ADMIN_PASSWORD" (
            <nul set /p="%%b" | clip
            echo [OK] Parola panoya kopyalandi! Giris ekraninda Ctrl+V yapabilirsiniz.
        )
    )
) else (
    echo [*] Guvenlik: Parola panoya otomatik kopyalanmadi. ^(Gelistirici modu icin: BASLAT.bat --dev^)
)

echo.
echo =====================================================================
echo  Web Arayuzu : http://127.0.0.1:8000
echo  API Dokuman : http://127.0.0.1:8000/docs
echo =====================================================================
echo.
echo [*] Tarayici baslatiliyor...
start http://127.0.0.1:8000

echo [*] Uvicorn FastAPI sunucusu baslatiliyor (Durdurmak icin Ctrl+C)...
echo.
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause

