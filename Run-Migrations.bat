@echo off
setlocal EnableExtensions EnableDelayedExpansion
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
echo [INFO] Running database updates...
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

echo [INFO] Ensuring default admin exists...
"%VENV_PY%" -m flask --app clinic_app.app seed-admin --username admin --password ChangeMe!123 || goto :seed_fail

echo [OK] Done.
echo Press any key to close...
pause >nul
endlocal & exit /b 0

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
goto :halt
:seed_fail
echo [ERROR] Failed to create/check default admin user.
goto :halt
:halt
echo Press any key to close...
pause >nul
endlocal & exit /b 1
