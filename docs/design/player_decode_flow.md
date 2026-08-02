# 首页播放器：解码 / 接口调用链

> 视频：`media_player.exe`（FFmpeg）按帧写出 RGB → Python 上屏  
> 音频：同文件走 Qt `QMediaPlayer`，不经 C++  
> 协议：子进程 **stdin 命令 / stdout 一行响应**；日志走 stderr  

**相关：** [implementation_flow.md](implementation_flow.md) · [../流程图/README.md](../流程图/README.md)

**源码入口：**

```
client/scripts/ui/video_player.py          VideoPlayerWidget
client/scripts/ui/gl_video_widget.py       GlVideoWidget
client/scripts/core/player_backend.py      PlayerBackend（IPC）
client/scripts/core/qt_audio_output.py     QtAudioOutput
client/src/player_main.cpp                 media_player 命令循环
client/src/core/video_player_engine.cpp    VideoPlayerEngine
```

---

## 1. 架构（双通道）

```
test.mp4
    │
    ├─► 视频通道
    │     VideoPlayerWidget
    │       → PlayerBackend  ←stdin/stdout→  media_player.exe
    │                                              └─ VideoPlayerEngine (FFmpeg)
    │       → 读 %TEMP%\me_player_*\frame.rgb
    │       → GlVideoWidget.set_rgb_frame()
    │
    └─► 音频通道（OPEN_OK audio=1 时）
          VideoPlayerWidget
            → QtAudioOutput.open(同一路径)
            → QMediaPlayer → 扬声器
```

`media_cli.exe`（切片 / extract-audio）是另一条程序，不参与首页预览。

---

## 2. 打开 `test.mp4`

```
用户打开 E:\...\test.mp4
    │
    ▼
VideoPlayerWidget.open_file(path)
    └─► _do_open_file(path)                    # 非音频走视频分支
            │
            ├─► PlayerBackend.set_hwaccel(pref)
            │       └─► stdin: HWACCEL on|off
            │       └─► stdout: HWACCEL_OK enabled=0|1
            │
            ├─► PlayerBackend.open(path)
            │       ├─► _restart()             # QUIT 旧进程 → Popen media_player.exe
            │       ├─► stdin: OPEN E:\...\test.mp4
            │       └─► stdout: OPEN_OK duration=… fps=… width=… height=…
            │                     audio=0|1 hw=0|1 hw_name=cpu|d3d11va
            │       └─► 解析 → PlayerInfo
            │
            ├─► [audio=1] QtAudioOutput.open(path)
            ├─► 设 duration / fps / QTimer interval ≈ 1000/fps
            ├─► _pull_and_show_frame()         # 首帧预览（暂停态）
            └─► [auto_play] play()
```

### 2.1 C++：`OPEN` → `VideoPlayerEngine::open`

```
media_player.exe  (player_main.cpp)
    │  stdin 行: OPEN <utf8-path>
    ▼
VideoPlayerEngine::open(filePath)
    ├─ close()                         # 清旧上下文
    ├─ common::ffmpegInit()
    ├─ common::pathForFfmpeg(path)     # UTF-8 → FFmpeg/本地路径
    ├─ avformat_open_input()           # 解封装 mp4/mkv…
    ├─ avformat_find_stream_info()
    ├─ 扫 streams → hasAudioStream
    ├─ common::openVideoDecoder()      # 找视频流 + avcodec_open2
    │       └─ 可选 D3D11VA（hwAccelPreferred）
    ├─ 填 PlayerInfo: w/h/fps/duration/codec
    └─ sws 延迟到首帧 ensureSwsContext() → sws_getContext(YUV→RGB24)

stdout:
    OPEN_OK duration=210.700000 fps=25.000000 width=1280 height=720
            audio=1 hw=1 hw_name=d3d11va
失败:
    ERROR open_failed
```

---

## 3. 播放一帧：`play` → `NEXT` → 上屏

```
VideoPlayerWidget.play()
    ├─► set_playback_filter / set_playback_scale   # SCALE w h（播放可缩到 ≤640×360）
    ├─► PlayerBackend.resume()
    │       └─ stdin: RESUME  →  RESUME_OK
    ├─► [有音频] QtAudioOutput.play(position_sec)
    └─► _schedule_tick()                           # QTimer.singleShot → _on_tick
            │
            ▼  (有音频：_sync_video_to_audio；无音频：_pull_and_show_frame)
        PlayerBackend.next_frame(min_ts, apply_filter)
            └─► _decode_frame()
                    ├─ stdin: NEXT <frame.rgb> <min_ts> <0|1>
                    ├─ stdout: FRAME_OK timestamp=… width=… height=…
                    │          skipped=… decode_ms=… hw_xfer=… path=…
                    │       或 FRAME_EOF
                    └─► _read_rgb_file(w,h) → bytes
                            │
                            ▼
                    VideoPlayerWidget._show_frame()
                        └─ GlVideoWidget.set_rgb_frame(rgb, w, h)
```

### 3.1 C++：`NEXT` → `decodeNextFrameToFile`

```
player_main: NEXT outPath [minTs] [applyFilter]
    ▼
VideoPlayerEngine::decodeNextFrameToFile(rgbPath, &result, minTs, applyFilter)
    │
    ├─ 循环直到产出一帧或 EOF:
    │     avcodec_receive_frame()
    │       ├─ EAGAIN → av_read_frame() → 非视频流丢弃
    │       │            → avcodec_send_packet()
    │       └─ 得到 AVFrame:
    │             ├─ seek 后可跳过非关键帧 / 未到 seekTarget
    │             ├─ catch-up: ts < minTs → skip（追音频时钟）
    │             ├─ [硬解帧] transferHwFrameToSoftware()
    │             ├─ ensureSwsContext() + sws_scale() → RGB24
    │             ├─ [applyFilter] FrameProcessor.processRgbFrame()  # OpenCV
    │             └─ 原子写: frame.rgb.part → rename → frame.rgb
    │
    └─ stdout FRAME_OK | FRAME_EOF
```

**跨进程帧缓冲：** 始终覆盖同一个 `frame.rgb`（`me_player_*` 临时目录），不是整片拆图。

---

## 4. 暂停 / 停止 / Seek

```
pause()
    ├─ 停 tick
    ├─ SCALE 0 0                 # 恢复全分辨率预览
    ├─ stdin: PAUSE → PAUSE_OK
    └─ QtAudioOutput.pause()

stop()
    ├─ pause()
    ├─ position = 0
    ├─ audio.stop()
    ├─ SEEK 0 + 拉一帧刷新
    └─ …

拖进度条松开 _on_seek_released()
    ├─ position_sec = slider ratio × duration
    ├─ PlayerBackend.seek(sec)
    │       └─ stdin: SEEK <sec>
    │       └─ VideoPlayerEngine::seek
    │             ├─ av_rescale_q(sec → stream time_base)
    │             ├─ av_seek_frame(..., AVSEEK_FLAG_BACKWARD)
    │             └─ flushCodec() + needKeyFrameAfterSeek
    │       └─ stdout: SEEK_OK timestamp=…
    ├─ QtAudioOutput.seek(sec)
    ├─ _pull_and_show_frame()
    └─ [拖前在播] play()
```

---

## 5. 音画对齐（当前实现）

```
有音频播放 tick:
    audio_sec = QtAudioOutput.position_sec()     # 主时钟
    want_idx  = 已显示帧 index + 1（落后太多则跳到 audio_idx 附近）
    next_frame(min_ts = want_idx * frame_interval)
        → C++ 丢弃过旧帧（skipped）再写 RGB
    进度条 / 字幕时间 ≈ audio_sec

无音频:
    纯按 fps timer 连续 NEXT
```

对齐点：`play` / `pause` / `seek` 两端一起动；长播漂移依赖音频追帧，不是工业级锁相。

---

## 6. IPC 一览（`PlayerBackend._send` ↔ `player_main`）

| stdin | stdout（成功） | 引擎调用 |
|-------|----------------|----------|
| `HWACCEL on\|off` | `HWACCEL_OK enabled=` | `setHwAccelPreferred` |
| `OPEN <path>` | `OPEN_OK duration= fps= width= height= audio= hw= hw_name=` | `open` |
| `NEXT <rgb> [minTs] [filter]` | `FRAME_OK …` / `FRAME_EOF` | `decodeNextFrameToFile` |
| `SEEK <sec>` | `SEEK_OK timestamp=` | `seek` |
| `PAUSE` / `RESUME` | `PAUSE_OK` / `RESUME_OK` | `pause` / `resume` |
| `SCALE w h` | `SCALE_OK width= height=` | `setPlaybackScale` |
| `FILTER <mode>` | `FILTER_OK mode= device= active=` | `setFrameFilter` |
| `FILTER_DEVICE auto\|cpu\|opencl` | `FILTER_DEVICE_OK …` | `setFrameFilterDevice` |
| `FILTER_STATUS` | `FILTER_STATUS_OK …` | 读状态 |
| `CLOSE` | `CLOSE_OK` | `close` |
| `QUIT` | `BYE` | 退出进程 |

失败：`ERROR <reason>`。Python 侧封装：`open` / `next_frame` / `seek` / `pause` / `resume` / `shutdown`。

---

## 7. 进程生命周期

```
首次 PlayerBackend.open / _ensure_running
    └─ Popen(media_player.exe)  stdin/stdout/stderr PIPE
              cwd = exe 目录（便于找 FFmpeg DLL）

再次 open
    └─ _restart(): QUIT → wait/kill → 新进程再 OPEN

可选 PlayerBackend.shutdown / Widget 销毁
    └─ _restart() 清掉子进程 + 临时目录随进程结束
```

---

## 8. 对照：`media_player` vs `media_cli`

```
首页预览          media_player.exe   → 临时 RGB → GlVideoWidget
后台扫帧/分析     media_cli iterate  → 回调时间戳，不画屏
ASR 抽音频        media_cli extract-audio → WAV 文件
缩略图            media_cli thumbnail → PPM（高光时间轴）
```

底层都可走 FFmpeg；入口与协议不同。

---

## 9. 跟代码顺序

```
video_player.py
    open_file / play / _on_tick / _pull_and_show_frame / _sync_video_to_audio
        → player_backend.py
              open / next_frame / _send / _decode_frame
        → player_main.cpp          # 字符串分发 OPEN/NEXT/SEEK…
        → video_player_engine.cpp  # open / seek / decodeNextFrameToFile
        → gl_video_widget.py       # set_rgb_frame
```

*以 `player_backend.py` + `player_main.cpp` 为准；协议变更时同步改本文调用树。*
