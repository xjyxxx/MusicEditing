@echo off
setlocal
cd /d "%~dp0\.."
echo === 验收便携包 ===
python scripts\accept_portable.py %*
exit /b %ERRORLEVEL%
