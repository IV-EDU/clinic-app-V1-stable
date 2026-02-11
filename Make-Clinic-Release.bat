@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "OUT_ZIP=ClinicApp-Release.zip"
set "STAGE=%TEMP%\ClinicApp-Release-%RANDOM%%RANDOM%"

echo [INFO] Creating clinic release package...
echo [INFO] Output: %OUT_ZIP%
echo.

for %%D in (clinic_app templates static migrations) do (
  if not exist "%%D\" (
    echo [ERROR] Required folder missing: %%D
    goto :halt
  )
)

for %%F in (alembic.ini requirements.txt wsgi.py Start-Clinic.bat Run-Migrations.bat) do (
  if not exist "%%F" (
    echo [ERROR] Required file missing: %%F
    goto :halt
  )
)

where powershell >nul 2>nul || goto :no_powershell

if exist "%OUT_ZIP%" del /f /q "%OUT_ZIP%" >nul 2>nul
if exist "%STAGE%" rmdir /s /q "%STAGE%" >nul 2>nul
mkdir "%STAGE%" || goto :stage_fail

echo [STEP] Copying runtime files...
call :copy_dir "clinic_app" "%STAGE%\clinic_app" || goto :copy_fail
call :copy_dir "templates" "%STAGE%\templates" || goto :copy_fail
call :copy_dir "static" "%STAGE%\static" || goto :copy_fail
call :copy_dir "migrations" "%STAGE%\migrations" || goto :copy_fail

copy /y "alembic.ini" "%STAGE%\alembic.ini" >nul || goto :copy_fail
copy /y "requirements.txt" "%STAGE%\requirements.txt" >nul || goto :copy_fail
copy /y "wsgi.py" "%STAGE%\wsgi.py" >nul || goto :copy_fail
copy /y "Start-Clinic.bat" "%STAGE%\Start-Clinic.bat" >nul || goto :copy_fail
copy /y "Run-Migrations.bat" "%STAGE%\Run-Migrations.bat" >nul || goto :copy_fail
if exist "Start-Clinic-Preview.bat" copy /y "Start-Clinic-Preview.bat" "%STAGE%\Start-Clinic-Preview.bat" >nul

mkdir "%STAGE%\data" >nul 2>nul
(
  echo This folder stores clinic data files.
  echo A database is created automatically on first run.
  echo Backup tip: copy the full data folder to a safe location.
) > "%STAGE%\data\README.txt"

(
  echo Clinic App Release Package
  echo.
  echo 1^) Double-click Start-Clinic.bat
  echo 2^) Keep the terminal window open while using the app
  echo 3^) If startup shows migration error, run Run-Migrations.bat once
  echo 4^) Backup regularly by copying the data folder
) > "%STAGE%\README.txt"

echo [STEP] Building ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$stage='%STAGE%'; $out=(Join-Path (Get-Location) '%OUT_ZIP%');" ^
  "if(Test-Path $out){Remove-Item $out -Force};" ^
  "$max=8; $delay=2;" ^
  "for($i=1; $i -le $max; $i++){" ^
    "try{ Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $out -Force; break }" ^
    "catch{ if($i -ge $max){ throw }; Start-Sleep -Seconds $delay }" ^
  "}" || goto :zip_fail

rmdir /s /q "%STAGE%" >nul 2>nul

if not exist "%OUT_ZIP%" goto :zip_fail

echo [OK] Release package created: %OUT_ZIP%
echo.
echo [NEXT] On clinic computer:
echo   1) Extract %OUT_ZIP% into a folder
echo   2) Double-click Start-Clinic.bat
echo.
echo Press any key to close...
pause >nul
endlocal & exit /b 0

:copy_dir
set "SRC=%~1"
set "DST=%~2"
robocopy "%SRC%" "%DST%" /E /R:3 /W:1 /XD "__pycache__" /XF "*.pyc" /NFL /NDL /NJH /NJS >nul
set "RC=!ERRORLEVEL!"
if !RC! GEQ 8 exit /b 1
exit /b 0

:no_powershell
echo [ERROR] PowerShell is required.
goto :halt

:stage_fail
echo [ERROR] Could not create staging folder.
goto :halt

:copy_fail
echo [ERROR] Failed while copying runtime files.
goto :halt

:zip_fail
echo [ERROR] Failed to create release ZIP.
goto :halt

:halt
if exist "%STAGE%" rmdir /s /q "%STAGE%" >nul 2>nul
echo Press any key to close...
pause >nul
endlocal & exit /b 1
