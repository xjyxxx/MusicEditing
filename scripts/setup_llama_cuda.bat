@echo off
python "%~dp0setup_llama_gpu.py" %*
exit /b %ERRORLEVEL%
