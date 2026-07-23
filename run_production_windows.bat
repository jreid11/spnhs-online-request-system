@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\waitress-serve.exe (
  echo Please run setup_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo.
echo Starting on all local network interfaces, port 5000...
echo Open http://YOUR-COMPUTER-IP:5000 from another device on the same network.
echo Press Ctrl+C to stop.
echo.
waitress-serve --listen=0.0.0.0:5000 app:app
pause
