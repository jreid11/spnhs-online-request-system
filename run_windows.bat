@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please run setup_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:5000
echo.
echo SPNHS-SHS system is running at http://127.0.0.1:5000
echo Keep this window open. Press Ctrl+C to stop.
echo.
python app.py
pause
