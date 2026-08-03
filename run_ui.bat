@echo off
setlocal

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "CLI=%PROJECT_DIR%\build\bin\Release\media_cli.exe"
set "PLAYER=%PROJECT_DIR%\build\bin\Release\media_player.exe"

if not exist "%CLI%" (
    echo [错误] 未找到 media_cli.exe，请先运行 .\build.bat
    exit /b 1
)

if not exist "%PLAYER%" (
    echo [错误] 未找到 media_player.exe，请先运行 .\build.bat
    exit /b 1
)

set PYTHONUTF8=1
pip install -r "%PROJECT_DIR%\client\scripts\requirements.txt" -q
if errorlevel 1 (
    echo [错误] Python 依赖安装失败
    exit /b 1
)
if exist "%PROJECT_DIR%\third_party\PySceneDetect\scenedetect\__init__.py" (
    pip install -e "%PROJECT_DIR%\third_party\PySceneDetect" -q
    if errorlevel 1 (
        echo [警告] PySceneDetect 安装失败，游戏高光将回退时间规则
    )
)

set "PATH=%PROJECT_DIR%\build\bin\Release;%PATH%"
python "%PROJECT_DIR%\client\scripts\main.py"

endlocal
