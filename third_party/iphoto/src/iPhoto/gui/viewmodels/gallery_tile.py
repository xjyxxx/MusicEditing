"""Immutable in-memory records consumed by Gallery tile painting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtGui import QImage, QPixmap

GalleryLoadingState = Literal["placeholder", "micro", "full"]


@dataclass(frozen=True, slots=True)
class GalleryTileRecord:
    asset_id: str
    abs_path: Path
    rel_path: Path
    media_type: str
    duration: float
    is_favorite: bool
    is_live: bool
    is_pano: bool

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"


@dataclass(frozen=True, slots=True)
class GalleryTileSnapshot:
    record: GalleryTileRecord | None
    micro_image: QImage | None
    full_pixmap: QPixmap | None
    loading_state: GalleryLoadingState
    is_current: bool = False


__all__ = ["GalleryLoadingState", "GalleryTileRecord", "GalleryTileSnapshot"]
