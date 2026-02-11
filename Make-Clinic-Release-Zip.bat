@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Re-launch in a persistent window so errors are visible.
if /I "%~1" NEQ "__stay" (
  start "Clinic App Release ZIP" cmd /k ""%~f0" __stay"
  exit /b 0
)

cd /d "%~dp0"

set "OUT_ZIP=ClinicApp-Release.zip"
set "STAGE=%TEMP%\\ClinicApp-Release-%RANDOM%%RANDOM%"
set "LOG=%CD%\\Make-Clinic-Release-Zip.log"

> "%LOG%" echo [INFO] Make-Clinic-Release-Zip started at %DATE% %TIME%
>> "%LOG%" echo [INFO] Working dir: %CD%

echo [INFO] Creating Clinic App RELEASE ZIP (clinic-friendly)...
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

REM Copy only folders/files needed to run the app.
robocopy "clinic_app" "%STAGE%\\clinic_app" /E /R:3 /W:1 /TEE /LOG+:"%LOG%"
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 goto :copy_fail

robocopy "templates" "%STAGE%\\templates" /E /R:3 /W:1 /TEE /LOG+:"%LOG%"
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 goto :copy_fail

robocopy "static" "%STAGE%\\static" /E /R:3 /W:1 /TEE /LOG+:"%LOG%"
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 goto :copy_fail

robocopy "migrations" "%STAGE%\\migrations" /E /R:3 /W:1 /TEE /LOG+:"%LOG%"
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 goto :copy_fail

copy /y "alembic.ini" "%STAGE%\\alembic.ini" >> "%LOG%" 2>&1 || goto :copy_fail
copy /y "requirements.txt" "%STAGE%\\requirements.txt" >> "%LOG%" 2>&1 || goto :copy_fail
copy /y "wsgi.py" "%STAGE%\\wsgi.py" >> "%LOG%" 2>&1 || goto :copy_fail
copy /y "Start-Clinic.bat" "%STAGE%\\Start-Clinic.bat" >> "%LOG%" 2>&1 || goto :copy_fail

REM Add empty data folder placeholder (fresh DB on first run)
mkdir "%STAGE%\\data" >> "%LOG%" 2>&1
(
  echo This folder will store the clinic database and files ^(created automatically on first run^).
  echo Backup = copy the whole data folder somewhere safe.
) > "%STAGE%\\data\\README.txt"

REM Create ZIP (ZipFile first, then Compress-Archive fallback)
echo [STEP] Creating ZIP...
>> "%LOG%" echo [STEP] Creating ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$stage='%STAGE%'; $out=(Join-Path (Get-Location) '%OUT_ZIP%');" ^
  "if(Test-Path $out){Remove-Item $out -Force};" ^
  "[IO.Compression.ZipFile]::CreateFromDirectory($stage,$out,[IO.Compression.CompressionLevel]::Optimal,$false);" ^
  "Write-Host '[INFO] ZIP created successfully.'" ^
  1>> "%LOG%" 2>&1
if errorlevel 1 (
  >> "%LOG%" echo [WARN] ZipFile method failed; trying Compress-Archive fallback...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "if(Test-Path '%OUT_ZIP%'){Remove-Item '%OUT_ZIP%' -Force};" ^
    "Compress-Archive -Path '%STAGE%\\*' -DestinationPath '%OUT_ZIP%' -Force" ^
    1>> "%LOG%" 2>&1 || goto :zip_fail
)

REM Cleanup staging
rmdir /s /q "%STAGE%" >> "%LOG%" 2>&1

if not exist "%OUT_ZIP%" goto :zip_fail

echo [OK] RELEASE ZIP created: %OUT_ZIP%
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

:no_powershell
echo [ERROR] PowerShell not found. This script requires PowerShell (Windows default).
echo [ERROR] See log: %LOG%
>> "%LOG%" echo [ERROR] PowerShell not found.
goto :halt

:stage_fail
echo [ERROR] Could not create staging folder: %STAGE%
echo [ERROR] See log: %LOG%
goto :halt

:copy_fail
echo [ERROR] Copy step failed.
echo [ERROR] See log: %LOG%
goto :halt

:zip_fail
echo [ERROR] ZIP creation failed.
echo [ERROR] See log: %LOG%
goto :halt

:halt
if exist "%STAGE%" rmdir /s /q "%STAGE%" >nul 2>nul
echo Press any key to close...
pause >nul
endlocal & exit /b 1

