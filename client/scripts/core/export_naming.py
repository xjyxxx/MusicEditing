"""导出命名规范：统一成片 / 片段 / 发布包文件名。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional


_SAFE = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)


def sanitize_stem(name: str, *, fallback: str = "export") -> str:
    s = (name or "").strip()
    if not s:
        s = fallback
    s = _SAFE.sub("_", s).strip("._")
    return (s[:80] or fallback)


def timestamp_tag(when: Optional[datetime] = None) -> str:
    return (when or datetime.now()).strftime("%Y%m%d_%H%M%S")


def build_export_name(
    source_path: str,
    *,
    kind: str = "highlight",
    preset: str = "custom",
    index: int | None = None,
    ext: str = "mp4",
    when: Optional[datetime] = None,
) -> str:
    """
    规范名：{源名}_{kind}[_{preset}][_NNN]_{时间}.{ext}

    kind: highlight | vertical | compact | merged | cover | topic
    preset: custom | douyin_vertical | bilibili_vertical | kuaishou_vertical
    """
    stem = sanitize_stem(Path(source_path).stem)
    parts = [stem, sanitize_stem(kind, fallback="clip")]
    preset_l = (preset or "custom").strip().lower()
    if preset_l and preset_l not in ("custom", "none", ""):
        short = {
            "douyin_vertical": "dy",
            "bilibili_vertical": "bili",
            "kuaishou_vertical": "ks",
        }.get(preset_l, sanitize_stem(preset_l)[:12])
        parts.append(short)
    if index is not None:
        parts.append(f"{int(index):03d}")
    parts.append(timestamp_tag(when))
    ext = (ext or "mp4").lstrip(".")
    return "_".join(parts) + f".{ext}"


def default_merged_name(source_path: str, *, preset: str = "custom", ext: str = "mp4") -> str:
    return build_export_name(source_path, kind="merged", preset=preset, ext=ext)


def default_vertical_name(source_path: str, *, preset: str = "douyin_vertical", ext: str = "mp4") -> str:
    return build_export_name(source_path, kind="vertical", preset=preset, ext=ext)


def default_clip_name(
    source_path: str,
    index: int,
    *,
    preset: str = "custom",
    ext: str = "mp4",
) -> str:
    return build_export_name(
        source_path, kind="highlight", preset=preset, index=index, ext=ext,
    )
