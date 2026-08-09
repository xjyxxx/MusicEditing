"""回归短测公共：找测试视频 / 引擎 / ffmpeg。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def ensure_scripts_path() -> Path:
    scripts = project_root() / "client" / "scripts"
    s = str(scripts)
    if s not in sys.path:
        sys.path.insert(0, s)
    return scripts


def find_test_video() -> Path | None:
    root = project_root()
    tests = root / "tests"
    for name in ("test_video.mp4", "222222.mp4"):
        p = tests / name
        if p.is_file():
            return p
    if not tests.is_dir():
        return None
    for p in sorted(tests.iterdir()):
        if p.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi"} and p.is_file():
            return p
    return None


def find_ffmpeg() -> Path | None:
    root = project_root()
    for p in (
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffmpeg.exe",
        root / "third_party" / "ffmpeg" / "bin" / "ffmpeg.exe",
    ):
        if p.is_file():
            return p
    which = shutil_which("ffmpeg")
    return Path(which) if which else None


def shutil_which(cmd: str) -> str | None:
    import shutil
    return shutil.which(cmd)


def find_media_cli() -> Path | None:
    root = project_root()
    for p in (
        root / "build_x64" / "bin" / "Release" / "media_cli.exe",
        root / "build" / "bin" / "Release" / "media_cli.exe",
    ):
        if p.is_file():
            return p
    return None


def find_media_player() -> Path | None:
    root = project_root()
    for p in (
        root / "build_x64" / "bin" / "Release" / "media_player.exe",
        root / "build" / "bin" / "Release" / "media_player.exe",
    ):
        if p.is_file():
            return p
    return None


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def fail(msg: str) -> None:
    print(f"FAIL  {msg}")
