@echo off
setlocal
rem Isolated User-edition TEST COPY for drafts hand checks. No real data.
cd /d "%~dp0"
set "FSR_HOME=D:\FSR_Drafts_HandChecks_2026-11-14"
set "FSR_EDITION=user"
set "FSR_SECRET_STORE="
set "FSR_DATABASE_DIR=%FSR_HOME%\LocalAppData\FieldSurveyReport\Databases"
echo Drafts test copy: %FSR_HOME%
echo Use invented reports and test-only accounts. Close this console when done.
".venv\Scripts\python.exe" main.py
endlocal
