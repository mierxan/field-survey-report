@echo off
rem Runs every automated test (temporary folders only - real data is not touched).
rem The end of the output says how many tests were SKIPPED. A test that could
rem not open the program's window counts as a FAILURE (--fail-on-gui-skip).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt
".venv\Scripts\python.exe" -m pytest -v -rs --fail-on-gui-skip
if errorlevel 1 (
  echo.
  echo RESULT: NOT OK - a test failed, or the screens could not be tested.
  echo         Read the lines above ^(look for FAILED and SKIPPED^).
) else (
  echo.
  echo RESULT: OK - see the SKIPPED line above for tests that did not run.
)
pause
