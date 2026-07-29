@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "OUT_DIR=%PROJECT_DIR%\third_party\yt-dlp"
set "OUT_EXE=%OUT_DIR%\yt-dlp.exe"
set "URL_GH=https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
set "URL_MIRROR=https://ghfast.top/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

echo ========================================
echo  下载 yt-dlp.exe（链接下载引擎）
echo  目标: %OUT_EXE%
echo ========================================

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

if exist "%OUT_EXE%" (
    for %%F in ("%OUT_EXE%") do set "SIZE=%%~zF"
    if !SIZE! GEQ 1000000 (
        echo [跳过] 已存在 ^(!SIZE! bytes^)
        exit /b 0
    )
)

echo 尝试镜像下载...
curl.exe -L --ssl-no-revoke --retry 3 --retry-delay 2 -o "%OUT_EXE%" "%URL_MIRROR%"
if errorlevel 1 goto try_official

for %%F in ("%OUT_EXE%") do set "SIZE=%%~zF"
if !SIZE! LSS 1000000 goto try_official
goto success

:try_official
echo 镜像失败或不完整，尝试 GitHub 官方...
del /q "%OUT_EXE%" 2>nul
curl.exe -L --ssl-no-revoke --retry 5 --retry-delay 2 -o "%OUT_EXE%" "%URL_GH%"
if errorlevel 1 goto fail

for %%F in ("%OUT_EXE%") do set "SIZE=%%~zF"
if !SIZE! LSS 1000000 goto fail
goto success

:success
echo [完成] %OUT_EXE%
exit /b 0

:fail
echo [失败] 请手动下载 yt-dlp.exe 到:
echo   %OUT_EXE%
echo 地址: %URL_GH%
exit /b 1
