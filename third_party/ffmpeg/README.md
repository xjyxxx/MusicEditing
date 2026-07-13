# FFmpeg 预编译库

与 OpenCV 相同，按架构分目录：

```
third_party/ffmpeg/
├── x86/          # Win32 构建（旧 API，bundled）
│   ├── include/
│   ├── lib/
│   └── bin/
└── x64/          # x64 构建（新 API + D3D11VA）
    ├── include/
    ├── lib/
    └── bin/
```

CMake 在 `-A Win32` 时选用 `x86/`，`-A x64` 时选用 `x64/`。

## x64 安装

**推荐：导入本机已下载包**

```bat
scripts\import_ffmpeg_x64.bat
rem 或指定路径:
scripts\import_ffmpeg_x64.bat "E:\path\to\ffmpeg-shared"
```

**备选：在线下载**

```bat
scripts\setup_ffmpeg_x64.bat
```

## 构建

```bat
build.bat          rem Win32 → ffmpeg/x86
build_x64.bat      rem x64   → ffmpeg/x64
```

> Win32 使用旧 decode API；x64 使用 `send_packet/receive_frame`。二者由 `shared/ffmpeg_compat.cpp` 统一封装。
