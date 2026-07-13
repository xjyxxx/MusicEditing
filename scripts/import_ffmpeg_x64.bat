@echo off
setlocal EnableDelayedExpansion

rem 从本机已下载的 BtbN x64 shared 包复制到 third_party\ffmpeg\x64
set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "DEFAULT_SRC=E:\FFmpegxuexi\ffmpeg-N-117275-g04182b5549-win64-lgpl-shared\ffmpeg-N-117275-g04182b5549-win64-lgpl-shared"
set "SRC=%~1"
if "%SRC%"=="" set "SRC=%DEFAULT_SRC%"
set "TARGET=%PROJECT_DIR%\third_party\ffmpeg\x64"

echo ========================================
echo  导入 FFmpeg x64
echo  源: %SRC%
echo  目标: %TARGET%
echo ========================================

if not exist "%SRC%\include\libavcodec\avcodec.h" (
    echo [错误] 源目录无效，请传入正确路径:
    echo   scripts\import_ffmpeg_x64.bat "E:\path\to\ffmpeg-shared"
    exit /b 1
)

if not exist "%TARGET%" mkdir "%TARGET%"

echo 复制 include / lib / bin ...
xcopy /E /I /Y "%SRC%\include" "%TARGET%\include" >nul
xcopy /E /I /Y "%SRC%\lib" "%TARGET%\lib" >nul
xcopy /E /I /Y "%SRC%\bin" "%TARGET%\bin" >nul

if not exist "%TARGET%\lib\avcodec.lib" (
    echo [错误] 未找到 avcodec.lib
    exit /b 1
)

echo [成功] FFmpeg x64 已导入到 third_party\ffmpeg\x64
echo 下一步: .\build_x64.bat

endlocal
