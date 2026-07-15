@echo off
setlocal EnableDelayedExpansion

rem 下载 CPU 版 ORT 到项目内缓存并导入（可选；GPU 包请手动解压后 import）
rem GPU 推荐: 解压 onnxruntime-win-x64-gpu_cuda12-*.zip 后执行
rem   scripts\import_onnxruntime.bat x64 "<解压目录>"

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "ORT_VERSION=1.27.1"
set "ORT_ZIP=onnxruntime-win-x64-%ORT_VERSION%.zip"
set "ORT_URL=https://github.com/microsoft/onnxruntime/releases/download/v%ORT_VERSION%/%ORT_ZIP%"

rem 全部落在项目 third_party 内，不写外部盘符
set "CACHE_ROOT=%PROJECT_DIR%\third_party\onnxruntime\_cache"
set "DOWNLOAD_DIR=%CACHE_ROOT%\downloads"
set "EXTRACT_ROOT=%CACHE_ROOT%"
set "SRC_DIR=%EXTRACT_ROOT%\onnxruntime-win-x64-%ORT_VERSION%"
set "TARGET_LIB=%PROJECT_DIR%\third_party\onnxruntime\x64\lib\onnxruntime.lib"
set "TARGET_DLL=%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime.dll"

echo ========================================
echo  安装 ONNX Runtime x64 到 third_party\onnxruntime\x64
echo  缓存目录: %CACHE_ROOT%
echo ========================================

if exist "%TARGET_LIB%" if exist "%TARGET_DLL%" (
    echo [跳过] 项目内已存在 ONNX Runtime
    exit /b 0
)

if not exist "%CACHE_ROOT%" mkdir "%CACHE_ROOT%"
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
        echo 下载 ^(CPU 包^): %ORT_URL%
        echo 若需 GPU CUDA12 包，请自行下载解压后:
        echo   scripts\import_onnxruntime.bat x64 "解压目录"
        set "ZIP_PART=%ZIP_PATH%.part"
        if exist "!ZIP_PART!" del /f /q "!ZIP_PART!"
        curl.exe -L --ssl-no-revoke --retry 5 --retry-delay 2 -o "!ZIP_PART!" "%ORT_URL%"
        if errorlevel 1 (
            echo [错误] 下载失败
            exit /b 1
        )
        move /Y "!ZIP_PART!" "%ZIP_PATH%" >nul
    )

    echo 解压到 %EXTRACT_ROOT% ...
    tar -xf "%ZIP_PATH%" -C "%EXTRACT_ROOT%" 2>nul
    if errorlevel 1 (
        powershell -NoProfile -Command "Expand-Archive -Path '%ZIP_PATH%' -DestinationPath '%EXTRACT_ROOT%' -Force"
        if errorlevel 1 (
            echo [错误] 解压失败
            exit /b 1
        )
    )
)

if not exist "%SRC_DIR%\lib\onnxruntime.lib" (
    echo [错误] 解压后未找到 %SRC_DIR%\lib\onnxruntime.lib
    exit /b 1
)

call "%PROJECT_DIR%\scripts\import_onnxruntime.bat" x64 "%SRC_DIR%"
if errorlevel 1 exit /b 1

echo.
echo [成功] ONNX Runtime x64 已就绪（项目内）
echo 下一步: scripts\download_lama_model.bat
echo         build_x64.bat
echo.

endlocal
