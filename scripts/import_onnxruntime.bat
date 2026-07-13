@echo off
setlocal EnableDelayedExpansion

rem 将 ONNX Runtime 预编译包复制到 third_party\onnxruntime\{x64|x86}
rem 用法:
rem   scripts\import_onnxruntime.bat x64
rem   scripts\import_onnxruntime.bat x64 "E:\FFmpegxuexi\onnxruntime-win-x64-gpu_cuda13-1.27.1\onnxruntime-win-x64-gpu_cuda13-1.27.1"

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "ARCH=%~1"
if /I "%ARCH%"=="win32" set "ARCH=x86"
if "%ARCH%"=="" set "ARCH=x64"

if /I "%ARCH%"=="x64" (
    set "DEFAULT_SRC=E:\FFmpegxuexi\onnxruntime-win-x64-gpu_cuda13-1.27.1\onnxruntime-win-x64-gpu_cuda13-1.27.1"
) else (
    echo [错误] 当前仅支持 x64 预编译包导入
    exit /b 1
)

set "SRC=%~2"
if "%SRC%"=="" set "SRC=%DEFAULT_SRC%"
set "TARGET=%PROJECT_DIR%\third_party\onnxruntime\%ARCH%"

echo ========================================
echo  导入 ONNX Runtime %ARCH%
echo  源: %SRC%
echo  目标: %TARGET%
echo ========================================

if not exist "%SRC%\lib\onnxruntime.lib" (
    echo [错误] 未找到 %SRC%\lib\onnxruntime.lib
    echo   请指定已解压的 ONNX Runtime 目录，或运行 scripts\setup_onnxruntime_x64.bat
    exit /b 1
)

if not exist "%SRC%\include\onnxruntime_cxx_api.h" (
    echo [错误] 未找到头文件 onnxruntime_cxx_api.h
    exit /b 1
)

rem GPU 包 dll 在 lib\；CPU 包通常在 bin\
set "DLL_SRC=%SRC%\bin"
if not exist "%DLL_SRC%\onnxruntime.dll" set "DLL_SRC=%SRC%\lib"

if exist "%TARGET%" rmdir /s /q "%TARGET%"
mkdir "%TARGET%\include"
mkdir "%TARGET%\lib"
mkdir "%TARGET%\bin"

echo 复制 include ...
xcopy /E /I /Y "%SRC%\include\*" "%TARGET%\include\" >nul

echo 复制 lib ...
for %%F in ("%SRC%\lib\*.lib") do copy /Y "%%~fF" "%TARGET%\lib\" >nul

echo 复制 bin ^(dll 源: %DLL_SRC%^) ...
for %%F in ("%DLL_SRC%\onnxruntime*.dll") do copy /Y "%%~fF" "%TARGET%\bin\" >nul

if not exist "%TARGET%\lib\onnxruntime.lib" (
    echo [错误] 导入失败: 缺少 onnxruntime.lib
    exit /b 1
)
if not exist "%TARGET%\bin\onnxruntime.dll" (
    echo [错误] 导入失败: 缺少 onnxruntime.dll
    exit /b 1
)

echo.
echo [成功] ONNX Runtime %ARCH% 已导入
echo   %TARGET%\include
echo   %TARGET%\lib\onnxruntime.lib
echo   %TARGET%\bin\onnxruntime.dll
for %%F in ("%TARGET%\bin\onnxruntime*.dll") do echo   %%~fF
echo.

endlocal
