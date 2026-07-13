@echo off
setlocal EnableDelayedExpansion

rem 去掉末尾反斜杠，避免 "%VAR%" 引号被转义
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "BUILD_DIR=%PROJECT_DIR%\build"
set "OPENCV_X86=%PROJECT_DIR%\third_party\opencv\x86\lib\opencv_world4120.lib"

echo ========================================
echo  MusicEditing Win32 构建
echo ========================================

if not exist "%OPENCV_X86%" (
    echo [提示] 未找到本地 OpenCV x86，尝试从 D:\APP\opencv 导入 ...
    call "%PROJECT_DIR%\scripts\import_opencv.bat" x86
    if errorlevel 1 (
        echo [警告] OpenCV x86 导入失败，将尝试外部 OPENCV_DIR 或禁用滤镜
    )
)

rem Release output may be locked while run_ui / media_player is running
echo Stopping media_player / media_cli ...
taskkill /F /IM media_player.exe >nul 2>&1
taskkill /F /IM media_cli.exe >nul 2>&1
taskkill /F /IM media_engine_test.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

cmake -S "%PROJECT_DIR%" -B "%BUILD_DIR%" -G "Visual Studio 18 2026" -A Win32
if errorlevel 1 (
    echo [错误] CMake 配置失败
    exit /b 1
)

cmake --build "%BUILD_DIR%" --config Release
if errorlevel 1 (
    echo [错误] 编译失败
    exit /b 1
)

echo.
echo [成功] 构建完成
echo 输出目录: %BUILD_DIR%\bin\Release
echo.
echo 运行 UI:    run_ui.bat
echo 运行测试:   run_test.bat
echo.

endlocal
