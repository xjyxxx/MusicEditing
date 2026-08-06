"""音频趣味效果：FFmpeg asetrate / atempo / areverse / apulsator / aecho。

对视频文件时：变速/倒放会同步改视频时间轴（setpts / reverse），避免只改音轨导致音画不同步。
参考 FFmpeg 常见做法（与雷霄骅教程中的 PTS / 滤镜体系一致）：
  加速 speed：-vf setpts=PTS/speed  +  -af atempo=speed
  倒放：      -vf reverse         +  -af areverse
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

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


def _find_ffprobe(ffmpeg: Optional[Path] = None) -> Path:
    ff = ffmpeg or _find_ffmpeg()
    cand = ff.parent / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    if cand.is_file():
        return cand
    found = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到 ffprobe")


def _probe_json(path: str, ffmpeg: Optional[Path] = None) -> dict:
    probe = _find_ffprobe(ffmpeg)
    r = subprocess.run(
        [
            str(probe), "-v", "error",
            "-show_streams", "-show_format",
            "-of", "json",
            str(Path(path).resolve()),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    if r.returncode != 0 or not r.stdout:
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def _probe_audio_sample_rate(path: str, ffmpeg: Optional[Path] = None) -> int:
    """探测音轨采样率；失败回退 44100。"""
    try:
        data = _probe_json(path, ffmpeg)
        for s in data.get("streams") or []:
            if s.get("codec_type") == "audio":
                sr = int(s.get("sample_rate") or 0)
                if 8000 <= sr <= 384000:
                    return sr
    except Exception:
        pass
    return 44100


def _probe_video_fps(path: str, ffmpeg: Optional[Path] = None) -> float:
    """探测视频帧率；供 setpts 后 fps= 恒定化（h264_mf 需要 CFR）。"""
    try:
        data = _probe_json(path, ffmpeg)
        for s in data.get("streams") or []:
            if s.get("codec_type") != "video":
                continue
            for key in ("avg_frame_rate", "r_frame_rate"):
                raw = str(s.get(key) or "")
                if not raw or raw in {"0/0", "N/A"}:
                    continue
                if "/" in raw:
                    a, b = raw.split("/", 1)
                    num, den = float(a), float(b)
                    if den > 0 and 1.0 <= num / den <= 240.0:
                        return num / den
                else:
                    val = float(raw)
                    if 1.0 <= val <= 240.0:
                        return val
    except Exception:
        pass
    return 25.0


def _video_encoder_args() -> List[str]:
    """与 media_bridge 默认质量接近；避免在无 libx264 的捆绑包上失败。"""
    if sys.platform == "win32":
        return [
            "-c:v", "h264_mf", "-pix_fmt", "yuv420p",
            "-b:v", "8M", "-maxrate", "12M", "-bufsize", "16M",
        ]
    return ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "veryfast"]


@dataclass
class AudioFxParams:
    """可叠加的趣味音频参数。"""

    speed: float = 1.0          # 0.25～4.0（atempo，不改音高；视频同步 setpts）
    pitch: float = 1.0          # 0.5～2.0（asetrate，改音高；时长补偿后保持）
    reverse: bool = False
    spatial_8d: bool = False    # apulsator 伪 8D
    reverb: bool = False        # aecho 简单混响
    reverb_delay_ms: int = 600
    eight_d_hz: float = 0.125


def _atempo_chain(speed: float) -> List[str]:
    """atempo 单段限制约 0.5～2.0，超出则串联。"""
    s = max(0.25, min(4.0, float(speed)))
    parts: List[str] = []
    while s > 2.0 + 1e-6:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5 - 1e-6:
        parts.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-3:
        parts.append(f"atempo={s:.5f}")
    return parts


def build_af_filter(params: AudioFxParams, *, sample_rate: int = 44100) -> str:
    """组装 -af 滤镜链。sample_rate 用于 asetrate 变调，避免硬编码 44100。"""
    filters: List[str] = []
    pitch = max(0.5, min(2.0, float(params.pitch)))
    speed = max(0.25, min(4.0, float(params.speed)))
    sr = int(sample_rate) if sample_rate > 0 else 44100

    # 变调：改采样率再重采样回原率；再用 atempo 把时长拉回，只保留音高变化
    if abs(pitch - 1.0) > 1e-3:
        filters.append(f"asetrate={sr}*{pitch:.5f}")
        filters.append(f"aresample={sr}")
        filters.extend(_atempo_chain(1.0 / pitch))

    if abs(speed - 1.0) > 1e-3:
        filters.extend(_atempo_chain(speed))

    if params.reverse:
        filters.append("areverse")

    if params.spatial_8d:
        hz = max(0.05, min(2.0, float(params.eight_d_hz)))
        filters.append(f"apulsator=mode=sine:hz={hz:.4f}:width=0.9:amount=0.85")

    if params.reverb:
        d = max(50, min(2000, int(params.reverb_delay_ms)))
        filters.append(f"aecho=0.8:0.75:{d}|{int(d * 1.7)}:0.35|0.25")

    if not filters:
        return "anull"
    return ",".join(filters)


def build_vf_filter(
    params: AudioFxParams,
    *,
    fps: float = 25.0,
) -> Optional[str]:
    """视频时间轴滤镜：与音频 speed/reverse 对齐。

    - 加速 speed>1：画面时间变短 → setpts=PTS/speed
    - 减速 speed<1：画面时间变长 → setpts=PTS/speed
    - 倒放：reverse（须重编码，无法 copy）
    顺序与音频一致：先变速再倒放（均匀倍速下与先倒再变速等价）。
    末尾加 fps= 输出 CFR，避免 Windows h264_mf「could not set output type」。
    """
    filters: List[str] = []
    speed = max(0.25, min(4.0, float(params.speed)))
    if abs(speed - 1.0) > 1e-3:
        filters.append(f"setpts=PTS/{speed:.6f}")
    if params.reverse:
        filters.append("reverse")
    if not filters:
        return None
    rate = max(1.0, min(120.0, float(fps) or 25.0))
    # 用合理精度，避免滤镜解析问题
    if abs(rate - round(rate)) < 1e-3:
        filters.append(f"fps={int(round(rate))}")
    else:
        filters.append(f"fps={rate:.3f}")
    return ",".join(filters)


def needs_video_retiming(params: AudioFxParams) -> bool:
    """变速/倒放会改变时间轴，视频不能再 stream copy。"""
    return abs(float(params.speed) - 1.0) > 1e-3 or bool(params.reverse)


def _run_ffmpeg(cmd: List[str], timeout: int = 3600) -> Tuple[int, str]:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    err = (result.stderr or "")[-800:]
    return result.returncode, err


def apply_audio_fx(
    input_path: str,
    output_path: str,
    params: AudioFxParams,
    *,
    on_progress: Optional[ProgressFn] = None,
) -> str:
    """对音频或视频音轨应用趣味效果。

    视频：
    - 仅变调/8D/混响：视频轨 copy（时长不变）
    - 变速或倒放：视频 setpts/reverse 重编码，与音轨时长对齐
    - 混响尾音可能略长：加 -shortest，避免音轨拖过画面
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(input_path)
    ffmpeg = _find_ffmpeg()
    report = on_progress or (lambda _p, _m: None)
    sr = _probe_audio_sample_rate(input_path, ffmpeg)
    af = build_af_filter(params, sample_rate=sr)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    ext = Path(input_path).suffix.lower()
    is_video = ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v"}
    out = str(Path(output_path).resolve())
    inp = str(Path(input_path).resolve())
    fps = _probe_video_fps(input_path, ffmpeg) if is_video else 25.0
    vf = build_vf_filter(params, fps=fps) if is_video else None

    report(5.0, f"音频滤镜: {af}" + (f" | 视频: {vf}" if vf else ""))

    if not is_video:
        cmd: List[str] = [
            str(ffmpeg), "-hide_banner", "-y",
            "-i", inp,
            "-af", af,
        ]
        out_ext = Path(output_path).suffix.lower()
        if out_ext in {".wav"}:
            cmd.extend(["-c:a", "pcm_s16le", out])
        elif out_ext in {".m4a", ".aac"}:
            cmd.extend(["-c:a", "aac", "-b:a", "192k", out])
        else:
            cmd.extend(["-c:a", "libmp3lame", "-q:a", "2", out])
        code, err = _run_ffmpeg(cmd)
        if code != 0 or not os.path.isfile(output_path):
            raise RuntimeError(err or "音频效果失败")
        report(100.0, f"完成: {os.path.basename(output_path)}")
        return out

    # —— 视频路径 ——
    retiming = needs_video_retiming(params)
    # aecho 会在末尾留混响尾，-shortest 裁到较短轨，避免「有声无画」
    use_shortest = bool(params.reverb) or not retiming

    if retiming:
        assert vf is not None
        report(15.0, "变速/倒放：同步重编码视频时间轴…")
        rate_args = ["-r", f"{fps:.3f}".rstrip("0").rstrip(".") or "25"]
        enc_attempts: List[List[str]] = [
            [*_video_encoder_args()],
            ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20"],
            ["-c:v", "mpeg4", "-q:v", "5"],
        ]
        last_err = ""
        ok = False
        for i, enc in enumerate(enc_attempts):
            if i == 1:
                report(40.0, "视频重编码回退 libx264…")
            elif i == 2:
                report(55.0, "视频重编码回退 mpeg4…")
            cmd = [
                str(ffmpeg), "-hide_banner", "-y",
                "-i", inp,
                "-vf", vf,
                "-af", af,
                *enc,
                *rate_args,
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
            ]
            if use_shortest:
                cmd.append("-shortest")
            cmd.append(out)
            code, err = _run_ffmpeg(cmd)
            last_err = err
            if code == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                ok = True
                break
        if not ok:
            raise RuntimeError(last_err or "音频效果失败")
    else:
        # 时长不变：优先 copy 视频轨
        cmd = [
            str(ffmpeg), "-hide_banner", "-y",
            "-i", inp,
            "-af", af,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            out,
        ]
        code, err = _run_ffmpeg(cmd)
        if code != 0 or not os.path.isfile(output_path):
            report(40.0, "视频轨 copy 失败，改为重编码…")
            cmd2 = [
                str(ffmpeg), "-hide_banner", "-y",
                "-i", inp,
                "-af", af,
                *_video_encoder_args(),
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                out,
            ]
            code2, err2 = _run_ffmpeg(cmd2)
            if code2 != 0 or not os.path.isfile(output_path):
                raise RuntimeError(err2 or err or "音频效果失败")

    report(100.0, f"完成: {os.path.basename(output_path)}")
    return out


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
