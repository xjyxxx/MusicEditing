"""可复用照片画布：适合窗口、滚轮缩放、按住左键平移。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QSizePolicy, QWidget


class ZoomableImageView(QWidget):
    zoomChanged = Signal(int)
    viewChanged = Signal(float, float, float)  # zoom, normalized pan x/y

    def __init__(self, source: QImage | QPixmap | None = None, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self._zoom = 1.0
        self._pan = QPointF()
        self._drag_position: QPointF | None = None
        self._message = "正在加载照片…"
        self.setMinimumSize(360, 260)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setToolTip("滚轮缩放，按住左键拖动，双击恢复适合窗口")
        if source is not None:
            self.set_image(source)

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def pan_x(self) -> float:
        return self._pan.x()

    @property
    def pan_y(self) -> float:
        return self._pan.y()

    def set_image(self, source: QImage | QPixmap) -> None:
        self._image = (source.toImage() if isinstance(source, QPixmap) else source).copy()
        self._message = ""
        self._clamp_pan()
        self.update()

    def set_message(self, text: str) -> None:
        self._message = text or ""
        self.update()
    def set_view_transform(
        self, zoom: float, pan_x: float = 0.0, pan_y: float = 0.0, *, emit: bool = False,
    ) -> None:
        old_zoom = self._zoom
        self._zoom = max(0.25, min(4.0, float(zoom)))
        self._pan = QPointF(float(pan_x), float(pan_y))
        self._clamp_pan()
        self._update_cursor()
        self.update()
        if emit:
            if abs(old_zoom - self._zoom) > 1e-6:
                self.zoomChanged.emit(round(self._zoom * 100))
            self.viewChanged.emit(self._zoom, self._pan.x(), self._pan.y())

    def reset_view(self) -> None:
        self.set_view_transform(1.0, 0.0, 0.0, emit=True)

    def _fit_size(self) -> tuple[float, float]:
        if self._image.isNull():
            return 0.0, 0.0
        scale = min(self.width() / max(1, self._image.width()),
                    self.height() / max(1, self._image.height())) * self._zoom
        return self._image.width() * scale, self._image.height() * scale

    def _clamp_pan(self) -> None:
        width, height = self._fit_size()
        max_x = max(0.0, (width - self.width()) * 0.5) / max(1, self.width())
        max_y = max(0.0, (height - self.height()) * 0.5) / max(1, self.height())
        self._pan.setX(max(-max_x, min(max_x, self._pan.x())))
        self._pan.setY(max(-max_y, min(max_y, self._pan.y())))

    def _update_cursor(self) -> None:
        width, height = self._fit_size()
        pannable = width > self.width() + 1 or height > self.height() + 1
        self.setCursor(Qt.ClosedHandCursor if self._drag_position is not None else
                       (Qt.OpenHandCursor if pannable else Qt.ArrowCursor))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#080A0E"))
        if self._image.isNull():
            painter.setPen(QColor("#A1A1A6"))
            painter.drawText(self.rect(), Qt.AlignCenter, self._message)
            return
        width, height = self._fit_size()
        x = (self.width() - width) * 0.5 + self._pan.x() * self.width()
        y = (self.height() - height) * 0.5 + self._pan.y() * self.height()
        painter.drawImage(
            QRectF(x, y, width, height), self._image,
            QRectF(0, 0, self._image.width(), self._image.height()),
        )

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta:
            factor = 1.15 if delta > 0 else 1.0 / 1.15
            self.set_view_transform(self._zoom * factor, self._pan.x(), self._pan.y(), emit=True)
            event.accept()
            return
        super().wheelEvent(event)
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            width, height = self._fit_size()
            if width > self.width() + 1 or height > self.height() + 1:
                self._drag_position = event.position()
                self._update_cursor()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_position is not None and event.buttons() & Qt.LeftButton:
            delta = event.position() - self._drag_position
            self._drag_position = event.position()
            self._pan += QPointF(delta.x() / max(1, self.width()),
                                 delta.y() / max(1, self.height()))
            self._clamp_pan()
            self.update()
            self.viewChanged.emit(self._zoom, self._pan.x(), self._pan.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._drag_position is not None:
            self._drag_position = None
            self._update_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._clamp_pan()
        self._update_cursor()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, 420)
