"""防止悬停滚轮误改 Slider / Combo / Spin（未聚焦时忽略改值）。

注意：不可拦截 QScrollBar（也继承 QAbstractSlider），否则滚动条/页面滚轮失效。
未聚焦的 Combo/Slider/Spin 上滚轮应交给外层 QScrollArea，而不是整段吞掉。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDial,
    QSlider,
    QWidget,
)


# 只拦「改数值」的控件；不要用 QAbstractSlider（会连 QScrollBar 一起拦）
_WHEEL_TYPES = (QComboBox, QSlider, QAbstractSpinBox, QDial)


def _scroll_enclosing_area(widget: QWidget, event) -> bool:
    """把滚轮交给最近的 QAbstractScrollArea；成功返回 True。"""
    w = widget.parentWidget() if isinstance(widget, QWidget) else None
    while w is not None:
        if isinstance(w, QAbstractScrollArea):
            pixel = event.pixelDelta()
            angle = event.angleDelta()
            if pixel.y() or angle.y():
                bar = w.verticalScrollBar()
                if bar.isVisible() or bar.maximum() > bar.minimum():
                    dy = pixel.y() if pixel.y() else angle.y()
                    bar.setValue(bar.value() - dy)
                    return True
            if pixel.x() or angle.x():
                bar = w.horizontalScrollBar()
                if bar.isVisible() or bar.maximum() > bar.minimum():
                    dx = pixel.x() if pixel.x() else angle.x()
                    bar.setValue(bar.value() - dx)
                    return True
            return True
        w = w.parentWidget()
    return False


class WheelFocusGuard(QObject):
    """安装到 QApplication：未聚焦的 Combo/Slider/Spin 不改值，滚轮转给滚动区。"""

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() != QEvent.Type.Wheel:
            return False
        if not isinstance(obj, _WHEEL_TYPES):
            return False
        if obj.hasFocus():
            return False
        # 未聚焦：禁止改值；尽量让外层页面照常滚动
        _scroll_enclosing_area(obj, event)
        return True


def install_wheel_focus_guard(app: QApplication | None = None) -> WheelFocusGuard:
    """全局安装一次；返回 guard 以便持有引用防 GC。"""
    application = app or QApplication.instance()
    if application is None:
        raise RuntimeError("QApplication 尚未创建")
    existing = application.property("_music_wheel_focus_guard")
    if isinstance(existing, WheelFocusGuard):
        return existing
    guard = WheelFocusGuard(application)
    application.installEventFilter(guard)
    application.setProperty("_music_wheel_focus_guard", guard)
    return guard


def harden_wheel_widgets(root: QWidget) -> None:
    """将根下 Combo/Slider/Spin 的焦点策略改为 StrongFocus（需点击后再用滚轮改值）。"""
    for w in root.findChildren(QWidget):
        if isinstance(w, _WHEEL_TYPES):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
