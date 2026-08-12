"""照片图库服务：隔离 UI 与 SQLite、sidecar、FFmpeg/媒体桥接。"""

from __future__ import annotations

from collections.abc import Sequence

from core.photo_library_index import PhotoAsset, PhotoLibraryIndex


class PhotoLibraryService:
    def __init__(self, bridge=None, index: PhotoLibraryIndex | None = None):
        self.bridge = bridge
        self.index = index or PhotoLibraryIndex()

    def roots(self) -> list[str]:
        return self.index.roots()

    def albums(self) -> list[tuple[str, str]]:
        return self.index.albums()

    def add_root(self, root: str) -> str:
        return self.index.add_root(root)

    def remove_root(self, root: str) -> None:
        self.index.remove_root(root)

    def scan(self, roots: Sequence[str], token=None) -> tuple[int, int]:
        cancelled = (lambda: bool(token and token.cancelled))
        return self.index.scan(roots, cancelled=cancelled)

    def query(self, section: str, text: str = "", limit: int = 600) -> list[PhotoAsset]:
        return self.index.assets(section, text, limit)

    def set_favorite(self, path: str, favorite: bool) -> None:
        self.index.set_favorite(path, favorite)

    def refresh_edit(self, path: str) -> None:
        self.index.refresh_sidecar(path)

    def video_thumbnail(self, path: str, max_width: int = 240) -> str:
        if self.bridge is None:
            raise RuntimeError("媒体引擎未加载")
        return self.bridge.extract_thumbnail(path, 0.0, max_width=max_width)
