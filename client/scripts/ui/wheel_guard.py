"""防止悬停滚轮误改 Slider / Combo / Spin（未聚焦时忽略滚轮）。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QWidget,
)


_WHEEL_TYPES = (QComboBox, QAbstractSlider, QAbstractSpinBox)


class WheelFocusGuard(QObject):
    """安装到 QApplication：未获得键盘焦点的控件不响应滚轮改值。"""

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Wheel and isinstance(obj, _WHEEL_TYPES):
            if not obj.hasFocus():
                event.ignore()
                return True
        return False


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
    """将根下 Combo/Slider/Spin 的焦点策略改为 StrongFocus（需点击后再用滚轮）。"""
    for w in root.findChildren(QWidget):
        if isinstance(w, _WHEEL_TYPES):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
