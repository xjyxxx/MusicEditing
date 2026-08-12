# MusicEditing — 实现说明（枢纽）

> **定位**：描述仓库**当前代码**的实现链路（非产品愿景稿）。  
> **学习路径（分阶段）**：[docs/LEARNING.md](../LEARNING.md)  
> **产品对照**：[AI本地音视频处理工具-产品交互设计文档（开发落地版）.md](../../AI本地音视频处理工具-产品交互设计文档（开发落地版）.md)  
> **文档总索引**：[docs/README.md](../README.md)  
> **维护规则**：改功能时同步更新本文状态表 + 对应专文（见 `.cursor/skills/music-editing-feature-docs/`）。

---

## 目录与专文

| 文档 | 内容 |
|------|------|
| [LEARNING.md](../LEARNING.md) | **学习路径**（分阶段：跑通 → 功能地图 → 架构 → 开发/发版） |
| **本文** | 总体架构、构建启动、状态表、命令速查 |
| [mvvm_and_ui.md](mvvm_and_ui.md) | Model / VM / View、滤镜、GPU、去水印/超分 UI 侧 |
| [photo_manager.md](photo_manager.md) | 照片图库：Folder-native、索引、非破坏编辑 |
| [media_engine.md](media_engine.md) | VideoDecoder、C API、CLI、llama.cpp |
| [feature_flows.md](feature_flows.md) | 各业务端到端链路 |
| [deps_and_extending.md](deps_and_extending.md) | 模块依赖树、扩展与路线图 |
| [player_decode_flow.md](player_decode_flow.md) | 首页播放器解码 / IPC |
| [release_checklist.md](release_checklist.md) | 发版前短测 / 冒烟 |
| [distribution.md](distribution.md) | 便携验收、签名、Inno、卡密服务 |
| [流程图/README.md](../流程图/README.md) | 播放器 + **照片图库** mermaid 总览 |

**推荐阅读：** 外人按阶段学请先读 [docs/LEARNING.md](../LEARNING.md)；专文速查：§1–§2 → 按任务读专文 → 查进度用 §3 → 跑命令用 §4。

---

## 1. 总体架构

**C++ 媒体引擎 + Python/PySide6 UI**；Python 经 **MediaBridge / PlayerBackend** 调用引擎：短调用（`probe` / `thumbnail`）优先 **ctypes 直连 `media_engine.dll`**，失败回退 `media_cli.exe`；播放仍用 `media_player.exe`；批处理导出用捆绑 `ffmpeg.exe`（stdout=协议，stderr=日志）。

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
  ├─ 后台线程：IP 定位城市 + Open-Meteo → 状态栏天气（[feature_flows.md](feature_flows.md) §5.11）
  ├─ 无 NVIDIA GPU 时弹窗提示 CPU 模式（见 [mvvm_and_ui.md](mvvm_and_ui.md) §3.6）
  └─ 显示功能页（首页/切片/增强/去水印/下载与热评等），进入事件循环
```

**退出（关闭窗口）：**
```
MainWindow.shutdown()
  ├─ VideoPlayerWidget.shutdown() → Qt 音频 stop
  └─ PlayerBackend.shutdown()    → kill media_player.exe
```

详见 [player_decode_flow.md](player_decode_flow.md)。

---

## 3. 已实现 vs 待实现

状态真源。表中「§5.x」见 [feature_flows.md](feature_flows.md)；「§3.x」见 [mvvm_and_ui.md](mvvm_and_ui.md)。

### 引擎与桥接

| 功能 | 状态 | 说明 |
|------|------|------|
| FFmpeg 视频打开/探测 | ✅ | VideoDecoder + probe |
| 视频帧遍历 | ✅ | iterateFrames + CLI |
| 缩略图提取 | ✅ | ctypes/`media_cli` thumbnail + 磁盘小图缓存 |
| MediaBridge ctypes | ✅ | `probe`/`thumbnail` 直连 `media_engine.dll`；失败回退 CLI；mtime 缓存 |
| 导出 remux 优先 | ✅ | 高光分段/拼接 `-c copy`；按参数整段一次重编码；AAC 分档 + faststart |
| OpenCV 帧处理 | ✅ | `FrameProcessor`：CPU + **OpenCL UMat**；标题 `OpenCV:clahe/opencl` |
| GLEW / OpenGL 第三方 | ✅ | `third_party/opengl`；`media_player` 链 GLEW |
| OpenGL 视频显示 | ✅ | `GlVideoWidget` 替换 QLabel；首页播放器 |
| FFmpeg GPU 硬解（D3D11VA） | ✅ | 播放器 + `VideoDecoder`/`iterate --hw`；失败回退 CPU |
| llama.cpp 第三方集成 | ✅ | third_party/llama.cpp，CMake 目标 `music_llama` |
| llama 本地推理业务 | ✅ | analyze-speech 已接入智能切片 |

### 播放器与首页

| 功能 | 状态 | 说明 |
|------|------|------|
| PySide6 菜单导航 UI | ✅ | MenuBar + QStackedWidget；核心/工作流/趣味/帮助分组（§3.3） |
| Studio 视觉主题 | ✅ | `ui/theme.py` macOS 浅色（暖白+系统蓝）；正文深色；白字仅用于强调按钮；§3.3.1 |
| 首页本地播放器 | ✅ | FFmpeg 视频 + Qt 音乐；OpenGL；**SHM 传帧** + 预取；音画软校正 |
| 媒体信息面板 | ✅ | 「信息」→ ffprobe 封装/编码/分辨率/码率（`MediaInfoDialog`，VideoEye 精简） |
| 波形/响度可视化 | ✅ | showwavespic + ebur128；播放器下方可点击 seek（§5.12） |
| MVVM 双向绑定 | ✅ | Signal/Slot |
| GPU 检测与状态栏 | ✅ | `nvidia-smi`；顶栏 `GPU: 型号` / `CPU 模式`（§3.6） |
| 状态栏天气 | ✅ | IP 定位 + Open-Meteo；今日氛围用电影向滤镜（暖阳/雨幕/雪色/雷霓…）（§5.11） |
| AI 运行状态提示 | ✅ | 增强/去水印页显示 GPU 推理与模型是否就绪；缺模型指向 download_*.bat |
| 长路径 UI | ✅ | `ElidedPathLabel`：增强/去水印/封面/BGM/音频趣味等路径行中间省略 |
| 帧共享内存 / 预取 | ✅ | 双缓冲 SHM + 预取；Seek **异步**首帧 + lookahead 预热 |



### 切片与导出

| 功能 | 状态 | 说明 |
|------|------|------|
| 高光时间轴（缩略图） | ✅ | `HighlightTimelineWidget` 色块+胶片条；列表带图标；见 §5.1.1 |
| 三大功能串联 | ✅ | `open_with_video` + 完成弹窗/「送去」；批量全流程队列见下 |
| 批量全流程队列 | ✅ | 有限并行；失败重试；磁盘预警；分阶段 ETA；超分默认试跑 8s |

| 切片/导入异步 | ✅ | `import_video` / `start_slice_analysis` 后台线程；UI 收 Signal |
| 手动切片 | ✅ | SlicePage 起止时间添加/删除/清空；不依赖 Vosk |
| 响度高潮切片 | ✅ | 场景「响度高潮」；ebur128 峰值成段（§5.12） |
| AI 高光识别（演讲/解说） | ✅ | 演讲金句：Vosk+LLM/金句词；无人声模型时人声段兜底 |
| AI 高光识别（游戏） | ✅ | 切点 + 运动/闪光 + HUD；可选 `game_event.onnx`（§5.2） |
| 批量导出剪辑 | ✅ | `一键高光成片` + 可选规范命名（§5.5） |
| 竖屏短视频导出 | ✅ | 切片成片→9:16；固定锚点 + **智能跟脸** `track_mode=face`（§5.5） |
| 发布预设 / 规范命名 | ✅ | 抖音/B站/快手竖屏 + `export_naming` / 封面话题（§5.5） |
| 成片模板一键竖屏 | ✅ | 抖音/B站/快手模板：时长上限+竖屏+封面话题；队列可选（§5.5/§5.9） |
| 静音剪掉 | ✅ | `静音剪掉` → silencedetect + 拼接紧凑口播 |
| 导出参数面板 | ✅ | 模板·预设·分辨率·质量·规范命名·封面话题（`ExportOptionsDialog`） |

### 画质与水印

| 功能 | 状态 | 说明 |
|------|------|------|
| 视频补帧 | ✅ | FFmpeg minterpolate（快速/精细）+ 可选 RIFE ONNX；默认试 15 秒（§5.10/§5.21） |
| 去水印批量重试 | ✅ | 失败重试 1–2 次；结果列表；抖音/快手角标预设（§5.18） |
| CUDA EP 自检 / tile / RIFE | ✅ | 提示回退 CPU；超分 tile；可选 RIFE 回退 minterpolate（§5.21） |
| 溯源水印 | ✅ | 频域封面 + 回声音频 + LSB + EXIF；封面导出可勾选（§5.22） |
| OpenCV 趣味滤镜 | ✅ | film / warm / cool / vintage / neon / comic / pixel；播放器下拉 |
| LUT 一键调色 | ✅ | 增强页 Tab + lut3d 导出；与 FrameProcessor 同预设（§5.13） |
| OpenCV GPU 滤镜 | ✅ | OpenCL `cv::UMat`（`opencv_filter_device=auto`）；失败回退 CPU |
| 图片 EXIF | ✅ | 图片右上角悬浮摘要 +「全部」弹窗；`exif_panel.py`（§5.7） |
| 4K 超分 | ✅ | AI：ctypes 常驻 + 自动 tile≈512；CUDA EP 缺失明示；OpenCV JPEG+多线程 |

| 去水印 | ✅ | `WatermarkPage` 快速/精修；智能建议角标；图片文件夹/多视频批量；帧批复用 |
| 水印智能建议/批量 | ✅ | 四角启发式 + 抖音/快手预设；批量重试与结果列表（§5.18） |

### 下载与热评

| 功能 | 状态 | 说明 |
|------|------|------|
| 网易云热评滚动 | ✅ | 三合一；B 站弹幕；首页速度/密度/区域（§5.2.1） |
| 链接下载 | ✅ | Cookie；B 站音画合并；失败白话+换 Cookie/重试（§5.6） |
| 热评导出 / 短视频成片 | ✅ | JSON+ASS+竖屏；失败可恢复提示（§5.2.1/§5.6） |
| 热评弹幕/卡片成片 | ✅ | `danmaku` / `cards` / `ass_caption` 三种 ASS 风格（§5.2.1） |

### 趣味音频与素材

| 功能 | 状态 | 说明 |
|------|------|------|
| 封面/缩略图工厂 | ✅ | 最清晰帧 + 大字标题 PNG；`CoverPage`（§5.14） |
| 音频趣味页 | ✅ | 整轨趣味 + **梗音叠加**（时刻/倍数/音量；user 自备热梗）（§5.15） |
| BGM 混音 | ✅ | FFmpeg 叠/替换/压低原声；`BgmPage`（§5.16） |
| Demucs 人声分离 | ✅ 可选 | `third_party/demucs` + `setup_demucs.bat`；未装不影响混音 |
| 本地素材库 | ✅ | 目录索引；送首页/切片/队列（§5.19） |
| **照片图库** | ✅ | 主路径：嵌入 `third_party/iphoto`（iPhotron）；地点无 GPS 空状态；宿主栏选中→播放/增强/去水印；降级：`PhotoLibraryPage`；播放回调本仓播放器（§5.24 · [photo_manager.md](photo_manager.md)） |
| 差异化能力入口 | ✅ | 菜单导航：热评 / 切片演讲成片 / 全流程队列（§5.20；首页无流水线卡片） |

### 系统与授权

| 功能 | 状态 | 说明 |
|------|------|------|
| 回归短测 | ✅ | SHM/Seek、超分、队列、竖屏、Cookie、试用、激活、打包、**地点叠层 smoke** |
| 发版 checklist | ✅ | [release_checklist.md](release_checklist.md) · [distribution.md](distribution.md) |
| 便携打包 | ✅ | `--profile` + 验收 + 可选 `--sign`；`accept_portable.py` |
| Inno 安装包 | ✅ | `scripts/build_installer.bat` + `scripts/inno/MusicEditing.iss` |
| 一键发版 | ✅ | `release_oneclick.py`：回归→pack→accept→Inno→清单 |
| 自动更新检查 | ✅ | `update_check.py`；`publish_update_manifest` / `serve_update_channel`；启动静默检查；帮助/个人中心 |
| 卡密激活服务 | ✅ | `scripts/license_server/`（签发 + POST /v1/activate + 演示购买页） |
| llama.cpp GPU 推理 | ✅ | 推荐 Vulkan（免 Toolkit）；或 CUDA；`MUSIC_LLM_N_GPU_LAYERS`；`setup_llama_gpu.py` |
| 开箱依赖向导 | ✅ | 缺啥摘要 + **试跑 15 秒成片**；模型/GPU/Cookie/yt-dlp/场景/LLM（§5.18） |
| 长任务进度 ETA | ✅ | 超分/去水印/补帧/队列线性外推「剩余约…」（§5.18） |
| 诊断日志打包 | ✅ | 个人中心一键 zip：player/cli/ORT EP（§5.23） |
| 临时帧/产物配额 | ✅ | 启动后台清理残留；队列 `max_output_gb`（§5.23） |
| UI 启动流畅 | ✅ | 页懒创建 + **空闲预热**（个人中心/切片/增强/下载）；`media_player` 延迟到开文件 |
| 导出完成体验 | ✅ | 完成后可「打开文件夹」选中成片（`os_util.reveal_in_explorer`） |
| Studio 页一致性 | ✅ | `studio_kit`：Hero/Card/滚动壳；切片/增强/队列 + **下载/素材库/封面/音频趣味**；首页轻量功能地图；音频/BGM/溯源 Tab 滚动 |
| 授权/卡密 | ✅ | 本地卡密 + **试用配额/720p** + 可选联网激活/购买页；收银台在外部站点 |
| 个人中心 | ✅ | 卡密、配额、购买页、GPU、输出目录、开箱向导、诊断打包、清理临时帧（§5.17/§5.23） |

---

## 4. 运行命令速查

```powershell
.\build.bat                    # 编译（含 llama.lib，可用 -DMUSIC_ENABLE_LLAMA=OFF 跳过）
.\build_x64.bat                # x64 编译（自动导入 FFmpeg/OpenCV/ONNX）
.\run_ui_x64.bat               # 一步启动 x64 UI（缺 ONNX 自动导入，缺产物自动编译；requirements 未变则跳过 pip）
# MUSIC_SKIP_PIP=1 可完全跳过 pip；MUSIC_FORCE_PIP=1 强制重装
# 照片完整依赖：pip install -r client/scripts/requirements-iphoto.txt
.\run_test.bat                 # 测试 FFmpeg（默认 Titanic.mkv）
.\run_test.bat "D:\a.mp4"      # 指定视频测试
.\run_ui.bat                   # 启动 UI
.\scripts\download_lama_model.bat          # 去水印精修模型
.\scripts\download_realesrgan_model.bat    # 画质超分模型（~5MB）
.\scripts\download_yt_dlp.bat              # 链接下载引擎 yt-dlp.exe → third_party/yt-dlp/
.\scripts\download_exiftool.bat            # 图片 EXIF：exiftool.exe + exiftool_files → third_party/exiftool/
.\scripts\download_vosk_model.bat          # 演讲金句 ASR：vosk-model-small-cn-0.22 → models/
.\scripts\install_scenedetect.bat          # 游戏高光：安装 PySceneDetect（scenedetect）
.\scripts\release_oneclick.bat       # 一键发版：回归→pack→accept→Inno→清单
.\scripts\pack_portable.bat          # 打便携包 → dist\（可加 --zip）
python .\scripts\pack_portable.py --zip
python .\scripts\accept_portable.py  # 验收便携包关键文件 + 干净机清单
.\scripts\build_installer.bat        # Inno 安装包（需 Inno Setup 6）
python .\scripts\license_server\gen_keys.py --count 5
python .\scripts\license_server\server.py --port 8765
python .\scripts\setup_llama_gpu.py       # llama GPU：推荐 Vulkan；可选 CUDA
.\scripts\run_regression_short.bat        # 工程质量短测（含地点叠层 smoke）
python .\scripts\smoke_place_map_thumbs.py # 单独跑地点地图缩略图冒烟
python .\scripts\sync_iphoto_vendor.py     # 核对 / 刷新 iPhoto vendor pin
```
