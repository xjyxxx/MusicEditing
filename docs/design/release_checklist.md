# 发版前短检（MusicEditing）

在仓库根目录执行。任一项失败则不要打 tag / 发安装包。

## 1. 回归短测（必跑）

```powershell
.\scripts\run_regression_short.bat
```

覆盖：

| 脚本 | 验收点 |
|------|--------|
| `test_player_shm_seek.py` | SHM 双缓冲 + Seek |
| `test_opencv_upscale.py` | OpenCV 超分短链路 |
| `test_pipeline_parallel.py` | 队列 `max_parallel=2` 切片重叠 |
| `test_vertical_export.py` | 竖屏 9:16 导出 |
| `test_cookie_probe_hint.py` | Cookie/限流/无音轨白话提示 |

期望末行：`ALL PASS`

## 2. 构建产物（x64）

```powershell
.\build_x64.bat
# 或已装 Vulkan SDK 时：
# $env:VULKAN_SDK="C:\VulkanSDK\<ver>"; python scripts\setup_llama_gpu.py vulkan
```

确认存在：

- `build_x64\bin\Release\media_cli.exe`
- `build_x64\bin\Release\media_player.exe`

演讲金句要 GPU：CMake 日志含 `GGML_VULKAN=ON`（或 CUDA），个人中心打开 GPU，`models\` 有 `.gguf`。

## 3. 便携分发（给别人用）

```powershell
.\scripts\pack_portable.bat
# 或: python scripts\pack_portable.py --zip
```

输出：`dist/MusicEditing_Portable_YYYYMMDD/`（可选同名 `.zip`）。

| 选项 | 含义 |
|------|------|
| `--zip` | 额外打 zip |
| `--skip-models` | 不带 lama/超分 ONNX（更小） |
| `--with-cuda-ort` | 带 CUDA ORT EP（约 +300MB） |
| `--with-llm` | 额外带 `.gguf` / vosk |
| `--ship-source` | **调试用**：保留可读 `.py`（默认删除，外发勿开） |
| `--no-scenedetect` | 不带 PySceneDetect |

对方解压后双击 **MusicEditing.exe**（推荐）。包内另有备用 `.bat`。**默认已内嵌 `runtime\`，对方不用再装 Python**；仅 Windows 10/11 x64。若闪退再装 VC++ x64 运行库。详见包内 `使用说明.txt`。

打包机需有 VS C++ 工具链（用于编译无黑框启动器）；脚本写临时 `build_launcher.bat` 调 `vcvars64`，避免 `cmd /c` 嵌套引号导致 exe 编译失败。

## 4. 手工冒烟（建议 10 分钟）

- [ ] `.\run_ui_x64.bat` 启动不卡死；首屏约 1s 内可点
- [ ] 首页打开 `tests\test_video.mp4`，播放 / Seek 正常
- [ ] 切片页：手动加一段 → 竖屏短视频出片
- [ ] 下载页：无 Cookie 拉抖音 → 弹「换 Cookie」类提示
- [ ] 全流程队列：选成片模板跑 1 条样例（可关超分）
- [ ] 开箱向导「试跑 15 秒」能出竖屏（若依赖齐）

## 5. 诊断包（可选）

个人中心 → 一键打包诊断日志 → 确认 zip 含 player/cli 日志。
