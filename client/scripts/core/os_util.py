"""系统级小工具（打开资源管理器等）。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def reveal_in_explorer(path: str | Path) -> bool:
    """在资源管理器中打开并尽量选中文件；目录则直接打开。失败返回 False。"""
    p = Path(path) if path else None
    if p is None:
        return False
    try:
        if p.is_file():
            subprocess.run(
                ["explorer", "/select,", str(p.resolve())],
                check=False,
            )
            return True
        folder = p if p.is_dir() else p.parent
        if folder.is_dir():
            os.startfile(str(folder))  # type: ignore[attr-defined]
            return True
    except Exception:
        try:
            os.startfile(str(p.parent if p.is_file() else p))  # type: ignore[attr-defined]
            return True
        except Exception:
            return False
    return False
