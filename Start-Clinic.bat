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

if exist requirements.txt (
  echo [INFO] Installing dependencies...
  "%VENV_PY%" -m pip install -r requirements.txt || goto :deps_fail
)

set PYTHONUTF8=1

rem --- Kill any existing process on port 8080 so we don't get conflicts ---
echo [INFO] Checking if port 8080 is already in use...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8080 " ^| findstr "LISTENING"') do (
  echo [INFO] Port 8080 is in use by PID %%p. Stopping it...
  taskkill /F /PID %%p >nul 2>&1
)

echo [INFO] Checking database updates...
set "MIGRATE_LOG=%TEMP%\clinic_migrate_%RANDOM%%RANDOM%.log"
"%VENV_PY%" -m flask --app clinic_app.app db upgrade >"%MIGRATE_LOG%" 2>&1 || goto :migrate_fail
type "%MIGRATE_LOG%"
findstr /C:"Running upgrade" "%MIGRATE_LOG%" >nul
if errorlevel 1 (
  echo [INFO] Database already up to date.
) else (
  echo [INFO] Database updates applied.
)
del /q "%MIGRATE_LOG%" >nul 2>&1

echo [INFO] Starting Clinic App...

rem Auto-open browser ~2s after start (no policy issues; single command)
powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8080/'" 2>nul

"%VENV_PY%" -m clinic_app.app
set EXITCODE=%ERRORLEVEL%
echo.
echo [INFO] App exited with code %EXITCODE%.
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
:migrate_fail
if exist "%MIGRATE_LOG%" (
  type "%MIGRATE_LOG%"
  del /q "%MIGRATE_LOG%" >nul 2>&1
)
echo [ERROR] Automatic database update failed.
echo [ERROR] Please run Run-Migrations.bat and try again.
goto :halt
:halt
echo Press any key to close...
pause >nul
endlocal & exit /b 1
