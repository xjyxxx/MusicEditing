# AI 本地音视频处理工具 (MusicEditing)

纯本地离线音视频处理工具，C++ FFmpeg 底层 + Python PySide6 客户端 UI，MVVM 架构。

## 功能模块

- **智能高光切片**：长视频自动识别精彩片段
- **画质增强 / 4K 超分**：1080P 升级 4K（预留 AI 模型接口）
- **一键去水印**：多区域水印去除（预留）
- **个人中心**：授权管理（预留）

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

### 2.1 下载模型（智能分析必需）

**Vosk 语音识别**（必需）：
- 下载 [vosk-model-small-cn-0.22](https://alphacephei.com/vosk/models)
- 解压到 `models/vosk-model-small-cn-0.22/`

**LLM 语义分析**（可选，留空则用规则打分）：
- 准备任意 `.gguf` 小模型，在 `client/resources/config/app.conf` 设置 `llm_model_path=`

### 3. 运行与测试

```bat
run_ui.bat          rem Win32
run_ui_x64.bat      rem x64
run_test.bat
run_test_x64.bat
```

> PowerShell 中运行 bat 需加 `.\` 前缀，例如 `.\build.bat` 而不是 `build.bat`。

## 项目结构

```
MusicEditing/
├── CMakeLists.txt          # 顶层 CMake
├── CMakePresets.json       # VS2022 构建预设
├── build.bat / build_x64.bat   # Win32 / x64 构建
├── third_party/ffmpeg/         # FFmpeg（x86/ 与 x64/ 分架构）
```

## 架构说明

采用 **MVVM** 双向绑定模式：

| 层 | 技术 | 职责 |
|---|---|---|
| Model | Python dataclass | 视频信息、任务队列、参数 |
| ViewModel | PySide6 QObject + Signal/Property | 业务逻辑、状态绑定 |
| View | PySide6 Widgets | 界面展示、用户交互 |
| 底层引擎 | C++ media_engine.dll | FFmpeg 解码、帧遍历 |

Python 通过 `ctypes` 调用 `media_engine.dll` 的 C API，无需额外绑定库。

## 版权与许可证

- **本项目原创代码**：Copyright (c) 2026 [xjyxxx](https://github.com/xjyxxx)，**保留所有权利**（见 [LICENSE](LICENSE)）。
- **禁止**未经授权的复制、修改、分发、商业使用或创建衍生作品。
- **第三方依赖**见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)（FFmpeg / OpenCV / llama.cpp 等沿用各自开源协议）。

## 开发说明

- C++ 使用 FFmpeg 2.x/3.x 旧版 API（与提供的 .lib 版本匹配）
- AI 推理模块（PyTorch/CUDA）接口已预留，当前切片分析为帧遍历 + 模拟片段
- 后续可在 `client/src/core/` 扩展 GPU 加速和 AI 模型调用
