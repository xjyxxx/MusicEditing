@echo off
setlocal
cd /d "%~dp0\.."
echo === MusicEditing 一键发版 ===
echo 用法: scripts\release_oneclick.bat [--profile standard] [--no-installer] [--sign]
python scripts\release_oneclick.py %*
exit /b %ERRORLEVEL%
