"""波形 + 响度条可视化（showwavespic 底图 + ebur128 瞬时响度曲线）。"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QLinearGradient, QFont
from PySide6.QtWidgets import QWidget

from core.audio_viz import LoudnessSample
from ui import theme


class WaveformWidget(QWidget):
    """
    首页播放器旁/下方：波形图 + 响度曲线 + 播放头。
    点击可 seek。
    """

    seekRequested = Signal(float)  # seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0.0
        self._position = 0.0
        self._wave: Optional[QPixmap] = None
        self._samples: List[LoudnessSample] = []
        self._integrated = -70.0
        self._lra = 0.0
        self._status = "打开媒体后自动分析波形 / 响度"
        self._busy = False
        self.setMinimumHeight(64)
        self.setMaximumHeight(96)
        self.setToolTip("波形（showwavespic）+ 响度（ebur128）· 点击跳转")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"background: {theme.PLAYER_BG}; border-radius: 8px;")

    def clear(self) -> None:
        self._wave = None
        self._samples = []
        self._duration = 0.0
        self._position = 0.0
        self._integrated = -70.0
        self._lra = 0.0
        self._status = "打开媒体后自动分析波形 / 响度"
        self._busy = False
        self.update()

    def set_busy(self, busy: bool, status: str = "") -> None:
        self._busy = busy
        if status:
            self._status = status
        self.update()

    def set_duration(self, duration_sec: float) -> None:
        self._duration = max(0.0, float(duration_sec or 0.0))
        self.update()

    def set_position(self, position_sec: float) -> None:
        self._position = max(0.0, float(position_sec or 0.0))
        self.update()

    def set_waveform_png(self, path: str) -> None:
        if path:
            pix = QPixmap(path)
            self._wave = None if pix.isNull() else pix
        else:
            self._wave = None
        self.update()

    def set_loudness(
        self,
        samples: Sequence[LoudnessSample],
        *,
        integrated_lufs: float = -70.0,
        lra: float = 0.0,
    ) -> None:
        self._samples = list(samples or [])
        self._integrated = float(integrated_lufs)
        self._lra = float(lra)
        if self._samples and self._duration <= 0:
            self._duration = max(s.t for s in self._samples) + 0.1
        self._busy = False
        if self._samples:
            self._status = f"I {self._integrated:.1f} LUFS · LRA {self._lra:.1f} LU"
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self._duration <= 0:
            return super().mousePressEvent(event)
        x = event.position().x() if hasattr(event, "position") else event.x()
        ratio = max(0.0, min(1.0, float(x) / max(1.0, float(self.width()))))
        self.seekRequested.emit(ratio * self._duration)
        return super().mousePressEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(theme.PLAYER_BG))

        # 波形底图
        if self._wave and not self._wave.isNull():
            scaled = self._wave.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            p.setOpacity(0.85)
            p.drawPixmap(0, 0, scaled)
            p.setOpacity(1.0)
        else:
            # 占位渐变
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0.0, QColor(theme.SURFACE_2))
            grad.setColorAt(1.0, QColor(theme.PLAYER_BG))
            p.fillRect(0, 0, w, h, grad)

        # 响度曲线（归一化 M）
        if self._samples and self._duration > 0:
            vals = [s.momentary_lufs for s in self._samples]
            lo = min(vals)
            hi = max(vals)
            if hi - lo < 1.0:
                hi = lo + 6.0
            pen = QPen(QColor(theme.SIGNAL), 1.4)
            p.setPen(pen)
            pts: List[QPointF] = []
            for s in self._samples:
                x = (s.t / self._duration) * w
                norm = (s.momentary_lufs - lo) / (hi - lo)
                y = h - 4 - norm * (h - 10)
                pts.append(QPointF(x, y))
            for i in range(1, len(pts)):
                p.drawLine(pts[i - 1], pts[i])

            # 右侧迷你响度条：当前位置附近 M
            cur_m = self._samples[0].momentary_lufs
            for s in self._samples:
                if s.t <= self._position:
                    cur_m = s.momentary_lufs
                else:
                    break
            bar_h = max(2.0, ((cur_m - lo) / (hi - lo)) * (h - 8))
            p.fillRect(w - 6, int(h - 4 - bar_h), 4, int(bar_h), QColor(theme.ACCENT))

        # 播放头
        if self._duration > 0:
            x = int((self._position / self._duration) * w)
            p.setPen(QPen(QColor(theme.ACCENT), 1.5))
            p.drawLine(x, 0, x, h)

        # 状态字
        p.setPen(QColor(theme.TEXT_MUTED))
        font = QFont()
        font.setPixelSize(11)
        p.setFont(font)
        label = self._status
        if self._busy:
            label = "分析中… " + label
        p.drawText(8, 14, label)
        p.end()
