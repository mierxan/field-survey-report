@echo off
rem Runs the automated tests (temporary folders only - real data is not touched).
rem
rem   RUN_TESTS.bat          every test, the program's window included
rem   RUN_TESTS.bat fast     only the tests that do not open the window
rem                          (-m "not gui": a few minutes)
rem   RUN_TESTS.bat cover    every test, with coverage per module
rem
rem The end of the output says how many tests were SKIPPED. A test that could
rem not open the program's window counts as a FAILURE (--fail-on-gui-skip).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt
if /i "%~1"=="fast" (
  ".venv\Scripts\python.exe" -m pytest -v -rs -m "not gui"
) else if /i "%~1"=="cover" (
  ".venv\Scripts\python.exe" -m pytest -q -rs --fail-on-gui-skip --cov --cov-report=term
) else (
  ".venv\Scripts\python.exe" -m pytest -v -rs --fail-on-gui-skip
)
if errorlevel 1 (
  echo.
  echo RESULT: NOT OK - a test failed, or the screens could not be tested.
  echo         Read the lines above ^(look for FAILED and SKIPPED^).
) else (
  echo.
  echo RESULT: OK - see the SKIPPED line above for tests that did not run.
)
pause
