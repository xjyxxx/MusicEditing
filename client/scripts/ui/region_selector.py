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


def _corner_edge_score(img: QImage, x: int, y: int, rw: int, rh: int) -> float:
    """简单灰度梯度能量；角标/logo 通常边缘更密。"""
    w, h = img.width(), img.height()
    x2 = min(w, x + rw)
    y2 = min(h, y + rh)
    x = max(0, x)
    y = max(0, y)
    if x2 - x < 4 or y2 - y < 4:
        return 0.0
    # 降采样累加
    step = max(1, min((x2 - x) // 24, (y2 - y) // 24, 4))
    energy = 0.0
    n = 0
    prev = None
    for yy in range(y, y2, step):
        for xx in range(x, x2, step):
            c = img.pixelColor(xx, yy)
            g = (c.red() + c.green() + c.blue()) / 3.0
            if prev is not None:
                energy += abs(g - prev)
                n += 1
            prev = g
    return energy / max(1, n)


class RegionSelectorWidget(QLabel):
    """在图片上拖拽绘制水印区域（支持多区域）"""

    regionsChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            "background: #080A0E; border: 1px solid #2A3344; color: #8B95A8; border-radius: 10px;"
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

    def suggest_corner_regions(self, max_count: int = 2) -> list[ImageRegion]:
        """四角启发式：边缘/对比度较高的角标候选（可再编辑）。"""
        if not self._source_pixmap or self._source_pixmap.isNull():
            return []
        img = self._source_pixmap.toImage().convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        if w < 32 or h < 32:
            return []
        cw = max(48, min(w // 6, w // 2))
        ch = max(36, min(h // 8, h // 2))
        corners = [
            (0, 0),
            (max(0, w - cw), 0),
            (0, max(0, h - ch)),
            (max(0, w - cw), max(0, h - ch)),
        ]
        scored: list[tuple[float, ImageRegion]] = []
        for x, y in corners:
            score = _corner_edge_score(img, x, y, cw, ch)
            scored.append((score, ImageRegion(x, y, cw, ch)))
        scored.sort(key=lambda t: t[0], reverse=True)
        # 相对阈值：取最高分，以及超过其 55% 的第二角
        if not scored or scored[0][0] < 8.0:
            return []
        picked = [scored[0][1]]
        if max_count > 1 and len(scored) > 1 and scored[1][0] >= scored[0][0] * 0.55:
            picked.append(scored[1][1])
        self.set_regions(picked)
        return picked

    def apply_platform_corner_preset(self, platform: str = "douyin") -> list[ImageRegion]:
        """
        右上角标一键框选（不依赖边缘检测）。
        douyin≈宽 22%×高 10%；kuaishou≈宽 20%×高 9%。
        """
        if not self._source_pixmap or self._source_pixmap.isNull():
            return []
        w = self._source_pixmap.width()
        h = self._source_pixmap.height()
        if w < 32 or h < 32:
            return []
        key = (platform or "douyin").strip().lower()
        if key in ("kuaishou", "ks", "快手"):
            rw, rh = int(w * 0.20), int(h * 0.09)
        else:
            rw, rh = int(w * 0.22), int(h * 0.10)
        rw = max(40, min(rw, w // 2))
        rh = max(28, min(rh, h // 3))
        x = max(0, w - rw - int(w * 0.02))
        y = max(0, int(h * 0.02))
        region = ImageRegion(x, y, rw, rh)
        self.set_regions([region])
        return [region]

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
