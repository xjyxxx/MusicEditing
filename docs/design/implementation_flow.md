# AI 本地音视频处理工具 — 软件实现流程说明

> 本文档描述当前代码的实际实现链路，对应产品交互文档中的功能设计。

---

## 1. 总体架构

软件采用 **C++ 底层 + Python UI** 双层架构，中间通过 **子进程 CLI** 通信（解决 64 位 Python 与 32 位 FFmpeg 库的位数不匹配问题）。

```
┌─────────────────────────────────────────────────────────────┐
│                    Python 客户端 (64-bit)                    │
│  ┌─────────┐   ┌──────────────┐   ┌─────────────────────┐  │
│  │  View   │◄─►│  ViewModel   │◄─►│  Model (dataclass)  │  │
│  │ PySide6 │   │ MainViewModel│   │ VideoModel/Task...  │  │
│  └─────────┘   └──────┬───────┘   └─────────────────────┘  │
│                       │                                      │
│                ┌──────▼───────┐                              │
│                │ MediaBridge  │  subprocess                  │
│                └──────┬───────┘                              │
└───────────────────────┼─────────────────────────────────────┘
                        │ stdout/stderr 文本协议
┌───────────────────────▼─────────────────────────────────────┐
│                 C++ 媒体引擎 (32-bit Win32)                  │
│  media_cli.exe ──► media_engine.dll ──► VideoDecoder        │
│                           │                                  │
│                    FFmpeg (avcodec/avformat/swscale)         │
└─────────────────────────────────────────────────────────────┘
```

### 编译产物

| 文件 | 作用 |
|------|------|
| `media_shared.lib` | 公共静态库（日志、工具、配置） |
| `media_engine.dll` | FFmpeg 封装，导出 C API |
| `media_cli.exe` | 命令行入口，供 Python 子进程调用 |
| `media_engine_test.exe` | C++ 独立测试程序 |

---

## 2. 构建与启动流程

### 2.1 编译流程

**Win32（默认）**

```
build.bat  →  cmake -A Win32  →  build/bin/Release
              FFmpeg: third_party/ffmpeg/x86/
              OpenCV: D:/APP/opencv/build_x86
```

**x64**

```
scripts/setup_ffmpeg_x64.bat   # 首次：下载 FFmpeg 到 third_party/ffmpeg/x64/
build_x64.bat  →  cmake -A x64  →  build_x64/bin/Release
                  FFmpeg: third_party/ffmpeg/x64/
                  OpenCV: D:/APP/opencv/build
```

Presets 见 `CMakePresets.json`：`windows-win32-release` / `windows-x64-release`。

**关键点：**
- FFmpeg **分目录**：Win32 用 `third_party/ffmpeg/x86/`，x64 用 `third_party/ffmpeg/x64/`
- 两套构建输出互不覆盖（`build/` vs `build_x64/`）
- Python 客户端始终 64-bit；C++ 引擎架构与 FFmpeg/OpenCV 一致

### 2.2 启动与退出

**启动：**
```
run_ui.bat / python client/scripts/main.py
  ├─ PySide6 QApplication（setQuitOnLastWindowClosed）
  ├─ MainViewModel（AppLogic GPU 检测、MediaBridge）
  ├─ detect_gpu_info() → 状态栏显示 GPU: 型号 或 CPU 模式
  ├─ 无 NVIDIA GPU 时弹窗提示 CPU 模式（见 §3.6）
  └─ 显示 5 标签页，进入事件循环
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
| `TaskModel` | 任务 ID、类型、状态、进度 |
| `HighlightSegment` | 高光起止时间、得分、是否选中 |
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
| `import_image(path)` | 图片去水印导入 |
| `update_watermark_range(start, end)` | 视频去水印时间段 |
| `update_slice_params(...)` | 参数滑块变更 |
| `set_output_dir(path)` | 导出目录选择 |

### 3.3 View 层 (`client/scripts/ui/main_window.py`)

| 页面 | 类 | 状态 |
|------|-----|------|
| 首页 | `HomePage` + `VideoPlayerWidget` | 本地预览播放器 + 功能卡片导航 |
| 智能切片 | `SlicePage` | **已实现完整交互** |
| 画质增强 | `PlaceholderPage` | 占位，待接入 AI |
| 去水印 | `WatermarkPage` + `RegionSelectorWidget` | **图片/视频去水印 UI 已实现**（框选多区域、时间段） |
| 热评滚动 | `HotCommentsPage` | **独立 Tab**：输入歌曲链接/ID → 热评滚动叠加播放器 |
| 个人中心 | `PlaceholderPage` | 占位，待接入授权 |

播放器组件：`client/scripts/ui/video_player.py`（PySide6 QLabel + `PlayerBackend` → `media_player.exe`）

### 3.4 首页播放器交互（统一 FFmpeg 播放器）

架构详见 `docs/流程图/README.md`，**解码/同步/存储详解见 `docs/design/player_decode_flow.md`**。

```
HomePage
  ├─ VideoPlayerWidget（Python GUI）
  │    ├─ QLabel 显示 RGB 帧（QImage/QPixmap，不用 QMediaPlayer 视频）
  │    ├─ Qt QMediaPlayer 仅输出音频（与 FFmpeg 视频并行）
  │    ├─ QTimer 15ms 轮询 + **以 Qt 音频 position 为主时钟** 同步画面
  │    │     （音频未到下一帧时刻则保持画面；落后时跳帧追赶）
  │    ├─ Seek/播放时音视频同时 jump 到同一时间点
  │    ├─ 打开视频 → fileOpened → ViewModel.import_video（全局共享）
  │    └─ 关闭窗口 → shutdown() 停止音频并 kill media_player.exe
  └─ videoLoaded 信号 → 智能切片页导入后，主页播放器自动同步加载

PlayerBackend (Python)
  └─ subprocess stdin/stdout ↔ media_player.exe

media_player.exe (C++)
  ├─ VideoPlayerEngine — FFmpeg Stateful 解码 → 临时 frame.rgb
  └─ FrameProcessor — OpenCV 帧滤镜（编译启用时：CLAHE/降噪/锐化）
```

View **不直接调用 FFmpeg**，通过 `PlayerBackend` 子进程与 C++ 播放器通信。

### 3.5 OpenCV 帧滤镜（`FrameProcessor`）

OpenCV **仅用于解码后的 RGB24 帧处理**，不参与 FFmpeg 解码本身。智能切片 ASR/LLM 链路当前**未使用** OpenCV。

#### 3.5.1 配置项（`client/resources/config/app.conf`）

```ini
# OpenCV 帧滤镜（需编译时启用 OpenCV）：clahe | denoise | sharpen | off
opencv_filter=clahe
```

| 值 | 效果 | OpenCV 实现 |
|----|------|-------------|
| `clahe`（默认） | 对比度增强，偏「画质预览」 | `COLOR_RGB2Lab` + `createCLAHE` |
| `denoise` | 轻度降噪 | `bilateralFilter` |
| `sharpen` | 锐化 | `GaussianBlur` + `addWeighted` |
| `off` | 关闭，直通原帧 | 不调用 OpenCV |

#### 3.5.2 界面显示

打开视频后，播放器标题栏（`VideoPlayerWidget._title`）会拼接滤镜状态，例如：

```
测试视频.mp4  ·  1280x720  ·  FFmpeg  ·  有声音  ·  OpenCV:clahe
```

逻辑见 `client/scripts/ui/video_player.py`：

- 启动时从 `load_app_config()` 读取 `opencv_filter`（默认 `clahe`）
- 若值不为 `off`，标题追加 `OpenCV:{模式名}`
- **注意**：标题显示只表示「已下发滤镜配置」；若编译时未链接 OpenCV（输出目录无 `opencv_world4120.dll`），画面仍为直通，无视觉效果

#### 3.5.3 端到端调用链

```
app.conf  opencv_filter=clahe
    │
    ▼
VideoPlayerWidget._do_open_file()
    ├─ PlayerBackend.open(path)          # 重启 media_player，OPEN 视频
    └─ _apply_opencv_filter()
           └─ PlayerBackend.set_filter("clahe")
                  └─ stdin: FILTER clahe
                         └─ media_player.exe → VideoPlayerEngine::setFrameFilter()
                                └─ FrameProcessor::setModeFromString("clahe")
    │
    ▼ 播放中每帧
VideoPlayerEngine::decodeNextFrameToFile()
    ├─ FFmpeg 解码 + sws_scale → RGB24 缓冲区
    └─ FrameProcessor::processRgbFrame(rgb, w, h)   # 原地修改 RGB
           └─ Python 读 frame.rgb → QImage → QLabel 显示
```

IPC 协议（`player_main.cpp`）：

```
FILTER clahe     →  FILTER_OK mode=clahe
FILTER off       →  FILTER_OK mode=off
FILTER invalid   →  ERROR invalid_filter
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

### 3.6 GPU 硬件加速

GPU 在本产品中承担 **AI 推理** 与 **视频硬解码** 两类加速目标；与 OpenCV **不冲突**。首页播放器（x64）已支持 **D3D11VA 硬解**。

#### 3.6.1 各模块 GPU 使用现状

| 模块 | 当前实现 | GPU 状态 | 说明 |
|------|----------|----------|------|
| **GPU 检测** | `nvidia-smi` 查显卡名 | ✅ 已实现 | 状态栏显示；D3D11VA 硬解不依赖 NVIDIA |
| **首页播放器解码** | D3D11VA + GPU→CPU 拷贝 | ✅ x64 已实现 | `VideoPlayerEngine` + `ffmpeg_hwaccel.cpp` |
| **离线批处理解码** | `VideoDecoder` D3D11VA | ✅ x64 已实现 | `preferHwaccel` / `media_cli iterate --hw`；失败回退 CPU |
| **OpenCV 帧滤镜** | CPU `cv::Mat` | CPU 运行 | 硬解后在 CPU 做 CLAHE 等，与硬解串联 |
| **Vosk ASR** | CPU 推理 | ❌ 未启用 | 智能切片转写阶段 |
| **llama.cpp 高光分析** | CPU（`n_gpu_layers=0`） | ⏳ 接口已有 | 需 `GGML_CUDA=ON` 编译 + 传入层数 |
| **去水印 LaMa** | ONNX Runtime + OpenCV | ✅ CPU EP（默认） | 已移除项目内 `cuda_runtime`；可选 `MUSIC_ORT_CUDA=1` |
| **4K 超分** | 占位页 | ⏳ 未接入 | 预期 ONNX / CUDA |
| **Qt 音频播放** | 系统解码器 | 可能硬解 | 与业务 GPU 开关无关 |

#### 3.6.2 界面与启动流程

**状态栏（`MainWindow` 顶部）：**

```
GPU: NVIDIA GeForce RTX 3060    # 检测到 NVIDIA 且 use_gpu=true
GPU: CPU 模式                   # 无 NVIDIA 或 use_gpu=false
```

逻辑见 `client/scripts/viewmodels/main_vm.py` 的 `gpu_name` 属性：读取 `AppLogic.use_gpu` 与 `gpu_info["name"]`。

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
测试视频.mp4  ·  1280x720  ·  D3D11VA  ·  有声音  ·  OpenCV:clahe
```

硬解失败或未启用时显示 `CPU解码`。

**ViewModel 预留开关：** `MainViewModel.set_gpu_enabled(bool)` 可切换 `use_gpu` / `prefer_hw_decode`，目前**尚未绑定 UI 控件**。

#### 3.6.3 配置项（`client/resources/config/app.conf`）

```ini
gpu_enabled=true
```

| 键 | 含义 | 当前是否生效 |
|----|------|--------------|
| `gpu_enabled` | 是否请求 D3D11VA 硬解 | ✅ `AppLogic.prefer_hw_decode` → `PlayerBackend.set_hwaccel()` |

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

#### 3.6.5 与 OpenCV 的关系（无逻辑冲突）

```
磁盘 → FFmpeg D3D11VA 硬解 → GPU→CPU 拷贝 → OpenCV CPU 滤镜 → 显示
```

- 硬解失败时自动 **回退 CPU 软解**，不影响播放。
- 同一 GPU 上硬解 + OpenCV CUDA + llama CUDA 会争抢资源，需分时调度。

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
4. **P3** — OpenCV CUDA 滤镜、4K 超分模型 GPU 推理  

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

- **Seek 参数**：此处用 `videoStreamIndex` + `AV_TIME_BASE`；播放器 `VideoPlayerEngine::seek` 则用 `stream_index=-1`（全局时间基），二者等价场景不同，详见 `player_decode_flow.md`。
- **缓冲区**：调用方必须提供 `width × height × 3` 字节；`media_extract_thumbnail` C API 负责分配/校验。

#### 4.1.8 与 C API / CLI 的对应关系

| C API（`media_engine.h`） | VideoDecoder 方法 | media_cli 子命令 |
|---------------------------|-------------------|------------------|
| `media_probe_video` | `open` → 读 `info()` → `close`（析构） | `probe <path>` |
| `media_iterate_frames(..., preferHw)` | `open(path, hw)` → `iterateFrames` | `iterate <path> [maxFrames] [--hw]` |
| `media_extract_thumbnail(..., preferHw)` | `open(path, hw)` → `extractThumbnail` | （API 已有，CLI 未单独暴露） |
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

---

### 5.1 智能切片完整链路（演讲/解说类 — 已落地）

对应产品文档 4.2 节。**场景：演讲金句、日常精彩片段、自定义识别**

```
用户点击「AI 智能分析」
  │
  ▼
MainViewModel.start_slice_analysis()
  → 判断 scene ∈ {演讲金句, 日常精彩片段, 自定义识别}
  → _analyze_speech_pipeline()
      │
      ├─ 1. media_cli extract-audio  → FFmpeg 抽 16kHz WAV
      ├─ 2. AsrEngine (Vosk)         → 带时间戳文稿 JSON
      ├─ 3. media_cli analyze-speech → llama.cpp 语义选段（无模型则规则兜底）
      └─ emit highlightsReady
  │
  ▼
SlicePage 列表展示 [起止时间 + 得分]
```

**依赖配置**（`client/resources/config/app.conf`）：

| 键 | 说明 |
|----|------|
| `vosk_model_dir` | Vosk 中文模型目录，默认 `models/vosk-model-small-cn-0.22` |
| `llm_model_path` | `.gguf` 模型路径；留空则 ASR + 规则打分 |

### 5.2 游戏高光（占位）

**场景：游戏高光** → `_analyze_game_fallback()`：抽音频 + 时间轴规则切分，视觉动作检测待接入。

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

### 5.3 原模拟链路（已替换）

~~`_simulate_highlights()` 均匀切分~~ → 演讲类走 ASR+LLM，游戏类仍用规则兜底。

### 5.4 media_cli 新增命令（§4.3 补充）

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

---

## 6. 原 §5 智能切片（旧描述保留参考）

以下为初版帧遍历描述，演讲类已不再逐帧扫描：

```
用户点击「AI 智能分析」（旧）
  → media_cli iterate（已改为仅游戏兜底可选）
```

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
    ├── ui/video_player.py
    │   └── core/player_backend.py  (subprocess → media_player.exe)
    └── viewmodels/main_vm.py
        ├── models/video_model.py
        ├── core/app_logic.py      (GPU 检测)
        └── core/media_bridge.py   (subprocess → media_cli.exe)
```

---

## 7. 已实现 vs 待实现

| 功能 | 状态 | 说明 |
|------|------|------|
| FFmpeg 视频打开/探测 | ✅ | VideoDecoder + probe |
| 视频帧遍历 | ✅ | iterateFrames + CLI |
| 缩略图提取 | ✅ | extractThumbnail（API 已有，UI 未接） |
| PySide6 多标签 UI | ✅ | 首页/切片/去水印/热评滚动；超分与个人中心占位 |
| 网易云热评滚动 | ✅ | `HotCommentsPage` + 外部爬虫脚本协议；默认演示数据 |
| 首页本地播放器 | ✅ | FFmpeg 视频帧 + Qt 音频，音频主时钟同步 |
| OpenCV 帧处理 | ✅ | `FrameProcessor`：播放器实时滤镜 + 缩略图；配置 `opencv_filter`，UI 标题显示 `OpenCV:clahe` |
| MVVM 双向绑定 | ✅ | Signal/Slot |
| GPU 检测与状态栏 | ✅ | `nvidia-smi`；顶栏 `GPU: 型号` / `CPU 模式`（§3.6） |
| FFmpeg GPU 硬解（D3D11VA） | ✅ | 播放器 + `VideoDecoder`/`iterate --hw`；失败回退 CPU |
| llama.cpp GPU 推理 | ⏳ | `n_gpu_layers` 接口已有，默认 0；需 `GGML_CUDA=ON` |
| OpenCV GPU 滤镜 | ⏳ | 当前 CPU；与硬解无冲突（§3.6.4） |
| AI 高光识别（演讲/解说） | ✅ | Vosk ASR + llama.cpp / 规则兜底 |
| AI 高光识别（游戏） | ⏳ | 规则兜底，视觉模型待接入 |
| 批量导出剪辑 | ⏳ | UI 按钮已有，逻辑未写 |
| 4K 超分 | ⏳ | 占位页 |
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

**架构：** 与主工程相同（当前 Win32）；本地 LLM 推理后续建议独立 x64 模块与 32 位 FFmpeg 并存。

---

## 9. 扩展接入指南

### 9.1 接入 llama.cpp 本地推理

1. 在 `client/` 或 `shared/` 新增 `llm_engine` 模块，`target_link_libraries(... music_llama)`
2. 封装 `llama_model_load` / `llama_decode` 为 C API，经 `media_cli` 或独立 exe 暴露给 Python
3. 在 `MainViewModel._simulate_highlights()` 处替换为 LLM/多模态打分

### 9.2 接入 PyTorch AI 模型

在 `MainViewModel.start_slice_analysis()` 中：

1. `iterate_frames` 回调里对每帧图像推理（需 C++ 侧增加帧数据导出或 Python 侧用 OpenCV 读帧）
2. 替换 `_simulate_highlights()` 为真实打分 + 片段聚合逻辑

### 9.3 接入视频导出

1. C++ 侧新增 `media_clip_export(start, end, outputPath)` API
2. `media_cli` 增加 `clip` 子命令
3. `MediaBridge` 增加 `export_clips()` 方法
4. `SlicePage._on_export()` 调用 ViewModel 批量导出

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

---

## 10. 运行命令速查

```powershell
.\build.bat                    # 编译（含 llama.lib，可用 -DMUSIC_ENABLE_LLAMA=OFF 跳过）
.\build_x64.bat                # x64 编译（自动导入 FFmpeg/OpenCV/ONNX）
.\run_ui_x64.bat               # 一步启动 x64 UI（缺 ONNX 自动导入，缺产物自动编译）
.\run_test.bat                 # 测试 FFmpeg（默认 Titanic.mkv）
.\run_test.bat "D:\a.mp4"      # 指定视频测试
.\run_ui.bat                   # 启动 UI
```
