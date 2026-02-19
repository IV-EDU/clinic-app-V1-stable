@echo off
setlocal
cd /d "%~dp0"

echo [INFO] Running backend logic tests (pytest)...
where py >nul 2>nul || goto :no_py

if not exist .venv (
  echo [INFO] Creating .venv with Python 3.12...
  py -3.12 -m venv .venv || goto :venv_fail
)

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto :venv_bad

"%VENV_PY%" -m pip --version >nul 2>nul || "%VENV_PY%" -m ensurepip --upgrade
"%VENV_PY%" -m pip install --upgrade pip || goto :pip_fail
if exist requirements.txt "%VENV_PY%" -m pip install -r requirements.txt || goto :deps_fail
if exist requirements.dev.txt "%VENV_PY%" -m pip install -r requirements.dev.txt || goto :deps_fail

"%VENV_PY%" -m pytest -q
set PYTEST_EXIT=%ERRORLEVEL%
if not %PYTEST_EXIT%==0 goto :pytest_fail

echo [INFO] Running browser smoke tests (Playwright)...
call Run-E2E-Tests.bat
set E2E_EXIT=%ERRORLEVEL%
if not %E2E_EXIT%==0 goto :e2e_fail

echo [INFO] Validation passed (pytest + Playwright smoke).
endlocal & exit /b 0

:no_py
echo [ERROR] Python launcher 'py' not found. Install Python 3.12 and ensure it is on PATH.
endlocal & exit /b 1

:venv_fail
echo [ERROR] Failed to create .venv with Python 3.12.
endlocal & exit /b 1

:venv_bad
echo [ERROR] .venv is missing Scripts\python.exe. Delete .venv and rerun.
endlocal & exit /b 1

:pip_fail
echo [ERROR] Failed to initialize pip in .venv.
endlocal & exit /b 1

:deps_fail
echo [ERROR] Failed to install Python dependencies.
endlocal & exit /b 1

:pytest_fail
echo [ERROR] Pytest failed with code %PYTEST_EXIT%.
endlocal & exit /b %PYTEST_EXIT%

:e2e_fail
echo [ERROR] Playwright smoke tests failed with code %E2E_EXIT%.
endlocal & exit /b %E2E_EXIT%
