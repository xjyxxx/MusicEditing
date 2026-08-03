# Demucs（仓库内第三方源码）

本目录已随仓库附带 [Demucs](https://github.com/facebookresearch/demucs) 源码（MIT），供「BGM 混音 / 人声分离」**可选**分轨使用。

上游：https://github.com/facebookresearch/demucs（Meta 原版已停更；源码约数百 KB，**不含** PyTorch 与权重）。  
同步自本机 `E:\FFmpegxuexi\demucs-main`（仅源码树，已去掉 test.mp3 / 大图等）。

## 体积说明（打包给别人）

| 部分 | 大约体积 | 是否随仓库 |
|------|----------|------------|
| 本目录源码 | ~0.3–1 MB | ✅ 随仓库 |
| PyTorch + torchaudio（CPU） | 数百 MB～2GB+ | ❌ 可选安装 |
| `htdemucs` 权重 | ~80 MB 级 | ❌ 首次分轨自动下载到 `.cache/demucs/` |

**不装 Demucs 也能用：** 客户端「BGM 混音」默认只靠项目内 **FFmpeg**（叠 BGM / 替换音轨），任意电脑拷贝仓库 + FFmpeg 即可。

## 别人机器怎么启用分轨

```bat
scripts\setup_demucs.bat
```

脚本会：

1. `pip install -e third_party\demucs`（及最小依赖）
2. 提示安装 **CPU 版** PyTorch（可改脚本装 CUDA）
3. 首次在 UI 点「人声分离」时再下权重到 `.cache/demucs/`（可打包时一并拷贝该目录到目标机，离线可用）

检查：

```bat
python -c "import demucs, torch; print(demucs.__version__, torch.__version__)"
```

## 运行时行为

- `client/scripts/core/demucs_sep.py`：探测失败则 UI 显示「未启用」，不影响混音。
- 不依赖 `E:\FFmpegxuexi\...` 等本机绝对路径。
- 权重缓存：项目根 `.cache/demucs/`（已 gitignore `.cache/`）。

## 许可

见本目录 `LICENSE`（MIT）。
