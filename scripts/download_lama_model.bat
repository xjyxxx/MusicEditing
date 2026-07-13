@echo off
setlocal

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "MODEL_DIR=%PROJECT_DIR%\models"
set "MODEL_PATH=%MODEL_DIR%\lama.onnx"
set "MODEL_URL=https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama.onnx"

echo ========================================
echo  下载 LaMa ONNX 模型（去水印）
echo  目标: %MODEL_PATH%
echo ========================================

if exist "%MODEL_PATH%" (
    echo [跳过] 模型已存在
    exit /b 0
)

if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"

echo 下载中（约 200MB）...
curl.exe -L --ssl-no-revoke --retry 5 --retry-delay 2 -o "%MODEL_PATH%" "%MODEL_URL%"
if errorlevel 1 (
    echo [错误] 下载失败，请手动下载:
    echo   %MODEL_URL%
    echo 保存为: %MODEL_PATH%
    exit /b 1
)

for %%F in ("%MODEL_PATH%") do set "SIZE=%%~zF"
if %SIZE% LSS 10000000 (
    echo [错误] 文件过小，可能下载失败
    del /q "%MODEL_PATH%" 2>nul
    exit /b 1
)

echo [成功] LaMa 模型已保存: %MODEL_PATH%

endlocal
