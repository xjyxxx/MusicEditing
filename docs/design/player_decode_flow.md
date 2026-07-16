# 播放器解码流程（学习文档）

> 对应代码：`media_player.exe`、`PlayerBackend`、`VideoPlayerWidget`、`QtAudioOutput`  
> 架构图：`docs/流程图/README.md`

---

## 1. 总体思路

本项目播放器采用 **「视频 C++ 解码 + 音频 Qt 播放」** 双通道：

| 通道 | 谁解码 | 数据放哪 | 谁显示/出声 |
|------|--------|----------|-------------|
| **视频** | FFmpeg（`media_player.exe`） | 临时 RGB 文件 → Python 内存 | `QLabel` + `QImage` |
| **音频** | Qt Multimedia（系统后端） | 不落地，系统直接读原文件 | `QMediaPlayer` + `QAudioOutput` |

**为什么不把音视频都在 C++ 解？**  
64 位 Python UI 与 32 位 FFmpeg 库位数不同，视频通过子进程 IPC 拉帧；音频用 Qt 走系统解码更稳定。

---

## 2. 视频解码全流程

```
用户打开 test.mp4
    │
    ▼
VideoPlayerWidget.open_file(path)
    │
    ├─► PlayerBackend.open(path)
    │       └─► 重启 media_player.exe 子进程
    │       └─► stdin: OPEN E:\...\test.mp4
    │       └─► stdout: OPEN_OK duration=210.7 fps=25 width=1280 height=720 audio=1
    │
    ▼
media_player.exe (C++)
    │
    ├─ pathUtf8ToNative()     # UTF-8 → Windows GBK 路径
    ├─ avformat_open_input()  # 解封装（读容器 mp4/mkv）
    ├─ avformat_find_stream_info()
    ├─ 找视频流 + 探测是否有音频流
    ├─ avcodec_open2()        # 打开 H264/HEVC 解码器
    └─ sws_getContext()       # 像素格式 → RGB24 转换器

播放循环（QTimer 按 fps 触发）:
    │
    ▼
PlayerBackend.next_frame()
    └─► stdin: NEXT C:\Users\...\Temp\me_player_xxx\frame.rgb
    │
    ▼
VideoPlayerEngine.decodeNextFrameToFile()
    ├─ av_read_frame()        # 读一个 AVPacket
    ├─ avcodec_decode_video2()# 解码成 YUV 帧
    ├─ sws_scale()            # YUV → RGB24
    ├─ FrameProcessor         # OpenCV 预留（当前直通）
    └─ fwrite → frame.rgb     # 写入临时文件

    stdout: FRAME_OK timestamp=0.04 width=1280 height=720 path=...

    │
    ▼
Python 读取 frame.rgb → bytes
    │
    ▼
RGB24 → GlVideoWidget（QOpenGL 纹理 + 着色器）显示
```

### 2.1 解码后的视频存在哪？

| 阶段 | 位置 | 格式 | 生命周期 |
|------|------|------|----------|
| FFmpeg 内部 | C++ 堆内存 | YUV（解码后） | 单帧，立刻 swscale |
| 转换后 | C++ 栈/vector | RGB24 原始字节 | 写文件后释放 |
| IPC 传输 | `%TEMP%\me_player_*\frame.rgb` | 裸 RGB24，大小 = `宽×高×3` | 每帧覆盖写，进程退出删除 temp 目录 |
| UI 显示 | Python `QImage` / `QPixmap` | Qt 图像对象 | 下一帧覆盖 |

**不落盘成 mp4/avi**——只有一帧临时 `.rgb` 文件用于跨进程传数据（后续可改为共享内存优化）。

### 2.2 关键代码位置

- 解封装/解码：`client/src/core/video_player_engine.cpp`
- IPC 入口：`client/src/player_main.cpp`
- Python 拉帧：`client/scripts/core/player_backend.py`
- UI 显示：`client/scripts/ui/video_player.py` → `_pull_and_show_frame()`

---

## 3. 音频流程

```
open_file(path) 且 has_audio=1
    │
    ▼
QtAudioOutput.open(path)
    └─ QMediaPlayer.setSource(QUrl.fromLocalFile(path))
       （Qt 内部：系统解码器读 mp4 里的 AAC，直接输出到声卡）

play()
    ├─ PlayerBackend.resume()     # 仅恢复视频解码状态
    └─ QtAudioOutput.play(position_sec)
           └─ setPosition(ms) + play()
```

### 3.1 解码后的音频存在哪？

| 阶段 | 位置 | 说明 |
|------|------|------|
| 源文件 | 磁盘 `test.mp4` | Qt 直接从容器读音频轨 |
| 解码 | Qt Multimedia 内部缓冲 | PCM，用户不可见 |
| 输出 | 系统音频设备 | 扬声器/耳机 |

**Python/C++ 侧不保存 WAV/PCM 文件**；与 `media_cli extract-audio`（导出 WAV 给 ASR）是不同链路。

---

## 4. 音视频同步策略

当前为 **「Seek 同步 + 独立时钟」**（MVP，非毫秒级精确）：

```
                    ┌─────────────────┐
                    │  _position_sec  │  ← 视频帧 PTS 更新
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
    播放开始            拖动进度条            停止
         │                   │                   │
  video: RESUME         video: SEEK t         seek(0)
  audio: play(t)        audio: seek(t)        stop()
         │                   │                   │
         └───────────────────┴───────────────────┘
                    两者跳到同一时间点
```

| 操作 | 视频 | 音频 |
|------|------|------|
| 播放 | `QTimer` 按 fps 调 `NEXT` 拉帧 | `QMediaPlayer.play()` |
| 暂停 | 停 Timer + `PAUSE` | `pause()` |
| Seek | `SEEK t` + 拉一帧 | `setPosition(t*1000)` |
| 进度显示 | 帧 `timestamp` 更新进度条 | 不单独读音频 PTS |

**局限：**

- 视频按帧 PTS 走，音频按 Qt 内部时钟走，长时间播放可能轻微漂移
- 未做音频主时钟校正（后续可用 `QMediaPlayer.position()` 驱动视频 seek）

**改进方向（待实现）：**

1. 以音频 `position()` 为主时钟，视频落后则跳帧/seek  
2. 或音视频都在 C++ 解，统一 PTS 后输出（SDL/miniaudio）

---

## 5. 进程与资源生命周期

```
应用启动
  └─ PlayerBackend（尚未 spawn media_player）
  └─ QtAudioOutput（空 QMediaPlayer）

打开视频
  └─ _restart() → 新 media_player.exe 进程
  └─ Qt 加载音频源

关闭窗口 / 退出应用  ← 必须全部释放
  ├─ QTimer.stop()
  ├─ QtAudioOutput.shutdown()  → stop + 清空 source
  ├─ PlayerBackend.shutdown()  → kill media_player.exe
  └─ QApplication.quit()
```

---

## 6. IPC 命令速查（media_player.exe）

| 命令 | 作用 |
|------|------|
| `OPEN <path>` | 打开视频，探测宽高/fps/是否有音频轨 |
| `NEXT <rgb路径>` | 解码下一帧，写入 RGB 文件 |
| `SEEK <秒>` | 跳转（`av_seek_frame` + flush） |
| `PAUSE` / `RESUME` | 视频解码暂停标志 |
| `CLOSE` / `QUIT` | 关闭并退出进程 |

日志在 stderr；协议在 stdout（一行一条）。

---

## 7. 与「智能切片」解码的区别

| 场景 | 程序 | 输出 |
|------|------|------|
| 首页预览 | `media_player.exe` | 临时 RGB 帧 → 屏幕 |
| 批量分析 | `media_cli iterate` | 逐帧回调/计数，不写屏 |
| 演讲 ASR | `media_cli extract-audio` | 16kHz WAV 文件 |

同一套 FFmpeg 库，不同业务命令。

---

## 8. 相关文件索引

```
client/
├── src/player_main.cpp              # 播放器 IPC 主程序
├── src/core/video_player_engine.cpp # 视频 Stateful 解码
├── src/core/frame_processor.cpp     # OpenCV 预留
├── scripts/core/player_backend.py   # Python ↔ media_player
├── scripts/core/qt_audio_output.py  # Qt 音频
└── scripts/ui/video_player.py       # UI 控件 + 同步逻辑
```
