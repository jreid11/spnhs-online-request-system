@echo off
setlocal
cd /d "%~dp0"
echo.
echo =====================================================
echo  SPNHS-SHS Online Records Request System - Setup
echo =====================================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from python.org.
  echo During installation, check "Add Python to PATH".
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :error
)
call .venv\Scripts\activate.bat
echo Installing required packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo.
echo Setup completed successfully.
echo Run the system using run_windows.bat
pause
exit /b 0
:error
echo.
echo Setup failed. Check your internet connection and Python installation.
pause
exit /b 1
