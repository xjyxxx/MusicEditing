# MusicEditing — 软件实现流程说明

> **定位**：描述仓库**当前代码**的实现链路（非产品愿景稿）。  
> **产品对照**：[AI本地音视频处理工具-产品交互设计文档（开发落地版）.md](../../AI本地音视频处理工具-产品交互设计文档（开发落地版）.md)  
> **文档索引**：[docs/design/README.md](README.md)  
> **维护规则**：改功能时同步更新本文（见 `.cursor/skills/music-editing-feature-docs/`）。

---

## 目录

| 章 | 内容 |
|----|------|
| [§1 总体架构](#1-总体架构) | 双层架构、编译产物 |
| [§2 构建与启动](#2-构建与启动流程) | x64 / Win32、启动退出 |
| [§3 MVVM](#3-mvvm-分层实现) | Model / VM / View、播放器、OpenCV、去水印/超分、GPU |
| [§4 C++ 引擎](#4-c-媒体引擎实现流程) | VideoDecoder、C API、CLI 协议 |
| [§5 业务链路](#5-业务功能链路) | 5.1 切片 · 5.8 字幕 · 5.12 波形响度 · 5.13 调色 · … |
| [§6 模块依赖](#6-模块间依赖关系) | CMake / Python 树 |
| [§7 状态表](#7-已实现-vs-待实现) | ✅ / ⏳ |
| [§8 llama.cpp](#8-llamacpp-集成说明) | 目录与 CMake |
| [§9 扩展指南](#9-扩展接入指南) | 扩展与路线图 |
| [§10 命令速查](#10-运行命令速查) | bat / 脚本 |

**相关专文：** [player_decode_flow.md](player_decode_flow.md)（播放解码）· [../流程图/README.md](../流程图/README.md)

> **§3 阅读顺序提示：** 文中标题顺序为 3.1–3.5（滤镜）→ **3.7 去水印** → **3.8 超分** → **3.6 GPU**（历史插入顺序，以标题号为准）。

---

## 1. 总体架构

**C++ 媒体引擎 + Python/PySide6 UI**；Python 经 **MediaBridge / PlayerBackend 子进程**调用 `media_cli.exe`、`media_player.exe` 与捆绑 `ffmpeg.exe`（stdout=协议，stderr=日志）。

日常推荐 **x64**（`build_x64.bat` + `run_ui_x64.bat`）。

```
┌─────────────────────────────────────────────────────────────┐
│                 Python 客户端 (64-bit PySide6)               │
│  View  ◄──►  MainViewModel  ◄──►  models (dataclass)         │
│                    │                                         │
│         MediaBridge / PlayerBackend / FFmpeg 封装            │
└────────────────────┼────────────────────────────────────────┘
                     │ subprocess
┌────────────────────▼────────────────────────────────────────┐
│  media_cli / media_player  →  media_engine.dll               │
│  VideoDecoder · 播放器 · 超分/去水印 ONNX（可选）              │
│  FFmpeg · OpenCV · ONNX Runtime ·（可选）llama               │
└─────────────────────────────────────────────────────────────┘
```

### 编译产物

| 文件 | 作用 |
|------|------|
| `media_shared.lib` | 公共静态库（日志、路径、硬解辅助等） |
| `media_engine.dll` | 探测 / 遍历 / 缩略图 / 超分·去水印 C API |
| `media_cli.exe` | CLI（Python 批处理入口） |
| `media_player.exe` | 首页播放器子进程 |
| `media_engine_test.exe` | C++ 冒烟测试 |

---

## 2. 构建与启动流程

### 2.1 编译流程

**x64（推荐）**

```
scripts/setup_ffmpeg_x64.bat   # 首次：FFmpeg → third_party/ffmpeg/x64/
build_x64.bat  →  cmake -A x64  →  build_x64/bin/Release
                  OpenCV/ONNX：third_party/opencv|onnxruntime/x64/
```

**Win32**

```
build.bat  →  cmake -A Win32  →  build/bin/Release
              FFmpeg: third_party/ffmpeg/x86/
              OpenCV: third_party/opencv/x86/（需 import）
```

Presets：`CMakePresets.json` → `windows-x64-release` / `windows-win32-release`。

**要点：**
- 第三方库按 `{x64|x86}` 分目录，详见各 `third_party/*/README.md`
- `build/` 与 `build_x64/` 互不覆盖
- Python 始终 64-bit；C++ 与第三方库架构一致

### 2.2 启动与退出

**启动：**
```
run_ui.bat / python client/scripts/main.py
  ├─ PySide6 QApplication（setQuitOnLastWindowClosed）
  ├─ MainViewModel（AppLogic GPU 检测、MediaBridge）
  ├─ detect_gpu_info() → 状态栏显示 GPU: 型号 或 CPU 模式
  ├─ 后台线程：IP 定位城市 + Open-Meteo → 状态栏天气（§5.11）
  ├─ 无 NVIDIA GPU 时弹窗提示 CPU 模式（见 §3.6）
  └─ 显示多标签页（首页/切片/增强/去水印/热评/下载等），进入事件循环
```

**退出（关闭窗口）：**
```
MainWindow.shutdown()
  ├─ VideoPlayerWidget.shutdown() → Qt 音频 stop
  └─ PlayerBackend.shutdown()    → kill media_player.exe
```

详见 `docs/design/player_decode_flow.md` §5。

---

## 3. MVVM 分层实现

### 3.1 Model 层 (`client/scripts/models/`)

纯数据结构，无 UI 依赖：

| 类型 | 字段/用途 |
|------|-----------|
| `VideoModel` | 文件路径、分辨率、时长、帧率、编码 |
| `TaskModel` | 任务 ID、类型（含 `INTERPOLATE`）、状态、进度 |
| `HighlightSegment` | 起止时间、得分、是否选中、`thumbnail_path` |
| `SliceParams` | 场景、最短/最长片段、敏感度 |
| `AppState` | 全局状态容器 |

任务状态枚举：`Waiting → Processing → Rendering → Completed / Failed / Cancelled`

### 3.2 ViewModel 层 (`client/scripts/viewmodels/main_vm.py`)

`MainViewModel` 继承 `QObject`，通过 **Signal/Property/Slot** 与 View 双向绑定：

| 信号 | 触发时机 |
|------|----------|
| `videoLoaded` | 视频导入成功 |
| `progressUpdated` | 帧遍历进度更新 |
| `highlightsReady` | AI 分析完成 |
| `errorOccurred` | 任意错误 |
| `statusMessageChanged` | 底部状态栏更新 |

| Slot 方法 | 调用方 |
|-----------|--------|
| `import_video(path)` | SlicePage「导入视频」 |
| `start_slice_analysis()` | SlicePage「AI 智能分析」 |
| `start_watermark_image(...)` / `start_watermark_video(...)` | WatermarkPage「开始去水印」 |
| `start_enhance_image(...)` / `start_enhance_video(...)` | EnhancePage「开始超分」 |
| `start_interpolate_video(...)` | EnhancePage「视频补帧」 |
| `import_image(path)` | 图片去水印 / 超分导入 |
| `add_manual_highlight` / `remove_highlight_at` / `clear_highlights` | 手动切片 |
| `update_watermark_range(start, end)` | 视频去水印时间段 |
| `update_enhance_range(start, end)` | 视频超分时间段 |
| `update_slice_params(...)` | 参数滑块变更 |
| `set_output_dir(path)` | 导出目录选择 |
| `export_highlights` / `compact_speech` / `export_vertical_short` | SlicePage 成片 / 静音 / 竖屏 |
| `start_pipeline_queue` / pause / skip / cancel | 全流程队列页 |

### 3.3 View 层 (`client/scripts/ui/main_window.py`)

| 页面 | 类 | 状态 |
|------|-----|------|
| 首页 | `HomePage` + `VideoPlayerWidget` | 本地预览 + 功能卡片 |
| 智能切片 | `SlicePage` + `HighlightTimelineWidget` | 分析 / 手动 / 成片 / **竖屏短视频** |
| 画质增强 | `EnhancePage` + `ExifPanel` | 图片超分 · 视频超分 · **视频补帧**；内页 Scroll 深色底 |
| 去水印 | `WatermarkPage` + `RegionSelectorWidget` + `ExifPanel` | 图片/视频去水印 + EXIF |
| 热评滚动 | `HotCommentsPage` | 歌曲链接/ID → 热评滚动 |
| 链接下载 | `DownloadPage` | yt-dlp 下载 → 可送首页播放 |
| 全流程队列 | `PipelineQueuePage` | 切片成片→超分→去水印；批量无人值守（§5.9.1） |
| 个人中心 | `PlaceholderPage` | 占位（授权待接入） |

播放器组件：`client/scripts/ui/video_player.py`（`GlVideoWidget` OpenGL + `PlayerBackend` → `media_player.exe`）

#### 3.3.1 视觉主题（Studio UI）

全局样式集中在 `client/scripts/ui/theme.py`，由 `MainWindow.setStyleSheet(app_stylesheet())` 注入。

**方向：** 借鉴媒体工具（Splice 炭黑扁平、Cinema Studio 琥珀 CTA）——深炭画布 + 发丝边 + 琥珀主按钮，去掉旧版紫调 `#5b5bd6`。

| 令牌 | 色值 | 用途 |
|------|------|------|
| `BG` | `#0E1116` | 窗口底 |
| `SURFACE` / `SURFACE_2` | `#161B22` / `#1C2330` | 顶栏、Tab 面板 |
| `ACCENT` | `#E8A45C` | 主按钮 / 选中 Tab / 进度条 |
| `SIGNAL` | `#3DB8A8` | 信息文字、GroupBox 标题 |
| 字体 | YaHei UI / Segoe UI Semibold | 中文桌面可读 |

顶栏为圆角 `TopChrome`：品牌名 + GPU/授权/天气胶囊 + 版本号。主按钮用 `objectName="primaryButton"`。

### 3.4 首页播放器交互（统一 FFmpeg 播放器）

架构详见 `docs/流程图/README.md`，**解码/同步/存储详解见 `docs/design/player_decode_flow.md`**。

```
HomePage
  ├─ VideoPlayerWidget（Python GUI）
  │    ├─ GlVideoWidget（QOpenGLWidget）显示 RGB 帧；点击画面 → 暂停/继续；暂停时中央显示三角播放图标
  │    ├─ 视频：FFmpeg 解码画面 + Qt QMediaPlayer 音频主时钟
  │    ├─ 音乐：仅 Qt QMediaPlayer（mp3/wav/flac/m4a…），封面占位图
  │    ├─ 「打开文件」同时支持视频与音乐过滤器
  │    ├─ 打开视频 → fileOpened → ViewModel.import_video（全局共享）
  │    └─ 打开音乐不导入切片链路（避免当视频 probe）
  └─ videoLoaded 信号 → 智能切片页导入后，主页播放器自动同步加载
```

View **不直接调用 FFmpeg**，通过 `PlayerBackend` 子进程与 C++ 播放器通信；纯音乐不启动视频解码。

### 3.5 OpenCV 帧滤镜（`FrameProcessor`）

OpenCV **仅用于解码后的 RGB24 帧处理**，不参与 FFmpeg 解码本身。智能切片 ASR/LLM 链路当前**未使用** OpenCV。

#### 3.5.1 配置项（`client/resources/config/app.conf`）

```ini
# OpenCV 帧滤镜：clahe | denoise | sharpen | film | warm | cool | vintage | neon | comic | pixel | off
opencv_filter=clahe
# 滤镜设备：auto（优先 OpenCL）| cpu | opencl
opencv_filter_device=auto
# 播放时是否启用滤镜（false=仅暂停预览；UI 下拉选手动选滤镜后会打开播放滤镜）
opencv_filter_playback=false
```

| 值 | 效果 | OpenCV 实现 |
|----|------|-------------|
| `clahe`（默认） | 明亮 / 对比度增强（晴天氛围推荐） | `COLOR_RGB2Lab` + `createCLAHE` |
| `denoise` | 轻度降噪 | `bilateralFilter` |
| `sharpen` | 锐化 | `GaussianBlur` + `addWeighted` |
| `film` | 胶片暖色 + 暗角（雨天氛围推荐） | sepia 矩阵 + vignette |
| `warm` | 电影暖调 | 3×3 色矩阵 + 轻对比（与增强页 LUT 同预设） |
| `cool` | 冷调 | 3×3 色矩阵 |
| `vintage` | 复古褪色 | sepia 弱化 + 降对比抬黑 |
| `neon` | 霓虹描边 | `Canny` 边缘叠色 |
| `comic` | 漫画风 | bilateral + 自适应阈值墨线 |
| `pixel` | 像素风 | 缩小再 `INTER_NEAREST` 放大 |
| `off` | 关闭，直通原帧 | 不调用 OpenCV |

首页播放器控制栏有滤镜下拉；选「胶片/暖调/冷调/复古/霓虹…」后**播放中也会套滤镜**。增强页「一键调色」导出同预设（FFmpeg `lut3d`）。

#### 3.5.2 界面显示

打开视频后，播放器标题栏（`VideoPlayerWidget._title`）会拼接滤镜状态，例如：

```
测试视频.mp4  ·  1280x720  ·  FFmpeg  ·  有声音  ·  OpenCV:clahe/opencl
```

逻辑见 `client/scripts/ui/video_player.py`：

- 启动时从 `load_app_config()` 读取 `opencv_filter` / `opencv_filter_device`（默认 `clahe` / `auto`）
- 若值不为 `off`，标题追加 `OpenCV:{模式}/{opencl|cpu}`；硬解且仅暂停预览时为 `OpenCV:clahe/opencl·预览`
- **注意**：若编译时未链接 OpenCV（输出目录无 `opencv_world4120.dll`），画面仍为直通；无 OpenCL 时后缀为 `/cpu`

#### 3.5.3 端到端调用链

```
app.conf  opencv_filter=clahe
          opencv_filter_device=auto
    │
    ▼
VideoPlayerWidget._do_open_file()
    ├─ PlayerBackend.open(path)
    └─ _apply_opencv_filter()
           ├─ FILTER_DEVICE auto → setFrameFilterDevice
           └─ FILTER clahe → setFrameFilter
    │
    ▼ 播放中每帧
decodeNextFrameToFile()
    ├─ FFmpeg 解码 + sws_scale → RGB24
    └─ FrameProcessor::processRgbFrame
           ├─ OpenCL：UMat upload → 算子 → download（优先）
           └─ 失败则 CPU Mat
```

IPC 协议（`player_main.cpp`）：

```
FILTER_DEVICE auto|cpu|opencl  →  FILTER_DEVICE_OK device=... opencl=0|1
FILTER clahe                   →  FILTER_OK mode=clahe device=auto active=cpu|opencl
FILTER_STATUS                  →  FILTER_STATUS_OK mode=... device=... active=... opencl=...
FILTER off                     →  FILTER_OK mode=off ...
FILTER invalid                 →  ERROR invalid_filter
```

#### 3.5.4 C++ 代码位置

| 文件 | 作用 |
|------|------|
| `client/include/core/frame_processor.h` | 滤镜模式枚举、`processRgbFrame()` |
| `client/src/core/frame_processor.cpp` | OpenCV 实现（`#ifdef MUSIC_HAS_OPENCV`） |
| `client/src/core/video_player_engine.cpp` | **播放器每帧**调用 `frameProcessor` |
| `client/src/core/video_decoder.cpp` | **缩略图** `extractThumbnail()` 转 RGB 后调用 |
| `client/src/player_main.cpp` | 处理 `FILTER` 命令 |
| `client/scripts/core/player_backend.py` | `set_filter(mode)` 封装 |
| `third_party/opencv/CMakeLists.txt` | 检测并链接 `opencv_world4120` |

#### 3.5.5 构建与 OpenCV 路径

编译宏 `MUSIC_HAS_OPENCV=1` 时才会 `#include <opencv2/...>` 并链接 DLL；否则 `FrameProcessor` 直通。

| 架构 | OpenCV 目录 | 构建命令 |
|------|-------------|----------|
| Win32 | `D:/APP/opencv/build_x86`（源码自编译） | `build.bat` |
| x64 | `D:/APP/opencv/build`（官方预编译） | `build_x64.bat` |

CMake 成功时应看到：`OpenCV x.x.x integrated (...)`。输出目录需存在 `opencv_world4120.dll` 滤镜才生效。

详见 `third_party/opencv/README.md`。

### 3.5.6 GLEW / OpenGL 第三方库（已引入）

项目内已复制 **GLEW 2.3.1**（非外部路径引用）：

```
third_party/opengl/
├── x64/include/GL  lib/glew32.lib  bin/glew32.dll
└── x86/...
```

| 项 | 说明 |
|----|------|
| CMake 目标 | `music_glew` → 链 `glew32.lib` + `opengl32` |
| 宏 | `MUSIC_HAS_GLEW=1` |
| C++ | `media_player` 链接 GLEW（预留原生 GL；当前解码仍写 RGB） |
| **UI 显示** | ✅ `ui/gl_video_widget.py`：`QOpenGLWidget` 纹理绘制视频帧（等比 letterbox） |

显示链路：`FFmpeg 解码 → RGB → GlVideoWidget.set_rgb_frame → glTex + 着色器`。  
OpenGL **实现**来自显卡驱动；GLEW 在 C++ 侧，UI 用 Qt OpenGL。详见 `third_party/opengl/README.md`。

### 3.7 去水印（OpenCV 快速 + LaMa 精修）

本地预编译包布局与 OpenCV 相同：

```
third_party/onnxruntime/x64/
├── include/   onnxruntime_cxx_api.h
├── lib/       onnxruntime.lib（及 providers_*.lib）
└── bin/       onnxruntime.dll、onnxruntime_providers_*.dll

models/lama.onnx   # scripts/download_lama_model.bat，不进 git（仅精修需要）
```

**项目内自包含：** 预编译包存放于 `third_party/onnxruntime/x64`（见 `VERSION.txt`），构建不依赖 `E:\FFmpegxuexi` 等外部路径。首次把官方包导入：

```bat
scripts\import_onnxruntime.bat x64 "<解压后的 onnxruntime-win-x64-gpu_cuda12-*>"
```

| 脚本 | 作用 |
|------|------|
| `scripts/import_onnxruntime.bat` | 导入到 `third_party`；无参数时仅检查项目内是否已就绪 |
| `scripts/setup_onnxruntime_x64.bat` | 下载 CPU 包到 `_cache` 并导入（可选） |
| `scripts/download_lama_model.bat` | 下载 Carve/LaMa-ONNX 到 `models/` |

编译宏：`MUSIC_HAS_ONNXRUNTIME=1` 且 `MUSIC_HAS_OPENCV=1` 时启用 `WatermarkInpainter`。

**双后端策略：**

| 模式 | 环境变量 | 适用 | 说明 |
|------|----------|------|------|
| **快速** | `MUSIC_WATERMARK_BACKEND=opencv` | **视频默认** | `cv::inpaint`，秒级；不加载 LaMa |
| **精修** | `MUSIC_WATERMARK_BACKEND=lama`（默认） | **图片默认** / 视频可选 | LaMa ONNX；CUDA→CPU→OpenCV 回退 |

`MediaBridge.set_watermark_backend` / UI「质量模式」注入该环境变量。视频路径仍走 **单次** `watermark-inpaint-frames`（进程内复用，不逐帧起进程）。

**C++ API（`media_engine.h`）：**

- `media_watermark_load_model(path)` — 快速模式 path 可为 `-`
- `media_watermark_inpaint_image(in, out, regions, n)` — regions 为 `x,y,w,h` 数组

**CLI 测试（图片，支持多区域）：**

```
media_cli watermark-inpaint models/lama.onnx in.png out.png <x> <y> <w> <h> [x2 y2 w2 h2 ...]
→ stderr:
  WATERMARK_BACKEND:lama|opencv
  WATERMARK_EP:cuda|cpu|opencv
→ stdout:
  WATERMARK_OK
  output=out.png
```

快速模式示例：`set MUSIC_WATERMARK_BACKEND=opencv` 后 path 传 `-` 即可。

环境变量 `MUSIC_ORT_CUDA=1` 可尝试 CUDA EP（**默认关闭**）。项目**不再**捆绑 `third_party/cuda_runtime`；缺库时回退 CPU，再失败回退 OpenCV inpaint。

视频默认 OpenCV 快速模式；图片/精修默认 LaMa **CPU**。

**CLI 批量帧（视频去水印，后端只加载一次）：**

```
media_cli watermark-inpaint-frames [-|models/lama.onnx] <输入帧目录> <输出帧目录> <x> <y> <w> <h> [...]
→ stderr: WATERMARK_BACKEND:lama|opencv
→ stdout:
  PROGRESS:1:5
  ...
  WATERMARK_FRAMES_OK
  count=5
```

**Python UI 链路（`WatermarkPage`）：**

```
WatermarkPage（图片/视频 Tab + 质量模式）
  → RegionSelectorWidget 框选多矩形
  → MainViewModel.start_watermark_image(..., backend) / start_watermark_video(..., backend)
  → MediaBridge（MUSIC_WATERMARK_BACKEND）
  → media_cli watermark-inpaint-frames（一次加载，帧间复用）+ ffmpeg 抽帧/编码/混音
```

- **视频默认**：OpenCV 快速；可选切换 LaMa 精修。
- **图片默认**：LaMa 精修；可选切换 OpenCV 快速。
- 抽帧：`end_sec > start_sec` 时用 `-t duration`（含 `start_sec==0`）。

**性能说明：** 严禁逐帧起 `watermark-inpaint`（每帧重载 ~200MB LaMa）。视频用快速模式时通常为秒级；LaMa 精修仍可能数分钟（CUDA 有混合 EP 开销）。

**后处理：** Carve LaMa ONNX 输出为 0~255 float（非 PyTorch 版 0~1），`WatermarkInpainter` 自动识别并正确转 uint8，避免修复区域发白。

### 3.8 画质增强 / Real-ESRGAN 超分

对应产品文档 4.3 节。与去水印共用 `MUSIC_HAS_ONNXRUNTIME` + OpenCV。

```
models/realesr-general-x4v3.onnx   # scripts/download_realesrgan_model.bat（~5MB，不进 git）
```

| 脚本 | 作用 |
|------|------|
| `scripts/download_realesrgan_model.bat` | 下载 Heliosoph/realesrgan-onnx → `models/`（优先 hf-mirror） |

**双后端：**

| 模式 | 环境变量 | 适用 | 说明 |
|------|----------|------|------|
| **快速** | `MUSIC_UPSCALE_BACKEND=opencv` | **视频默认** | `cv::resize` INTER_CUBIC，无需模型 |
| **AI** | `MUSIC_UPSCALE_BACKEND=realesrgan` | **图片默认** | Real-ESRGAN x4v3 ONNX；分块 tile=192 |

**倍率：** CLI/UI 支持 `scale=2|4`。模型固有 4×；选 2× 时用「半分辨率推理」快路径（先缩到 1/2 再 4×，像素量约 1/4）。Tile=384。有 NVIDIA 且 `use_gpu` 时尝试 CUDA EP。

**自然度：** AI 结果与双三次放大按 `strength`（0~100，默认 65）混合，减轻 Real-ESRGAN 过锐/假细节；UI「AI 强度」滑条可调。也可设环境变量 `MUSIC_UPSCALE_STRENGTH=0.5`。

```
EnhancePage
  → MainViewModel.start_enhance_image / start_enhance_video
  → MediaBridge.upscale_image / upscale_video（MUSIC_UPSCALE_BACKEND）
  → media_cli upscale / upscale-frames（一次加载，帧间复用）+ ffmpeg 抽帧/编码/混音
```

**C++：** `SuperResolution`（`super_resolution.cpp`）→ `media_upscale_*` API。

**预览加载（`core/image_loader.py`）：**

| 步骤 | 实现 | 说明 |
|------|------|------|
| 1 解码 | OpenCV `imdecode` + `np.fromfile` | 超大 PNG / 中文路径；Qt 常对上万像素 PNG 失败 |
| 2 缩放 | CPU `cv::resize`，有 CUDA 设备时用 `cv2.cuda.resize` | 预览最长边约 2560 |
| 3 回退 | Qt `QImageReader` | 无 OpenCV 或解码失败时 |
| 4 显示 | `QGraphicsView` 软件合成（不透明底 + 全量刷新） | 曾用 OpenGL 视口，缩小时易残影，已去掉；解码仍走 OpenCV |

去水印页导入图片/预览帧同样走 `load_preview`。导入图片时额外调用 `MediaBridge.read_image_exif`（`third_party/exiftool`），在图片右上角悬浮摘要，完整标签进弹窗。

### 3.6 GPU 硬件加速

GPU 在本产品中承担 **AI 推理** 与 **视频硬解码** 两类加速目标；与 OpenCV **不冲突**。首页播放器（x64）已支持 **D3D11VA 硬解**。

#### 3.6.1 各模块 GPU 使用现状

| 模块 | 当前实现 | GPU 状态 | 说明 |
|------|----------|----------|------|
| **GPU 检测** | `nvidia-smi` 查显卡名 | ✅ 已实现 | 状态栏显示；D3D11VA 硬解不依赖 NVIDIA |
| **首页播放器解码** | D3D11VA + GPU→CPU 拷贝 | ✅ x64 已实现 | `VideoPlayerEngine` + `ffmpeg_hwaccel.cpp` |
| **离线批处理解码** | `VideoDecoder` D3D11VA | ✅ x64 已实现 | `preferHwaccel` / `media_cli iterate --hw`；失败回退 CPU |
| **OpenCV 帧滤镜** | CPU `cv::Mat` | CPU 运行 | 硬解后在 CPU 做 CLAHE 等，与硬解串联 |
| **Vosk ASR** | CPU 推理 | ✅ 可选 | `download_vosk_model.bat`；无模型时人声段兜底 |
| **实时字幕（流式）** | 云/本地流式 ASR | ⏳ 接口预留 | `core/live_subtitle`：2-pass + WS 分路；见 §5.8 |
| **llama.cpp 高光分析** | CPU（`n_gpu_layers=0`） | ⏳ 接口已有 | 需 `GGML_CUDA=ON` 编译 + 传入层数 |
| **去水印 LaMa** | ONNX Runtime + OpenCV | ✅ CPU EP（默认） | 已移除项目内 `cuda_runtime`；可选 `MUSIC_ORT_CUDA=1` |
| **4K 超分** | Real-ESRGAN ONNX + OpenCV | ✅ CPU EP（默认） | 2× 半分辨率快路径 + tile=384；CUDA 需系统 CUDA 12 运行库（`cublasLt64_12.dll` 等） |
| **图片预览解码** | OpenCV `imdecode` + 可选 CUDA resize | ✅ OpenCV；CUDA 视本机包 | `core/image_loader.py`；超大 PNG 不走 Qt 解码；对比视图不用 OpenGL 视口（防缩放残影） |
| **Qt 音频播放** | 系统解码器 | 可能硬解 | 与业务 GPU 开关无关 |

#### 3.6.2 界面与启动流程

**状态栏（`MainWindow` 顶部 `TopChrome`）：**

```
MusicEditing   [GPU  RTX…]   [授权  试用]   [深圳 晴 26°C]          v0.x
```

逻辑见 `client/scripts/viewmodels/main_vm.py` 的 `gpu_name` 属性：读取 `AppLogic.use_gpu` 与 `gpu_info["name"]`。  
天气见 `core/weather_service.py` + `MainWindow._refresh_weather`（§5.11）。视觉见 §3.3.1。

**启动时弹窗（`main_window.py`）：** 若 `cuda_available == false`，提示「当前为 CPU 模式，处理速度较慢。支持 NVIDIA 显卡硬件加速（CUDA）。」

**检测实现（`client/scripts/core/app_logic.py`）：**

```python
detect_gpu_info()
  └─ subprocess: nvidia-smi --query-gpu=name --format=csv,noheader
       ├─ 成功 → cuda_available=True, name=显卡型号
       └─ 失败 → 保持 CPU 模式
```

启动时 `AppLogic.prefer_hw_decode` 由 `gpu_enabled` 配置决定；`use_gpu` 仍用于后续 CUDA/llama（需 `nvidia-smi`）。

**播放器标题栏（硬解成功时）：**

```
测试视频.mp4  ·  1280x720  ·  D3D11VA  ·  有声音  ·  OpenCV:clahe/opencl
```

硬解失败或未启用时显示 `CPU解码`。滤镜标签后缀为实际设备：`/opencl` 或 `/cpu`。

**ViewModel 预留开关：** `MainViewModel.set_gpu_enabled(bool)` 可切换 `use_gpu` / `prefer_hw_decode`，目前**尚未绑定 UI 控件**。

#### 3.6.3 配置项（`client/resources/config/app.conf`）

```ini
gpu_enabled=true
```

| 键 | 含义 | 当前是否生效 |
|----|------|--------------|
| `gpu_enabled` | 是否请求 D3D11VA 硬解 | ✅ `AppLogic.prefer_hw_decode` → `PlayerBackend.set_hwaccel()` |
| `opencv_filter_device` | 滤镜设备 auto/cpu/opencl | ✅ → `FILTER_DEVICE` → `FrameProcessor` OpenCL/CPU |

`gpu_enabled=false` 时强制 CPU 软解。

#### 3.6.4 播放器硬解调用链（已实现）

```
app.conf  gpu_enabled=true
    │
    ▼
VideoPlayerWidget._do_open_file()
    └─ PlayerBackend.set_hwaccel(true)
           └─ stdin: HWACCEL on
                  └─ VideoPlayerEngine::setHwAccelPreferred(true)
    └─ PlayerBackend.open(path)
           └─ stdin: OPEN <path>
                  └─ openVideoDecoder(..., &hw) → D3D11VA
                  └─ stdout: OPEN_OK ... hw=1 hw_name=D3D11VA
    │
    ▼ 每帧
decodeNextFrameToFile()
    ├─ avcodec_receive_frame → GPU 帧
    ├─ av_hwframe_transfer_data → CPU NV12 等
    ├─ sws_scale → RGB24
    └─ FrameProcessor (OpenCV) → 显示
```

IPC：

```
HWACCEL on|off   →  HWACCEL_OK enabled=1|0
OPEN <path>      →  OPEN_OK ... hw=1 hw_name=D3D11VA
```

**要求：** x64 构建（`build_x64.bat` / `run_ui_x64.bat`）；Win32 旧 FFmpeg 无 hwcontext，自动 CPU 回退。

#### 3.6.5 与 OpenCV 的关系（OpenCL 滤镜）

```
磁盘 → FFmpeg D3D11VA 硬解 → GPU→CPU 拷贝 → OpenCV 滤镜（OpenCL UMat 优先，失败回退 CPU）→ 显示
```

- 硬解失败时自动 **回退 CPU 软解**，不影响播放。
- 滤镜默认 `opencv_filter_device=auto`：探测 `cv::ocl::haveOpenCL()`，用 `cv::UMat` 跑 resize/blur/CLAHE 等；**film**（通道矩阵+暗角）固定 CPU。
- 无 OpenCL 或算子失败时 **自动回退 CPU Mat**，不中断播放。
- 强制设备：`FILTER_DEVICE cpu|opencl|auto`；查询：`FILTER_STATUS`。
- 同一 GPU 上硬解 + OpenCL + llama CUDA 会争抢资源；实时播放滤镜仍有 upload/download 开销。

**代码位置：** `FrameProcessor::processOpenCL` / `processCpu`（`frame_processor.cpp`）。

#### 3.6.6 FFmpeg 硬解代码位置

| 文件 | 作用 |
|------|------|
| `shared/src/ffmpeg_hwaccel.cpp` | D3D11VA 设备、GPU→CPU 帧传输 |
| `shared/src/ffmpeg_compat.cpp` | `openVideoDecoder(..., HwAccelContext*)` |
| `client/src/core/video_player_engine.cpp` | 播放器硬解 +  lazy `sws_scale` |
| `client/src/core/video_decoder.cpp` | 批处理硬解（`preferHwaccel`）+ 缩略图 GPU→CPU |
| `client/src/player_main.cpp` | `HWACCEL` / `OPEN_OK hw=` |
| `client/scripts/core/player_backend.py` | `set_hwaccel()`、`PlayerInfo.hw_decode` |
| `client/scripts/core/media_bridge.py` | `set_prefer_hw_decode` → `iterate --hw` |
| `client/scripts/ui/video_player.py` | 标题显示 `D3D11VA` / `CPU解码` |

Win32/x64 差异：`third_party/ffmpeg.cmake` 检测 `hwcontext.h`，定义 `MUSIC_FFMPEG_HWACCEL`；`media_player` 链接 `d3d11`/`dxgi`。

#### 3.6.7 llama.cpp GPU 推理（智能切片）

高光分析路径：

```
MainViewModel._analyze_speech_pipeline()
  └─ MediaBridge.analyze_speech(...)
       └─ media_cli analyze-speech ...
            └─ HighlightAnalyzer → LlmEngine
                 └─ llama_model_load_from_file(..., n_gpu_layers)
```

**当前限制：**

1. CMake 默认 `GGML_CUDA=OFF`（见 `build_x64/CMakeCache.txt`），llama 推理全在 CPU。
2. `HighlightAnalyzer::getLlm()` 创建 `LlmConfig` 时 **`n_gpu_layers` 固定为 0**（`highlight_analyzer.cpp`），未读取 Python `use_gpu`。

**启用 GPU 推理需：**

```powershell
# 构建时（示例）
cmake -B build_x64 -A x64 -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=native
```

并在 C++ 侧根据 `use_gpu` 设置 `cfg.n_gpu_layers = -1`（全部层上 GPU）或具体层数。

#### 3.6.8 其它 GPU 相关代码

| 文件 | 作用 |
|------|------|
| `client/scripts/core/app_logic.py` | `detect_gpu_info()`、`prefer_hw_decode`、`use_gpu` |
| `client/scripts/viewmodels/main_vm.py` | `gpu_name` 属性、`set_gpu_enabled()` |
| `client/scripts/ui/main_window.py` | 状态栏 `GPU:` 标签、无 NVIDIA 弹窗 |
| `client/src/core/llm_engine.cpp` | `n_gpu_layers` 传给 llama（待启用 CUDA） |
| `client/src/core/highlight_analyzer.cpp` | 创建 `LlmConfig`（待接 GPU 层数） |

#### 3.6.9 实施优先级（建议）

1. ~~**P0** — `gpu_enabled` → 播放器硬解~~ ✅ 已完成  
2. **P1** — llama：`GGML_CUDA=ON` + `n_gpu_layers` 随 `use_gpu` 变化  
3. ~~**P2** — `VideoDecoder` / `media_cli iterate` 硬解~~ ✅ 已完成（复用 `ffmpeg_hwaccel`）  
4. **P3** — OpenCV CUDA 滤镜；超分已支持可选 `MUSIC_ORT_CUDA=1`

---

## 4. C++ 媒体引擎实现流程

### 4.1 VideoDecoder 解码流程（`client/src/core/video_decoder.cpp`）

#### 4.1.1 模块定位

`VideoDecoder` 是 **media_engine.dll 的核心解码类**，供 `media_cli.exe` 的 `probe` / `iterate` / 缩略图等**离线批处理**使用。它与首页播放器的 `VideoPlayerEngine`（`media_player.exe`）是**两套独立实现**，职责不同：

| 类 | 所在进程 | 用途 | 状态 |
|----|----------|------|------|
| `VideoDecoder` | `media_engine.dll` ← `media_cli.exe` | 探测元数据、逐帧遍历、抽缩略图 | 与播放器共用 `openVideoDecoder` / `HwAccelContext` |
| `VideoPlayerEngine` | `media_player.exe` | 实时拉帧、Seek、写 RGB 文件给 Python 显示 | 有 `lastTimestamp`、EOF、暂停等播放状态 |

调用链：

```
Python MediaBridge.probe_video / iterate_frames(--hw)
  └─ subprocess: media_cli.exe probe|iterate [--hw] ...
       └─ media_engine.cpp (C API, preferHwaccel)
            └─ VideoDecoder::open(path, preferHw)
                 └─ openVideoDecoder(..., &hw)  ← 与播放器相同
                 └─ iterateFrames / extractThumbnail
                      └─ 硬解帧：transferHwFrameToSoftware（缩略图）
```

**硬解：** `open(..., preferHwaccel=true)` 或 CLI `--hw`；失败自动 CPU。`iterate` 仅需时间戳，硬解表面 `unref` 即可；`extractThumbnail` 须 GPU→CPU 后再 `sws_scale`。
#### 4.1.2 为何称为「FFmpeg 旧版 API」

项目 `third_party/ffmpeg` 捆绑的是 **FFmpeg 3.x / 4.x 时代的 C API**（Win32 x86）。与 FFmpeg 4.0+ / 5.0+ 推荐的新写法对比如下：

| 环节 | 本工程当前用法（旧 API） | FFmpeg 新 API（未升级） |
|------|-------------------------|-------------------------|
| 全局注册 | `av_register_all()` | 4.0 起已废弃，链接时自动注册 |
| 网络 | `avformat_network_init()` | 仍可用，部分场景可省略 |
| 流上取编码器 | `fmtCtx->streams[i]->codec` 直接得到 `AVCodecContext*` | 应 `avcodec_alloc_context3` + `avcodec_parameters_to_context` |
| 解码一帧 | `avcodec_decode_video2(ctx, frame, &got, &pkt)` | `avcodec_send_packet` + `avcodec_receive_frame` |
| 释放包 | `av_init_packet` + `av_free_packet` | `av_packet_unref` 或栈上 `AVPacket pkt` + `av_packet_unref` |



| 关闭解码器 | `avcodec_close(ctx)` | `avcodec_free_context(&ctx)` |

**说明：** Win32 使用 `third_party/ffmpeg/x86/` 旧 API；x64 使用 `third_party/ffmpeg/x64/` 新 API，二者通过 `shared/ffmpeg_compat.cpp` 统一封装。下文 4.1.2 表格以 Win32 旧库为例；x64 已走 `send_packet` / `receive_frame` 路径。

#### 4.1.3 核心 FFmpeg 对象（读代码前先建立心智模型）

```
磁盘 MP4/MKV ...
    │
    ▼ avformat_open_input
AVFormatContext  ── 容器：时长、封装格式、若干 AVStream
    │
    ├── AVStream[0] 视频  ── time_base, avg_frame_rate, codecpar/codec
    ├── AVStream[1] 音频
    └── ...
    │
    ▼ avcodec_open2
AVCodecContext   ── 解码器实例：width, height, pix_fmt
    │
    ▼ av_read_frame → avcodec_decode_video2
AVPacket         ── 压缩的一小段 ES 数据（属于某 stream_index）
AVFrame          ── 解码后的 YUV 像素；pts 需乘 stream->time_base 得秒
    │
    ▼ sws_scale（仅缩略图路径）
RGB24 缓冲区     ── width × height × 3 字节，供 UI 或回调使用
```

#### 4.1.4 `open(filePath)` — 打开文件并逐步初始化

对应源码 `video_decoder.cpp` 第 45–139 行，顺序如下：

**① 前置检查**

- `close()` 清掉上次会话，避免句柄泄漏。
- `fileExists` + 扩展名白名单（mp4/mov/avi/flv/mkv/wmv/webm），不支持仅告警不阻断。

**② FFmpeg 全局初始化（旧 API）**

```cpp
av_register_all();        // 注册所有 muxer/demuxer/codec
avformat_network_init();  // 若 URL 为网络流需此步；本地文件也无害
```

**③ 打开容器并解析流信息**

```cpp
avformat_open_input(&fmtCtx, filePath.c_str(), nullptr, nullptr);
avformat_find_stream_info(fmtCtx, nullptr);
```

- 失败则 `avformat_close_input` 并返回 `false`。
- 成功后 `fmtCtx->duration`（单位 AV_TIME_BASE=1e6）可换算成片长秒数。

**④ 查找视频流**

```cpp
for (i = 0; i < fmtCtx->nb_streams; ++i)
    if (fmtCtx->streams[i]->codec->codec_type == AVMEDIA_TYPE_VIDEO)
        videoIdx = i;
```

- 只取**第一个**视频轨；多视频轨文件不选轨。

**⑤ 打开视频解码器**

```cpp
AVCodecContext* codecCtx = fmtCtx->streams[videoIdx]->codec;  // 旧 API：codec 嵌在 AVStream 内
AVCodec* codec = avcodec_find_decoder(codecCtx->codec_id);
avcodec_open2(codecCtx, codec, nullptr);
```

**⑥ 填充 `VideoInfo` 元数据**

| 字段 | 来源 |
|------|------|
| `width` / `height` | `codecCtx->width/height` |
| `durationSec` | `fmtCtx->duration / AV_TIME_BASE` |
| `fps` | `av_q2d(stream->avg_frame_rate)`，无效则默认 25 |
| `totalFrames` | `stream->nb_frames`，或为 0 时用 `duration * fps` 估算 |
| `codecName` | `codec->name`（如 h264、hevc） |
| `formatName` | `fmtCtx->iformat->name`（如 mov,mp4,m4a） |

**⑦ 保存到 `Impl`**

```cpp
impl_->formatCtx = fmtCtx;
impl_->codecCtx = codecCtx;
impl_->videoStreamIndex = videoIdx;
impl_->opened = true;
```

#### 4.1.5 `close()` — 资源释放顺序

```cpp
avcodec_close(impl_->codecCtx);      // 先关解码器
avformat_close_input(&impl_->formatCtx);  // 再关容器（旧 API 下 codec 指针来自 stream，勿单独 free）
```

与播放器引擎一致：**先 codec 后 format**，避免 Windows 下堆损坏。

#### 4.1.6 `iterateFrames(callback)` —  demux + 解码 + 回调

供 `media_cli iterate` 与智能切片前的帧扫描使用。流程：

```
av_frame_alloc()
loop:
  av_read_frame(formatCtx, &packet)     // 读出一个 AVPacket（可能是音频/视频/字幕）
  if packet.stream_index == videoStreamIndex:
      avcodec_decode_video2(codecCtx, frame, &gotPicture, &packet)
      if gotPicture:
          ts = frame->pts * time_base   // 无 pts 则用 frameIndex/fps 估算
          callback(frameIndex, ts)      // 返回 false 则提前结束
          frameIndex++
  av_free_packet(&packet)
  av_init_packet(&packet)
av_frame_free(&frame)
```

要点：

- **只处理视频包**；音频包被直接丢弃，不解码。
- **一帧可能需多个 packet**（H.264/HEVC B 帧）；旧 API 用 `gotPicture` 判断是否输出图像。
- **时间戳**：优先 `frame->pts × stream->time_base`；缺失时用帧序号/fps，长视频 seek 时会有误差。
- **stdout 协议**：CLI 层把每次回调格式化为 `PROGRESS:idx:total:timestamp` 行输出给 Python。

#### 4.1.7 `extractThumbnail(timestampSec, rgbBuffer, bufferSize)` —  Seek 后解一帧并转 RGB

```
av_seek_frame(formatCtx, videoStreamIndex, timestampSec * AV_TIME_BASE, AVSEEK_FLAG_BACKWARD)
avcodec_flush_buffers(codecCtx)       // seek 后必须 flush，否则解码花屏

sws_getContext(..., pix_fmt → AV_PIX_FMT_RGB24)

loop av_read_frame:
  解码视频包 → sws_scale(YUV → RGB24) → memcpy 到 rgbBuffer → break

sws_freeContext / av_free / av_frame_free
```

- **Seek 参数**：与播放器一致，对 `videoStreamIndex` 使用 `av_rescale_q(sec*AV_TIME_BASE, AV_TIME_BASE_Q, stream->time_base)`；失败再回退 `stream_index=-1`。勿把 `AV_TIME_BASE` 秒值直接当一流时间戳（会导致靠后时刻抽到黑帧）。
- **取帧**：seek 后可多解若干帧，跳过近黑/未就绪帧；RGB 按 `linesize` 收成紧凑缓冲。
- **缓冲区**：调用方必须提供 `width × height × 3` 字节；`media_extract_thumbnail` C API 负责分配/校验。

#### 4.1.8 与 C API / CLI 的对应关系

| C API（`media_engine.h`） | VideoDecoder 方法 | media_cli 子命令 |
|---------------------------|-------------------|------------------|
| `media_probe_video` | `open` → 读 `info()` → `close`（析构） | `probe <path>` |
| `media_iterate_frames(..., preferHw)` | `open(path, hw)` → `iterateFrames` | `iterate <path> [maxFrames] [--hw]` |
| `media_extract_thumbnail(..., preferHw)` | `open(path, hw)` → `extractThumbnail` | `thumbnail <path> <sec> <out.ppm> [--hw] [--max-w N]` |
| `media_decoder_hwaccel_name` | `isHwAccelActive` | stderr `DECODE_HW:d3d11va\|cpu` |

每次 CLI 调用都会 **新建一个 `VideoDecoder` 实例**，`open` 处理完即销毁，**不跨命令复用解码器**。

#### 4.1.9 与播放器解码的差异（避免混淆）

| 项目 | VideoDecoder | VideoPlayerEngine |
|------|--------------|-------------------|
| RGB 输出 | 仅缩略图；iterate 只回调时间戳 | 每帧 `sws_scale` 写 `frame.rgb` 文件 |
| 硬解 | `preferHwaccel` / CLI `--hw`，同 `ffmpeg_hwaccel` | `setHwAccelPreferred` |
| Seek | 仅 `extractThumbnail` 内 | `seek()` + `decodeNextFrameToFile` 连续拉帧 |
| 中文路径 | `pathForFfmpeg` | `pathForFfmpeg` |
| 音频轨 | 不处理 | 只检测 `hasAudioStream` 标志，实际声音由 Qt 播放 |

---

### 4.2 C API 导出 (`media_engine.h`)

供 DLL 内部和 CLI 共用：

```c
media_engine_init()
media_probe_video(path, &width, &height, ...)
media_iterate_frames(path, callback, userData, preferHwaccel)
media_extract_thumbnail(path, timestamp, rgb, size, preferHwaccel)
media_decoder_hwaccel_name()   // "d3d11va" | "cpu"
media_engine_shutdown()
```

### 4.3 CLI 文本协议 (`media_cli.cpp`)

Python 与 C++ 的通信格式（stdout = 协议，stderr = 日志）：

**probe 命令：**
```
media_cli probe <path>
→ stdout:
  PROBE_OK
  width=640
  height=272
  duration=48.090000
  fps=23.976024
  total_frames=1153
  codec=h264
  format=matroska,webm
```

**iterate 命令：**
```
media_cli iterate <path> [maxFrames] [--hw]
→ stderr:
  DECODE_HW:d3d11va   # 或 cpu
→ stdout (逐行):
  PROGRESS:0:1153:0.000000
  PROGRESS:1:1153:0.041708
  ...
  ITERATE_OK:10
```

`MediaBridge.iterate_frames`：当 `prefer_hw_decode`（默认跟随 `AppLogic`）为真时自动追加 `--hw`。

**thumbnail 命令：**
```
media_cli thumbnail <path> <timestamp_sec> <output.ppm> [--hw] [--max-w 160]
→ stderr:
  DECODE_HW:d3d11va   # 或 cpu
→ stdout:
  THUMBNAIL_OK
  width=160
  height=90
  src_width=1920
  src_height=1080
  timestamp=12.500000
  output=<path>
```

流程：`probe` 取分辨率 → `media_extract_thumbnail` 解 RGB24 → 可选最近邻缩到 `--max-w` → 写二进制 PPM（无新库）。  
`MediaBridge.extract_thumbnail` 默认缓存到 `%TEMP%/MusicEditing/thumbs/`（`core/thumbnail_cache.py`），视频未改则复用。

**upscale 命令：**
```
media_cli upscale <model.onnx|-> <输入图> <输出图> [scale=2|4]
→ stderr:
  UPSCALE_BACKEND:realesrgan   # 或 opencv
  UPSCALE_EP:cpu               # 或 cuda / opencv
  UPSCALE_SCALE:2
→ stdout:
  UPSCALE_OK
  output=<path>
  scale=2
```

**upscale-frames 命令：**
```
media_cli upscale-frames <model.onnx|-> <输入帧目录> <输出帧目录> [scale=2|4]
→ stdout (逐行):
  PROGRESS:1:125
  ...
  UPSCALE_FRAMES_OK
  count=125
  scale=2
```

`model.onnx` 为 `-` 或 `MUSIC_UPSCALE_BACKEND=opencv` 时走双三次快速放大。

---

## 5. 业务功能链路

按产品功能组织的端到端链路（UI → ViewModel → Bridge / CLI / FFmpeg）。

### 5.1 智能切片完整链路（演讲金句等 — 已落地）

对应产品文档 4.2 节。**场景：演讲金句、日常精彩片段、自定义识别**

```
用户点击「AI 智能分析」（场景=演讲金句）
  │
  ▼
MainViewModel.start_slice_analysis()  [后台线程]
  → _analyze_speech_pipeline()
      ├─ extract-audio → 16kHz WAV
      ├─ 有 Vosk：ASR → analyze-speech（LLM 或 C++ 金句规则）
      │         失败则 Python speech_highlights.score_transcript
      └─ 无 Vosk：silencedetect 人声段 → clips_from_speech_ranges
  → highlightsReady → SlicePage 时间轴/列表
  → SlicePage 后台抽各段中点缩略图 → 时间轴胶片条 + 列表图标
```

| 资源 | 路径 |
|------|------|
| 金句规则 | `client/scripts/core/speech_highlights.py` |
| Vosk 下载 | `scripts/download_vosk_model.bat` → `models/vosk-model-small-cn-0.22/` |
| C++ 规则加权 | `highlight_analyzer.cpp` fallbackAnalyze |
| 缩略图 | 见 §5.1.1 |

**Vosk：** `resolve_vosk_model_dir` 校验 `am/final.mdl`；勿把空路径当成 `.`。无模型时演讲金句仍可用（人声段兜底），完整「听懂金句」需下载模型。

### 5.1.1 高光缩略图时间轴（产品 4.2「缩略图+时间轴」）

对应产品文档：分析完成后展示所有高光片段的**缩略图 + 时间轴**。

```
highlightsReady(segments)
  │
  ▼
SlicePage._on_highlights
  → HighlightTimelineWidget.set_segments（色块）
  → 列表文字项
  → 后台线程：对每段 midpoint
        MediaBridge.extract_thumbnail(video, mid, max_width=160)
          → media_cli thumbnail … [--hw]
              → media_extract_thumbnail → PPM（可缩放）
          → thumbnail_cache（%TEMP%/MusicEditing/thumbs/）
  → thumbnailReady → 时间轴胶片 + QListWidget 图标
```

| 资源 | 路径 |
|------|------|
| CLI | `media_cli thumbnail`（`client/src/media_cli.cpp`） |
| C API | `media_extract_thumbnail` / `VideoDecoder::extractThumbnail` |
| Bridge | `MediaBridge.extract_thumbnail` |
| 缓存 | `client/scripts/core/thumbnail_cache.py` |
| UI | `HighlightTimelineWidget`（色块 + 缩略图条）+ 切片页列表图标 |
| 模型字段 | `HighlightSegment.thumbnail_path` |

**说明：** 不引入新第三方库；输出 PPM（Qt `QPixmap` 可直接加载）。硬解跟随 `prefer_hw_decode`（`--hw`）。手动增删片段后同样会重新拉缩略图。

**依赖配置**（`client/resources/config/app.conf`）：

| 键 | 说明 |
|----|------|
| `vosk_model_dir` | Vosk 中文模型**绝对路径**（含 `am/final.mdl`）；留空自动探测，勿填 `.` |
| `llm_model_path` | `.gguf` 模型路径；留空则 ASR + 规则打分 |
| `live_subtitle_provider` | 实时字幕后端：`stub` / `funasr` / `aliyun` / `tencent`（§5.8） |
| `live_subtitle_mode` | `two_pass` / `realtime_dynamic` / `delayed_steady` |

### 5.2 游戏高光（PySceneDetect 场景切点）

**场景：游戏高光** → `_analyze_game_fallback()`：

```
SlicePage「游戏高光」→ start_slice_analysis
  → _analyze_game_fallback
      → core.scene_detect.detect_scene_ranges
            AdaptiveDetector（默认，抗快速运镜）或 ContentDetector
            敏感度 → adaptive_threshold / content threshold
      → ranges_to_clipped_segments（按最短/最长整形，最多约 24 段）
      → 失败 / 未安装 → 时间轴规则 `_simulate_highlights` 兜底
```

| 资源 | 路径 |
|------|------|
| 封装 | `client/scripts/core/scene_detect.py` |
| 第三方库 | `scenedetect`（[PySceneDetect](https://www.scenedetect.com/)） |
| 安装 | `run_ui_*.bat` 自动 `pip install -e third_party/PySceneDetect`；或 `scripts/install_scenedetect.bat` |
| 本地源码 | **已随仓库** `third_party/PySceneDetect`（见 `README.MusicEditing.md`） |

**配置（`app.conf`）：**

| 键 | 说明 |
|----|------|
| `scenedetect_method` | `adaptive`（默认）\| `content` |
| `scenedetect_frame_skip` | 跳帧加速，`0` 最准 |

**限制：** 切的是画面内容变化场景，不是「击杀/高光事件」语义；后者仍属视觉模型范畴。长视频可把 `scenedetect_frame_skip` 调到 `1`–`3` 提速。

### 5.2.1 网易云热评滚动（已落地）

独立 Tab「热评滚动」。参考 B 站展示思路（[BV1vC4y1t7Wi](https://www.bilibili.com/video/BV1vC4y1t7Wi/)）与
[ObjTube/NeteaseMusic-qingtian-comment](https://github.com/ObjTube/NeteaseMusic-qingtian-comment)：
取歌曲热评并在播放区叠加滚动；视频生成器 [wyy-videoGen](https://github.com/ObjTube/wyy-videoGen) 供展示参考（本项目不接讯飞合成）。

```
用户输入歌曲链接或 ID → 回车 /「确定」
  │
  ▼
HotCommentsPage
  → core.netease_comments.fetch_hot_comments(limit≤100)
       优先级:
       1) netease_hot_comments_script（可选自定义脚本）
       2) netease_api_base（可选本地 NeteaseCloudMusicApi /comment/music）
       3) 直连 music.163.com /api/v1/resource/comments/R_SO_4_{id}
          （hotComments 优先，不足用 comments 补齐）
       4) demo 回退（可选）
  → CommentMarquee 滚动 + 本页 VideoPlayerWidget
```

**配置（`app.conf`）：**

| 键 | 说明 |
|----|------|
| `netease_api_base` | 如 `http://127.0.0.1:3000` |
| `netease_hot_comments_script` | 自定义脚本绝对路径 |
| `netease_hot_comments_demo` | 网络失败时是否演示数据 |

试例歌曲（晴天）：`186016` 或 `https://music.163.com/#/song?id=186016`


### 5.3 media_cli 新增命令（§4.3 补充）

**extract-audio：**
```
media_cli extract-audio <video> <out.wav>
→ EXTRACT_AUDIO_OK
```

**analyze-speech：**
```
media_cli analyze-speech <transcript.json> <model.gguf> <场景> <最短> <最长> <敏感度>
→ HIGHLIGHTS_OK
→ HIGHLIGHT|12.500|18.000|0.850
```

### 5.4 画质增强 / 超分完整链路

对应产品文档 4.3 节。

```
用户操作 EnhancePage
  │
  ▼
View: EnhancePage._on_run_image / _on_run_video
  → ViewModel.start_enhance_image / start_enhance_video
      → MediaBridge.upscale_image / upscale_video
          → media_cli upscale / upscale-frames
              → SuperResolution::upscaleImageFile
  → emit enhanceProgress / enhanceFinished
  │
  ▼
View 更新进度与结果预览
```

**当前限制：** 视频 AI 超分较慢。对比区左原图 / 右超分结果，中间 1px 细线；滚轮缩放当前侧，Ctrl+滚轮两侧同步；拖拽平移。预览经 `image_loader`（OpenCV 解码）；显示为不透明底软件合成，避免缩小时残影。

### 5.5 一键高光成片 / 静音剪掉 / 竖屏短视频

```
SlicePage「一键高光成片」
  → MainViewModel.export_highlights(out_dir)
      → MediaBridge.export_highlights
          → ffmpeg 按段 -ss/-t 切出 highlight_XXX.mp4（优先 -c copy）
          → concat demuxer → highlights_merged.mp4
  → exportFinished

SlicePage「静音剪掉」
  → MainViewModel.compact_speech(out_mp4)
      → MediaBridge.remove_silence
          → ffmpeg silencedetect 解析静音区间
          → 反推有声段 → export_clip × N → concat
  → silenceFinished

SlicePage「竖屏短视频」
  → 选裁切锚点（居中/偏上/偏下）→ 保存路径
  → MainViewModel.export_vertical_short
      ├─ 有高光片段：export_highlights 临时成片
      ├─ 同名 .srt/.vtt/.ass：重定时（按片段拼接轴）→ 临时 burn.srt
      └─ MediaBridge.export_vertical_short
            → ffmpeg scale+crop 9:16（默认 1080x1920）
            → 可选 subtitles 滤镜烧录
  → verticalExportFinished → 可送去超分/去水印
```

优先走捆绑 `ffmpeg.exe`，无需新 C++ CLI。静音阈值默认 `-35dB`、最短静音 `0.45s`。  
竖屏字幕依赖 **libass/subtitles** 滤镜；失败时自动降级为无字幕竖屏。裁切不做主体追踪（MVP）。

### 5.6 链接下载（yt-dlp）

```
DownloadPage（内嵌 Tab）
  ├─ 「下载」：粘贴 URL → 可选探测 → 下视频/音频 → 首页播放器
  └─ 「仅获取信息」：左右分栏
        ├─ 左：yt-dlp -J → 名称 + 列表；播放优先读该条目本地缓存
        └─ 右：媒体缓存列表（**唯一主键 = 页面URL哈希:列表项哈希**）
              · 同一链接可缓存多条（每种格式/每首歌各一条）
              · 页面级：info.json（再点获取可命中）
              · 媒体级：media/{item_key}_{歌名或格式名}[_av].ext
```

| 资源 | 路径 |
|------|------|
| 引擎 | `third_party/yt-dlp/yt-dlp.exe`（`scripts/download_yt_dlp.bat`） |
| 转码 | 项目已有 FFmpeg |
| 信息缓存 | `core/url_info_cache.py` → 默认 `~/MusicEditingInfoCache` |

探测会解析格式列表或歌单条目；若码率/体积与元数据时长不符，提示「疑似试听片段」。
列表支持 **双击/播放选中**（有该条目缓存则直接播，否则拉取并按主键落盘）、**删除选中 / 清空**（左列表仅 UI）；右侧列出**每条媒体缓存**，可独立播放/删除；「打开所属链接」载入左侧。
B 站等 DASH：**仅画面**格式播放时会自动 `format+bestaudio` 合并，避免无声；列表会标注「仅画面 / 仅音频」。

**注意：** 仅下载自有/授权素材；站点规则变化时更新 yt-dlp 即可。

### 5.7 图片 EXIF（ExifTool）

```
EnhancePage / WatermarkPage 导入图片
  → ExifPanel.load_path（异步）
      → MediaBridge.read_image_exif(full=True)
          → third_party/exiftool/exiftool.exe
  → 图片右上角悬浮摘要（常用字段约 5 行）
  → 点「全部」/ 双击摘要 → ExifFullDialog 查看完整标签
```

| 资源 | 路径 |
|------|------|
| 引擎 | `third_party/exiftool/exiftool.exe` + `exiftool_files/`（`scripts/download_exiftool.bat`） |
| UI | `client/scripts/ui/exif_panel.py`（`ExifPanel` 悬浮 + `attach_exif_overlay`） |

**注意：** 复制到 `bin/Release` 时必须同时复制 `exiftool_files`。不再在图片下方常驻大段文本。

### 5.8 外挂字幕与实时字幕

对应产品：本地播放显示字幕；实时同传按平台常见手法预留接口。

#### 5.8.1 外挂字幕（播放器叠加）

```
打开视频 / 点击「字幕…」
  │
  ▼
View: VideoPlayerWidget
  → 自动 find_sidecar_subtitles(同目录同名 .srt/.vtt/.ass)
     或 QFileDialog 手动选择
  → SubtitleTrack.from_file / text_at(position_sec)
  → GlVideoWidget.set_subtitle_text（底部半透明条）
「关字幕」→ clear
```

| 资源 | 路径 |
|------|------|
| 解析 | `client/scripts/core/subtitle_track.py`（SRT / VTT / 简易 ASS Dialogue） |
| 显示 | `client/scripts/ui/gl_video_widget.py` `_draw_subtitle` |
| 控件 | `client/scripts/ui/video_player.py`「字幕…」「关字幕」 |

**当前限制：** 仅外挂文件，不抽内嵌轨；ASS 只取文本时间轴，不渲染样式/特效。

#### 5.8.2 实时字幕（流式 2-pass + 分路，接口预留）

对齐 B 站/虎牙/云厂商常见工程手法（**已去掉 Whisper 离线批处理路径**）：

```
「实时字幕」
  → LiveSubtitleConfig（app.conf live_subtitle_*）
  → create_pipeline()
        StreamingAsrBackend（Pass-1 草稿 partial）
        → [句末] Pass-2 / end_utterance → final（稳态订正）
        → [可选] TranslationBackend
        → FanOutSink：PlayerOverlaySink + WebSocketSubtitleSink
```

| 手法 | 代码入口 | 状态 |
|------|----------|------|
| 2-pass 草稿→订正 | `TwoPassSubtitlePipeline` + `SubtitleDisplayMode` | ✅ 编排层 |
| 字幕与视频分路 | `WebSocketSubtitleSink` | ⏳ WS 发送体预留 |
| 游戏热词 | `HotwordLexicon` / `set_hotwords` | ✅ 数据结构 |
| 云 ASR / FunASR | `providers`: stub / aliyun / tencent / funasr | ⏳ 占位，未接 SDK |
| 播放器 PCM 抽头 | `pipeline.feed_pcm` | ⏳ 待接通解码音轨 |

| 资源 | 路径 |
|------|------|
| 包 | `client/scripts/core/live_subtitle/` |
| 配置 | `app.conf`：`live_subtitle_provider|mode|hotwords|ws_url|…` |
| UI | `VideoPlayerWidget`「实时字幕」 |

**接入步骤（扩展）：** 实现 `StreamingAsrBackend` → 在 `providers.build_asr` 注册 → 设置 `live_subtitle_provider` → 从播放器/直播拉流向 `feed_pcm` 喂 16 kHz s16le mono。

### 5.9 三大功能串联（一站式剪辑，异步）

对应产品文档 §5。任意一页 `import_video` 写入 `AppState.current_video`，其它页经 `videoLoaded` 同步；**结果接力**通过 `MainWindow.open_with_video(path, tab)`。

**线程约定：** 重活在后台 `threading.Thread`；UI 只在主线程经 Qt Signal（Queued）更新。

| 操作 | 线程 |
|------|------|
| `import_video`（probe） | 后台 → `videoLoaded` |
| `start_slice_analysis` | 后台 → `progressUpdated` / `highlightsReady` |
| 超分 / 去水印 / 导出高光 / 静音剪掉 | 已后台 |
| `open_with_video` 切 Tab | 主线程（先切页再异步 import） |
| `start_pipeline_queue` | 后台单线程顺序跑完整条链路（§5.9.1） |

```
切片「一键高光成片 / 静音剪掉」完成（后台）
  → 主线程弹窗「送去超分 / 送去去水印」
  → open_with_video：先切 Tab，再异步 import_video(成片)

去水印完成（视频）→「送去超分」
超分完成（视频）→「送去去水印」

各页按钮：「用当前视频」「送去超分」「送去去水印」
```

| 资源 | 路径 |
|------|------|
| 编排 | `MainWindow.open_with_video` |
| 弹窗 | `ui/workflow_link.py` |
| 触发 | `SlicePage` / `EnhancePage` / `WatermarkPage` |

### 5.9.1 批量全流程队列（无人值守）

对应产品文档 §5.4「自动切片 + 画质增强 + 去水印」一站式批量。独立 Tab「全流程队列」，**不走**各页完成弹窗，直接调 `MediaBridge` + 切片分析逻辑。

```
PipelineQueuePage「开始队列」
  → MainViewModel.start_pipeline_queue(paths, PipelineSettings)
      → 后台线程 core/pipeline_runner.run_pipeline_queue
            对每个视频顺序：
              probe
              → [可选] analyze（复用演讲/游戏切片）→ export_highlights → highlights_merged.mp4
              → [可选] upscale_video（OpenCV / Real-ESRGAN）
              → [可选] watermark_inpaint_video（角标预设区域）
      → pipelineItemUpdated / pipelineFinished（主线程刷新列表）
```

| 资源 | 路径 |
|------|------|
| UI | `ui/pipeline_queue_page.py`（双栏：左队列 / 右步骤芯片+参数；底栏进度与操作） |
| 模型 | `models/pipeline_model.py` |
| 编排 | `core/pipeline_runner.py` |
| VM | `MainViewModel.start_pipeline_queue` / pause / skip / cancel |

**参数要点：** 步骤可勾选；超分默认 OpenCV 2×，试跑秒数 `0=全程`；去水印默认关，开启后用右上/左上等角标框（按成片分辨率比例），无需逐文件框选。输出：`output_root/<文件名>/`（未选目录则视频旁 `pipeline_out/<文件名>/`）。

**控制：** 暂停（进度回调处挂起）、跳过当前、取消队列。

**限制：** 单线程顺序执行（非底层多任务并行）；角标去水印是启发式框，复杂游走水印仍需去水印页手动画框；切片场景与单页相同（游戏为规则兜底）。

### 5.10 视频补帧（FFmpeg minterpolate）

对应画质增强 Tab「视频补帧」：2× / 4× 提帧率，**无 AI 模型**（Practical-RIFE 等已移除）。

```
EnhancePage「视频补帧」
  → 独立时间段（默认试 15 秒；可全程）+ 快速/精细
  → MainViewModel.start_interpolate_video
      → MediaBridge.interpolate_video(quality=fast|quality)
          → ffmpeg -vf minterpolate=…
                fast → mi_mode=blend（默认，快）
                quality → mi_mode=mci（运动补偿，慢；失败回退 blend）
          → h264_mf / libx264 重编码 + AAC
  → interpolateProgress / interpolateFinished
```

| 资源 | 路径 |
|------|------|
| UI | `EnhancePage` 第三 Tab |
| VM | `start_interpolate_video`（`TaskType.INTERPOLATE`） |
| Bridge | `MediaBridge.interpolate_video` |
| 引擎 | `third_party/ffmpeg/{x64\|x86}/bin/ffmpeg.exe` |

**参数：** `factor=2|4`；`quality=fast|quality`；区间与超分「试 2 秒」**独立**。  
**限制：** 精细模式慢；插帧+重编码会柔化细节，观感可能不如原片锐利。

### 5.11 状态栏天气（IP 定位 + Open-Meteo）

顶栏显示本地城市与当前天气；**不阻塞 UI**。晴/雨时附带「今日氛围」滤镜推荐（趣味彩蛋）。

```
MainWindow.__init__
  → _start_weather_refresh()
      → QTimer 30min + 立即 _refresh_weather()
          → 后台线程 fetch_local_weather(timeout=5s)
                ├─ locate_by_ip()  # 按本机公网 IP 粗定位本地城市
                │     ├─ 太平洋/pconline ipJson（中文省市）→ Open-Meteo 地理编码
                │     ├─ ip-api → Nominatim 反查中文城市
                │     └─ ipwho.is → Nominatim 反查
                └─ Open-Meteo /v1/forecast?current=temperature_2m,weather_code,…
          → weatherUpdated.emit(WeatherInfo | None)
              → _on_weather_updated
                    ├─ 文案：如「深圳 小毛毛雨 25°C · 胶片」
                    ├─ recommend_mood(code)：晴→明亮(clahe) / 雨→胶片(film)
                    └─ 可点天气胶囊 → 切首页 + VideoPlayerWidget.set_filter_mode
```

| 资源 | 路径 |
|------|------|
| UI | `MainWindow._weather_label` / `_on_weather_clicked` |
| 服务 | `core/weather_service.py`（`recommend_mood` / `WeatherMood`） |
| 滤镜落地 | `HomePage.apply_opencv_filter` → `VideoPlayerWidget.set_filter_mode` |
| 天气 API | `https://api.open-meteo.com`（免 Key） |

**今日氛围映射（WMO code）：**

| 天气 | code | 推荐标签 | OpenCV 模式 |
|------|------|----------|-------------|
| 晴 / 晴间多云 | 0, 1 | 明亮 | `clahe` |
| 毛毛雨/雨/阵雨/雷暴 | 50–69, 80–82, ≥95 | 胶片 | `film` |
| 其它 | — | （无推荐） | — |

点击天气胶囊：切到首页并把滤镜套到本地预览播放器（需已打开视频才看得见画面变化；纯音乐无视频轨时滤镜下拉仍会切换）。首次拉到可推荐天气时，底栏提示一次「今日氛围…」。

**限制：** 城市来自**本机出口 IP 粗定位**（代理/VPN 会偏到出口城市，非 GPS）；单次请求超时 5s，失败显示「天气: 暂不可用」。不自动改滤镜，需用户点击。



### 5.12 波形 + 响度可视化 / 响度高潮

纯 FFmpeg：`showwavespic` 出波形图，`ebur128` + `ametadata=print` 出瞬时响度曲线；无新第三方库。

#### 首页播放器

```
打开视频/音乐
  → VideoPlayerWidget._start_audio_viz（后台线程）
      → core.audio_viz.analyze_media_audio
            showwavespic → .cache/audio_viz/*_wave.png
            ebur128=metadata=1,ametadata=print → M/S/I 采样
  → WaveformWidget：底图波形 + 青绿响度曲线 + 琥珀播放头
  → 点击波形 → seek
```

| 资源 | 路径 |
|------|------|
| UI | `ui/waveform_widget.py`（嵌在 `VideoPlayerWidget` 画面下方） |
| 分析 | `core/audio_viz.py` |
| 缓存 | `.cache/audio_viz/`（gitignore） |

#### 切片「响度高潮」

```
SlicePage 场景「响度高潮」→ AI 智能分析
  → MainViewModel._analyze_loudness_climaxes
      → analyze_ebur128 → find_loudness_climaxes（阈值随敏感度）
  → highlightsReady（同其它场景）
```

全流程队列场景下拉同样可选「响度高潮」。

**限制：** 长视频分析耗时随时长线性增长（有磁盘缓存）；响度高潮偏音乐/情绪起伏，不替代游戏视觉切点或演讲语义。



### 5.13 LUT / 一键调色

与 `FrameProcessor` 滤镜同层预设：`warm`（电影暖调）/ `cool`（冷调）/ `vintage`（复古）。

```
首页滤镜下拉 warm|cool|vintage
  → media_player set_filter → FrameProcessor 色矩阵（实时预览）

EnhancePage「一键调色」
  → 预览：OpenCV 同矩阵
  → 导出：MediaBridge.apply_color_grade
        图片 → OpenCV；视频 → FFmpeg lut3d（.cache/luts/*.cube）
  → 「套到播放器滤镜」→ HomePage.apply_opencv_filter
```

| 资源 | 路径 |
|------|------|
| C++ | `frame_processor.h/.cpp`（Warm/Cool/Vintage） |
| Python | `core/color_grade.py`（cube 生成 + lut3d） |
| UI | `EnhancePage` Tab「一键调色」；播放器滤镜下拉 |
| VM | `MainViewModel.start_color_grade` |

**限制：** 调色矩阵为风格化近似，非专业电影 LUT 包；`lut3d` 失败时回退 `colorbalance`/`eq`。


---

## 6. 模块间依赖关系

```
CMakeLists.txt (顶层)
├── third_party/ffmpeg     → INTERFACE 库，链接 8 个 .lib
├── third_party/llama.cpp  → 静态库 llama（选项 MUSIC_ENABLE_LLAMA）
│   └── music_llama        → INTERFACE 别名，供业务模块链接
├── shared/media_shared    → 静态库
├── client/media_engine    → SHARED DLL，依赖 shared + ffmpeg
├── client/media_cli       → EXE，依赖 media_engine
├── client/media_player    → EXE，FFmpeg 统一播放器（Python 子进程拉帧）
├── client/media_engine_test
└── tests/shared_test
```

```
Python 模块依赖
main.py
└── ui/main_window.py
    ├── ui/highlight_timeline.py   (高光色块 + 缩略图条)
    ├── core/thumbnail_cache.py    (缩略图 PPM 缓存)
    ├── core/time_format.py        (m:ss / 区间格式化)
    ├── ui/video_player.py
    │   ├── core/player_backend.py  (subprocess → media_player.exe)
    │   ├── core/subtitle_track.py  (外挂 SRT/VTT/ASS)
    │   ├── core/live_subtitle/     (实时字幕 2-pass 接口预留)
    │   ├── core/audio_viz.py       (showwavespic + ebur128)
    │   ├── ui/waveform_widget.py   (波形/响度条)
    │   └── ui/gl_video_widget.py   (OpenGL 画面 + 字幕叠加)
    ├── ui/enhance_page.py / watermark_page.py
    │   ├── ui/exif_panel.py       (ExifTool 元数据面板)
    │   └── core/image_loader.py   (OpenCV 解码 / 可选 CUDA 缩放 / Qt 回退)
    └── viewmodels/main_vm.py
        ├── models/video_model.py
        ├── core/app_logic.py      (GPU 检测)
        ├── core/weather_service.py (IP 定位 + Open-Meteo 天气)
        ├── core/pipeline_runner.py (批量全流程：切片→超分→去水印)
        ├── core/scene_detect.py (PySceneDetect 游戏高光切点)
        ├── core/live_subtitle/ (流式字幕 2-pass / WS 分路预留)
        ├── core/asr_engine.py (Vosk)
        └── core/media_bridge.py   (subprocess → media_cli / FFmpeg；含 interpolate_video 补帧)
```

---

## 7. 已实现 vs 待实现

| 功能 | 状态 | 说明 |
|------|------|------|
| FFmpeg 视频打开/探测 | ✅ | VideoDecoder + probe |
| 视频帧遍历 | ✅ | iterateFrames + CLI |
| 缩略图提取 | ✅ | `media_cli thumbnail` + `MediaBridge.extract_thumbnail` + 磁盘小图缓存 |
| 高光时间轴（缩略图） | ✅ | `HighlightTimelineWidget` 色块+胶片条；列表带图标；见 §5.1.1 |
| 三大功能串联 | ✅ | `open_with_video` + 完成弹窗/「送去」；批量全流程队列见下 |
| 批量全流程队列 | ✅ | `PipelineQueuePage`：切片成片→超分→去水印；暂停/跳过/取消（§5.9.1） |
| 切片/导入异步 | ✅ | `import_video` / `start_slice_analysis` 后台线程；UI 收 Signal |
| 手动切片 | ✅ | SlicePage 起止时间添加/删除/清空；不依赖 Vosk |
| 视频补帧 | ✅ | EnhancePage：FFmpeg minterpolate；默认快速 blend，可选精细 MCI；默认试 15 秒 |
| PySide6 多标签 UI | ✅ | 首页/切片/画质增强/去水印/热评滚动；个人中心占位 |
| Studio 视觉主题 | ✅ | `ui/theme.py` 炭黑+琥珀；顶栏胶囊；§3.3.1 |
| 网易云热评滚动 | ✅ | `HotCommentsPage` + 外部爬虫脚本协议；默认演示数据 |
| 首页本地播放器 | ✅ | FFmpeg 视频 + Qt 音乐；OpenGL 显示；**点击画面暂停/继续** |
| 波形/响度可视化 | ✅ | showwavespic + ebur128；播放器下方可点击 seek（§5.12） |
| 响度高潮切片 | ✅ | 场景「响度高潮」；ebur128 峰值成段（§5.12） |
| 外挂字幕 | ✅ | SRT/VTT/简易 ASS；同名自动加载；`GlVideoWidget` 底部叠加 |
| 实时字幕（流式/同传） | ⏳ | `core/live_subtitle` 接口预留（2-pass、WS 分路、云/FunASR 占位）；§5.8.2 |
| OpenCV 帧处理 | ✅ | `FrameProcessor`：CPU + **OpenCL UMat**；标题 `OpenCV:clahe/opencl` |
| GLEW / OpenGL 第三方 | ✅ | `third_party/opengl`；`media_player` 链 GLEW |
| OpenGL 视频显示 | ✅ | `GlVideoWidget` 替换 QLabel；首页/热评页播放器共用 |
| MVVM 双向绑定 | ✅ | Signal/Slot |
| GPU 检测与状态栏 | ✅ | `nvidia-smi`；顶栏 `GPU: 型号` / `CPU 模式`（§3.6） |
| 状态栏天气 | ✅ | IP 定位 + Open-Meteo；晴/雨「今日氛围」推荐滤镜（§5.11） |
| FFmpeg GPU 硬解（D3D11VA） | ✅ | 播放器 + `VideoDecoder`/`iterate --hw`；失败回退 CPU |
| llama.cpp GPU 推理 | ⏳ | `n_gpu_layers` 接口已有，默认 0；需 `GGML_CUDA=ON` |
| AI 高光识别（演讲/解说） | ✅ | 演讲金句：Vosk+LLM/金句词；无人声模型时人声段兜底 |
| AI 高光识别（游戏） | ✅ | PySceneDetect 场景切点（§5.2）；失败回退时间规则 |
| 批量导出剪辑 | ✅ | `一键高光成片` → 分片 + `highlights_merged.mp4`（ffmpeg） |
| 竖屏短视频导出 | ✅ | 切片成片→9:16 裁切+字幕烧录（§5.5）；居中/偏上/偏下 |
| 静音剪掉 | ✅ | `静音剪掉` → silencedetect + 拼接紧凑口播 |
| OpenCV 趣味滤镜 | ✅ | film / warm / cool / vintage / neon / comic / pixel；播放器下拉 |
| LUT 一键调色 | ✅ | 增强页 Tab + lut3d 导出；与 FrameProcessor 同预设（§5.13） |
| OpenCV GPU 滤镜 | ✅ | OpenCL `cv::UMat`（`opencv_filter_device=auto`）；失败回退 CPU |
| 链接下载 | ✅ | `DownloadPage` + yt-dlp；「仅获取信息」左右分栏 + `url_info_cache`（歌名/片名目录） |
| 图片 EXIF | ✅ | 图片右上角悬浮摘要 +「全部」弹窗；`exif_panel.py`（§5.7） |
| 4K 超分 | ✅ | `EnhancePage` + Real-ESRGAN ONNX / OpenCV 双三次；`upscale` CLI；预览 `image_loader`（OpenCV） |
| 去水印 | ✅ | `WatermarkPage` 快速(OpenCV)/精修(LaMa)；视频默认快速 + 帧批复用 |
| 授权/卡密 | ⏳ | network.py 预留 |
| llama.cpp 第三方集成 | ✅ | third_party/llama.cpp，CMake 目标 `music_llama` |
| llama 本地推理业务 | ✅ | analyze-speech 已接入智能切片 |

---

## 8. llama.cpp 集成说明

### 8.0 目录与构建

```
third_party/llama.cpp/          ← junction 指向 PDFSearchEngine 同目录
third_party/CMakeLists.txt      ← MUSIC_ENABLE_LLAMA 开关 + add_subdirectory
third_party/llama.cpp.README.md ← 联接/clone 说明
```

**CMake 选项（默认仅编核心库）：**

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `MUSIC_ENABLE_LLAMA` | ON | 是否编译 llama.cpp |
| `LLAMA_BUILD_TOOLS` | OFF | 不编 CLI/server 工具 |
| `LLAMA_BUILD_TESTS` | OFF | 不编测试 |
| `BUILD_SHARED_LIBS` | OFF | 静态库 `llama.lib` |

**链接示例：**

```cmake
if(MUSIC_HAS_LLAMA)
    target_link_libraries(your_target PRIVATE music_llama)
endif()
```

**产物：** `build/lib/Release/llama.lib` + ggml 依赖库

**架构：** 与主工程相同（推荐 x64 `build_x64`）；Win32 亦可编（视预编译包而定）。

---

## 9. 扩展接入指南

### 9.1 接入 llama.cpp 本地推理

1. 在 `client/` 或 `shared/` 新增 `llm_engine` 模块，`target_link_libraries(... music_llama)`
2. 封装 `llama_model_load` / `llama_decode` 为 C API，经 `media_cli` 或独立 exe 暴露给 Python
3. 演讲链路已接 Vosk + analyze-speech；游戏高光已接 PySceneDetect 场景切点（§5.2），语义级「击杀检测」仍可另接视觉模型

### 9.2 接入 PyTorch AI 模型

游戏「击杀/高光事件」语义检测若接视觉模型：可在 `_analyze_game_fallback` 中叠在 PySceneDetect 结果之上；演讲链路已走 ASR，无需逐帧 PyTorch。

### 9.3 视频导出（已落地）

已用 Python + 捆绑 ffmpeg 实现，无需 C++ `clip` 子命令：

1. `MediaBridge.export_clip` / `concat_clips` / `export_highlights` / `export_vertical_short`
2. `MediaBridge.detect_speech_segments` / `remove_silence`
3. `MainViewModel.export_highlights` / `compact_speech` / `export_vertical_short`
4. `SlicePage`：「一键高光成片」「竖屏短视频」「静音剪掉」

### 9.4 x64 与 Win32 并存

已支持双预设，无需手动替换单一 `third_party/ffmpeg`：

| 命令 | 架构 | FFmpeg |
|------|------|--------|
| `build.bat` | Win32 | `third_party/ffmpeg/x86/` |
| `build_x64.bat` | x64 | `third_party/ffmpeg/x64/`（`setup_ffmpeg_x64.bat`） |

x64 构建后 Python 可逐步改为 **ctypes 直接加载** `media_engine.dll`，减少 subprocess 开销。

### 9.5 启用 GPU 加速（路线图）

详见 **§3.6**。已完成：

1. 播放器 D3D11VA 硬解  
2. ~~**VideoDecoder 硬解**~~：`open(..., preferHw)` + `media_cli iterate --hw`（复用 `ffmpeg_hwaccel`）  
3. **个人中心 UI**：`set_gpu_enabled()` → 播放硬解 / iterate `--hw`（不再默认开 LaMa CUDA）  
4. ~~**ONNX CUDA EP**~~：默认关闭；已移除 `third_party/cuda_runtime`  

待做：llama `GGML_CUDA` + `n_gpu_layers`。

### 9.6 接入实时字幕（流式 ASR / 云同传）

见 **§5.8.2**。步骤摘要：

1. 实现 `StreamingAsrBackend`（`feed_pcm` / `on_partial` / `on_final`）
2. 在 `core/live_subtitle/providers.py` 的 `build_asr` 注册，并设 `live_subtitle_provider`
3. 可选：实现 `TranslationBackend`、填写 `live_subtitle_ws_url` 启用字幕分路
4. 接通播放器或直播音轨 PCM → `TwoPassSubtitlePipeline.feed_pcm`

---

## 10. 运行命令速查

```powershell
.\build.bat                    # 编译（含 llama.lib，可用 -DMUSIC_ENABLE_LLAMA=OFF 跳过）
.\build_x64.bat                # x64 编译（自动导入 FFmpeg/OpenCV/ONNX）
.\run_ui_x64.bat               # 一步启动 x64 UI（缺 ONNX 自动导入，缺产物自动编译）
.\run_test.bat                 # 测试 FFmpeg（默认 Titanic.mkv）
.\run_test.bat "D:\a.mp4"      # 指定视频测试
.\run_ui.bat                   # 启动 UI
.\scripts\download_lama_model.bat          # 去水印精修模型
.\scripts\download_realesrgan_model.bat    # 画质超分模型（~5MB）
.\scripts\download_yt_dlp.bat              # 链接下载引擎 yt-dlp.exe → third_party/yt-dlp/
.\scripts\download_exiftool.bat            # 图片 EXIF：exiftool.exe + exiftool_files → third_party/exiftool/
.\scripts\download_vosk_model.bat          # 演讲金句 ASR：vosk-model-small-cn-0.22 → models/
.\scripts\install_scenedetect.bat          # 游戏高光：安装 PySceneDetect（scenedetect）
```