@echo off
setlocal
cd /d "%~dp0"

echo [INFO] Preparing Python environment...
where py >nul 2>nul || goto :no_py

if not exist .venv (
  echo [INFO] Creating .venv with Python 3.12...
  py -3.12 -m venv .venv || goto :venv_fail
)

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto :venv_bad

echo [INFO] Ensuring pip in the venv...
"%VENV_PY%" -m pip --version >nul 2>nul || "%VENV_PY%" -m ensurepip --upgrade
"%VENV_PY%" -m pip install --upgrade pip || goto :pip_fail

if exist requirements.txt (
  echo [INFO] Installing Python runtime dependencies...
  "%VENV_PY%" -m pip install -r requirements.txt || goto :deps_fail
)

echo [INFO] Checking Node/npm...
where node >nul 2>nul || goto :no_node
where npm >nul 2>nul || goto :no_npm

if not exist node_modules\@playwright\test (
  echo [INFO] Installing Node dependencies...
  npm install || goto :npm_fail
)

echo [INFO] Ensuring Playwright Chromium browser is available...
npx playwright install chromium || goto :pw_install_fail

set "PW_PYTHON=%VENV_PY%"
if not defined PW_PORT set "PW_PORT=8181"

echo [INFO] Running Playwright smoke tests...
npm run test:e2e
set EXITCODE=%ERRORLEVEL%

if %EXITCODE%==0 (
  echo [INFO] E2E smoke tests passed.
) else (
  echo [ERROR] E2E smoke tests failed with code %EXITCODE%.
)

endlocal & exit /b %EXITCODE%

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
echo [ERROR] Failed to install Python runtime dependencies.
endlocal & exit /b 1

:no_node
echo [ERROR] Node.js is not installed or not on PATH.
endlocal & exit /b 1

:no_npm
echo [ERROR] npm is not installed or not on PATH.
endlocal & exit /b 1

:npm_fail
echo [ERROR] npm install failed.
endlocal & exit /b 1

:pw_install_fail
echo [ERROR] Playwright browser installation failed.
endlocal & exit /b 1
