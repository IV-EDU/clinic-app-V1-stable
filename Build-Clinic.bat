@echo off
setlocal
cd /d "%~dp0"

echo [INFO] Building offline Clinic App (folder build)...
where py >nul 2>nul || goto :no_py

if not exist .venv (
  echo [INFO] Creating .venv with Python 3.12...
  py -3.12 -m venv .venv || goto :venv_fail
)

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto :venv_bad

echo [INFO] Installing build dependencies...
"%VENV_PY%" -m pip install --upgrade pip || goto :pip_fail
if exist requirements.txt "%VENV_PY%" -m pip install -r requirements.txt || goto :deps_fail
if exist requirements.dev.txt "%VENV_PY%" -m pip install -r requirements.dev.txt || goto :deps_fail

echo [INFO] Running PyInstaller...
"%VENV_PY%" -m PyInstaller --noconfirm clinic_app.spec || goto :build_fail

echo [INFO] Creating ZIP...
REM Safety: never ship real clinic data. If the packaged app was run from dist, it may have created dist\ClinicApp\data.
if exist "dist\ClinicApp\data" (
  echo [INFO] Removing dist\\ClinicApp\\data before zipping (do not ship clinic data)...
  rmdir /s /q "dist\ClinicApp\data"
)

REM Compress-Archive can fail on Windows if AV/indexing briefly locks a file. Retry a few times.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "if(Test-Path 'ClinicApp.zip'){Remove-Item 'ClinicApp.zip' -Force};" ^
  "$max=10; $delay=2;" ^
  "for($i=1; $i -le $max; $i++){" ^
    "try{" ^
      "Compress-Archive -Path 'dist\\ClinicApp\\*' -DestinationPath 'ClinicApp.zip' -Force;" ^
      "Write-Host '[INFO] ZIP created successfully.';" ^
      "break;" ^
    "}catch{" ^
      "if($i -ge $max){ throw }" ^
      "Write-Host ('[WARN] ZIP failed (try ' + $i + '/' + $max + '). Waiting ' + $delay + 's and retrying...');" ^
      "Start-Sleep -Seconds $delay;" ^
    "}" ^
  "}" || goto :zip_fail

echo [INFO] Done.
echo [INFO] Output:
echo   - dist\\ClinicApp\\ClinicApp.exe
echo   - ClinicApp.zip
echo.
echo Press any key to close...
pause >nul
endlocal & exit /b 0

:no_py
echo [ERROR] Python launcher 'py' not found. Install Python 3.12 (64-bit) and try again.
goto :halt
:venv_fail
echo [ERROR] Failed to create .venv with Python 3.12.
goto :halt
:venv_bad
echo [ERROR] .venv looks corrupted (missing Scripts\\python.exe). Delete .venv and try again.
goto :halt
:pip_fail
echo [ERROR] Failed to install/upgrade pip.
goto :halt
:deps_fail
echo [ERROR] Installing requirements failed.
goto :halt
:build_fail
echo [ERROR] PyInstaller build failed.
goto :halt
:zip_fail
echo [ERROR] ZIP creation failed.
goto :halt
:halt
echo Press any key to close...
pause >nul
endlocal & exit /b 1
