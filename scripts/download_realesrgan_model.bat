@echo off
setlocal

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "MODEL_DIR=%PROJECT_DIR%\models"
set "MODEL_PATH=%MODEL_DIR%\realesr-general-x4v3.onnx"
set "MODEL_URL_MIRROR=https://hf-mirror.com/Heliosoph/realesrgan-onnx/resolve/main/realesr-general-x4v3.onnx"
set "MODEL_URL=https://huggingface.co/Heliosoph/realesrgan-onnx/resolve/main/realesr-general-x4v3.onnx"

echo ========================================
echo  下载 Real-ESRGAN ONNX 模型（画质超分）
echo  目标: %MODEL_PATH%
echo ========================================

if exist "%MODEL_PATH%" (
    echo [跳过] 模型已存在
    exit /b 0
)

if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"

echo 尝试镜像下载（约 5MB）...
curl.exe -L --ssl-no-revoke --retry 3 --retry-delay 2 -o "%MODEL_PATH%" "%MODEL_URL_MIRROR%"
if errorlevel 1 goto try_official

for %%F in ("%MODEL_PATH%") do set "SIZE=%%~zF"
if %SIZE% LSS 1000000 goto try_official
goto success

:try_official
echo 镜像失败，尝试官方 HuggingFace...
del /q "%MODEL_PATH%" 2>nul
curl.exe -L --ssl-no-revoke --retry 5 --retry-delay 2 -o "%MODEL_PATH%" "%MODEL_URL%"
if errorlevel 1 goto fail

for %%F in ("%MODEL_PATH%") do set "SIZE=%%~zF"
if %SIZE% LSS 1000000 goto fail
goto success

:fail
echo [错误] 下载失败，请手动下载其一:
echo   %MODEL_URL_MIRROR%
echo   %MODEL_URL%
echo 保存为: %MODEL_PATH%
del /q "%MODEL_PATH%" 2>nul
exit /b 1

:success
echo [成功] Real-ESRGAN 模型已保存: %MODEL_PATH%
endlocal
exit /b 0
