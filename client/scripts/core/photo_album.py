"""Folder-native 相册描述：每个图库根目录携带一个轻量 JSON 文件。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ALBUM_FILE_NAME = ".musicediting.album.json"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AlbumDescriptor:
    schema_version: int
    title: str
    created_at: float
    updated_at: float
    cover_path: str = ""
    description: str = ""


def descriptor_path(root: str | Path) -> Path:
    return Path(root) / ALBUM_FILE_NAME


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _from_payload(payload: object, root: Path) -> AlbumDescriptor:
    if not isinstance(payload, dict):
        raise ValueError("相册描述文件不是 JSON 对象")
    if int(payload.get("schemaVersion", 0) or 0) != SCHEMA_VERSION:
        raise ValueError("相册描述文件版本不受支持")
    title = str(payload.get("title") or root.name or "未命名图库").strip()
    if not title:
        title = "未命名图库"
    return AlbumDescriptor(
        schema_version=SCHEMA_VERSION,
        title=title,
        created_at=float(payload.get("createdAt") or time.time()),
        updated_at=float(payload.get("updatedAt") or time.time()),
        cover_path=str(payload.get("coverPath") or ""),
        description=str(payload.get("description") or ""),
    )


def load_album(root: str | Path) -> AlbumDescriptor | None:
    folder = Path(root)
    path = descriptor_path(folder)
    if not path.is_file():
        return None
    try:
        return _from_payload(json.loads(path.read_text(encoding="utf-8")), folder)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def ensure_album(root: str | Path) -> AlbumDescriptor:
    """首次添加图库时创建描述文件；已有合法文件绝不覆盖。"""
    folder = Path(root).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("相册目录不存在")
    existing = load_album(folder)
    if existing is not None:
        return existing
    if descriptor_path(folder).exists():
        raise ValueError("相册描述文件无效或版本不受支持，未覆盖原文件")
    now = time.time()
    album = AlbumDescriptor(
        schema_version=SCHEMA_VERSION,
        title=folder.name or "未命名图库",
        created_at=now,
        updated_at=now,
    )
    save_album(folder, album)
    return album


def save_album(root: str | Path, album: AlbumDescriptor) -> AlbumDescriptor:
    folder = Path(root).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("相册目录不存在")
    now = time.time()
    saved = AlbumDescriptor(
        schema_version=SCHEMA_VERSION,
        title=(album.title or folder.name or "未命名图库").strip(),
        created_at=float(album.created_at or now),
        updated_at=now,
        cover_path=(album.cover_path or "").strip(),
        description=(album.description or "").strip(),
    )
    payload = {
        "schemaVersion": saved.schema_version,
        "title": saved.title,
        "createdAt": saved.created_at,
        "updatedAt": saved.updated_at,
        "coverPath": saved.cover_path,
        "description": saved.description,
    }
    _atomic_json_write(descriptor_path(folder), payload)
    return saved
