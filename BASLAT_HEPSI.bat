@echo off
:: =====================================================================
:: ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
:: Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
:: =====================================================================
chcp 65001 >nul
title FreyaTTS Otomotiv - Tam Sistem Başlatıcı (Backend + Frontend)

cd /d "%~dp0"

echo =====================================================================
echo    FREYATTS OTOMOTIV SESLI ASISTAN (POC) - TAM SISTEM BASLATICI
echo =====================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [HATA] Sanal ortam (.venv) bulunamadi!
    echo Lutfen once Python ortamini kurun.
    pause
    exit /b 1
)

echo [*] Veritabani semasi guncelleniyor (Alembic)...
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
    echo.
    echo [HATA] Veritabani sema guncellemesi (Alembic) basarisiz oldu!
    echo Tarayici ve servisler baslatilmadi. Lutfen veritabani hatalarini duzeltin.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [*] Frontend bagimliliklari yukleniyor...
    call npm install --prefix frontend
    if errorlevel 1 (
        echo.
        echo [HATA] Frontend bagimliliklari yuklenemedi (npm install)!
        echo Tarayici ve servisler baslatilmadi.
        pause
        exit /b 1
    )
)

echo [*] Hizli derleme paketi kontrol ediliyor...
if not exist "frontend\dist\index.html" (
    echo [*] Frontend dist paketi hazirlaniyor...
    call npm run build --prefix frontend
    if errorlevel 1 (
        echo.
        echo [HATA] Frontend derlemesi (npm run build) basarisiz oldu!
        echo Tarayici ve servisler baslatilmadi.
        pause
        exit /b 1
    )
)

echo.
echo =====================================================================
echo  [1] Backend API & WebSocket:  http://127.0.0.1:8000
echo  [2] Frontend Hizli Gelistirici: http://127.0.0.1:5173
echo  [3] Swagger API Dokumantasyon: http://127.0.0.1:8000/docs
echo =====================================================================
echo.

echo [*] Backend Uvicorn sunucusu ayri pencerede baslatiliyor...
start "FreyaTTS Backend (FastAPI :8000)" cmd /k "chcp 65001 >nul && title FreyaTTS Backend :8000 && cd /d "%~dp0" && .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 2 /nobreak >nul

echo [*] Frontend Vite gelistirme sunucusu ayri pencerede baslatiliyor...
start "FreyaTTS Frontend (Vite :5173)" cmd /k "chcp 65001 >nul && title FreyaTTS Frontend :5173 && cd /d "%~dp0\frontend" && npm run dev"

timeout /t 2 /nobreak >nul

echo [*] Varsayilan web tarayicisi aciliyor...
start http://127.0.0.1:5173

echo.
echo [OK] Backend ve Frontend basariyla ayaga kalkti!
echo Servisleri durdurmak icin acilan konsol pencerelerini kapatabilir veya Ctrl+C yapabilirsiniz.
echo.
pause
