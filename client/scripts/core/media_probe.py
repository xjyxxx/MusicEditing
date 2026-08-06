"""本地媒体码流探测（ffprobe）— VideoEye 精简版数据源。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def find_ffprobe() -> Path:
    root = _project_root()
    for p in (
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffprobe.exe",
        root / "third_party" / "ffmpeg" / "x86" / "bin" / "ffprobe.exe",
        root / "build_x64" / "bin" / "Release" / "ffprobe.exe",
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffmpeg.exe",
    ):
        if p.name.lower().startswith("ffmpeg"):
            cand = p.parent / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
            if cand.is_file():
                return cand
        elif p.is_file():
            return p
    # 与 ffmpeg 同目录
    for name in ("ffmpeg.exe", "ffmpeg"):
        found = shutil.which(name)
        if found:
            cand = Path(found).parent / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
            if cand.is_file():
                return cand
    found = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到 ffprobe.exe")


def _parse_rate(raw: str) -> Optional[float]:
    if not raw or raw in {"0/0", "N/A"}:
        return None
    try:
        if "/" in raw:
            a, b = raw.split("/", 1)
            num, den = float(a), float(b)
            if den > 0:
                return num / den
        return float(raw)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _fmt_bitrate(bps: Optional[int]) -> str:
    if not bps or bps <= 0:
        return "—"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    if bps >= 1000:
        return f"{bps / 1000:.0f} kbps"
    return f"{bps} bps"


def _fmt_duration(sec: Optional[float]) -> str:
    if sec is None or sec < 0:
        return "—"
    s = int(sec)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d} ({sec:.3f}s)"
    return f"{m}:{s:02d} ({sec:.3f}s)"


def _fmt_size(n: Optional[int]) -> str:
    if not n or n <= 0:
        return "—"
    if n >= 1024 ** 3:
        return f"{n / (1024 ** 3):.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / (1024 ** 2):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


@dataclass
class StreamInfo:
    index: int = 0
    codec_type: str = ""
    codec_name: str = ""
    profile: str = ""
    width: int = 0
    height: int = 0
    pix_fmt: str = ""
    fps: Optional[float] = None
    sample_rate: int = 0
    channels: int = 0
    channel_layout: str = ""
    bit_rate: Optional[int] = None
    duration: Optional[float] = None
    language: str = ""

    def summary_line(self) -> str:
        if self.codec_type == "video":
            res = f"{self.width}x{self.height}" if self.width and self.height else "?"
            fps = f"{self.fps:.3f} fps" if self.fps else "— fps"
            return (
                f"视频#{self.index} {self.codec_name or '?'} {res} {fps} "
                f"{self.pix_fmt or ''} {_fmt_bitrate(self.bit_rate)}"
            ).strip()
        if self.codec_type == "audio":
            ch = self.channel_layout or (f"{self.channels}ch" if self.channels else "")
            sr = f"{self.sample_rate} Hz" if self.sample_rate else ""
            return (
                f"音频#{self.index} {self.codec_name or '?'} {sr} {ch} "
                f"{_fmt_bitrate(self.bit_rate)}"
            ).strip()
        return f"{self.codec_type}#{self.index} {self.codec_name or '?'}"


@dataclass
class MediaProbeResult:
    path: str = ""
    format_name: str = ""
    format_long_name: str = ""
    duration: Optional[float] = None
    size: Optional[int] = None
    bit_rate: Optional[int] = None
    streams: List[StreamInfo] = field(default_factory=list)
    raw_error: str = ""

    @property
    def video(self) -> Optional[StreamInfo]:
        for s in self.streams:
            if s.codec_type == "video":
                return s
        return None

    @property
    def audio(self) -> Optional[StreamInfo]:
        for s in self.streams:
            if s.codec_type == "audio":
                return s
        return None

    def rows(self) -> List[Tuple[str, str]]:
        """UI 键值表。"""
        rows: List[Tuple[str, str]] = [
            ("文件", self.path),
            ("封装", self.format_long_name or self.format_name or "—"),
            ("时长", _fmt_duration(self.duration)),
            ("文件大小", _fmt_size(self.size)),
            ("总码率", _fmt_bitrate(self.bit_rate)),
        ]
        v = self.video
        if v:
            rows.extend([
                ("视频编码", f"{v.codec_name}" + (f" ({v.profile})" if v.profile else "")),
                ("分辨率", f"{v.width}x{v.height}" if v.width else "—"),
                ("帧率", f"{v.fps:.3f}" if v.fps else "—"),
                ("像素格式", v.pix_fmt or "—"),
                ("视频码率", _fmt_bitrate(v.bit_rate)),
            ])
        else:
            rows.append(("视频", "无"))
        a = self.audio
        if a:
            rows.extend([
                ("音频编码", a.codec_name or "—"),
                ("采样率", f"{a.sample_rate} Hz" if a.sample_rate else "—"),
                ("声道", a.channel_layout or (str(a.channels) if a.channels else "—")),
                ("音频码率", _fmt_bitrate(a.bit_rate)),
                ("语言", a.language or "—"),
            ])
        else:
            rows.append(("音频", "无"))
        extra = [s for s in self.streams if s.codec_type not in ("video", "audio")]
        for s in extra:
            rows.append((f"其他流#{s.index}", s.summary_line()))
        if self.raw_error:
            rows.append(("探测备注", self.raw_error))
        return rows

    def summary_text(self) -> str:
        lines = [f"{k}: {v}" for k, v in self.rows()]
        return "\n".join(lines)

    def tooltip_line(self) -> str:
        parts = []
        if self.format_name:
            parts.append(self.format_name)
        v = self.video
        if v and v.width:
            parts.append(f"{v.width}x{v.height}")
            if v.codec_name:
                parts.append(v.codec_name)
            if v.fps:
                parts.append(f"{v.fps:.2f}fps")
        a = self.audio
        if a and a.codec_name:
            parts.append(a.codec_name)
        if self.bit_rate:
            parts.append(_fmt_bitrate(self.bit_rate))
        return " · ".join(parts) if parts else os.path.basename(self.path or "")


def _stream_from_dict(s: dict) -> StreamInfo:
    tags = s.get("tags") or {}
    lang = str(tags.get("language") or tags.get("LANGUAGE") or "")
    br = s.get("bit_rate")
    try:
        bit_rate = int(br) if br not in (None, "N/A", "") else None
    except (TypeError, ValueError):
        bit_rate = None
    dur = s.get("duration")
    try:
        duration = float(dur) if dur not in (None, "N/A", "") else None
    except (TypeError, ValueError):
        duration = None
    fps = _parse_rate(str(s.get("avg_frame_rate") or "")) or _parse_rate(
        str(s.get("r_frame_rate") or "")
    )
    return StreamInfo(
        index=int(s.get("index") or 0),
        codec_type=str(s.get("codec_type") or ""),
        codec_name=str(s.get("codec_name") or ""),
        profile=str(s.get("profile") or ""),
        width=int(s.get("width") or 0),
        height=int(s.get("height") or 0),
        pix_fmt=str(s.get("pix_fmt") or ""),
        fps=fps,
        sample_rate=int(s.get("sample_rate") or 0),
        channels=int(s.get("channels") or 0),
        channel_layout=str(s.get("channel_layout") or ""),
        bit_rate=bit_rate,
        duration=duration,
        language=lang,
    )


def probe_media(path: str) -> MediaProbeResult:
    """对本地文件跑 ffprobe，返回结构化结果。"""
    result = MediaProbeResult(path=str(Path(path).resolve()) if path else "")
    if not path or not os.path.isfile(path):
        result.raw_error = "文件不存在"
        return result
    try:
        probe = find_ffprobe()
    except FileNotFoundError as e:
        result.raw_error = str(e)
        return result

    try:
        r = subprocess.run(
            [
                str(probe), "-v", "error",
                "-show_format", "-show_streams",
                "-of", "json",
                str(Path(path).resolve()),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        result.raw_error = "ffprobe 超时"
        return result
    except OSError as e:
        result.raw_error = str(e)
        return result

    if r.returncode != 0 or not (r.stdout or "").strip():
        result.raw_error = (r.stderr or "ffprobe 失败")[-400:]
        return result

    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        result.raw_error = "ffprobe JSON 解析失败"
        return result

    fmt = data.get("format") or {}
    result.format_name = str(fmt.get("format_name") or "")
    result.format_long_name = str(fmt.get("format_long_name") or "")
    try:
        result.duration = float(fmt["duration"]) if fmt.get("duration") else None
    except (TypeError, ValueError, KeyError):
        result.duration = None
    try:
        result.size = int(fmt["size"]) if fmt.get("size") else None
    except (TypeError, ValueError, KeyError):
        result.size = None
    try:
        result.bit_rate = int(fmt["bit_rate"]) if fmt.get("bit_rate") else None
    except (TypeError, ValueError, KeyError):
        result.bit_rate = None

    for s in data.get("streams") or []:
        if isinstance(s, dict):
            result.streams.append(_stream_from_dict(s))
    return result
