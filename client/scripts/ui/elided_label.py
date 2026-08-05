"""路径/长文本标签：中间省略，避免撑开整页布局。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedPathLabel(QLabel):
    """横向占位可收缩；显示中间省略，完整内容放 Tooltip。"""

    def __init__(
        self,
        text: str = "",
        *,
        object_name: str = "PathLabel",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._full = ""
        self.setObjectName(object_name)
        self.setWordWrap(False)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setText(text)

    def full_text(self) -> str:
        return self._full

    def setText(self, text: str) -> None:  # noqa: N802 — Qt API
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply_elide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_elide()

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        sh.setWidth(40)
        return sh

    def sizeHint(self):
        sh = super().sizeHint()
        # 禁止按完整路径回报宽度，否则会把窗口/Tab 整体撑向右侧
        sh.setWidth(120)
        return sh

    def _apply_elide(self) -> None:
        w = max(0, self.width() - 4)
        if w <= 8 or not self._full:
            QLabel.setText(self, self._full)
            return
        elided = self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, w)
        QLabel.setText(self, elided)
