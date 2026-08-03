"""高光片段时间轴：色块 + 片段中点缩略图（产品：缩略图+时间轴）。"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QToolTip, QWidget

from core.time_format import format_range, format_timestamp


class HighlightTimelineWidget(QWidget):
    """整段视频时间轴 + 高光区间色块 + 缩略图条；点击色块/缩略图发出 segmentClicked(index)。"""

    segmentClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0.0
        self._segments: List[tuple[float, float, float]] = []  # start, end, score
        self._thumbs: List[Optional[QPixmap]] = []
        self._selected = -1
        self._hover = -1
        self.setMinimumHeight(118)
        self.setMaximumHeight(140)
        self.setMouseTracking(True)
        self.setToolTip("高光时间轴（点击片段或缩略图可选中）")
        self.setStyleSheet("background: #080A0E; border-radius: 10px;")

    def set_duration(self, duration_sec: float) -> None:
        self._duration = max(0.0, float(duration_sec or 0.0))
        self.update()

    def set_segments(self, segments: Sequence) -> None:
        """segments: 带 start_sec / end_sec / score 的对象列表。"""
        self._segments = []
        for seg in segments:
            start = float(getattr(seg, "start_sec", 0.0) or 0.0)
            end = float(getattr(seg, "end_sec", 0.0) or 0.0)
            score = float(getattr(seg, "score", 0.0) or 0.0)
            if end > start:
                self._segments.append((start, end, score))
        self._thumbs = [None] * len(self._segments)
        # 若片段已带路径则预载
        for i, seg in enumerate(segments):
            if i >= len(self._segments):
                break
            path = getattr(seg, "thumbnail_path", "") or ""
            if path:
                self._set_thumb_at(i, path)
        self._selected = -1
        self._hover = -1
        self.update()

    def set_thumbnails(self, paths: Sequence[str]) -> None:
        """按片段顺序设置缩略图路径（PPM/PNG/JPG，QImage 可读）。"""
        n = len(self._segments)
        self._thumbs = [None] * n
        for i, path in enumerate(paths):
            if i >= n:
                break
            if path:
                self._set_thumb_at(i, path)
        self.update()

    def set_thumbnail_at(self, index: int, path: str) -> None:
        if index < 0 or index >= len(self._segments):
            return
        while len(self._thumbs) < len(self._segments):
            self._thumbs.append(None)
        self._set_thumb_at(index, path)
        self.update()

    def _set_thumb_at(self, index: int, path: str) -> None:
        pix = QPixmap(path)
        if pix.isNull():
            self._thumbs[index] = None
            return
        self._thumbs[index] = pix.scaled(
            QSize(96, 54), Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )

    def clear(self) -> None:
        self._segments.clear()
        self._thumbs.clear()
        self._selected = -1
        self._hover = -1
        self.update()

    def set_selected_index(self, index: int) -> None:
        if index == self._selected:
            return
        self._selected = index
        self.update()

    def _bar_rect(self) -> QRectF:
        m = 10.0
        top = 22.0
        h = 18.0
        return QRectF(m, top, max(1.0, self.width() - 2 * m), h)

    def _thumb_band_rect(self) -> QRectF:
        bar = self._bar_rect()
        top = bar.bottom() + 8.0
        h = max(40.0, self.height() - top - 8.0)
        return QRectF(bar.left(), top, bar.width(), h)

    def _thumb_rect(self, index: int) -> QRectF:
        if index < 0 or index >= len(self._segments) or self._duration <= 0:
            return QRectF()
        start, end, _ = self._segments[index]
        mid = (start + end) * 0.5
        band = self._thumb_band_rect()
        tw, th = 72.0, 40.0
        cx = band.left() + (mid / self._duration) * band.width()
        x = max(band.left(), min(cx - tw * 0.5, band.right() - tw))
        y = band.top() + (band.height() - th) * 0.5
        return QRectF(x, y, tw, th)

    def _index_at(self, x: float, y: float) -> int:
        # 优先点缩略图
        for i in range(len(self._segments) - 1, -1, -1):
            if self._thumb_rect(i).contains(x, y):
                return i
        bar = self._bar_rect()
        if self._duration <= 0 or not bar.contains(x, y):
            return -1
        t = (x - bar.left()) / bar.width() * self._duration
        for i in range(len(self._segments) - 1, -1, -1):
            start, end, _ = self._segments[i]
            if start <= t <= end:
                return i
        return -1

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        font = QFont(painter.font())
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QColor(150, 150, 170))
        dur_txt = format_timestamp(self._duration) if self._duration > 0 else "0:00"
        painter.drawText(10, 14, "0:00")
        tw = painter.fontMetrics().horizontalAdvance(dur_txt)
        painter.drawText(self.width() - 10 - tw, 14, dur_txt)
        if self._segments:
            mid = f"{len(self._segments)} 段"
            mw = painter.fontMetrics().horizontalAdvance(mid)
            painter.drawText((self.width() - mw) // 2, 14, mid)

        bar = self._bar_rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(40, 40, 58))
        painter.drawRoundedRect(bar, 4, 4)

        if self._duration <= 0:
            painter.setPen(QColor(100, 100, 120))
            painter.drawText(bar, Qt.AlignCenter, "导入视频并分析后显示时间轴")
            painter.end()
            return

        painter.setPen(QPen(QColor(70, 70, 90), 1))
        n_ticks = 4 if self.width() < 400 else 8
        for i in range(n_ticks + 1):
            tx = bar.left() + bar.width() * i / n_ticks
            painter.drawLine(int(tx), int(bar.top()), int(tx), int(bar.bottom()))

        for i, (start, end, score) in enumerate(self._segments):
            x0 = bar.left() + (start / self._duration) * bar.width()
            x1 = bar.left() + (end / self._duration) * bar.width()
            w = max(3.0, x1 - x0)
            rect = QRectF(x0, bar.top() + 2, w, bar.height() - 4)
            t = max(0.0, min(1.0, score if score > 1.0 else score))
            if score <= 1.0:
                base = 80 + int(100 * t)
            else:
                base = 140
            if i == self._selected:
                color = QColor(120, 180, 255, 230)
            elif i == self._hover:
                color = QColor(100, 160, 240, 200)
            else:
                color = QColor(90, 100, base + 40, 200)
            painter.setBrush(color)
            painter.setPen(QPen(QColor(200, 210, 255, 80), 1))
            painter.drawRoundedRect(rect, 3, 3)

        # 缩略图条
        band = self._thumb_band_rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(28, 28, 40))
        painter.drawRoundedRect(band, 4, 4)
        if not self._segments:
            painter.setPen(QColor(100, 100, 120))
            painter.drawText(band, Qt.AlignCenter, "暂无片段")
        else:
            for i in range(len(self._segments)):
                r = self._thumb_rect(i)
                painter.setBrush(QColor(35, 35, 50))
                pen = QPen(QColor(120, 180, 255) if i == self._selected else QColor(70, 70, 95), 2 if i == self._selected else 1)
                painter.setPen(pen)
                painter.drawRoundedRect(r, 3, 3)
                thumb = self._thumbs[i] if i < len(self._thumbs) else None
                if thumb and not thumb.isNull():
                    tr = QRectF(
                        r.left() + 2, r.top() + 2,
                        r.width() - 4, r.height() - 4,
                    )
                    painter.drawPixmap(tr.toRect(), thumb)
                else:
                    painter.setPen(QColor(110, 110, 130))
                    painter.drawText(r, Qt.AlignCenter, f"#{i + 1}")

        painter.end()

    def mouseMoveEvent(self, event) -> None:
        idx = self._index_at(event.position().x(), event.position().y())
        if idx != self._hover:
            self._hover = idx
            self.update()
        if idx >= 0:
            start, end, score = self._segments[idx]
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"#{idx + 1}  {format_range(start, end)}  ·  得分 {score:.2f}",
                self,
            )
        else:
            QToolTip.hideText()

    def leaveEvent(self, event) -> None:
        if self._hover != -1:
            self._hover = -1
            self.update()
        QToolTip.hideText()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            idx = self._index_at(event.position().x(), event.position().y())
            if idx >= 0:
                self.set_selected_index(idx)
                self.segmentClicked.emit(idx)
        super().mousePressEvent(event)
