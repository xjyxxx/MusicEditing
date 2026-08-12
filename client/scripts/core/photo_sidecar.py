"""照片非破坏性编辑配方：原图旁路 JSON，不写入或重编码原始媒体。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

SIDECAR_SUFFIX = ".musicediting.photo.json"
SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {1, 2}


@dataclass(frozen=True)
class EditRecipe:
    master_light: float = 0.0
    master_color: float = 0.0
    exposure: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    temperature: float = 0.0
    perspective_horizontal: float = 0.0
    perspective_vertical: float = 0.0
    rotation: float = 0.0

    def normalized(self) -> "EditRecipe":
        return EditRecipe(
            master_light=max(-1.0, min(1.0, float(self.master_light))),
            master_color=max(-1.0, min(1.0, float(self.master_color))),
            exposure=max(-3.0, min(3.0, float(self.exposure))),
            contrast=max(-1.0, min(1.0, float(self.contrast))),
            saturation=max(-1.0, min(1.0, float(self.saturation))),
            temperature=max(-1.0, min(1.0, float(self.temperature))),
            perspective_horizontal=max(-1.0, min(1.0, float(self.perspective_horizontal))),
            perspective_vertical=max(-1.0, min(1.0, float(self.perspective_vertical))),
            rotation=max(-45.0, min(45.0, float(self.rotation))),
        )

    @property
    def is_identity(self) -> bool:
        value = self.normalized()
        return value == EditRecipe()


@dataclass(frozen=True)
class PhotoSidecar:
    schema_version: int
    source_path: str
    source_size: int
    source_mtime_ns: int
    updated_at: float
    recipe: EditRecipe


def sidecar_path(source: str | Path) -> Path:
    path = Path(source)
    return path.with_name(path.name + SIDECAR_SUFFIX)


def _source_state(source: str | Path) -> tuple[str, int, int]:
    path = Path(source).resolve()
    stat = path.stat()
    return str(path), int(stat.st_size), int(stat.st_mtime_ns)


def _atomic_write(path: Path, payload: dict) -> None:
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


def load_sidecar(source: str | Path) -> PhotoSidecar | None:
    sidecar = sidecar_path(source)
    if not sidecar.is_file():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        version = int(payload.get("schemaVersion", 0)) if isinstance(payload, dict) else 0
        if not isinstance(payload, dict) or version not in SUPPORTED_SCHEMA_VERSIONS:
            return None
        recipe_raw = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else {}
        source_raw = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        recipe = EditRecipe(
            master_light=float(recipe_raw.get("master_light", 0.0)),
            master_color=float(recipe_raw.get("master_color", 0.0)),
            exposure=float(recipe_raw.get("exposure", 0.0)),
            contrast=float(recipe_raw.get("contrast", 0.0)),
            saturation=float(recipe_raw.get("saturation", 0.0)),
            temperature=float(recipe_raw.get("temperature", 0.0)),
            perspective_horizontal=float(recipe_raw.get("perspective_horizontal", 0.0)),
            perspective_vertical=float(recipe_raw.get("perspective_vertical", 0.0)),
            rotation=float(recipe_raw.get("rotation", 0.0)),
        ).normalized()
        return PhotoSidecar(
            schema_version=version,
            source_path=str(source_raw.get("path") or ""),
            source_size=int(source_raw.get("size") or 0),
            source_mtime_ns=int(source_raw.get("mtimeNs") or 0),
            updated_at=float(payload.get("updatedAt") or 0.0),
            recipe=recipe,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def sidecar_is_current(source: str | Path, sidecar: PhotoSidecar | None = None) -> bool:
    entry = sidecar or load_sidecar(source)
    if entry is None:
        return False
    try:
        path, size, mtime_ns = _source_state(source)
    except OSError:
        return False
    return entry.source_path == path and entry.source_size == size and entry.source_mtime_ns == mtime_ns


def save_sidecar(source: str | Path, recipe: EditRecipe) -> PhotoSidecar:
    """原子保存配方；不改变输入文件字节。"""
    path, size, mtime_ns = _source_state(source)
    saved = PhotoSidecar(
        schema_version=SCHEMA_VERSION,
        source_path=path,
        source_size=size,
        source_mtime_ns=mtime_ns,
        updated_at=time.time(),
        recipe=recipe.normalized(),
    )
    payload = {
        "schemaVersion": saved.schema_version,
        "source": {"path": saved.source_path, "size": saved.source_size, "mtimeNs": saved.source_mtime_ns},
        "updatedAt": saved.updated_at,
        "recipe": asdict(saved.recipe),
    }
    _atomic_write(sidecar_path(path), payload)
    return saved


def remove_sidecar(source: str | Path) -> None:
    try:
        sidecar_path(source).unlink()
    except FileNotFoundError:
        pass


def sidecar_status(source: str | Path) -> tuple[bool, float]:
    """返回 (是否有有效非默认编辑, sidecar 修改时间)。"""
    sidecar = load_sidecar(source)
    path = sidecar_path(source)
    try:
        mtime = path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        mtime = 0.0
    return bool(sidecar and sidecar_is_current(source, sidecar) and not sidecar.recipe.is_identity), mtime
