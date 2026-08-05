"""加权热评/弹幕层（右→左），可叠在播放器画面上。"""

from __future__ import annotations

import random
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from core.netease_comments import HotComment
from ui.theme import ACCENT

# 弹幕显示区域（相对画面高度，自顶部向下）
AREA_FULL = "full"
AREA_HALF = "half"
AREA_QUARTER = "quarter"
_AREA_RATIO = {
    AREA_FULL: 1.0,
    AREA_HALF: 0.5,
    AREA_QUARTER: 0.25,
}


class _Barrage:
    __slots__ = ("label", "base_speed", "opacity", "fade_in", "effect")

    def __init__(self, label: QLabel, base_speed: float, effect: QGraphicsOpacityEffect):
        self.label = label
        self.base_speed = base_speed
        self.opacity = 0.2
        self.fade_in = True
        self.effect = effect


class CommentMarquee(QWidget):
    """加权弹幕（右→左）；支持速度、密度、全屏/半屏/四分之一区域。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self._comments: List[HotComment] = []
        self._items: List[_Barrage] = []
        self._lane_y: List[int] = [16, 48, 80]
        self._speed_scale = 1.0
        self._density = 1.0
        self._area_mode = AREA_FULL
        self._paused = False
        self._emit_idx = 0
        self._max_liked = 1

        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)
        self._spawn = QTimer(self)
        self._spawn.setInterval(1800)
        self._spawn.timeout.connect(self._spawn_one)

    def set_comments(self, comments: List[HotComment]):
        self.stop()
        self._comments = [c for c in comments if c.display_text()]
        self._emit_idx = 0
        self._max_liked = max((c.liked_count for c in self._comments), default=1) or 1
        self._rebuild_lanes()
        self._apply_spawn_interval()
        if self._comments:
            self._spawn_one()
            if not self._paused:
                self._spawn.start()
                self._timer.start()

    def spawn_comment(self, comment: HotComment):
        if not comment or not comment.display_text():
            return
        self._spawn_one(forced=comment)
        if not self._paused and not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._spawn.stop()
        self._timer.stop()
        for b in self._items:
            b.label.deleteLater()
        self._items.clear()

    def pause(self):
        self._paused = True
        self._spawn.stop()
        self._timer.stop()

    def resume(self):
        self._paused = False
        if self._comments:
            self._apply_spawn_interval()
            self._spawn.start()
            self._timer.start()

    def set_speed(self, scale: float):
        """弹幕横向速度倍率（约 0.4～2.5），飞行中即时生效。"""
        self._speed_scale = max(0.4, min(2.5, float(scale)))

    def set_density(self, density: float):
        """弹幕密度（约 0.4～2.5）；越高生成越密、同屏越多。"""
        self._density = max(0.4, min(2.5, float(density)))
        self._apply_spawn_interval()
        self._rebuild_lanes()

    def set_area_mode(self, mode: str):
        """显示区域：full / half / quarter（自画面顶部向下）。"""
        key = (mode or AREA_FULL).strip().lower()
        if key not in _AREA_RATIO:
            key = AREA_FULL
        if key == self._area_mode:
            self._rebuild_lanes()
            return
        self._area_mode = key
        self._rebuild_lanes()
        limit = self._area_bottom()
        kept: List[_Barrage] = []
        for b in self._items:
            if b.label.y() + b.label.height() <= limit + 4:
                kept.append(b)
            else:
                b.label.deleteLater()
        self._items = kept

    def area_mode(self) -> str:
        return self._area_mode

    def speed_scale(self) -> float:
        return self._speed_scale

    def density(self) -> float:
        return self._density

    def _area_ratio(self) -> float:
        return _AREA_RATIO.get(self._area_mode, 1.0)

    def _area_bottom(self) -> int:
        return max(36, int(self.height() * self._area_ratio()))

    def _apply_spawn_interval(self):
        base = 2000.0 / self._density
        self._spawn.setInterval(int(max(350, min(4200, base))))

    def _rebuild_lanes(self):
        area_h = self._area_bottom()
        n_base = max(3, min(10, area_h // 28))
        n = max(3, min(12, int(round(n_base * (0.7 + 0.5 * self._density)))))
        pad = 8
        span = max(1, area_h - 28 - pad)
        self._lane_y = [pad + int(span * i / max(1, n - 1)) for i in range(n)]

    def _weight(self, c: HotComment) -> float:
        return min(1.0, (c.liked_count or 0) / float(self._max_liked))

    def _style_for(self, weight: float) -> tuple[str, int]:
        if weight >= 0.66:
            pt = 15
            qss = (
                f"color: #FFF8EE; background: rgba(18,14,8,210);"
                f"border: 1px solid {ACCENT}; border-radius: 10px;"
                f"padding: 6px 14px; font-weight: 700;"
            )
        elif weight >= 0.33:
            pt = 13
            qss = (
                "color: #F0F3F8; background: rgba(8,10,14,185);"
                "border: 1px solid #4A566C; border-radius: 9px;"
                "padding: 5px 12px; font-weight: 600;"
            )
        else:
            pt = 12
            qss = (
                "color: #C8D0DC; background: rgba(8,10,14,150);"
                "border: 1px solid #343C4C; border-radius: 8px;"
                "padding: 4px 10px;"
            )
        return qss, pt

    def _max_on_screen(self) -> int:
        # 收紧同屏数量，避免高密度时上百 QLabel.move 拖垮 UI
        return max(6, min(22, int(10 * self._density + 4 * self._area_ratio())))

    def _spawn_one(self, forced: Optional[HotComment] = None):
        if not self._comments and forced is None:
            return
        # 达上限则不再新建 QLabel，减轻主线程负担
        if forced is None and len(self._items) >= self._max_on_screen():
            return
        c = forced if forced is not None else self._comments[self._emit_idx % len(self._comments)]
        if forced is None:
            self._emit_idx += 1

        w = self._weight(c)
        qss, pt = self._style_for(w)
        text = c.display_text()
        if w >= 0.66 and c.liked_count:
            text = f"{text}  ·♥{c.liked_count}"
        lbl = QLabel(text, self)
        lbl.setStyleSheet(qss)
        f = QFont("Microsoft YaHei UI")
        f.setPointSize(pt)
        if w >= 0.66:
            f.setBold(True)
        lbl.setFont(f)
        lbl.adjustSize()
        if lbl.width() > max(280, self.width() - 40):
            lbl.setFixedWidth(max(280, self.width() - 40))
            lbl.setWordWrap(False)

        if not self._lane_y:
            self._rebuild_lanes()
        lane = random.randrange(len(self._lane_y))
        y = self._lane_y[lane]
        lbl.move(self.width() + 12, y)
        eff = QGraphicsOpacityEffect(lbl)
        eff.setOpacity(0.15)
        lbl.setGraphicsEffect(eff)
        lbl.show()

        base_speed = 2.0 + w * 2.4 + random.uniform(-0.35, 0.55)
        self._items.append(_Barrage(lbl, base_speed, eff))

        while len(self._items) > self._max_on_screen():
            old = self._items.pop(0)
            old.label.deleteLater()

    def _tick(self):
        if self._paused:
            return
        alive: List[_Barrage] = []
        for b in self._items:
            if b.fade_in and b.opacity < 1.0:
                b.opacity = min(1.0, b.opacity + 0.12)
                b.effect.setOpacity(b.opacity)
                if b.opacity >= 1.0:
                    b.fade_in = False
            x = b.label.x() - (b.base_speed * self._speed_scale)
            if x + b.label.width() < -24:
                b.label.deleteLater()
                continue
            b.label.move(int(x), b.label.y())
            alive.append(b)
        self._items = alive

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_lanes()
