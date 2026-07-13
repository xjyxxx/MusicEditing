@echo off
setlocal

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "CLI=%PROJECT_DIR%\build_x64\bin\Release\media_cli.exe"

if not exist "%CLI%" (
    echo [错误] 未找到 x64 media_cli.exe，请先运行 .\build_x64.bat
    exit /b 1
)

set "PATH=%PROJECT_DIR%\build_x64\bin\Release;%PATH%"
set "VIDEO=%~1"
if "%VIDEO%"=="" (
    set "VIDEO=%PROJECT_DIR%\tests\test_video.mp4"
    echo 未指定视频，使用: %VIDEO%
    echo.
)

if not exist "%VIDEO%" (
    echo [错误] 视频不存在: %VIDEO%
    exit /b 1
)

echo === 版本 ===
"%CLI%" version
echo.
echo === 探测 ===
"%CLI%" probe "%VIDEO%"
echo.
echo === 遍历 10 帧 ===
"%CLI%" iterate "%VIDEO%" 10

endlocal
