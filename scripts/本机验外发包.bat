@echo off
setlocal
cd /d "%~dp0\.."
chcp 65001 >nul 2>&1
echo === Local portable check (smoke then MusicEditing.exe) ===
echo Do NOT use run_ui_x64.bat. This uses package runtime + clean PATH.
echo.

if exist "dist\_share_probe\MusicEditing_Share_20260817\MusicEditing.exe" (
  python scripts\smoke_portable_env.py dist\_share_probe\MusicEditing_Share_20260817
) else if exist "dist\MusicEditing_Share_20260817\MusicEditing.exe" (
  python scripts\smoke_portable_env.py dist\MusicEditing_Share_20260817
) else (
  echo [info] No unpacked Share folder; running pack_for_share first...
  call scripts\只打包.bat
  if errorlevel 1 exit /b 1
  for /f "delims=" %%D in ('dir /b /ad /o-d dist\MusicEditing_Share_* 2^>nul') do (
    python scripts\smoke_portable_env.py --no-overlay "dist\%%D"
    goto :done
  )
  echo [FAIL] No Share folder after pack
  exit /b 1
)

:done
if errorlevel 1 (
  echo.
  echo [FAIL] Smoke failed - do not ship
  exit /b 1
)
echo.
echo [PASS] Auto smoke OK. In the opened window: open video, play, check gallery.
echo After manual OK, run: scripts\只打包.bat
exit /b 0
