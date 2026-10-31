@echo off
rem ============================================================
rem  Builds  FieldSurveyReport_Setup.exe  (run on YOUR Windows PC)
rem  1) Installs/updates the packages in .venv
rem  2) Runs the automated tests (if pytest is installed)
rem  3) PyInstaller turns the program into FieldSurveyReport.exe
rem  4) Inno Setup (free) wraps it into one Setup file
rem
rem  Options:  build_installer.bat /nopause   (do not wait for a key)
rem            build_installer.bat /notests   (skip the tests)
rem ============================================================
setlocal
cd /d "%~dp0"

set NOPAUSE=
set NOTESTS=
for %%A in (%*) do (
  if /i "%%A"=="/nopause" set NOPAUSE=1
  if /i "%%A"=="/notests" set NOTESTS=1
)

set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo The .venv folder was not found. Run this file inside the project folder
  echo that PyCharm created ^(the one with the .venv folder^).
  goto failed
)

rem version = build date, e.g. 2026.10.30
for /f %%V in ('powershell -NoProfile -Command "Get-Date -Format yyyy.MM.dd"') do set APPVER=%%V
if "%APPVER%"=="" set APPVER=1.0
echo Building version %APPVER%
echo.

echo [1/4] Installing the packages and the build tool...
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if errorlevel 1 goto failed

echo [2/4] Running the tests...
if defined NOTESTS (
  echo   skipped ^(/notests^)
) else (
  "%PY%" -c "import pytest" >nul 2>nul
  if errorlevel 1 (
    echo   pytest is not installed - skipped ^(pip install -r requirements-dev.txt^)
  ) else (
    "%PY%" -m pytest -q
    if errorlevel 1 (
      echo.
      echo The tests failed - the installer was NOT built.
      goto failed
    )
  )
)

echo [3/4] Building FieldSurveyReport.exe ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
"%PY%" -m PyInstaller --noconfirm --clean --windowed ^
  --name FieldSurveyReport --icon logo.ico ^
  --collect-all ttkbootstrap ^
  --collect-submodules mysql.connector ^
  --collect-submodules warehouse ^
  --collect-submodules warehouse_ui ^
  --hidden-import matplotlib.backends.backend_tkagg ^
  --hidden-import win32com.client ^
  --add-data "First_Page.xlsx;." ^
  --add-data "Cargo_Details.xlsx;." ^
  --add-data "Containerized_Loading_Form.xlsx;." ^
  --add-data "Incident_Report.xlsx;." ^
  --add-data "master_list.json;." ^
  --add-data "logo.png;." ^
  --add-data "logo.ico;." ^
  --add-data "installer_defaults\db_config.json;." ^
  --add-data "auth_seed.json;." ^
  field_survey_report.py
if errorlevel 1 goto failed
if not exist "dist\FieldSurveyReport\FieldSurveyReport.exe" goto failed

echo [4/4] Building the Setup file...
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo.
  echo FieldSurveyReport.exe is ready in:  dist\FieldSurveyReport
  echo To make the Setup file install Inno Setup 6 ^(jrsoftware.org^) and run
  echo this file again.
  goto done
)
"%ISCC%" /Q "/DAppVersion=%APPVER%" installer.iss
if errorlevel 1 goto failed

echo.
echo DONE.  Your installer ^(version %APPVER%^):  Installer\FieldSurveyReport_Setup.exe
:done
if not defined NOPAUSE pause
exit /b 0

:failed
echo.
echo The build failed. Read the messages above ^(send them to me^).
if not defined NOPAUSE pause
exit /b 1
