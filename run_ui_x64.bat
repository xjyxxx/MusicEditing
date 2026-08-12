@echo off

setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "BUILD_DIR=%PROJECT_DIR%\build_x64"
set "BIN=%BUILD_DIR%\bin\Release"
set "CLI=%BIN%\media_cli.exe"
set "PLAYER=%BIN%\media_player.exe"
set "ORT_LIB=%PROJECT_DIR%\third_party\onnxruntime\x64\lib\onnxruntime.lib"
set "ORT_DLL=%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime.dll"
set "NEED_BUILD=0"
set "CACHE_DIR=%PROJECT_DIR%\.cache"
set "REQ_FILE=%PROJECT_DIR%\client\scripts\requirements.txt"
set "REQ_STAMP=%CACHE_DIR%\requirements.core.stamp"

echo ========================================
echo  MusicEditing x64 UI
echo ========================================

rem 去水印 LaMa 默认 CPU EP（不捆绑 cuda_runtime，体积过大）

rem 缺 ONNX 时提示使用项目内 third_party（不再引用外部盘符）
if not exist "%ORT_LIB%" (
    echo [错误] 未找到项目内 ONNX Runtime:
    echo   %ORT_LIB%
    echo 请执行:
    echo   scripts\import_onnxruntime.bat x64 "解压后的 ORT 目录"
    echo 去水印将不可用，继续启动...
)

if not exist "%CLI%" set "NEED_BUILD=1"
if not exist "%PLAYER%" set "NEED_BUILD=1"

rem 已导入 ONNX 但构建产物里还没有对应 DLL，说明需要重新编译
if exist "%ORT_DLL%" if not exist "%BIN%\onnxruntime.dll" set "NEED_BUILD=1"

if "!NEED_BUILD!"=="1" (
    echo [提示] 正在构建 x64 工程 ...
    call "%PROJECT_DIR%\build_x64.bat"
    if errorlevel 1 (
        echo [错误] 构建失败
        exit /b 1
    )
)

if not exist "%CLI%" (
    echo [错误] 未找到 x64 media_cli.exe
    exit /b 1
)

if not exist "%PLAYER%" (
    echo [错误] 未找到 x64 media_player.exe
    exit /b 1
)

rem 兜底：确保运行时 DLL 在输出目录
if exist "%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime.dll" (
    for %%F in ("%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime*.dll") do (
        copy /Y "%%~fF" "%BIN%\" >nul 2>&1
    )
)
if exist "%PROJECT_DIR%\third_party\opencv\x64\bin\opencv_world4120.dll" (
    copy /Y "%PROJECT_DIR%\third_party\opencv\x64\bin\opencv_world4120.dll" "%BIN%\" >nul 2>&1
)

if not exist "%PROJECT_DIR%\models\lama.onnx" (
    echo [提示] 未找到 LaMa 去水印模型，正在下载（约 200MB，仅首次）...
    call "%PROJECT_DIR%\scripts\download_lama_model.bat"
    if errorlevel 1 (
        echo [警告] LaMa 模型下载失败，去水印功能将不可用
        echo         可稍后手动运行: scripts\download_lama_model.bat
    )
)

if not exist "%PROJECT_DIR%\third_party\yt-dlp\yt-dlp.exe" (
    echo [提示] 未找到 yt-dlp，正在下载到 third_party\yt-dlp\ ...
    call "%PROJECT_DIR%\scripts\download_yt_dlp.bat"
    if errorlevel 1 (
        echo [警告] yt-dlp 下载失败，链接下载功能将不可用
        echo         可稍后手动运行: scripts\download_yt_dlp.bat
    )
)
if exist "%PROJECT_DIR%\third_party\yt-dlp\yt-dlp.exe" (
    copy /Y "%PROJECT_DIR%\third_party\yt-dlp\yt-dlp.exe" "%BIN%\" >nul 2>&1
)

if not exist "%PROJECT_DIR%\third_party\exiftool\exiftool.exe" (
    echo [提示] 未找到 ExifTool，正在下载到 third_party\exiftool\ ...
    call "%PROJECT_DIR%\scripts\download_exiftool.bat"
    if errorlevel 1 (
        echo [警告] ExifTool 下载失败，图片 EXIF 面板将不可用
        echo         可稍后手动运行: scripts\download_exiftool.bat
    )
)
if exist "%PROJECT_DIR%\third_party\exiftool\exiftool.exe" (
    copy /Y "%PROJECT_DIR%\third_party\exiftool\exiftool.exe" "%BIN%\" >nul 2>&1
    if exist "%PROJECT_DIR%\third_party\exiftool\exiftool_files" (
        xcopy /E /I /Y "%PROJECT_DIR%\third_party\exiftool\exiftool_files" "%BIN%\exiftool_files\" >nul 2>&1
    )
)

set PYTHONUTF8=1

rem ---- Python 依赖：仅在 requirements 变更或强制时 pip；可用 MUSIC_SKIP_PIP=1 完全跳过 ----
if /I "%MUSIC_SKIP_PIP%"=="1" (
    echo [提示] 已设置 MUSIC_SKIP_PIP=1，跳过 pip
    goto :after_pip
)

if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%" >nul 2>&1

set "NEED_PIP=1"
if /I "%MUSIC_FORCE_PIP%"=="1" goto :do_pip
if exist "%REQ_STAMP%" if exist "%REQ_FILE%" (
    for %%A in ("%REQ_FILE%") do set "REQ_MTIME=%%~tA"
    set /p OLD_STAMP=<"%REQ_STAMP%"
    if "!OLD_STAMP!"=="!REQ_MTIME!" set "NEED_PIP=0"
)

if "!NEED_PIP!"=="0" (
    echo [提示] 依赖未变，跳过 pip（改 requirements 或设 MUSIC_FORCE_PIP=1 可重装）
    goto :after_core_pip
)
:do_pip
echo [提示] 正在检查 / 安装 Python 依赖 ...
pip install -r "%REQ_FILE%" -q
if errorlevel 1 (
    echo [错误] Python 依赖安装失败
    exit /b 1
)
for %%A in ("%REQ_FILE%") do echo %%~tA>"%REQ_STAMP%"
:after_core_pip

if exist "%PROJECT_DIR%\third_party\PySceneDetect\scenedetect\__init__.py" (
    set "SD_STAMP=%CACHE_DIR%\scenedetect.stamp"
    set "NEED_SD=1"
    if exist "%SD_STAMP%" set "NEED_SD=0"
    if /I "%MUSIC_FORCE_PIP%"=="1" set "NEED_SD=1"
    if "!NEED_SD!"=="1" (
        pip install -e "%PROJECT_DIR%\third_party\PySceneDetect" -q
        if errorlevel 1 (
            echo [警告] PySceneDetect 安装失败，游戏高光将回退时间规则
        ) else (
            echo ok>"%SD_STAMP%"
        )
    )
)

:after_pip

set "PATH=%BIN%;%PATH%"
python "%PROJECT_DIR%\client\scripts\main.py"

endlocal
