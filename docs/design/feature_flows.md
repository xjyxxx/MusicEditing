# 业务功能链路

> **上级枢纽：** [implementation_flow.md](implementation_flow.md)  
> **相关：** [mvvm_and_ui.md](mvvm_and_ui.md) · [media_engine.md](media_engine.md) · [deps_and_extending.md](deps_and_extending.md)

按产品功能组织的端到端链路（UI → ViewModel → Bridge / CLI / FFmpeg）。对应原实现说明 §5。

---

## 目录

| 节 | 主题 |
|----|------|
| §5.1 | 智能切片 / 缩略图时间轴 |
| §5.2 | 游戏高光 · 热评滚动 |
| §5.3+ | CLI 补充、超分、成片导出、下载、EXIF… |
| §5.9 | 三大功能串联 / 全流程队列 |
| §5.10+ | 补帧、天气、波形、LUT、封面、音频、BGM、个人中心… |
| §5.22 | 溯源水印 |
| §5.23 | 工程质量：回归短测 / 诊断包 / 资源清理 |

### 5.1 智能切片完整链路（演讲金句等 — 已落地）

对应产品文档 4.2 节。**场景：演讲金句、日常精彩片段、自定义识别**

```
用户点击「AI 智能分析」（场景=演讲金句）
  │
  ▼
MainViewModel.start_slice_analysis()  [后台线程]
  → _analyze_speech_pipeline()
      ├─ extract-audio → 16kHz WAV
      ├─ 有 Vosk：ASR → analyze-speech（LLM 或 C++ 金句规则）
      │         失败则 Python speech_highlights.score_transcript
      └─ 无 Vosk：silencedetect 人声段 → clips_from_speech_ranges
  → highlightsReady → SlicePage 时间轴/列表
  → SlicePage 后台抽各段中点缩略图 → 时间轴胶片条 + 列表图标
```

| 资源 | 路径 |
|------|------|
| 金句规则 | `client/scripts/core/speech_highlights.py` |
| Vosk 下载 | `scripts/download_vosk_model.bat` → `models/vosk-model-small-cn-0.22/` |
| C++ 规则加权 | `highlight_analyzer.cpp` fallbackAnalyze |
| 缩略图 | 见 §5.1.1 |

**Vosk：** `resolve_vosk_model_dir` 校验 `am/final.mdl`；勿把空路径当成 `.`。无模型时演讲金句仍可用（人声段兜底），完整「听懂金句」需下载模型。

### 5.1.1 高光缩略图时间轴（产品 4.2「缩略图+时间轴」）

对应产品文档：分析完成后展示所有高光片段的**缩略图 + 时间轴**。

```
highlightsReady(segments)
  │
  ▼
SlicePage._on_highlights
  → HighlightTimelineWidget.set_segments（色块）
  → 列表文字项
  → 后台线程：对每段 midpoint
        MediaBridge.extract_thumbnail(video, mid, max_width=160)
          → media_cli thumbnail … [--hw]
              → media_extract_thumbnail → PPM（可缩放）
          → thumbnail_cache（%TEMP%/MusicEditing/thumbs/）
  → thumbnailReady → 时间轴胶片 + QListWidget 图标
```

| 资源 | 路径 |
|------|------|
| CLI | `media_cli thumbnail`（`client/src/media_cli.cpp`） |
| C API | `media_extract_thumbnail` / `VideoDecoder::extractThumbnail` |
| Bridge | `MediaBridge.extract_thumbnail` |
| 缓存 | `client/scripts/core/thumbnail_cache.py` |
| UI | `HighlightTimelineWidget`（色块 + 缩略图条）+ 切片页列表图标 |
| 模型字段 | `HighlightSegment.thumbnail_path` |

**说明：** 不引入新第三方库；输出 PPM（Qt `QPixmap` 可直接加载）。硬解跟随 `prefer_hw_decode`（`--hw`）。手动增删片段后同样会重新拉缩略图。

**依赖配置**（`client/resources/config/app.conf`）：

| 键 | 说明 |
|----|------|
| `vosk_model_dir` | Vosk 中文模型**绝对路径**（含 `am/final.mdl`）；留空自动探测，勿填 `.` |
| `llm_model_path` | `.gguf` 模型路径；留空则 ASR + 规则打分 |

### 5.2 游戏高光（PySceneDetect + 轻量语义打分）

**场景：游戏高光** → `_analyze_game_fallback()`：

```
SlicePage「游戏高光」→ start_slice_analysis
  → _analyze_game_fallback
      → core.scene_detect.detect_scene_ranges
            AdaptiveDetector（默认，抗快速运镜）或 ContentDetector
            敏感度 → adaptive_threshold / content threshold
      → ranges_to_clipped_segments（按最短/最长整形，最多约 24 段）
      → core.game_semantic.enrich_game_segments
            运动/闪光 + HUD 击杀感；有 models/game_event.onnx 则 ORT 抬分
            重排/抬高 score
      → 失败 / 未安装 → 时间轴规则 `_simulate_highlights` 兜底
```

| 资源 | 路径 |
|------|------|
| 封装 | `client/scripts/core/scene_detect.py` |
| 语义层 | `client/scripts/core/game_semantic.py` |
| 第三方库 | `scenedetect`（[PySceneDetect](https://www.scenedetect.com/)） |
| 安装 | `run_ui_*.bat` 自动 `pip install -e third_party/PySceneDetect`；或 `scripts/install_scenedetect.bat` |
| 本地源码 | **已随仓库** `third_party/PySceneDetect`（见 `README.MusicEditing.md`） |

**配置（`app.conf`）：**

| 键 | 说明 |
|----|------|
| `scenedetect_method` | `adaptive`（默认）\| `content` |
| `scenedetect_frame_skip` | 跳帧加速，`0` 最准 |

**限制：** 语义层含运动/闪光 + HUD「击杀感」；若存在 `models/game_event.onnx` 则 ORT 推理抬分（可用 `scripts/make_game_event_stub_onnx.py` 生成占位）。真击杀检测请覆盖同名 ONNX。长视频可把 `scenedetect_frame_skip` 调到 `1`–`3` 提速。

### 5.2.1 网易云热评滚动（已落地）

与链接下载**三合一**为同一页（菜单「工作流 → 下载与热评」；趣味「热评弹幕」滚到评论结果区）。
本页**无播放器、无弹幕预览**：一步「获取」产出**评论列表 + 媒体列表**（勾选加入，可点选播放），媒体槽供「送首页播放」在 `HomePage` 叠 `CommentMarquee`。

参考 B 站展示思路（[BV1vC4y1t7Wi](https://www.bilibili.com/video/BV1vC4y1t7Wi/)）与
[ObjTube/NeteaseMusic-qingtian-comment](https://github.com/ObjTube/NeteaseMusic-qingtian-comment)；
视频生成器 [wyy-videoGen](https://github.com/ObjTube/wyy-videoGen) 仅作展示参考（本项目本轮不接烧录成片）。

```
用户输入链接或歌曲 ID /「晴天 186016」试例 →「获取」（不下载）
  │
  ▼
DownloadPage
  ├─ 网易云 song_id → 并行 fetch_hot_comments → 评论列表
  └─ yt-dlp 探测（normalize 抖音 modal_id 等）→ 弹窗勾选 → 加入媒体列表
  │
  ▼
双击/「播放选中」→ 拉取后送首页叠弹幕（写入本地历史）
「下载到媒体槽」→ 写入唯一媒体槽 → 可再「送首页播放」
下次打开本页自动载入历史，无需再粘贴链接
B 站：列表优先「音画合并」（DASH 画面+音轨）；获取时并行拉弹幕 XML
```

**UI：** 氛围条（歌名/试例）+ 获取条（输入框 +「获取」，无单独粘贴按钮；分段音视频）+ 保存目录 + **Cookie 文件选择/清除**（写入 `yt_dlp_cookies_file`）+ 媒体卡 + 媒体列表（含历史）+ 评论/弹幕列表；无独立「高级探测」区；页级 `hot_comments_stylesheet()`。弹幕仅首页 `CommentMarquee`（速度/密度/全屏·半屏·四分之一）。

**历史：** 播放/下载成功后经 `url_info_cache` 写入 `~/MusicEditingInfoCache`；启动时载入最近约 40 条；选中时回填链接输入框。

**B 站：** `normalize_webpage_url` 收敛为 `/video/BVxxx`；探测列表由 `_prefer_av_merged_items` 生成「音画合并」项。下载默认**先无 Cookie**（普通画质音画通常可用），再回退浏览器 Cookie；`format` 用 `bv*+ba` 并加重试；若仍无音轨则**分轨下载 + ffmpeg 合并**。大会员高画质需 `yt_dlp_cookies_file`（Windows 上 Chrome DPAPI 常失败）。勾选音画合并时忽略「只要音频」。历史坏缓存（无声 MP4 / 误存 MP3）播放时丢弃重下。`core/bilibili_danmaku.py` 经 cid 拉弹幕 XML。

**首页弹幕控制（`HomePage` + `CommentMarquee`）：**

| 项 | 说明 |
|----|------|
| 速度 | 0.40×～2.50×，飞行中即时生效 |
| 密度 | 0.40×～2.50×，影响生成间隔与同屏数量 |
| 区域 | 全屏 / 半屏 / 四分之一（自画面顶部向下） |

**评论导出与短视频（`core/comment_export.py`）：**

| API | 状态 | 说明 |
|-----|------|------|
| `CommentExportPackage` / `build_export_package` | ✅ | 导出契约：评论 + 歌曲/媒体元数据 |
| `export_comments_json` / `load_export_package` | ✅ | 完整 JSON，可供二次处理 |
| `export_comments_ass` | ✅ | `style=ass_caption\|danmaku\|cards`（顺序 / 滚动弹幕 / 底栏卡片） |
| `CommentShortVideoRequest` / `render_comment_short_video` | ✅ | 按 style 生成 ASS 后竖屏烧录；下载页导出可选三种风格 |

UI「导出评论…」可选 JSON / ASS / 热评短视频 MP4（短视频前选风格）。

**配置（`app.conf`）：**

| 键 | 说明 |
|----|------|
| `netease_api_base` | 如 `http://127.0.0.1:3000` |
| `netease_hot_comments_script` | 自定义脚本绝对路径 |
| `netease_hot_comments_demo` | 网络失败时是否演示数据 |
| `yt_dlp_cookies_from_browser` | 如 `chrome` / `edge`；须退出浏览器；失败会无 Cookie 回退 |
| `yt_dlp_cookies_file` | Netscape cookies.txt 路径（优先于 from-browser） |

试例歌曲（晴天）：`186016` 或 `https://music.163.com/#/song?id=186016`

**缓存：** `.cache/hot_comments/`（gitignore）；网络失败时可读缓存并标注来源。


### 5.3 media_cli 新增命令（见 [media_engine.md](media_engine.md) CLI）

**extract-audio：**
```
media_cli extract-audio <video> <out.wav>
→ EXTRACT_AUDIO_OK
```

**analyze-speech：**
```
media_cli analyze-speech <transcript.json> <model.gguf> <场景> <最短> <最长> <敏感度>
→ HIGHLIGHTS_OK
→ HIGHLIGHT|12.500|18.000|0.850
```

### 5.4 画质增强 / 超分完整链路

对应产品文档 4.3 节。

```
用户操作 EnhancePage
  │
  ▼
View: EnhancePage._on_run_image / _on_run_video
  → 顶栏 ai_runtime_hint（GPU 推理开/关 · 超分/LaMa 模型是否就绪）
  → 试用门禁：AI 4× 灰显 + require_feature("enhance_ai_4x")
  → ViewModel.start_enhance_image / start_enhance_video
      → 缺 realesrgan 模型时提示 scripts\download_realesrgan_model.bat
      → MediaBridge.upscale_image / upscale_video（继承 MUSIC_ORT_CUDA）
          → media_cli upscale / upscale-frames
              → SuperResolution::upscaleImageFile
  → emit enhanceProgress / enhanceFinished
  │
  ▼
View 更新进度与结果预览
```

**当前限制：** 视频 AI 超分仍较慢（ONNX 串行）；OpenCV 快路径已用 JPEG 中间帧 + 多线程批帧。对比区左原图 / 右超分结果，中间 1px 细线；滚轮缩放当前侧，Ctrl+滚轮两侧同步；拖拽平移。预览经 `image_loader`（OpenCV 解码）；显示为不透明底软件合成，避免缩小时残影。试用可用 OpenCV 2×；正式版解锁 AI 4×（见 §5.17）。

**长路径：** 各子 Tab 路径行使用 `ui/elided_label.ElidedPathLabel`（`ElideMiddle` + Tooltip 全文），`sizeHint` 不按完整路径回报宽度，避免缓存目录超长文件名把整页/窗口撑向右侧。

### 5.5 一键高光成片 / 静音剪掉 / 竖屏短视频

```
SlicePage「一键高光成片」
  → ExportOptionsDialog（分辨率 / 质量 / 容器；可等同现网默认）
  → MainViewModel.export_highlights(out_dir, max_height=, quality=, container=)
      → MediaBridge.export_highlights
          → ffmpeg 按段 -ss/-t 切出 highlight_XXX.（优先 -c copy；有缩放/质量则重编码）
          → concat demuxer → highlights_merged.*
  → exportFinished

SlicePage「静音剪掉」
  → MainViewModel.compact_speech(out_mp4)
      → MediaBridge.remove_silence
          → ffmpeg silencedetect 解析静音区间
          → 反推有声段 → export_clip × N → concat
  → silenceFinished

SlicePage「竖屏短视频」
  → 选裁切锚点（居中/偏上/偏下）→ ExportOptionsDialog → 保存路径
  → MainViewModel.export_vertical_short(..., quality=)
      ├─ 有高光片段：export_highlights 临时成片
      └─ MediaBridge.export_vertical_short
            → ffmpeg scale+crop 9:16（默认 1080x1920；质量映射 _video_encoder_args）
  → verticalExportFinished → 可送去超分/去水印
```

**导出参数（`ui/export_options_dialog.py`）：** 分辨率 原画/1080p/720p；质量 高/标准/小文件；格式 mp4/mov。不选或保持默认时行为与现网固定管线一致。  
**remux 优先：** 高光分段与拼接默认 `-c copy`；仅当质量≠高或限制分辨率时，对合并成片**一次**重编码（避免分段多次重编）。编码档映射 `_video_encoder_args` / `_audio_encoder_args`，并带 `-movflags +faststart`。另有 `MediaBridge.remux_copy` 供仅改封装。

优先走捆绑 `ffmpeg.exe`，无需新 C++ CLI。静音阈值默认 `-35dB`、最短静音 `0.45s`。  
竖屏导出**不再**烧录外挂 SRT；热评短视频仍可通过 ASS + `export_vertical_short(subtitle_path=…)` 烧录评论文本。

**智能跟脸（`track_mode=face`）：** SlicePage 竖屏锚点可选「智能跟脸」→ OpenCV Haar 采样人脸中心 → 平滑轨迹 → 分段 `crop`+`concat`；无人脸或失败回退 `crop_bias` 固定裁切（`core/face_track.py`）。

**发布预设 + 规范命名 + 成片模板：**  
- `ExportOptionsDialog` / 队列页可选 **成片模板**（抖音爆款≤45s / B站高光≤60s / 快手快剪≤30s）：限总时长 → 合并 → 跟脸竖屏 → 封面文案位 + 话题草稿（`core/film_templates.py`）。  
- 发布预设仍填抖音/B站/快手分辨率与质量；规范命名见 `export_naming`。

### 5.6 链接下载（yt-dlp）+ 热评三合一

```
DownloadPage（单页）
  ├─ 「获取」：链接/ID → 规范化 → 探测（不下载）→ 弹窗勾选 →「加入列表」
  │            网易云→热评；B 站→弹幕 XML（cid）
  ├─ 「媒体列表」：含历史；B 站优先「音画合并」；双击播放；下载到媒体槽
  └─ 「结果」：媒体槽 + 评论/弹幕 →「送首页播放」（§5.2.1）
```

| 资源 | 路径 |
|------|------|
| 引擎 | `third_party/yt-dlp/yt-dlp.exe`（`scripts/download_yt_dlp.bat`） |
| 转码 | 项目已有 FFmpeg |
| 信息/播放历史 | `core/url_info_cache.py` → `~/MusicEditingInfoCache`（启动自动载入列表） |
| Cookie | 本页「Cookie…」→ `yt_dlp_cookies_file`（优先）或 `yt_dlp_cookies_from_browser` |
| 重试 | `_yt_dlp_retry_args`：retries/fragment/file-access + 指数退避；缓解 bilivideo SSL EOF |
| 失败可恢复 | `core/download_recover.py` 白话分类（Cookie/限流/无音轨/SSL）；下载页弹窗「换 Cookie / 重试」；热评短视频失败同理 |

**B 站稳定性：** 探测优先「音画合并」；下载 `bv*+ba`；仍无音轨则分轨 + ffmpeg 合并；普通画质可无 Cookie，大会员高画质需 Cookie 文件。

**抖音 Cookie 导出（必做）：**

1. Edge/Chrome 允许「来自其他应用商店的扩展」后安装 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)，或用 Cookie Editor 导出 **Netscape** 格式。
2. 打开 [douyin.com](https://www.douyin.com) 并能刷视频，再点扩展 **Export**。
3. 用记事本确认文件含多行 `.douyin.com …` 数据（**只有两行 `#` 注释的空文件无效**）。
4. 本页点「Cookie…」选择该文件（**勿选 `app.conf`**）；写入 `yt_dlp_cookies_file` 后重新「获取」。

**抖音：** `jingxuan?modal_id=` → `/video/<id>`（链接本身通常可用）。**必须**提供有效 Cookie 文件；`cookies-from-browser` 在 Windows 新版 Chrome/Edge 上常因 DPAPI/锁库失败。

「获取」**不会**自动下载；勾选加入列表后点选播放。已播放/下载的条目会留在历史中，下次打开可直接点播。

**注意：** 仅下载自有/授权素材；站点规则变化时更新 yt-dlp 即可。

### 5.7 图片 EXIF（ExifTool）

```
EnhancePage / WatermarkPage 导入图片
  → ExifPanel.load_path（异步）
      → MediaBridge.read_image_exif(full=True)
          → third_party/exiftool/exiftool.exe
  → 图片右上角悬浮摘要（常用字段约 5 行）
  → 点「全部」/ 双击摘要 → ExifFullDialog 查看完整标签
```

| 资源 | 路径 |
|------|------|
| 引擎 | `third_party/exiftool/exiftool.exe` + `exiftool_files/`（`scripts/download_exiftool.bat`） |
| UI | `client/scripts/ui/exif_panel.py`（`ExifPanel` 悬浮 + `attach_exif_overlay`） |

**注意：** 复制到 `bin/Release` 时必须同时复制 `exiftool_files`。不再在图片下方常驻大段文本。

### 5.8 （已移除）外挂字幕 / 实时字幕

播放器外挂字幕与实时同传已从产品范围移除；热评 ASS 烧录仍见 §5.2.1。


### 5.9 三大功能串联（一站式剪辑，异步）

对应产品文档 §5。任意一页 `import_video` 写入 `AppState.current_video`，其它页经 `videoLoaded` 同步；**结果接力**通过 `MainWindow.open_with_video(path, tab)`。

**线程约定：** 重活在后台 `threading.Thread`；UI 只在主线程经 Qt Signal（Queued）更新。

| 操作 | 线程 |
|------|------|
| `import_video`（probe） | 后台 → `videoLoaded` |
| `start_slice_analysis` | 后台 → `progressUpdated` / `highlightsReady` |
| 超分 / 去水印 / 导出高光 / 静音剪掉 | 已后台 |
| `open_with_video` 切 Tab | 主线程（先切页再异步 import） |
| `start_pipeline_queue` | 后台有限并行（默认 2）：切片/导出可重叠；超分+去水印串行（§5.9.1） |

```
切片「一键高光成片 / 静音剪掉」完成（后台）
  → 主线程弹窗「送去超分 / 送去去水印」
  → open_with_video：先切 Tab，再异步 import_video(成片)

去水印完成（视频）→「送去超分」
超分完成（视频）→「送去去水印」

各页按钮：「用当前视频」「送去超分」「送去去水印」
```

| 资源 | 路径 |
|------|------|
| 编排 | `MainWindow.open_with_video` |
| 弹窗 | `ui/workflow_link.py` |
| 触发 | `SlicePage` / `EnhancePage` / `WatermarkPage` |

### 5.9.1 批量全流程队列（无人值守）

对应产品文档 §5.4「自动切片 + 画质增强 + 去水印」一站式批量。独立 Tab「全流程队列」，**不走**各页完成弹窗，直接调 `MediaBridge` + 切片分析逻辑。

```
PipelineQueuePage「开始队列」
  → MainViewModel.start_pipeline_queue(paths, PipelineSettings)
      → 后台线程 core/pipeline_runner.run_pipeline_queue
            max_parallel（默认 2）：多任务切片/导出可重叠
            超分 + 去水印用信号量串行（防 GPU/磁盘互抢）
            每个视频：
              probe
              → [可选] analyze → export_highlights → highlights_merged.mp4
              → [可选] upscale_video（OpenCV / Real-ESRGAN）
              → [可选] watermark_inpaint_video（角标预设区域）
      → pipelineItemUpdated / pipelineFinished（主线程刷新列表）
```

| 资源 | 路径 |
|------|------|
| UI | `ui/pipeline_queue_page.py`（双栏：左队列 / 右步骤芯片+参数；底栏进度与操作） |
| 模型 | `models/pipeline_model.py` |
| 编排 | `core/pipeline_runner.py` |
| VM | `MainViewModel.start_pipeline_queue` / pause / skip / cancel |

**参数要点：** 步骤可勾选；**成片模板**（抖音/B站/快手一键竖屏+封面话题）；超分默认 OpenCV 2×，试跑秒数默认 **8**（`0=全程`）；**并行任务 1–4**（默认 2）；**产物上限**默认 20 GB；失败自动重试 1 次；启动前磁盘 &lt;5GB 预警。去水印默认关。输出：`output_root/<文件名>/`。

**控制：** 暂停、跳过当前（并行时消费一次）、取消队列。

**限制：** 超分/去水印仍串行；角标去水印是启发式框；切片场景与单页相同。

### 5.10 视频补帧（FFmpeg minterpolate / 可选 RIFE）

对应画质增强 Tab「视频补帧」：2× / 4× 提帧率。默认 FFmpeg minterpolate；可选 RIFE ONNX（需 `models/rife.onnx`，失败回退 FFmpeg）。

```
EnhancePage「视频补帧」
  → 独立时间段（默认试 15 秒；可全程）+ 快速/精细 + 引擎 ffmpeg|rife
  → MainViewModel.start_interpolate_video(backend=)
      → MediaBridge.interpolate_video
          ├─ backend=rife → 提帧 → RIFE ONNX → 编码（失败回退）
          └─ ffmpeg -vf minterpolate=…
                fast → mi_mode=blend（默认，快）
                quality → mi_mode=mci（运动补偿，慢；失败回退 blend）
  → interpolateProgress / interpolateFinished（含 ETA）
```

| 资源 | 路径 |
|------|------|
| UI | `EnhancePage` 第三 Tab |
| VM | `start_interpolate_video`（`TaskType.INTERPOLATE`） |
| Bridge | `MediaBridge.interpolate_video` |
| 引擎 | `third_party/ffmpeg/{x64\|x86}/bin/ffmpeg.exe` |

**参数：** `factor=2|4`；`quality=fast|quality`；区间与超分「试 2 秒」**独立**。  
**限制：** 精细模式慢；插帧+重编码会柔化细节，观感可能不如原片锐利。

### 5.11 状态栏天气（IP 定位 + Open-Meteo）

顶栏显示本地城市与当前天气；**不阻塞 UI**。晴/雨时附带「今日氛围」滤镜推荐（趣味彩蛋）。

```
MainWindow.__init__
  → _start_weather_refresh()
      → QTimer 30min + 立即 _refresh_weather()
          → 后台线程 fetch_local_weather(timeout=5s)
                ├─ locate_by_ip()  # 按本机公网 IP 粗定位本地城市
                │     ├─ 太平洋/pconline ipJson（中文省市）→ Open-Meteo 地理编码
                │     ├─ ip-api → Nominatim 反查中文城市
                │     └─ ipwho.is → Nominatim 反查
                └─ Open-Meteo /v1/forecast?current=temperature_2m,weather_code,…
          → weatherUpdated.emit(WeatherInfo | None)
              → _on_weather_updated
                    ├─ 文案：如「深圳 小毛毛雨 25°C · 胶片」
                    ├─ recommend_mood(code)：晴→暖阳(warm) / 雨→雨幕(film) / 雪→雪色(cool) / 雷→雷霓(neon)…
                    ├─ 胶囊换色 +「· 点我」+ 边框闪烁
                    └─ 可点天气胶囊 → 切首页 + VideoPlayerWidget.set_filter_mode
```

| 资源 | 路径 |
|------|------|
| UI | `MainWindow._weather_label` / `_on_weather_clicked` |
| 服务 | `core/weather_service.py`（`recommend_mood` / `WeatherMood`） |
| 滤镜落地 | `HomePage.apply_opencv_filter` → `VideoPlayerWidget.set_filter_mode` |
| 天气 API | `https://api.open-meteo.com`（免 Key） |

**今日氛围映射（WMO code）——电影向滤镜，观感更明显：**

| 天气 | code | 标签 | 滤镜 | 观感 |
|------|------|------|------|------|
| 晴 / 晴间多云 | 0, 1 | 暖阳 | `warm` | 金橙电影暖调（替代原 CLAHE） |
| 多云 / 阴 | 2, 3 | 天光/阴冷 | `cool` | 青蓝冷调 |
| 雾 | 45, 48 | 雾色 | `vintage` | 复古褪色雾感 |
| 雨 / 阵雨 | 50–69, 80–82 | 雨幕 | `film` | 胶片颗粒+暗角 |
| 雪 | 70–79, 85–86 | 雪色 | `cool` | 冷调干净感 |
| 雷暴 | ≥95 | 雷霓 | `neon` | 霓虹描边（最醒目） |

顶栏胶囊按氛围换色（琥珀/雨蓝/冷青/雾褐/雷紫），文案带「· 点我」，首次出现边框闪烁；点击切首页并套滤镜，底栏明确反馈。

**限制：** 城市来自**本机出口 IP 粗定位**（代理/VPN 会偏到出口城市，非 GPS）；单次请求超时 5s，失败显示「天气: 暂不可用」。不自动改滤镜，需用户点击；需首页已打开视频才能看见画面变化。



### 5.12 波形 + 响度可视化 / 响度高潮

纯 FFmpeg：`showwavespic` 出波形图，`ebur128` + `ametadata=print` 出瞬时响度曲线；无新第三方库。

#### 首页播放器

```
打开视频/音乐
  → VideoPlayerWidget._start_audio_viz（后台线程）
      → core.audio_viz.analyze_media_audio
            showwavespic → .cache/audio_viz/*_wave.png
            ebur128=metadata=1,ametadata=print → M/S/I 采样
  → WaveformWidget：底图波形 + 青绿响度曲线 + 琥珀播放头
  → 点击波形 → seek
```

| 资源 | 路径 |
|------|------|
| UI | `ui/waveform_widget.py`（嵌在 `VideoPlayerWidget` 画面下方） |
| 分析 | `core/audio_viz.py` |
| 缓存 | `.cache/audio_viz/`（gitignore） |

#### 切片「响度高潮」

```
SlicePage 场景「响度高潮」→ AI 智能分析
  → MainViewModel._analyze_loudness_climaxes
      → analyze_ebur128 → find_loudness_climaxes（阈值随敏感度）
  → highlightsReady（同其它场景）
```

全流程队列场景下拉同样可选「响度高潮」。

**限制：** 长视频分析耗时随时长线性增长（有磁盘缓存）；响度高潮偏音乐/情绪起伏，不替代游戏视觉切点或演讲语义。



### 5.13 LUT / 一键调色

与 `FrameProcessor` 滤镜同层预设：`warm`（电影暖调）/ `cool`（冷调）/ `vintage`（复古）。

```
首页滤镜下拉 warm|cool|vintage
  → media_player set_filter → FrameProcessor 色矩阵（实时预览）

EnhancePage「一键调色」
  → 预览：OpenCV 同矩阵
  → 导出：MediaBridge.apply_color_grade
        图片 → OpenCV；视频 → FFmpeg lut3d（.cache/luts/*.cube）
  → 「套到播放器滤镜」→ HomePage.apply_opencv_filter
```

| 资源 | 路径 |
|------|------|
| C++ | `frame_processor.h/.cpp`（Warm/Cool/Vintage） |
| Python | `core/color_grade.py`（cube 生成 + lut3d） |
| UI | `EnhancePage` Tab「一键调色」；播放器滤镜下拉 |
| VM | `MainViewModel.start_color_grade` |

**限制：** 调色矩阵为风格化近似，非专业电影 LUT 包；`lut3d` 失败时回退 `colorbalance`/`eq`。

**性能：** 预览用 `cv2.transform` + 缩边；视频导出默认**不整片拷贝**到临时目录（非 ASCII 路径才拷贝）；`lut3d` 用 `trilinear`；Win 优先 `h264_mf`；播放器暖/冷/复古走 `cv::transform`（OpenCL UMat 可用时走 GPU）。


### 5.14 封面 / 缩略图工厂

在已有 `media_cli thumbnail` / `MediaBridge.extract_thumbnail` 之上：均匀抽样多帧 → OpenCV Laplacian 方差选最清晰帧 → Qt 绘制大字标题 PNG（默认 9:16）。

```
CoverPage「生成封面」
  → MainViewModel.start_cover_factory
      → MediaBridge.make_short_cover
          → cover_factory.pick_sharpest_frame（多次 extract_thumbnail）
          → cover_factory.render_cover_png（QPainter + 微软雅黑）
  → coverFinished → 预览 PNG
  →（可选）导出后溯源勾选
        → blind_watermark_dct.embed_text_dct（大标题）
        → exif_stamp.stamp_exif（作者=大标题）
```

| 资源 | 路径 |
|------|------|
| Python | `core/cover_factory.py` |
| UI | `ui/cover_page.py`（Tab「封面工厂」） |
| VM | `MainViewModel.start_cover_factory` |
| 依赖 | `extract_thumbnail`（PPM）+ OpenCV + PySide6；可选 ExifTool / 频域水印 |

**限制：** 锐度启发式（非语义「好看」）；中文字体依赖系统「Microsoft YaHei UI」。


### 5.15 音频趣味页

纯 FFmpeg 滤镜链：变调 `asetrate`+`aresample`、变速 `atempo`、倒放 `areverse`、伪 8D `apulsator`、简单混响 `aecho`。可作用于音频文件或**带画面的视频**。

**音画同步（重要）：** 旧实现仅对音轨 `atempo`/`areverse` 且 `-c:v copy`，加速 1.25× 等会导致音频变短而画面仍原时长 → 音画不同步。现已对齐：

| 效果 | 音频 | 视频 | 说明 |
|------|------|------|------|
| 变速 `speed` | `atempo`（可串联） | `setpts=PTS/speed` 重编码 | 倍速一致，时长一致 |
| 倒放 | `areverse` | `reverse` 重编码 | 须整段解码，耗内存 |
| 变调 `pitch` | `asetrate`+补偿 `atempo` | copy（时长不变） | 采样率取自 ffprobe，非写死 44100 |
| 8D / 混响 | `apulsator` / `aecho` | copy + `-shortest` | 混响尾音裁到画面长度 |

```
AudioFunPage「导出效果」
  → MainViewModel.start_audio_fx
      → MediaBridge.apply_audio_fx
          → core.audio_fx.apply_audio_fx
                ├─ 仅音效：-af … -c:v copy
                └─ 变速/倒放：-vf setpts|reverse -af … 视频重编码
  → audioFxFinished
```

| 资源 | 路径 |
|------|------|
| Python | `core/audio_fx.py` |
| UI | `ui/audio_fun_page.py`（Tab「整轨趣味」） |
| VM | `MainViewModel.start_audio_fx` |

**限制：** 变调为采样率法（非专业移调器）；8D 为左右脉冲伪环绕；视频倒放需整段进内存；非实时预览。

**梗音叠加（同页 Tab「梗音叠加」）：** 本地短音效叠到视频指定时刻，支持倍数（0.5～4×，atempo 串联）与音量；可选略压原声。音效库：`assets/sfx/user/`（用户自备热梗）+ `assets/sfx/demo/`（自动生成免费演示音）。**不内置**第三方热梗原声。

```
AudioFunPage「梗音叠加」→ 导出
  → MainViewModel.start_sfx_overlay
      → MediaBridge.overlay_sfx → core.sfx_overlay.overlay_sfx
            → ffmpeg adelay + atempo + amix（视频 -c:v copy）
  → sfxOverlayFinished
```


### 5.16 BGM 混音 / 人声分离（Demucs 可选）

下载页拿歌 → 本页混到成片；进阶分轨用仓库内 Demucs 源码（可选装 PyTorch）。

```
BgmPage「BGM 混音」
  → MainViewModel.start_bgm_mix
      → MediaBridge.mix_bgm → core.bgm_mix（FFmpeg amix / 替换音轨）

BgmPage「人声分离」
  → MainViewModel.start_demucs_separate
      → MediaBridge.separate_demucs → core.demucs_sep
          → third_party/demucs（Separator API）
  未安装 torch/demucs 时 UI 灰显并提示 scripts\setup_demucs.bat
```

| 资源 | 路径 |
|------|------|
| 混音 | `core/bgm_mix.py`（仅 FFmpeg，默认可打包） |
| 分轨 | `core/demucs_sep.py` + `third_party/demucs`（MIT，~0.3MB 源码） |
| 安装 | `scripts/setup_demucs.bat`（可选；PyTorch + 权重另算） |
| UI | `ui/bgm_page.py`；菜单「工作流 → BGM 混音」 |
| 权重缓存 | `.cache/demucs/`（gitignore；可随包拷贝到其它电脑离线用） |

**打包给其它电脑：**

1. **必带：** 仓库 + `third_party/ffmpeg` → 混音可用。  
2. **可选分轨：** 再带 `third_party/demucs`，在目标机跑 `setup_demucs.bat`；或把已装的 venv + `.cache/demucs` 一并拷贝。  
3. **不要**依赖 `E:\FFmpegxuexi\demucs-main` 绝对路径。

**限制：** Demucs 依赖 PyTorch（体积大）；CPU 分轨慢；模型首次下载需网络（或预置缓存）。


### 5.17 个人中心（卡密 / GPU / 输出目录）

```
帮助 → 个人中心（ProfilePage）
  │
  ├─ 卡密兑换
  │     → MainViewModel.redeem_license
  │         → AppLogic.redeem_license → network.validate_license_key
  │         → 写入 app.conf：auth_type=正式版、license_fp=指纹
  │         → authTypeChanged → 顶栏「授权」胶囊
  │
  ├─ GPU 开关
  │     → MainViewModel.set_gpu_enabled
  │         → AppLogic.toggle_gpu → gpu_enabled 持久化
  │         → MediaBridge.set_prefer_hw_decode / set_prefer_cuda
  │
  ├─ 默认输出目录 → set_output_dir → app.conf output_dir
  │
  ├─ 开箱向导 → SetupWizardDialog
  │
  └─ 诊断与清理
        →「一键打包诊断日志」core/diag_pack.pack_diagnostics
              docs 下 player/cli/Python 日志 + ort_ep_report.json + diag_snapshot.json → zip
        →「清理临时帧」core/resource_cleanup.cleanup_orphan_temp_dirs
```

| 资源 | 路径 |
|------|------|
| UI | `client/scripts/ui/profile_page.py` |
| 校验 | `client/scripts/core/network.py` |
| 配置 | `app.conf`：`auth_type` / `license_fp` / `gpu_enabled` / `output_dir` |

**当前限制：** 卡密为本地格式校验（≥16 且含字母数字），联网支付未接。

**试用 / 正式门禁（`MainViewModel.require_feature`）：**

| 功能键 | 试用 | 正式 |
|--------|------|------|
| `enhance_ai_4x` | 灰显 AI 4×，VM 拦截 | ✅ |
| `pipeline_queue` | 「开始队列」灰显 + 拦截 | ✅ |
| `watermark_lama` | 精修 LaMa 灰显 + 拦截 | ✅ |

试用仍可用：OpenCV 超分 2×、快速去水印、单文件切片/导出。兑换/恢复试用经 `authTypeChanged` 刷新各页。


### 5.18 开箱向导 / 进度 ETA / 去水印批量加固

```
首次启动（setup_wizard_done 未写）或 media_cli 缺失
  → MainWindow._maybe_show_setup_wizard
      → SetupWizardDialog
            顶部「建议优先处理」摘要（next_actions_summary）
            检测：引擎 media_cli / GPU / Real-ESRGAN / LaMa / Vosk /
                  yt-dlp / Cookie / PySceneDetect / .gguf / game_event.onnx
      → 一键 scripts/download_*.bat；Cookie→下载页；编译/LLM 说明弹窗
      → **试跑 15 秒成片**（tests 样例 → 裁切 → 竖屏，`core/trial_run.py`）
      → 关键缺失时确认后才可「完成并进入」→ app.conf setup_wizard_done=true
个人中心「打开开箱向导…」可再次打开
```

**进度 ETA：** `core/progress_eta.py` 线性外推；超分/去水印/补帧/竖屏导出/全流程队列进度文案附「剩余约 XmYs」。

**批量去水印：** 失败自动重试 1～2 次（换 OpenCV / 略缩小区域）；列表显示等待/处理中/重试/成功/失败。角标预设：抖音右上 / 快手右上（`RegionSelector.apply_platform_corner_preset`）。

| 资源 | 路径 |
|------|------|
| 检测 | `core/setup_status.py` |
| 向导 UI | `ui/setup_wizard.py` |
| ETA | `core/progress_eta.py` |


### 5.19 本地素材库

```
工作流 → 本地素材库（MediaLibraryPage）
  → 索引 output_dir / 自选根目录（非云）
  → 列表：文件名 / 大小
  → 送首页 / 送切片 / 送队列（enqueue_paths）
```

| 资源 | 路径 |
|------|------|
| 索引 | `core/media_library.py` |
| UI | `ui/media_library_page.py`（`TAB_LIBRARY=10`） |


### 5.20 差异化能力入口（菜单）

首页仅作本地预览；功能入口走顶部菜单，例如：

1. **热评短视频** → 工作流「下载与热评」/ 趣味「热评弹幕」  
2. **演讲成片** → 核心「智能切片」（金句 → 静音剪掉 → 跟脸竖屏 → 抖音预设）  
3. **批量成片** → 工作流「全流程队列」（ETA + 角标去水印）

本地离线主链路默认可用；下载/热评网络步骤单独标注。


### 5.21 AI 画质速度（CUDA / tile / RIFE）

- **CUDA 自检：** `MediaBridge.probe_ort_cuda`；`ai_runtime_hint` 在 GPU 开但无 CUDA EP 时提示「已回退 CPU」  
- **超分 tile：** 增强页高级选项 → `MUSIC_UPSCALE_TILE`（C++ `super_resolution.cpp`，默认 384）  
- **补帧 RIFE：** EnhancePage 可选 RIFE ONNX（`models/rife.onnx`）；失败回退 FFmpeg minterpolate（`core/rife_interp.py`）  
- **不做：** TensorRT、云端超分  


### 5.22 溯源水印（频域 / 回声 / LSB / EXIF，自研）

与「去水印」分离：主动藏信息，非去除台标。**不 pip 安装** HideInfo / blind-watermark；仅用 OpenCV/NumPy/ExifTool/FFmpeg。

```
趣味 → 溯源水印（StegoPage）
  ├─ 频域封面（DCT Y 通道中频）→ core/blind_watermark_dct.py
  ├─ 回声水印（成片音轨 / WAV）→ core/echo_watermark.py（≥约 11s）
  ├─ LSB（PNG）→ core/stego_lsb.py
  └─ EXIF 署名 → core/exif_stamp.py
封面工厂导出可选：勾选后对 PNG 嵌频域水印 + 写 EXIF
```

| 资源 | 路径 |
|------|------|
| 频域 | `client/scripts/core/blind_watermark_dct.py` |
| 回声 | `client/scripts/core/echo_watermark.py` |
| LSB | `client/scripts/core/stego_lsb.py` |
| EXIF | `client/scripts/core/exif_stamp.py` |
| UI | `client/scripts/ui/stego_page.py`（`TAB_STEGO=11`） |

**致谢：** 思路参考 [blind-watermark](https://github.com/guofei9987/blind_watermark)、[HideInfo](https://github.com/guofei9987/HideInfo)（MIT），独立实现、未整库 vendoring。

**限制：** LSB 不抗强 JPEG；频域抗轻度压缩更好；回声需足够音轨时长且会重编码音频。不宣称对抗平台重编码。


### 5.23 工程质量（回归短测 / 诊断包 / 资源清理）

**回归短测（各一条自动化脚本）：**

```
scripts/run_regression_short.bat
  ├─ tests/regression/test_player_shm_seek.py     SHM + 预取 + Seek
  ├─ tests/regression/test_opencv_upscale.py      OpenCV 超分（≤12 帧）
  ├─ tests/regression/test_pipeline_parallel.py   队列 max_parallel=2 切片重叠
  ├─ tests/regression/test_vertical_export.py     竖屏 9:16 导出
  └─ tests/regression/test_cookie_probe_hint.py   Cookie/限流/无音轨白话提示
```

发版前清单见 [release_checklist.md](release_checklist.md)。

**便携分发：** `scripts/pack_portable.py` → `dist/MusicEditing_Portable_*` + `MusicEditing.exe`；内嵌 `runtime\`；**默认去掉可读 `.py`（只留 `.pyc`）**；C++ 为 exe/dll。`--ship-source` 仅调试。启动器经临时 bat 调 `vcvars64` 编译（避免 cmd 嵌套引号失败）。

**诊断包：** 个人中心「一键打包诊断日志」→ `core/diag_pack.py`  
写入桌面（或 `docs/diagnostics/`）zip：`log_media_player` / `log_media_cli` / Python 日志、`ort_ep_report.json`、`diag_snapshot.json`。  
`MediaBridge` 启动时为 CLI 设置 `MUSIC_LOG_FILE=docs/log_media_cli.txt`。

**资源清理：**

| 能力 | 实现 |
|------|------|
| 超分/去水印临时帧 | 正常路径 `finally` 删除；启动清理 `music_sr_*` 等残留（>6h）；个人中心可手动全清 |
| 队列产物上限 | `PipelineSettings.max_output_gb`（默认 20）；超限按最旧媒体文件删；队列页可改 |

| 资源 | 路径 |
|------|------|
| 诊断 | `client/scripts/core/diag_pack.py` |
| 清理 | `client/scripts/core/resource_cleanup.py` |
| 短测 | `tests/regression/` · `scripts/run_regression_short.bat` |


---
