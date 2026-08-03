"""BGM 混音：成片视频 + 背景音乐（纯 FFmpeg，可打包、无 Demucs 也能用）。"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

ProgressFn = Callable[[float, str], None]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _find_ffmpeg() -> Path:
    root = _project_root()
    for p in (
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffmpeg.exe",
        root / "third_party" / "ffmpeg" / "x86" / "bin" / "ffmpeg.exe",
    ):
        if p.is_file():
            return p
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到 ffmpeg.exe")


@dataclass
class BgmMixParams:
    """混音参数。"""

    mode: str = "overlay"  # overlay | replace | duck
    bgm_volume: float = 0.35
    voice_volume: float = 1.0
    loop_bgm: bool = True


MIX_MODES = {
    "overlay": "叠加 BGM（保留原声）",
    "replace": "替换为 BGM（去掉原声）",
    "duck": "压低原声 + BGM",
}


def mix_bgm(
    video_path: str,
    bgm_path: str,
    output_path: str,
    params: Optional[BgmMixParams] = None,
    *,
    on_progress: Optional[ProgressFn] = None,
) -> str:
    """
    把 BGM 混进视频音轨。
    - overlay: 原声 + 减弱 BGM
    - replace: 仅 BGM（循环铺满视频时长）
    - duck: 原声压低后再叠 BGM
    """
    params = params or BgmMixParams()
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    if not os.path.isfile(bgm_path):
        raise FileNotFoundError(bgm_path)

    ffmpeg = _find_ffmpeg()
    report = on_progress or (lambda _p, _m: None)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    bv = max(0.0, min(2.0, float(params.bgm_volume)))
    vv = max(0.0, min(2.0, float(params.voice_volume)))
    mode = (params.mode or "overlay").lower()
    if mode not in MIX_MODES:
        mode = "overlay"

    report(5.0, f"混音模式: {MIX_MODES[mode]}")

    # 用 -stream_loop 让短 BGM 铺满；duration=first 以视频为准截断
    loop_args = ["-stream_loop", "-1"] if params.loop_bgm else []

    if mode == "replace":
        # 视频画面 copy + 仅 BGM
        fc = f"[1:a]volume={bv:.4f}[a]"
        cmd = [
            str(ffmpeg), "-hide_banner", "-y",
            "-i", str(Path(video_path).resolve()),
            *loop_args, "-i", str(Path(bgm_path).resolve()),
            "-filter_complex", fc,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(Path(output_path).resolve()),
        ]
    else:
        voice = vv if mode == "overlay" else min(vv, 0.45)
        # 无原声音轨时 amix 会失败 → 下面有回退
        fc = (
            f"[0:a]volume={voice:.4f}[va];"
            f"[1:a]volume={bv:.4f}[ba];"
            f"[va][ba]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]"
        )
        cmd = [
            str(ffmpeg), "-hide_banner", "-y",
            "-i", str(Path(video_path).resolve()),
            *loop_args, "-i", str(Path(bgm_path).resolve()),
            "-filter_complex", fc,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(Path(output_path).resolve()),
        ]

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=7200,
    )
    if result.returncode != 0 or not os.path.isfile(output_path):
        # 无音轨视频：当作 replace
        report(40.0, "原声混音失败，改为仅铺 BGM…")
        fc = f"[1:a]volume={bv:.4f}[a]"
        cmd2 = [
            str(ffmpeg), "-hide_banner", "-y",
            "-i", str(Path(video_path).resolve()),
            *loop_args, "-i", str(Path(bgm_path).resolve()),
            "-filter_complex", fc,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(Path(output_path).resolve()),
        ]
        result2 = subprocess.run(
            cmd2, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=7200,
        )
        if result2.returncode != 0 or not os.path.isfile(output_path):
            err = (result2.stderr or result.stderr or "混音失败")[-900:]
            raise RuntimeError(err)

    report(100.0, f"混音完成: {os.path.basename(output_path)}")
    return str(Path(output_path).resolve())
