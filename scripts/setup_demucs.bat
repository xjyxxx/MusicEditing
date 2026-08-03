@echo off
REM 可选：安装仓库内 Demucs + PyTorch（人声分离）。不装也能用 FFmpeg BGM 混音。
setlocal
cd /d "%~dp0.."

set "VENDOR=%CD%\third_party\demucs"

if not exist "%VENDOR%\demucs\__init__.py" (
  echo [错误] 未找到仓库内源码: %VENDOR%\demucs
  echo 请确认 third_party\demucs 已随仓库提交。
  exit /b 1
)

echo.
echo === MusicEditing Demucs 可选安装 ===
echo 源码目录: %VENDOR%
echo 说明: 权重首次分轨时下载到 .cache\demucs\ （约数十~百 MB）
echo PyTorch 体积较大；仅需「人声分离」的机器才跑本脚本。
echo.

REM 1) 先装 CPU 版 torch（若已有 CUDA 版可跳过本段）
python -c "import torch" 1>nul 2>nul
if errorlevel 1 (
  echo [1/3] 安装 PyTorch CPU（体积大，请耐心等待）…
  python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
  if errorlevel 1 (
    echo [警告] 官方 CPU 轮失败，尝试默认源 torch+torchaudio…
    python -m pip install "torch" "torchaudio"
  )
) else (
  echo [1/3] 已检测到 torch，跳过安装。
)

REM 2) Demucs 最小依赖（不含全量训练工具）
echo [2/3] 安装 demucs 最小依赖…
python -m pip install "einops" "julius>=0.2.3" "lameenc>=1.2" "openunmix" "pyyaml" "tqdm" "dora-search" "soundfile"
if errorlevel 1 (
  echo 依赖安装失败。
  exit /b 1
)

echo [3/3] editable 安装仓库 demucs…
python -m pip install -e "%VENDOR%"
if errorlevel 1 (
  echo editable 失败，尝试直接安装目录…
  python -m pip install "%VENDOR%"
)
if errorlevel 1 (
  echo Demucs 安装失败。
  exit /b 1
)

python -c "import demucs, torch; print('demucs OK', demucs.__version__); print('torch', torch.__version__, 'cuda=', torch.cuda.is_available())"
if errorlevel 1 exit /b 1

echo.
echo 完成。请重启客户端；在「BGM 混音」页可使用人声分离。
echo 若需 NVIDIA GPU：自行安装对应 CUDA 版 torch 后重跑本脚本（跳过已装 torch）。
endlocal
