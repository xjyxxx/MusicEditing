@echo off
setlocal

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "CLI=%PROJECT_DIR%\build\bin\Release\media_cli.exe"

if not exist "%CLI%" (
    echo [错误] 未找到 media_cli.exe，请先运行 .\build.bat
    exit /b 1
)

set "VIDEO=%~1"
if "%VIDEO%"=="" (
    set "VIDEO=E:\FFmpegxuexi\simplest_ffmpeg_player\simplest_ffmpeg_decoder\Titanic.mkv"
    echo 未指定视频，使用默认测试文件:
    echo   %VIDEO%
    echo.
)

if not exist "%VIDEO%" (
    echo [错误] 视频文件不存在: %VIDEO%
    echo 用法: run_test.bat [视频路径]
    exit /b 1
)

echo === 版本 ===
"%CLI%" version
echo.

echo === 探测视频 ===
"%CLI%" probe "%VIDEO%"
if errorlevel 1 (
    echo [错误] 视频探测失败
    exit /b 1
)
echo.

echo === 遍历前 10 帧 ===
"%CLI%" iterate "%VIDEO%" 10
if errorlevel 1 (
    echo [错误] 帧遍历失败
    exit /b 1
)

echo.
echo [成功] 测试完成
endlocal
