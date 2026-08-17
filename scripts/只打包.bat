@echo off
setlocal
cd /d "%~dp0\.."
echo === 只打包（外发瘦包：无 models / 无测试片 / zip 最高压缩）===
echo 需要 ONNX 去水印超分时加: --with-models
echo 需要测试视频时加: --with-tests
python scripts\pack_for_share.py %*
if errorlevel 1 exit /b 1
echo.
echo 输出: dist\MusicEditing_Share_*.zip
echo 对方无需安装 Visual Studio / Python，解压双击即可
exit /b 0
