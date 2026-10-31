@echo off
rem Demo Mode: fictional TEST data in the demo_data folder, MySQL off.
rem The real Excel file, settings and MySQL database are not used.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run SETUP_NEW_PC.bat first.
  pause
  exit /b 1
)
if not exist "demo_data\Field_Survey_Reports_DEMO.xlsx" (
  echo Creating the sample data in demo_data ...
  ".venv\Scripts\python.exe" -m warehouse.sample_data generate
)
set FSR_DEMO=1
start "" ".venv\Scripts\pythonw.exe" main.py
