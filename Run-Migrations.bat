@echo off
setlocal
cd /d "%~dp0"

set "PY_CMD="
py -3 --version >nul 2>&1
if not errorlevel 1 (
  set "PY_CMD=py -3"
)
if not defined PY_CMD (
  where python3 >nul 2>&1
  if not errorlevel 1 (
    set "PY_CMD=python3"
  )
)
if not defined PY_CMD (
  where python >nul 2>&1
  if not errorlevel 1 (
    set "PY_CMD=python"
  )
)

if not defined PY_CMD (
  echo Python 3 is required. Install Python and rerun.
  pause
  exit /b 1
)

set "FLASK_APP=wsgi.py"

echo Installing project requirements...
%PY_CMD% -m pip install --upgrade pip >nul
if errorlevel 1 (
  echo Failed to upgrade pip.
  pause
  exit /b 1
)

%PY_CMD% -m pip install -r requirements.txt >nul
if errorlevel 1 (
  echo Failed to install requirements.
  pause
  exit /b 1
)

echo Running alembic migrations...
%PY_CMD% -m flask db upgrade
if errorlevel 1 (
  echo Migration failed.
  pause
  exit /b 1
)

echo Seeding default admin...
%PY_CMD% -m flask seed-admin --username admin --password ChangeMe!123
if errorlevel 1 (
  echo Failed to seed admin.
  pause
  exit /b 1
)

echo Migrations ^& seed complete.
pause
