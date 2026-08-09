@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "BUILD_DIR=%PROJECT_DIR%\build_x64"
set "FFMPEG_X64=%PROJECT_DIR%\third_party\ffmpeg\x64\lib\avcodec.lib"
set "OPENCV_X64=%PROJECT_DIR%\third_party\opencv\x64\lib\opencv_world4120.lib"
set "ORT_X64=%PROJECT_DIR%\third_party\onnxruntime\x64\lib\onnxruntime.lib"

echo ========================================
echo  MusicEditing x64 构建
echo ========================================

if not exist "%FFMPEG_X64%" (
    echo [提示] 未找到 x64 FFmpeg，正在导入本机已下载包 ...
    call "%PROJECT_DIR%\scripts\import_ffmpeg_x64.bat"
    if errorlevel 1 exit /b 1
)

if not exist "%OPENCV_X64%" (
    echo [提示] 未找到本地 OpenCV x64，正在从 D:\APP\opencv 导入 ...
    call "%PROJECT_DIR%\scripts\import_opencv.bat" x64
    if errorlevel 1 (
        echo [警告] OpenCV 导入失败，将尝试外部 OPENCV_DIR 或禁用滤镜
    )
)

if not exist "%ORT_X64%" (
    echo [错误] 项目内未找到 ONNX Runtime:
    echo   %ORT_X64%
    echo 请先将 GPU 包导入到 third_party（不要依赖外部盘符）:
    echo   scripts\import_onnxruntime.bat x64 "解压后的 onnxruntime-win-x64-gpu_cuda12 目录"
    echo 或下载 CPU 包: scripts\setup_onnxruntime_x64.bat
    echo 去水印模块将禁用，继续编译...
)

echo Stopping media_player / media_cli ...
taskkill /F /IM media_player.exe >nul 2>&1
taskkill /F /IM media_cli.exe >nul 2>&1
taskkill /F /IM media_engine_test.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

set "CMAKE_EXTRA="
set "NVCC_EXE="
where nvcc >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%A in ('where nvcc') do (
        set "NVCC_EXE=%%A"
        goto :nvcc_found
    )
)
for %%V in (v12.6 v12.5 v12.4 v12.3 v12.2 v12.1 v12.0 v13.0 v13.1 v13.2 v13.3) do (
    if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\%%V\bin\nvcc.exe" (
        set "NVCC_EXE=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\%%V\bin\nvcc.exe"
        set "PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\%%V\bin;!PATH!"
        goto :nvcc_found
    )
)

rem 无 CUDA Toolkit：优先 Vulkan（体积小，免下载数 GB Toolkit）
if defined VULKAN_SDK (
    if exist "%VULKAN_SDK%\Bin\glslc.exe" goto :vulkan_found
    if exist "%VULKAN_SDK%\bin\glslc.exe" goto :vulkan_found
)
for /d %%D in ("C:\VulkanSDK\*") do (
    if exist "%%~fD\Bin\glslc.exe" (
        set "VULKAN_SDK=%%~fD"
        set "PATH=%%~fD\Bin;!PATH!"
        goto :vulkan_found
    )
)
echo [提示] 未检测到 CUDA Toolkit / Vulkan SDK。llama 使用 prebuilt CPU。
echo       推荐免 Toolkit GPU: python scripts\setup_llama_gpu.py install-vulkan
echo       然后: python scripts\setup_llama_gpu.py vulkan
goto :cmake_cfg

:vulkan_found
echo [提示] 检测到 Vulkan SDK: !VULKAN_SDK!
echo       启用 llama 源码 + GGML_VULKAN（无需 CUDA Toolkit）
set "CMAKE_EXTRA=-DMUSIC_GGML_VULKAN=ON -DMUSIC_LLAMA_FROM_SOURCE=ON -DMUSIC_GGML_CUDA=OFF"
goto :cmake_cfg

:nvcc_found
echo [提示] 检测到 CUDA Toolkit: !NVCC_EXE!
echo       启用 llama 源码 + GGML_CUDA（跳过 llama_prebuilt）
set "CMAKE_EXTRA=-DMUSIC_GGML_CUDA=ON -DMUSIC_LLAMA_FROM_SOURCE=ON -DCMAKE_CUDA_ARCHITECTURES=89;86;80;75"

:cmake_cfg
cmake -S "%PROJECT_DIR%" -B "%BUILD_DIR%" -G "Visual Studio 18 2026" -A x64 %CMAKE_EXTRA%
if errorlevel 1 (
    echo [错误] CMake 配置失败
    exit /b 1
)

cmake --build "%BUILD_DIR%" --config Release
if errorlevel 1 (
    echo [错误] 编译失败
    exit /b 1
)

if exist "%PROJECT_DIR%\third_party\opencv\x64\bin\opencv_world4120.dll" (
    copy /Y "%PROJECT_DIR%\third_party\opencv\x64\bin\opencv_world4120.dll" "%BUILD_DIR%\bin\Release\" >nul
)
if exist "%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime.dll" (
    for %%F in ("%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime*.dll") do (
        copy /Y "%%~fF" "%BUILD_DIR%\bin\Release\" >nul
    )
)

echo.
echo [成功] x64 构建完成
echo 输出目录: %BUILD_DIR%\bin\Release
echo 运行 UI:  run_ui_x64.bat
echo.

endlocal
