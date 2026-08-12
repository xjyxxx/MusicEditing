@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "CLI=%PROJECT_DIR%\build\bin\Release\media_cli.exe"
set "PLAYER=%PROJECT_DIR%\build\bin\Release\media_player.exe"
set "CACHE_DIR=%PROJECT_DIR%\.cache"
set "REQ_FILE=%PROJECT_DIR%\client\scripts\requirements.txt"
set "REQ_STAMP=%CACHE_DIR%\requirements.core.stamp"

if not exist "%CLI%" (
    echo [错误] 未找到 media_cli.exe，请先运行 .\build.bat
    exit /b 1
)

if not exist "%PLAYER%" (
    echo [错误] 未找到 media_player.exe，请先运行 .\build.bat
    exit /b 1
)

set PYTHONUTF8=1

if /I "%MUSIC_SKIP_PIP%"=="1" goto :after_pip

if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%" >nul 2>&1
set "NEED_PIP=1"
if /I "%MUSIC_FORCE_PIP%"=="1" goto :do_pip
if exist "%REQ_STAMP%" if exist "%REQ_FILE%" (
    for %%A in ("%REQ_FILE%") do set "REQ_MTIME=%%~tA"
    set /p OLD_STAMP=<"%REQ_STAMP%"
    if "!OLD_STAMP!"=="!REQ_MTIME!" set "NEED_PIP=0"
)
if "!NEED_PIP!"=="0" (
    echo [提示] 依赖未变，跳过 pip
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
    if not exist "%SD_STAMP%" (
        pip install -e "%PROJECT_DIR%\third_party\PySceneDetect" -q
        if errorlevel 1 (
            echo [警告] PySceneDetect 安装失败，游戏高光将回退时间规则
        ) else (
            echo ok>"%SD_STAMP%"
        )
    )
)

:after_pip

set "PATH=%PROJECT_DIR%\build\bin\Release;%PATH%"
python "%PROJECT_DIR%\client\scripts\main.py"

endlocal
