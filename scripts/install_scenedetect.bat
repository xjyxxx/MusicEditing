@echo off
REM 安装仓库内 third_party/PySceneDetect（供游戏高光场景切点）
setlocal
cd /d "%~dp0.."

set "VENDOR=%CD%\third_party\PySceneDetect"

if not exist "%VENDOR%\scenedetect\__init__.py" (
  echo [错误] 未找到仓库内源码: %VENDOR%\scenedetect
  echo 请确认 third_party\PySceneDetect 已随仓库提交。
  exit /b 1
)

echo 从仓库第三方目录安装 scenedetect…
python -m pip install -e "%VENDOR%"
if errorlevel 1 (
  echo editable 失败，尝试直接路径安装…
  python -m pip install "%VENDOR%"
)
if errorlevel 1 (
  echo 安装失败。
  exit /b 1
)

python -c "from scenedetect import AdaptiveDetector; import scenedetect; print('scenedetect OK', scenedetect.__version__)"
if errorlevel 1 exit /b 1
echo 完成。
endlocal
