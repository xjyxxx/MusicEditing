@echo off
setlocal
cd /d "%~dp0\.."
echo === 只打包（外发：zip + 内嵌 Python + 无业务源码）===
python scripts\pack_for_share.py %*
if errorlevel 1 exit /b 1
echo.
echo 输出: dist\MusicEditing_Share_*.zip
echo 对方无需安装 Visual Studio / Python，解压双击即可
exit /b 0
