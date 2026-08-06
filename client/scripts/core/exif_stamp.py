"""用 ExifTool 写入图片署名（Artist / Comment / Copyright）。"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def find_exiftool() -> Path:
    root = _project_root()
    for p in (
        root / "third_party" / "exiftool" / "exiftool.exe",
        root / "build_x64" / "bin" / "Release" / "exiftool.exe",
        root / "build" / "bin" / "Release" / "exiftool.exe",
    ):
        if p.is_file():
            return p
    found = shutil.which("exiftool") or shutil.which("exiftool.exe")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "未找到 exiftool.exe。请运行 scripts\\download_exiftool.bat"
    )


@dataclass
class ExifStamp:
    artist: str = ""
    comment: str = ""
    copyright: str = ""
    title: str = ""


def stamp_exif(
    image_path: str,
    stamp: ExifStamp,
    *,
    output_path: Optional[str] = None,
) -> str:
    """
    写入 EXIF/XMP 常用署名字段。
    若指定 output_path 且不同于输入，则先复制再写（避免破坏原图）。
    """
    src = Path(image_path)
    if not src.is_file():
        raise FileNotFoundError(image_path)

    dest = Path(output_path) if output_path else src
    if dest.resolve() != src.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    et = find_exiftool()
    cmd = [
        str(et),
        "-overwrite_original",
        "-charset", "filename=utf8",
        "-charset", "exif=utf8",
        "-charset", "iptc=utf8",
    ]
    if stamp.artist.strip():
        cmd.append(f"-Artist={stamp.artist.strip()}")
        cmd.append(f"-XPAuthor={stamp.artist.strip()}")
    if stamp.title.strip():
        cmd.append(f"-ImageDescription={stamp.title.strip()}")
        cmd.append(f"-XPTitle={stamp.title.strip()}")
    if stamp.comment.strip():
        cmd.append(f"-UserComment={stamp.comment.strip()}")
        cmd.append(f"-XPComment={stamp.comment.strip()}")
    if stamp.copyright.strip():
        cmd.append(f"-Copyright={stamp.copyright.strip()}")
        cmd.append(f"-XPKeywords={stamp.copyright.strip()}")

    # 至少写一个字段
    if len(cmd) <= 5:
        raise ValueError("请至少填写作者、作品名、备注或版权之一")

    cmd.append(str(dest.resolve()))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or f"exiftool exit {proc.returncode}")
    return str(dest.resolve())
