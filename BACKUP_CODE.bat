@echo off
rem Back up the program's CODE: every branch and tag as one dated git
rem bundle, checked before it counts, in a folder you choose. The newest 10
rem are kept. No data, accounts, passwords or .venv are in it.
rem   BACKUP_CODE.bat            asks for the folder (remembers the last one)
rem   BACKUP_CODE.bat D:\Backup  backs up to that folder
rem How to restore: docs\BACKUP_CODE.md
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
  echo Git is not installed or not on the PATH, so nothing was backed up.
  pause
  exit /b 1
)
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=py -3"
%PY% tools\backup_code.py %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
