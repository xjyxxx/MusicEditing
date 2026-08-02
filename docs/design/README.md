# 设计 / 技术文档索引

本目录存放 **MusicEditing 实现级**说明。改代码时请同步更新对应文档（规范见仓库 `.cursor/skills/music-editing-feature-docs/`）。

## 必读

| 文档 | 说明 |
|------|------|
| [**implementation_flow.md**](implementation_flow.md) | **主技术文档**：架构、构建、MVVM、引擎 CLI、各业务链路、状态表、命令速查 |
| [player_decode_flow.md](player_decode_flow.md) | 首页播放器调用链（OPEN/NEXT/SEEK、FFmpeg、音画双通道） |
| [../流程图/README.md](../流程图/README.md) | 播放器相关流程图说明 |

## 产品对照（只读）

仓库根目录：

- `AI本地音视频处理工具-产品交互设计文档（开发落地版）.md`

实现以 `implementation_flow.md` 为准；产品文档仅作交互需求对照。

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

1. `implementation_flow.md` §1–§2（架构与构建）  
2. §3（UI / MVVM）→ §5（要做的功能链路）  
3. 需要改引擎时再读 §4（VideoDecoder / CLI）  
4. 查进度用 §7；跑命令用 §10  
