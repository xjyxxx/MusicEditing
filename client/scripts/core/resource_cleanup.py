"""临时帧 / 队列产物清理与体积上限。"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


# 进程崩溃后可能残留的临时目录前缀
TEMP_PREFIXES = (
    "music_sr_",
    "music_wm_",
    "me_player_",
    "me_lut_",
    "me_ebur_",
    "me_cover_",
    "music_preview_",
    "me_rife_",
    "me_echo_",
    "me_face_",
    "me_vertical_",
)


def dir_size_bytes(path: str | Path) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    total = 0
    if root.is_file():
        try:
            return int(root.stat().st_size)
        except OSError:
            return 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                total += int(fp.stat().st_size)
            except OSError:
                pass
    return total


def format_bytes(n: int) -> str:
    x = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024.0 or unit == "TB":
            return f"{x:.1f} {unit}" if unit != "B" else f"{int(x)} B"
        x /= 1024.0
    return f"{n} B"


def cleanup_orphan_temp_dirs(
    *,
    prefixes: Sequence[str] = TEMP_PREFIXES,
    max_age_hours: float = 6.0,
    dry_run: bool = False,
) -> List[Tuple[str, int]]:
    """
    清理系统临时目录下超龄的 music_sr_* / me_player_* 等残留。
    返回 [(路径, 释放字节)]。
    """
    tmp = Path(tempfile.gettempdir())
    now = time.time()
    max_age_sec = max(0.0, float(max_age_hours)) * 3600.0
    freed: List[Tuple[str, int]] = []
    try:
        entries = list(tmp.iterdir())
    except OSError:
        return freed

    for p in entries:
        try:
            if not p.is_dir():
                continue
            name = p.name
            if not any(name.startswith(pref) for pref in prefixes):
                continue
            age = now - p.stat().st_mtime
            if age < max_age_sec:
                continue
            size = dir_size_bytes(p)
            if not dry_run:
                shutil.rmtree(p, ignore_errors=True)
            if not p.exists() or dry_run:
                freed.append((str(p), size))
        except OSError:
            continue
    return freed


def enforce_output_quota(
    root: str | Path,
    *,
    max_gb: float = 20.0,
    delete_oldest: bool = True,
) -> Tuple[int, List[str]]:
    """
    若 output 根目录超过 max_gb，按 mtime 从旧到新删除文件直到达标。
    返回 (删除字节数, 删除路径列表)。不删正在写入的锁文件；只删常见媒体产物。
    max_gb<=0 表示不限制。
    """
    if max_gb is None or float(max_gb) <= 0:
        return 0, []
    root_p = Path(root)
    if not root_p.is_dir():
        return 0, []

    limit = int(float(max_gb) * (1024 ** 3))
    current = dir_size_bytes(root_p)
    if current <= limit:
        return 0, []

    # 收集可删文件（视频/图/草稿）
    exts = {
        ".mp4", ".mov", ".mkv", ".webm", ".avi",
        ".png", ".jpg", ".jpeg", ".txt", ".ass", ".json",
    }
    files: List[Tuple[float, Path, int]] = []
    for dirpath, _dns, filenames in os.walk(root_p):
        for name in filenames:
            fp = Path(dirpath) / name
            if fp.suffix.lower() not in exts:
                continue
            try:
                st = fp.stat()
                files.append((st.st_mtime, fp, int(st.st_size)))
            except OSError:
                pass
    files.sort(key=lambda x: x[0])  # 旧→新

    deleted_bytes = 0
    deleted_paths: List[str] = []
    if not delete_oldest:
        return 0, []

    for _mtime, fp, size in files:
        if current - deleted_bytes <= limit:
            break
        try:
            fp.unlink(missing_ok=True)
            deleted_bytes += size
            deleted_paths.append(str(fp))
        except OSError:
            continue
    return deleted_bytes, deleted_paths


def quota_status(root: str | Path, max_gb: float) -> dict:
    used = dir_size_bytes(root)
    limit = int(float(max_gb) * (1024 ** 3)) if max_gb and max_gb > 0 else 0
    return {
        "root": str(root),
        "used_bytes": used,
        "used_human": format_bytes(used),
        "limit_bytes": limit,
        "limit_human": format_bytes(limit) if limit else "不限制",
        "over": bool(limit and used > limit),
    }
