@echo off
setlocal EnableDelayedExpansion

rem 将 OpenCV 预编译包复制到 third_party\opencv\{x64|x86}
rem 用法:
rem   scripts\import_opencv.bat x64
rem   scripts\import_opencv.bat x86
rem   scripts\import_opencv.bat x64 "D:\APP\opencv\build"

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "ARCH=%~1"
if /I "%ARCH%"=="win32" set "ARCH=x86"
if "%ARCH%"=="" set "ARCH=x64"

if /I "%ARCH%"=="x64" (
    set "DEFAULT_SRC=D:\APP\opencv\build"
    set "LIB_SUB=x64\vc16\lib"
    set "BIN_SUB=x64\vc16\bin"
    set "INC_SUB=include"
) else if /I "%ARCH%"=="x86" (
    set "DEFAULT_SRC=D:\APP\opencv\build_x86"
    set "LIB_SUB=x86\vc16\lib"
    set "BIN_SUB=x86\vc16\bin"
    set "INC_SUB=include"
) else (
    echo [错误] 架构应为 x64 或 x86
    exit /b 1
)

set "SRC=%~2"
if "%SRC%"=="" set "SRC=%DEFAULT_SRC%"
set "TARGET=%PROJECT_DIR%\third_party\opencv\%ARCH%"

echo ========================================
echo  导入 OpenCV %ARCH%
echo  源: %SRC%
echo  目标: %TARGET%
echo ========================================

if not exist "%SRC%\%LIB_SUB%\opencv_world4120.lib" (
    echo [错误] 未找到 %SRC%\%LIB_SUB%\opencv_world4120.lib
    if /I "%ARCH%"=="x86" echo   请先运行 scripts\build_opencv_win32.bat
    exit /b 1
)

if exist "%TARGET%" rmdir /s /q "%TARGET%"
mkdir "%TARGET%\include"
mkdir "%TARGET%\lib"
mkdir "%TARGET%\bin"

echo 复制 include ...
xcopy /E /I /Y "%SRC%\%INC_SUB%\*" "%TARGET%\include\" >nul

echo 复制 lib / bin ...
copy /Y "%SRC%\%LIB_SUB%\opencv_world4120.lib" "%TARGET%\lib\" >nul
if exist "%SRC%\%LIB_SUB%\opencv_world4120d.lib" (
    copy /Y "%SRC%\%LIB_SUB%\opencv_world4120d.lib" "%TARGET%\lib\" >nul
)
copy /Y "%SRC%\%BIN_SUB%\opencv_world4120.dll" "%TARGET%\bin\" >nul
if exist "%SRC%\%BIN_SUB%\opencv_world4120d.dll" (
    copy /Y "%SRC%\%BIN_SUB%\opencv_world4120d.dll" "%TARGET%\bin\" >nul
)

if not exist "%TARGET%\lib\opencv_world4120.lib" (
    echo [错误] 导入失败
    exit /b 1
)

echo.
echo [成功] OpenCV %ARCH% 已导入
echo   %TARGET%\include
echo   %TARGET%\lib\opencv_world4120.lib
echo   %TARGET%\bin\opencv_world4120.dll
echo.

endlocal
