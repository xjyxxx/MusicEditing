# S04 — C++ 引擎与 CLI 协议

**时长**：90–120 分钟 · **模块**：B 架构

## 本期目标

说清 DLL / CLI / Player 分工；能读懂一条 CLI stdout 协议；理解 ctypes 优先、失败回退。

## 硬核点

| 产物 | 职责 |
|------|------|
| media_engine.dll | probe / iterate / thumbnail / 超分·去水印 C API |
| media_cli.exe | 批处理入口，stdout=协议，stderr=日志 |
| media_player.exe | 首页播放子进程 |

- MediaBridge：短调用 ctypes → 失败 CLI  
- 导出常捆绑 ffmpeg（remux `-c copy` 优先）  

## Lab

命令行跑一次 probe 或 thumbnail（按 `media_engine.md` 示例），把 stdout 贴到作业。

## 对照阅读

- `media_engine.md` · `media_bridge.py` 头部注释
