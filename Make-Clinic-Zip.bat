@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Clinic-friendly ZIP builder: includes only what a clinic needs to run the app.
REM This script intentionally does NOT include clinic data, tests, dev tools, or extra BAT files.

cd /d "%~dp0"

set "OUT_ZIP=ClinicApp-Clinic.zip"
set "STAGE=%TEMP%\ClinicApp-Release-%RANDOM%%RANDOM%"
set "LOG=%CD%\Make-Clinic-Zip.log"

> "%LOG%" echo [INFO] Make-Clinic-Zip started at %DATE% %TIME%
>> "%LOG%" echo [INFO] Working dir: %CD%

echo [INFO] Creating Clinic App ZIP (clinic release)...
echo [INFO] Output: %OUT_ZIP%
echo [INFO] Log: %LOG%
echo.

where powershell >nul 2>nul || goto :no_powershell

REM Remove previous zip if present
if exist "%OUT_ZIP%" del /f /q "%OUT_ZIP%" >nul 2>nul

REM Create staging folder
if exist "%STAGE%" rmdir /s /q "%STAGE%" >nul 2>nul
mkdir "%STAGE%" >> "%LOG%" 2>&1 || goto :stage_fail

echo [STEP] Copying app runtime files...
>> "%LOG%" echo [STEP] Copying app runtime files...

call :copy_dir "clinic_app" "%STAGE%\clinic_app"
if errorlevel 1 goto :copy_fail
call :copy_dir "templates" "%STAGE%\templates"
if errorlevel 1 goto :copy_fail
call :copy_dir "static" "%STAGE%\static"
if errorlevel 1 goto :copy_fail
call :copy_dir "migrations" "%STAGE%\migrations"
if errorlevel 1 goto :copy_fail

copy /y "wsgi.py" "%STAGE%\wsgi.py" >> "%LOG%" 2>&1 || goto :copy_fail
copy /y "alembic.ini" "%STAGE%\alembic.ini" >> "%LOG%" 2>&1 || goto :copy_fail
copy /y "requirements.txt" "%STAGE%\requirements.txt" >> "%LOG%" 2>&1 || goto :copy_fail

REM Keep ONLY this start script for clinic users
copy /y "Start-Clinic.bat" "%STAGE%\Start-Clinic.bat" >> "%LOG%" 2>&1 || goto :copy_fail

REM Add a short clinic README (so staff know what to do)
> "%STAGE%\README.txt" echo Clinic App (Clinic Copy)
>> "%STAGE%\README.txt" echo.
>> "%STAGE%\README.txt" echo 1^) Double-click Start-Clinic.bat
>> "%STAGE%\README.txt" echo 2^) Keep the black terminal window open while using the app
>> "%STAGE%\README.txt" echo 3^) Your clinic database and files are stored in the data\ folder
>> "%STAGE%\README.txt" echo    Backup = copy the whole data\ folder somewhere safe.

REM Empty data/ folder placeholder (fresh DB on first run)
mkdir "%STAGE%\data" >> "%LOG%" 2>&1
> "%STAGE%\data\README.txt" echo This folder stores the clinic database and files (created automatically on first run).
>> "%STAGE%\data\README.txt" echo Backup = copy the whole data folder somewhere safe.

echo [STEP] Creating ZIP...
>> "%LOG%" echo [STEP] Creating ZIP...

REM Use a simple PowerShell ZIP with retries (avoids cmd parsing edge-cases).
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $stage='%STAGE%'; $out=(Join-Path (Get-Location) '%OUT_ZIP%'); if(Test-Path $out){Remove-Item $out -Force}; $max=10; $delay=2; for($i=1; $i -le $max; $i++){ try{ Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $out -Force; break } catch { if($i -ge $max){ throw } Start-Sleep -Seconds $delay } }"
if errorlevel 1 goto :zip_fail

REM Cleanup staging
rmdir /s /q "%STAGE%" >> "%LOG%" 2>&1

if not exist "%OUT_ZIP%" goto :zip_fail

echo [OK] Clinic ZIP created: %OUT_ZIP%
echo.
echo [NEXT] On the clinic PC:
echo   1) Extract %OUT_ZIP% to any folder (e.g. Desktop\ClinicApp)
echo   2) Double-click Start-Clinic.bat
echo      - A new database will be created in .\data\
echo      - Keep the terminal open while using the app
echo.
echo Press any key to close...
pause >nul
endlocal & exit /b 0

:copy_dir
set "SRC=%~1"
set "DST=%~2"
robocopy "%SRC%" "%DST%" /E /R:3 /W:1 /LOG+:"%LOG%" /XD "__pycache__" /XF "*.pyc" /NFL /NDL /NJH /NJS >nul
set "RC=!ERRORLEVEL!"
REM Robocopy exit codes 0-7 are success (including "some files skipped").
if !RC! GEQ 8 exit /b 1
exit /b 0

:no_powershell
echo [ERROR] PowerShell not found. This script requires PowerShell (Windows default).
>> "%LOG%" echo [ERROR] PowerShell not found.
goto :halt

:stage_fail
echo [ERROR] Could not create staging folder: %STAGE%
goto :halt

:copy_fail
echo [ERROR] Copy step failed. See log: %LOG%
goto :halt

:zip_fail
echo [ERROR] ZIP creation failed. See log: %LOG%
goto :halt

:halt
if exist "%STAGE%" rmdir /s /q "%STAGE%" >nul 2>nul
echo Press any key to close...
pause >nul
endlocal & exit /b 1
