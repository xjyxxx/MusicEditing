# S05 — 播放器硬核：IPC / SHM / Seek

**时长**：90–120 分钟 · **模块**：B 架构

## 本期目标

口述「点播放 → 一帧上屏」路径；解释为何 Seek 要异步 + lookahead；SHM 双缓冲解决什么。

## 硬核点

- VideoPlayerWidget → PlayerBackend → stdin/stdout → media_player  
- 视频 RGB 帧：共享内存双缓冲；音频：Qt 侧  
- Seek：异步首帧、抑制软校正、预热预取  
- OpenGL 显示 / 可选 D3D11VA 硬解回退  

## Lab

对照 `docs/流程图/README.md` + `player_decode_flow.md`，画一帧数据流（允许手绘拍照）。

## 对照阅读

- `player_decode_flow.md` · `video_player.py` · `player_backend.py`
