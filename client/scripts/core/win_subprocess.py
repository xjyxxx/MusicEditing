"""Windows：隐藏子进程控制台窗口（避免从 pythonw/GUI 拉起 media_cli/ffmpeg 时狂闪黑框）。

开发时用带控制台的 python.exe 往往不明显；便携包用 pythonw.exe 时每个
subprocess 都会闪一下，界面也会跟着卡。
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

# Win32：与 CREATE_NEW_CONSOLE 互斥；有新建控制台需求时不要加 NO_WINDOW
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_CONSOLE = 0x00000010


def hide_console_kwargs(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """合并进 subprocess.run / Popen 的 kwargs。非 Windows 原样返回。"""
    out: dict[str, Any] = dict(extra or {})
    if sys.platform != "win32":
        return out
    flags = int(out.get("creationflags", 0) or 0)
    if flags & _CREATE_NEW_CONSOLE:
        return out
    out["creationflags"] = flags | getattr(
        subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW
    )
    return out


def install_hidden_console_patch() -> None:
    """猴子补丁：默认给 run/Popen 加上 CREATE_NO_WINDOW（可被显式 CREATE_NEW_CONSOLE 覆盖）。"""
    if sys.platform != "win32":
        return
    if getattr(subprocess, "_music_hide_console_patched", False):
        return

    _orig_run = subprocess.run
    _orig_popen = subprocess.Popen

    def run(*args: Any, **kwargs: Any):
        return _orig_run(*args, **hide_console_kwargs(kwargs))

    class Popen(_orig_popen):  # type: ignore[valid-type,misc]
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **hide_console_kwargs(kwargs))

    subprocess.run = run  # type: ignore[assignment]
    subprocess.Popen = Popen  # type: ignore[misc,assignment]
    subprocess._music_hide_console_patched = True  # type: ignore[attr-defined]
