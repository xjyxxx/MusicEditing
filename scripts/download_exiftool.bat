@echo off
setlocal EnableDelayedExpansion

REM Download ExifTool Windows x64 into third_party/exiftool/

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "OUT_DIR=%PROJECT_DIR%\third_party\exiftool"
set "OUT_EXE=%OUT_DIR%\exiftool.exe"
set "VER=13.59"

echo ========================================
echo  Download ExifTool (image metadata)
echo  Target: %OUT_EXE%
echo ========================================

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

if exist "%OUT_EXE%" if exist "%OUT_DIR%\exiftool_files" (
    for %%F in ("%OUT_EXE%") do set "SIZE=%%~zF"
    if !SIZE! GEQ 100000 (
        echo [skip] already installed ^(!SIZE! bytes^)
        exit /b 0
    )
)

echo Resolving latest version from exiftool.org ...
for /f "usebackq delims=" %%V in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $h=Invoke-WebRequest -UseBasicParsing 'https://exiftool.org/' -TimeoutSec 30; if($h.Content -match 'exiftool-(\d+\.\d+)_64\.zip'){ $Matches[1] } else { '' } } catch { '' }"`) do set "VER=%%V"
if "%VER%"=="" set "VER=13.59"
echo Version: %VER%

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_install_exiftool.ps1" -Version "%VER%" -OutDir "%OUT_DIR%"
if errorlevel 1 goto fail
if not exist "%OUT_EXE%" goto fail
if not exist "%OUT_DIR%\exiftool_files" goto fail
echo [OK] %OUT_EXE%
exit /b 0

:fail
echo [FAIL] Manual install:
echo   1. Download exiftool-*_64.zip from https://exiftool.org/
echo   2. Extract into %OUT_DIR%
echo   3. Rename exiftool(-k).exe to exiftool.exe
echo   4. Keep exiftool_files next to the exe
exit /b 1
