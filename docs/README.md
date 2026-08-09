# MusicEditing 文档索引

本目录为项目**实现级与设计级**文档入口。改功能时请同步更新对应专文（规范见 `.cursor/skills/music-editing-feature-docs/`）。

## 从哪里读起

| 你想… | 打开 |
|-------|------|
| 了解整体架构与构建 | [design/implementation_flow.md](design/implementation_flow.md)（枢纽） |
| 查某功能 UI→引擎链路 | [design/feature_flows.md](design/feature_flows.md) |
| 改 Python MVVM / 页面 | [design/mvvm_and_ui.md](design/mvvm_and_ui.md) |
| 改 C++ 引擎 / CLI | [design/media_engine.md](design/media_engine.md) |
| 改首页播放器解码 | [design/player_decode_flow.md](design/player_decode_flow.md) |
| 看依赖树 / 扩展路线 | [design/deps_and_extending.md](design/deps_and_extending.md) |
| 对照产品交互需求 | 仓库根目录产品交互设计文档（只读） |

完整设计目录说明：[design/README.md](design/README.md)

## 流程图

- [流程图/README.md](流程图/README.md) — 播放器分层 mermaid 总览  
- 详解以 `player_decode_flow.md` 为准

## 第三方与模型

| 路径 | 内容 |
|------|------|
| `third_party/ffmpeg/README.md` | FFmpeg x86 / x64 |
| `third_party/opencv/README.md` | OpenCV 导入 |
| `third_party/onnxruntime/README.md` | ONNX Runtime |
| `third_party/opengl/README.md` | GLEW |
| `third_party/yt-dlp/README.md` | yt-dlp |
| `third_party/exiftool/README.md` | ExifTool |
| `models/README.md` | 模型放置 |

## 归档与本地杂项

- [archive/](archive/) — 历史笔记（非实现真源），见其中说明  
- `docs/log_*.txt`、`*cookies*.txt`：**本地调试产物**，已在 `.gitignore`，请勿提交
