"""可框选多个矩形区域的图片预览控件"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


@dataclass
class ImageRegion:
    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


class RegionSelectorWidget(QLabel):
    """在图片上拖拽绘制水印区域（支持多区域）"""

    regionsChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            "background: #111; border: 1px solid #444; color: #666;"
        )
        self.setText("导入图片或视频预览帧后，在此拖拽框选水印区域")

        self._source_pixmap: QPixmap | None = None
        self._image_size = (0, 0)
        self._display_rect = QRect()
        self._regions: list[ImageRegion] = []
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None

    @property
    def image_size(self) -> tuple[int, int]:
        return self._image_size

    def regions(self) -> list[ImageRegion]:
        return list(self._regions)

    def set_regions(self, regions: list[ImageRegion]) -> None:
        self._regions = list(regions)
        self._refresh()
        self.regionsChanged.emit(self.regions())

    def clear_regions(self) -> None:
        self._regions.clear()
        self._refresh()
        self.regionsChanged.emit([])

    def load_pixmap(self, pixmap: QPixmap, image_size: tuple[int, int]) -> None:
        self._source_pixmap = pixmap
        self._image_size = image_size
        self._regions.clear()
        self._drag_start = None
        self._drag_current = None
        self._refresh()
        self.regionsChanged.emit([])

    def clear_image(self) -> None:
        self._source_pixmap = None
        self._image_size = (0, 0)
        self._regions.clear()
        self._drag_start = None
        self._drag_current = None
        self.setPixmap(QPixmap())
        self.setText("导入图片或视频预览帧后，在此拖拽框选水印区域")
        self.regionsChanged.emit([])

    def _refresh(self) -> None:
        if not self._source_pixmap or self._source_pixmap.isNull():
            return

        scaled = self._source_pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        canvas = QPixmap(scaled.size())
        canvas.fill(Qt.black)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, scaled)

        ox = (self.width() - scaled.width()) // 2
        oy = (self.height() - scaled.height()) // 2
        self._display_rect = QRect(ox, oy, scaled.width(), scaled.height())

        sx = scaled.width() / max(1, self._image_size[0])
        sy = scaled.height() / max(1, self._image_size[1])

        pen = QPen(QColor(255, 80, 80), 2)
        painter.setPen(pen)
        for r in self._regions:
            rx = int(r.x * sx)
            ry = int(r.y * sy)
            rw = max(1, int(r.w * sx))
            rh = max(1, int(r.h * sy))
            painter.drawRect(rx, ry, rw, rh)

        if self._drag_start and self._drag_current:
            rect = QRect(self._drag_start, self._drag_current).normalized()
            local = QRect(
                rect.left() - ox, rect.top() - oy,
                rect.width(), rect.height(),
            )
            painter.drawRect(local)

        painter.end()
        self.setPixmap(canvas)
        self.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _widget_to_image(self, pos: QPoint) -> tuple[int, int] | None:
        if not self._display_rect.isValid() or self._image_size[0] <= 0:
            return None
        if not self._display_rect.contains(pos):
            return None
        lx = pos.x() - self._display_rect.x()
        ly = pos.y() - self._display_rect.y()
        sx = self._image_size[0] / max(1, self._display_rect.width())
        sy = self._image_size[1] / max(1, self._display_rect.height())
        ix = int(lx * sx)
        iy = int(ly * sy)
        ix = max(0, min(self._image_size[0] - 1, ix))
        iy = max(0, min(self._image_size[1] - 1, iy))
        return ix, iy

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._source_pixmap:
            self._drag_start = event.position().toPoint()
            self._drag_current = self._drag_start
            self._refresh()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start:
            self._drag_current = event.position().toPoint()
            self._refresh()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self._drag_start or event.button() != Qt.LeftButton:
            return
        p1 = self._widget_to_image(self._drag_start)
        p2 = self._widget_to_image(self._drag_current or self._drag_start)
        self._drag_start = None
        self._drag_current = None
        if not p1 or not p2:
            self._refresh()
            return
        x1, y1 = p1
        x2, y2 = p2
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        if w >= 4 and h >= 4:
            self._regions.append(ImageRegion(x, y, w, h))
            self.regionsChanged.emit(self.regions())
        self._refresh()
