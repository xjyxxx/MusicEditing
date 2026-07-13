@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "ORT_VERSION=1.27.1"
set "ORT_GPU_DIR=E:\FFmpegxuexi\onnxruntime-win-x64-gpu_cuda13-%ORT_VERSION%\onnxruntime-win-x64-gpu_cuda13-%ORT_VERSION%"
set "ORT_ZIP=onnxruntime-win-x64-%ORT_VERSION%.zip"
set "ORT_URL=https://github.com/microsoft/onnxruntime/releases/download/v%ORT_VERSION%/%ORT_ZIP%"

rem 下载/解压放在 FFmpegxuexi，不进项目 git
set "EXTERN_ROOT=E:\FFmpegxuexi\onnxruntime"
set "DOWNLOAD_DIR=%EXTERN_ROOT%\downloads"
set "EXTRACT_ROOT=%EXTERN_ROOT%"
set "SRC_DIR=%ORT_GPU_DIR%"
if not exist "%SRC_DIR%\lib\onnxruntime.lib" (
    set "SRC_DIR=%EXTERN_ROOT%\onnxruntime-win-x64-%ORT_VERSION%"
)
set "TARGET_LIB=%PROJECT_DIR%\third_party\onnxruntime\x64\lib\onnxruntime.lib"
set "TARGET_DLL=%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime.dll"

echo ========================================
echo  安装 ONNX Runtime x64 到 third_party\onnxruntime\x64
echo  外部目录: %EXTERN_ROOT%
echo ========================================

if exist "%TARGET_LIB%" if exist "%TARGET_DLL%" (
    echo [跳过] 已存在 %TARGET_LIB% 与 %TARGET_DLL%
    goto :import
)

if not exist "%EXTERN_ROOT%" mkdir "%EXTERN_ROOT%"
if not exist "%DOWNLOAD_DIR%" mkdir "%DOWNLOAD_DIR%"

set "ZIP_PATH=%DOWNLOAD_DIR%\%ORT_ZIP%"

if not exist "%SRC_DIR%\lib\onnxruntime.lib" (
    if exist "%ZIP_PATH%" (
        for %%A in ("%ZIP_PATH%") do if %%~zA LSS 60000000 (
            echo [警告] zip 不完整 ^(%%~zA 字节^)，重新下载...
            del /f /q "%ZIP_PATH%"
        )
    )
    if not exist "%ZIP_PATH%" (
        echo 下载: %ORT_URL%
        set "ZIP_PART=%ZIP_PATH%.part"
        if exist "!ZIP_PART!" del /f /q "!ZIP_PART!"
        curl.exe -L --ssl-no-revoke --retry 5 --retry-delay 2 -o "!ZIP_PART!" "%ORT_URL%"
        if errorlevel 1 (
            echo [错误] 下载失败
            exit /b 1
        )
        move /Y "!ZIP_PART!" "%ZIP_PATH%" >nul
    )

    echo 解压到 %EXTERN_ROOT% ...
    tar -xf "%ZIP_PATH%" -C "%EXTRACT_ROOT%" 2>nul
    if errorlevel 1 (
        powershell -NoProfile -Command "Expand-Archive -Path '%ZIP_PATH%' -DestinationPath '%EXTRACT_ROOT%' -Force"
        if errorlevel 1 (
            echo [错误] 解压失败，请删除损坏的 zip 后重试
            exit /b 1
        )
    )
)

if not exist "%SRC_DIR%\lib\onnxruntime.lib" (
    echo [错误] 解压后未找到 %SRC_DIR%\lib\onnxruntime.lib
    exit /b 1
)

:import
call "%PROJECT_DIR%\scripts\import_onnxruntime.bat" x64 "%SRC_DIR%"
if errorlevel 1 exit /b 1

echo.
echo [成功] ONNX Runtime x64 已就绪
echo 下一步: scripts\download_lama_model.bat  （可选，去水印模型）
echo         build_x64.bat
echo.

endlocal
