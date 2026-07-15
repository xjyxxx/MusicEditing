# ONNX Runtime 预编译包（LaMa 去水印推理）

包已落在**本仓库**内，构建/运行只读此目录，**不依赖**外部盘符。

```
third_party/onnxruntime/
├── VERSION.txt
├── CMakeLists.txt
├── x64/
│   ├── include/
│   ├── lib/
│   └── bin/
└── _cache/
```

## 首次放入项目

推荐 **CPU** 包（体积更小，本项目去水印默认走 CPU EP）：

```bat
scripts\setup_onnxruntime_x64.bat
```

或自行解压后导入：

```bat
scripts\import_onnxruntime.bat x64 "解压后的 onnxruntime-win-x64 目录"
```

## 构建

```bat
build_x64.bat
run_ui_x64.bat
```

## 执行提供方

`WatermarkInpainter` **默认 CPU EP**（`MUSIC_ORT_CUDA` 未设置或为 0）。  
项目**不再**捆绑 `third_party/cuda_runtime`（原 cu12/cuDNN 体积过大）。

视频去水印默认 OpenCV 快速模式；图片/精修用 LaMa CPU。

若本机已自行安装 CUDA 并坚持试 CUDA EP，可手动设 `MUSIC_ORT_CUDA=1`（不保证可用，缺库则回退 CPU）。

## Git 说明

`x64/bin`、`x64/lib` 含大文件，已 gitignore；换机时重新 import / setup 即可。
