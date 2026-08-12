"""嵌入 MusicEditing 时使用的软件大图预览（避开 QRhi 空白）。

PlayerViewController 仍按 GLImageViewer 接口调用；本类用 QPixmap 绘制，
调色结果由上游 worker 已烘焙进 QImage，无需 GPU shader。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

from .image_viewer import ImageViewer


class SoftImageViewer(ImageViewer):
    """``ImageViewer`` + 兼容 ``GLImageViewer`` 的最小 API 面。"""

    firstFrameReady = Signal()
    viewTransformChanged = Signal()
    fullscreenToggleRequested = Signal()
    cropChanged = Signal(float, float, float, float)
    cropInteractionStarted = Signal()
    cropInteractionFinished = Signal()
    colorPicked = Signal(float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._emitted_first_frame = False
        self._adjustments: dict[str, Any] = {}

    def set_image(
        self,
        image: QImage | None,
        adjustments: Mapping[str, Any] | None = None,
        *,
        image_source: object | None = None,
        reset_view: bool = True,
        force_texture_refresh: bool = False,
    ) -> None:
        del image_source, force_texture_refresh
        self._adjustments = dict(adjustments or {})
        if image is None or image.isNull():
            self.clear()
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self.clear()
            return
        if reset_view:
            try:
                self.set_zoom(1.0)
            except Exception:  # noqa: BLE001
                pass
        self.set_pixmap(pixmap)
        self._emit_first_frame()

    def set_placeholder(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self.clear()
            return
        self.set_pixmap(pixmap)
        self._emit_first_frame()

    def set_adjustments(self, adjustments: Mapping[str, Any] | None = None) -> None:
        # 嵌入软件路径：实时 shader 调色不可用；完整预览依赖 worker 烘焙图。
        self._adjustments = dict(adjustments or {})

    def set_video_frame(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    def shutdown(self) -> None:
        self.clear()

    def reset_zoom(self) -> None:
        try:
            self.set_zoom(1.0)
        except Exception:  # noqa: BLE001
            pass

    def rotate_image_ccw(self) -> dict[str, Any]:
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return {}
        transformed = pix.transformed(QTransform().rotate(-90))
        self.set_pixmap(transformed)
        return {"rotation": 90}

    def _emit_first_frame(self) -> None:
        if self._emitted_first_frame:
            return

        def _fire() -> None:
            if not self._emitted_first_frame:
                self._emitted_first_frame = True
                self.firstFrameReady.emit()

        QTimer.singleShot(0, _fire)
