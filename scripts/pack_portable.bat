@echo off
setlocal
cd /d "%~dp0\.."
echo === 打包 MusicEditing 便携版（内嵌 Python，对方不用装）===
echo 档位: 默认 standard；可用 --profile slim ^| standard ^| full
echo 例: scripts\pack_portable.bat --profile slim
echo 签名: 设 MUSIC_CODE_SIGN_THUMBPRINT 并加 --sign
python scripts\pack_portable.py --zip %*
if errorlevel 1 (
  echo 打包失败
  exit /b 1
)
echo.
echo 输出在 dist\ 目录 — 对方解压后双击 MusicEditing.exe
echo 对方无需装 Visual Studio / Python；极少数闪退再装 VC++ 可再发行组件（不是 VS）
exit /b 0
