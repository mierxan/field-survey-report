@echo off
rem ============================================================
rem  Builds the two Setup files  (run on YOUR Windows PC)
rem    Installer\FieldSurveyReport_Owner_Setup_<version>.exe
rem        the owner's PC: Excel + MySQL (Workbench) + Import Master Data
rem    Installer\FieldSurveyReport_User_Setup_<version>.exe
rem        the site PCs: Excel/JSON on that PC only + Export Master Data
rem
rem  1) Installs/updates the packages in .venv
rem  2) Runs the automated tests (if pytest is installed)
rem  3) PyInstaller turns the program into FieldSurveyReport.exe (per edition)
rem  4) Inno Setup (free) wraps each one into a Setup file
rem
rem  Options:  build_installer.bat /nopause   (do not wait for a key)
rem            build_installer.bat /notests   (skip the tests)
rem            build_installer.bat /owner     (only the Owner edition)
rem            build_installer.bat /user      (only the User edition)
rem ============================================================
setlocal
cd /d "%~dp0"

set NOPAUSE=
set NOTESTS=
set ONLY=
for %%A in (%*) do (
  if /i "%%A"=="/nopause" set NOPAUSE=1
  if /i "%%A"=="/notests" set NOTESTS=1
  if /i "%%A"=="/owner" set ONLY=Owner
  if /i "%%A"=="/user" set ONLY=User
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
      echo The tests failed - the installers were NOT built.
      goto failed
    )
  )
)

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

if /i not "%ONLY%"=="User" (
  call :edition Owner
  if errorlevel 1 goto failed
)
if /i not "%ONLY%"=="Owner" (
  call :edition User
  if errorlevel 1 goto failed
)

echo.
if not defined ISCC (
  echo The programs are ready in  dist\Owner  and  dist\User.
  echo To make the Setup files install Inno Setup 6 ^(jrsoftware.org^) and run
  echo this file again.
  goto done
)
echo DONE.  Your installers ^(version %APPVER%^) are in the Installer folder:
if /i not "%ONLY%"=="User"  echo    FieldSurveyReport_Owner_Setup_%APPVER%.exe   - the owner's PC
if /i not "%ONLY%"=="Owner" echo    FieldSurveyReport_User_Setup_%APPVER%.exe    - the site PCs
:done
if not defined NOPAUSE pause
exit /b 0

:failed
echo.
echo The build failed. Read the messages above ^(send them to me^).
if not defined NOPAUSE pause
exit /b 1


rem ---- one edition: %1 = Owner or User -------------------------------
:edition
set ED=%~1
echo.
echo [3/4] Building FieldSurveyReport.exe - %ED% edition ...
set EDDIR=build\edition_%ED%\data\json
mkdir "%EDDIR%" 2>nul
if /i "%ED%"=="Owner" (
  >"%EDDIR%\edition.json" echo {"edition": "owner"}
) else (
  >"%EDDIR%\edition.json" echo {"edition": "user"}
)

rem Only the Owner edition carries the MySQL driver, the MySQL defaults and
rem the owner's account (auth_seed.json). The User edition is installed
rem WITHOUT any account: the first person on a site PC creates the
rem Administrator account of that PC.
set EXTRA=
if /i "%ED%"=="Owner" set EXTRA=--collect-submodules mysql.connector --add-data "%CD%\data\json\private\installer_defaults\db_config.json;data\json\private\installer_defaults" --add-data "%CD%\data\json\private\auth_seed.json;data\json\private"
if /i "%ED%"=="User" set EXTRA=--exclude-module mysql --exclude-module mysql.connector

"%PY%" -m PyInstaller --noconfirm --clean --windowed ^
  --name FieldSurveyReport --icon "%CD%\logo.ico" ^
  --distpath "dist\%ED%" --workpath "build\work_%ED%" --specpath "build" ^
  --collect-all ttkbootstrap ^
  --collect-submodules warehouse ^
  --collect-submodules warehouse_ui ^
  --hidden-import matplotlib.backends.backend_tkagg ^
  --hidden-import win32com.client ^
  --add-data "%CD%\data\excel\First_Page.xlsx;data\excel" ^
  --add-data "%CD%\data\excel\Cargo_Details.xlsx;data\excel" ^
  --add-data "%CD%\data\excel\Containerized_Loading_Form.xlsx;data\excel" ^
  --add-data "%CD%\data\excel\Incident_Report.xlsx;data\excel" ^
  --add-data "%CD%\data\json\master_list.json;data\json" ^
  --add-data "%CD%\%EDDIR%\edition.json;data\json" ^
  --add-data "%CD%\logo.png;." ^
  --add-data "%CD%\logo.ico;." ^
  %EXTRA% ^
  field_survey_report.py
if errorlevel 1 exit /b 1
if not exist "dist\%ED%\FieldSurveyReport\FieldSurveyReport.exe" exit /b 1

rem The User edition must never contain an account, a password hash or a
rem MySQL login. The build stops here if it does.
if /i "%ED%"=="User" "%PY%" fsr_build_check.py "dist\User\FieldSurveyReport"
if errorlevel 1 (
  echo.
  echo The User edition contains private account data - it was NOT packaged.
  exit /b 1
)

if not defined ISCC exit /b 0
echo [4/4] Building the %ED% Setup file...
"%ISCC%" /Q "/DAppVersion=%APPVER%" "/DEdition=%ED%" installer.iss
if errorlevel 1 exit /b 1
exit /b 0
