@echo off
setlocal
cd /d "%~dp0\.."
echo === 外发打包 MusicEditing（zip + 内嵌 Python + 严格无业务源码）===
echo 禁止带 --ship-source；输出 dist\MusicEditing_Share_*.zip
echo.
python scripts\pack_for_share.py %*
if errorlevel 1 (
  echo 打包失败
  exit /b 1
)
echo.
echo 把 dist\ 里的 MusicEditing_Share_*.zip 发给对方即可
echo 对方解压后双击 MusicEditing.exe；闪退请装 VC++ 2015-2022 x64
exit /b 0
