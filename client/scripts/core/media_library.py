"""本地素材库：索引 output_dir / 自选根目录。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class MediaItem:
    path: str
    name: str
    kind: str  # video | image
    size_bytes: int = 0
    mtime: float = 0.0


def iter_media_files(root: str, *, recursive: bool = True, limit: int = 500) -> List[MediaItem]:
    if not root or not os.path.isdir(root):
        return []
    items: List[MediaItem] = []
    root_path = Path(root)
    if recursive:
        paths: Iterable[Path] = root_path.rglob("*")
    else:
        paths = root_path.iterdir()
    for p in paths:
        if len(items) >= limit:
            break
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in VIDEO_EXTS:
            kind = "video"
        elif ext in IMAGE_EXTS:
            kind = "image"
        else:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        items.append(MediaItem(
            path=str(p.resolve()),
            name=p.name,
            kind=kind,
            size_bytes=int(st.st_size),
            mtime=float(st.st_mtime),
        ))
    items.sort(key=lambda m: m.mtime, reverse=True)
    return items


def default_library_roots(output_dir: str = "") -> List[str]:
    roots: List[str] = []
    if output_dir and os.path.isdir(output_dir):
        roots.append(output_dir)
    # 常见默认输出
    here = Path(__file__).resolve().parent.parent.parent.parent
    for cand in (here / "output", here / "exports"):
        if cand.is_dir() and str(cand) not in roots:
            roots.append(str(cand))
    return roots
