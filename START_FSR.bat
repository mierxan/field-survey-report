@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run SETUP_NEW_PC.bat first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
