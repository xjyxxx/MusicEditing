# C++ 媒体引擎与 llama.cpp

> **上级枢纽：** [implementation_flow.md](implementation_flow.md)  
> **相关：** [feature_flows.md](feature_flows.md) · [mvvm_and_ui.md](mvvm_and_ui.md) · [player_decode_flow.md](player_decode_flow.md)

本文对应原实现说明 §4（VideoDecoder / C API / CLI）与 §8（llama.cpp）。

---

## 1. C++ 媒体引擎实现流程

### 1.1 VideoDecoder 解码流程（`client/src/core/video_decoder.cpp`）

#### 1.1.1 模块定位

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
#### 1.1.2 为何称为「FFmpeg 旧版 API」

项目 `third_party/ffmpeg` 捆绑的是 **FFmpeg 3.x / 4.x 时代的 C API**（Win32 x86）。与 FFmpeg 4.0+ / 5.0+ 推荐的新写法对比如下：

| 环节 | 本工程当前用法（旧 API） | FFmpeg 新 API（未升级） |
|------|-------------------------|-------------------------|
| 全局注册 | `av_register_all()` | 4.0 起已废弃，链接时自动注册 |
| 网络 | `avformat_network_init()` | 仍可用，部分场景可省略 |
| 流上取编码器 | `fmtCtx->streams[i]->codec` 直接得到 `AVCodecContext*` | 应 `avcodec_alloc_context3` + `avcodec_parameters_to_context` |
| 解码一帧 | `avcodec_decode_video2(ctx, frame, &got, &pkt)` | `avcodec_send_packet` + `avcodec_receive_frame` |
| 释放包 | `av_init_packet` + `av_free_packet` | `av_packet_unref` 或栈上 `AVPacket pkt` + `av_packet_unref` |



| 关闭解码器 | `avcodec_close(ctx)` | `avcodec_free_context(&ctx)` |

**说明：** Win32 使用 `third_party/ffmpeg/x86/` 旧 API；x64 使用 `third_party/ffmpeg/x64/` 新 API，二者通过 `shared/ffmpeg_compat.cpp` 统一封装。下文 §1.1.2 表格以 Win32 旧库为例；x64 已走 `send_packet` / `receive_frame` 路径。

#### 1.1.3 核心 FFmpeg 对象（读代码前先建立心智模型）

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

#### 1.1.4 `open(filePath)` — 打开文件并逐步初始化

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

#### 1.1.5 `close()` — 资源释放顺序

```cpp
avcodec_close(impl_->codecCtx);      // 先关解码器
avformat_close_input(&impl_->formatCtx);  // 再关容器（旧 API 下 codec 指针来自 stream，勿单独 free）
```

与播放器引擎一致：**先 codec 后 format**，避免 Windows 下堆损坏。

#### 1.1.6 `iterateFrames(callback)` —  demux + 解码 + 回调

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

#### 1.1.7 `extractThumbnail(timestampSec, rgbBuffer, bufferSize)` —  Seek 后解一帧并转 RGB

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

#### 1.1.8 与 C API / CLI 的对应关系

| C API（`media_engine.h`） | VideoDecoder 方法 | media_cli 子命令 |
|---------------------------|-------------------|------------------|
| `media_probe_video` | `open` → 读 `info()` → `close`（析构） | `probe <path>` |
| `media_iterate_frames(..., preferHw)` | `open(path, hw)` → `iterateFrames` | `iterate <path> [maxFrames] [--hw]` |
| `media_extract_thumbnail(..., preferHw)` | `open(path, hw)` → `extractThumbnail` | `thumbnail <path> <sec> <out.ppm> [--hw] [--max-w N]` |
| `media_decoder_hwaccel_name` | `isHwAccelActive` | stderr `DECODE_HW:d3d11va\|cpu` |

每次 CLI 调用都会 **新建一个 `VideoDecoder` 实例**，`open` 处理完即销毁，**不跨命令复用解码器**。

#### 1.1.9 与播放器解码的差异（避免混淆）

| 项目 | VideoDecoder | VideoPlayerEngine |
|------|--------------|-------------------|
| RGB 输出 | 仅缩略图；iterate 只回调时间戳 | 每帧 `sws_scale` 写 `frame.rgb` 文件 |
| 硬解 | `preferHwaccel` / CLI `--hw`，同 `ffmpeg_hwaccel` | `setHwAccelPreferred` |
| Seek | 仅 `extractThumbnail` 内 | `seek()` + `decodeNextFrameToFile` 连续拉帧 |
| 中文路径 | `pathForFfmpeg` | `pathForFfmpeg` |
| 音频轨 | 不处理 | 只检测 `hasAudioStream` 标志，实际声音由 Qt 播放 |

---

### 1.2 C API 导出 (`media_engine.h`)

供 DLL 内部和 CLI 共用：

```c
media_engine_init()
media_probe_video(path, &width, &height, ...)
media_iterate_frames(path, callback, userData, preferHwaccel)
media_extract_thumbnail(path, timestamp, rgb, size, preferHwaccel)
media_decoder_hwaccel_name()   // "d3d11va" | "cpu"
media_engine_shutdown()
```

### 1.3 CLI 文本协议 (`media_cli.cpp`)

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

---

## 2. llama.cpp 集成说明

### 2.0 目录与构建

```
third_party/llama.cpp/          ← 源码（CUDA / Vulkan / FROM_SOURCE 时用）
third_party/llama_prebuilt/     ← CPU 预编译（默认）
third_party/CMakeLists.txt      ← MUSIC_ENABLE_LLAMA / MUSIC_GGML_CUDA / MUSIC_GGML_VULKAN
scripts/setup_llama_gpu.py      ← 推荐 Vulkan；可选 CUDA
```

**CMake 选项：**

| 选项 | 默认 | 说明 |
|------|------|------|
| `MUSIC_ENABLE_LLAMA` | ON | 是否启用 llama |
| `MUSIC_LLAMA_FROM_SOURCE` | OFF | 强制用源码，忽略 prebuilt |
| `MUSIC_GGML_VULKAN` | OFF | Vulkan GPU（**无需 CUDA Toolkit**，推荐） |
| `MUSIC_GGML_CUDA` | OFF | CUDA GPU（需 Toolkit，体积大） |
| `CMAKE_CUDA_ARCHITECTURES` | `75;80;86;89` | 仅 CUDA；4060=89 |

**从 prebuilt(CPU) 切到 GPU（推荐 Vulkan）：**

```powershell
python scripts\setup_llama_gpu.py install-vulkan   # 若缺 SDK
# 新开终端或设置:
$env:VULKAN_SDK="C:\VulkanSDK\<version>"
python scripts\setup_llama_gpu.py vulkan           # 源码链入 media_cli
```

CMake 日志应出现 `GGML_VULKAN=ON`。个人中心打开 GPU，`models\` 放置 `.gguf` 后演讲金句可走 GPU 层（`MUSIC_LLM_N_GPU_LAYERS=-1`）。

（CUDA：`setup_llama_gpu.py install-cuda` / `cuda`，需下载完整 Toolkit。）

运行时：`MUSIC_LLM_N_GPU_LAYERS`（`MediaBridge.set_prefer_cuda`：开=-1，关=0）。

**链接示例：**

```cmake
if(MUSIC_HAS_LLAMA)
    target_link_libraries(your_target PRIVATE music_llama)
endif()
```

**产物：** 源码模式下由 llama 目标传递依赖（含 ggml-cuda）；prebuilt 为静态 `llama.lib` + ggml-cpu。

**架构：** 推荐 x64 `build_x64`。

---
