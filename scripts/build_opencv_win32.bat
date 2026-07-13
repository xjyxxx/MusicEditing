@echo off
setlocal EnableDelayedExpansion

rem 为 Win32 项目编译 OpenCV x86（预装的 D:\APP\opencv\build 仅为 x64）
set "OPENCV_SRC=D:\APP\opencv\sources"
set "OPENCV_BUILD=D:\APP\opencv\build_x86"

if not exist "%OPENCV_SRC%\CMakeLists.txt" (
    echo [错误] 未找到 OpenCV 源码: %OPENCV_SRC%
    exit /b 1
)

echo ========================================
echo  OpenCV Win32 编译 (与 MusicEditing 同架构)
echo  源码: %OPENCV_SRC%
echo  输出: %OPENCV_BUILD%
echo ========================================
echo 首次编译约 15-30 分钟，请耐心等待...
echo.

cmake -S "%OPENCV_SRC%" -B "%OPENCV_BUILD%" -G "Visual Studio 18 2026" -A Win32 ^
  -DBUILD_opencv_world=ON ^
  -DBUILD_EXAMPLES=OFF ^
  -DBUILD_TESTS=OFF ^
  -DBUILD_PERF_TESTS=OFF ^
  -DBUILD_DOCS=OFF ^
  -DBUILD_opencv_apps=OFF ^
  -DWITH_CUDA=OFF ^
  -DWITH_IPP=OFF
if errorlevel 1 (
    echo [错误] CMake 配置失败
    exit /b 1
)

cmake --build "%OPENCV_BUILD%" --config Release -j
if errorlevel 1 (
    echo [错误] 编译失败
    exit /b 1
)

echo.
echo [成功] OpenCV Win32 已生成
echo 库目录: %OPENCV_BUILD%\x86\vc16\lib
echo DLL:    %OPENCV_BUILD%\x86\vc16\bin\opencv_world4120.dll
echo.
echo 接下来运行: .\build.bat
echo.

endlocal
