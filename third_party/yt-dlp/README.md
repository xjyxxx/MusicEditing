# yt-dlp（链接下载引擎）

本目录存放 **yt-dlp** 独立可执行文件，供「链接下载」功能打包分发。

## 布局

```
third_party/yt-dlp/
  yt-dlp.exe          # Windows x64（由脚本下载，默认不进 git）
  README.md
```

## 获取

```powershell
.\scripts\download_yt_dlp.bat
```

官方发布页：https://github.com/yt-dlp/yt-dlp/releases

## 运行时查找顺序

`MediaBridge` / 下载页：

1. `third_party/yt-dlp/yt-dlp.exe`
2. `build_x64/bin/Release/yt-dlp.exe`（若打包时复制）
3. `PATH` 中的 `yt-dlp`

转码依赖项目已有 FFmpeg：`third_party/ffmpeg/x64/bin/ffmpeg.exe`（通过 `--ffmpeg-location` 传入）。

## 许可

yt-dlp 为 Unlicense；请遵守各视频站点服务条款，仅用于自有/授权素材。
