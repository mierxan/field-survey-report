@echo off
setlocal
title Go back to the Excel file
set "HERE=%~dp0"
cd /d "%HERE%"
rem Stops using the reports database: the Excel file is brought up to date
rem (it then holds every report) and the database file is put aside
rem (renamed, not deleted). Use it before going back to the previous
rem version of the program. Steps for everyone: docs\SQLITE.md, "The way
rem back". Works beside the installed program and in the project folder.

echo ================================================================
echo   GO BACK TO THE EXCEL FILE
echo ================================================================
echo.
echo  Since this version, the reports are kept in a database file and
echo  the Excel file is a copy that the program keeps up to date.
echo.
echo  This makes the Excel file hold every report again and stops using
echo  the database. The database file is kept (renamed), not deleted.
echo  Use it before you go back to the previous version of the program.
echo.

rem ---- 1. the program must be closed -----------------------------------
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'FieldSurveyReport.exe' -or ($_.Name -like 'python*.exe' -and $_.CommandLine -match 'main\.py|field_survey_report\.py') }; if ($p) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  echo  The Field Survey Report program is still open.
  echo  Close it ^(and wait until its window is gone^), then run this again.
  echo.
  pause
  exit /b 1
)

rem ---- 2. how to start the program's own code --------------------------
set "REPORT=%TEMP%\fsr_go_back_%RANDOM%%RANDOM%.txt"
if exist "FieldSurveyReport.exe" (
  set "MODE=exe"
) else if exist ".venv\Scripts\python.exe" (
  set "MODE=python"
) else (
  echo  This file must be in the folder of the program
  echo  ^(next to FieldSurveyReport.exe^). Nothing was changed.
  echo.
  pause
  exit /b 1
)

rem ---- 3. what is there now ---------------------------------------------
echo  Looking at the reports ...
echo.
call :run --database-status
set "RC=%ERRORLEVEL%"
call :show
if "%RC%"=="3" (
  echo  Nothing to do.
  echo.
  pause
  exit /b 0
)
if not "%RC%"=="0" (
  echo  Nothing was changed.
  echo.
  pause
  exit /b 1
)

rem ---- 4. ask, then do it ----------------------------------------------
echo.
echo  Type YES ^(in capital letters^) and press Enter to go back to the
echo  Excel file. Anything else stops here and changes nothing.
set "ANSWER="
set /p "ANSWER=  > "
if not "%ANSWER%"=="YES" (
  echo.
  echo  Stopped. Nothing was changed.
  echo.
  pause
  exit /b 0
)
echo.
echo  Bringing the Excel file up to date ...
echo.
call :run --go-back-to-workbook
set "RC=%ERRORLEVEL%"
call :show
if "%RC%"=="0" (
  echo  DONE.
) else (
  echo  NOT DONE - see above.
)
echo.
pause
exit /b %RC%

rem ---- helpers ------------------------------------------------------------
:run
if exist "%REPORT%" del "%REPORT%"
if "%MODE%"=="exe" (
  start "" /wait "%HERE%FieldSurveyReport.exe" %1 --report "%REPORT%"
) else (
  "%HERE%.venv\Scripts\python.exe" "%HERE%main.py" %1 --report "%REPORT%"
)
exit /b %ERRORLEVEL%

:show
if exist "%REPORT%" (
  type "%REPORT%"
  del "%REPORT%"
) else (
  echo  The program did not answer. Nothing was changed.
)
echo.
exit /b 0
