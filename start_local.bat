@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo  RASH Telegram Mini App - LOCALHOST TEST MODE
echo ==============================================

where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher topilmadi. Python 3.11 yoki yangirogini o'rnating.
  echo O'rnatishda "Add Python to PATH" ni belgilang.
  pause
  exit /b 1
)

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo Lokal sozlama .env fayliga nusxalandi.
)

if not exist ".venv\Scripts\python.exe" (
  echo Virtual muhit yaratilmoqda...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Virtual muhit yaratilmadi. Python o'rnatilishini tekshiring.
    pause
    exit /b 1
  )
)

echo Lokal uchun kerakli kutubxonalar tekshirilmoqda...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-local.txt
if errorlevel 1 (
  echo Kutubxonalar o'rnatilmadi. Internet aloqasini tekshirib qayta urinib ko'ring.
  pause
  exit /b 1
)

echo Server yangi oynada ishga tushiriladi. Brauzer ochilishini kuting...
start "RASH Local Server" cmd /k ""%CD%\.venv\Scripts\python.exe" app.py"
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8080"
echo.
echo Ilova: http://127.0.0.1:8080
 echo Lokal server oynasini yopmang.
echo.
pause
