@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

echo === 构建 MusicEditing 安装包（Inno Setup）===

REM 1) 定位便携目录
set "PORTABLE="
if not "%~1"=="" (
  set "PORTABLE=%~1"
) else (
  for /f "delims=" %%D in ('dir /b /ad /o-d dist\MusicEditing_Portable_* 2^>nul') do (
    if not defined PORTABLE set "PORTABLE=dist\%%D"
  )
)

if not defined PORTABLE (
  echo [提示] 未找到便携目录，先打 standard 包…
  python scripts\pack_portable.py --profile standard --zip
  if errorlevel 1 exit /b 1
  for /f "delims=" %%D in ('dir /b /ad /o-d dist\MusicEditing_Portable_* 2^>nul') do (
    if not defined PORTABLE set "PORTABLE=dist\%%D"
  )
)

if not defined PORTABLE (
  echo [错误] 仍无便携目录
  exit /b 1
)

for %%I in ("%PORTABLE%") do set "PORTABLE_ABS=%%~fI"
echo [源] !PORTABLE_ABS!

if not exist "!PORTABLE_ABS!\MusicEditing.exe" (
  echo [警告] 缺少 MusicEditing.exe，安装后仍可用 bat 启动
)

REM 2) 找 ISCC
set "ISCC="
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
where ISCC >nul 2>&1 && for /f "delims=" %%P in ('where ISCC') do set "ISCC=%%P"

if not defined ISCC (
  echo [错误] 未找到 Inno Setup 6 的 ISCC.exe
  echo 请安装: https://jrsoftware.org/isdl.php
  echo 或 winget install JRSoftware.InnoSetup
  exit /b 1
)

echo [ISCC] !ISCC!
"!ISCC!" /DPortableDir="!PORTABLE_ABS!" /DMyAppVersion=0.1.0 "scripts\inno\MusicEditing.iss"
if errorlevel 1 (
  echo 安装包编译失败
  exit /b 1
)

echo.
echo 输出在 dist\MusicEditing_Setup_*.exe
echo [签名] 尝试签名 Setup（无证书则跳过，属正常）…
python scripts\sign_artifact.py --latest-setup
echo 发给用户前建议: python scripts\accept_portable.py "!PORTABLE_ABS!"
exit /b 0
