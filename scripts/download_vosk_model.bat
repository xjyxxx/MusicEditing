@echo off
setlocal

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "MODEL_DIR=%PROJECT_DIR%\models"
set "MODEL_NAME=vosk-model-small-cn-0.22"
set "MODEL_PATH=%MODEL_DIR%\%MODEL_NAME%"
set "ZIP_PATH=%MODEL_DIR%\%MODEL_NAME%.zip"
set "MODEL_URL=https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"
set "MODEL_URL_MIRROR=https://hf-mirror.com/alphacep/vosk-model-small-cn-0.22/resolve/main/vosk-model-small-cn-0.22.zip"

echo ========================================
echo  下载 Vosk 中文小模型（演讲金句 ASR）
echo  目标: %MODEL_PATH%
echo  约 40MB，解压后需含 am\final.mdl
echo ========================================

if exist "%MODEL_PATH%\am\final.mdl" (
    echo [跳过] 模型已存在
    exit /b 0
)

if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"

echo 尝试官方源下载...
curl.exe -L --ssl-no-revoke --retry 3 --retry-delay 2 -o "%ZIP_PATH%" "%MODEL_URL%"
if errorlevel 1 goto try_mirror

for %%F in ("%ZIP_PATH%") do set "SIZE=%%~zF"
if not defined SIZE goto try_mirror
if %SIZE% LSS 5000000 goto try_mirror
goto unzip

:try_mirror
echo 官方源失败，尝试镜像...
del /q "%ZIP_PATH%" 2>nul
curl.exe -L --ssl-no-revoke --retry 5 --retry-delay 2 -o "%ZIP_PATH%" "%MODEL_URL_MIRROR%"
if errorlevel 1 goto fail
for %%F in ("%ZIP_PATH%") do set "SIZE=%%~zF"
if %SIZE% LSS 5000000 goto fail

:unzip
echo 正在解压...
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%MODEL_DIR%' -Force"
if errorlevel 1 goto fail

if not exist "%MODEL_PATH%\am\final.mdl" (
    echo [错误] 解压后未找到 am\final.mdl
    goto fail
)

del /q "%ZIP_PATH%" 2>nul
echo [完成] Vosk 模型已就绪: %MODEL_PATH%
echo 可在智能切片选择「演讲金句」后点击 AI 智能分析。
exit /b 0

:fail
echo [失败] 请手动下载:
echo   %MODEL_URL%
echo 解压到: %MODEL_PATH%
exit /b 1
