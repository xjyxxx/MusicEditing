@echo off

setlocal EnableDelayedExpansion



set "PROJECT_DIR=%~dp0"

if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "BUILD_DIR=%PROJECT_DIR%\build_x64"

set "BIN=%BUILD_DIR%\bin\Release"

set "CLI=%BIN%\media_cli.exe"

set "PLAYER=%BIN%\media_player.exe"

set "ORT_LIB=%PROJECT_DIR%\third_party\onnxruntime\x64\lib\onnxruntime.lib"

set "ORT_DLL=%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime.dll"

set "NEED_BUILD=0"



echo ========================================

echo  MusicEditing x64 UI

echo ========================================



rem 缺 ONNX 预编译包时，从 FFmpegxuexi 自动导入（与 build_x64 相同逻辑）

if not exist "%ORT_LIB%" (

    echo [提示] 未找到 ONNX Runtime，正在从 FFmpegxuexi 导入 ...

    call "%PROJECT_DIR%\scripts\import_onnxruntime.bat" x64

    if errorlevel 1 (

        echo [警告] ONNX Runtime 导入失败，去水印模块将禁用

    ) else (

        set "NEED_BUILD=1"

    )

)



if not exist "%CLI%" set "NEED_BUILD=1"

if not exist "%PLAYER%" set "NEED_BUILD=1"



rem 已导入 ONNX 但构建产物里还没有对应 DLL，说明需要重新编译

if exist "%ORT_DLL%" if not exist "%BIN%\onnxruntime.dll" set "NEED_BUILD=1"



if "!NEED_BUILD!"=="1" (

    echo [提示] 正在构建 x64 工程 ...

    call "%PROJECT_DIR%\build_x64.bat"

    if errorlevel 1 (

        echo [错误] 构建失败

        exit /b 1

    )

)



if not exist "%CLI%" (

    echo [错误] 未找到 x64 media_cli.exe

    exit /b 1

)



if not exist "%PLAYER%" (

    echo [错误] 未找到 x64 media_player.exe

    exit /b 1

)



rem 兜底：确保运行时 DLL 在输出目录

if exist "%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime.dll" (

    for %%F in ("%PROJECT_DIR%\third_party\onnxruntime\x64\bin\onnxruntime*.dll") do (

        copy /Y "%%~fF" "%BIN%\" >nul 2>&1

    )

)

if exist "%PROJECT_DIR%\third_party\opencv\x64\bin\opencv_world4120.dll" (

    copy /Y "%PROJECT_DIR%\third_party\opencv\x64\bin\opencv_world4120.dll" "%BIN%\" >nul 2>&1

)

if not exist "%PROJECT_DIR%\models\lama.onnx" (
    echo [提示] 未找到 LaMa 去水印模型，正在下载（约 200MB，仅首次）...
    call "%PROJECT_DIR%\scripts\download_lama_model.bat"
    if errorlevel 1 (
        echo [警告] LaMa 模型下载失败，去水印功能将不可用
        echo         可稍后手动运行: scripts\download_lama_model.bat
    )
)

pip install -r "%PROJECT_DIR%\client\scripts\requirements.txt" -q

if errorlevel 1 (

    echo [错误] Python 依赖安装失败

    exit /b 1

)



set "PATH=%BIN%;%PATH%"

python "%PROJECT_DIR%\client\scripts\main.py"



endlocal

