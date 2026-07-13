@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "TARGET=%PROJECT_DIR%\third_party\ffmpeg\x64"
set "TEMP_ZIP=%PROJECT_DIR%\third_party\ffmpeg\x64_download.zip"
set "TEMP_DIR=%PROJECT_DIR%\third_party\ffmpeg\_x64_extract"

rem 优先 4.4 shared（与旧 decode API 兼容）；失败可改 latest
set "FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2024-09-30-15-36/ffmpeg-N-117275-g04182b5549-win64-lgpl-shared.zip"
set "MIN_SIZE=10000000"

echo ========================================
echo  安装 FFmpeg x64 到 third_party\ffmpeg\x64
echo ========================================

if exist "%TARGET%\lib\avcodec.lib" (
    echo [跳过] 已存在 %TARGET%\lib\avcodec.lib
    goto :done
)

if not exist "%TARGET%" mkdir "%TARGET%"

echo 下载: %FFMPEG_URL%
curl.exe -L --retry 3 -o "%TEMP_ZIP%" "%FFMPEG_URL%"
if errorlevel 1 goto :download_fail

for %%F in ("%TEMP_ZIP%") do set "ZIP_SIZE=%%~zF"
if not defined ZIP_SIZE set "ZIP_SIZE=0"
if %ZIP_SIZE% LSS %MIN_SIZE% (
    echo [错误] 下载文件过小 ^(%ZIP_SIZE% 字节^)，可能 URL 失效
    goto :download_fail
)

if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%"
mkdir "%TEMP_DIR%"

echo 解压中...
tar -xf "%TEMP_ZIP%" -C "%TEMP_DIR%"
if errorlevel 1 (
    powershell -NoProfile -Command "Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%TEMP_DIR%' -Force"
    if errorlevel 1 (
        echo [错误] 解压失败
        exit /b 1
    )
)

rem 查找含 include/lib/bin 的子目录
set "SRC_ROOT="
for /d %%D in ("%TEMP_DIR%\*") do (
    if exist "%%D\include\libavcodec\avcodec.h" set "SRC_ROOT=%%D"
)
if not defined SRC_ROOT (
    if exist "%TEMP_DIR%\include\libavcodec\avcodec.h" set "SRC_ROOT=%TEMP_DIR%"
)

if not defined SRC_ROOT (
    echo [错误] 解压包结构无法识别，请手动复制 include/lib/bin 到 third_party\ffmpeg\x64
    exit /b 1
)
goto :copy_files

:download_fail
echo [错误] 下载失败，请手动下载 win64-lgpl-shared.zip 并解压到 third_party\ffmpeg\x64
echo 说明见 third_party\ffmpeg\README.md
exit /b 1

:copy_files

echo 复制到 %TARGET% ...
xcopy /E /I /Y "%SRC_ROOT%\include" "%TARGET%\include" >nul
xcopy /E /I /Y "%SRC_ROOT%\lib" "%TARGET%\lib" >nul
xcopy /E /I /Y "%SRC_ROOT%\bin" "%TARGET%\bin" >nul

if not exist "%TARGET%\lib\avcodec.lib" (
    echo [错误] 未找到 avcodec.lib，可能下载了纯 bin 包而非 shared 版
    exit /b 1
)

del /q "%TEMP_ZIP%" 2>nul
rmdir /s /q "%TEMP_DIR%" 2>nul

:done
echo.
echo [成功] FFmpeg x64 已就绪: %TARGET%
echo 下一步: build_x64.bat
echo.

endlocal
