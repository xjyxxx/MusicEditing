"""高光缩略图小图缓存（磁盘 PPM，由 media_cli thumbnail 生成）。"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def cache_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "MusicEditing" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(video_path: str, timestamp_sec: float, max_width: int = 160) -> Path:
    abs_v = os.path.abspath(video_path)
    digest = hashlib.sha1(abs_v.encode("utf-8", errors="replace")).hexdigest()[:16]
    ts_ms = max(0, int(float(timestamp_sec) * 1000.0))
    # v2：修复 seek 时间基后的缓存命名，避免沿用旧黑帧 PPM
    return cache_dir() / f"{digest}_{ts_ms}_w{int(max_width)}_v2.ppm"


def is_fresh(path: Path, video_path: str) -> bool:
    if not path.is_file() or path.stat().st_size < 32:
        return False
    try:
        return path.stat().st_mtime >= os.path.getmtime(video_path)
    except OSError:
        return path.is_file()
