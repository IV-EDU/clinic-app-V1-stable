@echo off
setlocal
cd /d "%~dp0"

echo [INFO] Using project venv (Python 3.12)...
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

if exist requirements.txt "%VENV_PY%" -m pip install -r requirements.txt || goto :deps_fail
if exist requirements.dev.txt "%VENV_PY%" -m pip install -r requirements.dev.txt || goto :deps_fail

echo [INFO] Running tests...
"%VENV_PY%" -m pytest -q
set EXITCODE=%ERRORLEVEL%
echo.
if %EXITCODE%==0 (echo [INFO] Tests passed.) else (echo [ERROR] Tests failed with code %EXITCODE%.)
echo Press any key to close...
pause >nul
endlocal & exit /b %EXITCODE%

:no_py
echo [ERROR] Python launcher 'py' not found. Install Python 3.12 (64-bit) and ensure it's on PATH.
goto :halt
:venv_fail
echo [ERROR] Failed to create .venv with Python 3.12. Run: py -0p (confirm 3.12 listed).
goto :halt
:venv_bad
echo [ERROR] .venv looks corrupted (missing Scripts\python.exe). Delete .venv and try again.
goto :halt
:pip_fail
echo [ERROR] Failed to install/upgrade pip in the venv.
goto :halt
:deps_fail
echo [ERROR] Installing requirements failed.
goto :halt
:halt
echo Press any key to close...
pause >nul
endlocal & exit /b 1
