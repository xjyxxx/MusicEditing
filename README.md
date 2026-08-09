# AI 本地音视频处理工具 (MusicEditing)

纯本地离线音视频处理工具，C++ FFmpeg 底层 + Python PySide6 客户端 UI，MVVM 架构。

## 功能模块

- **智能高光切片**：演讲金句（Vosk/规则）/ 手动切片；**缩略图时间轴**
- **画质增强**：Real-ESRGAN / OpenCV 超分；**FFmpeg 视频补帧**（快速 blend / 精细 MCI）
- **一键去水印**：视频快速(OpenCV) / 图片精修(LaMa)；帧批复用
- **链接下载 / 热评滚动** 等（详见技术文档）
- **个人中心**：授权管理（本地卡密）

## 技术文档

- **学习路径（推荐先读）**：[docs/LEARNING.md](docs/LEARNING.md)
- **对外硬核课（多期 PPT）**：[docs/course/README.md](docs/course/README.md)
- **总索引**：[docs/README.md](docs/README.md)
- 枢纽（架构 / 状态 / 命令）：[docs/design/implementation_flow.md](docs/design/implementation_flow.md)
- 业务链路：[docs/design/feature_flows.md](docs/design/feature_flows.md)

## 环境要求

- Windows 10/11
- Visual Studio 2022/2026（含 C++ 桌面开发）
- CMake 3.20+
- Python 3.10+
- PySide6

## 构建架构（Win32 / x64 双预设）

| 架构 | FFmpeg 目录 | OpenCV | 构建 | 运行 |
|------|-------------|--------|------|------|
| **Win32** | `third_party/ffmpeg/x86/` | `third_party/opencv/x86/`（`scripts\import_opencv.bat x86`） | `build.bat` | `run_ui.bat` |
| **x64** | `third_party/ffmpeg/x64/`（脚本下载） | `third_party/opencv/x64/`（`scripts\import_opencv.bat x64`） | `build_x64.bat` | `run_ui_x64.bat` |

输出目录：`build/`（Win32）、`build_x64/`（x64），互不覆盖。

CMake Presets 见 `CMakePresets.json`：`windows-win32-release` / `windows-x64-release`。

### FFmpeg

**Win32** — 已包含在 `third_party/ffmpeg/x86/`。

**x64** — 首次构建前安装：

```bat
scripts\setup_ffmpeg_x64.bat
```

下载 BtbN **FFmpeg 4.4 win64 lgpl-shared** 到 `third_party/ffmpeg/x64/`。详见 [third_party/ffmpeg/README.md](third_party/ffmpeg/README.md)。

## OpenCV（可选，帧增强）

| 架构 | 本地目录 | 首次导入 |
|------|----------|----------|
| x64 | `third_party/opencv/x64/` | `scripts\import_opencv.bat x64`（`build_x64.bat` 会自动尝试） |
| Win32 | `third_party/opencv/x86/` | 先 `scripts\build_opencv_win32.bat`，再 `scripts\import_opencv.bat x86` |

链接用 `opencv_world4120.lib`，运行需 `opencv_world4120.dll`（构建时会复制到 exe 目录）。

配置：`client/resources/config/app.conf` → `opencv_filter=clahe`

## 快速开始

### Win32（当前默认，无需额外下载 FFmpeg）

```bat
build.bat
run_ui.bat
```

### x64（推荐：OpenCV 预编译 + 后续 AI 扩展）

```bat
scripts\setup_ffmpeg_x64.bat
build_x64.bat
run_ui_x64.bat
```

```bat
pip install -r client\scripts\requirements.txt
```

### 下载模型（智能分析必需）

**Vosk 语音识别**（必需）：
- 下载 [vosk-model-small-cn-0.22](https://alphacephei.com/vosk/models)
- 解压到 `models/vosk-model-small-cn-0.22/`
- 或运行 `scripts\download_vosk_model.bat`

**LLM 语义分析**（可选，留空则用规则打分）：
- 准备任意 `.gguf` 小模型，在 `client/resources/config/app.conf` 设置 `llm_model_path=`

### 运行与测试

```bat
run_ui.bat          rem Win32
run_ui_x64.bat      rem x64
run_test.bat
run_test_x64.bat
```

> PowerShell 中运行 bat 需加 `.\` 前缀，例如 `.\build.bat` 而不是 `build.bat`。

## 发版给别人用

```powershell
.\scripts\release_oneclick.bat
# 或: python scripts\release_oneclick.py --profile standard
```

详见 [docs/design/distribution.md](docs/design/distribution.md)（便携包 / Inno / 签名 / 卡密 / 更新检查）。

## 项目结构

```
MusicEditing/
├── CMakeLists.txt / CMakePresets.json
├── build.bat / build_x64.bat / run_ui.bat / run_ui_x64.bat
├── client/                 # C++ 引擎 + Python UI
│   ├── src/ include/       # media_engine / media_cli / media_player
│   └── scripts/            # PySide6：models / viewmodels / ui / core
├── shared/                 # 公共 C++（日志、FFmpeg 兼容、硬解）
├── docs/                   # 文档（见 docs/README.md）
│   └── design/             # 实现枢纽与专文
├── models/                 # 本地模型（不进 git）
├── scripts/                # 下载/导入第三方与模型
└── third_party/            # FFmpeg / OpenCV / ONNX / llama…
```

## 架构说明

采用 **MVVM**；Python（64-bit）经 **MediaBridge / PlayerBackend** 调用 C++：`probe`/`thumbnail` 优先 ctypes 直连 `media_engine.dll`，播放用 `media_player` 子进程。详见 [docs/design/implementation_flow.md](docs/design/implementation_flow.md) §1。

| 层 | 技术 | 职责 |
|---|---|---|
| Model | Python dataclass | 视频信息、任务队列、参数 |
| ViewModel | PySide6 QObject + Signal/Property | 业务逻辑、状态绑定 |
| View | PySide6 Widgets | 界面展示、用户交互 |
| 底层引擎 | C++ media_engine / media_cli / media_player | 解码、缩略图、超分/去水印、播放 |

## 版权与许可证

- **本项目原创代码**：Copyright (c) 2026 [xjyxxx](https://github.com/xjyxxx)，**保留所有权利**（见 [LICENSE](LICENSE)）。
- **禁止**未经授权的复制、修改、分发、商业使用或创建衍生作品。
- **第三方依赖**见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)（FFmpeg / OpenCV / llama.cpp 等沿用各自开源协议）。

## 开发说明

- 功能变更请同步更新 `docs/design/` 对应专文与枢纽状态表（见 `.cursor/skills/music-editing-feature-docs/`）
- x64 为推荐开发/运行路径
- 播放器细节见 `docs/design/player_decode_flow.md`
