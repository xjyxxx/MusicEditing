# 模块依赖与扩展指南

> **上级枢纽：** [implementation_flow.md](implementation_flow.md)  
> **相关：** [feature_flows.md](feature_flows.md) · [media_engine.md](media_engine.md) · [mvvm_and_ui.md](mvvm_and_ui.md)

本文对应原实现说明 §6（依赖树）与 §9（扩展/路线图，已落地项改为短表）。

---

## 1. 模块间依赖关系

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
    │   ├── core/media_probe.py     (ffprobe 封装/码流探测)
    │   ├── ui/media_info_dialog.py (媒体信息对话框)
    │   ├── core/audio_viz.py       (showwavespic + ebur128)
    │   ├── ui/waveform_widget.py   (波形/响度条)
    │   └── ui/gl_video_widget.py   (OpenGL 画面)
    ├── ui/enhance_page.py / watermark_page.py
    │   ├── ui/elided_label.py     (长路径中间省略)
    │   ├── ui/region_selector.py  (框选 + 四角智能建议)
    │   ├── ui/exif_panel.py       (ExifTool 元数据面板)
    │   └── core/image_loader.py   (OpenCV 解码 / 可选 CUDA 缩放 / Qt 回退)
    ├── ui/export_options_dialog.py (高光/竖屏/抖音预设 + 封面话题)
    ├── ui/setup_wizard.py         (首次开箱依赖向导)
    ├── ui/media_library_page.py   (本地素材库)
    ├── ui/profile_page.py         (个人中心：卡密 / GPU / 诊断打包 / 清理临时帧)
    ├── ui/cover_page.py           (封面工厂)
    │   └── core/cover_factory.py  (最清晰帧 + 标题 PNG)
    ├── ui/stego_page.py           (溯源：频域/回声/LSB/EXIF)
    │   ├── core/blind_watermark_dct.py
    │   ├── core/echo_watermark.py
    │   ├── core/stego_lsb.py
    │   └── core/exif_stamp.py
    ├── core/face_track.py         (竖屏跟脸采样)
    ├── core/publish_pack.py       (封面+话题草稿)
    ├── core/progress_eta.py       (线性 ETA)
    ├── core/rife_interp.py        (可选 RIFE ONNX)
    ├── ui/audio_fun_page.py       (音频趣味：整轨 + 梗音叠加)
    │   ├── core/audio_fx.py       (atempo+setpts 同步变速；areverse+reverse 倒放)
    │   └── core/sfx_overlay.py    (adelay+atempo 梗音叠加)
    ├── ui/bgm_page.py             (BGM 混音 / 人声分离)
    │   ├── core/bgm_mix.py        (FFmpeg 混音)
    │   └── core/demucs_sep.py     (可选 Demucs → third_party/demucs)
    └── viewmodels/main_vm.py
        ├── models/video_model.py
        ├── core/app_logic.py      (GPU 检测 / 卡密持久化)
        ├── core/network.py        (本地卡密校验)
        ├── core/weather_service.py (IP 定位 + Open-Meteo 天气)
        ├── core/pipeline_runner.py (批量全流程：切片→超分→去水印；产物配额)
        ├── core/diag_pack.py (诊断 zip：player/cli/ORT)
        ├── core/resource_cleanup.py (临时帧清理 / 输出上限)
        ├── core/scene_detect.py (PySceneDetect 游戏高光切点)
        ├── core/game_semantic.py (切点+HUD；可选 game_event.onnx)
        ├── core/film_templates.py (一键竖屏成片模板)
        ├── core/download_recover.py (下载失败白话与可恢复动作)
        ├── core/trial_run.py (开箱试跑 15 秒)
        ├── core/export_naming.py (成片规范命名)
        ├── core/setup_status.py (开箱依赖检测)
        ├── core/asr_engine.py (Vosk)
        ├── core/media_bridge.py   (ctypes 优先 + media_cli / FFmpeg)
        └── core/media_engine_ctypes.py  (直连 media_engine.dll)
```

---

## 2. 扩展与路线图

### 2.1 已落地（详见专文）

| 主题 | 说明位置 |
|------|----------|
| 视频导出 / 高光 / 竖屏 / 静音 | [feature_flows.md](feature_flows.md) §5.5 |
| x64 与 Win32 双预设；ctypes 优先 probe/thumbnail | 枢纽 §2；[media_engine.md](media_engine.md) |
| 播放器 / VideoDecoder D3D11VA 硬解 | [mvvm_and_ui.md](mvvm_and_ui.md) GPU 节 |
| 热评短视频成片（ass/danmaku/cards） | [feature_flows.md](feature_flows.md) §5.2.1 |
| 实时字幕 | 已移除（见 feature_flows §5.8） |

### 2.2 接入 llama.cpp 本地推理

1. 在 `client/` 或 `shared/` 新增模块，`target_link_libraries(... music_llama)`
2. 封装 `llama_model_load` / `llama_decode` 为 C API，经 `media_cli` 暴露给 Python
3. 演讲链路已接 Vosk + analyze-speech；游戏高光已接 PySceneDetect + `game_semantic`（运动/闪光/HUD + 可选 `game_event.onnx`）

构建选项见 [media_engine.md](media_engine.md) §2。

### 2.3 接入 PyTorch / 视觉模型

游戏「击杀/高光事件」：`game_semantic` 已叠 HUD；有 `models/game_event.onnx` 时走 ORT。可用 `scripts/make_game_event_stub_onnx.py` 生成占位模型。

### 2.4 GPU 加速

已完成：播放器 D3D11VA、`VideoDecoder`/`iterate --hw`、个人中心开关、ONNX CUDA EP、llama `n_gpu_layers` 随 `use_gpu`（`MUSIC_LLM_N_GPU_LAYERS`）。

**构建：** 推荐 `python scripts\setup_llama_gpu.py vulkan`（Vulkan SDK，免 CUDA Toolkit）。有 Toolkit 时可用 `cuda`。无 GPU 后端时仍用 prebuilt CPU。

详见 [media_engine.md](media_engine.md) §2 与 `third_party/llama.cpp.README.md`。

**播放路径优化（已落地）：** 双缓冲 SHM + 预取 + Seek 异步首帧；音画软校正。详见 [player_decode_flow.md](player_decode_flow.md)。

**吞吐（已落地）：** OpenCV 超分 JPEG+多线程；AI 超分 ctypes 常驻 Session + 自动 tile；CUDA EP 缺失时进度/顶栏明示；全流程队列有限并行 + 失败重试 + 磁盘预警 + 分阶段 ETA。

**llama GPU：** 推荐 Vulkan（`setup_llama_gpu.py`），不必下载巨型 CUDA Toolkit。

