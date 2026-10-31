@echo off
rem Run this ONCE on a new PC (Python must be installed first).
cd /d "%~dp0"
echo Creating the program environment...
where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)
%PY% -m venv .venv
if errorlevel 1 (
  echo.
  echo Python was not found. Install Python from python.org first,
  echo tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo The installation failed. Check the internet connection and try again.
  pause
  exit /b 1
)
echo.
echo Done. Start the program with START_FSR.bat
pause
