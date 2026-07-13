# ONNX Runtime 预编译包（LaMa 去水印推理）



与 OpenCV / FFmpeg 相同，按架构分目录：



```

third_party/onnxruntime/

├── x64/

│   ├── include/     onnxruntime_c_api.h, onnxruntime_cxx_api.h ...

│   ├── lib/         onnxruntime.lib（及 providers_*.lib）

│   └── bin/         onnxruntime.dll、onnxruntime_providers_*.dll

└── x86/             （可选，Win32 构建）

```



## 安装（x64）



**推荐：从本机已下载包导入（GPU / CPU 均可）**



```bat

scripts\import_onnxruntime.bat x64 "E:\FFmpegxuexi\onnxruntime-win-x64-gpu_cuda13-1.27.1\onnxruntime-win-x64-gpu_cuda13-1.27.1"

```



省略第二参数时，默认使用：



`E:\FFmpegxuexi\onnxruntime-win-x64-gpu_cuda13-1.27.1\onnxruntime-win-x64-gpu_cuda13-1.27.1`



**一键下载 CPU 包**（可选，缓存目录不进 git）：



```bat

scripts\setup_onnxruntime_x64.bat

```



- 优先使用 `E:\FFmpegxuexi\onnxruntime-win-x64-gpu_cuda13-1.27.1\` 下已解压目录

- 否则下载官方 win-x64 CPU 包到 `E:\FFmpegxuexi\onnxruntime\` 并导入



## LaMa 模型（去水印）



```bat

scripts\download_lama_model.bat

```



默认保存到 `models\lama.onnx`（已 gitignore，约 200MB）。



## 构建

```bat
build_x64.bat
```

或 **一步启动 UI**（自动导入 ONNX + 缺产物时自动编译）：

```bat
run_ui_x64.bat
```



CMake 检测到 `third_party/onnxruntime/x64/lib/onnxruntime.lib` 后启用 `MUSIC_HAS_ONNXRUNTIME`。



## 源码说明



本项目 **不** 在仓库内编译 ONNX Runtime 源码。下载/解压目录放在 `E:\FFmpegxuexi\`，用 `import_onnxruntime.bat` 复制 `include/lib/bin` 到本目录。

