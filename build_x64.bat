@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "BUILD_DIR=%PROJECT_DIR%\build_x64"
set "FFMPEG_X64=%PROJECT_DIR%\third_party\ffmpeg\x64\lib\avcodec.lib"
set "OPENCV_X64=%PROJECT_DIR%\third_party\opencv\x64\lib\opencv_world4120.lib"

echo ========================================
echo  MusicEditing x64 构建
echo ========================================

if not exist "%FFMPEG_X64%" (
    echo [提示] 未找到 x64 FFmpeg，正在导入本机已下载包 ...
    call "%PROJECT_DIR%\scripts\import_ffmpeg_x64.bat"
    if errorlevel 1 exit /b 1
)

if not exist "%OPENCV_X64%" (
    echo [提示] 未找到本地 OpenCV x64，正在从 D:\APP\opencv 导入 ...
    call "%PROJECT_DIR%\scripts\import_opencv.bat" x64
    if errorlevel 1 (
        echo [警告] OpenCV 导入失败，将尝试外部 OPENCV_DIR 或禁用滤镜
    )
)

echo Stopping media_player / media_cli ...
taskkill /F /IM media_player.exe >nul 2>&1
taskkill /F /IM media_cli.exe >nul 2>&1
taskkill /F /IM media_engine_test.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

cmake -S "%PROJECT_DIR%" -B "%BUILD_DIR%" -G "Visual Studio 18 2026" -A x64
if errorlevel 1 (
    echo [错误] CMake 配置失败
    exit /b 1
)

cmake --build "%BUILD_DIR%" --config Release
if errorlevel 1 (
    echo [错误] 编译失败
    exit /b 1
)

if exist "%PROJECT_DIR%\third_party\opencv\x64\bin\opencv_world4120.dll" (
    copy /Y "%PROJECT_DIR%\third_party\opencv\x64\bin\opencv_world4120.dll" "%BUILD_DIR%\bin\Release\" >nul
)

echo.
echo [成功] x64 构建完成
echo 输出目录: %BUILD_DIR%\bin\Release
echo 运行 UI:  run_ui_x64.bat
echo.

endlocal
