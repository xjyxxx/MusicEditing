"""结构化照片元数据读取；优先批量 ExifTool，缺失时降级为文件属性。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

_DATE_RE = re.compile(r"^(\d{4})[-:](\d{2})[-:](\d{2})[ T](\d{2}):(\d{2}):(\d{2})")


@dataclass(frozen=True)
class PhotoMetadata:
    captured_at: float = 0.0
    latitude: float | None = None
    longitude: float | None = None
    camera: str = ""
    width: int = 0
    height: int = 0
    content_identifier: str = ""


def _as_float(value: object) -> float | None:
    try:
        number = float(value)
        return number if -180.0 <= number <= 180.0 else None
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _timestamp(value: object, fallback: float) -> float:
    match = _DATE_RE.match(str(value or "").strip())
    if not match:
        return fallback
    try:
        return datetime(*[int(part) for part in match.groups()]).timestamp()
    except ValueError:
        return fallback


def _metadata_from_row(row: dict, fallback: float) -> PhotoMetadata:
    make = str(row.get("Make") or "").strip()
    model = str(row.get("Model") or "").strip()
    camera = " ".join(value for value in (make, model) if value).strip()
    lat = _as_float(row.get("GPSLatitude"))
    lon = _as_float(row.get("GPSLongitude"))
    # 坐标必须成对出现；单独一个值可能是损坏/不完整标签。
    if lat is None or lon is None:
        lat = lon = None
    captured = _timestamp(
        row.get("DateTimeOriginal") or row.get("CreateDate") or row.get("MediaCreateDate"),
        fallback,
    )
    return PhotoMetadata(
        captured_at=captured,
        latitude=lat,
        longitude=lon,
        camera=camera,
        width=_as_int(row.get("ImageWidth") or row.get("ExifImageWidth")),
        height=_as_int(row.get("ImageHeight") or row.get("ExifImageHeight")),
        content_identifier=str(
            row.get("ContentIdentifier") or row.get("Apple:ContentIdentifier") or ""
        ).strip(),
    )


def _fallback(path: str) -> PhotoMetadata:
    try:
        return PhotoMetadata(captured_at=os.path.getmtime(path))
    except OSError:
        return PhotoMetadata()


def _chunks(values: list[str], size: int = 128) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def read_photo_metadata(paths: Iterable[str], timeout: int = 90) -> dict[str, PhotoMetadata]:
    """批量读取元数据。ExifTool 不可用或单批失败时保持可用的文件时间降级。"""
    files = [str(Path(path).resolve()) for path in paths if os.path.isfile(path)]
    results = {path: _fallback(path) for path in files}
    if not files:
        return results
    try:
        from core.media_bridge import _find_exiftool
        exiftool = _find_exiftool()
    except Exception:
        return results

    for batch in _chunks(files):
        command = [
            str(exiftool), "-j", "-n", "-charset", "filename=utf8", "-e",
            "-DateTimeOriginal", "-CreateDate", "-MediaCreateDate",
            "-GPSLatitude", "-GPSLongitude", "-Make", "-Model",
            "-ImageWidth", "-ImageHeight", "-ExifImageWidth", "-ExifImageHeight",
            "-ContentIdentifier", "-Apple:ContentIdentifier", *batch,
        ]
        try:
            process = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
            )
            if process.returncode != 0 or not process.stdout.strip():
                continue
            rows = json.loads(process.stdout)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                source = str(row.get("SourceFile") or "")
                if not source:
                    continue
                path = str(Path(source).resolve())
                if path in results:
                    results[path] = _metadata_from_row(row, results[path].captured_at)
        except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
            continue
    return results
