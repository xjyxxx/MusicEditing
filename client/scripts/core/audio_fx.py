"""音频趣味效果：FFmpeg asetrate / atempo / areverse / apulsator / aecho。"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

ProgressFn = Callable[[float, str], None]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _find_ffmpeg() -> Path:
    root = _project_root()
    for p in (
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffmpeg.exe",
        root / "third_party" / "ffmpeg" / "x86" / "bin" / "ffmpeg.exe",
        root / "build_x64" / "bin" / "Release" / "ffmpeg.exe",
    ):
        if p.is_file():
            return p
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到 ffmpeg.exe")


@dataclass
class AudioFxParams:
    """可叠加的趣味音频参数。"""

    speed: float = 1.0          # 0.5～2.0（atempo，不改音高）
    pitch: float = 1.0          # 0.5～2.0（asetrate，改音高）
    reverse: bool = False
    spatial_8d: bool = False    # apulsator 伪 8D
    reverb: bool = False        # aecho 简单混响
    reverb_delay_ms: int = 600
    eight_d_hz: float = 0.125


def _atempo_chain(speed: float) -> List[str]:
    """atempo 单段限制约 0.5～2.0，超出则串联。"""
    s = max(0.25, min(4.0, float(speed)))
    parts: List[str] = []
    # 先处理 >2
    while s > 2.0 + 1e-6:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5 - 1e-6:
        parts.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-3:
        parts.append(f"atempo={s:.5f}")
    return parts


def build_af_filter(params: AudioFxParams) -> str:
    """组装 -af 滤镜链。"""
    filters: List[str] = []
    pitch = max(0.5, min(2.0, float(params.pitch)))
    speed = max(0.25, min(4.0, float(params.speed)))

    # 变调：改采样率再重采样回原率（时长会变，再与 atempo 配合）
    if abs(pitch - 1.0) > 1e-3:
        # 用相对写法：先 aformat 保证有采样率元数据
        filters.append(f"asetrate=44100*{pitch:.5f}")
        filters.append("aresample=44100")
        # asetrate 会使播放变快/慢，用 atempo 把时长拉回，只保留音高变化
        # 音高升高 pitch>1 → 时长变短 → atempo 再 /pitch 拉长
        compensate = 1.0 / pitch
        filters.extend(_atempo_chain(compensate))

    if abs(speed - 1.0) > 1e-3:
        filters.extend(_atempo_chain(speed))

    if params.reverse:
        filters.append("areverse")

    if params.spatial_8d:
        hz = max(0.05, min(2.0, float(params.eight_d_hz)))
        filters.append(f"apulsator=mode=sine:hz={hz:.4f}:width=0.9:amount=0.85")

    if params.reverb:
        d = max(50, min(2000, int(params.reverb_delay_ms)))
        # in_gain:out_gain:delays:decays
        filters.append(f"aecho=0.8:0.75:{d}|{int(d * 1.7)}:0.35|0.25")

    if not filters:
        return "anull"
    return ",".join(filters)


def apply_audio_fx(
    input_path: str,
    output_path: str,
    params: AudioFxParams,
    *,
    on_progress: Optional[ProgressFn] = None,
) -> str:
    """对音频或视频音轨应用趣味效果；视频保留画面（copy 视频轨）。"""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(input_path)
    ffmpeg = _find_ffmpeg()
    report = on_progress or (lambda _p, _m: None)
    af = build_af_filter(params)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    ext = Path(input_path).suffix.lower()
    is_video = ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v"}

    report(5.0, f"音频滤镜: {af}")
    cmd: List[str] = [
        str(ffmpeg), "-hide_banner", "-y",
        "-i", str(Path(input_path).resolve()),
        "-af", af,
    ]
    if is_video:
        cmd.extend([
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(Path(output_path).resolve()),
        ])
    else:
        out_ext = Path(output_path).suffix.lower()
        if out_ext in {".wav"}:
            cmd.extend(["-c:a", "pcm_s16le", str(Path(output_path).resolve())])
        else:
            # 默认 mp3 / m4a
            if out_ext in {".m4a", ".aac"}:
                cmd.extend(["-c:a", "aac", "-b:a", "192k", str(Path(output_path).resolve())])
            else:
                cmd.extend(["-c:a", "libmp3lame", "-q:a", "2", str(Path(output_path).resolve())])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    if result.returncode != 0 or not os.path.isfile(output_path):
        # 视频 copy 失败时整段重编码
        if is_video:
            report(40.0, "视频轨 copy 失败，改为重编码…")
            cmd2 = [
                str(ffmpeg), "-hide_banner", "-y",
                "-i", str(Path(input_path).resolve()),
                "-af", af,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                str(Path(output_path).resolve()),
            ]
            result2 = subprocess.run(
                cmd2, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=3600,
            )
            if result2.returncode != 0 or not os.path.isfile(output_path):
                raise RuntimeError((result2.stderr or result.stderr or "音频效果失败")[-800:])
        else:
            raise RuntimeError((result.stderr or "音频效果失败")[-800:])

    report(100.0, f"完成: {os.path.basename(output_path)}")
    return str(Path(output_path).resolve())


def describe_params(params: AudioFxParams) -> str:
    bits = []
    if abs(params.speed - 1.0) > 1e-3:
        bits.append(f"变速×{params.speed:.2f}")
    if abs(params.pitch - 1.0) > 1e-3:
        bits.append(f"变调×{params.pitch:.2f}")
    if params.reverse:
        bits.append("倒放")
    if params.spatial_8d:
        bits.append("8D")
    if params.reverb:
        bits.append("混响")
    return " · ".join(bits) if bits else "直通"


PRESETS: Sequence[tuple[str, AudioFxParams]] = (
    ("芯片鼠（升调）", AudioFxParams(pitch=1.35, speed=1.0)),
    ("低沉（降调）", AudioFxParams(pitch=0.75, speed=1.0)),
    ("加速 1.25×", AudioFxParams(speed=1.25)),
    ("慢放 0.8×", AudioFxParams(speed=0.8)),
    ("倒放", AudioFxParams(reverse=True)),
    ("8D 环绕", AudioFxParams(spatial_8d=True)),
    ("大厅混响", AudioFxParams(reverb=True, reverb_delay_ms=800)),
    ("8D+混响", AudioFxParams(spatial_8d=True, reverb=True)),
)
