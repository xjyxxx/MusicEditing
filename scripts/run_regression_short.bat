@echo off
setlocal
cd /d "%~dp0\.."
echo === MusicEditing regression short ===
set FAIL=0

python tests\regression\test_player_shm_seek.py
if errorlevel 1 set FAIL=1

python tests\regression\test_opencv_upscale.py
if errorlevel 1 set FAIL=1

python tests\regression\test_pipeline_parallel.py
if errorlevel 1 set FAIL=1

python tests\regression\test_vertical_export.py
if errorlevel 1 set FAIL=1

python tests\regression\test_cookie_probe_hint.py
if errorlevel 1 set FAIL=1

echo.
if "%FAIL%"=="0" (
  echo ALL PASS
  exit /b 0
) else (
  echo SOME FAILED
  exit /b 1
)
