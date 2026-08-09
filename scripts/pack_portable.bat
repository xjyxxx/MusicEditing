@echo off
setlocal
cd /d "%~dp0\.."
echo === 打包 MusicEditing 便携版（内嵌 Python，对方不用装）===
python scripts\pack_portable.py --zip %*
if errorlevel 1 (
  echo 打包失败
  exit /b 1
)
echo.
echo 输出在 dist\ 目录 — 对方解压后双击 MusicEditing.exe
exit /b 0
