# 设计 / 技术文档索引

本目录存放 **MusicEditing 实现级**说明。改代码时请同步更新对应专文（规范见仓库 `.cursor/skills/music-editing-feature-docs/`）。

总入口：[docs/README.md](../README.md)

## 文档地图

| 文档 | 说明 |
|------|------|
| [**implementation_flow.md**](implementation_flow.md) | **枢纽**：架构、构建、状态表、命令速查 |
| [mvvm_and_ui.md](mvvm_and_ui.md) | MVVM、页面导航、滤镜、GPU、去水印/超分 UI |
| [media_engine.md](media_engine.md) | VideoDecoder、C API、CLI、llama.cpp |
| [feature_flows.md](feature_flows.md) | 各业务端到端链路（UI → 引擎） |
| [deps_and_extending.md](deps_and_extending.md) | 模块依赖树、扩展与路线图 |
| [player_decode_flow.md](player_decode_flow.md) | 首页播放器调用链（OPEN/NEXT/SEEK、音画双通道） |
| [release_checklist.md](release_checklist.md) | 发版前短测 / 冒烟清单 |
| [流程图/README.md](../流程图/README.md) | 播放器分层 mermaid 总览 |

## 产品对照（只读）

仓库根目录：

- `AI本地音视频处理工具-产品交互设计文档（开发落地版）.md`

实现以枢纽 + 各专文为准；产品文档仅作交互需求对照。

## 第三方说明（分目录 README）

| 路径 | 内容 |
|------|------|
| `third_party/ffmpeg/README.md` | FFmpeg x86 / x64 |
| `third_party/opencv/README.md` | OpenCV 导入 |
| `third_party/onnxruntime/README.md` | ONNX Runtime |
| `third_party/opengl/README.md` | GLEW |
| `third_party/yt-dlp/README.md` | yt-dlp |
| `third_party/exiftool/README.md` | ExifTool |
| `models/README.md` | 模型放置 |

## 推荐阅读顺序

1. [implementation_flow.md](implementation_flow.md) §1–§2（架构与构建）
2. 按任务读专文：功能 → `feature_flows`；UI → `mvvm_and_ui`；引擎 → `media_engine`
3. 播放器细节 → `player_decode_flow` + 流程图
4. 查进度用枢纽 §3；跑命令用枢纽 §4
