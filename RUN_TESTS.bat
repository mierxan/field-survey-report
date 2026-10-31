@echo off
rem Runs every automated test (temporary folders only - real data is not touched).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt
".venv\Scripts\python.exe" -m pytest -v
pause
