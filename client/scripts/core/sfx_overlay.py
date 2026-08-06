"""梗音效叠加：本地短音效叠到视频指定时刻，支持倍数/音量。"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

ProgressFn = Callable[[float, str], None]

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def sfx_dirs() -> List[Path]:
    root = _project_root()
    return [
        root / "assets" / "sfx" / "user",
        root / "assets" / "sfx" / "demo",
    ]


def ensure_sfx_dirs() -> None:
    for d in sfx_dirs():
        d.mkdir(parents=True, exist_ok=True)


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


def ensure_demo_sfx() -> None:
    """生成几段免费演示音效（非版权梗音）；用户梗音请放 user/。"""
    ensure_sfx_dirs()
    demo = sfx_dirs()[1]
    specs = [
        ("叮一声.wav", "sine=frequency=880:duration=0.18", 0.5),
        ("鼓点咚.wav", "sine=frequency=90:duration=0.22", 0.8),
        ("滑稽升调.wav", "sine=frequency=320:duration=0.35", 0.55),
    ]
    try:
        ffmpeg = _find_ffmpeg()
    except FileNotFoundError:
        return
    for name, aeval, vol in specs:
        out = demo / name
        if out.is_file():
            continue
        cmd = [
            str(ffmpeg), "-hide_banner", "-y",
            "-f", "lavfi", "-i", aeval,
            "-af", f"volume={vol},afade=t=out:st=0.12:d=0.08",
            str(out),
        ]
        subprocess.run(cmd, capture_output=True, timeout=30)


@dataclass
class SfxItem:
    path: str
    name: str
    source: str  # user | demo


def list_sfx_library() -> List[SfxItem]:
    ensure_sfx_dirs()
    ensure_demo_sfx()
    items: List[SfxItem] = []
    seen = set()
    for d, src in ((sfx_dirs()[0], "user"), (sfx_dirs()[1], "demo")):
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.suffix.lower() not in AUDIO_EXTS:
                continue
            key = os.path.normcase(str(p.resolve()))
            if key in seen:
                continue
            seen.add(key)
            items.append(SfxItem(path=str(p.resolve()), name=p.name, source=src))
    return items


@dataclass
class SfxOverlayParams:
    """把短音效叠到成片指定时刻。"""

    start_sec: float = 0.0
    speed: float = 1.0  # 倍数 0.5~4
    sfx_volume: float = 1.2
    voice_volume: float = 1.0
    duck_voice: bool = False  # 叠加瞬间略压原声


def _atempo_chain(speed: float) -> str:
    """FFmpeg atempo 单级仅支持 0.5~2.0，超出则串联。"""
    s = max(0.25, min(4.0, float(speed)))
    if abs(s - 1.0) < 1e-3:
        return ""
    parts: list[str] = []
    while s > 2.0 + 1e-6:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5 - 1e-6:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def overlay_sfx(
    video_path: str,
    sfx_path: str,
    output_path: str,
    params: Optional[SfxOverlayParams] = None,
    *,
    on_progress: Optional[ProgressFn] = None,
) -> str:
    """视频画面 copy，音轨 = 原声 + 延迟后的梗音效（可变速）。"""
    params = params or SfxOverlayParams()
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    if not os.path.isfile(sfx_path):
        raise FileNotFoundError(sfx_path)

    ffmpeg = _find_ffmpeg()
    report = on_progress or (lambda _p, _m: None)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    start = max(0.0, float(params.start_sec))
    delay_ms = int(round(start * 1000))
    speed = max(0.25, min(4.0, float(params.speed)))
    sv = max(0.0, min(3.0, float(params.sfx_volume)))
    vv = max(0.0, min(2.0, float(params.voice_volume)))
    if params.duck_voice:
        vv = min(vv, 0.55)

    tempo = _atempo_chain(speed)
    sfx_af = []
    if tempo:
        sfx_af.append(tempo)
    sfx_af.append(f"volume={sv:.4f}")
    sfx_af.append(f"adelay={delay_ms}|{delay_ms}")
    sfx_chain = ",".join(sfx_af)

    report(8.0, f"叠加音效 @ {start:.2f}s · {speed:.2f}×")

    fc = (
        f"[0:a]volume={vv:.4f}[va];"
        f"[1:a]{sfx_chain}[sa];"
        f"[va][sa]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )
    cmd = [
        str(ffmpeg), "-hide_banner", "-y",
        "-i", str(Path(video_path).resolve()),
        "-i", str(Path(sfx_path).resolve()),
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
        report(40.0, "原声混音失败，改为仅叠音效轨…")
        fc2 = f"[1:a]{sfx_chain},apad[a]"
        cmd2 = [
            str(ffmpeg), "-hide_banner", "-y",
            "-i", str(Path(video_path).resolve()),
            "-i", str(Path(sfx_path).resolve()),
            "-filter_complex", fc2,
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
            err = (result2.stderr or result.stderr or "音效叠加失败")[-900:]
            raise RuntimeError(err)

    report(100.0, f"音效完成: {os.path.basename(output_path)}")
    return str(Path(output_path).resolve())
