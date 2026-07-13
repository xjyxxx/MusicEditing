@echo off
setlocal EnableDelayedExpansion

rem 编译 llama.cpp，打包为 third_party\llama_prebuilt（仅 include / lib / bin）
rem 用法:
rem   scripts\build_llama_lib.bat          静态 .lib，打包并删除源码与 build
rem   scripts\build_llama_lib.bat dll      动态 .dll + 导入库
rem   scripts\build_llama_lib.bat off keep-src   打包但保留 llama.cpp 源码

set "PROJECT_DIR=%~dp0.."
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "LLAMA_DIR=%PROJECT_DIR%\third_party\llama.cpp"
set "OUT_DIR=%PROJECT_DIR%\third_party\llama_prebuilt"
set "BUILD_DIR=%LLAMA_DIR%\build"
set "CONFIG=Release"

set "SHARED=OFF"
set "KEEP_SRC=0"
if /I "%~1"=="dll" set "SHARED=ON"
if /I "%~1"=="shared" set "SHARED=ON"
if /I "%~1"=="on" set "SHARED=ON"
if /I "%~2"=="keep-src" set "KEEP_SRC=1"
if /I "%~1"=="keep-src" set "KEEP_SRC=1"

echo ========================================
echo  llama.cpp 库构建 ^(shared=%SHARED%^)
echo ========================================

if not exist "%LLAMA_DIR%\CMakeLists.txt" (
    if exist "%OUT_DIR%\lib\llama.lib" (
        echo [跳过] 已是预编译包: %OUT_DIR%
        goto :show_out
    )
    echo [错误] 未找到 third_party\llama.cpp 源码，且不存在 llama_prebuilt
    exit /b 1
)

if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"

cmake -S "%LLAMA_DIR%" -B "%BUILD_DIR%" -G "Visual Studio 18 2026" -A x64 ^
  -DBUILD_SHARED_LIBS=%SHARED% ^
  -DLLAMA_BUILD_APP=OFF ^
  -DLLAMA_BUILD_UI=OFF ^
  -DLLAMA_BUILD_TOOLS=OFF ^
  -DLLAMA_BUILD_EXAMPLES=OFF ^
  -DLLAMA_BUILD_SERVER=OFF ^
  -DLLAMA_BUILD_TESTS=OFF ^
  -DLLAMA_BUILD_COMMON=OFF ^
  -DLLAMA_OPENSSL=OFF ^
  -DGGML_CCACHE=OFF
if errorlevel 1 (
    echo [错误] CMake 配置失败
    exit /b 1
)

cmake --build "%BUILD_DIR%" --config %CONFIG%
if errorlevel 1 (
    echo [错误] 编译失败
    exit /b 1
)

echo.
echo 打包到 %OUT_DIR% ^(仅 include / lib / bin^) ...

if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%\include"
mkdir "%OUT_DIR%\lib"
mkdir "%OUT_DIR%\bin"

copy /Y "%LLAMA_DIR%\include\*.h" "%OUT_DIR%\include\" >nul
xcopy /E /I /Y "%LLAMA_DIR%\ggml\include\*.h" "%OUT_DIR%\include\" >nul

for /r "%BUILD_DIR%" %%F in (*.lib) do (
    copy /Y "%%F" "%OUT_DIR%\lib\" >nul
)
for /r "%BUILD_DIR%" %%F in (*.dll) do (
    copy /Y "%%F" "%OUT_DIR%\bin\" >nul
)

if not exist "%OUT_DIR%\lib\llama.lib" (
    echo [错误] 未找到 llama.lib，打包失败
    exit /b 1
)

echo 删除 build 中间文件 ...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"

if "%KEEP_SRC%"=="0" (
    echo 删除 llama.cpp 源码目录 ...
    rmdir /s /q "%LLAMA_DIR%"
)

:show_out
echo.
echo [成功] llama 预编译包:
echo   %OUT_DIR%
echo.
echo include:
dir /B "%OUT_DIR%\include\*.h" 2>nul
echo.
echo lib:
dir /B "%OUT_DIR%\lib\*.lib" 2>nul
echo.
if exist "%OUT_DIR%\bin\*.dll" (
    echo bin:
    dir /B "%OUT_DIR%\bin\*.dll" 2>nul
    echo.
)
echo Restore source from git, then run this script again.
echo To keep llama.cpp source: scripts\build_llama_lib.bat off keep-src
echo.

endlocal
