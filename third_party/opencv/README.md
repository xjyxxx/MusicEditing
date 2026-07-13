# OpenCV 本地预编译包

OpenCV 使用 **world 版**：链接时需要 `.lib`，运行时需要 `.dll`（与 FFmpeg 相同，不能只留其一）。

## 目录结构

```
third_party/opencv/
├── x64/
│   ├── include/opencv2/...
│   ├── lib/opencv_world4120.lib
│   └── bin/opencv_world4120.dll
└── x86/          （Win32 构建，可选）
    ├── include/
    ├── lib/
    └── bin/
```

克隆仓库后若缺少上述文件，在本机执行导入脚本（需已安装 OpenCV 或使用下方编译脚本）。

## 导入（从 D:\APP\opencv）

```bat
rem x64（build_x64.bat 用）
scripts\import_opencv.bat x64

rem Win32（build.bat 用）
scripts\import_opencv.bat x86
```

也可指定路径：

```bat
scripts\import_opencv.bat x64 "D:\APP\opencv\build"
```

## Win32 首次：自编译 x86

官方 Windows 包通常只有 x64，Win32 需自行编译：

```bat
scripts\build_opencv_win32.bat
scripts\import_opencv.bat x86
```

## CMake

优先使用 `third_party/opencv/{x64|x86}`；不存在时回退 `D:/APP/opencv/build*`。

关闭 OpenCV：`-DMUSIC_ENABLE_OPENCV=OFF`

## 配置

`client/resources/config/app.conf` → `opencv_filter=clahe`
