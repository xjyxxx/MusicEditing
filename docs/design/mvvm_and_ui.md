# MVVM 与 UI 分层

> **上级枢纽：** [implementation_flow.md](implementation_flow.md)  
> **相关：** [feature_flows.md](feature_flows.md) · [player_decode_flow.md](player_decode_flow.md) · [media_engine.md](media_engine.md)

本文对应原实现说明 §3：Model / ViewModel / View、播放器入口、OpenCV 滤镜、GPU、去水印与超分。

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

**导航：** 顶部 `QMenuBar`（文件 / 核心 / 工作流 / 趣味 / 帮助）→ `MainWindow._goto_page` → `QStackedWidget`。顶栏胶囊显示当前页名。页面索引见 `ui/workflow_link.py`（`TAB_*` / `MENU_GROUPS` / `PAGE_TITLES`），`open_with_video` 接力仍用同一套索引。

| 页面 | 类 | 菜单分组 | 状态 |
|------|-----|----------|------|
| 首页 | `HomePage` + `VideoPlayerWidget` + `CommentMarquee` | 核心 | 本地预览；可叠热评弹幕 |
| 智能切片 | `SlicePage` + `HighlightTimelineWidget` | 核心 | 分析 / 手动 / 成片 / 竖屏短视频 |
| 画质增强 | `EnhancePage` + `ExifPanel` + `ElidedPathLabel` | 核心 | 超分 / 补帧 / 调色；长路径中间省略不撑布局 |
| 去水印 | `WatermarkPage` + `RegionSelectorWidget` + `ExifPanel` | 核心 | 图片/视频去水印 + EXIF |
| 全流程队列 | `PipelineQueuePage` | 工作流 | 切片→超分→去水印（见 [feature_flows.md](feature_flows.md) §5.9.1） |
| 下载与热评 | `DownloadPage`（一步获取） | 工作流 | 评论列表 + 唯一媒体 → 首页叠播 |
| BGM 混音 | `BgmPage` | 工作流 | FFmpeg 叠 BGM；Demucs 可选分轨（[feature_flows](feature_flows.md) §5.16） |
| 封面工厂 | `CoverPage` | 趣味 | 最清晰帧 + 标题 PNG（[feature_flows](feature_flows.md) §5.14） |
| 音频趣味 | `AudioFunPage` | 趣味 | 整轨趣味 + 梗音叠加/倍数（[feature_flows](feature_flows.md) §5.15） |
| 个人中心 | `ProfilePage` | 帮助 | 卡密本地校验、GPU 开关、输出目录、关于 |

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

顶栏为圆角 `TopChrome`：品牌名 + 当前页胶囊 + GPU/授权/天气 + 版本号。主功能入口为菜单栏。主按钮用 `objectName="primaryButton"` 或 Studio `StudioPrimary`。长路径标签用 `ui/elided_label.ElidedPathLabel`（中间省略 + Tooltip），避免撑开布局。

**Studio 页壳（`ui/studio_kit.py`）：** 个人中心 / 切片 / 增强 / 队列统一 **Hero + Card + 12px 全宽边距**（切片全页滚动；增强 Hero+Tabs；队列 Hero+双栏面板）。避免各页 QGroupBox「半成品感」。

### 3.4 首页播放器交互（统一 FFmpeg 播放器）

架构见 [流程图/README.md](../流程图/README.md)；**解码/同步/存储详解见 [player_decode_flow.md](player_decode_flow.md)**。

```
HomePage
  ├─ VideoPlayerWidget（Python GUI）
  │    ├─ GlVideoWidget（QOpenGLWidget）显示 RGB 帧；点击画面 → 未加载时打开文件对话框（同「打开文件」），已加载则暂停/继续；暂停时中央显示三角播放图标
  │    ├─ 视频：FFmpeg 解码画面 + Qt QMediaPlayer 音频主时钟；长播漂移可软校正（seek 对齐，见 player_decode_flow §5）
  │    ├─ 音乐：仅 Qt QMediaPlayer（mp3/wav/flac/m4a…），封面占位图
  │    ├─ 「打开文件」同时支持视频与音乐过滤器；「信息」→ ffprobe 媒体信息对话框
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
| **llama.cpp 高光分析** | `MUSIC_LLM_N_GPU_LAYERS` | ✅ 随 GPU 开关 | `set_prefer_cuda` → `-1`（全层）/ `0`（CPU）；需 `MUSIC_GGML_CUDA=ON` 构建才真正上 GPU |
| **去水印 LaMa** | ONNX Runtime + OpenCV | ✅ GPU 开则 CUDA EP，失败回退 CPU | `set_prefer_cuda` → `MUSIC_ORT_CUDA`；无捆绑 `cuda_runtime` |
| **4K 超分** | Real-ESRGAN ONNX + OpenCV | ✅ 同上 | 2× 半分辨率快路径 + tile=384；CUDA 需系统 CUDA 12 运行库 |
| **图片预览解码** | OpenCV `imdecode` + 可选 CUDA resize | ✅ OpenCV；CUDA 视本机包 | `core/image_loader.py`；超大 PNG 不走 Qt 解码；对比视图不用 OpenGL 视口（防缩放残影） |
| **Qt 音频播放** | 系统解码器 | 可能硬解 | 与业务 GPU 开关无关 |

#### 3.6.2 界面与启动流程

**状态栏（`MainWindow` 顶部 `TopChrome`）：**

```
MusicEditing   [GPU  RTX…]   [授权  试用]   [深圳 晴 26°C]          v0.x
```

逻辑见 `client/scripts/viewmodels/main_vm.py` 的 `gpu_name` 属性：读取 `AppLogic.use_gpu` 与 `gpu_info["name"]`。  
天气见 `core/weather_service.py` + `MainWindow._refresh_weather`（[feature_flows](feature_flows.md) §5.11）。视觉见上文 §3.3.1。

**启动时弹窗（`main_window.py`）：** 首屏 `show` 后约 500ms 再扫依赖；若需开箱向导则弹出；若向导不弹且 `cuda_available == false`，再提示「当前为 CPU 模式…」。

**启动流畅度：**
- 功能页懒创建：`MainWindow` 启动只建首页，其它 TAB 首次点开再 `_ensure_page`
- `media_player.exe` 延迟到首次打开本地视频再启动（见 [player_decode_flow](player_decode_flow.md) §7）
- 临时帧清理在后台线程（`main.py`），不堵 UI

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

**ViewModel 开关：** `MainViewModel.set_gpu_enabled(bool)` 切换 `use_gpu` / `prefer_hw_decode`，写入 `app.conf` 的 `gpu_enabled`；同时 `MediaBridge.set_prefer_cuda(use_gpu)` 控制超分/LaMa 的 `MUSIC_ORT_CUDA`。**个人中心** `ProfilePage` 已绑定该开关。

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
MainViewModel.set_gpu_enabled(True)
  └─ MediaBridge.set_prefer_cuda(True)
       └─ env MUSIC_LLM_N_GPU_LAYERS=-1
            └─ media_cli analyze-speech
                 └─ HighlightAnalyzer::getLlm() 读环境变量
                      └─ LlmEngine(n_gpu_layers=-1)
```

**已接通：**

1. Python：`set_prefer_cuda` 同步设置 `MUSIC_LLM_N_GPU_LAYERS`（开=-1，关=0）
2. C++：`HighlightAnalyzer` 读取该环境变量写入 `LlmConfig.n_gpu_layers`

**构建注意：** 当前若使用 `third_party/llama_prebuilt`（无 CUDA），层数设置不会真正上 GPU。要从源码编 CUDA 版：

```powershell
# 检测到 nvcc 时 build_x64.bat 会加 -DMUSIC_GGML_CUDA=ON
# 或手动：
cmake -B build_x64 -A x64 -DMUSIC_GGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=native
```

并确保 CMake 走 `llama.cpp` 源码路径而非仅 prebuilt。

#### 3.6.8 其它 GPU 相关代码

| 文件 | 作用 |
|------|------|
| `client/scripts/core/app_logic.py` | `detect_gpu_info()`、`prefer_hw_decode`、`use_gpu` |
| `client/scripts/viewmodels/main_vm.py` | `gpu_name` 属性、`set_gpu_enabled()` |
| `client/scripts/ui/main_window.py` | 状态栏 `GPU:` 标签、无 NVIDIA 弹窗 |
| `client/scripts/core/media_bridge.py` | `MUSIC_ORT_CUDA` + `MUSIC_LLM_N_GPU_LAYERS` |
| `client/src/core/llm_engine.cpp` | `n_gpu_layers` 传给 llama |
| `client/src/core/highlight_analyzer.cpp` | 读 `MUSIC_LLM_N_GPU_LAYERS` |

#### 3.6.9 实施优先级（建议）

1. ~~**P0** — `gpu_enabled` → 播放器硬解~~ ✅ 已完成  
2. ~~**P1** — llama：`n_gpu_layers` 随 `use_gpu`~~ ✅ 已接通；CUDA 构建视本机 Toolkit  
3. ~~**P2** — `VideoDecoder` / `media_cli iterate` 硬解~~ ✅ 已完成（复用 `ffmpeg_hwaccel`）  
4. **P3** — OpenCV CUDA 滤镜；超分已支持可选 `MUSIC_ORT_CUDA=1`

---

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

个人中心开启 GPU 且检测到 NVIDIA 时，`MediaBridge.set_prefer_cuda(True)` 将子进程环境设为 `MUSIC_ORT_CUDA=1`，超分/LaMa 优先尝试 CUDA EP；缺 CUDA 运行库或 EP 失败则回退 CPU，再失败回退 OpenCV inpaint。项目**不再**捆绑 `third_party/cuda_runtime`。缺模型时 UI/`MainViewModel` 提示运行 `scripts\download_lama_model.bat` / `download_realesrgan_model.bat`。

视频默认 OpenCV 快速模式；图片/精修默认 LaMa（有 GPU 开关则优先 CUDA，否则 CPU）。

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
WatermarkPage（图片/视频 Tab + 质量模式 + AI 运行提示）
  → RegionSelectorWidget 框选多矩形
  → 「智能建议」：对预览帧四角做对比度/边缘密度启发式，生成 1–2 个角标矩形（可再编辑）
  → 图片「导入文件夹」批量：同一套区域 + 快速/精修（精修受正式版门禁）→ 输出目录
  → 视频「多视频批量」：多文件顺序处理同一角标预设（复用单视频管线）
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

