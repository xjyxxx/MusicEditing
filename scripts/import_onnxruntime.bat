@echo off
setlocal EnableDelayedExpansion

rem 将 ONNX Runtime 预编译包复制到项目内 third_party\onnxruntime\{x64|x86}
rem 用法:
rem   scripts\import_onnxruntime.bat x64
rem       → 若 third_party 已有完整包则跳过（不依赖外部目录）
rem   scripts\import_onnxruntime.bat x64 "<已解压的 ORT 包路径>"
rem       → 一次性导入到 third_party（此后构建只读项目内路径）

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "ARCH=%~1"
if /I "%ARCH%"=="win32" set "ARCH=x86"
if "%ARCH%"=="" set "ARCH=x64"

if /I not "%ARCH%"=="x64" (
    echo [错误] 当前仅支持 x64 预编译包导入
    exit /b 1
)

set "TARGET=%PROJECT_DIR%\third_party\onnxruntime\%ARCH%"
set "SRC=%~2"

echo ========================================
echo  导入 ONNX Runtime %ARCH%
echo  目标: %TARGET%
echo ========================================

rem 未指定源路径：只检查项目内是否已就绪
if "%SRC%"=="" (
    if exist "%TARGET%\lib\onnxruntime.lib" if exist "%TARGET%\bin\onnxruntime.dll" (
        echo [跳过] 项目内已有 ONNX Runtime，无需外部路径
        echo   %TARGET%\lib\onnxruntime.lib
        echo   %TARGET%\bin\onnxruntime.dll
        for %%F in ("%TARGET%\bin\onnxruntime*.dll") do echo   %%~fF
        exit /b 0
    )
    echo [错误] 项目内缺少 third_party\onnxruntime\%ARCH%
    echo   请将 GPU 包解压后执行一次:
    echo   scripts\import_onnxruntime.bat x64 "解压目录"
    echo   推荐包名: onnxruntime-win-x64-gpu_cuda12-*.zip
    exit /b 1
)

if not exist "%SRC%\lib\onnxruntime.lib" (
    echo [错误] 未找到 %SRC%\lib\onnxruntime.lib
    exit /b 1
)

if not exist "%SRC%\include\onnxruntime_cxx_api.h" (
    echo [错误] 未找到头文件 onnxruntime_cxx_api.h
    exit /b 1
)

rem GPU 包 dll 常在 lib\；CPU 包通常在 bin\
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

echo onnxruntime-win-x64-gpu_cuda12-1.27.1> "%PROJECT_DIR%\third_party\onnxruntime\VERSION.txt"
echo bundled=%DATE% %TIME%>> "%PROJECT_DIR%\third_party\onnxruntime\VERSION.txt"

echo.
echo [成功] ONNX Runtime 已写入项目内（不依赖外部路径）
echo   %TARGET%\include
echo   %TARGET%\lib\onnxruntime.lib
echo   %TARGET%\bin\onnxruntime.dll
for %%F in ("%TARGET%\bin\onnxruntime*.dll") do echo   %%~fF
echo.

endlocal
